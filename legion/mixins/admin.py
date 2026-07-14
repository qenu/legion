"""Admin mixin: the owner-only text console ([p]admin ...) and the staged
content-patch workflow (check / compare / schedule / force-apply / freeze)."""

import asyncio
from datetime import datetime
from typing import Union

import discord
from discord.ext import commands
from loguru import logger as log

from maki.cogs.legion import render, strings
from maki.cogs.legion.content import PATCH
from maki.cogs.legion.mixins.base import FREEZE_FLAG_KEY, LegionCogBase
from maki.cogs.legion.model.model import (
    ActiveSkill,
    GamePatch,
    HuntingGround,
    LifeSkillMastery,
    Material,
    Mob,
    Player,
    PlayerWeapon,
    Recipe,
    Weapon,
    WeaponCategory,
    WeaponMastery,
    WeaponActiveSkill,
    WeaponPassiveSkill,
)
from maki.cogs.legion.constants import LifeSkillType
from maki.cogs.legion.seeds import (
    apply_patch,
    content_hash,
    content_summary,
    pending_removals,
    validate_patch,
)
from maki.cogs.legion.utils import clean_legion_name, clean_player_name, patch_timeline
from maki.cogs.legion.views import PatchDecisionView, PatchView


class AdminMixin(LegionCogBase):
    # --- [p]admin (owner-only text command group) ------------------------------

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
        material = await Material.get_or_none(key=item) or await Material.get_or_none(
            name=item
        )
        if material is not None:
            return material, None
        weapon = await Weapon.get_or_none(key=item) or await Weapon.get_or_none(
            name=item
        )
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
            await self.legions.ensure_daily_reset(legion)  # honest "kills today"
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
            # for _ in range(min(qty, 10)):
            #     await self.inventory.grant_weapon(player, weapon)
            # await ctx.send(
            #     f"✅ {player.username} +{min(qty, 10)}× {weapon.name} (flat)"
            # )
            pseudo_legion_level = qty
            skill_ids = [
                *(a.active_skill_id for a in await WeaponActiveSkill.filter(weapon=weapon)),
                *(p.passive_skill_id for p in await WeaponPassiveSkill.filter(weapon=weapon)),
            ]
            mutations = await self.inventory.roll_mutations(skill_ids, pseudo_legion_level)
            pw = await self.inventory.grant_weapon(player, weapon, mutations)
            quality = strings.WEAPON_QUALITY_DISPLAY.get(pw.quality, pw.quality.value)
            await ctx.send(
                f"✅ {player.username} +{weapon.name}({quality}) with {len(mutations)} mutations"
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
                await ctx.send(
                    f"🏰 {legion.name} · `{field}` = {getattr(legion, attr)}"
                )
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
                await ctx.send(
                    f"🧑 {player.username} · `{field}` = {getattr(player, attr)}"
                )
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
        category = await WeaponCategory.get_or_none(
            key=field
        ) or await WeaponCategory.get_or_none(name=field)
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
            await LifeSkillMastery.create(player=player, skill=life, level=level, exp=0)
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

    # --- staged content patches ------------------------------------------------

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
            current,
            live_counts,
            PATCH["version"],
            content_hash(),
            legion,
            self.bot.color,
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
            await self._notify(interaction, strings.PATCH_UP_TO_DATE)
            return
        # Validate BEFORE offering the update -- broken references die at
        # review time, never at apply time.
        problems = validate_patch()
        if problems:
            shown = "\n".join(f"- {e}" for e in problems[:15])
            if len(problems) > 15:
                shown += f"\n… and {len(problems) - 15} more"
            await self._notify(
                interaction,
                f"❌ The on-disk patch is invalid ({len(problems)} problems):\n"
                f"```\n{shown}\n```",
            )
            return
        view.check.disabled = True
        view.view_update.disabled = False
        await self._edit_tracked(
            interaction, content=strings.PATCH_UPDATE_FOUND, view=view
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
        await self._edit_tracked(
            interaction,
            content=None,
            embed=embed,
            view=PatchDecisionView(self, interaction.user.id),
        )

    async def patch_schedule(self, interaction: discord.Interaction) -> None:
        lock_at, apply_at = patch_timeline(datetime.now().astimezone())
        pending = await self.patches.schedule(
            content_hash(),
            PATCH["version"],
            PATCH.get("notes"),
            content_summary(),
            lock_at,
            apply_at,
        )
        if pending is None:
            await self._notify(interaction, "A patch is already scheduled.")
            return
        self._pending_patch = pending
        self._start_patch_timer(pending)
        await self._edit_tracked(
            interaction,
            content=strings.PATCH_SCHEDULED.format(
                lock=int(lock_at.timestamp()), apply=int(apply_at.timestamp())
            ),
            embed=None,
            view=None,
        )

    async def patch_cancel_scheduled(self, interaction: discord.Interaction) -> None:
        pending = await self.patches.pending()
        if pending is not None:
            await self.patches.cancel(pending)
        if self._patch_task is not None:
            self._patch_task.cancel()
            self._patch_task = None
        self._pending_patch = None
        await self._edit_tracked(
            interaction, content=strings.PATCH_CANCELLED, embed=None, view=None
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
            PATCH["version"],
            content_hash(),
            created,
        )
        return created

    def _start_patch_timer(self, pending: GamePatch) -> None:
        async def timer() -> None:
            delay = (pending.apply_at - datetime.now().astimezone()).total_seconds()
            if delay > 0:
                await asyncio.sleep(delay)
            await apply_patch()
            await self.patches.mark_applied(pending)
            self._pending_patch = None
            log.info("Scheduled patch {} applied.", pending.version)

        if self._patch_task is not None:
            self._patch_task.cancel()
        self._patch_task = asyncio.create_task(timer())
