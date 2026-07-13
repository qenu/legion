"""Shared surface for the LegionCog mixins.

``LegionCogBase`` declares the attribute surface every mixin relies on (the
repos and services are ASSIGNED in ``LegionCog.__init__``; the annotations
here exist for type checkers and editors) and owns the cross-cutting helpers:
the patch gate, Discord-response utilities, and the player interceptors that
every command funnels through.
"""

from datetime import datetime
from typing import TYPE_CHECKING

import discord

from maki.cogs.legion import strings
from maki.cogs.legion.calculator import mastery_erosion_pts
from maki.cogs.legion.constants import (
    ContentStatus,
    EXPEDITION_MIN_HP_PCT,
    STARTER_POTION_KEY,
    STARTER_WEAPONS,
)
from maki.cogs.legion.model.model import GamePatch, Legion, Material, Player, Weapon
from maki.cogs.legion.simulation import (
    effective_max_hp,
    effective_max_hp_and_regen,
)
from maki.cogs.legion.utils import clean_legion_name, clean_player_name, patch_phase
from maki.cogs.legion.views import OnboardView

if TYPE_CHECKING:
    import asyncio

    from maki.core import Maki
    from maki.cogs.legion.model.repository import (
        ActivityRepo,
        DungeonRepo,
        InventoryRepo,
        LegionRepo,
        MasteryRepo,
        PatchRepo,
        PlayerRepo,
        SystemRepo,
    )
    from maki.cogs.legion.settlement import SettlementService

FREEZE_FLAG_KEY = "maintenance_freeze"


class LegionCogBase:
    """Attribute surface + shared helpers. Never instantiated on its own --
    ``LegionCog`` assigns every annotated attribute in ``__init__``."""

    if TYPE_CHECKING:
        bot: "Maki"
        players: "PlayerRepo"
        legions: "LegionRepo"
        inventory: "InventoryRepo"
        masteries: "MasteryRepo"
        activities: "ActivityRepo"
        dungeons: "DungeonRepo"
        settlement: "SettlementService"
        patches: "PatchRepo"
        system: "SystemRepo"
        _lobby_tasks: dict[int, asyncio.Task]
        _replay_tasks: set[asyncio.Task]
        _pending_patch: GamePatch | None
        _patch_task: asyncio.Task | None
        _frozen: bool

    # --- patch gate ----------------------------------------------------------

    def _patch_blocked(self, session_start: bool = False) -> bool:
        """The update lock: a manual maintenance freeze blocks everything; the
        scheduled patch's 'locked' blocks session starts, 'frozen'/'due' block
        everything."""
        if self._frozen:  # manual owner freeze: hard-blocks every command
            return True
        pending = self._pending_patch
        if pending is None or pending.lock_at is None:
            return False
        phase = patch_phase(
            pending.lock_at, pending.apply_at, datetime.now().astimezone()
        )
        if phase in ("frozen", "due"):
            return True
        return phase == "locked" and session_start

    async def _send_patch_blocked(self, interaction: discord.Interaction) -> None:
        msg = strings.LEGION_FROZEN if self._frozen else strings.PATCH_BLOCKED
        await self._notify(interaction, msg)

    # --- Discord response helpers --------------------------------------------

    @staticmethod
    async def _edit_tracked(interaction: discord.Interaction, **kwargs) -> None:
        """edit_message + hand the (new) view its message so on_timeout can
        strip dead buttons even if the view is never pressed. Deferred-aware:
        after _defer() the token-bound response is spent, so edits go through
        the webhook (valid 15 min) instead of the 3-second initial window."""
        view = kwargs.get("view")
        if view is not None and interaction.message is not None:
            view.message = interaction.message
        if interaction.response.is_done():
            await interaction.edit_original_response(**kwargs)
        else:
            await interaction.response.edit_message(**kwargs)

    @staticmethod
    async def _defer(interaction: discord.Interaction, ephemeral: bool = False) -> None:
        """Acknowledge within Discord's 3s window BEFORE doing DB work --
        prevents 10062 Unknown interaction on slow paths. Component presses defer
        the message update (ephemeral is ignored there); slash commands should
        pass ephemeral=True when their eventual reply is ephemeral."""
        if not interaction.response.is_done():
            await interaction.response.defer(ephemeral=ephemeral)

    @staticmethod
    async def _notify(interaction: discord.Interaction, content: str) -> None:
        """Ephemeral notice that works before or after a defer. THE one way
        to send gate/error notices -- never re-implement the is_done() fork."""
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)

    # --- interceptors ------------------------------------------------------

    async def _legion_for(self, guild: discord.Guild) -> Legion:
        return await self.legions.get_or_create(guild.id, clean_legion_name(guild.name))

    async def ensure_player(
        self, interaction: discord.Interaction, gate_patch: bool = True
    ) -> Player | None:
        """The onboarding interceptor: returns the (regen-applied) player, or
        sends the ephemeral weapon-pick prompt and returns None. Also the
        full-freeze patch gate: every game command passes through here.
        ``gate_patch=False`` skips the freeze check -- for actions that finish
        something already in flight (e.g. joining an open lobby)."""
        if gate_patch and self._patch_blocked():
            await self._send_patch_blocked(interaction)
            return None
        player = await self.players.get(interaction.user.id)
        if player is None:
            if interaction.guild is None:
                await interaction.response.send_message(
                    strings.ONBOARD_DM_ONLY, ephemeral=True
                )
                return None
            legion = await self._legion_for(interaction.guild)
            starters = await Weapon.filter(
                key__in=list(STARTER_WEAPONS), status=ContentStatus.ENABLED
            )
            onboard_view = OnboardView(self, legion, starters)
            prompt = strings.ONBOARD_PROMPT.format(legion=legion.name)
            if interaction.response.is_done():
                onboard_view.message = await interaction.followup.send(
                    prompt, view=onboard_view, ephemeral=True, wait=True
                )
            else:
                await interaction.response.send_message(
                    prompt, view=onboard_view, ephemeral=True
                )
                onboard_view.message = await interaction.original_response()
            return None
        own_level = 0
        if player.legion_id:
            own = await player.legion
            own_level = own.level
        eff_max, regen_bonus = await effective_max_hp_and_regen(player, own_level)
        await self.players.apply_regen(
            player, own_level, eff_max, bonus_regen=regen_bonus
        )
        # Inactivity decay BEFORE bumping the activity stamp: erode above-cap
        # mastery for the gap since last seen, then reset the bookmark.
        if player.last_active_at is not None:
            inactive = (
                datetime.now().astimezone() - player.last_active_at
            ).total_seconds()
            pts = mastery_erosion_pts(inactive)
            if pts:
                await self.masteries.erode(player, pts)
        await self.players.touch_active(player)
        return player

    async def ensure_alive(
        self, interaction: discord.Interaction, player: Player
    ) -> bool:
        """Death penalty: the dead can't act. Potions (via inventory) are the
        only way back."""
        if player.health_points > 0:
            return True
        await self._notify(interaction, strings.DEAD_BLOCKED)
        return False

    async def ensure_battle_ready(
        self, interaction: discord.Interaction, player: Player
    ) -> bool:
        """Expedition gate: dead OR below EXPEDITION_MIN_HP_PCT% can't fight."""
        if not await self.ensure_alive(interaction, player):
            return False
        own_level = (await player.legion).level if player.legion_id else 0
        eff_max = await effective_max_hp(player, own_level)
        if player.health_points * 100 < eff_max * EXPEDITION_MIN_HP_PCT:
            await self._notify(
                interaction, strings.HP_TOO_LOW.format(pct=EXPEDITION_MIN_HP_PCT)
            )
            return False
        return True

    async def ensure_not_afk(
        self, interaction: discord.Interaction, player: Player
    ) -> bool:
        """The AFK interceptor: all game actions are blocked while gathering."""
        activity = await self.activities.active_for(player)
        if activity is None:
            return True
        await self._notify(
            interaction, strings.GATHER_BLOCKED.format(site=activity.site.name)
        )
        return False

    async def ensure_not_in_expedition(
        self, interaction: discord.Interaction, player: Player
    ) -> bool:
        """The expedition interceptor: while the player is in an ACTIVE
        (pre-settlement) run -- any guild's -- they can't gather or enter
        another expedition. One HP pool, one fight at a time."""
        instance = await self.dungeons.active_for_player(player)
        if instance is None:
            return True
        await self._notify(
            interaction,
            strings.HUNTING_EXPEDITION_BUSY.format(ground=instance.ground.name),
        )
        return False

    # --- onboarding ----------------------------------------------------------

    async def onboard(
        self, user: discord.abc.User, legion: Legion, weapon: Weapon
    ) -> Player:
        player = await self.players.get_or_create(
            user.id, clean_player_name(user.display_name)
        )
        await self.players.join_legion(player, legion)
        starter = await self.inventory.grant_weapon(player, weapon)
        await self.inventory.equip(player, starter)  # starters are main-hand
        # One potion in the pocket: the revive safety net.
        potion = await Material.get_or_none(
            key=STARTER_POTION_KEY, status=ContentStatus.ENABLED
        )
        if potion is not None:
            await self.inventory.add_material(player, potion, 1)
        # Start at FULL effective max (base + legion bonus + starter's HP
        # passives) -- not base/effective, e.g. 100/120. Equip first: the
        # starter weapon counts toward the max.
        player.health_points = await effective_max_hp(player, legion.level)
        player.hp_updated_at = datetime.now().astimezone()
        await player.save(update_fields=["health_points", "hp_updated_at"])
        return player
