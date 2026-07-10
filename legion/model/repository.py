"""Repositories for the legion cog.

Plain query-helper classes over the legion models -- never registered with
Tortoise (discovery skips ``repository.py``). The cog holds its own instances
in its ``__init__``.
"""

import random
from datetime import datetime, timedelta

from tortoise.expressions import F, Q
from tortoise.transactions import in_transaction

from maki.cogs.legion.calculator import (
    MasteryGrant,
    apply_mastery_drain,
    apply_mastery_gain,
    drainable_exp,
    get_regen_rate,
    legion_upgrade_qty,
    legion_level_cost,
    quality_from_mutations,
    upgrade_ready,
    promote_elite_mob,
)
from maki.cogs.legion.constants import (
    BASE_REGEN_PER_MINUTE,
    REVIVE_HP,
    REVIVE_MINUTES,
    ACTIVE_TOUCH_THROTTLE_MINUTES,
    ACTIVE_WINDOW_DAYS,
    CONTRI_PER_MAT_RARITY,
    ContentStatus,
    CRAFT_SKILLS,
    MAX_ITEM_STACK,
    GATHER_SKILLS,
    MASTERY_SOFT_CAP,
    DungeonStatus,
    LifeSkillType,
    PatchStatus,
    WeaponQuality,
    WeaponSlot,
    RANDOM_ELITE_MOB_CHANCE,
)
from maki.cogs.legion.model.model import (
    DungeonInstance,
    DungeonParticipant,
    GamePatch,
    GatherSite,
    GroundMob,
    HuntingGround,
    Legion,
    LegionStockpile,
    LegionUpgradeCost,
    LifeSkillMastery,
    Material,
    Mob,
    MobDrop,
    Player,
    PlayerActivity,
    PlayerMaterial,
    PlayerWeapon,
    Weapon,
    WeaponCategory,
    WeaponMastery,
)


class PlayerRepo:
    """Query helpers over Player. One row per Discord user."""

    async def get(self, discord_id: int) -> Player | None:
        return await Player.get_or_none(discord_id=discord_id)

    async def get_or_create(self, discord_id: int, username: str) -> Player:
        player, _ = await Player.get_or_create(
            discord_id=discord_id,
            defaults={
                "username": username,
                "last_active_at": datetime.now().astimezone(),
            },
        )
        return player

    async def join_legion(self, player: Player, legion: Legion) -> None:
        """Join (or switch to) a legion. Contribution is per-legion status,
        so switching resets it; manager status never transfers."""
        player.legion = legion
        player.contribution = 0
        player.is_legion_manager = False
        await player.save(
            update_fields=["legion_id", "contribution", "is_legion_manager"]
        )

    async def leave_legion(self, player: Player) -> None:
        player.legion = None
        player.left_legion_at = datetime.now().astimezone()
        player.contribution = 0
        player.is_legion_manager = False
        await player.save(
            update_fields=[
                "legion_id", "left_legion_at", "contribution", "is_legion_manager"
            ]
        )

    async def add_contribution(self, player: Player, pts: int) -> None:
        player.contribution += pts
        await player.save(update_fields=["contribution"])

    async def apply_regen(
        self, player: Player, legion_level: int, effective_max: int | None = None
    ) -> int:
        """Lazy out-of-combat regen: heal elapsed-minutes * rate since the
        bookmark, advance the bookmark by whole minutes (keeping the
        remainder). Food buffs add +regen_buff_rate/min for the part of the
        window inside the buff. The DEAD (0 HP) do not regenerate -- potions
        are the revive path. Call whenever a player is fetched."""
        now = datetime.now().astimezone()
        if player.health_points <= 0:
            # While dead the bookmark is the DEATH TIMESTAMP (settlement and
            # potion-use both stamp it). After REVIVE_MINUTES the player
            # lazily revives at REVIVE_HP and regen resumes from that moment.
            died_at = player.hp_updated_at or now
            if now - died_at < timedelta(minutes=REVIVE_MINUTES):
                return 0
            player.health_points = REVIVE_HP
            player.hp_updated_at = died_at + timedelta(minutes=REVIVE_MINUTES)
            await player.save(update_fields=["health_points", "hp_updated_at"])
        # Effective max can SHRINK (unequip/dismantle/leave legion): clamp
        # stored HP down so the displayed pool stays honest.
        if effective_max and player.health_points > effective_max:
            player.health_points = effective_max
            await player.save(update_fields=["health_points"])
        last = player.hp_updated_at or player.created_at or now
        minutes = int((now - last).total_seconds() // 60)
        if minutes <= 0:
            return 0
        cap = effective_max or player.max_health_points
        rate = BASE_REGEN_PER_MINUTE + get_regen_rate(legion_level)
        healed = minutes * rate

        # Food buff overlap: buffed minutes inside [last, last+minutes].
        if player.regen_buff_rate and player.regen_buff_until:
            buff_end = min(now, player.regen_buff_until)
            buffed = int(max(0.0, (buff_end - last).total_seconds()) // 60)
            healed += min(buffed, minutes) * player.regen_buff_rate
        update = ["health_points", "hp_updated_at"]
        if player.regen_buff_until and player.regen_buff_until <= now:
            player.regen_buff_rate = 0
            player.regen_buff_until = None
            update += ["regen_buff_rate", "regen_buff_until"]

        healed = min(healed, cap - player.health_points)
        player.health_points += max(0, healed)
        player.hp_updated_at = last + timedelta(minutes=minutes)
        await player.save(update_fields=update)
        return max(0, healed)

    async def set_username(self, player: Player, username: str) -> None:
        player.username = username
        await player.save(update_fields=["username"])

    async def touch_active(self, player: Player) -> None:
        """Stamp last_active_at, throttled: skip the write when the existing
        stamp is fresher than ACTIVE_TOUCH_THROTTLE_MINUTES, so this can run on
        every command without a DB round-trip each time."""
        now = datetime.now().astimezone()
        last = player.last_active_at
        if last is not None and now - last < timedelta(
            minutes=ACTIVE_TOUCH_THROTTLE_MINUTES
        ):
            return
        player.last_active_at = now
        await player.save(update_fields=["last_active_at"])


class LegionRepo:
    """Query helpers over Legion. One row per Discord guild (world)."""

    async def get(self, guild_id: int) -> Legion | None:
        return await Legion.get_or_none(guild_id=guild_id)

    async def get_or_create(self, guild_id: int, name: str) -> Legion:
        legion, _ = await Legion.get_or_create(
            guild_id=guild_id, defaults={"name": name}
        )
        return legion

    async def add_kills(self, legion: Legion, kills: int = 1) -> None:
        legion.daily_kills += kills
        await legion.save(update_fields=["daily_kills"])

    async def reset_daily(self, legion: Legion) -> None:
        legion.daily_kills = 0
        legion.last_reset_at = datetime.now().astimezone()
        await legion.save(update_fields=["daily_kills", "last_reset_at"])

    async def add_exp(self, legion: Legion, pts: int) -> bool:
        """Bank legion exp (NO auto-level -- upgrading is a manual, perm-gated
        act). Returns True if the banked exp now covers the next level, so the
        caller can post the upgrade reminder."""
        legion.exp += pts
        await legion.save(update_fields=["exp"])
        return upgrade_ready(legion.level, legion.exp)

    # -- stockpile & upgrades --

    async def donate(
        self, player: Player, legion: Legion, material: Material, qty: int
    ) -> tuple[int, int] | None:
        """Move up to ``qty`` mats from a player's inventory into the legion
        stockpile, which is capped at MAX_ITEM_STACK. Returns
        ``(accepted_qty, contribution)``; ``accepted_qty`` is below ``qty`` when
        the stockpile fills up (the overflow stays in the donor's bag), and 0
        when it is already full. Returns None if the player lacks the mats."""
        async with in_transaction():
            stack = (
                await PlayerMaterial.filter(player=player, material=material)
                .select_for_update()
                .first()
            )
            if stack is None or stack.quantity < qty:
                return None

            pile = (
                await LegionStockpile.filter(legion=legion, material=material)
                .select_for_update()
                .first()
            )
            current = pile.quantity if pile is not None else 0
            accepted = min(qty, max(0, MAX_ITEM_STACK - current))
            if accepted == 0:
                return (0, 0)

            stack.quantity -= accepted
            await stack.save(update_fields=["quantity"])
            if pile is None:
                await LegionStockpile.create(
                    legion=legion, material=material, quantity=accepted
                )
            else:
                pile.quantity += accepted
                await pile.save(update_fields=["quantity"])

            contri = accepted * material.rarity * CONTRI_PER_MAT_RARITY
            player.contribution += contri
            await player.save(update_fields=["contribution"])
            return (accepted, contri)

    async def stockpiled(self, legion: Legion, material: Material) -> int:
        """Current legion stockpile total of a material (0 if none)."""
        pile = await LegionStockpile.get_or_none(legion=legion, material=material)
        return pile.quantity if pile is not None else 0

    async def active_member_count(self, legion: Legion) -> int:
        """Members seen within ACTIVE_WINDOW_DAYS. Never-stamped legacy rows
        (last_active_at is null) are grandfathered in as active."""
        cutoff = datetime.now().astimezone() - timedelta(days=ACTIVE_WINDOW_DAYS)
        return await Player.filter(
            Q(legion=legion),
            Q(last_active_at__gte=cutoff) | Q(last_active_at__isnull=True),
        ).count()

    async def upgrade_sheet(
        self, legion: Legion
    ) -> list[tuple[Material, int, int]]:
        """Requirements for the NEXT level: ``(material, needed, stockpiled)``
        with needed already scaled by the ACTIVE member count."""
        members = await self.active_member_count(legion)
        costs = await LegionUpgradeCost.filter(level=legion.level + 1).prefetch_related(
            "material"
        )
        piles = {
            p.material_id: p.quantity
            for p in await LegionStockpile.filter(legion=legion)
        }
        return [
            (c.material, legion_upgrade_qty(c.base_qty, members), piles.get(c.material_id, 0))
            for c in costs
        ]

    async def upgrade(self, legion: Legion) -> bool:
        """Perform the upgrade: banked exp >= cost AND stockpile covers the
        sheet. Consumes both and levels up. False if anything is short."""
        async with in_transaction():
            locked = (
                await Legion.filter(id=legion.id).select_for_update().first()
            )
            if locked is None or not upgrade_ready(locked.level, locked.exp):
                return False
            sheet = await self.upgrade_sheet(locked)
            if any(have < need for _, need, have in sheet):
                return False

            for material, need, _ in sheet:
                await LegionStockpile.filter(
                    legion=locked, material=material
                ).update(quantity=F("quantity") - need)
            # locked.exp -= legion_level_cost(locked.level + 1)
            locked.exp = 0  # reset exp to 0 on upgrade
            locked.level += 1
            await locked.save(update_fields=["level", "exp"])
            legion.level, legion.exp = locked.level, locked.exp
            return True


class InventoryRepo:
    """Query helpers over a player's materials and weapon instances."""

    # -- materials --

    async def add_material(
        self, player: Player, material: Material, qty: int
    ) -> None:
        """Add to a player's stack, clamped at MAX_ITEM_STACK (excess lost)."""
        async with in_transaction():
            stack, created = await PlayerMaterial.get_or_create(
                player=player, material=material,
                defaults={"quantity": min(qty, MAX_ITEM_STACK)},
            )
            if not created:
                stack.quantity = min(stack.quantity + qty, MAX_ITEM_STACK)
                await stack.save(update_fields=["quantity"])

    async def quantity(self, player: Player, material: Material) -> int:
        stack = await PlayerMaterial.get_or_none(player=player, material=material)
        return stack.quantity if stack else 0

    async def consume(self, player: Player, costs: dict[int, int]) -> bool:
        """Atomically spend ``{material_id: qty}``. All-or-nothing: returns
        False (spending nothing) if any stack is short."""
        async with in_transaction():
            stacks = (
                await PlayerMaterial.filter(
                    player=player, material_id__in=list(costs)
                ).select_for_update()
            )
            by_material = {s.material_id: s for s in stacks}
            for material_id, qty in costs.items():
                stack = by_material.get(material_id)
                if stack is None or stack.quantity < qty:
                    return False
            for material_id, qty in costs.items():
                stack = by_material[material_id]
                stack.quantity -= qty
                await stack.save(update_fields=["quantity"])
            return True

    # -- weapons --

    async def grant_weapon(
        self,
        player: Player,
        weapon: Weapon,
        mutations: dict[str, int] | None = None,
    ) -> PlayerWeapon:
        """Grant an instance. Crafted weapons pass their mutation rolls
        (quality tier is derived); starters pass None -> flat STANDARD."""
        return await PlayerWeapon.create(
            player=player,
            weapon=weapon,
            mutations=mutations or {},
            quality=quality_from_mutations(mutations or {}),
        )

    async def equipped(self, player: Player, slot: WeaponSlot) -> PlayerWeapon | None:
        return await PlayerWeapon.get_or_none(
            player=player, equipped_slot=slot
        ).prefetch_related("weapon__category")

    async def equip(
        self, player: Player, player_weapon: PlayerWeapon
    ) -> WeaponSlot | None:
        """Equip an owned instance into ITS designated slot (main-hand
        weapons -> MAIN, others -> SUB), unequipping whatever held that slot.
        Returns the slot used, or None if not the owner."""
        if player_weapon.player_id != player.id:
            return None
        weapon = await player_weapon.weapon
        slot = WeaponSlot.MAIN if weapon.main_weapon else WeaponSlot.SUB
        async with in_transaction():
            await PlayerWeapon.filter(player=player, equipped_slot=slot).update(
                equipped_slot=None
            )
            player_weapon.equipped_slot = slot
            await player_weapon.save(update_fields=["equipped_slot"])
            return slot


class ActivityRepo:
    """Query helpers over AFK gathering sessions. One open session per player;
    while one runs, ALL other game actions are blocked (`active_for` is the
    cog-level interceptor check). Payout math lives in calculator/cog."""

    async def active_for(self, player: Player) -> PlayerActivity | None:
        return await PlayerActivity.get_or_none(
            player=player, collected=False
        ).prefetch_related("site")

    async def start(
        self, player: Player, site: GatherSite
    ) -> PlayerActivity | None:
        """Begin an open-ended session, or return None if one is running."""
        async with in_transaction():
            existing = (
                await PlayerActivity.filter(player=player, collected=False)
                .select_for_update()
                .first()
            )
            if existing is not None:
                return None
            return await PlayerActivity.create(
                player=player, site=site, skill=site.skill
            )

    async def stop(self, activity: PlayerActivity) -> int:
        """Close a session; returns elapsed minutes (uncapped -- the caller
        applies the bag cap via calculator.gather_payout_chunks)."""
        activity.collected = True
        await activity.save(update_fields=["collected"])
        elapsed = datetime.now().astimezone() - activity.started_at
        return max(0, int(elapsed.total_seconds() // 60))

    async def unlocked_sites(self, legion_level: int) -> list[GatherSite]:
        return await GatherSite.filter(
            min_legion_level__lte=legion_level, status=ContentStatus.ENABLED
        )


class MasteryRepo:
    """Mastery grants with the zero-sum drain rule.

    Below the soft cap, gains are free growth. Gaining points in a mastery
    already at/above the soft cap drains the same points from one RANDOM
    other mastery in the same pool. THREE independent pools: weapon
    masteries, gathers (mine/garden), crafts (cook/brew). Never drains below
    the soft-cap floor. The returned ``MasteryGrant`` carries everything the
    feedback log needs.
    """

    async def total_mastery(self, player: Player) -> int:
        """Sum of ALL mastery levels (weapon + life skills): the coarse
        progression proxy for the use-item-on-others abuse gate."""
        weapon = await WeaponMastery.filter(player=player).values_list(
            "level", flat=True
        )
        life = await LifeSkillMastery.filter(player=player).values_list(
            "level", flat=True
        )
        return sum(weapon) + sum(life)

    async def grant_weapon(
        self, player: Player, category: WeaponCategory, pts: int
    ) -> MasteryGrant:
        async with in_transaction():
            mastery, _ = await WeaponMastery.get_or_create(
                player=player, category=category
            )
            zero_sum = mastery.level >= MASTERY_SOFT_CAP
            mastery.level, mastery.exp, gained = apply_mastery_gain(
                mastery.level, mastery.exp, pts
            )
            await mastery.save(update_fields=["level", "exp"])

            grant = MasteryGrant(
                pts=pts, levels_gained=gained, category=category.name
            )
            if zero_sum:
                victims = [
                    m
                    for m in await WeaponMastery.filter(player=player)
                    .exclude(id=mastery.id)
                    .prefetch_related("category")
                    if drainable_exp(m.level, m.exp) > 0
                ]
                if victims:
                    victim = random.choice(victims)
                    victim.level, victim.exp, drained, lost = apply_mastery_drain(
                        victim.level, victim.exp, pts
                    )
                    await victim.save(update_fields=["level", "exp"])
                    grant.drained_from = victim.category.name
                    grant.drained_pts = drained
                    grant.levels_lost = lost
            return grant

    async def grant_life(
        self, player: Player, skill: LifeSkillType, pts: int
    ) -> MasteryGrant:
        async with in_transaction():
            mastery, _ = await LifeSkillMastery.get_or_create(
                player=player, skill=skill
            )
            zero_sum = mastery.level >= MASTERY_SOFT_CAP
            mastery.level, mastery.exp, gained = apply_mastery_gain(
                mastery.level, mastery.exp, pts
            )
            await mastery.save(update_fields=["level", "exp"])

            grant = MasteryGrant(
                pts=pts, levels_gained=gained, category=skill.value
            )
            if zero_sum:
                pool = GATHER_SKILLS if skill in GATHER_SKILLS else CRAFT_SKILLS
                victims = [
                    m
                    for m in await LifeSkillMastery.filter(
                        player=player, skill__in=list(pool)
                    ).exclude(id=mastery.id)
                    if drainable_exp(m.level, m.exp) > 0
                ]
                if victims:
                    victim = random.choice(victims)
                    victim.level, victim.exp, drained, lost = apply_mastery_drain(
                        victim.level, victim.exp, pts
                    )
                    await victim.save(update_fields=["level", "exp"])
                    grant.drained_from = victim.skill.value
                    grant.drained_pts = drained
                    grant.levels_lost = lost
            return grant


class PatchRepo:
    """Query helpers over GamePatch: the applied baseline + the pending one."""

    async def current(self) -> "GamePatch | None":
        return (
            await GamePatch.filter(status=PatchStatus.APPLIED)
            .order_by("-applied_at")
            .first()
        )

    async def pending(self) -> "GamePatch | None":
        return await GamePatch.get_or_none(status=PatchStatus.PENDING)

    async def schedule(
        self,
        hash_: str,
        version: str,
        notes: str | None,
        summary: dict,
        lock_at: datetime,
        apply_at: datetime,
    ) -> "GamePatch | None":
        """Create the PENDING row, or None if one already exists."""
        async with in_transaction():
            existing = (
                await GamePatch.filter(status=PatchStatus.PENDING)
                .select_for_update()
                .first()
            )
            if existing is not None:
                return None
            return await GamePatch.create(
                hash=hash_, version=version, notes=notes, summary=summary,
                lock_at=lock_at, apply_at=apply_at,
            )

    async def cancel(self, patch: "GamePatch") -> None:
        patch.status = PatchStatus.CANCELLED
        await patch.save(update_fields=["status"])

    async def mark_applied(self, patch: "GamePatch") -> None:
        patch.status = PatchStatus.APPLIED
        patch.applied_at = datetime.now().astimezone()
        await patch.save(update_fields=["status", "applied_at"])

    async def record_applied(
        self, hash_: str, version: str, notes: str | None, summary: dict
    ) -> "GamePatch":
        """Direct apply (force update / first bootstrap): record as APPLIED."""
        return await GamePatch.create(
            hash=hash_, version=version, notes=notes, summary=summary,
            status=PatchStatus.APPLIED,
            applied_at=datetime.now().astimezone(),
        )


class DungeonRepo:
    """Query helpers over expeditions (DungeonInstance / DungeonParticipant)
    and hunting grounds.

    Enforces the one-ACTIVE-instance-per-legion rule that the schema cannot
    express (Tortoise has no partial unique indexes).
    """

    # -- grounds --

    async def unlocked_grounds(self, legion_level: int) -> list[HuntingGround]:
        return await HuntingGround.filter(
            min_legion_level__lte=legion_level, status=ContentStatus.ENABLED
        )

    async def ground_pool(self, ground: HuntingGround) -> list[GroundMob]:
        """The ground's encounter pool (enabled mobs only), mob prefetched."""
        return await GroundMob.filter(
            ground=ground, mob__status=ContentStatus.ENABLED
        ).prefetch_related("mob")

    async def drop_preview(self, mobs: list[Mob]) -> list[Material]:
        """Unique materials droppable by ANY of the given mobs (enabled only),
        sorted by rarity then name -- the ground detail 'possible drops' list."""
        drops = await MobDrop.filter(
            mob_id__in=[m.id for m in mobs], material__status=ContentStatus.ENABLED
        ).prefetch_related("material")
        unique = {d.material.id: d.material for d in drops}
        return sorted(unique.values(), key=lambda m: (m.rarity, m.name))

    async def roll_mob(
        self, ground: HuntingGround, rng: random.Random | None = None
    ) -> Mob | None:
        """Weighted encounter roll from the ground's pool (enabled mobs only)."""
        pool = await self.ground_pool(ground)
        if not pool:
            return None
        rng_ = rng or random
        entry = rng_.choices(pool, weights=[e.weight for e in pool], k=1)[0]
        if rng_.random() < RANDOM_ELITE_MOB_CHANCE: # 10% chance for higher stats
            promote_elite_mob(entry.mob)
        return entry.mob

    # -- lifecycle --

    async def active_for(self, legion: Legion) -> DungeonInstance | None:
        return await DungeonInstance.get_or_none(
            legion=legion, status=DungeonStatus.ACTIVE
        )

    async def active_for_player(self, player: Player) -> DungeonInstance | None:
        """The ACTIVE (pre-settlement) run this player has joined, or None.
        Ground prefetched for the block message."""
        dp = await DungeonParticipant.filter(
            player=player, instance__status=DungeonStatus.ACTIVE
        ).prefetch_related("instance__ground").first()
        return dp.instance if dp is not None else None

    async def spawn(
        self,
        legion: Legion,
        ground: HuntingGround,
        mob: Mob,
        expires_at: datetime,
        random_ground: bool = False,
    ) -> DungeonInstance | None:
        """Create an ACTIVE instance, or return None if one already exists."""
        async with in_transaction():
            existing = (
                await DungeonInstance.filter(
                    legion=legion, status=DungeonStatus.ACTIVE
                )
                .select_for_update()
                .first()
            )
            if existing is not None:
                return None
            return await DungeonInstance.create(
                legion=legion,
                ground=ground,
                mob=mob,
                expires_at=expires_at,
                random_ground=random_ground,
            )

    async def expire(self, instance: DungeonInstance) -> None:
        """Close a lobby that hit its deadline with nobody joined."""
        instance.status = DungeonStatus.EXPIRED
        instance.ended_at = datetime.now().astimezone()
        await instance.save(update_fields=["status", "ended_at"])

    async def join(self, instance: DungeonInstance, player: Player) -> bool:
        """Register a participant. Returns False if already joined."""
        _, created = await DungeonParticipant.get_or_create(
            instance=instance, player=player
        )
        return created

    async def settle(
        self,
        instance: DungeonInstance,
        status: DungeonStatus,
        participant_stats: dict[int, dict] | None = None,
    ) -> None:
        """Close a run: set final status and write per-run participant stats
        (``{player_id: {"damage_dealt": int, "died": bool}}``) in one batch.
        """
        async with in_transaction():
            instance.status = status
            instance.ended_at = datetime.now().astimezone()
            await instance.save(update_fields=["status", "ended_at"])

            for player_id, stats in (participant_stats or {}).items():
                await DungeonParticipant.filter(
                    instance=instance, player_id=player_id
                ).update(**stats)

    async def void_all_active(self) -> int:
        """Mark every ACTIVE instance VOIDED (bot boot after a restart lost
        their in-memory combat state). Returns the number voided."""
        return await DungeonInstance.filter(status=DungeonStatus.ACTIVE).update(
            status=DungeonStatus.VOIDED,
            ended_at=datetime.now().astimezone(),
        )
