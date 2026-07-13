"""Embed builders for the legion cog. Pure presentation: take models /
dataclasses, return discord.Embed. No DB access, no state."""

from datetime import datetime

import discord

from maki.cogs.legion import strings
from maki.cogs.legion.calculator import (
    eval_formula,
    legion_level_cost,
    mastery_level_cost,
    mutated,
    tier_scaled,
)
from maki.cogs.legion.constants import (
    BAR_LENGTH,
    CRAFT_SURFACE_PAGE_SIZE,
    LOBBY_SECONDS,
    MASTERY_HARD_CAP,
    MASTERY_KIND_WEAPONS,
    MASTERY_SOFT_CAP,
    PLAYER_BASE_ATK,
    PLAYER_BASE_DEF,
    PLAYER_BASE_SPEED,
    SETTLEMENT_PLAYERS_PER_PAGE,
    WeaponSlot,
    LOBBY_PLAYERS_SHOWN,
)
from maki.cogs.legion.model.model import (
    DungeonInstance,
    GatherSite,
    HuntingGround,
    Legion,
    LifeSkillMastery,
    Material,
    Mob,
    Player,
    PlayerActivity,
    PlayerMaterial,
    PlayerWeapon,
    WeaponMastery,
)
from maki.cogs.legion.settlement import SettlementReport
from maki.cogs.legion.simulation import CombatEvent, SimulationResult

# Display stats for skill-value previews: effect_value / stat_bonus_value are
# FORMULA STRINGS now ("{atk} + 12"); detail embeds resolve them against base
# player stats (combat resolves against live stats at use time, so shown
# numbers are a baseline, not a promise).
_BASE_STATS = {
    "atk": PLAYER_BASE_ATK,
    "attack": PLAYER_BASE_ATK,
    "def": PLAYER_BASE_DEF,
    "defense": PLAYER_BASE_DEF,
    "speed": PLAYER_BASE_SPEED,
    "hp": 100,
    "max_hp": 100,  # Player.max_health_points base default
}


def _formula_value(expr, tier: int, mutation: int | None = None) -> int:
    """Formula -> display number: eval vs base stats, then tier%/mutation%."""
    try:
        base = eval_formula(expr, _BASE_STATS)
    except ValueError:
        return 0  # bad formula should never pass the patch validator
    return mutated(tier_scaled(base, tier), mutation)


# --- expedition --------------------------------------------------------------


def ground_list_embed(
    grounds: list[HuntingGround], color: discord.Colour
) -> discord.Embed:
    """Layer 1: every ground open to the legion, one line each."""
    lines = []
    for g in grounds:
        lines.append(
            f"**{g.name}** — {strings.DANGER_TITLE}{strings.EXPONENT_TITLE} {g.danger}"
        )
        if g.description:
            lines.append(f"-# {g.description}")
    embed = discord.Embed(
        title=strings.HUNTING_GROUND_LIST_TITLE,
        description="\n".join(lines),
        color=color,
    )
    embed.set_footer(
        text=f"{strings.RANDOM_PREFIX}{strings.AREA_TITLE}：{strings.HUNTING_RANDOM_DESC}"
    )
    return embed


def ground_detail_embed(
    ground: HuntingGround,
    pool: list,  # list[GroundMob], mob prefetched
    drops: list[Material],
    color: discord.Colour,
) -> discord.Embed:
    """Layer 2: one ground's intel -- danger, encounter pool, droppable mats."""
    desc = [f"{strings.DANGER_TITLE}{strings.EXPONENT_TITLE}：**{ground.danger}**"]
    if ground.description:
        desc.insert(0, ground.description)
    embed = discord.Embed(title=ground.name, description="\n".join(desc), color=color)
    total = sum(e.weight for e in pool) or 1
    mob_lines = [
        strings.HUNTING_GROUND_MOB_LINE.format(
            name=e.mob.name, tier=e.mob.tier, pct=round(e.weight * 100 / total)
        )
        for e in pool
    ]
    embed.add_field(
        name=strings.HUNTING_GROUND_MOBS_TITLE,
        value="\n".join(mob_lines) or strings.HUNTING_GROUND_NO_INTEL,
        inline=False,
    )
    embed.add_field(
        name=strings.HUNTING_GROUND_DROPS_TITLE,
        value="、".join(m.name for m in drops) or strings.HUNTING_GROUND_NO_INTEL,
        inline=False,
    )
    return embed


def lobby_embed(
    ground: HuntingGround,
    mob: Mob,
    random_ground: bool,
    participants: list[str],
    expires_at: datetime,
    color: discord.Colour,
    started: bool = False,
) -> discord.Embed:
    where = (
        ground.name if not random_ground else f"{ground.name} ({strings.RANDOM_PREFIX})"
    )
    desc = strings.HUNTING_EXPEDITION_DESC_LIST[
        hash(where) % len(strings.HUNTING_EXPEDITION_DESC_LIST)
    ].format(ground=ground.name, mob=mob.name, tier=mob.tier)
    rounds_limit = strings.HUNTING_EXPEDITION_ROUNDSLIMIT.format(
        rounds=mob.rounds_limit
    )
    # At expiry the countdown line flips to the preparation-over notice.
    time_left = (
        strings.HUNTING_PREPARATION_OVER
        if started
        else strings.HUNTING_EXPEDITION_TIMELEFT.format(
            expires=int(expires_at.timestamp())
        )
    )
    embed = discord.Embed(
        title=f"{where}",
        description="\n".join([desc, rounds_limit, time_left]),
        color=color,
    )
    embed.set_author(name=strings.HUNTING_EXPEDITION_IN_PROGRESS)
    if len(participants) > LOBBY_PLAYERS_SHOWN:
        names = (
            "\n".join(f"- {n}" for n in participants[:LOBBY_PLAYERS_SHOWN]) + "\n..."
        )
    else:
        names = (
            "\n".join(f"- {n}" for n in participants[:LOBBY_PLAYERS_SHOWN])
            or strings.HUNTING_PARTY_EMPTY
        )
    embed.add_field(
        name=f"{strings.HUNTING_PARTY} ({len(participants)}{strings.PLAYER_UNIT})",
        value=names,
    )
    embed.set_footer(
        text=strings.HUNTING_FOOTER_TOOLTIP.format(
            command=strings.EXPEDITION_COMMAND_NAME
        )
    )
    return embed


def event_line(e: CombatEvent) -> str:
    template = strings.COMBAT_EVENT.get(e.kind, "{actor} {kind}")
    return template.format(
        actor=e.actor, target=e.target, value=e.value, detail=e.detail, kind=e.kind
    )


COMBAT_LOG_FIELDS_PER_EMBED = 6
COMBAT_LOG_EMBED_CHAR_BUDGET = 5500  # under Discord's 6000 total-embed ceiling


def combat_log_embeds(
    result: SimulationResult, rounds_limit: int, color: discord.Colour
) -> list[discord.Embed]:
    """The fight as embeds: one field per round (name 第 X 回合, value = its
    events). Up to COMBAT_LOG_FIELDS_PER_EMBED fields per embed, spilling to the
    next embed when a field would blow the per-embed char budget. Every embed
    carries the 戰鬥紀錄 author line and a timestamp; the caller paginates."""
    rounds: dict[int, list[CombatEvent]] = {}
    for e in result.events:
        rounds.setdefault(e.round, []).append(e)

    fields: list[tuple[str, str]] = []
    for round_no in sorted(rounds):
        name = strings.COMBAT_LOG_FIELD.format(round_no=round_no)
        value = "\n".join(event_line(e) for e in rounds[round_no])
        fields.append((name, value[:1024] or strings.COMBAT_ROUND_EMPTY))
    if not fields:  # a fight with no recorded events (shouldn't happen)
        fields = [
            (strings.COMBAT_LOG_FIELD.format(round_no=0), strings.COMBAT_ROUND_EMPTY)
        ]

    def _fresh() -> discord.Embed:
        embed = discord.Embed(color=color)
        embed.set_author(name=strings.COMBAT_LOG_BUTTON)
        embed.timestamp = discord.utils.utcnow()
        return embed

    embeds: list[discord.Embed] = []
    current = _fresh()
    used, count = 0, 0
    for name, value in fields:
        cost = len(name) + len(value)
        if count and (
            count >= COMBAT_LOG_FIELDS_PER_EMBED
            or used + cost > COMBAT_LOG_EMBED_CHAR_BUDGET
        ):
            embeds.append(current)
            current = _fresh()
            used, count = 0, 0
        current.add_field(name=name, value=value, inline=False)
        used += cost
        count += 1
    embeds.append(current)
    return embeds


def round_embed(
    round_no: int,
    rounds_limit: int,
    events: list[CombatEvent],
    color: discord.Colour,
) -> discord.Embed:
    lines = [event_line(e) for e in events]
    embed = discord.Embed(
        description="\n".join(lines)[:4000] or strings.COMBAT_ROUND_EMPTY,
        color=color,
    )
    embed.set_footer(
        text=strings.COMBAT_ROUND.format(round_no=round_no, rounds_limit=rounds_limit)
    )
    return embed


def _signed_delta(value: int) -> str:
    """Pre-signed mastery delta: ``+6`` for gains, ``−5`` (U+2212) for losses."""
    return f"+{value:,}" if value > 0 else f"−{abs(value):,}"


def _settlement_field(line, result: SimulationResult) -> tuple[str, str, int]:
    """One player's settlement block. Returns ``(header, text, sort_key)``
    where sort_key = damage dealt + taken (page ordering)."""
    # Combine main + off-hand gains and the zero-sum drains into ONE net
    # change per weapon category, then list them positives-first (high->low)
    # and negatives after (low->high).
    deltas: dict[str, int] = {}
    relocks: dict[str, int] = {}
    for g in (line.grant, line.grant_sub):
        if g is None:
            continue
        if g.category:
            deltas[g.category] = deltas.get(g.category, 0) + g.pts
        if g.drained_pts and g.drained_from:
            deltas[g.drained_from] = deltas.get(g.drained_from, 0) - g.drained_pts
            if g.levels_lost:
                relocks[g.drained_from] = relocks.get(g.drained_from, 0) + g.levels_lost
    ordered = sorted(
        ((c, v) for c, v in deltas.items() if v != 0),
        key=lambda cv: (cv[1] < 0, -cv[1] if cv[1] >= 0 else cv[1]),
    )
    mastery_lines = []
    for category, value in ordered:
        text = strings.SETTLE_MASTERY_NET.format(
            category=category, delta=_signed_delta(value)
        )
        if value < 0 and category in relocks:
            text += strings.SETTLE_RELOCK_LINE.format(
                category=category, levels=relocks[category]
            )
        mastery_lines.append(text)

    ps = next((p for p in result.party if p.player.id == line.player.id), None)
    # A top-damage or top-tank finish earns a crown -- on the field NAME (where
    # custom emojis render), since the value goes back inside a code block.
    header = line.player.username
    if line.top_damage or line.top_tank:
        header = f"{strings.CROWN_EMOJI} {header}"
    sort_key = 0
    # Value = blank-line-separated groups: combat stats, mastery changes, rewards.
    groups: list[str] = []
    if ps is not None:
        sort_key = ps.damage_dealt + ps.damage_taken
        header += (
            strings.SKULL_EMOJI
            if not ps.alive
            else f" ({ps.current_hp:,}/{ps.max_hp:,} {strings.HEALTHPOINT_TITLE_SHORT})"
        )
        groups.append(
            "\n".join(
                [
                    f"{strings.SETTLE_DAMAGE_DEALT}: {ps.damage_dealt:,}",
                    f"{strings.SETTLE_DAMAGE_TAKEN}: {ps.damage_taken:,}",
                    f"{strings.SETTLE_HEAL_DONE}: {ps.healing_done:,}",
                ]
            )
        )
    if mastery_lines:
        groups.append("\n".join(mastery_lines))
    rewards = []
    if line.drops:
        rewards.append(
            strings.SETTLE_DROP
            + ": "
            + ", ".join(
                f"{mat.name}{strings.TIMES_EMOJI}{qty}" for mat, qty in line.drops
            )
        )
    if line.daily_contri:
        rewards.append(strings.SETTLE_DAILY_CONTRI.format(pts=line.daily_contri))
    if line.outsider:
        rewards.append(strings.SETTLE_OUTSIDER_TAG)
    if rewards:
        groups.append("\n".join(rewards))
    return header, "```\n{}\n```".format("\n\n".join(groups)), sort_key


def settlement_embeds(
    report: SettlementReport,
    result: SimulationResult,
    color: discord.Colour,
    per_page: int = SETTLEMENT_PLAYERS_PER_PAGE,
) -> tuple[list[discord.Embed], dict[int, str]]:
    """Paged settlement (players sorted by dealt+taken desc, ``per_page`` per
    embed) plus ``{discord_id: personal_text}`` for the ephemeral my-result
    button."""
    if result.won:
        title = strings.SETTLE_WON.format(mob=result.mob.name, rounds=result.rounds + 1)
    elif result.rounded_out:
        title = strings.SETTLE_END.format(mob=result.mob.name, rounds=result.rounds + 1)
    else:
        title = strings.SETTLE_LOST.format(
            mob=result.mob.name, rounds=result.rounds + 1
        )
    blocks = []
    personal: dict[int, str] = {}
    for line in report.players:
        header, text, sort_key = _settlement_field(line, result)
        blocks.append((sort_key, header, text))
        personal[line.player.discord_id] = f"**{header}**\n{text}"
    blocks.sort(key=lambda b: b[0], reverse=True)

    note = ""
    if report.legion_exp:
        note = f"{strings.LEGION_REFER}{strings.EXPERIENCE_UNIT} +{report.legion_exp:,} {strings.EXPERIENCE_UNIT_SHORTER}"
        if report.upgrade_ready:
            note += "\n" + strings.LEGION_UPGRADE_READY_SHORT

    pages = [blocks[i : i + per_page] for i in range(0, len(blocks), per_page)] or [[]]
    embeds = []
    for page_no, page in enumerate(pages, start=1):
        embed = discord.Embed(title=title, color=color)
        embed.set_author(name=strings.SETTLE_RESULT_AUTHOR)
        embed.description = strings.SETTLE_MOB_HP.format(
            mob=result.mob.name,
            hp=max(0, result.mob.current_hp),
            max_hp=result.mob.max_hp,
        )
        for _, header, text in page:
            embed.add_field(name=header, value=text, inline=False)
        footer = note
        if len(pages) > 1:
            page_tag = strings.SETTLE_PAGE.format(page=page_no, pages=len(pages))
            footer = f"{note} · {page_tag}" if note else page_tag
        if footer:
            embed.set_footer(text=footer)
        embeds.append(embed)
    return embeds, personal


def settlement_embed(
    report: SettlementReport,
    result: SimulationResult,
    color: discord.Colour,
) -> discord.Embed:
    """Back-compat single-embed view (first page)."""
    return settlement_embeds(report, result, color)[0][0]


def expired_embed(color: discord.Colour) -> discord.Embed:
    return discord.Embed(
        title=strings.HUNTING_FAILED_INIT,
        description=strings.HUNTING_PARTY_MIA,
        color=color,
    )


def progress_bar(percent: float, length: int = BAR_LENGTH) -> str:
    """0-100 -> emoji bar. 70 -> head_full + 6 body_full + 2 body_empty +
    tail_empty. Each segment has empty/half/full, so odd percentages land on
    a half segment (75 -> 7 full + 1 half + 2 empty)."""
    percent = max(0.0, min(100.0, percent))
    halves = round(percent / 100 * length * 2)
    segments = []
    for i in range(length):
        state = max(0, min(2, halves - i * 2))
        if i == 0:
            pool = (strings.HEAD_EMPTY, strings.HEAD_HALF_FULL, strings.HEAD_FULL)
        elif i == length - 1:
            pool = (strings.TAIL_EMPTY, strings.TAIL_HALF_FULL, strings.TAIL_FULL)
        else:
            pool = (strings.BODY_EMPTY, strings.BODY_HALF_FULL, strings.BODY_FULL)
        segments.append(pool[state])
    if segments[-2] == strings.BODY_FULL and percent < 100:
        segments[-1] = (
            strings.TAIL_HALF_FULL
        )  # show a half tail for 99.9% to avoid confusion with full
    return "".join(segments)


# --- profile & friends --------------------------------------------------------


def profile_embed(
    player: Player,
    legion: Legion | None,
    equipped: dict[WeaponSlot, PlayerWeapon | None],
    color: discord.Colour,
    effective_max: int | None = None,
) -> discord.Embed:
    # Effective max (base + legion + equipped passives) is THE displayed max
    # everywhere -- players restore to a true full.
    max_hp = effective_max or player.max_health_points
    embed = discord.Embed(title=player.username, color=color)
    embed.set_author(name=strings.PROFILE_TITLE)
    embed.add_field(
        name=strings.HEALTHPOINT_TITLE,
        value=(
            f"{progress_bar(player.health_points / max(1, max_hp) * 100)}\n"
            f"-# {player.health_points:,}/{max_hp:,}"
        ),
        inline=False,
    )
    embed.add_field(
        name=strings.BELONGS_TO_TITLE + strings.LEGION_REFER,
        value=(
            (legion.name if legion else strings.LEGION_DNE)
            + f"\n-# {strings.LEGION_CONTRIBUTION}: {player.contribution:,}"
        ),
        inline=False,
    )
    for slot in (WeaponSlot.MAIN, WeaponSlot.SUB):
        pw = equipped.get(slot)
        label = (
            f"{strings.WEAPON_QUALITY_NAMES.get(pw.quality.value, '')} {pw.weapon.name}"
            if pw is not None
            else f"-# {strings.NOT_EQUIPPED_TITLE}"
        )
        embed.add_field(name=f"{strings.WEAPON_HAND_NAMES[slot.value]}", value=label)
    return embed


def _mastery_field(name: str, level: int, exp: int) -> tuple[str, str]:
    """``(field_name, field_value)`` for one mastery: level + zone tag in the
    name, the emoji bar + exp progress in the value. One field per mastery --
    a 10-segment bar is ~380 chars, so stacking them in one field would blow
    the 1024 cap."""
    zone = (
        strings.LOCK_EMOJI
        if level >= MASTERY_HARD_CAP
        else (strings.ADDITION_EMOJI if level >= MASTERY_SOFT_CAP else "")
    )
    field_name = f"{name} {strings.LEVEL_EMOJI} {level} {zone}".strip()
    if level >= MASTERY_HARD_CAP:
        value = f"{progress_bar(100)}\n-# {strings.MAX_EMOJI}"
    else:
        need = mastery_level_cost(level + 1)
        value = f"{progress_bar(exp / max(1, need) * 100)}\n-# {exp:,}/{need:,}"
    return field_name, value


def mastery_embed(
    kind: str,
    masteries: list,  # WeaponMastery (category prefetched) or LifeSkillMastery
    color: discord.Colour,
) -> discord.Embed:
    """ONE mastery pool per page (weapon grip vs life skills), picked by the
    view's select menu -- the combined embed got too crowded with bar fields."""
    weapons = kind == MASTERY_KIND_WEAPONS
    section = strings.MASTERY_WEAPON if weapons else strings.MASTERY_LIFE
    embed = discord.Embed(title=f"\u00b7 {section}", color=color)
    if not masteries:
        embed.description = strings.MASTERY_NONE
    for m in masteries:
        display = (
            m.category.name
            if weapons
            else strings.LIFE_SKILL_NAMES.get(m.skill.value, m.skill.value)
        )
        name, value = _mastery_field(display, m.level, m.exp)
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(
        text=strings.MASTERY_FOOTER.format(
            softcap=MASTERY_SOFT_CAP, hardcap=MASTERY_HARD_CAP
        )
    )
    return embed


def _weapon_display(pw: PlayerWeapon) -> str:
    quality = strings.WEAPON_QUALITY_NAMES.get(pw.quality.value, pw.quality.value)
    return strings.INVENTORY_WEAPON_NAME.format(
        quality=quality, weapon=pw.weapon.name
    ).strip()


def inventory_home_embed(
    stacks: list[PlayerMaterial],
    equipped: list[PlayerWeapon],
    color: discord.Colour,
) -> discord.Embed:
    """Layer 1: every material stack + only the EQUIPPED weapons."""
    embed = discord.Embed(title=strings.INVENTORY_TITLE, color=color)
    mat_lines = [
        f"**{s.material.name}**{strings.TIMES_EMOJI}{s.quantity:,}"
        for s in stacks
        if s.quantity > 0
    ]
    embed.add_field(
        name=strings.INVENTORY_MATERIALS_TITLE,
        value=", ".join(mat_lines)[:3000] or strings.INVENTORY_EMPTY,
        inline=False,
    )
    equipped_lines = [f"**{_weapon_display(w)}**" for w in equipped]
    embed.add_field(
        name=strings.INVENTORY_EQUIPPED_TITLE,
        value="\n".join(equipped_lines) or strings.INVENTORY_EMPTY,
        inline=False,
    )
    return embed


def inventory_weapons_embed(
    weapons: list[PlayerWeapon], color: discord.Colour
) -> discord.Embed:
    """Layer 2: every owned weapon with details (hand, category, equip state,
    mutation potential)."""
    embed = discord.Embed(
        title=f"{strings.INVENTORY_TITLE} — {strings.INVENTORY_WEAPONS_TITLE}",
        color=color,
    )
    for w in weapons[:25]:
        hand = strings.INVENTORY_MAIN if w.weapon.main_weapon else strings.INVENTORY_SUB
        details = [f"{w.weapon.category.name} · {hand}"]
        if w.equipped_slot:
            details.append(strings.INVENTORY_EQUIPPED)
        if w.mutations:
            avg = round(sum(w.mutations.values()) / len(w.mutations))
            details.append(strings.INVENTORY_POTENTIAL.format(pct=avg))
        embed.add_field(
            name=f"{_weapon_display(w)}",
            value=" · ".join(details),
            inline=False,
        )
    if not weapons:
        embed.description = strings.INVENTORY_EMPTY
    return embed


def recipe_detail_embed(
    recipe,
    inputs: list,  # [(Material, need, have)]
    color: discord.Colour,
    *,
    weapon=None,
    actives: list = [],
    passives: list = [],
    weapon_mastery: int = 0,
    material=None,
    mutation_range: tuple[int, int] | None = None,
) -> discord.Embed:
    """Craft layer 3: what a recipe makes (base stats -- mutations roll at
    craft time), what it costs, and whether the player can afford it."""
    desc_parts = []
    if weapon is not None:
        hand = strings.INVENTORY_MAIN if weapon.main_weapon else strings.INVENTORY_SUB
        desc_parts.append(f"{weapon.category.name} · {hand}")
        if mutation_range is not None:
            desc_parts.append(
                strings.CRAFT_POTENTIAL_RANGE.format(
                    low=mutation_range[0], high=mutation_range[1]
                )
            )
        if weapon.description:
            desc_parts.append(weapon.description)
    elif material is not None:
        if material.stat_bonus_value:
            desc_parts.append(
                strings.INVENTORY_HEAL_EFFECT.format(value=material.stat_bonus_value)
            )
        desc_parts.append(strings.CRAFT_RESULT_QTY.format(qty=recipe.result_qty))
        if material.description:
            desc_parts.append(material.description)

    embed = discord.Embed(
        title=recipe.name, description="\n".join(desc_parts), color=color
    )

    if weapon is not None:

        def lock_suffix(req: int) -> str:
            if weapon_mastery >= req:
                return ""
            return "\n" + strings.SKILL_LOCKED_TAG.format(
                category=weapon.category.name, req=req
            )

        active_lines = []
        for mount in actives:
            skill = mount.active_skill
            text = strings.SKILL_ACTIVE_DESCRIPTION.get(
                skill.effect_type.value, "{value:,}"
            ).format(value=_formula_value(skill.effect_value, mount.tier))
            text += strings.SKILL_COOLDOWN_DESCRIPTION.format(value=skill.cooldown)
            tier = strings.SKILL_TIER_TAG.format(tier=mount.tier)
            active_lines.append(
                f"**{skill.name}** ({tier})\n{text}"
                f"{lock_suffix(mount.mastery_level_required)}"
            )
        if active_lines:
            embed.add_field(
                name=strings.SKILL_ACTIVE_SKILL,
                value="\n\n".join(active_lines)[:1000],
                inline=False,
            )
        passive_lines = []
        for mount in passives:
            skill = mount.passive_skill
            text = strings.SKILL_PASSIVE_DESCRIPTION.get(
                skill.stat_bonus_type.value, "{value:,}"
            ).format(value=_formula_value(skill.stat_bonus_value, mount.tier))
            tier = strings.SKILL_TIER_TAG.format(tier=mount.tier)
            passive_lines.append(
                f"**{skill.name}** ({tier})\n{text}"
                f"{lock_suffix(mount.mastery_level_required)}"
            )
        if passive_lines:
            embed.add_field(
                name=strings.SKILL_PASSIVE_SKILL,
                value="\n\n".join(passive_lines)[:1000],
                inline=False,
            )

    mat_lines = [
        strings.CRAFT_MAT_LINE.format(
            mark=strings.CHECK_EMOJI if have >= need else strings.CROSS_EMOJI,
            name=mat.name,
            have=have,
            need=need,
        )
        for mat, need, have in inputs
    ]
    embed.add_field(
        name=strings.CRAFT_MATS_TITLE,
        value="\n".join(mat_lines) or strings.INVENTORY_EMPTY,
        inline=False,
    )
    return embed


def weapon_detail_embed(
    pw: PlayerWeapon,
    actives: list,  # WeaponActiveSkill with .active_skill, ordered by tier
    passives: list,  # WeaponPassiveSkill with .passive_skill, ordered by tier
    mastery_level: int,
    color: discord.Colour,
) -> discord.Embed:
    """Layer 3: one weapon instance in full -- identity on top, skill fields
    below with mutation-adjusted values and lock states from the player's
    mastery of this weapon's category."""
    category = pw.weapon.category
    hand = strings.INVENTORY_MAIN if pw.weapon.main_weapon else strings.INVENTORY_SUB
    quality = strings.WEAPON_QUALITY_DISPLAY.get(pw.quality.value, pw.quality.value)
    desc_parts = [
        f"{category.name} · {hand}",
        f"{strings.WEAPON_QUALITY_TITLE}: {quality}",
    ]
    if pw.equipped_slot:
        desc_parts.append(strings.INVENTORY_EQUIPPED)
    muts: dict[str, int] = pw.mutations or {}
    if muts:
        avg = round(sum(muts.values()) / len(muts))
        desc_parts.append(strings.INVENTORY_POTENTIAL.format(pct=avg))
    if pw.weapon.description:
        desc_parts.append(pw.weapon.description)

    embed = discord.Embed(
        title=_weapon_display(pw),
        description="\n".join(desc_parts),
        color=color,
    )

    def lock_suffix(req: int) -> str:
        if mastery_level >= req:
            return ""
        return "\n" + strings.SKILL_LOCKED_TAG.format(category=category.name, req=req)

    active_lines = []
    for mount in actives:
        skill = mount.active_skill
        value = _formula_value(
            skill.effect_value, mount.tier, muts.get(str(mount.active_skill_id))
        )
        text = strings.SKILL_ACTIVE_DESCRIPTION.get(
            skill.effect_type.value, "{value:,}"
        ).format(value=value)
        text += strings.SKILL_COOLDOWN_DESCRIPTION.format(value=skill.cooldown)
        tier = strings.SKILL_TIER_TAG.format(tier=mount.tier)
        active_lines.append(
            f"**{skill.name}** ({tier})\n{text}{lock_suffix(mount.mastery_level_required)}"
        )
    embed.add_field(
        name=strings.SKILL_ACTIVE_SKILL,
        value="\n\n".join(active_lines)[:1000] or strings.INVENTORY_EMPTY,
        inline=False,
    )

    passive_lines = []
    for mount in passives:
        skill = mount.passive_skill
        value = _formula_value(
            skill.stat_bonus_value, mount.tier, muts.get(str(mount.passive_skill_id))
        )
        text = strings.SKILL_PASSIVE_DESCRIPTION.get(
            skill.stat_bonus_type.value, "{value:,}"
        ).format(value=value)
        tier = strings.SKILL_TIER_TAG.format(tier=mount.tier)
        passive_lines.append(
            f"**{skill.name}** ({tier})\n{text}{lock_suffix(mount.mastery_level_required)}"
        )
    embed.add_field(
        name=strings.SKILL_PASSIVE_SKILL,
        value="\n\n".join(passive_lines)[:1000] or strings.INVENTORY_EMPTY,
        inline=False,
    )
    return embed


def inventory_consumables_embed(
    stacks: list[PlayerMaterial], color: discord.Colour
) -> discord.Embed:
    """Layer 2: every consumable with its effect and description."""
    embed = discord.Embed(
        title=f"{strings.INVENTORY_TITLE} — {strings.INVENTORY_CONSUMABLE_DESC}",
        color=color,
    )
    for s in stacks[:25]:
        details = []
        kind = s.material.kind.value
        stype = s.material.stat_bonus_type.value if s.material.stat_bonus_type else "hp"
        if kind == "food" and s.material.stat_bonus_value:
            if stype in ("regen", "hp"):
                details.append(
                    strings.INVENTORY_REGEN_EFFECT.format(
                        value=s.material.stat_bonus_value,
                        duration=s.material.duration or 0,
                    )
                )
            else:  # timed combat-stat buff
                details.append(
                    strings.FOOD_BUFF_EFFECT.format(
                        value=s.material.stat_bonus_value,
                        category=strings.STAT_NAMES.get(stype, stype),
                        duration=s.material.duration or 0,
                    )
                )
        elif s.material.stat_bonus_value:
            details.append(
                strings.INVENTORY_HEAL_EFFECT.format(value=s.material.stat_bonus_value)
            )
            if kind == "potion":
                details.append(strings.POTION_REVIVE_TAG)
        if s.material.description:
            details.append(s.material.description)
        embed.add_field(
            name=strings.INVENTORY_CONSUMABLE_NAME.format(
                material=s.material.name, qty=s.quantity
            ),
            value=" · ".join(details) or strings.INVENTORY_CONSUMABLE_DESC,
            inline=False,
        )
    if not stacks:
        embed.description = strings.INVENTORY_EMPTY
    return embed


# --- legion --------------------------------------------------------------------


def legion_embed(
    legion: Legion,
    member_count: int,
    active_count: int,
    sheet: list[tuple[Material, int, int]],
    color: discord.Colour,
) -> discord.Embed:
    next_cost = legion_level_cost(legion.level + 1)
    embed = discord.Embed(title=legion.name, color=color)
    embed.set_author(name=strings.LEGION_REFER + strings.INFO_TITLE)
    embed.add_field(name=strings.LEVEL_UNIT, value=str(legion.level))
    embed.add_field(
        name=strings.EXPERIENCE_UNIT,
        value=f"{progress_bar(legion.exp / max(1, next_cost) * 100)}\n-# {legion.exp:,}/{next_cost:,}",
        inline=False,
    )
    embed.add_field(
        name=strings.MEMBERS_TITLE,
        value=f"{member_count:,}",
    )
    embed.add_field(name=strings.LEGION_KILLS_COUNT, value=str(legion.daily_kills))
    if sheet:
        lines = [
            f"{strings.CHECK_EMOJI if have >= need else strings.CROSS_EMOJI} {mat.name}: {have:,}/{need:,}"
            for mat, need, have in sheet
        ]
        embed.add_field(
            name=(
                f"{strings.LEVEL_EMOJI}{legion.level + 1} "
                f"{strings.LEGION_UPDATE_SHEET}"
            ),
            value="\n".join(lines),
            inline=False,
        )
    if not legion.channel_id:
        embed.set_footer(text=strings.LEGION_NO_CHANNEL_SET)
    return embed


def members_embed(
    legion: Legion,
    entries: list[Player],
    page: int,
    pages: int,
    color: discord.Colour,
) -> discord.Embed:
    embed = discord.Embed(
        title=strings.LEGION_REFER + strings.MEMBERS_TITLE,
        color=color,
    )
    if entries:
        # Two inline fields render as aligned columns -- names and contribution
        # share the same row order, so line N of each matches the same player.
        names = "\n".join(
            f"{f'[{strings.MANAGER_TITLE}] ' if p.is_legion_manager else ''}{p.username}"
            for p in entries
        )
        values = "\n".join(f"{p.contribution:,}" for p in entries)
        embed.add_field(name=strings.MEMBERS_NAME_COL, value=names, inline=True)
        embed.add_field(name=strings.LEGION_CONTRIBUTION, value=values, inline=True)
    else:
        embed.description = (
            strings.LEGION_REFER + strings.MEMBERS_TITLE + strings.DNE_TITLE
        )
    embed.set_footer(
        text=strings.PAGE_NUM_TITLE.format(page=page + 1, pages=max(1, pages))
    )
    return embed


def donate_embed(
    legion: Legion,
    stacks: list[PlayerMaterial],
    sheet_map: dict[int, tuple[int, int]],  # material_id -> (need, have)
    color: discord.Colour,
) -> discord.Embed:
    """The donate panel: your stacks, tagged where the upgrade sheet needs
    them (need/have of the LEGION stockpile)."""
    embed = discord.Embed(
        title=f"{strings.DONATE_TITLE}{strings.LEGION_REFER}{strings.MATERIAL_TITLE}",
        description=strings.DONATE_DESC,
        color=color,
    )
    lines = []
    for s in stacks:
        line = f"**{s.material.name}** {strings.TIMES_EMOJI}{s.quantity:,}"
        if s.material_id in sheet_map:
            need, have = sheet_map[s.material_id]
            line += f" — {strings.DONATE_NEEDED_TAG.format(have=have, need=need)}"
        lines.append(line)
    if lines:
        embed.add_field(
            name=strings.INVENTORY_MATERIALS_TITLE,
            value="\n".join(lines)[:1000],
            inline=False,
        )
    else:
        embed.description = strings.DONATE_NOTHING
    return embed


def donation_announce_embed(
    donor: str,
    qty: int,
    material: Material,
    stockpiled: int,
    need: int | None,
    color: discord.Colour,
) -> discord.Embed:
    """Public shout when a member donates: who gave what, plus the legion's
    current stockpile of that material -- shown as upgrade progress when the
    material is on the next-level sheet, else a plain total."""
    embed = discord.Embed(
        title=strings.DONATE_ANNOUNCE_TITLE,
        description=strings.DONATE_ANNOUNCE_DESC.format(
            donor=donor, material=material.name, qty=qty
        ),
        color=color,
    )
    if need is not None:
        value = strings.DONATE_ANNOUNCE_PROGRESS.format(have=stockpiled, need=need)
    else:
        value = strings.DONATE_ANNOUNCE_STOCK.format(have=stockpiled)
    embed.add_field(name=material.name, value=value, inline=False)
    return embed


def legion_settings_embed(
    legion: Legion,
    managers: list[Player],
    color: discord.Colour,
) -> discord.Embed:
    """The legion settings layer: current values on top, selects below."""
    embed = discord.Embed(
        title=f"{legion.name} — {strings.LEGION_SETTINGS_TITLE}",
        color=color,
    )
    embed.add_field(name=strings.LEGION_SETTINGS_NAME, value=legion.name)
    embed.add_field(
        name=strings.LEGION_SETTINGS_CHANNEL,
        value=(
            f"<#{legion.channel_id}>"
            if legion.channel_id
            else strings.LEGION_SETTINGS_NOT_SET
        ),
    )
    embed.add_field(
        name=strings.MANAGER_TITLE,
        value="\n".join(f"- {m.username}" for m in managers)
        or strings.LEGION_SETTINGS_NOT_SET,
        inline=False,
    )
    return embed


# --- gathering -------------------------------------------------------------------


def gather_idle_embed(
    sites: list[GatherSite],
    yields_by_site: dict[int, list[str]],
    color: discord.Colour,
) -> discord.Embed:
    embed = discord.Embed(
        title=strings.GATHER_TITLE,
        description=strings.GATHER_DESCRIPTION,
        color=color,
    )
    for site in sites:
        mats = ", ".join(yields_by_site.get(site.id, [])) or strings.DNE_TITLE
        embed.add_field(
            name=f"{'⛏️' if site.skill.value == 'mine' else '🌿'} {site.name}",
            value=f"{site.description or ''}\n{strings.GATHER_YIELDS}: {mats}".strip(),
            inline=False,
        )
    return embed


def patch_status_embed(
    current: object | None,  # GamePatch | None
    live_counts: dict[str, int],
    disk_version: str,
    disk_hash: str,
    legion: Legion | None,
    color: discord.Colour,
) -> discord.Embed:
    embed = discord.Embed(title=strings.PATCH_TITLE, color=color)
    if current is not None:
        embed.add_field(
            name=strings.PATCH_CURRENT, value=f"**{current.version}** `{current.hash}`"
        )
        if current.notes:
            embed.add_field(
                name=strings.PATCH_NOTES, value=current.notes[:1000], inline=False
            )
    else:
        embed.add_field(name=strings.PATCH_CURRENT, value=strings.DNE_TITLE)
    embed.add_field(
        name=strings.PATCH_ON_DISK, value=f"**{disk_version}** `{disk_hash}`"
    )
    stats = " · ".join(f"{k} {v}" for k, v in live_counts.items())
    embed.add_field(
        name=strings.PATCH_LIVE_CONTENT, value=stats or strings.DNE_TITLE, inline=False
    )
    if legion is not None:
        embed.add_field(
            name=strings.PATCH_THIS_LEGION, value=f"{strings.LEVEL_EMOJI}{legion.level}"
        )
    return embed


def patch_compare_embed(
    current_version: str,
    current_summary: dict[str, int],
    next_version: str,
    next_notes: str | None,
    next_summary: dict[str, int],
    next_hash: str,
    color: discord.Colour,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🆕 {current_version} → {next_version} (`{next_hash}`)",
        description=next_notes or "*no notes*",
        color=color,
    )
    lines = []
    for key in sorted(set(current_summary) | set(next_summary)):
        old, new = current_summary.get(key, 0), next_summary.get(key, 0)
        delta = new - old
        mark = f" ({'+' if delta > 0 else ''}{delta})" if delta else ""
        lines.append(f"**{key}**: {old} → {new}{mark}")
    embed.add_field(name="Content", value="\n".join(lines) or "*no changes*")
    return embed


def gather_busy_embed(
    activity: PlayerActivity,
    possible: list[str],
    color: discord.Colour,
) -> discord.Embed:
    embed = discord.Embed(
        title=strings.GATHER_BUSY_TITLE.format(site=activity.site.name),
        color=color,
    )
    embed.add_field(
        name=strings.GATHER_AFK_SINCE,
        value=f"<t:{int(activity.started_at.timestamp())}:R>",
    )
    embed.add_field(
        name=strings.GATHER_YIELDS, value="\n".join(possible) or strings.QUESTION_TITLE
    )
    return embed


# --- crafting -------------------------------------------------------------------

_CRAFT_SURFACES = (
    ("forge", strings.FORGE_EMOJI, strings.FORGE_TITLE, None),
    ("cook", strings.COOK_EMOJI, strings.COOK_TITLE, "cook"),
    ("brew", strings.BREW_EMOJI, strings.BREW_TITLE, "brew"),
)


def craft_home_embed(
    groups: dict[str, list],  # surface -> [(Recipe, unlocked: bool)]
    life_levels: dict,  # LifeSkillType/str -> level
    color: discord.Colour,
) -> discord.Embed:
    embed = discord.Embed(
        title=strings.CRAFT_TITLE,
        description=strings.CRAFT_HOME_DESC,
        color=color,
    )
    levels = {str(getattr(k, "value", k)): v for k, v in life_levels.items()}
    for skill, desc in strings.CRAFT_DESC.items():
        embed.add_field(
            name=(
                (f"{strings.LIFE_SKILL_NAMES.get(skill, skill)}")
                + (
                    ""
                    if skill == "forge"
                    else f" {strings.CRAFT_MASTERY_TAG.format(level=levels.get(skill, 0))}"
                )
            ),
            value=desc,
            inline=False,
        )
    return embed


def craft_surface_embed(
    surface: str,
    entries: list,  # [(Recipe, unlocked: bool, inputs_text: str)]
    color: discord.Colour,
) -> list[discord.Embed]:
    """One PAGE LIST per workstation: recipes chunk into pages of
    CRAFT_SURFACE_PAGE_SIZE fields; a single page gets no footer and the
    view shows no pager buttons."""
    _, emoji, title, _ = next(s for s in _CRAFT_SURFACES if s[0] == surface)
    chunks = [
        entries[i : i + CRAFT_SURFACE_PAGE_SIZE]
        for i in range(0, len(entries), CRAFT_SURFACE_PAGE_SIZE)
    ] or [[]]
    embeds = []
    for page_no, chunk in enumerate(chunks, start=1):
        embed = discord.Embed(
            title=f"{emoji} {title}{strings.SKILL_REFER}", color=color
        )
        for recipe, unlocked, inputs_text in chunk:
            marker = "" if unlocked else strings.LOCK_EMOJI
            req = ""
            if not unlocked and recipe.skill is not None:
                req = "\n" + strings.CRAFT_NEED_MASTERY.format(
                    skill=strings.LIFE_SKILL_NAMES.get(
                        recipe.skill.value, recipe.skill.value
                    ),
                    req=recipe.mastery_level_required,
                )
            embed.add_field(
                name=f"{marker} {recipe.name}",
                value=(inputs_text or "—") + req,
                inline=False,
            )
        if not entries:
            embed.description = strings.DNE_TITLE
        if len(chunks) > 1:
            embed.set_footer(
                text=strings.PAGE_NUM_TITLE.format(page=page_no, pages=len(chunks))
            )
        embeds.append(embed)
    return embeds
