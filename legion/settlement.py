"""Dungeon-run settlement: the single place where a finished fight turns into
rewards -- mastery pts (with the outsider tax), material drops, participant
stats, and legion exp. The simulation engine hands this module its results;
the cog renders the returned report as the feedback log.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone

from maki.cogs.legion.calculator import MasteryGrant, roll_drops
from maki.cogs.legion.constants import (
    CONTRI_DAILY_FIRST_RUN,
    ContentStatus,
    DROP_ROLLS_PER_RUN,
    LEGION_EXP_PER_MOB_TIER,
    RANDOM_GROUND_DROP_ROLLS,
    RANDOM_GROUND_MASTERY_BONUS,
    MASTERY_PTS_JOIN,
    MASTERY_PTS_SURVIVED,
    MASTERY_PTS_TOP_DAMAGE,
    MASTERY_PTS_TOP_TANK,
    MASTERY_PTS_WIN,
    OUTSIDER_MASTERY_DIVISOR,
    DungeonStatus,
    WeaponSlot,
)
from maki.cogs.legion.model.model import (
    DungeonInstance,
    Material,
    MobDrop,
    Player,
    PlayerWeapon,
)
from maki.cogs.legion.model.repository import (
    DungeonRepo,
    LegionRepo,
    InventoryRepo,
    MasteryRepo,
)


@dataclass
class ParticipantResult:
    """What the simulation reports about one player at run end."""

    player: Player
    damage_dealt: int = 0
    damage_taken: int = 0
    died: bool = False
    final_hp: int | None = None  # persistent HP write-back; None = leave unchanged
    max_hp: int | None = None    # snapshot effective max: the slice-back anchor


@dataclass
class PlayerSettlement:
    """One player's line in the settlement log."""

    player: Player
    outsider: bool
    mastery_pts: int
    top_damage: bool = False
    top_tank: bool = False
    grant: MasteryGrant | None = None      # None = no main weapon equipped
    drops: list[tuple[Material, int]] = field(default_factory=list)
    daily_contri: int = 0                  # first fight of the day bonus


@dataclass
class SettlementReport:
    status: DungeonStatus
    players: list[PlayerSettlement]
    legion_exp: int = 0
    upgrade_ready: bool = False  # banked exp now covers the next level


def mastery_awards(
    results: list[ParticipantResult], won: bool
) -> tuple[dict[int, int], set[int], set[int]]:
    """Compute pts per player pk. Returns ``(pts, top_damage_ids, top_tank_ids)``.

    join=1, win=2, survived=2; top damage dealt=1 and top damage taken=1 are
    competitive (ties all win, zero-stat runs award nobody).
    """
    pts = {r.player.id: MASTERY_PTS_JOIN for r in results}
    top_damage: set[int] = set()
    top_tank: set[int] = set()

    if won:
        for r in results:
            pts[r.player.id] += MASTERY_PTS_WIN
    for r in results:
        if not r.died:
            pts[r.player.id] += MASTERY_PTS_SURVIVED

    max_dealt = max((r.damage_dealt for r in results), default=0)
    if max_dealt > 0:
        top_damage = {r.player.id for r in results if r.damage_dealt == max_dealt}
        for pid in top_damage:
            pts[pid] += MASTERY_PTS_TOP_DAMAGE
    max_taken = max((r.damage_taken for r in results), default=0)
    if max_taken > 0:
        top_tank = {r.player.id for r in results if r.damage_taken == max_taken}
        for pid in top_tank:
            pts[pid] += MASTERY_PTS_TOP_TANK

    return pts, top_damage, top_tank


class SettlementService:
    def __init__(
        self,
        dungeons: DungeonRepo,
        masteries: MasteryRepo,
        inventory: InventoryRepo,
        legions: LegionRepo,
    ) -> None:
        self.dungeons = dungeons
        self.masteries = masteries
        self.inventory = inventory
        self.legions = legions

    async def settle(
        self,
        instance: DungeonInstance,
        results: list[ParticipantResult],
        won: bool,
        rng: random.Random | None = None,
    ) -> SettlementReport:
        # A loss here always means the party FOUGHT and fell short (deaths or
        # the mob outlived its rounds limit); empty lobbies never reach settle
        # (DungeonRepo.expire handles those).
        status = DungeonStatus.CLEARED if won else DungeonStatus.FAILED
        report = SettlementReport(status=status, players=[])

        pts_by_player, top_damage, top_tank = mastery_awards(results, won)
        if won and instance.random_ground:
            # Explorer's bonus: venturing into the unknown pays extra.
            for pid in pts_by_player:
                pts_by_player[pid] += RANDOM_GROUND_MASTERY_BONUS
        drop_rolls = (
            RANDOM_GROUND_DROP_ROLLS if instance.random_ground else DROP_ROLLS_PER_RUN
        )
        drops = (
            await MobDrop.filter(
                mob_id=instance.mob_id,
                material__status=ContentStatus.ENABLED,  # disabled mats never drop
            ).prefetch_related("material")
            if won
            else []
        )
        materials = {d.material_id: d.material for d in drops}

        for result in results:
            player = result.player
            outsider = player.legion_id != instance.legion_id
            pts = pts_by_player[player.id]
            if outsider:
                pts = max(1, pts // OUTSIDER_MASTERY_DIVISOR)

            line = PlayerSettlement(
                player=player,
                outsider=outsider,
                mastery_pts=pts,
                top_damage=player.id in top_damage,
                top_tank=player.id in top_tank,
            )

            main = await PlayerWeapon.get_or_none(
                player=player, equipped_slot=WeaponSlot.MAIN
            ).prefetch_related("weapon__category")
            if main is not None:
                line.grant = await self.masteries.grant_weapon(
                    player, main.weapon.category, pts
                )

            if won and not outsider and drops:
                rolled = roll_drops(drops, drop_rolls, rng)
                for material_id, qty in rolled.items():
                    material = materials[material_id]
                    await self.inventory.add_material(player, material, qty)
                    line.drops.append((material, qty))

            if result.final_hp is not None:
                # Effective max IS the real max now; the snapshot max is the
                # slice-back anchor for future combat-only HP boosts.
                cap = result.max_hp or player.max_health_points
                player.health_points = min(result.final_hp, cap)
                # Re-bookmark regen so pre-fight downtime can't heal the
                # damage the fight just dealt.
                player.hp_updated_at = datetime.now(timezone.utc)
                await player.save(update_fields=["health_points", "hp_updated_at"])

            # Daily contribution: first fight of the UTC day, own legion only.
            if not outsider:
                now = datetime.now(timezone.utc)
                if player.last_daily_at is None or player.last_daily_at.astimezone(
                    timezone.utc
                ).date() < now.date():
                    player.contribution += CONTRI_DAILY_FIRST_RUN
                    player.last_daily_at = now
                    await player.save(
                        update_fields=["contribution", "last_daily_at"]
                    )
                    line.daily_contri = CONTRI_DAILY_FIRST_RUN

            report.players.append(line)

        await self.dungeons.settle(
            instance,
            status,
            {
                r.player.id: {
                    "damage_dealt": r.damage_dealt,
                    "damage_taken": r.damage_taken,
                    "died": r.died,
                }
                for r in results
            },
        )

        if won:
            legion = await instance.legion
            mob = await instance.mob
            report.legion_exp = mob.tier * LEGION_EXP_PER_MOB_TIER
            # Exp banks only -- leveling is the manual Upgrade act. The flag
            # tells the cog to post the "ready to upgrade" reminder.
            report.upgrade_ready = await self.legions.add_exp(
                legion, report.legion_exp
            )
            await self.legions.add_kills(legion)

        return report
