"""Gather mixin: /gatherer -- AFK sessions at mine/garden sites, with payout
computed at stop (capped by the gather-mastery bag)."""

import discord
from discord import app_commands
from loguru import logger as log

from maki.cogs.legion import render, strings
from maki.cogs.legion.calculator import gather_payout_chunks, roll_drops
from maki.cogs.legion.constants import ContentStatus
from maki.cogs.legion.mixins.base import LegionCogBase
from maki.cogs.legion.model.model import LifeSkillMastery, Player, SiteYield
from maki.cogs.legion.views import GatherBusyView, GatherIdleView


class GatherMixin(LegionCogBase):
    @app_commands.command(
        name=strings.GATHERER_COMMAND_NAME, description=strings.GATHERER_COMMAND_DESC
    )
    @app_commands.guild_only()
    async def gatherer(self, interaction: discord.Interaction) -> None:
        log.debug("/resource by user {}", interaction.user.id)
        await self._defer(interaction, ephemeral=True)
        player = await self.ensure_player(interaction)
        if player is None:
            return
        activity = await self.activities.active_for(player)
        if activity is not None:
            possible = [
                y.material.name
                for y in await SiteYield.filter(site=activity.site).prefetch_related(
                    "material"
                )
            ]
            busy_view = GatherBusyView(self, interaction.user.id, player)
            await self._edit_tracked(
                interaction,
                embed=render.gather_busy_embed(activity, possible, self.bot.color),
                view=busy_view,
            )
            busy_view.message = await interaction.original_response()
            return
        if not await self.ensure_not_in_expedition(interaction, player):
            return
        # Sites unlock off the player's OWN legion -- gather loot is personal,
        # so visiting a higher-level guild must not open its sites (unlike
        # expeditions, which are the guild's activity with an outsider tax).
        own_level = (await player.legion).level if player.legion_id else 0
        sites = await self.activities.unlocked_sites(own_level)
        yields_by_site: dict[int, list[str]] = {}
        for y in await SiteYield.filter(
            site_id__in=[s.id for s in sites],
            material__status=ContentStatus.ENABLED,
        ).prefetch_related("material"):
            yields_by_site.setdefault(y.site_id, []).append(y.material.name)
        idle_view = GatherIdleView(self, interaction.user.id, player, sites)
        await self._edit_tracked(
            interaction,
            embed=render.gather_idle_embed(sites, yields_by_site, self.bot.color),
            view=idle_view,
        )
        idle_view.message = await interaction.original_response()

    async def start_gather(
        self, interaction: discord.Interaction, player: Player, site_id: int
    ) -> None:
        if self._patch_blocked(session_start=True):
            await self._send_patch_blocked(interaction)
            return
        if not await self.ensure_alive(interaction, player):
            return
        if not await self.ensure_not_in_expedition(interaction, player):
            return
        # Authoritative unlock check at START, not just at listing -- a stale
        # view (or a legion switch since) must not start a locked site.
        own_level = (await player.legion).level if player.legion_id else 0
        sites = await self.activities.unlocked_sites(own_level)
        site = next((s for s in sites if s.id == site_id), None)
        if site is None:
            await self._notify(interaction, strings.GATHER_NO_SUCH_SITE)
            return
        activity = await self.activities.start(player, site)
        if activity is None:
            await self._notify(interaction, strings.GATHER_BLOCKED_SHORT)
            return
        await self._edit_tracked(
            interaction,
            content=strings.GATHER_STARTED.format(site=site.name),
            embed=None,
            view=None,
        )

    async def stop_gather(
        self, interaction: discord.Interaction, player: Player
    ) -> None:
        await self._defer(interaction)
        activity = await self.activities.active_for(player)
        if activity is None:
            # _notify, NOT response.send_message -- the response token is
            # already spent by the defer above.
            await self._notify(interaction, strings.GATHER_NOTHING)
            return
        elapsed = await self.activities.stop(activity)
        mastery = await LifeSkillMastery.get_or_none(
            player=player, skill=activity.skill
        )
        level = mastery.level if mastery else 0
        chunks, pts = gather_payout_chunks(elapsed, level)

        yields = await SiteYield.filter(
            site=activity.site, material__status=ContentStatus.ENABLED
        ).prefetch_related("material")
        materials = {y.material_id: y.material for y in yields}
        rolled = roll_drops(yields, chunks)
        loot_parts = []
        for material_id, qty in rolled.items():
            await self.inventory.add_material(player, materials[material_id], qty)
            loot_parts.append(f"{materials[material_id].name}×{qty:,}")
        if pts:
            await self.masteries.grant_life(player, activity.skill, pts)

        result = strings.GATHER_STOPPED.format(
            site=activity.site.name,
            hours=elapsed // 60,
            minutes=elapsed % 60,
        )
        if loot_parts:
            result += strings.GATHER_RESULT.format(loot=", ".join(loot_parts), pts=pts)
        else:
            result += strings.GATHER_RESULT_EMPTY

        await self._edit_tracked(
            interaction,
            content=result,
            embed=None,
            view=None,
        )
