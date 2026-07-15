"""Craft mixin: /craft -- the forge (weapons, quality rolls) and the life-skill
workstations (cook/brew, instant material crafts with the double-outcome
mastery perk)."""

import asyncio
import random

import discord
from discord import app_commands
from loguru import logger as log

from maki.cogs.legion import render, strings
from maki.cogs.legion.calculator import craft_double_chance, roll_mutations
from maki.cogs.legion.constants import (
    CRAFT_MASTERY_PTS,
    ContentStatus,
    MUTATION_MAX,
    MUTATION_MIN,
)
from maki.cogs.legion.mixins.base import LegionCogBase
from maki.cogs.legion.model.model import (
    LifeSkillMastery,
    Player,
    PlayerMaterial,
    PlayerWeapon,
    Recipe,
    RecipeMaterial,
    WeaponActiveSkill,
    WeaponMastery,
    WeaponPassiveSkill,
)
from maki.cogs.legion.views import (
    CraftConfirmView,
    CraftHomeView,
    CraftResultView,
    CraftSurfaceView,
    RecipeDetailView,
)


class CraftMixin(LegionCogBase):
    @app_commands.command(
        name=strings.CRAFTING_COMMAND_NAME, description=strings.CRAFTING_COMMAND_DESC
    )
    @app_commands.guild_only()
    async def craft_command(self, interaction: discord.Interaction) -> None:
        log.debug("/make by user {}", interaction.user.id)
        await self._defer(interaction, ephemeral=True)
        player = await self.ensure_player(interaction)
        if player is None or not await self.ensure_not_afk(interaction, player):
            return
        await self.show_craft_home(interaction, player, edit=True)

    async def _craft_groups(self, player: Player) -> tuple[dict[str, list], dict]:
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
                unlocked = levels.get(recipe.skill, 0) >= recipe.mastery_level_required
                groups[recipe.skill.value].append((recipe, unlocked))
        return groups, levels

    async def show_craft_home(
        self, interaction: discord.Interaction, player: Player, edit: bool = True
    ) -> None:
        groups, levels = await self._craft_groups(player)
        embed = render.craft_home_embed(groups, levels, self.bot.color)
        view = CraftHomeView(self, interaction.user.id, player)
        if edit:
            await self._edit_tracked(interaction, content=None, embed=embed, view=view)
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
            await PlayerMaterial.filter(player=player, quantity__gt=0).values_list(
                "material_id", flat=True
            )
        )
        entries = []
        craftable = []
        for recipe, unlocked in groups.get(surface, []):
            inputs = await RecipeMaterial.filter(recipe=recipe).prefetch_related(
                "material"
            )
            text = ", ".join(
                strings.CRAFT_MAT_DETAIL.format(name=i.material.name, count=i.quantity)
                for i in inputs
            )
            entries.append((recipe, unlocked, text))
            has_material = any(i.material_id in owned for i in inputs)
            if unlocked and (surface != "forge" or has_material):
                craftable.append(recipe)
        embeds = render.craft_surface_embed(surface, entries, self.bot.color)
        await self._edit_tracked(
            interaction,
            content=note,
            embed=embeds[0],
            view=CraftSurfaceView(
                self,
                interaction.user.id,
                player,
                surface,
                craftable,
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
        mastery = await LifeSkillMastery.get_or_none(player=player, skill=recipe.skill)
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
            await self._notify(interaction, strings.CRAFT_NO_SUCH_RECIPE)
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
            embed = render.recipe_detail_embed(
                recipe,
                inputs,
                self.bot.color,
                weapon=recipe.result_weapon,
                actives=actives,
                passives=passives,
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
            await self._notify(interaction, strings.CRAFT_NO_SUCH_RECIPE)
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
                    for a in await WeaponActiveSkill.filter(weapon=recipe.result_weapon)
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
            item = (
                recipe.result_material.name if recipe.result_material else recipe.name
            )
            dots = 3

        # The show: crafting… with the quality-tell dot count.
        await self._edit_tracked(
            interaction,
            content=strings.CRAFT_CRAFTING.format(item=item) + ".",
            view=None,
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
            # Fresh from the anvil: 裝備 or 拆解 right here, no inventory trip.
            result_view = CraftResultView(self, interaction.user.id, player, pw.id)
            await message.edit(
                content=None,
                embed=render.weapon_detail_embed(
                    pw,
                    actives,
                    passives,
                    mastery.level if mastery else 0,
                    self.bot.color,
                ),
                view=result_view,
            )
            result_view.message = message
        else:
            if recipe.result_material is not None:
                qty = recipe.result_qty
                template = strings.CRAFT_MADE
                if recipe.skill is not None:
                    # Craft mastery perk: each cook/brew level adds a chance
                    # for the batch to come out DOUBLED.
                    mastery = await LifeSkillMastery.get_or_none(
                        player=player, skill=recipe.skill
                    )
                    level = mastery.level if mastery else 0
                    if random.random() < craft_double_chance(level):
                        qty *= 2
                        template = strings.CRAFT_MADE_DOUBLE
                await self.inventory.add_material(
                    player, recipe.result_material, qty
                )
                if recipe.skill is not None:
                    await self.masteries.grant_life(
                        player, recipe.skill, CRAFT_MASTERY_PTS
                    )
                await message.edit(
                    content=template.format(
                        qty=qty, material=recipe.result_material.name
                    )
                )
            else:
                await message.edit(content=strings.CRAFT_NOTHING)
