"""discord.ui views and modals for the legion cog.

Views are thin: they gate who may press what, then delegate to the cog's
service methods and re-render via render.py. No game logic lives here.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import discord

from maki.cogs.legion import render, strings
from maki.cogs.legion.constants import (
    LOBBY_SECONDS,
    MASTERY_KIND_LIFE,
    MASTERY_KIND_WEAPONS,
)
from maki.cogs.legion.model.model import (
    GatherSite,
    HuntingGround,
    Legion,
    Player,
    PlayerWeapon,
    Recipe,
    Weapon,
)
from maki.cogs.legion.utils import clean_player_name

if TYPE_CHECKING:
    from maki.cogs.legion.cog import LegionCog

RANDOM_GROUND_VALUE = "__random__"

from maki.core.constants import interaction_error
from maki.core.view import GenericEmbedPaginator
from .strings import *


class _AuthorOnly(discord.ui.View):
    """Base: only the invoking user may interact. Tracks its message (set at
    send time by the cog, refreshed on every component press) so on_timeout
    can strip the dead buttons from the message."""

    def __init__(self, author_id: int, timeout: float | None = 180):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.message is not None:
            self.message = interaction.message
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                interaction_error["InteractionNotAuthor"], ephemeral=True
            )
            return False
        return True

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


# --- onboarding ---------------------------------------------------------------

class OnboardView(_AuthorOnly):
    """Ephemeral starter-weapon pick; creates the player on press."""

    def __init__(self, cog: "LegionCog", legion: Legion, starters: list[Weapon]):
        super().__init__(author_id=0, timeout=300)  # author set per-send
        self.cog = cog
        self.legion = legion
        for weapon in starters:
            self.add_item(self._button(weapon))

    def _button(self, weapon: Weapon) -> discord.ui.Button:
        button = discord.ui.Button(
            label=weapon.name, style=discord.ButtonStyle.primary
        )

        async def callback(interaction: discord.Interaction) -> None:
            player = await self.cog.onboard(
                interaction.user, self.legion, weapon
            )
            await interaction.response.edit_message(
                content=strings.ONBOARD_WELCOME.format(
                    legion=self.legion.name,
                    player=player.username,
                    weapon=weapon.name,
                ),
                view=None,
            )

        button.callback = callback
        return button

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.message is not None:
            self.message = interaction.message
        return True  # ephemeral message: only the target can see it anyway


# --- expedition ------------------------------------------------------------------

class GroundSelectView(_AuthorOnly):
    """Ephemeral two-layer picker. Layer 1 (selected=None): ground list embed,
    launch button reads 隨機遠征. Layer 2 (selected=ground): that ground's
    intel embed, launch button reads 發起遠征, plus a return button. The
    select persists on BOTH layers, so switching grounds is one click."""

    def __init__(
        self,
        cog: "LegionCog",
        author_id: int,
        grounds: list[HuntingGround],
        selected: HuntingGround | None = None,
    ):
        super().__init__(author_id=author_id)
        self.cog = cog
        options = [
            discord.SelectOption(
                label=g.name,
                value=str(g.id),
                description=f"{DANGER_TITLE}{EXPONENT_TITLE} {g.danger}",
                default=selected is not None and g.id == selected.id,
            )
            for g in grounds[:25]
        ]
        select = discord.ui.Select(
            placeholder=f"{CHOOSE_TITLE}{HUNTING_TITLE}{AREA_TITLE}...", options=options
        )

        async def on_select(interaction: discord.Interaction) -> None:
            await self.cog.show_ground_detail(interaction, int(select.values[0]))

        select.callback = on_select
        self.add_item(select)

        launch = discord.ui.Button(
            label=EXPEDITION_START_TITLE if selected else EXPEDITION_RANDOM_TITLE,
            style=discord.ButtonStyle.success,
            emoji=BATTLE_EMOJI,
        )

        async def on_launch(interaction: discord.Interaction) -> None:
            if selected is None:
                await self.cog.start_expedition(interaction, True, RANDOM_GROUND_VALUE)
            else:
                await self.cog.start_expedition(interaction, False, str(selected.id))

        launch.callback = on_launch
        self.add_item(launch)

        if selected is not None:
            back = discord.ui.Button(
                label=RETURN_TITLE, style=discord.ButtonStyle.secondary
            )

            async def on_back(interaction: discord.Interaction) -> None:
                await self.cog.show_ground_list(interaction, edit=True)

            back.callback = on_back
            self.add_item(back)


class UseItemView(_AuthorOnly):
    """Ephemeral picker under the 使用道具 context menu: the INVOKER'S
    consumable stacks; the chosen one is spent on the target (potions
    revive dead targets, food feeds living ones)."""

    def __init__(
        self,
        cog: "LegionCog",
        author_id: int,
        target_discord_id: int,
        stacks: list,  # PlayerMaterial with material prefetched
    ):
        super().__init__(author_id=author_id)
        self.cog = cog
        options = []
        for s in stacks[:25]:
            m = s.material
            if m.kind.value == "food":
                desc = INVENTORY_REGEN_EFFECT.format(
                    value=m.stat_bonus_value or 0, duration=m.duration or 0
                )
            else:
                desc = f"{INVENTORY_HEAL_EFFECT.format(value=m.stat_bonus_value or 0)} · {POTION_REVIVE_TAG}"
            options.append(
                discord.SelectOption(
                    label=f"{m.name} {TIMES_EMOJI}{s.quantity}",
                    value=str(m.id),
                    description=desc[:100],
                )
            )
        select = discord.ui.Select(
            placeholder=f"{CHOOSE_TITLE}{MATERIAL_TITLE}...", options=options
        )

        async def on_pick(interaction: discord.Interaction) -> None:
            await self.cog.use_item_on(
                interaction, target_discord_id, int(select.values[0])
            )

        select.callback = on_pick
        self.add_item(select)


class LobbyView(discord.ui.View):
    """The public Join button under the expedition announcement."""

    def __init__(self, cog: "LegionCog", instance_id: int):
        super().__init__(timeout=LOBBY_SECONDS + 30)
        self.cog = cog
        self.instance_id = instance_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.message is not None:
            self.message = interaction.message
        return True

    async def on_timeout(self) -> None:
        # Safety net only: _run_lobby edits the view away at expiry.
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    @discord.ui.button(label=JOIN_TITLE, style=discord.ButtonStyle.success, emoji=BATTLE_EMOJI)
    async def join(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.join_expedition(interaction, self.instance_id)


# --- settlement -------------------------------------------------------------------

def _combat_log_button(log_text: str) -> discord.ui.Button:
    """戰鬥紀錄: hands the presser the full fight as an EPHEMERAL rounds.log.
    A fresh discord.File per press -- file objects are single-use."""
    button = discord.ui.Button(
        label=COMBAT_LOG_BUTTON, style=discord.ButtonStyle.secondary
    )

    async def callback(interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            file=discord.File(
                io.BytesIO(log_text.encode("utf-8")),
                filename=COMBAT_LOG_FILENAME,
            ),
            ephemeral=True,
        )

    button.callback = callback
    return button


class CombatLogView(discord.ui.View):
    """Single-page settlement: just the public 戰鬥紀錄 button (the paginator
    carries its own copy). Times out like the pager and strips itself."""

    def __init__(self, log_text: str):
        super().__init__(timeout=600)
        self.message: discord.Message | None = None
        self.add_item(_combat_log_button(log_text))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.message is not None:
            self.message = interaction.message
        return True  # public message, public button

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass


class SettlementPaginator(GenericEmbedPaginator):
    """Public settlement pages: open to EVERYONE (shared page state), no
    close button (nobody should delete the legion's battle record), plus a
    my-result button that answers each presser EPHEMERALLY with their own
    line -- off-page players never need to touch the pager."""

    def __init__(
        self,
        embeds: list[discord.Embed],
        personal: dict[int, str],
        log_text: str | None = None,
    ):
        super().__init__(embeds, author=None, timeout=600)
        self.personal = personal
        self.message: discord.Message | None = None
        self.remove_item(self.remove)  # inherited close/delete button
        if log_text:
            self.add_item(_combat_log_button(log_text))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.message is not None:
            self.message = interaction.message
        return True  # public message, public buttons

    async def on_timeout(self) -> None:
        if self.message is not None:
            try:
                await self.message.edit(view=None)
            except discord.HTTPException:
                pass

    @discord.ui.button(label=SETTLE_MY_RESULT, style=discord.ButtonStyle.primary)
    async def my_result(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        text = self.personal.get(interaction.user.id)
        await interaction.response.send_message(
            text or SETTLE_MY_RESULT_NONE, ephemeral=True
        )


# --- legion ---------------------------------------------------------------------

class LegionView(_AuthorOnly):
    def __init__(
        self,
        cog: "LegionCog",
        author_id: int,
        legion: Legion,
        is_officer: bool,
        maxed: bool = False,
    ):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.legion = legion
        if not is_officer:
            self.upgrade.disabled = True
            self.settings.disabled = True
        if maxed:  # no next-level cost defined: nothing left to upgrade into
            self.upgrade.disabled = True

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # These two aren't author-gated: Upgrade is perm-gated (any officer),
        # and Daily Supply is personal (any member claims their own).
        if interaction.message is not None:
            self.message = interaction.message
        open_buttons = {self.upgrade.custom_id, self.daily_supply.custom_id}
        if interaction.data and interaction.data.get("custom_id") in open_buttons:
            return True
        return await super().interaction_check(interaction)

    @discord.ui.button(
            label=UPGRADE_TITLE, style=discord.ButtonStyle.primary, 
            emoji=UP_EMOJI, row=0   
            )
    async def upgrade(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.press_upgrade(interaction, self.legion)

    @discord.ui.button(label=DONATE_TITLE, style=discord.ButtonStyle.success, row=0)
    async def donate(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_donate(interaction, self.legion)

    @discord.ui.button(label=MEMBERS_TITLE, style=discord.ButtonStyle.secondary, row=0)
    async def members(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_members(interaction, self.legion, page=0)

    @discord.ui.button(label=DAILY_SUPPLY_TITLE, style=discord.ButtonStyle.success, row=1)
    async def daily_supply(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.press_daily_supply(interaction, self.legion)

    @discord.ui.button(
            label=LEGION_SETTINGS_TITLE, style=discord.ButtonStyle.secondary,
            emoji=COG_EMOJI, row=1
            )
    async def settings(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_legion_settings(interaction, self.legion)


class LegionNameModal(discord.ui.Modal):
    """Rename the legion -- same pattern as the profile nickname modal."""

    def __init__(self, cog: "LegionCog", legion: Legion):
        super().__init__(title=PROFILE_CHANGE_NICK)
        self.cog = cog
        self.legion = legion
        self.name = discord.ui.TextInput(
            label=LEGION_RENAME_PROMPT, max_length=64
        )
        self.add_item(self.name)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.set_legion_name(
            interaction, self.legion, str(self.name.value)
        )


class LegionSettingsView(_AuthorOnly):
    """Settings layer: current values in the embed; channel + manager selects
    and the rename modal live here. Officer-gated by the cog."""

    def __init__(self, cog: "LegionCog", author_id: int, legion: Legion):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.legion = legion
        self.add_item(self._channel_select())
        self.add_item(self._manager_select())

    def _channel_select(self) -> discord.ui.ChannelSelect:
        select = discord.ui.ChannelSelect(
            placeholder=LEGION_SET_CHANNEL,
            channel_types=[discord.ChannelType.text],
            row=1,
        )

        async def callback(interaction: discord.Interaction) -> None:
            await self.cog.set_channel(
                interaction, self.legion, select.values[0].id
            )

        select.callback = callback
        return select

    def _manager_select(self) -> discord.ui.UserSelect:
        select = discord.ui.UserSelect(placeholder=LEGION_SET_MANAGER, row=2)

        async def callback(interaction: discord.Interaction) -> None:
            await self.cog.appoint_manager(
                interaction, self.legion, select.values[0]
            )

        select.callback = callback
        return select

    @discord.ui.button(label=PROFILE_CHANGE_NICK, style=discord.ButtonStyle.secondary, row=3)
    async def rename(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(
            LegionNameModal(self.cog, self.legion)
        )

    @discord.ui.button(label=RETURN_TITLE, style=discord.ButtonStyle.secondary, row=3)
    async def back(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_legion_home(interaction)


class DonateQtyModal(discord.ui.Modal):
    def __init__(
        self,
        cog: "LegionCog",
        player: Player,
        legion: Legion,
        material_id: int,
        max_qty: int,
    ):
        super().__init__(title=DONATE_TITLE)
        self.cog = cog
        self.player = player
        self.legion = legion
        self.material_id = material_id
        self.max_qty = max_qty
        self.qty = discord.ui.TextInput(
            label=DONATE_QTY_LABEL,
            placeholder=DONATE_QTY_PLACEHOLDER.format(max=max_qty),
            default=str(max_qty),
            max_length=6,
        )
        self.add_item(self.qty)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            qty = int(str(self.qty.value))
        except ValueError:
            qty = 0
        if qty < 1 or qty > self.max_qty:
            await interaction.response.send_message(
                DONATE_INVALID_QTY, ephemeral=True
            )
            return
        await self.cog.do_donate(
            interaction, self.player, self.legion, self.material_id, qty
        )


class DonateView(_AuthorOnly):
    """Material select (upgrade-sheet needs tagged) -> quantity modal."""

    def __init__(
        self,
        cog: "LegionCog",
        author_id: int,
        player: Player,
        legion: Legion,
        stacks: list,  # PlayerMaterial with material prefetched
        sheet_map: dict[int, tuple[int, int]],
    ):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.player = player
        self.legion = legion
        self.stacks = {s.material_id: s for s in stacks}
        if stacks:
            options = [
                discord.SelectOption(
                    label=INVENTORY_CONSUMABLE_NAME.format(
                        material=s.material.name, qty=s.quantity
                    ),
                    value=str(s.material_id),
                    description=(
                        DONATE_NEEDED_TAG.format(
                            have=sheet_map[s.material_id][1],
                            need=sheet_map[s.material_id][0],
                        )
                        if s.material_id in sheet_map
                        else None
                    ),
                )
                for s in stacks[:25]
            ]
            select = discord.ui.Select(placeholder=DONATE_PICK, options=options)

            async def callback(interaction: discord.Interaction) -> None:
                material_id = int(select.values[0])
                stack = self.stacks[material_id]
                await interaction.response.send_modal(
                    DonateQtyModal(
                        self.cog, self.player, self.legion,
                        material_id, stack.quantity,
                    )
                )

            select.callback = callback
            self.add_item(select)

    @discord.ui.button(label=RETURN_TITLE, style=discord.ButtonStyle.secondary, row=2)
    async def back(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_legion_home(interaction)


class MembersView(_AuthorOnly):
    PAGE_SIZE = 10

    def __init__(
        self,
        cog: "LegionCog",
        author_id: int,
        player: Player | None,
        legion: Legion,
        page: int,
        pages: int,
    ):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.legion = legion
        self.page = page
        self.prev.disabled = page <= 0
        self.next.disabled = page >= pages - 1
        
        if isinstance(player, Player) and (player.legion_id == legion.id):
            self.add_item(self._leave_button())
        else:
            self.add_item(self._join_button())
        
    @discord.ui.button(label=RETURN_TITLE, style=discord.ButtonStyle.secondary, row=1)
    async def back(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_legion_home(interaction)

    @discord.ui.button(label=ARROW_LEFT_EMOJI, style=discord.ButtonStyle.secondary, row=0)
    async def prev(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_members(interaction, self.legion, self.page - 1)

    @discord.ui.button(label=ARROW_RIGHT_EMOJI, style=discord.ButtonStyle.secondary, row=0)
    async def next(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_members(interaction, self.legion, self.page + 1)

    def _join_button(self) -> discord.ui.Button:
        button = discord.ui.Button(
            label=JOIN_TITLE + LEGION_REFER, style=discord.ButtonStyle.success, row=1
        )

        async def callback(interaction: discord.Interaction) -> None:
            await self.cog.press_join_legion(interaction, self.legion)

        button.callback = callback
        return button
    
    def _leave_button(self) -> discord.ui.Button:
        button = discord.ui.Button(
            label=LEAVE_TITLE + LEGION_REFER, style=discord.ButtonStyle.danger, row=1
        )

        async def callback(interaction: discord.Interaction) -> None:
            await self.cog.press_leave_legion(interaction, self.legion)

        button.callback = callback
        return button


# --- profile ---------------------------------------------------------------------

class NicknameModal(discord.ui.Modal, title=PROFILE_CHANGE_NICK):
    nickname = discord.ui.TextInput(label=PROFILE_CHANGE_NICK_PROMPT, max_length=32)

    def __init__(self, cog: "LegionCog", player: Player):
        super().__init__()
        self.cog = cog
        self.player = player

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = clean_player_name(str(self.nickname.value))
        await self.cog.players.set_username(self.player, name)
        await interaction.response.send_message(
            PROFILE_NEW_NICK.format(nickname=name), ephemeral=True
        )


class ProfileView(_AuthorOnly):
    def __init__(
        self,
        cog: "LegionCog",
        author_id: int,
        player: Player,
        show_return: bool = False,
    ):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.player = player
        if show_return:
            self.add_item(self._return_button())

    def _return_button(self) -> discord.ui.Button:
        button = discord.ui.Button(
            label=RETURN_TITLE, style=discord.ButtonStyle.secondary, row=1
        )

        async def callback(interaction: discord.Interaction) -> None:
            await self.cog.show_profile(interaction, self.player, edit=True)

        button.callback = callback
        return button

    @discord.ui.button(label=INVENTORY_TITLE, style=discord.ButtonStyle.primary)
    async def inventory(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_inventory(interaction, self.player)

    @discord.ui.button(label=PROFILE_MASTERY, style=discord.ButtonStyle.secondary)
    async def mastery(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_mastery(interaction, self.player)

    @discord.ui.button(label=PROFILE_CHANGE_NICK, style=discord.ButtonStyle.secondary)
    async def nickname(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_modal(NicknameModal(self.cog, self.player))


class LegionMasteryView(_AuthorOnly):
    """The mastery page: a select flips between the weapon-grip pool and the
    life-skill pool (one embed each -- both at once was too crowded)."""

    def __init__(
        self, cog: "LegionCog", author_id: int, player: Player, kind: str
    ):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.player = player
        select = discord.ui.Select(
            options=[
                discord.SelectOption(
                    label=MASTERY_WEAPON,
                    value=MASTERY_KIND_WEAPONS,
                    default=kind == MASTERY_KIND_WEAPONS,
                ),
                discord.SelectOption(
                    label=MASTERY_LIFE,
                    value=MASTERY_KIND_LIFE,
                    default=kind == MASTERY_KIND_LIFE,
                ),
            ],
        )

        async def on_pick(interaction: discord.Interaction) -> None:
            await self.cog.show_mastery(
                interaction, self.player, kind=select.values[0]
            )

        select.callback = on_pick
        self.add_item(select)

    @discord.ui.button(label=RETURN_TITLE, style=discord.ButtonStyle.secondary, row=1)
    async def back(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_profile(interaction, self.player, edit=True)


KIND_WEAPONS = "weapons"
KIND_CONSUMABLES = "consumables"


class InventoryHomeView(_AuthorOnly):
    """Layer 1: //category picker (weapons / consumables) + return to profile."""

    def __init__(self, cog: "LegionCog", author_id: int, player: Player):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.player = player
        select = discord.ui.Select(
            placeholder=INVENTORY_CATEGORY_PICK,
            options=[
                discord.SelectOption(
                    label=INVENTORY_WEAPONS_TITLE,
                    value=KIND_WEAPONS,
                    description=INVENTORY_CATEGORY_WEAPONS_DESC,
                ),
                discord.SelectOption(
                    label=INVENTORY_CONSUMABLE_DESC,
                    value=KIND_CONSUMABLES,
                    description=INVENTORY_CATEGORY_CONSUMABLES_DESC,
                ),
            ],
        )

        async def callback(interaction: discord.Interaction) -> None:
            await self.cog.show_inventory_category(
                interaction, self.player, select.values[0]
            )

        select.callback = callback
        self.add_item(select)

    @discord.ui.button(label=RETURN_TITLE, style=discord.ButtonStyle.secondary, row=2)
    async def back(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_profile(interaction, self.player, edit=True)


class InventoryCategoryView(_AuthorOnly):
    """Layer 2: one category's items in a select, Use (+ Dismantle for
    weapons), Return to the inventory home."""

    def __init__(
        self,
        cog: "LegionCog",
        author_id: int,
        player: Player,
        kind: str,
        weapons: list[PlayerWeapon] | None = None,
        consumables: list | None = None,
    ):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.player = player
        self.kind = kind
        self.selected: str | None = None
        if kind == KIND_WEAPONS:
            options = [
                discord.SelectOption(
                    label=INVENTORY_WEAPON_NAME.format(
                        quality=WEAPON_QUALITY_NAMES[w.quality.value],
                        weapon=w.weapon.name,
                    ).strip(),
                    value=f"w:{w.id}",
                    description=(
                        (INVENTORY_MAIN if w.weapon.main_weapon else INVENTORY_SUB)
                        + (f" ({INVENTORY_EQUIPPED})" if w.equipped_slot else "")
                    ),
                )
                for w in (weapons or [])[:25]
            ]
        else:
            options = [
                discord.SelectOption(
                    label=INVENTORY_CONSUMABLE_NAME.format(
                        material=s.material.name, qty=s.quantity
                    ),
                    value=f"m:{s.material_id}",
                    emoji="🧪",
                    description=INVENTORY_CONSUMABLE_DESC,
                )
                for s in (consumables or [])[:25]
            ]
        if options:
            select = discord.ui.Select(placeholder=INVENTORY_CHOOSE, options=options)

            async def callback(interaction: discord.Interaction) -> None:
                self.selected = select.values[0]
                if self.selected.startswith("w:"):
                    # weapons: selection opens the detail layer
                    await self.cog.show_weapon_detail(
                        interaction, self.player, int(self.selected[2:])
                    )
                    return
                chosen = next(
                    o for o in select.options if o.value == select.values[0]
                )
                prefix = (
                    f"{chosen.emoji} "
                    if chosen.emoji and not str(chosen.emoji).startswith("<")
                    else ""
                )
                select.placeholder = f"{prefix}{chosen.label}"[:150]
                self.use.disabled = False
                await interaction.response.edit_message(view=self)

            select.callback = callback
            self.add_item(select)
        self.use.disabled = True
        self.dismantle.disabled = True
        if kind == KIND_WEAPONS:
            # use/dismantle live on the weapon DETAIL layer now
            self.remove_item(self.use)
            self.remove_item(self.dismantle)
        else:
            self.remove_item(self.dismantle)

    @discord.ui.button(label=INVENTORY_USE, style=discord.ButtonStyle.green, row=2)
    async def use(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.press_use(interaction, self.player, self.selected)

    @discord.ui.button(label=INVENTORY_DISMANTLE, style=discord.ButtonStyle.gray, row=2)
    async def dismantle(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.press_dismantle(interaction, self.player, self.selected)

    @discord.ui.button(label=RETURN_TITLE, style=discord.ButtonStyle.secondary, row=2)
    async def back(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_inventory(interaction, self.player)


class WeaponDetailView(_AuthorOnly):
    """Layer 3: one weapon. Use equips into its hand, Dismantle destroys
    (unequipped only), Return goes back to the weapons list."""

    def __init__(
        self, cog: "LegionCog", author_id: int, player: Player, pw_id: int
    ):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.player = player
        self.pw_id = pw_id

    @discord.ui.button(label=INVENTORY_USE, style=discord.ButtonStyle.green)
    async def use(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.press_detail_equip(interaction, self.player, self.pw_id)

    @discord.ui.button(label=INVENTORY_DISMANTLE, style=discord.ButtonStyle.gray)
    async def dismantle(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.press_dismantle(
            interaction, self.player, f"w:{self.pw_id}"
        )

    @discord.ui.button(label=RETURN_TITLE, style=discord.ButtonStyle.secondary)
    async def back(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_inventory_category(
            interaction, self.player, KIND_WEAPONS
        )


# --- gathering ---------------------------------------------------------------------

class GatherIdleView(_AuthorOnly):
    def __init__(
        self,
        cog: "LegionCog",
        author_id: int,
        player: Player,
        sites: list[GatherSite],
    ):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.player = player
        options = [
            discord.SelectOption(
                label=s.name, 
                value=str(s.id), 
                description=strings.GATHER_SKILL_TYPES.get(s.skill.value, s.skill.value)
            )
            for s in sites[:25]
        ]
        select = discord.ui.Select(placeholder=PICK_DESTINATION_TITLE, options=options)

        async def callback(interaction: discord.Interaction) -> None:
            await self.cog.start_gather(
                interaction, self.player, int(select.values[0])
            )

        select.callback = callback
        self.add_item(select)


class GatherBusyView(_AuthorOnly):
    def __init__(self, cog: "LegionCog", author_id: int, player: Player):
        super().__init__(author_id=author_id, timeout=None)
        self.cog = cog
        self.player = player

    @discord.ui.button(label=LEAVE_TITLE, style=discord.ButtonStyle.danger)
    async def stop_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.stop_gather(interaction, self.player)


# --- patching ---------------------------------------------------------------------

class PatchView(_AuthorOnly):
    """Stage 1: current patch + 'Check for update' (enables View update on a
    hash mismatch). If a patch is already scheduled, shows Cancel instead."""

    def __init__(self, cog: "LegionCog", author_id: int, pending_exists: bool):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.view_update.disabled = True
        if pending_exists:
            self.clear_items()
            self.add_item(self._cancel_scheduled())

    @discord.ui.button(label=PATCH_CHECK, style=discord.ButtonStyle.primary, emoji="🔍")
    async def check(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        # The cog flips the button states on this view before responding.
        await self.cog.patch_check(interaction, self)

    @discord.ui.button(label=PATCH_VIEW_UPDATE, style=discord.ButtonStyle.success, emoji="📋")
    async def view_update(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.patch_show_compare(interaction)

    def _cancel_scheduled(self) -> discord.ui.Button:
        button = discord.ui.Button(
            label=PATCH_CANCELLED, style=discord.ButtonStyle.danger
        )

        async def callback(interaction: discord.Interaction) -> None:
            await self.cog.patch_cancel_scheduled(interaction)

        button.callback = callback
        return button


class PatchDecisionView(_AuthorOnly):
    """Stage 2: the diff is on screen — Update / Cancel, Force on row 2."""

    def __init__(self, cog: "LegionCog", author_id: int):
        super().__init__(author_id=author_id)
        self.cog = cog

    @discord.ui.button(label=PATCH_UPDATE, style=discord.ButtonStyle.success, emoji="🗓️")
    async def update(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.patch_schedule(interaction)

    @discord.ui.button(label=CANCEL_TITLE, style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            content=PATCH_CANCELLED, embed=None, view=None
        )

    @discord.ui.button(
        label=PATCH_FORCE_UPDATE, style=discord.ButtonStyle.danger, emoji="⚠️", row=1
    )
    async def force(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        confirm = ForceConfirmView(self.cog, interaction.user.id)
        await interaction.response.send_message(
            strings.PATCH_FORCE_CONFIRM, view=confirm, ephemeral=True
        )
        confirm.message = await interaction.original_response()


class ForceConfirmView(_AuthorOnly):
    """Stage 3: the two-stage predicate for force updates."""

    def __init__(self, cog: "LegionCog", author_id: int):
        super().__init__(author_id=author_id, timeout=60)
        self.cog = cog

    @discord.ui.button(label=f"{CONFIRM_TITLE}{PATCH_FORCE_UPDATE}", style=discord.ButtonStyle.danger)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.patch_apply_now(interaction)

    @discord.ui.button(label=CANCEL_TITLE, style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            content=CANCEL_TITLE + PATCH_FORCE_UPDATE, view=None
        )


# --- crafting ---------------------------------------------------------------------

class CraftHomeView(_AuthorOnly):
    """Top level: one button per workstation; the embed shows masteries and
    what each station can make."""

    def __init__(self, cog: "LegionCog", author_id: int, player: Player):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.player = player

    @discord.ui.button(label=FORGE_TITLE, style=discord.ButtonStyle.primary, emoji=FORGE_EMOJI)
    async def forge(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_craft_surface(interaction, self.player, "forge")

    @discord.ui.button(label=COOK_TITLE, style=discord.ButtonStyle.primary, emoji=COOK_EMOJI)
    async def cook(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_craft_surface(interaction, self.player, "cook")

    @discord.ui.button(label=BREW_TITLE, style=discord.ButtonStyle.primary, emoji=BREW_EMOJI)
    async def brew(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_craft_surface(interaction, self.player, "brew")


class CraftSurfaceView(_AuthorOnly):
    """One workstation: a select of its UNLOCKED recipes + Return. Locked
    recipes appear in the embed only, so the select never crowds. Past
    CRAFT_SURFACE_PAGE_SIZE recipes the embed paginates: ◀ ▶ flip between
    the pre-built pages in place (no DB round-trip); the select always
    carries every unlocked recipe regardless of the visible page."""

    def __init__(
        self,
        cog: "LegionCog",
        author_id: int,
        player: Player,
        surface: str,
        craftable: list[Recipe],
        embeds: list[discord.Embed] | None = None,
    ):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.player = player
        self.surface = surface
        self.embeds = embeds or []
        self.page = 0
        if len(self.embeds) > 1:
            prev_b = discord.ui.Button(
                label=ARROW_LEFT_EMOJI, style=discord.ButtonStyle.secondary,
                row=1, disabled=True,
            )
            next_b = discord.ui.Button(
                label=ARROW_RIGHT_EMOJI, style=discord.ButtonStyle.secondary,
                row=1,
            )

            async def flip(interaction: discord.Interaction, delta: int) -> None:
                self.page = max(0, min(len(self.embeds) - 1, self.page + delta))
                prev_b.disabled = self.page == 0
                next_b.disabled = self.page == len(self.embeds) - 1
                await interaction.response.edit_message(
                    embed=self.embeds[self.page], view=self
                )

            prev_b.callback = lambda i: flip(i, -1)
            next_b.callback = lambda i: flip(i, +1)
            self.add_item(prev_b)
            self.add_item(next_b)
        if craftable:
            options = [
                discord.SelectOption(label=r.name, value=str(r.id))
                for r in craftable[:25]
            ]
            select = discord.ui.Select(placeholder=CRAFT_PICK, options=options)

            async def callback(interaction: discord.Interaction) -> None:
                await self.cog.show_recipe_detail(
                    interaction, self.player, int(select.values[0])
                )

            select.callback = callback
            self.add_item(select)

    @discord.ui.button(label=RETURN_TITLE, style=discord.ButtonStyle.secondary, row=2)
    async def back(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_craft_home(interaction, self.player, edit=True)

class RecipeDetailView(_AuthorOnly):
    """Craft layer 3: one recipe in full. Craft (disabled when unaffordable)
    -> ephemeral confirm; Return -> the workstation."""

    def __init__(
        self,
        cog: "LegionCog",
        author_id: int,
        player: Player,
        surface: str,
        recipe_id: int,
        craftable: bool,
    ):
        super().__init__(author_id=author_id)
        self.cog = cog
        self.player = player
        self.surface = surface
        self.recipe_id = recipe_id
        self.craft_button.disabled = not craftable

    @discord.ui.button(label=CRAFT_ACTION, style=discord.ButtonStyle.success)
    async def craft_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.confirm_craft(interaction, self.player, self.recipe_id)

    @discord.ui.button(label=RETURN_TITLE, style=discord.ButtonStyle.secondary)
    async def back(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.show_craft_surface(interaction, self.player, self.surface)


class CraftConfirmView(_AuthorOnly):
    """The ephemeral are-you-sure. Yes runs the craft (with the dot-count
    quality tell animation); Cancel closes."""

    def __init__(self, cog: "LegionCog", author_id: int, player: Player, recipe_id: int):
        super().__init__(author_id=author_id, timeout=60)
        self.cog = cog
        self.player = player
        self.recipe_id = recipe_id

    @discord.ui.button(label=CONFIRM_TITLE, style=discord.ButtonStyle.success)
    async def yes(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.do_craft(interaction, self.player, self.recipe_id)

    @discord.ui.button(label=CANCEL_TITLE, style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            content=CRAFT_CANCELLED, embed=None, view=None
        )


class DismantleConfirmView(_AuthorOnly):
    """The ephemeral are-you-sure before dismantling. Yes destroys the weapon
    (rolling salvage); Cancel closes."""

    def __init__(self, cog: "LegionCog", author_id: int, player: Player, pw_id: int):
        super().__init__(author_id=author_id, timeout=60)
        self.cog = cog
        self.player = player
        self.pw_id = pw_id

    @discord.ui.button(label=CONFIRM_TITLE, style=discord.ButtonStyle.danger)
    async def yes(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await self.cog.do_dismantle(interaction, self.player, self.pw_id)

    @discord.ui.button(label=CANCEL_TITLE, style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            content=INVENTORY_DISMANTLE_CANCELLED, embed=None, view=None
        )

