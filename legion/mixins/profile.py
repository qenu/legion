"""Profile mixin: /profile, inventory (weapons/consumables), mastery pages,
weapon detail/equip/dismantle, consumable use -- including on others via the
context menu -- and the public show-off profile."""

from datetime import datetime, timedelta

import discord
from discord import app_commands
from loguru import logger as log

from maki.cogs.legion import render, strings
from maki.cogs.legion.calculator import mastery_level_cost
from maki.cogs.legion.constants import (
    ContentStatus,
    MASTERY_HARD_CAP,
    MASTERY_KIND_WEAPONS,
    MaterialKind,
    REVIVE_MINUTES,
    StatBonusType,
    USE_ITEM_MASTERY_GAP_PCT,
    WeaponSlot,
)
from maki.cogs.legion.mixins.base import LegionCogBase
from maki.cogs.legion.model.model import (
    LifeSkillMastery,
    Material,
    Player,
    PlayerMaterial,
    PlayerWeapon,
    WeaponActiveSkill,
    WeaponMastery,
    WeaponPassiveSkill,
)
from maki.cogs.legion.simulation import (
    effective_max_hp,
    effective_max_hp_and_regen,
    invalidate_player_state,
)
from maki.cogs.legion.views import (
    DismantleConfirmView,
    InventoryCategoryView,
    InventoryHomeView,
    KIND_CONSUMABLES,
    KIND_WEAPONS,
    LegionMasteryView,
    ProfileView,
    UseItemView,
    WeaponDetailView,
)


class ProfileMixin(LegionCogBase):
    # --- /profile -----------------------------------------------------------------

    @app_commands.command(
        name=strings.PROFILE_COMMAND_NAME, description=strings.PROFILE_COMMAND_DESC
    )
    async def profile(self, interaction: discord.Interaction) -> None:
        log.debug("/account by user {}", interaction.user.id)
        await self._defer(interaction, ephemeral=True)
        player = await self.ensure_player(interaction)
        if player is None:
            return
        await self.show_profile(interaction, player, edit=True)

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

    # --- inventory ------------------------------------------------------------

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
        await self._edit_tracked(
            interaction,
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
                    MaterialKind.FOOD,
                    MaterialKind.POTION,
                    MaterialKind.CONSUMABLE,
                ],
            ).prefetch_related("material")
            embed = render.inventory_consumables_embed(consumables, self.bot.color)
            placeholder = next(
                (s.material.name for s in consumables if s.material_id == used_id),
                None,
            )
            view = InventoryCategoryView(
                self,
                interaction.user.id,
                player,
                kind,
                consumables=consumables,
                placeholder=placeholder,
            )
        await self._edit_tracked(interaction, content=note, embed=embed, view=view)

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
        await self._edit_tracked(
            interaction,
            embed=render.mastery_embed(kind, masteries, self.bot.color),
            view=LegionMasteryView(self, interaction.user.id, player, kind),
        )

    # --- weapon detail / equip / dismantle -------------------------------------

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
                pw,
                actives,
                passives,
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
                interaction,
                player,
                KIND_CONSUMABLES,
                note=note,
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
            view=confirm,
            ephemeral=True,
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
                interaction,
                content=strings.INVENTORY_CANNOT_DISMANTLE,
                embed=None,
                view=None,
            )
            return
        if pw.equipped_slot is not None:
            await self._edit_tracked(
                interaction,
                content=strings.INVENTORY_CANNOT_DISMANTLE_EQUIPPED,
                embed=None,
                view=None,
            )
            return
        name = pw.weapon.name
        returned = await self.inventory.dismantle_salvage(player, pw.weapon)
        await pw.delete()
        invalidate_player_state(player)  # loadout changed
        note = strings.INVENTORY_DISMANTLED.format(weapon=name)
        if returned:
            mats = "、".join(f"{mat.name}×{qty:,}" for mat, qty in returned)
            note += " " + strings.INVENTORY_DISMANTLE_RETURNED.format(mats=mats)
        # Refresh the weapons embed WITHOUT the note, then deliver the outcome
        # as its own ephemeral message rather than as content on the embed.
        await self.show_inventory_category(interaction, player, KIND_WEAPONS)
        await interaction.followup.send(note, ephemeral=True)

    # --- consumables ------------------------------------------------------------

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
            or material.kind
            not in (MaterialKind.FOOD, MaterialKind.POTION, MaterialKind.CONSUMABLE)
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
                        target=recipient.username,
                        material=material.name,
                        value=value,
                        duration=duration,
                    )
                return material, strings.FOOD_BUFF_APPLIED.format(
                    material=material.name,
                    value=value,
                    duration=duration,
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
                    target=recipient.username,
                    material=material.name,
                    value=value,
                    category=category,
                    duration=duration,
                )
            return material, strings.FOOD_BUFF_EFFECT_APPLIED.format(
                material=material.name,
                value=value,
                category=category,
                duration=duration,
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
        log.debug("use-item menu by user {} on {}", interaction.user.id, member.id)
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
            view=view,
            ephemeral=True,
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
                if legion.channel_id
                else None
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
                MaterialKind.FOOD,
                MaterialKind.POTION,
                MaterialKind.CONSUMABLE,
            ],
        ).prefetch_related("material")

    # --- show-off profile (context menu) --------------------------------------

    async def showoff_profile_context(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        """Allow others to summon a visible profile of a player, but only if
        they have one (onboarded)."""
        log.debug("show-profile menu by user {} on {}", interaction.user.id, member.id)
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
        embed.set_author(
            name=strings.SHOWOFF_PROFILE_TITLE.format(name=target.username),
            icon_url=member.display_avatar.url,
        )
        masteries = (
            await WeaponMastery.filter(player=target)
            .order_by("-level", "-exp")
            .limit(2)
            .prefetch_related("category")
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

        embed.set_footer(
            text=strings.SHOWOFF_PROFILE_FOOTER.format(
                author=interaction.user.display_name
            )
        )
        await interaction.followup.send(embed=embed)  # public by design
