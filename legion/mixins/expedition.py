"""Expedition mixin: /expedition, the anti-script captcha, ground pickers,
the lobby timer, and the fight -> settlement -> replay pipeline."""

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from loguru import logger as log

from maki.cogs.legion import render, strings
from maki.cogs.legion.constants import (
    CAPTCHA_BLACKLIST_AT_SECONDS,
    CAPTCHA_BUTTONS,
    CAPTCHA_INTERVAL_TOLERANCE,
    CAPTCHA_LOCKOUT_BASE,
    CAPTCHA_RUNS_CHANCE_CAP,
    CAPTCHA_RUNS_CHANCE_STEP,
    CAPTCHA_RUNS_GRACE,
    CAPTCHA_RUNS_RESET_GAP,
    CAPTCHA_STREAK_TRIGGER,
    LOBBY_SECONDS,
)
from maki.cogs.legion.mixins.base import LegionCogBase
from maki.cogs.legion.model.model import (
    DungeonInstance,
    DungeonParticipant,
    Player,
)
from maki.cogs.legion.simulation import (
    build_mob_state,
    build_player_state,
    run_simulation,
)
from maki.cogs.legion.views import (
    CaptchaView,
    CombatLogView,
    GroundSelectView,
    LobbyView,
    SettlementPaginator,
)


@dataclass
class _CaptchaState:
    """Per-user anti-script state, kept in memory only (cleared on restart)."""

    last_at: datetime | None = None  # last expedition attempt
    last_interval: int = 0  # previous gap, seconds
    streak: int = 0  # regular-gap run length
    runs: int = 0  # consecutive expeditions this session (volume)
    fails: int = 0  # consecutive test failures
    locked_until: datetime | None = None  # soft-lockout expiry


class ExpeditionMixin(LegionCogBase):
    _captcha: dict[int, _CaptchaState]
    _lobby_tasks: dict[int, asyncio.Task]
    _replay_tasks: set[asyncio.Task]

    # --- /expedition ---------------------------------------------------------

    @app_commands.command(
        name=strings.EXPEDITION_COMMAND_NAME,
        description=strings.EXPEDITION_COMMAND_DESC,
    )
    @app_commands.guild_only()
    async def expedition(self, interaction: discord.Interaction) -> None:
        log.debug("/expedition by user {}", interaction.user.id)
        if self._patch_blocked(session_start=True):
            await self._send_patch_blocked(interaction)
            return
        await self._defer(interaction, ephemeral=True)
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
            await self._notify(interaction, strings.LEGION_NOT_CONFIGURED)
            return
        if await self.dungeons.active_for(legion) is not None:
            await self._notify(interaction, strings.HUNTING_EXPEDITION_BUSY_SHORT)
            return
        if not await self.ensure_captcha(interaction, player):
            return  # locked out, or a verification test was shown
        await self.show_ground_list(interaction, edit=True)

    # --- anti-script captcha -------------------------------------------------

    def _captcha_should_test(self, st: "_CaptchaState", now: datetime) -> str | None:
        """Update the heuristics and return a trigger reason, or None. Two tells:
        (1) robotic REGULARITY -- gaps matching within CAPTCHA_INTERVAL_TOLERANCE
        CAPTCHA_STREAK_TRIGGER times running; (2) VOLUME -- once consecutive
        expeditions pass CAPTCHA_RUNS_GRACE, each further run rolls a growing
        chance. A long gap resets the run counter (not a continuous grind)."""
        if st.last_at is not None:
            interval = int((now - st.last_at).total_seconds())
            if interval > CAPTCHA_RUNS_RESET_GAP:
                st.runs = 0  # a real break -- this isn't one grind session
            if (
                st.last_interval > 0
                and abs(interval - st.last_interval) <= CAPTCHA_INTERVAL_TOLERANCE
            ):
                st.streak += 1
            else:
                st.streak = 0
            st.last_interval = interval
        st.last_at = now
        st.runs += 1
        if st.streak >= CAPTCHA_STREAK_TRIGGER:
            return "regular-timing"
        if st.runs > CAPTCHA_RUNS_GRACE:
            chance = min(
                CAPTCHA_RUNS_CHANCE_CAP,
                (st.runs - CAPTCHA_RUNS_GRACE) * CAPTCHA_RUNS_CHANCE_STEP,
            )
            if random.random() < chance:
                return "high-volume"
        return None

    async def ensure_captcha(
        self, interaction: discord.Interaction, player: Player
    ) -> bool:
        """Gate the expedition. Returns True to proceed; False if the user is
        blacklisted/locked out or a test was shown (its outcome resumes)."""
        uid = interaction.user.id
        if uid in self.bot.blacklist:  # bot-wide core blacklist
            await self._edit_tracked(
                interaction,
                content=strings.CAPTCHA_BLACKLISTED,
                embed=None,
                view=None,
            )
            return False
        now = datetime.now(timezone.utc)
        st = self._captcha.setdefault(uid, _CaptchaState())
        if st.locked_until and now < st.locked_until:
            await self._edit_tracked(
                interaction,
                content=strings.CAPTCHA_LOCKED.format(
                    until=int(st.locked_until.timestamp())
                ),
                embed=None,
                view=None,
            )
            return False
        # A fail streak (post-lockout) force-tests until a pass clears it;
        # otherwise the timing/volume heuristics decide.
        if st.fails > 0:
            reason = "post-lockout"
        else:
            reason = self._captcha_should_test(st, now)
            if reason is None:
                return True
        log.info(
            "Captcha challenge: user {} ({}, streak={}, runs={}, fails={})",
            uid,
            reason,
            st.streak,
            st.runs,
            st.fails,
        )
        answer = random.randint(1, 9)
        others = random.sample(
            [n for n in range(1, 10) if n != answer], CAPTCHA_BUTTONS - 1
        )
        choices = others + [answer]
        random.shuffle(choices)
        view = CaptchaView(self, uid, player, answer, choices)
        await self._edit_tracked(
            interaction,
            content=strings.CAPTCHA_PROMPT.format(answer=answer),
            embed=None,
            view=view,
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
        secs = CAPTCHA_LOCKOUT_BASE * (2**st.fails)
        if secs >= CAPTCHA_BLACKLIST_AT_SECONDS:
            await self.bot.add_to_blacklist(uid)
            self._captcha.pop(uid, None)
            log.warning(
                "Captcha blacklist: user {} hit the lockout ceiling "
                "(added to the bot-wide blacklist)",
                uid,
            )
            await interaction.response.edit_message(
                content=strings.CAPTCHA_BLACKLISTED, embed=None, view=None
            )
            return
        st.locked_until = datetime.now(timezone.utc) + timedelta(seconds=secs)
        st.fails += 1
        log.info("Captcha fail: user {} locked {}s (fail #{})", uid, secs, st.fails)
        await interaction.response.edit_message(
            content=strings.CAPTCHA_FAILED.format(
                until=int(st.locked_until.timestamp())
            ),
            embed=None,
            view=None,
        )

    # --- ground pickers ------------------------------------------------------

    async def show_ground_list(
        self, interaction: discord.Interaction, edit: bool = False
    ) -> None:
        """Layer 1: embed listing every unlocked ground + 隨機遠征 button."""
        legion = await self._legion_for(interaction.guild)
        grounds = await self.dungeons.unlocked_grounds(legion.level)
        if not grounds:
            if edit:
                await self._edit_tracked(
                    interaction,
                    content="No hunting grounds are open to this legion yet.",
                    embed=None,
                    view=None,
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

    # --- lobby & fight -------------------------------------------------------

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
            await self._edit_tracked(
                interaction, content=strings.HUNTING_GROUND_GONE, embed=None, view=None
            )
            return
        mob = await self.dungeons.roll_mob(ground)
        if mob is None:
            await self._edit_tracked(
                interaction, content=strings.HUNTING_MOB_GONE, embed=None, view=None
            )
            return
        expires_at = datetime.now().astimezone() + timedelta(seconds=LOBBY_SECONDS)
        instance = await self.dungeons.spawn(
            legion, ground, mob, expires_at, random_ground=is_random
        )
        if instance is None:
            await self._edit_tracked(
                interaction,
                content=strings.HUNTING_EXPEDITION_BUSY_SHORT,
                embed=None,
                view=None,
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
        await self._edit_tracked(
            interaction,
            content=strings.EXPEDITION_INIT.format(channel=channel.mention),
            embed=None,
            view=None,
        )

        task = asyncio.create_task(self._run_lobby(instance.id, legion.id, message))
        self._lobby_tasks[legion.id] = task
        task.add_done_callback(lambda _: self._lobby_tasks.pop(legion.id, None))

    async def join_expedition(
        self, interaction: discord.Interaction, instance_id: int
    ) -> None:
        # Deliberately NO patch/freeze gate here: spawning new expeditions is
        # what locks -- an already-open lobby is the players' FINAL game, and
        # anyone may still pile into it before it fires.
        await self._defer(interaction)
        player = await self.ensure_player(interaction, gate_patch=False)
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
            await message.edit(embed=render.expired_embed(self.bot.color), view=None)
            return
        task = asyncio.create_task(self._run_fight(instance, participants, message))
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
