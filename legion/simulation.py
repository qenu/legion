"""ATB combat simulation for dungeon runs.

DB access happens ONLY in the async builders (`build_player_state`,
`build_mob_state`), which snapshot everything into dataclasses. The fight
itself (`run_simulation`) is pure and synchronous: deterministic given the
same states and RNG seed, unit-testable without a database, and never
persisted -- a bot restart voids the run.

Flow: builders -> run_simulation -> SimulationResult.to_results() ->
SettlementService.settle().
"""

import random
import time
from dataclasses import dataclass, field

from maki.cogs.legion.calculator import (
    eval_formula,
    get_def_bonus,
    get_hp_bonus,
    get_mob_stats,
    tier_multiplier,
)
from maki.cogs.legion.constants import (
    ATB_THRESHOLD,
    BLEED_DURATION,
    ContentStatus,
    DEATH_HP,
    POISON_DURATION,
    POISON_PCT_MAX_HP,
    BURN_DURATION,
    BURN_DOUBLE_CHANCE,
    FREEZE_DURATION,
    FREEZE_SKIP_CHANCE,
    HP_AGGRO_WEIGHT,
    PLAYER_BASE_ATK,
    PLAYER_BASE_DEF,
    PLAYER_BASE_SPEED,
    PLAYER_BASE_TAUNT,
    SIM_MAX_TICKS,
    TAUNT_AGGRO_WEIGHT,
    EffectType,
    RequirementType,
    StatBonusType,
    WeaponSlot,
)
from maki.cogs.legion.model.model import (
    ActiveSkill,
    Mob,
    MobPassive,
    MobSkill,
    Player,
    PlayerWeapon,
    WeaponActiveSkill,
    WeaponMastery,
    WeaponPassiveSkill,
)
from maki.cogs.legion.settlement import ParticipantResult
from maki.cogs.legion.strings import MYSELF_TITLE
from maki.cogs.legion.content import PATCH


def _category_bonuses() -> dict[str, list[tuple[int, str, int]]]:
    """Weapon-category mastery stat bonuses from content, keyed by category
    key -> list of ``(unlock_level, stat_bonus_type, value)``. A player gets
    every entry whose level is at or below their mastery in that category."""
    out: dict[str, list[tuple[int, str, int]]] = {}
    for c in PATCH.get("categories", []):
        rows = c.get("bonus_stat")
        if rows:
            out[c["key"]] = [
                (int(b["level"]), b["stat_bonus_type"], int(b["value"])) for b in rows
            ]
    return out


# --- runtime state ----------------------------------------------------------


@dataclass
class LoadedSkill:
    """An active skill snapshotted into the fight. The formula resolves at
    USE time against the actor's live stats; ``scale`` folds tier multiplier
    and craft mutation together."""

    skill: ActiveSkill
    cooldown: int  # the actor's own turns (0 = usable every turn)
    formula: str = "0"  # e.g. "{atk} + 12" -- see calculator.eval_formula
    scale: float = 1.0  # tier% * mutation% / 10000
    hp_threshold: float = 1.0  # mob-only gate: usable when hp ratio <= this


@dataclass
class DoT:
    dmg_per_round: int
    rounds_left: int
    source: "Combatant"  # gets damage_dealt credit for each round's tick
    label: str = "bleed"  # DoT flavor -> event kinds: "{label}_tick" / "{label}_effect"
    pct_max_hp: float = 0.0  # poison: bonus = pct * victim.max_hp per round
    double_chance: float = 0.0  # burn: chance the round's damage is doubled


@dataclass
class Combatant:
    name: str
    max_hp: int
    current_hp: int
    atk: int
    def_: int
    speed: int

    taunt: int = 0  # aggro pull; only read for mob target weighting (players)
    skills: list[LoadedSkill] = field(default_factory=list)
    cooldowns: dict[int, int] = field(
        default_factory=dict
    )  # skill id -> ready at own-turn N
    turns_taken: int = 0

    gauge: int = 0
    stun_rounds: int = 0  # missed turn-opportunities left (rounds, not ticks)
    freeze_rounds: int = 0  # turns still under freeze (each has a chance to skip)
    dots: list[DoT] = field(default_factory=list)

    damage_dealt: int = 0
    damage_taken: int = 0
    healing_done: int = 0

    @property
    def alive(self) -> bool:
        return self.current_hp > 0

    @property
    def hp_ratio(self) -> float:
        return self.current_hp / self.max_hp if self.max_hp else 0.0


@dataclass
class PlayerState(Combatant):
    player: Player = None  # type: ignore[assignment]
    regen_bonus: int = 0  # HP/min from equipped REGEN passives (out-of-combat)


@dataclass
class PassiveRequirement:
    passive: MobPassive
    requirement_type: RequirementType
    requirement_value: float
    activated: bool = False


@dataclass
class MobState(Combatant):
    mob: Mob = None  # type: ignore[assignment]
    rounds_limit: int = 10  # the doom clock: fight ends at the mob's Nth action
    active_passives: list[MobPassive] = field(default_factory=list)
    pending_requirements: list[PassiveRequirement] = field(default_factory=list)


@dataclass
class BattleContext:
    tick: int = 0
    round: int = 0  # increments each mob action
    dead_player_count: int = 0


@dataclass
class CombatEvent:
    tick: int
    round: int  # 1-based; round r ends with the mob's rth action
    actor: str
    kind: str  # "skill" | "attack" | "heal" | "stun" | "stunned" | "bleed" | "death" | "passive" | "bleed_tick"
    target: str | None = None
    value: int = 0
    detail: str = ""  # skill/passive name


@dataclass
class SimulationResult:
    won: bool
    ticks: int
    rounds: int  # mob turns taken (replay chapters)
    rounded_out: bool  # mob survived its rounds_limit -> FAILED
    party: list[PlayerState]
    mob: MobState
    events: list[CombatEvent]

    def to_results(self) -> list[ParticipantResult]:
        return [
            ParticipantResult(
                player=ps.player,
                damage_dealt=ps.damage_dealt,
                damage_taken=ps.damage_taken,
                died=not ps.alive,
                final_hp=ps.current_hp if ps.alive else DEATH_HP,
                max_hp=ps.max_hp,
            )
            for ps in self.party
        ]


# --- builders (the only DB access) ------------------------------------------


async def build_player_state(player: Player, legion_level: int = 0) -> PlayerState:
    """Snapshot a player into combat state: base stats + legion defensive
    perks (the player's OWN legion's level -- perks travel with them) +
    passive bonuses from unlocked passives on equipped weapons; actives in
    priority order (main before sub, higher tier first)."""
    mastery_levels = {
        m.category_id: m.level for m in await WeaponMastery.filter(player=player)
    }

    max_hp = player.max_health_points + get_hp_bonus(legion_level)
    atk, def_, speed = (
        PLAYER_BASE_ATK,
        PLAYER_BASE_DEF + get_def_bonus(legion_level),
        PLAYER_BASE_SPEED,
    )
    taunt = PLAYER_BASE_TAUNT
    regen_bonus = 0  # summed from equipped REGEN passives; read out-of-combat
    # Passive formulas evaluate against BASE stats (before any passive
    # applies) -- no ordering dependence, no self-compounding.
    base_stats = {
        "atk": atk,
        "attack": atk,
        "def": def_,
        "defense": def_,
        "speed": speed,
        "hp": player.health_points,
        "max_hp": max_hp,
        "taunt": taunt,
    }
    skills: list[LoadedSkill] = []
    equipped_cats: dict[str, int] = {}  # category key -> mastery level (deduped)

    for slot in (WeaponSlot.MAIN, WeaponSlot.SUB):
        pw = await PlayerWeapon.get_or_none(
            player=player, equipped_slot=slot
        ).prefetch_related("weapon__category")
        if pw is None:
            continue
        level = mastery_levels.get(pw.weapon.category_id, 0)
        equipped_cats[pw.weapon.category.key] = level
        muts: dict[str, int] = pw.mutations or {}

        actives = (
            await WeaponActiveSkill.filter(
                weapon=pw.weapon,
                mastery_level_required__lte=level,
                active_skill__status=ContentStatus.ENABLED,  # disabled = pulled from combat
            )
            .order_by("-tier")
            .prefetch_related("active_skill")
        )
        skills += [
            LoadedSkill(
                skill=a.active_skill,
                cooldown=a.active_skill.cooldown,
                formula=a.active_skill.effect_value,
                scale=(
                    tier_multiplier(a.tier)
                    * (muts.get(str(a.active_skill_id)) or 100)
                    / 10000
                ),
            )
            for a in actives
        ]

        passives = await WeaponPassiveSkill.filter(
            weapon=pw.weapon,
            mastery_level_required__lte=level,
            passive_skill__status=ContentStatus.ENABLED,
        ).prefetch_related("passive_skill")
        for p in passives:
            bonus = p.passive_skill
            value = round(
                eval_formula(bonus.stat_bonus_value, base_stats)
                * tier_multiplier(p.tier)
                * (muts.get(str(p.passive_skill_id)) or 100)
                / 10000
            )
            if bonus.stat_bonus_type == StatBonusType.HP:
                max_hp += value
            elif bonus.stat_bonus_type == StatBonusType.ATK:
                atk += value
            elif bonus.stat_bonus_type == StatBonusType.DEF:
                def_ += value
            elif bonus.stat_bonus_type == StatBonusType.SPEED:
                speed += value
            elif bonus.stat_bonus_type == StatBonusType.TAUNT:
                taunt += value
            elif bonus.stat_bonus_type == StatBonusType.REGEN:
                regen_bonus += value

    # Weapon-category mastery bonuses: applied ONCE per equipped category (a
    # dual-wield of the same type doesn't double them), for every unlock at or
    # below that category's mastery level.
    cat_bonuses = _category_bonuses()
    for cat_key, mlevel in equipped_cats.items():
        for unlock, stype, val in cat_bonuses.get(cat_key, []):
            if unlock > mlevel:
                continue
            if stype == StatBonusType.HP:
                max_hp += val
            elif stype == StatBonusType.ATK:
                atk += val
            elif stype == StatBonusType.DEF:
                def_ += val
            elif stype == StatBonusType.SPEED:
                speed += val
            elif stype == StatBonusType.TAUNT:
                taunt += val

    # Timed food stat-buffs (atk/def/speed/taunt) still within their window.
    now_epoch = time.time()
    for stype, buff in (player.stat_buffs or {}).items():
        if not isinstance(buff, dict) or buff.get("until", 0) <= now_epoch:
            continue
        val = int(buff.get("value", 0))
        if stype == StatBonusType.ATK:
            atk += val
        elif stype == StatBonusType.DEF:
            def_ += val
        elif stype == StatBonusType.SPEED:
            speed += val
        elif stype == StatBonusType.TAUNT:
            taunt += val

    return PlayerState(
        name=player.username,
        max_hp=max_hp,
        current_hp=min(player.health_points, max_hp),  # persistent HP carries in
        atk=atk,
        def_=def_,
        speed=speed,
        taunt=taunt,
        skills=skills,
        player=player,
        regen_bonus=regen_bonus,
    )


async def effective_max_hp(player: Player, legion_level: int) -> int:
    """THE max HP: base + legion bonus + equipped HP passives (mutated).
    Implemented via build_player_state so combat and out-of-combat can never
    drift apart. Future combat-only HP-boost skills must inflate a separate
    field, NOT this -- settlement slices back to this anchor."""
    return (await build_player_state(player, legion_level)).max_hp


async def effective_max_hp_and_regen(
    player: Player, legion_level: int
) -> tuple[int, int]:
    """One build -> (effective max HP, passive REGEN bonus HP/min). Lets the
    interceptor fetch both without building the player state twice."""
    state = await build_player_state(player, legion_level)
    return state.max_hp, state.regen_bonus


async def build_mob_state(mob: Mob, danger: int, player_count: int) -> MobState:
    """Snapshot a mob: stats scaled by the hunting ground's danger + party
    size, loadout, and passives split into always-active (applied now) and
    pending (checked per tick)."""
    stats = get_mob_stats(mob, danger, player_count)

    skills = [
        LoadedSkill(
            skill=ms.skill,
            cooldown=ms.cooldown,
            formula=ms.skill.effect_value,  # mobs: no tier/mutation scaling
            hp_threshold=ms.hp_threshold,
        )
        for ms in await MobSkill.filter(
            mob=mob, skill__status=ContentStatus.ENABLED
        ).prefetch_related("skill")
    ]

    state = MobState(
        name=mob.name,
        max_hp=stats["hp"],
        current_hp=stats["hp"],
        atk=stats["atk"],
        def_=stats["def"],
        speed=stats["speed"],
        skills=skills,
        mob=mob,
        rounds_limit=mob.rounds_limit,
    )

    for passive in await MobPassive.filter(
        mob=mob, skill__status=ContentStatus.ENABLED
    ).prefetch_related("skill"):
        if passive.requirement_type is None:
            state.active_passives.append(passive)
            _apply_mob_passive(state, passive)
        else:
            state.pending_requirements.append(
                PassiveRequirement(
                    passive=passive,
                    requirement_type=passive.requirement_type,
                    requirement_value=passive.requirement_value or 0.0,
                )
            )
    return state


def _apply_mob_passive(state: MobState, passive: MobPassive) -> None:
    bonus = passive.skill
    value = eval_formula(bonus.stat_bonus_value, _stats_of(state))
    if bonus.stat_bonus_type == StatBonusType.HP:
        state.max_hp += value
        state.current_hp += value
    elif bonus.stat_bonus_type == StatBonusType.ATK:
        state.atk += value
    elif bonus.stat_bonus_type == StatBonusType.DEF:
        state.def_ += value
    elif bonus.stat_bonus_type == StatBonusType.SPEED:
        state.speed += value
    elif bonus.stat_bonus_type == StatBonusType.TAUNT:
        state.taunt += value


def _stats_of(c: Combatant) -> dict:
    """Formula variables exposed to skill/passive expressions."""
    return {
        "atk": c.atk,
        "attack": c.atk,
        "def": c.def_,
        "defense": c.def_,
        "speed": c.speed,
        "hp": c.current_hp,
        "max_hp": c.max_hp,
        "taunt": c.taunt,
    }


def _skill_value(loaded: LoadedSkill, actor: Combatant) -> int:
    """Resolve a skill's formula against the actor's LIVE stats, then apply
    the tier+mutation scale."""
    return max(0, round(eval_formula(loaded.formula, _stats_of(actor)) * loaded.scale))


# --- the fight ---------------------------------------------------------------


def _check_requirements(
    mob: MobState, ctx: BattleContext, events: list[CombatEvent]
) -> None:
    for req in mob.pending_requirements:
        if req.activated:
            continue
        met = (
            (
                req.requirement_type == RequirementType.HP_BELOW
                and mob.hp_ratio <= req.requirement_value
            )
            or (
                req.requirement_type == RequirementType.PLAYER_DEAD
                and ctx.dead_player_count >= req.requirement_value
            )
            or (
                req.requirement_type == RequirementType.ROUND
                and ctx.round >= req.requirement_value
            )
        )
        if met:
            req.activated = True
            mob.active_passives.append(req.passive)
            _apply_mob_passive(mob, req.passive)
            events.append(
                CombatEvent(
                    tick=ctx.tick,
                    round=ctx.round + 1,
                    actor=mob.name,
                    kind="passive",
                    detail=req.passive.skill.name,
                )
            )


def _deal_damage(
    attacker: Combatant,
    target: Combatant,
    raw: int,
    ctx: BattleContext,
    events: list[CombatEvent],
    kind: str,
    detail: str = "",
) -> None:
    dmg = max(1, raw - target.def_)
    target.current_hp = max(0, target.current_hp - dmg)
    attacker.damage_dealt += dmg
    target.damage_taken += dmg
    events.append(
        CombatEvent(
            tick=ctx.tick,
            round=ctx.round + 1,
            actor=attacker.name,
            kind=kind,
            target=target.name,
            value=dmg,
            detail=detail,
        )
    )
    if not target.alive:
        events.append(
            CombatEvent(
                tick=ctx.tick, round=ctx.round + 1, actor=target.name, kind="death"
            )
        )
        if isinstance(target, PlayerState):
            ctx.dead_player_count += 1


def _use_skill(
    actor: Combatant,
    loaded: LoadedSkill,
    enemy: Combatant,
    allies: list[Combatant],
    ctx: BattleContext,
    events: list[CombatEvent],
) -> None:
    skill = loaded.skill
    # Cooldowns count the actor's own turns: ready again once the actor has
    # taken `cooldown` more turns (0 = every turn, 1 = next turn is fine).
    actor.cooldowns[skill.id] = actor.turns_taken + loaded.cooldown

    # Formula resolves against LIVE stats; it fully owns any ATK scaling
    # (write "{atk} + 12" for the old base-attack behavior).
    value = _skill_value(loaded, actor)
    if skill.effect_type == EffectType.DAMAGE:
        _deal_damage(
            actor,
            enemy,
            value,
            ctx,
            events,
            kind="skill",
            detail=skill.name,
        )
    elif skill.effect_type == EffectType.HEAL:
        target = min((a for a in allies if a.alive), key=lambda a: a.hp_ratio)
        healed = min(value, target.max_hp - target.current_hp)
        target.current_hp += healed
        actor.healing_done += healed  # the HEALER gets the credit
        # Relabel only THIS event's target (avoid "Alice heals Alice"); never
        # mutate the combatant's name -- that would stick for all later events.
        target_name = MYSELF_TITLE if actor is target else target.name
        events.append(
            CombatEvent(
                tick=ctx.tick,
                round=ctx.round + 1,
                actor=actor.name,
                kind="heal",
                target=target_name,
                value=healed,
                detail=skill.name,
            )
        )
    elif skill.effect_type == EffectType.STUN:
        # Stun is measured in ROUNDS: the target misses that many of its own
        # turn-opportunities. When the MOB stuns a player, its current action
        # is about to close this round (which would instantly eat one stack),
        # so it grants +1 to deliver the full duration.
        rounds = value + (1 if isinstance(actor, MobState) else 0)
        enemy.stun_rounds = max(enemy.stun_rounds, rounds)
        events.append(
            CombatEvent(
                tick=ctx.tick,
                round=ctx.round + 1,
                actor=actor.name,
                kind="stun",
                target=enemy.name,
                value=value,
                detail=skill.name,
            )
        )
    elif skill.effect_type == EffectType.BLEED:
        enemy.dots.append(DoT(value, BLEED_DURATION, actor))
        events.append(
            CombatEvent(
                tick=ctx.tick,
                round=ctx.round + 1,
                actor=actor.name,
                kind="bleed",
                target=enemy.name,
                value=value,
                detail=skill.name,
            )
        )
    elif skill.effect_type == EffectType.POISON:
        # Poison: base DoT + an extra 1% of the victim's max HP each round.
        enemy.dots.append(
            DoT(
                value,
                POISON_DURATION,
                actor,
                label="poison",
                pct_max_hp=POISON_PCT_MAX_HP,
            )
        )
        events.append(
            CombatEvent(
                tick=ctx.tick,
                round=ctx.round + 1,
                actor=actor.name,
                kind="poison",
                target=enemy.name,
                value=value,
                detail=skill.name,
            )
        )
    elif skill.effect_type == EffectType.BURN:
        # Burn: base DoT that has a 30% chance each round to deal double.
        enemy.dots.append(
            DoT(
                value,
                BURN_DURATION,
                actor,
                label="burn",
                double_chance=BURN_DOUBLE_CHANCE,
            )
        )
        events.append(
            CombatEvent(
                tick=ctx.tick,
                round=ctx.round + 1,
                actor=actor.name,
                kind="burn",
                target=enemy.name,
                value=value,
                detail=skill.name,
            )
        )
    elif skill.effect_type == EffectType.FREEZE:
        # Freeze: base DoT (like the others) that ALSO lingers as a status --
        # each of the victim's next turns has a chance to be skipped (resolved
        # in the turn loop as the freeze_effect).
        enemy.dots.append(DoT(value, FREEZE_DURATION, actor, label="freeze"))
        enemy.freeze_rounds = max(enemy.freeze_rounds, FREEZE_DURATION)
        events.append(
            CombatEvent(
                tick=ctx.tick,
                round=ctx.round + 1,
                actor=actor.name,
                kind="freeze",
                target=enemy.name,
                value=value,
                detail=skill.name,
            )
        )


def _player_act(
    ps: PlayerState,
    mob: MobState,
    party: list[PlayerState],
    ctx: BattleContext,
    events: list[CombatEvent],
) -> None:
    """EVERY off-cooldown skill fires this turn (cooldowns are the only
    pacing; tier no longer orders a priority rotation -- it scales values).
    Basic attack only when nothing else fired."""
    fired = False
    for loaded in ps.skills:
        if not mob.alive:
            break
        if ps.cooldowns.get(loaded.skill.id, 0) <= ps.turns_taken:
            _use_skill(ps, loaded, mob, list(party), ctx, events)
            fired = True
    if not fired and mob.alive:
        _deal_damage(ps, mob, ps.atk, ctx, events, kind="attack")
    ps.turns_taken += 1


def _pick_target(targets: list[PlayerState], rng: random.Random) -> PlayerState:
    """Aggro-weighted target roll: pull = HP_AGGRO_WEIGHT * max_hp +
    TAUNT_AGGRO_WEIGHT * taunt. Higher-HP and higher-taunt players are hit more
    often; re-rolled every mob turn (no sticky focus-fire)."""
    weights = [
        max(
            1.0,
            HP_AGGRO_WEIGHT * t.max_hp + TAUNT_AGGRO_WEIGHT * t.taunt,
        )
        for t in targets
    ]
    return rng.choices(targets, weights=weights, k=1)[0]


def _mob_act(
    mob: MobState,
    party: list[PlayerState],
    ctx: BattleContext,
    events: list[CombatEvent],
    rng: random.Random,
) -> None:
    targets = [p for p in party if p.alive]
    if not targets:
        return
    usable = [
        ls
        for ls in mob.skills
        if mob.hp_ratio <= ls.hp_threshold
        and mob.cooldowns.get(ls.skill.id, 0) <= mob.turns_taken
    ]
    if usable:
        loaded = rng.choice(usable)
        _use_skill(mob, loaded, _pick_target(targets, rng), [mob], ctx, events)
    else:
        _deal_damage(
            mob, _pick_target(targets, rng), mob.atk, ctx, events, kind="attack"
        )
    mob.turns_taken += 1
    # The mob's action CLOSES the round (its events above are stamped with the
    # round in progress); the doom clock advances here. Player stuns are
    # denominated in completed rounds, so they wear down at the close too.
    ctx.round += 1
    for p in party:
        if p.stun_rounds > 0:
            p.stun_rounds -= 1


def _dot_hurt(
    combatant: Combatant,
    source: Combatant,
    dmg: int,
    kind: str,
    ctx: BattleContext,
    events: list[CombatEvent],
) -> None:
    """Apply one chunk of DoT damage, credit the source, and log it."""
    if dmg <= 0:
        return
    combatant.current_hp = max(0, combatant.current_hp - dmg)
    combatant.damage_taken += dmg
    source.damage_dealt += dmg
    events.append(
        CombatEvent(
            tick=ctx.tick,
            round=ctx.round + 1,
            actor=combatant.name,
            kind=kind,
            value=dmg,
        )
    )


def _apply_dots(
    combatant: Combatant,
    ctx: BattleContext,
    events: list[CombatEvent],
    rng: random.Random,
) -> None:
    for dot in combatant.dots:
        if not combatant.alive:
            break
        # Base tick (from effect_value), then the status's special bonus.
        _dot_hurt(
            combatant,
            dot.source,
            dot.dmg_per_round,
            f"{dot.label}_tick",
            ctx,
            events,
        )
        if combatant.alive:
            bonus = 0
            if dot.pct_max_hp:  # poison: +% max HP
                bonus = max(1, int(combatant.max_hp * dot.pct_max_hp))
            elif dot.double_chance and rng.random() < dot.double_chance:
                bonus = dot.dmg_per_round  # burn: doubled -> +base
            _dot_hurt(
                combatant,
                dot.source,
                bonus,
                f"{dot.label}_effect",
                ctx,
                events,
            )
        dot.rounds_left -= 1
        if not combatant.alive:
            events.append(
                CombatEvent(
                    tick=ctx.tick,
                    round=ctx.round + 1,
                    actor=combatant.name,
                    kind="death",
                )
            )
            if isinstance(combatant, PlayerState):
                ctx.dead_player_count += 1
    combatant.dots = [b for b in combatant.dots if b.rounds_left > 0]


def run_simulation(
    party: list[PlayerState], mob: MobState, rng: random.Random | None = None
) -> SimulationResult:
    """Run the fight to completion. Pure: no DB, no awaits, no wall clock."""
    rng = rng or random.Random()
    ctx = BattleContext()
    events: list[CombatEvent] = []

    # Everyone enters combat with their cooldowns RUNNING: a cd-N skill first
    # fires after the owner's Nth turn (cd 0 = every turn from the start). No
    # opening alpha-strike where the whole kit dumps on turn one; skills come
    # online in cooldown order. Applies to mobs too.
    for combatant in (*party, mob):
        for loaded in combatant.skills:
            combatant.cooldowns.setdefault(loaded.skill.id, loaded.cooldown)

    def rounded_out() -> bool:
        # The mob's Nth action ends the fight -- the doom clock is exact.
        return mob.alive and ctx.round >= mob.rounds_limit

    def over() -> bool:
        return not mob.alive or not any(p.alive for p in party) or rounded_out()

    while ctx.tick < SIM_MAX_TICKS and not over():
        ctx.tick += 1

        ready: list[Combatant] = []
        for combatant in (*party, mob):
            if not combatant.alive:
                continue
            if isinstance(combatant, PlayerState) and combatant.stun_rounds > 0:
                # Stunned players freeze: no gauge until the stun wears off
                # (it ticks down as the mob closes rounds). The MOB always
                # keeps filling -- its stun is spent by skipping the turns
                # themselves, so freezing it would deadlock the fight.
                continue
            combatant.gauge += combatant.speed
            if combatant.gauge >= ATB_THRESHOLD:
                ready.append(combatant)

        for actor in sorted(ready, key=lambda c: c.gauge, reverse=True):
            if over() or not actor.alive:
                continue
            if isinstance(actor, PlayerState) and actor.stun_rounds > 0:
                continue  # stunned mid-tick by the mob; gauge kept for later
            actor.gauge -= ATB_THRESHOLD
            if isinstance(actor, MobState):
                if actor.stun_rounds > 0:
                    # A stunned mob LOSES this turn: no action, and the round
                    # stays open -- the doom clock only counts real actions,
                    # so stunning never shrinks the party's kill window.
                    actor.stun_rounds -= 1
                    events.append(
                        CombatEvent(
                            tick=ctx.tick,
                            round=ctx.round + 1,
                            actor=actor.name,
                            kind="stunned",
                        )
                    )
                    continue
                # Freeze: like stun but probabilistic -- a lingering status
                # where each turn has a chance to be lost (round stays open).
                if actor.freeze_rounds > 0:
                    actor.freeze_rounds -= 1
                    if rng.random() < FREEZE_SKIP_CHANCE:
                        events.append(
                            CombatEvent(
                                tick=ctx.tick,
                                round=ctx.round + 1,
                                actor=actor.name,
                                kind="freeze_effect",
                            )
                        )
                        continue
                # Round boundary: dots tick ONCE per round, just before the
                # mob acts -- a bleeding combatant can die of wounds here,
                # including the mob itself, before it gets its turn.
                for combatant in (*party, mob):
                    if combatant.alive and combatant.dots:
                        _apply_dots(combatant, ctx, events, rng)
                if over() or not actor.alive:
                    continue
                _mob_act(actor, party, ctx, events, rng)
            else:
                if actor.freeze_rounds > 0:
                    actor.freeze_rounds -= 1
                    if rng.random() < FREEZE_SKIP_CHANCE:
                        events.append(
                            CombatEvent(
                                tick=ctx.tick,
                                round=ctx.round + 1,
                                actor=actor.name,
                                kind="freeze_effect",
                            )
                        )
                        continue
                _player_act(actor, mob, party, ctx, events)  # type: ignore[arg-type]
            _check_requirements(mob, ctx, events)

    return SimulationResult(
        won=not mob.alive,
        ticks=ctx.tick,
        rounds=ctx.round,
        rounded_out=rounded_out(),
        party=party,
        mob=mob,
        events=events,
    )
