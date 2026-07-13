"""The legion cog: assembly and lifecycle.

Layering: commands/buttons -> mixin service methods -> repos/services. Game
rules live below (calculator/settlement/simulation); each domain's Discord
orchestration lives in its mixin (maki/cogs/legion/mixins/):

  * ExpeditionMixin  -- /expedition, captcha, lobby timers, the fight pipeline
  * LegionPanelMixin -- /legion home, upgrade, donate, members, settings
  * ProfileMixin     -- /profile, inventory, mastery, item use (incl. on others)
  * GatherMixin      -- /gatherer AFK sessions
  * CraftMixin       -- /craft forge + cook/brew workstations
  * AdminMixin       -- owner console + the staged patch workflow

This file only wires them together: repos, context menus, boot/shutdown.
"""

import asyncio

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger as log

from maki.core import Maki

from maki.cogs.legion import strings
from maki.cogs.legion.mixins import (
    AdminMixin,
    CraftMixin,
    ExpeditionMixin,
    FREEZE_FLAG_KEY,
    GatherMixin,
    LegionPanelMixin,
    ProfileMixin,
    _CaptchaState,
)
from maki.cogs.legion.model.model import GamePatch
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


class LegionCog(
    ExpeditionMixin,
    LegionPanelMixin,
    ProfileMixin,
    GatherMixin,
    CraftMixin,
    AdminMixin,
    commands.Cog,
):
    def __init__(self, bot: Maki):
        self.bot = bot
        self.players = PlayerRepo()
        self.legions = LegionRepo()
        self.inventory = InventoryRepo()
        self.masteries = MasteryRepo()
        self.activities = ActivityRepo()
        self.dungeons = DungeonRepo()
        self.settlement = SettlementService(
            self.dungeons, self.masteries, self.inventory, self.legions
        )
        self.patches = PatchRepo()
        self.system = SystemRepo()
        self._lobby_tasks: dict[int, asyncio.Task] = {}  # legion_id -> timer
        self._replay_tasks: set[asyncio.Task] = set()
        self._pending_patch: GamePatch | None = None
        self._patch_task: asyncio.Task | None = None
        # Manual maintenance freeze: an owner toggle (`admin freeze on`) that
        # blocks ALL commands, independent of the scheduled-patch phases. Meant
        # as the graceful lead-in to a force patch -- flip it on, let in-flight
        # actions drain, force-apply, flip it off. Persisted (SystemFlag) so it
        # SURVIVES the restart used to apply a patch; loaded in cog_load.
        self._frozen = False
        # Anti-script captcha retry state, keyed by discord_id. In-memory only
        # (a restart clears it; the timing heuristic re-catches persistent bots).
        # Escalation past the ceiling hands off to the bot-wide core blacklist.
        self._captcha: dict[int, _CaptchaState] = {}
        # Right-click a member -> Apps -> 使用道具: consumables on OTHERS,
        # including the potion revive. Context menus can't live in cogs as
        # decorated methods, so it's built here and (un)registered in
        # cog_load/cog_unload.
        self._use_item_menu = app_commands.ContextMenu(
            name=strings.USE_ITEM_CONTEXT_NAME, callback=self.use_item_context
        )
        self._showoff_profile_menu = app_commands.ContextMenu(
            name=strings.CHECK_PROFILE_CONTEXT_NAME,
            callback=self.showoff_profile_context,
        )

    async def cog_load(self) -> None:
        self.bot.tree.add_command(self._use_item_menu)
        self.bot.tree.add_command(self._showoff_profile_menu)
        voided = await self.dungeons.void_all_active()
        if voided:
            log.info("Voided {} orphaned expedition lobbies on boot.", voided)
        # Restore the maintenance freeze across the restart (e.g. a force patch).
        self._frozen = await self.system.get_flag(FREEZE_FLAG_KEY)
        # Resume a scheduled patch across restarts (or apply it if overdue).
        self._pending_patch = await self.patches.pending()
        if self._pending_patch is not None:
            self._start_patch_timer(self._pending_patch)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(
            self._use_item_menu.name, type=discord.AppCommandType.user
        )
        self.bot.tree.remove_command(
            self._showoff_profile_menu.name, type=discord.AppCommandType.user
        )
        # Graceful shutdown: lobbies are droppable (boot voids them), but an
        # in-flight replay narrates already-settled rewards -- let it finish.
        for task in self._lobby_tasks.values():
            task.cancel()
        if self._patch_task is not None:
            self._patch_task.cancel()
        if self._replay_tasks:
            await asyncio.wait(self._replay_tasks, timeout=30)
