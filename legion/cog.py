"""The legion cog: commands, views wiring, lobby timers, and the replay feed.

Layering: commands/buttons -> this cog's service methods -> repos/services.
Game rules live below (calculator/settlement/simulation); this file only
orchestrates Discord I/O around them.
"""

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Union

import discord
from discord import app_commands
from discord.ext import commands
from loguru import logger as log

from maki.core import Maki

from maki.cogs.legion import render, strings
from maki.cogs.legion.calculator import (
    gather_payout_chunks,
    mastery_erosion_pts,
    mastery_level_cost,
    roll_drops,
    roll_mutations,
)
from maki.cogs.legion.constants import (
    CAPTCHA_BLACKLIST_AT_SECONDS,
    CAPTCHA_BUTTONS,
    CAPTCHA_INTERVAL_TOLERANCE,
    CAPTCHA_LOCKOUT_BASE,
    CAPTCHA_STREAK_TRIGGER,
    CRAFT_MASTERY_PTS,
    MASTERY_HARD_CAP,
    ContentStatus,
    EXPEDITION_MIN_HP_PCT,
    LOBBY_SECONDS,
    REVIVE_MINUTES,
    STARTER_POTION_KEY,
    STARTER_WEAPONS,
    MASTERY_KIND_WEAPONS,
    USE_ITEM_MASTERY_GAP_PCT,
    LifeSkillType,
    MaterialKind,
    StatBonusType,
    WeaponSlot,
)
from maki.cogs.legion.model.model import (
    ActiveSkill,
    DungeonInstance,
    DungeonParticipant,
    GamePatch,
    GatherSite,
    HuntingGround,
    Legion,
    LifeSkillMastery,
    Material,
    Mob,
    Player,
    PlayerMaterial,
    PlayerWeapon,
    Recipe,
    RecipeMaterial,
    SiteYield,
    Weapon,
    WeaponActiveSkill,
    WeaponCategory,
    WeaponMastery,
    WeaponPassiveSkill,
)
from maki.cogs.legion.content import PATCH
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

FREEZE_FLAG_KEY = "maintenance_freeze"


@dataclass
class _CaptchaState:
    """Per-user anti-script state, kept in memory only (cleared on restart)."""

    last_at: datetime | None = None   # last expedition attempt
    last_interval: int = 0            # previous gap, seconds
    streak: int = 0                   # regular-gap run length
    fails: int = 0                    # consecutive test failures
    locked_until: datetime | None = None  # soft-lockout expiry
from maki.cogs.legion.seeds import (
    apply_patch,
    content_hash,
    content_summary,
    pending_removals,
    validate_patch,
)
from maki.cogs.legion.settlement import SettlementService
from maki.cogs.legion.simulation import (
    build_mob_state,
    build_player_state,
    effective_max_hp,
    effective_max_hp_and_regen,
    run_simulation,
)
from maki.cogs.legion.utils import (
    clean_legion_name,
    clean_player_name,
    patch_phase,
    patch_timeline,
)
from maki.cogs.legion.views import (
    CaptchaView,
    CraftConfirmView,
    CraftHomeView,
    CraftSurfaceView,
    DismantleConfirmView,
    RecipeDetailView,
    KIND_CONSUMABLES,
    KIND_WEAPONS,
    DonateView,
    GatherBusyView,
    GatherIdleView,
    GroundSelectView,
    InventoryCategoryView,
    InventoryHomeView,
    LegionMasteryView,
    LegionSettingsView,
    LegionView,
    LobbyView,
    MembersView,
    OnboardView,
    CombatLogView,
    PatchDecisionView,
    PatchView,
    ProfileView,
    SettlementPaginator,
    UseItemView,
    WeaponDetailView,
)


class LegionCog(commands.Cog):
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
        self._lobby_tasks: dict[int, asyncio.Task] = {}   # legion_id -> timer
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
            name=strings.CHECK_PROFILE_CONTEXT_NAME, callback=self.showoff_profile_context
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
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    @staticmethod
    async def _edit_tracked(
        interaction: discord.Interaction, **kwargs
    ) -> None:
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
    async def _defer(interaction: discord.Interaction) -> None:
        """Acknowledge a component press within Discord's 3s window BEFORE
        doing DB work -- prevents 10062 Unknown interaction on slow paths."""
        if not interaction.response.is_done():
            await interaction.response.defer()

    @staticmethod
    async def _notify(interaction: discord.Interaction, content: str) -> None:
        """Ephemeral notice that works before or after a defer."""
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)

    # --- interceptors ------------------------------------------------------

    async def _legion_for(self, guild: discord.Guild) -> Legion:
        return await self.legions.get_or_create(
            guild.id, clean_legion_name(guild.name)
        )

    async def ensure_player(
        self, interaction: discord.Interaction
    ) -> Player | None:
        """The onboarding interceptor: returns the (regen-applied) player, or
        sends the ephemeral weapon-pick prompt and returns None. Also the
        full-freeze patch gate: every game command passes through here."""
        if self._patch_blocked():
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
        if interaction.response.is_done():
            await interaction.followup.send(strings.DEAD_BLOCKED, ephemeral=True)
        else:
            await interaction.response.send_message(
                strings.DEAD_BLOCKED, ephemeral=True
            )
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
            message = strings.HP_TOO_LOW.format(pct=EXPEDITION_MIN_HP_PCT)
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
            return False
        return True

    async def ensure_not_afk(
        self, interaction: discord.Interaction, player: Player
    ) -> bool:
        """The AFK interceptor: all game actions are blocked while gathering."""
        activity = await self.activities.active_for(player)
        if activity is None:
            return True
        message = strings.GATHER_BLOCKED.format(site=activity.site.name)
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
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
        message = strings.HUNTING_EXPEDITION_BUSY.format(ground=instance.ground.name)
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
        return False

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

    # --- /expedition ---------------------------------------------------------

    @app_commands.command(
        name=strings.EXPEDITION_COMMAND_NAME, description=strings.EXPEDITION_COMMAND_DESC
    )
    @app_commands.guild_only()
    async def expedition(self, interaction: discord.Interaction) -> None:
        if self._patch_blocked(session_start=True):
            await self._send_patch_blocked(interaction)
            return
        player = await self.ensure_player(interaction)
        if player is None or not await self.ensure_not_afk(interaction, player):
            return
        if not await self.ensure_battle_ready(interaction, player):
            return
        # Player-level check: already in SOME guild's pre-settlement run.
        if not await self.ensure_not_in_expedition(interaction, player):
            return
        legion = await self._legion_for(interaction.guild)
        if not legion.channel_id:
            await interaction.response.send_message(
                strings.LEGION_NOT_CONFIGURED, ephemeral=True
            )
            return
        if await self.dungeons.active_for(legion) is not None:
            await interaction.response.send_message(
                strings.HUNTING_EXPEDITION_BUSY_SHORT, ephemeral=True
            )
            return
        if not await self.ensure_captcha(interaction, player):
            return  # locked out, or a verification test was shown
        await self.show_ground_list(interaction)

    # --- anti-script captcha -------------------------------------------------

    def _captcha_should_test(self, st: "_CaptchaState", now: datetime) -> bool:
        """Update the timing heuristic and report whether to challenge. Robotic
        REGULARITY is the tell: gaps between expeditions matching within
        CAPTCHA_INTERVAL_TOLERANCE, CAPTCHA_STREAK_TRIGGER times running."""
        triggered = False
        if st.last_at is not None:
            interval = int((now - st.last_at).total_seconds())
            if (
                st.last_interval > 0
                and abs(interval - st.last_interval) <= CAPTCHA_INTERVAL_TOLERANCE
            ):
                st.streak += 1
            else:
                st.streak = 0
            st.last_interval = interval
            triggered = st.streak >= CAPTCHA_STREAK_TRIGGER
        st.last_at = now
        return triggered

    async def ensure_captcha(
        self, interaction: discord.Interaction, player: Player
    ) -> bool:
        """Gate the expedition. Returns True to proceed; False if the user is
        blacklisted/locked out or a test was shown (its outcome resumes)."""
        uid = interaction.user.id
        if uid in self.bot.blacklist:  # bot-wide core blacklist
            await self._notify(interaction, strings.CAPTCHA_BLACKLISTED)
            return False
        now = datetime.now(timezone.utc)
        st = self._captcha.setdefault(uid, _CaptchaState())
        if st.locked_until and now < st.locked_until:
            await self._notify(
                interaction,
                strings.CAPTCHA_LOCKED.format(until=int(st.locked_until.timestamp())),
            )
            return False
        # A fail streak (post-lockout) force-tests until a pass clears it.
        if not (st.fails > 0 or self._captcha_should_test(st, now)):
            return True
        answer = random.randint(1, 9)
        others = random.sample(
            [n for n in range(1, 10) if n != answer], CAPTCHA_BUTTONS - 1
        )
        choices = others + [answer]
        random.shuffle(choices)
        view = CaptchaView(self, uid, player, answer, choices)
        await interaction.response.send_message(
            strings.CAPTCHA_PROMPT.format(answer=answer), view=view, ephemeral=True
        )
        view.message = await interaction.original_response()
        return False

    async def captcha_passed(
        self, interaction: discord.Interaction, player: Player
    ) -> None:
        """Correct answer: wipe the retry state and continue into the ground list."""
        self._captcha.pop(interaction.user.id, None)
        await self.show_ground_list(interaction, edit=True)

    async def captcha_failed(
        self, interaction: discord.Interaction, player: Player
    ) -> None:
        """Wrong answer: soft-lock, doubling the window each consecutive fail --
        until it would reach the ceiling, at which point hand off to the
        bot-wide core blacklist."""
        uid = interaction.user.id
        st = self._captcha.setdefault(uid, _CaptchaState())
        secs = CAPTCHA_LOCKOUT_BASE * (2 ** st.fails)
        if secs >= CAPTCHA_BLACKLIST_AT_SECONDS:
            await self.bot.add_to_blacklist(uid)
            self._captcha.pop(uid, None)
            await interaction.response.edit_message(
                content=strings.CAPTCHA_BLACKLISTED, embed=None, view=None
            )
            return
        st.locked_until = datetime.now(timezone.utc) + timedelta(seconds=secs)
        st.fails += 1
        await interaction.response.edit_message(
            content=strings.CAPTCHA_FAILED.format(
                until=int(st.locked_until.timestamp())
            ),
            embed=None, view=None,
        )

    async def show_ground_list(
        self, interaction: discord.Interaction, edit: bool = False
    ) -> None:
        """Layer 1: embed listing every unlocked ground + 隨機遠征 button."""
        legion = await self._legion_for(interaction.guild)
        grounds = await self.dungeons.unlocked_grounds(legion.level)
        if not grounds:
            if edit:
                await self._edit_tracked(interaction,
                    content="No hunting grounds are open to this legion yet.",
                    embed=None, view=None,
                )
            else:
                await interaction.response.send_message(
                    "No hunting grounds are open to this legion yet.", ephemeral=True
                )
            return
        embed = render.ground_list_embed(grounds, self.bot.color)
        view = GroundSelectView(self, interaction.user.id, grounds)
        if edit:
            await self._edit_tracked(interaction, content=None, embed=embed, view=view)
        else:
            await interaction.response.send_message(
                embed=embed, view=view, ephemeral=True
            )
            view.message = await interaction.original_response()

    async def show_ground_detail(
        self, interaction: discord.Interaction, ground_id: int
    ) -> None:
        """Layer 2: one ground's intel -- danger, encounter pool, possible
        drops -- with the launch button flipped to 發起遠征."""
        await self._defer(interaction)
        legion = await self._legion_for(interaction.guild)
        grounds = await self.dungeons.unlocked_grounds(legion.level)
        ground = next((g for g in grounds if g.id == ground_id), None)
        if ground is None:  # disabled/re-locked since the list rendered
            await self.show_ground_list(interaction, edit=True)
            return
        pool = await self.dungeons.ground_pool(ground)
        drops = await self.dungeons.drop_preview([e.mob for e in pool])
        embed = render.ground_detail_embed(ground, pool, drops, self.bot.color)
        view = GroundSelectView(self, interaction.user.id, grounds, selected=ground)
        await self._edit_tracked(interaction, content=None, embed=embed, view=view)

    async def start_expedition(
        self, interaction: discord.Interaction, is_random: bool, value: str
    ) -> None:
        await self._defer(interaction)
        # Re-check at launch: the picker may be stale (joined another guild's
        # lobby since it was opened).
        player = await self.players.get(interaction.user.id)
        if player is None or not await self.ensure_not_in_expedition(
            interaction, player
        ):
            return
        legion = await self._legion_for(interaction.guild)
        grounds = await self.dungeons.unlocked_grounds(legion.level)
        if is_random:
            ground = random.choice(grounds)
        else:
            ground = next((g for g in grounds if str(g.id) == value), None)
        if ground is None:
            await self._edit_tracked(interaction,
                content=strings.HUNTING_GROUND_GONE, embed=None, view=None
            )
            return
        mob = await self.dungeons.roll_mob(ground)
        if mob is None:
            await self._edit_tracked(interaction,
                content=strings.HUNTING_MOB_GONE, embed=None, view=None
            )
            return
        expires_at = datetime.now().astimezone() + timedelta(seconds=LOBBY_SECONDS)
        instance = await self.dungeons.spawn(
            legion, ground, mob, expires_at, random_ground=is_random
        )
        if instance is None:
            await self._edit_tracked(interaction,
                content=strings.HUNTING_EXPEDITION_BUSY_SHORT, embed=None, view=None
            )
            return
        await self.dungeons.join(instance, player)  # starter auto-joins

        channel = interaction.guild.get_channel(legion.channel_id)
        embed = render.lobby_embed(
            ground, mob, is_random, [player.username], expires_at, self.bot.color
        )
        lobby_view = LobbyView(self, instance.id)
        message = await channel.send(embed=embed, view=lobby_view)
        lobby_view.message = message
        await self._edit_tracked(interaction,
            content=strings.EXPEDITION_INIT.format(channel=channel.mention),
            embed=None, view=None,
        )

        task = asyncio.create_task(
            self._run_lobby(instance.id, legion.id, message)
        )
        self._lobby_tasks[legion.id] = task
        task.add_done_callback(
            lambda _: self._lobby_tasks.pop(legion.id, None)
        )

    async def join_expedition(
        self, interaction: discord.Interaction, instance_id: int
    ) -> None:
        if self._patch_blocked(session_start=True):
            await self._send_patch_blocked(interaction)
            return
        await self._defer(interaction)
        player = await self.ensure_player(interaction)
        if player is None or not await self.ensure_not_afk(interaction, player):
            return
        if not await self.ensure_battle_ready(interaction, player):
            return
        instance = await DungeonInstance.get_or_none(id=instance_id).prefetch_related(
            "ground", "mob"
        )
        if instance is None or instance.status != "active":
            await self._notify(interaction, strings.HUNTING_EXPEDITION_OVER)
            return
        # One run at a time -- but re-pressing THIS lobby's join stays a
        # harmless idempotent re-join, not a scolding.
        active = await self.dungeons.active_for_player(player)
        if active is not None and active.id != instance.id:
            await self._notify(
                interaction,
                strings.HUNTING_EXPEDITION_BUSY.format(ground=active.ground.name),
            )
            return
        await self.dungeons.join(instance, player)
        names = [
            dp.player.username
            for dp in await DungeonParticipant.filter(
                instance=instance
            ).prefetch_related("player")
        ]
        embed = render.lobby_embed(
            instance.ground,
            instance.mob,
            instance.random_ground,
            names,
            instance.expires_at,
            self.bot.color,
        )
        await self._edit_tracked(interaction, embed=embed)

    async def _run_lobby(
        self, instance_id: int, legion_id: int, message: discord.Message
    ) -> None:
        await asyncio.sleep(LOBBY_SECONDS)
        instance = await DungeonInstance.get_or_none(id=instance_id).prefetch_related(
            "ground", "mob", "legion"
        )
        if instance is None or instance.status != "active":
            return
        participants = await DungeonParticipant.filter(
            instance=instance
        ).prefetch_related("player__legion")
        if not participants:
            await self.dungeons.expire(instance)
            await message.edit(
                embed=render.expired_embed(self.bot.color), view=None
            )
            return
        task = asyncio.create_task(
            self._run_fight(instance, participants, message)
        )
        self._replay_tasks.add(task)
        task.add_done_callback(self._replay_tasks.discard)

    async def _run_fight(
        self,
        instance: DungeonInstance,
        participants: list[DungeonParticipant],
        message: discord.Message,
    ) -> None:
        party = []
        for dp in participants:
            own_level = dp.player.legion.level if dp.player.legion else 0
            party.append(await build_player_state(dp.player, own_level))
        mob_state = await build_mob_state(
            instance.mob, instance.ground.danger, len(party)
        )
        result = run_simulation(party, mob_state)

        # Settle FIRST: rewards are committed before a single story message.
        report = await self.settlement.settle(
            instance, result.to_results(), won=result.won
        )
        # if report.upgrade_ready and instance.legion.channel_id:
        #     channel = message.channel
        #     await channel.send(
        #         strings.LEGION_UPGRADE_READY.format(
        #             legion=instance.legion.name, level=instance.legion.level + 1
        #         )
        #     )

        # Flip the lobby's countdown line to "preparation over", then post the
        # results directly. The full log lives behind a 戰鬥紀錄 button that
        # replies to each presser with ephemeral, paginated round embeds.
        await message.edit(
            embed=render.lobby_embed(
                instance.ground,
                instance.mob,
                instance.random_ground,
                [dp.player.username for dp in participants],
                instance.expires_at,
                self.bot.color,
                started=True,
            ),
            view=None,
        )
        log_embeds = render.combat_log_embeds(
            result, mob_state.rounds_limit, self.bot.color
        )
        embeds, personal = render.settlement_embeds(report, result, self.bot.color)
        if len(embeds) == 1:
            view = CombatLogView(log_embeds)
            view.message = await message.reply(embed=embeds[0], view=view)
        else:
            # Public pager (shared page state, open to all) + ephemeral
            # my-result button + the log button.
            pager = SettlementPaginator(embeds, personal, log_embeds=log_embeds)
            pager.message = await message.reply(embed=embeds[0], view=pager)

    # --- /legion ----------------------------------------------------------------

    @app_commands.command(name=strings.LEGION_COMMAND_NAME, description=strings.LEGION_COMMAND_DESC)
    @app_commands.guild_only()
    async def legion(self, interaction: discord.Interaction) -> None:
        player = await self.ensure_player(interaction)
        if player is None:
            return
        await self.show_legion_home(interaction, edit=False)

    async def show_legion_home(
        self, interaction: discord.Interaction, edit: bool = True
    ) -> None:
        legion = await self._legion_for(interaction.guild)
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
            await interaction.response.send_message(
                strings.LEGION_OFFICERS_ONLY, ephemeral=True
            )
            return
        if not await self.legions.upgrade_sheet(legion):  # no next-level cost
            await interaction.response.send_message(
                strings.LEGION_UPGRADE_MAXED, ephemeral=True
            )
            return
        if await self.legions.upgrade(legion):
            await interaction.response.send_message(
                strings.LEGION_UPGRADE_DONE.format(
                    legion=legion.name, level=legion.level
                )
            )
        else:
            await interaction.response.send_message(
                strings.LEGION_UPGRADE_SHORT, ephemeral=True
            )

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
        await self._notify(
            interaction, strings.DAILY_SUPPLY_RECEIVED.format(mats=mats)
        )

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
        await self._edit_tracked(interaction, 
            embed=render.members_embed(
                legion, entries, page, pages, self.bot.color
            ),
            view=MembersView(self, interaction.user.id, player, legion, page, pages),
        )

    async def show_donate(
        self, interaction: discord.Interaction, legion: Legion, note: str | None = None
    ) -> None:
        """The donate panel: member's stacks tagged with upgrade-sheet needs."""
        player = await self.players.get(interaction.user.id)
        if player is None or player.legion_id != legion.id:
            await interaction.response.send_message(
                strings.DONATE_MEMBERS_ONLY, ephemeral=True
            )
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
        await self._edit_tracked(interaction,
            content=note,
            embed=render.donate_embed(legion, stacks, sheet_map, self.bot.color),
            view=DonateView(
                self, interaction.user.id, player, legion, stacks, sheet_map
            ),
        )

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
                interaction, legion,
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

    async def show_legion_settings(
        self, interaction: discord.Interaction, legion: Legion, note: str | None = None
    ) -> None:
        """Settings layer: current name/channel/managers + the selects."""
        if not await self._is_officer(interaction, legion):
            await interaction.response.send_message(
                strings.LEGION_OFFICERS_ONLY, ephemeral=True
            )
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
            await interaction.response.send_message(
                strings.LEGION_OFFICERS_ONLY, ephemeral=True
            )
            return
        legion.channel_id = channel_id
        await legion.save(update_fields=["channel_id"])
        await self.show_legion_settings(
            interaction, legion,
            note=strings.LEGION_CHANNEL_SET.format(channel=f"<#{channel_id}>"),
        )

    async def appoint_manager(
        self, interaction: discord.Interaction, legion: Legion, user: discord.User
    ) -> None:
        if not await self._is_officer(interaction, legion):
            await interaction.response.send_message(
                strings.LEGION_OFFICERS_ONLY, ephemeral=True
            )
            return
        player = await self.players.get(user.id)
        if player is None or player.legion_id != legion.id:
            await interaction.response.send_message(
                strings.DONATE_MEMBERS_ONLY, ephemeral=True
            )
            return
        player.is_legion_manager = True
        await player.save(update_fields=["is_legion_manager"])
        await self.show_legion_settings(
            interaction, legion,
            note=strings.LEGION_MANAGER_SET.format(player=player.username),
        )

    async def set_legion_name(
        self, interaction: discord.Interaction, legion: Legion, raw: str
    ) -> None:
        if not await self._is_officer(interaction, legion):
            await interaction.response.send_message(
                strings.LEGION_OFFICERS_ONLY, ephemeral=True
            )
            return
        legion.name = clean_legion_name(raw)
        await legion.save(update_fields=["name"])
        await self.show_legion_settings(
            interaction, legion,
            note=strings.LEGION_RENAMED.format(name=legion.name),
        )

    async def press_join_legion(
        self, interaction: discord.Interaction, legion: Legion
    ) -> None:
        player = await self.players.get(interaction.user.id)
        if player is None:
            await interaction.response.send_message(
                strings.ONBOARD_ANY_CMD, ephemeral=True
            )
            return
        if not await self.ensure_not_afk(interaction, player):
            return
        if player.legion_id == legion.id:
            await interaction.response.send_message(
                strings.LEGION_ALREADY_MEMBER, ephemeral=True
            )
            return
        await self.players.join_legion(player, legion)
        await interaction.response.send_message(
            strings.LEGION_WELCOME.format(legion=legion.name),
            ephemeral=True,
        )

    async def press_leave_legion(
        self, interaction: discord.Interaction, legion: Legion
    ) -> None:
        player = await self.players.get(interaction.user.id)
        if player is None or player.legion_id != legion.id:
            await interaction.response.send_message(
                strings.LEGION_NOT_MEMBER, ephemeral=True
            )
            return
        if not await self.ensure_not_afk(interaction, player):
            return
        await self.players.leave_legion(player)
        await interaction.response.send_message(
            strings.LEGION_LEFT.format(legion=legion.name), ephemeral=True
        )

    # --- /profile -----------------------------------------------------------------

    @app_commands.command(name=strings.PROFILE_COMMAND_NAME, description=strings.PROFILE_COMMAND_DESC)
    async def profile(self, interaction: discord.Interaction) -> None:
        player = await self.ensure_player(interaction)
        if player is None:
            return
        await self.show_profile(interaction, player, edit=False)

    async def show_profile(
        self, interaction: discord.Interaction, player: Player, edit: bool = True
    ) -> None:
        legion = await player.legion if player.legion_id else None
        equipped = {
            slot: await self.inventory.equipped(player, slot)
            for slot in (WeaponSlot.MAIN, WeaponSlot.SUB)
        }
        eff_max = await effective_max_hp(player, legion.level if legion else 0)
        embed = render.profile_embed(
            player, legion, equipped, self.bot.color, effective_max=eff_max
        )
        view = ProfileView(self, interaction.user.id, player)

        # Death countdown: ensure_player already flushed regen (lazily reviving
        # if due), so a still-dead player has a revive time in the future --
        # hp_updated_at is the death stamp while dead.
        if player.health_points <= 0:
            died_at = player.hp_updated_at or datetime.now().astimezone()
            revive_at = died_at + timedelta(minutes=REVIVE_MINUTES)
            embed.add_field(
                name=strings.DEATH_TIMER_TITLE,
                value=strings.DEATH_TIMER_VALUE.format(
                    revive=int(revive_at.timestamp())
                ),
                inline=False,
            )

        # Active food buffs (regen + timed stat buffs). The timestamp checks
        # guard the sub-minute window where a buff ended before a flush.
        now = datetime.now().astimezone()
        buff_lines: list[str] = []
        if (
            player.regen_buff_rate
            and player.regen_buff_until
            and player.regen_buff_until > now
        ):
            buff_lines.append(
                strings.FOOD_BUFF_ACTIVE.format(
                    value=player.regen_buff_rate,
                    until=int(player.regen_buff_until.timestamp()),
                )
            )
        now_epoch = now.timestamp()
        for stype, buff in (player.stat_buffs or {}).items():
            if not isinstance(buff, dict) or buff.get("until", 0) <= now_epoch:
                continue
            buff_lines.append(
                strings.FOOD_STAT_BUFF_ACTIVE.format(
                    category=strings.STAT_NAMES.get(stype, stype),
                    value=int(buff.get("value", 0)),
                    until=int(buff["until"]),
                )
            )
        if buff_lines:
            embed.add_field(
                name=strings.FOOD_BUFF_TITLE,
                value="\n".join(buff_lines),
                inline=False,
            )

        if edit:
            await self._edit_tracked(interaction, embed=embed, view=view)
        else:
            await interaction.response.send_message(
                embed=embed, view=view, ephemeral=True
            )
            view.message = await interaction.original_response()

    async def show_inventory(
        self, interaction: discord.Interaction, player: Player
    ) -> None:
        """Layer 1: all materials + equipped weapons; category select."""
        stacks = await PlayerMaterial.filter(
            player=player, quantity__gt=0
        ).prefetch_related("material")
        equipped = await PlayerWeapon.filter(
            player=player, equipped_slot__isnull=False
        ).prefetch_related("weapon")
        await self._edit_tracked(interaction, 
            content=None,
            embed=render.inventory_home_embed(stacks, equipped, self.bot.color),
            view=InventoryHomeView(self, interaction.user.id, player),
        )

    async def show_inventory_category(
        self,
        interaction: discord.Interaction,
        player: Player,
        kind: str,
        note: str | None = None,
        used_id: int | None = None,
    ) -> None:
        """Layer 2: one category's detailed embed + item select. ``used_id`` (a
        just-consumed material still in stock) becomes the select placeholder,
        so a player can chain-heal off the same item without re-hunting it."""
        if kind == KIND_WEAPONS:
            weapons = await PlayerWeapon.filter(player=player).prefetch_related(
                "weapon__category"
            )
            embed = render.inventory_weapons_embed(weapons, self.bot.color)
            view = InventoryCategoryView(
                self, interaction.user.id, player, kind, weapons=weapons
            )
        else:
            consumables = await PlayerMaterial.filter(
                player=player,
                quantity__gt=0,
                material__kind__in=[
                    MaterialKind.FOOD, MaterialKind.POTION, MaterialKind.CONSUMABLE
                ],
            ).prefetch_related("material")
            embed = render.inventory_consumables_embed(consumables, self.bot.color)
            placeholder = next(
                (s.material.name for s in consumables if s.material_id == used_id),
                None,
            )
            view = InventoryCategoryView(
                self, interaction.user.id, player, kind,
                consumables=consumables, placeholder=placeholder,
            )
        await self._edit_tracked(interaction, 
            content=note, embed=embed, view=view
        )

    async def show_mastery(
        self,
        interaction: discord.Interaction,
        player: Player,
        kind: str = MASTERY_KIND_WEAPONS,
    ) -> None:
        """One mastery pool per page; the view's select flips between them."""
        if kind == MASTERY_KIND_WEAPONS:
            masteries = await WeaponMastery.filter(player=player).prefetch_related(
                "category"
            )
        else:
            masteries = await LifeSkillMastery.filter(player=player)
        await self._edit_tracked(interaction,
            embed=render.mastery_embed(kind, masteries, self.bot.color),
            view=LegionMasteryView(self, interaction.user.id, player, kind),
        )

    async def show_weapon_detail(
        self,
        interaction: discord.Interaction,
        player: Player,
        pw_id: int,
        note: str | None = None,
    ) -> None:
        """Layer 3: one weapon in full -- skills with mutation-adjusted values
        and lock states from the player's mastery."""
        await self._defer(interaction)
        pw = await PlayerWeapon.get_or_none(id=pw_id).prefetch_related(
            "weapon__category"
        )
        if pw is None or pw.player_id != player.id:
            await self.show_inventory_category(interaction, player, KIND_WEAPONS)
            return
        actives = (
            await WeaponActiveSkill.filter(
                weapon=pw.weapon, active_skill__status=ContentStatus.ENABLED
            )
            .order_by("tier")
            .prefetch_related("active_skill")
        )
        passives = (
            await WeaponPassiveSkill.filter(
                weapon=pw.weapon, passive_skill__status=ContentStatus.ENABLED
            )
            .order_by("tier")
            .prefetch_related("passive_skill")
        )
        mastery = await WeaponMastery.get_or_none(
            player=player, category_id=pw.weapon.category_id
        )
        await self._edit_tracked(
            interaction,
            content=note,
            embed=render.weapon_detail_embed(
                pw, actives, passives,
                mastery.level if mastery else 0,
                self.bot.color,
            ),
            view=WeaponDetailView(self, interaction.user.id, player, pw.id),
        )

    async def press_detail_equip(
        self, interaction: discord.Interaction, player: Player, pw_id: int
    ) -> None:
        """Equip from the detail layer, then re-render the SAME detail."""
        await self._defer(interaction)
        if not await self.ensure_not_afk(interaction, player):
            return
        pw = await PlayerWeapon.get_or_none(id=pw_id)
        if pw is None or await self.inventory.equip(player, pw) is None:
            await self._notify(interaction, "Can't equip that.")
            return
        await self.show_weapon_detail(interaction, player, pw_id)

    async def press_use(
        self,
        interaction: discord.Interaction,
        player: Player,
        selection: str | None,
    ) -> None:
        """The unified Use button: weapons equip into their designated hand,
        consumables get consumed."""
        if selection is None:
            await self._notify(interaction, "Pick an item first.")
            return
        await self._defer(interaction)
        if not await self.ensure_not_afk(interaction, player):
            return
        kind, _, raw_id = selection.partition(":")
        if kind == "w":
            pw = await PlayerWeapon.get_or_none(id=int(raw_id))
            if pw is None or await self.inventory.equip(player, pw) is None:
                await self._notify(interaction, "Can't equip that.")
                return
            await self.show_inventory_category(interaction, player, KIND_WEAPONS)
        else:
            material, note = await self._use_consumable(player, int(raw_id))
            await self.show_inventory_category(
                interaction, player, KIND_CONSUMABLES, note=note,
                used_id=material.id if material is not None else None,
            )

    async def press_dismantle(
        self,
        interaction: discord.Interaction,
        player: Player,
        selection: str | None,
    ) -> None:
        """The ephemeral are-you-sure predicate before dismantling (destructive
        and irreversible -- salvage is a chance, not a refund)."""
        if selection is None or not selection.startswith("w:"):
            await self._notify(interaction, strings.INVENTORY_DISMANTLE_WEAPON_ONLY)
            return
        pw_id = int(selection.partition(":")[2])
        pw = await PlayerWeapon.get_or_none(id=pw_id).prefetch_related("weapon")
        if pw is None or pw.player_id != player.id:
            await self._notify(interaction, strings.INVENTORY_CANNOT_DISMANTLE)
            return
        if pw.equipped_slot is not None:
            await self._notify(interaction, strings.INVENTORY_CANNOT_DISMANTLE_EQUIPPED)
            return
        confirm = DismantleConfirmView(self, interaction.user.id, player, pw_id)
        await interaction.response.send_message(
            strings.INVENTORY_DISMANTLE_CONFIRM.format(weapon=pw.weapon.name),
            view=confirm, ephemeral=True,
        )
        confirm.message = await interaction.original_response()

    async def do_dismantle(
        self, interaction: discord.Interaction, player: Player, pw_id: int
    ) -> None:
        """Perform the dismantle on the ephemeral confirm message: re-validate
        (the weapon may have been equipped/dismantled since), salvage, destroy."""
        await self._defer(interaction)
        pw = await PlayerWeapon.get_or_none(id=pw_id).prefetch_related("weapon")
        if pw is None or pw.player_id != player.id:
            await self._edit_tracked(
                interaction, content=strings.INVENTORY_CANNOT_DISMANTLE,
                embed=None, view=None,
            )
            return
        if pw.equipped_slot is not None:
            await self._edit_tracked(
                interaction, content=strings.INVENTORY_CANNOT_DISMANTLE_EQUIPPED,
                embed=None, view=None,
            )
            return
        name = pw.weapon.name
        returned = await self.inventory.dismantle_salvage(player, pw.weapon)
        await pw.delete()
        note = strings.INVENTORY_DISMANTLED.format(weapon=name)
        if returned:
            mats = "、".join(f"{mat.name}×{qty:,}" for mat, qty in returned)
            note += " " + strings.INVENTORY_DISMANTLE_RETURNED.format(mats=mats)
        # Refresh the weapons embed WITHOUT the note, then deliver the outcome
        # as its own ephemeral message rather than as content on the embed.
        await self.show_inventory_category(interaction, player, KIND_WEAPONS)
        await interaction.followup.send(note, ephemeral=True)

    async def _use_consumable(
        self, player: Player, material_id: int, target: Player | None = None
    ) -> tuple[Material | None, str]:
        """Consume one; returns (material, note) -- material is None when
        nothing was actually spent (the note then explains why).

        ``player`` PAYS the stack; the effect lands on ``target`` when given
        (the use-item context menu), otherwise on the user themselves.

        FOOD: alive-only, grants the regen-over-time buff (rate = value
        HP/min, duration in minutes; re-eating overwrites the buff).
        POTION (and legacy consumable): instant heal -- and the REVIVE path:
        usable at 0 HP, restoring up to its value.
        """
        recipient = target if target is not None else player
        on_other = recipient.id != player.id
        material = await Material.get_or_none(id=material_id)
        if (
            material is None
            or material.status != ContentStatus.ENABLED
            or material.kind not in (
                MaterialKind.FOOD, MaterialKind.POTION, MaterialKind.CONSUMABLE
            )
            or material.stat_bonus_type is None
        ):
            return None, "That can't be used right now."

        own_level = (await recipient.legion).level if recipient.legion_id else 0
        eff_max, regen_bonus = await effective_max_hp_and_regen(recipient, own_level)
        stype = material.stat_bonus_type
        value = material.stat_bonus_value or 0
        duration = material.duration or 0
        now = datetime.now().astimezone()

        if material.kind == MaterialKind.FOOD:
            if recipient.health_points <= 0:
                if on_other:
                    return None, strings.USE_ITEM_TARGET_DEAD_FOOD.format(
                        target=recipient.username
                    )
                return None, strings.DEAD_BLOCKED
            if not await self.inventory.consume(player, {material.id: 1}):
                return None, strings.INVENTORY_QTY_NOT_ENOUGH

            if stype in (StatBonusType.REGEN, StatBonusType.HP):
                # HP-per-minute regen buff. Flush the elapsed regen window first
                # (with the passive bonus) so the new rate isn't back-paid.
                await self.players.apply_regen(
                    recipient, own_level, eff_max, bonus_regen=regen_bonus
                )
                recipient.regen_buff_rate = value
                recipient.regen_buff_until = now + timedelta(minutes=duration)
                await recipient.save(
                    update_fields=["regen_buff_rate", "regen_buff_until"]
                )
                if on_other:
                    return material, strings.FOOD_BUFF_APPLIED_OTHER.format(
                        target=recipient.username, material=material.name,
                        value=value, duration=duration,
                    )
                return material, strings.FOOD_BUFF_APPLIED.format(
                    material=material.name, value=value, duration=duration,
                )

            # Timed combat-stat buff (atk/def/speed/taunt): re-eating refreshes
            # the same stat; different stats stack.
            buffs = dict(recipient.stat_buffs or {})
            buffs[str(stype)] = {
                "value": value,
                "until": int((now + timedelta(minutes=duration)).timestamp()),
            }
            recipient.stat_buffs = buffs
            await recipient.save(update_fields=["stat_buffs"])
            category = strings.STAT_NAMES.get(str(stype), str(stype))
            if on_other:
                return material, strings.FOOD_BUFF_EFFECT_APPLIED_OTHER.format(
                    target=recipient.username, material=material.name,
                    value=value, category=category, duration=duration,
                )
            return material, strings.FOOD_BUFF_EFFECT_APPLIED.format(
                material=material.name, value=value,
                category=category, duration=duration,
            )

        # potion / consumable: instant, revive-capable
        if not await self.inventory.consume(player, {material.id: 1}):
            return None, strings.INVENTORY_QTY_NOT_ENOUGH
        was_dead = recipient.health_points <= 0
        healed = min(value, eff_max - recipient.health_points)
        recipient.health_points += healed
        # Re-bookmark so a revive doesn't backpay dead downtime as regen.
        recipient.hp_updated_at = now
        await recipient.save(update_fields=["health_points", "hp_updated_at"])
        if was_dead:
            if on_other:
                return material, strings.REVIVED_OTHER.format(
                    target=recipient.username, material=material.name, healed=healed
                )
            return material, strings.REVIVED.format(
                material=material.name, healed=healed
            )
        if on_other:
            return material, strings.INVENTORY_USED_OTHER.format(
                target=recipient.username, material=material.name, healed=healed
            )
        return material, strings.INVENTORY_USED.format(
            material=material.name,
            healed=healed,
            hp=recipient.health_points,
            max_hp=eff_max,  # dynamic effective max, not the stored base
        )

    # --- use item on others (context menu) -----------------------------------------

    async def use_item_context(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        """Entry: right-click member -> Apps -> 使用道具. Ephemeral picker of
        the INVOKER'S consumables; effects land on the target (revive included)."""
        if interaction.guild is None:
            return
        player = await self.ensure_player(interaction)
        if player is None or not await self.ensure_not_afk(interaction, player):
            return
        if not await self.ensure_alive(interaction, player):
            return  # the dead can't nurse others; self-revive via inventory
        if member.bot:
            await self._notify(interaction, strings.USE_ITEM_TARGET_NOT_PLAYER)
            return
        target = await self.players.get(member.id)
        if target is None:
            await self._notify(interaction, strings.USE_ITEM_TARGET_NOT_PLAYER)
            return
        if not await self._mastery_gap_ok(player, target):
            await self._notify(
                interaction,
                strings.USE_ITEM_MASTERY_GAP.format(target=target.username),
            )
            return
        stacks = await self._usable_stacks(player)
        if not stacks:
            await self._notify(interaction, strings.USE_ITEM_NONE)
            return
        view = UseItemView(self, interaction.user.id, member.id, stacks)
        await interaction.response.send_message(
            strings.USE_ITEM_PICK.format(target=target.username),
            view=view, ephemeral=True,
        )
        view.message = await interaction.original_response()

    async def use_item_on(
        self,
        interaction: discord.Interaction,
        target_discord_id: int,
        material_id: int,
    ) -> None:
        """Select callback: spend the invoker's stack on the target."""
        await self._defer(interaction)
        player = await self.players.get(interaction.user.id)
        target = await self.players.get(target_discord_id)
        if player is None or target is None:
            await self._notify(interaction, strings.USE_ITEM_TARGET_NOT_PLAYER)
            return
        if player.health_points <= 0:  # died since the picker opened
            await self._notify(interaction, strings.DEAD_BLOCKED)
            return
        on_other = target.id != player.id
        if on_other and not await self._mastery_gap_ok(player, target):
            await self._edit_tracked(
                interaction,
                content=strings.USE_ITEM_MASTERY_GAP.format(target=target.username),
                view=None,
            )
            return
        used, note = await self._use_consumable(
            player, material_id, target=target if on_other else None
        )
        if used is not None and on_other:
            # The flavor line goes PUBLIC ("X 對 Y 使用了 Z，Z 將 Y 從鬼門關
            # 拉了回來…"); the user's ephemeral just gets the short receipt.
            legion = await self._legion_for(interaction.guild)
            channel = (
                interaction.guild.get_channel(legion.channel_id)
                if legion.channel_id else None
            )
            if channel is not None:
                await channel.send(
                    strings.USE_ITEM_ANNOUNCE.format(
                        player=player.username,
                        target=target.username,
                        material=used.name,
                        result=note,
                    )
                )
            note = strings.USE_ITEM_SHORT_NOTE.format(
                target=target.username, material=used.name
            )
        stacks = await self._usable_stacks(player)
        if stacks:
            view = UseItemView(self, interaction.user.id, target_discord_id, stacks)
            await self._edit_tracked(
                interaction,
                content=f"{note}\n{strings.USE_ITEM_PICK.format(target=target.username)}",
                view=view,
            )
        else:
            await self._edit_tracked(interaction, content=note, view=None)

    async def _mastery_gap_ok(self, feeder: Player, feedee: Player) -> bool:
        """Anti-mule gate: the FEEDER'S total mastery may trail the target's
        by at most USE_ITEM_MASTERY_GAP_PCT -- a fresh AFK alt can't farm
        potions and pump them up to a veteran main. Feeding downward
        (veteran helping a newbie) is always fine."""
        if feeder.id == feedee.id:
            return True
        feeder_total = await self.masteries.total_mastery(feeder)
        feedee_total = await self.masteries.total_mastery(feedee)
        return feeder_total * 100 >= feedee_total * (100 - USE_ITEM_MASTERY_GAP_PCT)

    async def _usable_stacks(self, player: Player) -> list[PlayerMaterial]:
        return await PlayerMaterial.filter(
            player=player,
            quantity__gt=0,
            material__status=ContentStatus.ENABLED,
            material__kind__in=[
                MaterialKind.FOOD, MaterialKind.POTION, MaterialKind.CONSUMABLE
            ],
        ).prefetch_related("material")
    
    async def showoff_profile_context(self, interaction: discord.Interaction, member: discord.Member) -> None:
        """Allow others to summon a visable profile of a player, but only if they have one (onboarded)."""
        if interaction.guild is None:
            return
        if self._patch_blocked():  # frozen blocks ALL commands
            await self._send_patch_blocked(interaction)
            return
        # NOTE: deliberately no ensure_player here -- non-players may view
        # others' profiles; they just can't summon their own.
        if member.bot:
            await self._notify(interaction, strings.PROFILE_TARGET_NOT_PLAYER)
            return
        target = await self.players.get(member.id)
        if target is None:
            await self._notify(interaction, strings.PROFILE_TARGET_NOT_PLAYER)
            return
        await self._defer(interaction)  # several queries follow; 3s token

        legion = await target.legion if target.legion_id else None
        eff_max = await effective_max_hp(target, legion.level if legion else 0)
        # Flush the TARGET'S lazy regen (and any overdue auto-revive): they
        # may not have run a command in hours -- don't show stale HP.
        await self.players.apply_regen(target, legion.level if legion else 0, eff_max)
        equipped = {
            slot: await self.inventory.equipped(target, slot)
            for slot in (WeaponSlot.MAIN, WeaponSlot.SUB)
        }
        embed = render.profile_embed(
            target, legion, equipped, self.bot.color, effective_max=eff_max
        )
        embed.set_author(name=strings.SHOWOFF_PROFILE_TITLE.format(
            name=target.username),
            icon_url=member.display_avatar.url
        )
        masteries = await WeaponMastery.filter(player=target).order_by("-level", "-exp").limit(2).prefetch_related(
            "category"
        )
        for mastery in masteries:
            if mastery.level >= MASTERY_HARD_CAP:
                value = f"{render.progress_bar(100)}\n-# {strings.MAX_EMOJI}"
            else:
                need = mastery_level_cost(mastery.level + 1)
                value = f"{render.progress_bar(mastery.exp / max(1, need) * 100)}\n-# {mastery.exp:,}/{need:,}"
            embed.add_field(
                name=strings.MASTERY_SUMMARY.format(
                    category=mastery.category.name, level=mastery.level
                ),
                value=value,
                inline=False,
            )

        embed.set_footer(text=strings.SHOWOFF_PROFILE_FOOTER.format(
            author=interaction.user.display_name
        ))
        await interaction.followup.send(embed=embed)  # public by design

    # --- /gatherer -----------------------------------------------------------------

    @app_commands.command(
        name=strings.GATHERER_COMMAND_NAME, description=strings.GATHERER_COMMAND_DESC
    )
    @app_commands.guild_only()
    async def gatherer(self, interaction: discord.Interaction) -> None:
        player = await self.ensure_player(interaction)
        if player is None:
            return
        activity = await self.activities.active_for(player)
        if activity is not None:
            possible = [
                y.material.name
                for y in await SiteYield.filter(
                    site=activity.site
                ).prefetch_related("material")
            ]
            busy_view = GatherBusyView(self, interaction.user.id, player)
            await interaction.response.send_message(
                embed=render.gather_busy_embed(activity, possible, self.bot.color),
                view=busy_view,
                ephemeral=True,
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
        await interaction.response.send_message(
            embed=render.gather_idle_embed(sites, yields_by_site, self.bot.color),
            view=idle_view,
            ephemeral=True,
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
            await interaction.response.send_message(strings.GATHER_NO_SUCH_SITE, ephemeral=True)
            return
        activity = await self.activities.start(player, site)
        if activity is None:
            await interaction.response.send_message(
                strings.GATHER_BLOCKED_SHORT, ephemeral=True
            )
            return
        await self._edit_tracked(interaction, 
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
            await interaction.response.send_message(
                strings.GATHER_NOTHING, ephemeral=True
            )
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
            result += strings.GATHER_RESULT.format(
                loot=", ".join(loot_parts), pts=pts
            )
        else:
            result += strings.GATHER_RESULT_EMPTY

        await self._edit_tracked(interaction, 
            content=result,
            embed=None,
            view=None,
        )

    # --- /craft ---------------------------------------------------------------------

    @app_commands.command(name=strings.CRAFTING_COMMAND_NAME, description=strings.CRAFTING_COMMAND_DESC)
    @app_commands.guild_only()
    async def craft_command(self, interaction: discord.Interaction) -> None:
        player = await self.ensure_player(interaction)
        if player is None or not await self.ensure_not_afk(interaction, player):
            return
        await self.show_craft_home(interaction, player, edit=False)

    async def _craft_groups(
        self, player: Player
    ) -> tuple[dict[str, list], dict]:
        """Enabled recipes grouped by workstation, marked unlocked-by-mastery,
        plus the player's life-skill levels."""
        levels = {
            m.skill: m.level for m in await LifeSkillMastery.filter(player=player)
        }
        groups: dict[str, list] = {"forge": [], "cook": [], "brew": []}
        for recipe in await Recipe.filter(status=ContentStatus.ENABLED):
            if recipe.skill is None:
                groups["forge"].append((recipe, True))
            else:
                unlocked = (
                    levels.get(recipe.skill, 0) >= recipe.mastery_level_required
                )
                groups[recipe.skill.value].append((recipe, unlocked))
        return groups, levels

    async def show_craft_home(
        self, interaction: discord.Interaction, player: Player, edit: bool = True
    ) -> None:
        groups, levels = await self._craft_groups(player)
        embed = render.craft_home_embed(groups, levels, self.bot.color)
        view = CraftHomeView(self, interaction.user.id, player)
        if edit:
            await self._edit_tracked(interaction, 
                content=None, embed=embed, view=view
            )
        else:
            await interaction.response.send_message(
                embed=embed, view=view, ephemeral=True
            )
            view.message = await interaction.original_response()

    async def show_craft_surface(
        self,
        interaction: discord.Interaction,
        player: Player,
        surface: str,
        note: str | None = None,
    ) -> None:
        groups, _ = await self._craft_groups(player)
        # Forge select is filtered to recipes the player holds at least one of
        # the required materials for; the embed still lists them all.
        owned = set(
            await PlayerMaterial.filter(
                player=player, quantity__gt=0
            ).values_list("material_id", flat=True)
        )
        entries = []
        craftable = []
        for recipe, unlocked in groups.get(surface, []):
            inputs = await RecipeMaterial.filter(recipe=recipe).prefetch_related(
                "material"
            )
            text = ", ".join(strings.CRAFT_MAT_DETAIL.format(name=i.material.name, count=i.quantity) for i in inputs)
            entries.append((recipe, unlocked, text))
            has_material = any(i.material_id in owned for i in inputs)
            if unlocked and (surface != "forge" or has_material):
                craftable.append(recipe)
        embeds = render.craft_surface_embed(surface, entries, self.bot.color)
        await self._edit_tracked(interaction,
            content=note,
            embed=embeds[0],
            view=CraftSurfaceView(
                self, interaction.user.id, player, surface, craftable,
                embeds=embeds,
            ),
        )

    async def _recipe_costs(self, recipe: Recipe, player: Player):
        """``([(material, need, have)], affordable)`` for a recipe."""
        inputs = []
        affordable = True
        for rm in await RecipeMaterial.filter(recipe=recipe).prefetch_related(
            "material"
        ):
            have = await self.inventory.quantity(player, rm.material)
            inputs.append((rm.material, rm.quantity, have))
            if have < rm.quantity:
                affordable = False
        return inputs, affordable

    async def _recipe_mastery_ok(self, recipe: Recipe, player: Player) -> bool:
        if recipe.skill is None:
            return True
        mastery = await LifeSkillMastery.get_or_none(
            player=player, skill=recipe.skill
        )
        return (mastery.level if mastery else 0) >= recipe.mastery_level_required

    async def show_recipe_detail(
        self,
        interaction: discord.Interaction,
        player: Player,
        recipe_id: int,
        note: str | None = None,
    ) -> None:
        """Craft layer 3: the recipe in full -- result stats (base values;
        mutations roll at craft time), inputs have/need, Craft + Return."""
        recipe = await Recipe.get_or_none(id=recipe_id).prefetch_related(
            "result_weapon__category", "result_material"
        )
        if recipe is None:
            await interaction.response.send_message(strings.CRAFT_NO_SUCH_RECIPE, ephemeral=True)
            return
        surface = recipe.skill.value if recipe.skill else "forge"
        inputs, affordable = await self._recipe_costs(recipe, player)
        craftable = affordable and await self._recipe_mastery_ok(recipe, player)

        if recipe.result_weapon is not None:
            actives = (
                await WeaponActiveSkill.filter(
                    weapon=recipe.result_weapon,
                    active_skill__status=ContentStatus.ENABLED,
                )
                .order_by("tier")
                .prefetch_related("active_skill")
            )
            passives = (
                await WeaponPassiveSkill.filter(
                    weapon=recipe.result_weapon,
                    passive_skill__status=ContentStatus.ENABLED,
                )
                .order_by("tier")
                .prefetch_related("passive_skill")
            )
            mastery = await WeaponMastery.get_or_none(
                player=player, category_id=recipe.result_weapon.category_id
            )
            from maki.cogs.legion.constants import MUTATION_MAX, MUTATION_MIN

            embed = render.recipe_detail_embed(
                recipe, inputs, self.bot.color,
                weapon=recipe.result_weapon,
                actives=actives, passives=passives,
                weapon_mastery=mastery.level if mastery else 0,
                mutation_range=(MUTATION_MIN, MUTATION_MAX),
            )
        else:
            embed = render.recipe_detail_embed(
                recipe, inputs, self.bot.color, material=recipe.result_material
            )
        await self._edit_tracked(
            interaction,
            content=note,
            embed=embed,
            view=RecipeDetailView(
                self, interaction.user.id, player, surface, recipe.id, craftable
            ),
        )

    async def confirm_craft(
        self, interaction: discord.Interaction, player: Player, recipe_id: int
    ) -> None:
        """The ephemeral are-you-sure predicate before crafting."""
        recipe = await Recipe.get_or_none(id=recipe_id).prefetch_related(
            "result_weapon", "result_material"
        )
        if recipe is None:
            await interaction.response.send_message(strings.CRAFT_NO_SUCH_RECIPE, ephemeral=True)
            return
        item = (
            recipe.result_weapon.name
            if recipe.result_weapon
            else recipe.result_material.name if recipe.result_material else recipe.name
        )
        confirm = CraftConfirmView(self, interaction.user.id, player, recipe_id)
        await interaction.response.send_message(
            strings.CRAFT_CONFIRM.format(item=item), view=confirm, ephemeral=True
        )
        confirm.message = await interaction.original_response()

    async def do_craft(
        self, interaction: discord.Interaction, player: Player, recipe_id: int
    ) -> None:
        """Perform the craft on the ephemeral confirm message: validate,
        consume, then the crafting animation -- the dot count quietly
        telegraphs the rolled quality -- and finally the detailed result."""
        await self._defer(interaction)
        if not await self.ensure_not_afk(interaction, player):
            return
        if not await self.ensure_alive(interaction, player):
            return
        recipe = await Recipe.get_or_none(id=recipe_id).prefetch_related(
            "result_weapon__category", "result_material"
        )
        if recipe is None:
            await self._edit_tracked(
                interaction, content=strings.CRAFT_NOTHING, view=None
            )
            return
        if not await self._recipe_mastery_ok(recipe, player):
            await self._edit_tracked(
                interaction,
                content=strings.CRAFT_NEED_MASTERY.format(
                    skill=strings.LIFE_SKILL_NAMES.get(
                        recipe.skill.value, recipe.skill.value
                    ),
                    req=recipe.mastery_level_required,
                ),
                view=None,
            )
            return
        costs = {
            rm.material_id: rm.quantity
            for rm in await RecipeMaterial.filter(recipe=recipe)
        }
        if not await self.inventory.consume(player, costs):
            await self._edit_tracked(
                interaction,
                content=strings.CRAFT_SHORT_MATS.format(recipe=recipe.name),
                view=None,
            )
            return

        if recipe.result_weapon is not None:
            legion_level = 0
            if player.legion_id:
                legion_level = (await player.legion).level
            skill_ids = [
                *(
                    a.active_skill_id
                    for a in await WeaponActiveSkill.filter(
                        weapon=recipe.result_weapon
                    )
                ),
                *(
                    p.passive_skill_id
                    for p in await WeaponPassiveSkill.filter(
                        weapon=recipe.result_weapon
                    )
                ),
            ]
            mutations = roll_mutations(skill_ids, legion_level)
            pw = await self.inventory.grant_weapon(
                player, recipe.result_weapon, mutations=mutations
            )
            item = recipe.result_weapon.name
            dots = strings.QUALITY_DOTS.get(pw.quality.value, 3)
        else:
            pw = None
            item = recipe.result_material.name if recipe.result_material else recipe.name
            dots = 3

        # The show: crafting… with the quality-tell dot count.
        await self._edit_tracked(
            interaction,
            content=strings.CRAFT_CRAFTING.format(item=item) + ".", view=None,
        )
        message = await interaction.original_response()
        for i in range(2, dots + 1):
            await asyncio.sleep(0.8)
            await message.edit(
                content=strings.CRAFT_CRAFTING.format(item=item) + "." * i
            )
        await asyncio.sleep(0.8)

        if pw is not None:
            pw = await PlayerWeapon.get(id=pw.id).prefetch_related("weapon__category")
            actives = (
                await WeaponActiveSkill.filter(
                    weapon=pw.weapon, active_skill__status=ContentStatus.ENABLED
                )
                .order_by("tier")
                .prefetch_related("active_skill")
            )
            passives = (
                await WeaponPassiveSkill.filter(
                    weapon=pw.weapon, passive_skill__status=ContentStatus.ENABLED
                )
                .order_by("tier")
                .prefetch_related("passive_skill")
            )
            mastery = await WeaponMastery.get_or_none(
                player=player, category_id=pw.weapon.category_id
            )
            await message.edit(
                content=None,
                embed=render.weapon_detail_embed(
                    pw, actives, passives,
                    mastery.level if mastery else 0,
                    self.bot.color,
                ),
            )
        else:
            if recipe.result_material is not None:
                await self.inventory.add_material(
                    player, recipe.result_material, recipe.result_qty
                )
                if recipe.skill is not None:
                    await self.masteries.grant_life(
                        player, recipe.skill, CRAFT_MASTERY_PTS
                    )
                await message.edit(
                    content=strings.CRAFT_MADE.format(
                        qty=recipe.result_qty, material=recipe.result_material.name
                    )
                )
            else:
                await message.edit(content=strings.CRAFT_NOTHING)

    # --- [p]settings (owner-only text command group) ------------------------------

    @commands.group(name="admin", hidden=True, invoke_without_command=True)
    @commands.is_owner()
    async def admin_group(self, ctx: commands.Context) -> None:
        """Owner console. Target = a @user/user-id (player) or guild-id (legion)."""
        prefix = (await self.bot.get_prefix(""))[-1]
        embed = discord.Embed(
            title="⚙️ Owner Console",
            description=(
                "Admin tools for players & legions. **Target** is a "
                "`@user`/user-id (player) or a guild-id (legion)."
            ),
            color=self.bot.color,
        )
        legion_fields = ", ".join(f"`{f}`" for f in self._LEGION_SET_FIELDS)
        player_fields = ", ".join(f"`{f}`" for f in self._PLAYER_SET_FIELDS)
        embed.add_field(
            name=f"{prefix}admin get <user|guild>",
            value="Inspect a player or a legion — stats, level, contribution, "
            "channel, member counts.",
            inline=False,
        )
        embed.add_field(
            name=f"{prefix}admin give <user|guild> <item> [qty]",
            value="Grant an item (by key or name). A **user** fills their bag; "
            "a **guild** fills the legion stockpile (materials only). `qty` ≤ 100.",
            inline=False,
        )
        embed.add_field(
            name=f"{prefix}admin remove <user|guild> <item> [qty]  ·  alias rm",
            value="Take an item back — from a player's bag or a legion stockpile.",
            inline=False,
        )
        embed.add_field(
            name=f"{prefix}admin set <user|guild> <field> [value]",
            value="Set a field, or **omit the value to read** the current one.\n"
            f"Legion: {legion_fields}\n"
            f"Player: {player_fields}, or a **mastery** — a weapon category "
            "(`sword`, `bow`, …) or life skill (`mine`/`garden`/`cook`/`brew`).",
            inline=False,
        )
        embed.add_field(
            name=f"{prefix}admin freeze [on|off]",
            value="Maintenance freeze: blocks **all** commands — the graceful "
            "lead-in to a force patch. Bare toggles; clears on restart.",
            inline=False,
        )
        embed.add_field(
            name=f"{prefix}admin patch",
            value="Staged content updates: review, schedule, or force-apply the "
            "on-disk patch.",
            inline=False,
        )
        await ctx.send(embed=embed)

    @staticmethod
    async def _resolve_item(item: str):
        """Look up a Material or Weapon by stable key, then by display name.
        Returns ``(material, weapon)`` with exactly one set, or ``(None, None)``."""
        material = await Material.get_or_none(
            key=item
        ) or await Material.get_or_none(name=item)
        if material is not None:
            return material, None
        weapon = await Weapon.get_or_none(
            key=item
        ) or await Weapon.get_or_none(name=item)
        return None, weapon

    # exposed field -> (model attribute, caster)
    _LEGION_SET_FIELDS = {
        "level": ("level", int),
        "exp": ("exp", int),
        "name": ("name", str),
        "channel_id": ("channel_id", int),
        "killcount": ("daily_kills", int),
    }
    _PLAYER_SET_FIELDS = {
        "nickname": ("username", str),
        "health": ("health_points", int),
        "contribution": ("contribution", int),
    }

    @admin_group.command(name="get")
    @commands.is_owner()
    async def admin_get(
        self, ctx: commands.Context, target: Union[discord.User, discord.Guild]
    ) -> None:
        """Inspect a player (user) or a legion (guild)."""
        if isinstance(target, discord.Guild):
            legion = await self.legions.get(target.id)
            if legion is None:
                await ctx.send("No legion for that guild id.")
                return
            members = await Player.filter(legion=legion).count()
            active = await self.legions.active_member_count(legion)
            await ctx.send(
                f"🏰 **{legion.name}** (guild {legion.guild_id})\n"
                f"level {legion.level} · exp {legion.exp} · "
                f"kills today {legion.daily_kills} · "
                f"members {members} ({active} active) · "
                f"channel {legion.channel_id or '*unset*'}"
            )
            return
        player = await self.players.get(target.id)
        if player is None:
            await ctx.send("That user hasn't onboarded yet.")
            return
        legion = await player.legion if player.legion_id else None
        await ctx.send(
            f"🧑 **{player.username}** (id {player.discord_id})\n"
            f"hp {player.health_points}/{player.max_health_points} · "
            f"legion {legion.name if legion else '*none*'} · "
            f"contribution {player.contribution} · "
            f"manager {player.is_legion_manager}"
        )

    @admin_group.command(name="give")
    @commands.is_owner()
    async def admin_give(
        self,
        ctx: commands.Context,
        target: Union[discord.User, discord.Guild],
        item: str,
        qty: int = 1,
    ) -> None:
        """Give an item to a player's bag (user) or a legion stockpile (guild)."""
        qty = max(1, min(qty, 100))
        material, weapon = await self._resolve_item(item)
        if isinstance(target, discord.Guild):
            legion = await self.legions.get(target.id)
            if legion is None:
                await ctx.send("No legion for that guild id.")
                return
            if material is None:
                await ctx.send("Legion stockpiles hold materials only.")
                return
            total = await self.legions.stock_add(legion, material, qty)
            await ctx.send(
                f"✅ {legion.name} stockpile +{material.name}×{qty} (now {total:,})"
            )
            return
        player = await self.players.get(target.id)
        if player is None:
            await ctx.send("That user hasn't onboarded yet.")
            return
        if material is not None:
            await self.inventory.add_material(player, material, qty)
            await ctx.send(f"✅ {player.username} +{material.name}×{qty}")
        elif weapon is not None:
            for _ in range(min(qty, 10)):
                await self.inventory.grant_weapon(player, weapon)
            await ctx.send(
                f"✅ {player.username} +{min(qty, 10)}× {weapon.name} (flat)"
            )
        else:
            await ctx.send(f"❌ No material or weapon named `{item}`.")

    @admin_group.command(name="remove", aliases=["rm"])
    @commands.is_owner()
    async def admin_remove(
        self,
        ctx: commands.Context,
        target: Union[discord.User, discord.Guild],
        item: str,
        qty: int = 1,
    ) -> None:
        """Remove an item from a player's bag (user) or legion stockpile (guild)."""
        qty = max(1, min(qty, 100))
        material, weapon = await self._resolve_item(item)
        if isinstance(target, discord.Guild):
            legion = await self.legions.get(target.id)
            if legion is None:
                await ctx.send("No legion for that guild id.")
                return
            if material is None:
                await ctx.send("Legion stockpiles hold materials only.")
                return
            total = await self.legions.stock_remove(legion, material, qty)
            if total is None:
                await ctx.send(
                    f"❌ {legion.name} stockpile short of {material.name}×{qty}."
                )
            else:
                await ctx.send(
                    f"✅ {legion.name} stockpile −{material.name}×{qty} (now {total:,})"
                )
            return
        player = await self.players.get(target.id)
        if player is None:
            await ctx.send("That user hasn't onboarded yet.")
            return
        if material is not None:
            if await self.inventory.consume(player, {material.id: qty}):
                await ctx.send(f"✅ {player.username} −{material.name}×{qty}")
            else:
                await ctx.send(
                    f"❌ {player.username} doesn't have {material.name}×{qty}."
                )
        elif weapon is not None:
            pw = await PlayerWeapon.filter(
                player=player, weapon=weapon, equipped_slot__isnull=True
            ).first()
            if pw is None:
                await ctx.send("❌ No unequipped instance to remove (unequip first).")
            else:
                await pw.delete()
                await ctx.send(f"✅ removed one {weapon.name} from {player.username}")
        else:
            await ctx.send(f"❌ No material or weapon named `{item}`.")

    @admin_group.command(name="set")
    @commands.is_owner()
    async def admin_set(
        self,
        ctx: commands.Context,
        target: Union[discord.User, discord.Guild],
        field: str,
        *,
        value: str | None = None,
    ) -> None:
        """Set a field on a player (user) or legion (guild). Omit the value to
        READ the current one instead. Player fields include each mastery (a
        weapon category key or a life skill: mine/garden/cook/brew)."""
        field = field.lower()
        if isinstance(target, discord.Guild):
            legion = await self.legions.get(target.id)
            if legion is None:
                await ctx.send("No legion for that guild id.")
                return
            spec = self._LEGION_SET_FIELDS.get(field)
            if spec is None:
                await ctx.send(f"Legion fields: {', '.join(self._LEGION_SET_FIELDS)}")
                return
            attr, caster = spec
            if value is None:
                await ctx.send(f"🏰 {legion.name} · `{field}` = {getattr(legion, attr)}")
                return
            try:
                parsed = caster(value)
            except ValueError:
                await ctx.send(f"`{field}` needs a {caster.__name__}.")
                return
            if attr == "name":
                parsed = clean_legion_name(parsed)
            setattr(legion, attr, parsed)
            await legion.save(update_fields=[attr])
            await ctx.send(f"✅ {legion.name}: `{field}` → {parsed}")
            return

        player = await self.players.get(target.id)
        if player is None:
            await ctx.send("That user hasn't onboarded yet.")
            return
        spec = self._PLAYER_SET_FIELDS.get(field)
        if spec is not None:
            attr, caster = spec
            if value is None:
                await ctx.send(f"🧑 {player.username} · `{field}` = {getattr(player, attr)}")
                return
            try:
                parsed = caster(value)
            except ValueError:
                await ctx.send(f"`{field}` needs a {caster.__name__}.")
                return
            if attr == "username":
                parsed = clean_player_name(parsed)
            setattr(player, attr, parsed)
            await player.save(update_fields=[attr])
            await ctx.send(f"✅ {player.username}: `{field}` → {parsed}")
            return
        # anything else: treat the field as a mastery (weapon category / life skill)
        await self._admin_set_mastery(ctx, player, field, value)

    async def _admin_set_mastery(
        self, ctx: commands.Context, player: Player, field: str, value: str | None
    ) -> None:
        """Read/set one of a player's masteries -- a weapon category (key or
        name) or a life skill (mine/garden/cook/brew). Sets the LEVEL (exp is
        zeroed); omit the value to read the current level."""
        category = (
            await WeaponCategory.get_or_none(key=field)
            or await WeaponCategory.get_or_none(name=field)
        )
        life = next((t for t in LifeSkillType if t.value == field), None)
        if category is None and life is None:
            cats = [c.key for c in await WeaponCategory.all() if c.key]
            skills = [t.value for t in LifeSkillType]
            await ctx.send(
                f"Player fields: {', '.join(self._PLAYER_SET_FIELDS)}; "
                f"masteries: {', '.join(cats + skills)}"
            )
            return
        if category is not None:
            row = await WeaponMastery.get_or_none(player=player, category=category)
            label = category.name
        else:
            row = await LifeSkillMastery.get_or_none(player=player, skill=life)
            label = field
        if value is None:
            await ctx.send(
                f"🧑 {player.username} · {label} 精通 = {row.level if row else 0}"
            )
            return
        try:
            level = int(value)
        except ValueError:
            await ctx.send("Mastery level must be an integer.")
            return
        if row is not None:
            row.level, row.exp = level, 0
            await row.save(update_fields=["level", "exp"])
        elif category is not None:
            await WeaponMastery.create(
                player=player, category=category, level=level, exp=0
            )
        else:
            await LifeSkillMastery.create(
                player=player, skill=life, level=level, exp=0
            )
        await ctx.send(f"✅ {player.username}: {label} 精通 → {level}")

    @admin_group.command(name="freeze")
    @commands.is_owner()
    async def settings_freeze(
        self, ctx: commands.Context, state: str | None = None
    ) -> None:
        """Maintenance freeze: block ALL commands while you force a patch.

        `admin freeze on` / `off`, or bare `admin freeze` to toggle. Persisted,
        so it SURVIVES a restart -- the graceful lead-in to `admin patch`
        force-apply. Remember to `admin freeze off` once you're done.
        """
        if state is None:
            self._frozen = not self._frozen
        elif state.lower() in ("on", "true", "1", "freeze"):
            self._frozen = True
        elif state.lower() in ("off", "false", "0", "unfreeze"):
            self._frozen = False
        else:
            await ctx.send("Usage: `admin freeze [on|off]`")
            return
        await self.system.set_flag(FREEZE_FLAG_KEY, self._frozen)
        await ctx.send(
            "🧊 **FROZEN** — all commands blocked. Force the patch, then "
            "`admin freeze off`."
            if self._frozen
            else "☀️ **Unfrozen** — commands resumed."
        )

    @admin_group.command(name="patch")
    @commands.is_owner()
    async def settings_patch(self, ctx: commands.Context) -> None:
        """Game patch status & staged updates."""
        current = await self.patches.current()
        live_counts = {
            "materials": await Material.all().count(),
            "categories": await WeaponCategory.all().count(),
            "weapons": await Weapon.all().count(),
            "skills": await ActiveSkill.all().count(),
            "mobs": await Mob.all().count(),
            "grounds": await HuntingGround.all().count(),
            "recipes": await Recipe.all().count(),
            "players": await Player.all().count(),
        }
        legion = await self.legions.get(ctx.guild.id) if ctx.guild else None
        pending = await self.patches.pending()
        self._pending_patch = pending
        embed = render.patch_status_embed(
            current, live_counts, PATCH["version"], content_hash(),
            legion, self.bot.color,
        )
        if pending is not None:
            embed.add_field(
                name="Scheduled",
                value=strings.PATCH_SCHEDULED.format(
                    lock=int(pending.lock_at.timestamp()),
                    apply=int(pending.apply_at.timestamp()),
                ),
                inline=False,
            )
        patch_view = PatchView(self, ctx.author.id, pending is not None)
        patch_view.message = await ctx.send(embed=embed, view=patch_view)

    async def patch_check(
        self, interaction: discord.Interaction, view: PatchView
    ) -> None:
        current = await self.patches.current()
        changed = current is None or current.hash != content_hash()
        if not changed:
            await interaction.response.send_message(
                strings.PATCH_UP_TO_DATE, ephemeral=True
            )
            return
        # Validate BEFORE offering the update -- broken references die at
        # review time, never at apply time.
        problems = validate_patch()
        if problems:
            shown = "\n".join(f"- {e}" for e in problems[:15])
            if len(problems) > 15:
                shown += f"\n… and {len(problems) - 15} more"
            await interaction.response.send_message(
                f"❌ The on-disk patch is invalid ({len(problems)} problems):\n"
                f"```\n{shown}\n```",
                ephemeral=True,
            )
            return
        view.check.disabled = True
        view.view_update.disabled = False
        await self._edit_tracked(interaction, 
            content=strings.PATCH_UPDATE_FOUND, view=view
        )

    async def patch_show_compare(self, interaction: discord.Interaction) -> None:
        current = await self.patches.current()
        embed = render.patch_compare_embed(
            current.version if current else "—",
            dict(current.summary) if current else {},
            PATCH["version"],
            PATCH.get("notes"),
            content_summary(),
            content_hash(),
            self.bot.color,
        )
        # Review safety net: keys that vanished from content.py get tombstoned
        # at apply -- an accidental key rename shows up right here.
        removals = await pending_removals()
        if removals:
            lines = [
                f"**{section}**: {', '.join(entries)}"
                for section, entries in removals.items()
            ]
            embed.add_field(
                name="⚠️ Will be REMOVED (tombstoned)",
                value="\n".join(lines)[:1000],
                inline=False,
            )
        await self._edit_tracked(interaction, 
            content=None,
            embed=embed,
            view=PatchDecisionView(self, interaction.user.id),
        )

    async def patch_schedule(self, interaction: discord.Interaction) -> None:
        lock_at, apply_at = patch_timeline(datetime.now().astimezone())
        pending = await self.patches.schedule(
            content_hash(), PATCH["version"], PATCH.get("notes"),
            content_summary(), lock_at, apply_at,
        )
        if pending is None:
            await interaction.response.send_message(
                "A patch is already scheduled.", ephemeral=True
            )
            return
        self._pending_patch = pending
        self._start_patch_timer(pending)
        await self._edit_tracked(interaction, 
            content=strings.PATCH_SCHEDULED.format(
                lock=int(lock_at.timestamp()), apply=int(apply_at.timestamp())
            ),
            embed=None,
            view=None,
        )

    async def patch_cancel_scheduled(
        self, interaction: discord.Interaction
    ) -> None:
        pending = await self.patches.pending()
        if pending is not None:
            await self.patches.cancel(pending)
        if self._patch_task is not None:
            self._patch_task.cancel()
            self._patch_task = None
        self._pending_patch = None
        await self._edit_tracked(interaction, 
            content=strings.PATCH_CANCELLED, embed=None, view=None
        )

    async def patch_apply_now(self, interaction: discord.Interaction) -> None:
        """Force update: applies immediately (2-stage confirm already passed)."""
        await interaction.response.defer(ephemeral=True)
        pending = await self.patches.pending()
        if pending is not None:
            await self.patches.cancel(pending)
        if self._patch_task is not None:
            self._patch_task.cancel()
            self._patch_task = None
        self._pending_patch = None
        created = await self._apply_and_record()
        await interaction.followup.send(
            strings.PATCH_APPLIED.format(
                version=PATCH["version"], hash=content_hash(), created=created
            ),
            ephemeral=True,
        )

    async def _apply_and_record(self) -> int:
        created = await apply_patch()
        await self.patches.record_applied(
            content_hash(), PATCH["version"], PATCH.get("notes"), content_summary()
        )
        log.info(
            "Applied patch {} ({}) — {} new rows.",
            PATCH["version"], content_hash(), created,
        )
        return created

    def _start_patch_timer(self, pending: GamePatch) -> None:
        async def timer() -> None:
            delay = (
                pending.apply_at - datetime.now().astimezone()
            ).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
            await apply_patch()
            await self.patches.mark_applied(pending)
            self._pending_patch = None
            log.info("Scheduled patch {} applied.", pending.version)

        if self._patch_task is not None:
            self._patch_task.cancel()
        self._patch_task = asyncio.create_task(timer())

