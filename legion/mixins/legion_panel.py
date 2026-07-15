"""Legion panel mixin: /legion home, upgrade, daily supply, members, donate,
settings, and join/leave."""

from datetime import datetime, timezone

import discord
from discord import app_commands
from loguru import logger as log

from maki.cogs.legion import render, strings
from maki.cogs.legion.content import PATCH
from maki.cogs.legion.mixins.base import LegionCogBase
from maki.cogs.legion.model.model import (
    Legion,
    Material,
    Player,
    PlayerMaterial,
)
from maki.cogs.legion.utils import clean_legion_name
from maki.cogs.legion.views import (
    DonateView,
    LegionSettingsView,
    LegionView,
    MembersView,
)


class LegionPanelMixin(LegionCogBase):
    # --- /legion ---------------------------------------------------------------

    @app_commands.command(
        name=strings.LEGION_COMMAND_NAME, description=strings.LEGION_COMMAND_DESC
    )
    @app_commands.guild_only()
    async def legion(self, interaction: discord.Interaction) -> None:
        log.debug("/legion by user {}", interaction.user.id)
        await self._defer(interaction)  # public reply
        player = await self.ensure_player(interaction)
        if player is None:
            return
        await self.show_legion_home(interaction, edit=True)

    async def show_legion_home(
        self, interaction: discord.Interaction, edit: bool = True
    ) -> None:
        legion = await self._legion_for(interaction.guild)
        # The embed shows today's kills -- roll the daily window first.
        await self.legions.ensure_daily_reset(legion)
        player = await self.players.get(interaction.user.id)
        member_count = await Player.filter(legion=legion).count()
        active_count = await self.legions.active_member_count(legion)
        sheet = await self.legions.upgrade_sheet(legion)
        is_officer = interaction.user.guild_permissions.manage_guild or bool(
            player and player.is_legion_manager
        )
        embed = render.legion_embed(
            legion, member_count, active_count, sheet, self.bot.color
        )
        view = LegionView(
            self, interaction.user.id, legion, is_officer, maxed=not sheet
        )
        if edit:
            await self._edit_tracked(interaction, embed=embed, view=view)
        else:
            await interaction.response.send_message(embed=embed, view=view)
            view.message = await interaction.original_response()

    async def _is_officer(
        self, interaction: discord.Interaction, legion: Legion
    ) -> bool:
        if interaction.user.guild_permissions.manage_guild:
            return True
        player = await self.players.get(interaction.user.id)
        return bool(
            player and player.legion_id == legion.id and player.is_legion_manager
        )

    async def press_upgrade(
        self, interaction: discord.Interaction, legion: Legion
    ) -> None:
        if not await self._is_officer(interaction, legion):
            await self._notify(interaction, strings.LEGION_OFFICERS_ONLY)
            return
        if not await self.legions.upgrade_sheet(legion):  # no next-level cost
            await self._notify(interaction, strings.LEGION_UPGRADE_MAXED)
            return
        if await self.legions.upgrade(legion):
            await interaction.response.send_message(
                strings.LEGION_UPGRADE_DONE.format(
                    legion=legion.name, level=legion.level
                )
            )
        else:
            await self._notify(interaction, strings.LEGION_UPGRADE_SHORT)

    async def press_daily_supply(
        self, interaction: discord.Interaction, legion: Legion
    ) -> None:
        """Once-per-(UTC)-day supply claim. The player receives every reward at
        the HIGHEST contribution threshold they've reached -- not cumulative."""
        player = await self.players.get(interaction.user.id)
        if player is None:
            await self._notify(interaction, strings.LEGION_NOT_MEMBER)
            return
        now = datetime.now(timezone.utc)
        if (
            player.last_supply_at is not None
            and player.last_supply_at.astimezone(timezone.utc).date() >= now.date()
        ):
            await self._notify(interaction, strings.DAILY_SUPPLY_CLAIMED)
            return

        rewards = PATCH.get("daily_reward", [])
        thresholds = sorted({r["threshold"] for r in rewards})
        eligible = [t for t in thresholds if t <= player.contribution]
        if not eligible:
            if thresholds:
                await self._notify(
                    interaction,
                    strings.DAILY_SUPPLY_LOW.format(need=thresholds[0]),
                )
            else:
                await self._notify(interaction, strings.DAILY_SUPPLY_NONE)
            return

        best = max(eligible)
        granted: list[tuple[Material, int]] = []
        for r in rewards:
            if r["threshold"] != best:
                continue
            material = await Material.get_or_none(
                key=r["material"]
            ) or await Material.get_or_none(name=r["material"])
            if material is None:
                continue
            qty = int(r.get("qty", 1))
            await self.inventory.add_material(player, material, qty)
            granted.append((material, qty))
        if not granted:  # misconfigured threshold (all materials missing)
            await self._notify(interaction, strings.DAILY_SUPPLY_NONE)
            return

        player.last_supply_at = now
        await player.save(update_fields=["last_supply_at"])
        mats = "、".join(f"{m.name}×{q:,}" for m, q in granted)
        await self._notify(interaction, strings.DAILY_SUPPLY_RECEIVED.format(mats=mats))

    async def show_members(
        self, interaction: discord.Interaction, legion: Legion, page: int
    ) -> None:
        player = await self.players.get(interaction.user.id)
        size = MembersView.PAGE_SIZE
        total = await Player.filter(legion=legion).count()
        pages = max(1, -(-total // size))
        page = max(0, min(page, pages - 1))
        entries = (
            await Player.filter(legion=legion)
            .order_by("-contribution")
            .offset(page * size)
            .limit(size)
        )
        await self._edit_tracked(
            interaction,
            embed=render.members_embed(legion, entries, page, pages, self.bot.color),
            view=MembersView(self, interaction.user.id, player, legion, page, pages),
        )

    # --- donations -------------------------------------------------------------

    async def show_donate(
        self,
        interaction: discord.Interaction,
        legion: Legion,
        note: str | None = None,
        fresh: bool = False,
    ) -> None:
        """The donate panel: member's stacks tagged with upgrade-sheet needs.

        ``fresh=True`` (the /legion 捐贈 button, open to every member) sends
        the panel as the presser's OWN ephemeral message and leaves the shared
        legion embed untouched; the default edits in place -- the panel's own
        buttons refreshing themselves after a donation."""
        player = await self.players.get(interaction.user.id)
        if player is None or player.legion_id != legion.id:
            await self._notify(interaction, strings.DONATE_MEMBERS_ONLY)
            return
        sheet = await self.legions.upgrade_sheet(legion)
        sheet_map = {mat.id: (need, have) for mat, need, have in sheet}
        # Only upgrade-requirement materials are donatable; junk can't be dumped.
        stacks = [
            s
            for s in await PlayerMaterial.filter(
                player=player, quantity__gt=0
            ).prefetch_related("material")
            if s.material_id in sheet_map
        ]
        embed = render.donate_embed(legion, stacks, sheet_map, self.bot.color)
        view = DonateView(self, interaction.user.id, player, legion, stacks, sheet_map)
        if fresh:
            if interaction.response.is_done():
                view.message = await interaction.followup.send(
                    content=note, embed=embed, view=view, ephemeral=True, wait=True
                )
            else:
                await interaction.response.send_message(
                    content=note, embed=embed, view=view, ephemeral=True
                )
                view.message = await interaction.original_response()
            return
        await self._edit_tracked(interaction, content=note, embed=embed, view=view)

    async def do_donate(
        self,
        interaction: discord.Interaction,
        player: Player,
        legion: Legion,
        material_id: int,
        qty: int,
    ) -> None:
        await self._defer(interaction)
        if not await self.ensure_not_afk(interaction, player):
            return
        if not await self.ensure_alive(interaction, player):
            return
        material = await Material.get_or_none(id=material_id)
        sheet = await self.legions.upgrade_sheet(legion)
        sheet_map = {mat.id: (need, have) for mat, need, have in sheet}
        if material is None or material.id not in sheet_map:
            # Authoritative gate: only upgrade-requirement mats earn/donate.
            await self.show_donate(
                interaction,
                legion,
                note=strings.LEGION_DONATE_NOT_NEEDED.format(
                    material=material.name if material else "?"
                ),
            )
            return
        result = await self.legions.donate(
            player, legion, material, qty, need=sheet_map[material.id][0]
        )
        if result is None:
            note = strings.LEGION_DONATE_SHORT.format(material=material.name)
        else:
            accepted, contri = result
            if accepted == 0:
                note = strings.LEGION_STOCKPILE_FULL.format(material=material.name)
            else:
                template = (
                    strings.LEGION_DONATED_CAPPED
                    if accepted < qty
                    else strings.LEGION_DONATED
                )
                note = template.format(
                    qty=accepted, material=material.name, contri=contri
                )
                await self._announce_donation(
                    interaction, legion, player, material, accepted
                )
        await self.show_donate(interaction, legion, note=note)

    async def _announce_donation(
        self,
        interaction: discord.Interaction,
        legion: Legion,
        player: Player,
        material: Material,
        qty: int,
    ) -> None:
        """Post a public donation shout to the legion's appointed channel.
        Silently no-ops if no channel is configured or reachable."""
        if not legion.channel_id or interaction.guild is None:
            return
        channel = interaction.guild.get_channel(legion.channel_id)
        if channel is None:
            return
        # `have` from the sheet already reflects the just-committed donation
        # (fresh query); off-sheet materials fall back to a plain stockpile total.
        sheet = await self.legions.upgrade_sheet(legion)
        sheet_map = {mat.id: (need, have) for mat, need, have in sheet}
        if material.id in sheet_map:
            need, have = sheet_map[material.id]
        else:
            need, have = None, await self.legions.stockpiled(legion, material)
        embed = render.donation_announce_embed(
            player.username, qty, material, have, need, self.bot.color
        )
        await channel.send(embed=embed)

    # --- settings ----------------------------------------------------------------

    async def show_legion_settings(
        self, interaction: discord.Interaction, legion: Legion, note: str | None = None
    ) -> None:
        """Settings layer: current name/channel/managers + the selects."""
        if not await self._is_officer(interaction, legion):
            await self._notify(interaction, strings.LEGION_OFFICERS_ONLY)
            return
        managers = await Player.filter(legion=legion, is_legion_manager=True)
        await self._edit_tracked(
            interaction,
            content=note,
            embed=render.legion_settings_embed(legion, managers, self.bot.color),
            view=LegionSettingsView(self, interaction.user.id, legion),
        )

    async def set_channel(
        self, interaction: discord.Interaction, legion: Legion, channel_id: int
    ) -> None:
        if not await self._is_officer(interaction, legion):
            await self._notify(interaction, strings.LEGION_OFFICERS_ONLY)
            return
        legion.channel_id = channel_id
        await legion.save(update_fields=["channel_id"])
        await self.show_legion_settings(
            interaction,
            legion,
            note=strings.LEGION_CHANNEL_SET.format(channel=f"<#{channel_id}>"),
        )

    async def appoint_manager(
        self, interaction: discord.Interaction, legion: Legion, user: discord.User
    ) -> None:
        if not await self._is_officer(interaction, legion):
            await self._notify(interaction, strings.LEGION_OFFICERS_ONLY)
            return
        player = await self.players.get(user.id)
        if player is None or player.legion_id != legion.id:
            await self._notify(interaction, strings.DONATE_MEMBERS_ONLY)
            return
        player.is_legion_manager = True
        await player.save(update_fields=["is_legion_manager"])
        await self.show_legion_settings(
            interaction,
            legion,
            note=strings.LEGION_MANAGER_SET.format(player=player.username),
        )

    async def set_legion_name(
        self, interaction: discord.Interaction, legion: Legion, raw: str
    ) -> None:
        if not await self._is_officer(interaction, legion):
            await self._notify(interaction, strings.LEGION_OFFICERS_ONLY)
            return
        legion.name = clean_legion_name(raw)
        await legion.save(update_fields=["name"])
        await self.show_legion_settings(
            interaction,
            legion,
            note=strings.LEGION_RENAMED.format(name=legion.name),
        )

    # --- membership ----------------------------------------------------------------

    async def press_join_legion(
        self, interaction: discord.Interaction, legion: Legion
    ) -> None:
        player = await self.players.get(interaction.user.id)
        if player is None:
            await self._notify(interaction, strings.ONBOARD_ANY_CMD)
            return
        if not await self.ensure_not_afk(interaction, player):
            return
        if player.legion_id == legion.id:
            await self._notify(interaction, strings.LEGION_ALREADY_MEMBER)
            return
        await self.players.join_legion(player, legion)
        await self._notify(
            interaction, strings.LEGION_WELCOME.format(legion=legion.name)
        )

    async def press_leave_legion(
        self, interaction: discord.Interaction, legion: Legion
    ) -> None:
        player = await self.players.get(interaction.user.id)
        if player is None or player.legion_id != legion.id:
            await self._notify(interaction, strings.LEGION_NOT_MEMBER)
            return
        if not await self.ensure_not_afk(interaction, player):
            return
        await self.players.leave_legion(player)
        await self._notify(interaction, strings.LEGION_LEFT.format(legion=legion.name))
