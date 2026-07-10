from tortoise import fields
from tortoise.models import Model

from maki.cogs.legion.constants import (
    ContentStatus,
    DungeonStatus,
    EffectType,
    LifeSkillType,
    MaterialKind,
    PatchStatus,
    RequirementType,
    StatBonusType,
    WeaponQuality,
    WeaponSlot,
)

class Player(Model):
    """A player in the game, identified by their Discord ID."""

    id = fields.IntField(pk=True)
    # Discord IDs are externally supplied (snowflakes), never auto-generated.
    discord_id = fields.BigIntField(unique=True, generated=False)
    created_at = fields.DatetimeField(auto_now_add=True)

    username = fields.CharField(max_length=32)

    health_points = fields.IntField(default=100)
    max_health_points = fields.IntField(default=100)
    hp_updated_at = fields.DatetimeField(null=True)  # lazy-regen bookmark

    # Food buff: +rate HP/min until the timestamp (lazy, computed on read;
    # db_default so the AddField migration backfills the populated table).
    regen_buff_rate  = fields.IntField(default=0, db_default=0)
    regen_buff_until = fields.DatetimeField(null=True)

    legion = fields.ForeignKeyField(
        "legion.Legion", null=True, on_delete=fields.SET_NULL
    )
    left_legion_at = fields.DatetimeField(null=True)

    # Last time the player ran any command (throttled write via ensure_player).
    # Legion upgrade costs scale by members active within ACTIVE_WINDOW_DAYS;
    # null = legacy row not yet stamped (grandfathered as active until it acts).
    last_active_at = fields.DatetimeField(null=True)

    # Per-legion status; reset to 0 when switching legions. Earned by donating
    # (qty * rarity) and the first dungeon fight of each UTC day.
    contribution  = fields.IntField(default=0)
    last_daily_at = fields.DatetimeField(null=True)  # last daily-contri award

    # Appointed by Manage Guild members; may press legion Upgrade/settings
    # without holding Discord perms themselves.
    is_legion_manager = fields.BooleanField(default=False)

    # Equipped weapons live on PlayerWeapon.equipped_slot (a Player->PlayerWeapon
    # FK would be a cyclic reference Tortoise's schema generator rejects).

    class Meta: # type: ignore
        table = "players"

    def __str__(self) -> str:
        return f"Player({self.discord_id}, {self.username})"
    

class WeaponMastery(Model):
    """Represents a player weapon-category mastery."""

    player = fields.ForeignKeyField("legion.Player", related_name="weapon_masteries")
    category = fields.ForeignKeyField("legion.WeaponCategory", related_name="weapon_masteries")
    level = fields.IntField(default=0)
    exp = fields.IntField(default=0)

    class Meta: # type: ignore
        table = "weapon_masteries"
        unique_together = ("player", "category")

    def __str__(self) -> str:
        return f"WeaponMastery(Player: {self.player.discord_id}, Category: {self.category.name}, Level: {self.level})"
    

class WeaponCategory(Model):
    """Represents a category of weapons."""

    # Stable content identity: patching & references key off this; `name`
    # is display-only and freely patchable/localizable.
    key    = fields.CharField(max_length=64, unique=True, null=True)
    status = fields.CharEnumField(ContentStatus, default=ContentStatus.ENABLED)
    name = fields.CharField(max_length=32)
    description = fields.TextField(null=True)

    class Meta: # type: ignore
        table = "weapon_categories"

    def __str__(self) -> str:
        return f"WeaponCategory({self.name})"
    

class Weapon(Model):
    """Represents a weapon in the game."""

    # Stable content identity: patching & references key off this; `name`
    # is display-only and freely patchable/localizable.
    key    = fields.CharField(max_length=64, unique=True, null=True)
    status = fields.CharEnumField(ContentStatus, default=ContentStatus.ENABLED)
    name = fields.CharField(max_length=32)
    category = fields.ForeignKeyField("legion.WeaponCategory", related_name="weapons")
    description = fields.TextField(null=True)

    # Which hand this weapon equips into (True = MAIN, False = SUB). Category
    # is orthogonal: a dagger can be sword-category with main_weapon=False,
    # sharing sword mastery. db_default so the AddField migration backfills
    # the populated weapons table.
    main_weapon = fields.BooleanField(default=True, db_default=True)

    # Starter weapons are named in constants.STARTER_WEAPONS, not flagged here.

    class Meta: # type: ignore
        table = "weapons"

    def __str__(self) -> str:
        return f"Weapon({self.name}, Category: {self.category.name})"
    

class ActiveSkill(Model):
    """Represents an active skill that a player can use."""

    # Stable content identity: patching & references key off this; `name`
    # is display-only and freely patchable/localizable.
    key    = fields.CharField(max_length=64, unique=True, null=True)
    status = fields.CharEnumField(ContentStatus, default=ContentStatus.ENABLED)
    name = fields.CharField(max_length=32)
    description = fields.TextField(null=True)

    effect_type = fields.CharEnumField(EffectType)
    # Formula string: "20", "{atk} + 12", "{atk}*10% + 20" -- resolved at
    # use time against the actor's stats (calculator.eval_formula).
    effect_value = fields.CharField(max_length=64, default="0")

    cooldown = fields.IntField(default=0)  # Cooldown in the wielder's own turns (0 = every turn)

    class Meta: # type: ignore
        table = "active_skills"

    def __str__(self) -> str:
        return f"ActiveSkill({self.name}, Effect: {self.effect_type} {self.effect_value}, Cooldown: {self.cooldown})"
    

class PassiveSkill(Model):
    """Represents a passive skill that a player can have."""

    # Stable content identity: patching & references key off this; `name`
    # is display-only and freely patchable/localizable.
    key    = fields.CharField(max_length=64, unique=True, null=True)
    status = fields.CharEnumField(ContentStatus, default=ContentStatus.ENABLED)
    name = fields.CharField(max_length=32)
    description = fields.TextField(null=True)

    stat_bonus_type = fields.CharEnumField(StatBonusType)
    # Formula string, evaluated against BASE stats (before passives apply).
    stat_bonus_value = fields.CharField(max_length=64, default="0")

    class Meta: # type: ignore
        table = "passive_skills"

    def __str__(self) -> str:
        return f"PassiveSkill({self.name})"
    

class WeaponActiveSkill(Model):
    """Represents the relationship between a weapon and an active skill."""

    weapon = fields.ForeignKeyField("legion.Weapon", related_name="active_skills")
    active_skill = fields.ForeignKeyField("legion.ActiveSkill", related_name="weapons")

    tier = fields.IntField(default=1)  # Tier of unlock for this weapon
    mastery_level_required = fields.IntField(default=0)  # Mastery level required to unlock this skill

    class Meta: # type: ignore
        table = "weapon_active_skills"
        unique_together = ("weapon", "active_skill")

    def __str__(self) -> str:
        return f"WeaponActiveSkill(Weapon: {self.weapon.name}, ActiveSkill: {self.active_skill.name}, Tier: {self.tier}, Mastery Level Required: {self.mastery_level_required})"
    

class WeaponPassiveSkill(Model):
    """Represents the relationship between a weapon and a passive skill."""

    weapon = fields.ForeignKeyField("legion.Weapon", related_name="passive_skills")
    passive_skill = fields.ForeignKeyField("legion.PassiveSkill", related_name="weapons")

    tier = fields.IntField(default=1)  # Tier of unlock for this weapon
    mastery_level_required = fields.IntField(default=0)  # Mastery level required to unlock this skill

    class Meta: # type: ignore
        table = "weapon_passive_skills"
        unique_together = ("weapon", "passive_skill")

    def __str__(self) -> str:
        return f"WeaponPassiveSkill(Weapon: {self.weapon.name}, PassiveSkill: {self.passive_skill.name}, Tier: {self.tier}, Mastery Level Required: {self.mastery_level_required})"
    

class Legion(Model):
    """Represents a legion (Discord server/world) in the game."""

    id            = fields.IntField(pk=True)
    guild_id      = fields.BigIntField(unique=True, generated=False)
    name          = fields.CharField(max_length=64)

    # Exp BANKS here from settlements; leveling is manual (Upgrade button:
    # banked exp >= cost AND stockpile covers the upgrade sheet).
    level         = fields.IntField(default=1)
    exp           = fields.IntField(default=0)

    daily_kills   = fields.IntField(default=0)
    last_reset_at = fields.DatetimeField(auto_now_add=True)

    # Designated bot channel, set by Manage Guild members (announcements,
    # dungeon feeds, upgrade reminders). Nothing posts until configured.
    channel_id    = fields.BigIntField(null=True)

    created_at    = fields.DatetimeField(auto_now_add=True)

    class Meta:  # type: ignore
        table = "legions"

    def __str__(self) -> str:
        return f"Legion({self.name}, Level: {self.level})"
    

class Mob(Model):
    """Represents a mob (enemy) in the game."""

    id = fields.IntField(pk=True)
    # Stable content identity: patching & references key off this; `name`
    # is display-only and freely patchable/localizable.
    key    = fields.CharField(max_length=64, unique=True, null=True)
    status = fields.CharEnumField(ContentStatus, default=ContentStatus.ENABLED)
    name = fields.CharField(max_length=64)
    description = fields.TextField(null=True)

    tier = fields.IntField(default=1)  # difficulty weight; scales legion exp on clear

    # The doom clock: the party must kill the mob within this many of the
    # MOB'S OWN turns; its Nth action ends the fight (FAILED if it survives).
    rounds_limit = fields.IntField(default=10)

    base_hp = fields.IntField(default=100)
    base_atk = fields.IntField(default=10)
    base_def = fields.IntField(default=5)
    base_speed = fields.IntField(default=1)

    class Meta:  # type: ignore
        table = "mobs"

    def __str__(self) -> str:
        return f"Mob({self.name})"


class MobSkill(Model):
    """Represents the relationship between a mob and an active skill."""

    mob          = fields.ForeignKeyField("legion.Mob", related_name="skills")
    skill        = fields.ForeignKeyField("legion.ActiveSkill", related_name="mob_entries")
    hp_threshold = fields.FloatField(default=1.0)  # Usable when HP ratio <= threshold
    cooldown     = fields.IntField(default=0)      # In the mob's own turns (0 = every turn)

    class Meta:  # type: ignore
        table = "mob_skills"
        unique_together = ("mob", "skill")

    def __str__(self) -> str:
        return f"MobSkill(Mob: {self.mob.name}, Skill: {self.skill.name})"


class MobPassive(Model):
    """Represents the relationship between a mob and a passive skill."""

    mob               = fields.ForeignKeyField("legion.Mob", related_name="passives")
    skill             = fields.ForeignKeyField("legion.PassiveSkill", related_name="mob_entries")
    requirement_type  = fields.CharEnumField(RequirementType, null=True)  # null = always active
    requirement_value = fields.FloatField(null=True)

    class Meta:  # type: ignore
        table = "mob_passives"
        unique_together = ("mob", "skill")

    def __str__(self) -> str:
        return f"MobPassive(Mob: {self.mob.name}, Skill: {self.skill.name}, Requirement: {self.requirement_type})"


class HuntingGround(Model):
    """An expedition destination. Difficulty comes from the ground danger
    rating (never from legion level -- legion level only UNLOCKS grounds)."""

    # Stable content identity: patching & references key off this; `name`
    # is display-only and freely patchable/localizable.
    key    = fields.CharField(max_length=64, unique=True, null=True)
    status = fields.CharEnumField(ContentStatus, default=ContentStatus.ENABLED)
    name             = fields.CharField(max_length=64)
    description      = fields.TextField(null=True)

    danger           = fields.IntField(default=1)  # scales mob stats
    min_legion_level = fields.IntField(default=1)

    class Meta:  # type: ignore
        table = "hunting_grounds"

    def __str__(self) -> str:
        return f"HuntingGround({self.name}, Danger: {self.danger}, MinLegion: {self.min_legion_level})"


class GroundMob(Model):
    """A hunting ground encounter pool entry (weighted roll at spawn)."""

    ground = fields.ForeignKeyField("legion.HuntingGround", related_name="mobs")
    mob    = fields.ForeignKeyField("legion.Mob", related_name="grounds")
    weight = fields.IntField(default=1)

    class Meta:  # type: ignore
        table = "ground_mobs"
        unique_together = ("ground", "mob")

    def __str__(self) -> str:
        return f"GroundMob(Ground: {self.ground.name}, Mob: {self.mob.name}, Weight: {self.weight})"


class DungeonInstance(Model):
    """A single expedition run spawned by a legion member.

    Combat state (mob HP, ticks, cooldowns) is memory-only; this row records
    existence and outcome. At most one ACTIVE instance per legion, enforced
    by the repository (Tortoise cannot express partial unique indexes).
    """

    id         = fields.IntField(pk=True)
    legion     = fields.ForeignKeyField("legion.Legion", related_name="dungeon_instances")
    ground     = fields.ForeignKeyField("legion.HuntingGround", related_name="expeditions")
    mob        = fields.ForeignKeyField("legion.Mob", related_name="dungeon_instances")

    # Player pressed Random instead of picking the ground: explorer's bonus
    # at settlement (+1 mastery to all, richer drop rolls) on a win.
    random_ground = fields.BooleanField(default=False)

    status     = fields.CharEnumField(DungeonStatus, default=DungeonStatus.ACTIVE)

    created_at = fields.DatetimeField(auto_now_add=True)
    expires_at = fields.DatetimeField()  # lobby deadline: auto-fight fires here
    ended_at   = fields.DatetimeField(null=True)  # set when status leaves ACTIVE

    class Meta:  # type: ignore
        table = "dungeon_instances"

    def __str__(self) -> str:
        return f"DungeonInstance(Legion: {self.legion.name}, Ground: {self.ground.name}, Mob: {self.mob.name}, Status: {self.status})"


class DungeonParticipant(Model):
    """A dungeon-run participation record - per-run stats are written
    once at settlement (run end), never per tick."""

    instance     = fields.ForeignKeyField("legion.DungeonInstance", related_name="participants")
    player       = fields.ForeignKeyField("legion.Player", related_name="dungeon_entries")

    joined_at    = fields.DatetimeField(auto_now_add=True)
    damage_dealt = fields.IntField(default=0)
    damage_taken = fields.IntField(default=0)
    died         = fields.BooleanField(default=False)

    class Meta:  # type: ignore
        table = "dungeon_participants"
        unique_together = ("instance", "player")

    def __str__(self) -> str:
        return f"DungeonParticipant(Instance: {self.instance.id}, Player: {self.player.discord_id})"


class PlayerWeapon(Model):
    """A weapon instance owned by a player -- crafted (quality rolled) or a
    starter granted at onboarding. Equipping references these, never the
    catalog Weapon directly."""

    player     = fields.ForeignKeyField("legion.Player", related_name="weapons")
    weapon     = fields.ForeignKeyField("legion.Weapon", related_name="instances")
    crafted_at = fields.DatetimeField(auto_now_add=True)

    # Craft mutation: {skill_id: effectiveness_pct} for every active/passive
    # on the weapon at craft time. Starters are flat (empty = all 100%).
    # `quality` is the cached tier derived from the mutation average.
    mutations  = fields.JSONField(default=dict)
    quality    = fields.CharEnumField(WeaponQuality, default=WeaponQuality.STANDARD)

    # null = in bag; unique per (player, slot) -- NULLs are distinct, so any
    # number of unequipped weapons coexist.
    equipped_slot = fields.CharEnumField(WeaponSlot, null=True)

    class Meta:  # type: ignore
        table = "player_weapons"
        unique_together = ("player", "equipped_slot")

    def __str__(self) -> str:
        return f"PlayerWeapon(Player: {self.player.discord_id}, Weapon: {self.weapon.name}, Quality: {self.quality})"


class Material(Model):
    """A material in the game: crafting input, consumable, or chest.

    Potions: stat_bonus_value = instant heal (revives the dead). Food:
    stat_bonus_value = regen HP/min, duration = buff length in MINUTES.
    """

    # Stable content identity: patching & references key off this; `name`
    # is display-only and freely patchable/localizable.
    key    = fields.CharField(max_length=64, unique=True, null=True)
    status = fields.CharEnumField(ContentStatus, default=ContentStatus.ENABLED)
    name        = fields.CharField(max_length=64)
    description = fields.TextField(null=True)

    kind   = fields.CharEnumField(MaterialKind, default=MaterialKind.MATERIAL)
    rarity = fields.IntField(default=1)

    stat_bonus_type  = fields.CharEnumField(StatBonusType, null=True)
    stat_bonus_value = fields.IntField(null=True)
    duration         = fields.IntField(null=True)  # seconds; null = instant

    class Meta:  # type: ignore
        table = "materials"

    def __str__(self) -> str:
        return f"Material({self.name}, Kind: {self.kind})"


class PlayerMaterial(Model):
    """A player material stack."""

    player   = fields.ForeignKeyField("legion.Player", related_name="materials")
    material = fields.ForeignKeyField("legion.Material", related_name="holders")
    quantity = fields.IntField(default=0)

    class Meta:  # type: ignore
        table = "player_materials"
        unique_together = ("player", "material")

    def __str__(self) -> str:
        return f"PlayerMaterial(Player: {self.player.discord_id}, Material: {self.material.name}, Qty: {self.quantity})"


class MobDrop(Model):
    """A mob loot table entry. Rolled per player at settlement - outsiders
    (player.legion != instance.legion) receive no materials."""

    mob      = fields.ForeignKeyField("legion.Mob", related_name="drops")
    material = fields.ForeignKeyField("legion.Material", related_name="dropped_by")

    weight  = fields.IntField(default=1)
    min_qty = fields.IntField(default=1)
    max_qty = fields.IntField(default=1)

    class Meta:  # type: ignore
        table = "mob_drops"
        unique_together = ("mob", "material")

    def __str__(self) -> str:
        return f"MobDrop(Mob: {self.mob.name}, Material: {self.material.name}, Weight: {self.weight})"


class Recipe(Model):
    """A crafting recipe for any surface: weapon forge (skill=null, quality
    roll applies, legion level nudges the roll) or a life skill (cook/brew
    produce material stacks)."""

    # Stable content identity: patching & references key off this; `name`
    # is display-only and freely patchable/localizable.
    key    = fields.CharField(max_length=64, unique=True, null=True)
    status = fields.CharEnumField(ContentStatus, default=ContentStatus.ENABLED)
    name = fields.CharField(max_length=64)

    skill                  = fields.CharEnumField(LifeSkillType, null=True)  # null = weapon forge
    mastery_level_required = fields.IntField(default=0)

    result_weapon   = fields.ForeignKeyField(
        "legion.Weapon", null=True, on_delete=fields.SET_NULL, related_name="recipes"
    )
    result_material = fields.ForeignKeyField(
        "legion.Material", null=True, on_delete=fields.SET_NULL, related_name="recipes"
    )
    result_qty      = fields.IntField(default=1)

    class Meta:  # type: ignore
        table = "recipes"

    def __str__(self) -> str:
        return f"Recipe({self.name}, Skill: {self.skill})"


class RecipeMaterial(Model):
    """A material input required by a recipe."""

    recipe   = fields.ForeignKeyField("legion.Recipe", related_name="inputs")
    material = fields.ForeignKeyField("legion.Material", related_name="used_in")
    quantity = fields.IntField(default=1)

    class Meta:  # type: ignore
        table = "recipe_materials"
        unique_together = ("recipe", "material")

    def __str__(self) -> str:
        return f"RecipeMaterial(Recipe: {self.recipe.name}, Material: {self.material.name}, Qty: {self.quantity})"


class LifeSkillMastery(Model):
    """A weaponless life-skill mastery (cook/brew/mine)."""

    player = fields.ForeignKeyField("legion.Player", related_name="life_skills")
    skill  = fields.CharEnumField(LifeSkillType)
    level  = fields.IntField(default=0)
    exp    = fields.IntField(default=0)

    class Meta:  # type: ignore
        table = "life_skill_masteries"
        unique_together = ("player", "skill")

    def __str__(self) -> str:
        return f"LifeSkillMastery(Player: {self.player.discord_id}, Skill: {self.skill}, Level: {self.level})"


class GatherSite(Model):
    """An AFK gathering area (mine/garden), unlocked by legion level."""

    # Stable content identity: patching & references key off this; `name`
    # is display-only and freely patchable/localizable.
    key    = fields.CharField(max_length=64, unique=True, null=True)
    status = fields.CharEnumField(ContentStatus, default=ContentStatus.ENABLED)
    name             = fields.CharField(max_length=64)
    description      = fields.TextField(null=True)

    skill            = fields.CharEnumField(LifeSkillType)  # MINE or GARDEN
    min_legion_level = fields.IntField(default=1)

    class Meta:  # type: ignore
        table = "gather_sites"

    def __str__(self) -> str:
        return f"GatherSite({self.name}, Skill: {self.skill}, MinLegion: {self.min_legion_level})"


class SiteYield(Model):
    """A gather site yield table entry, rolled per 30-min chunk at stop."""

    site     = fields.ForeignKeyField("legion.GatherSite", related_name="yields")
    material = fields.ForeignKeyField("legion.Material", related_name="gathered_from")

    weight  = fields.IntField(default=1)
    min_qty = fields.IntField(default=1)
    max_qty = fields.IntField(default=1)

    class Meta:  # type: ignore
        table = "site_yields"
        unique_together = ("site", "material")

    def __str__(self) -> str:
        return f"SiteYield(Site: {self.site.name}, Material: {self.material.name}, Weight: {self.weight})"


class PlayerActivity(Model):
    """An open-ended AFK gathering session. DB-persisted so a bot restart
    never loses one. Ends when the player presses Stop; payout is computed
    from elapsed time then, capped by the gather-mastery bag. All other game
    actions are blocked while a session is running."""

    player     = fields.ForeignKeyField("legion.Player", related_name="activities")
    site       = fields.ForeignKeyField("legion.GatherSite", related_name="sessions")
    skill      = fields.CharEnumField(LifeSkillType)  # denormalized from site

    started_at = fields.DatetimeField(auto_now_add=True)
    collected  = fields.BooleanField(default=False)

    class Meta:  # type: ignore
        table = "player_activities"

    def __str__(self) -> str:
        return f"PlayerActivity(Player: {self.player.discord_id}, Site: {self.site.name}, Collected: {self.collected})"


class LegionStockpile(Model):
    """A legion stack of a donated material (feeds upgrades)."""

    legion   = fields.ForeignKeyField("legion.Legion", related_name="stockpile")
    material = fields.ForeignKeyField("legion.Material", related_name="stockpiled_by")
    quantity = fields.IntField(default=0)

    class Meta:  # type: ignore
        table = "legion_stockpiles"
        unique_together = ("legion", "material")

    def __str__(self) -> str:
        return f"LegionStockpile(Legion: {self.legion.name}, Material: {self.material.name}, Qty: {self.quantity})"


class GamePatch(Model):
    """A content patch lifecycle: what is applied, and what is scheduled.

    The latest APPLIED row is the live patch (its hash is compared against
    content.py's hash to detect updates). A PENDING row drives the graceful
    rollout timeline; it survives restarts, so timers resume on boot.
    """

    id           = fields.IntField(pk=True)
    hash         = fields.CharField(max_length=16)
    version      = fields.CharField(max_length=32)
    notes        = fields.TextField(null=True)
    summary      = fields.JSONField(default=dict)  # section counts

    status       = fields.CharEnumField(PatchStatus, default=PatchStatus.PENDING)
    lock_at      = fields.DatetimeField(null=True)  # sessions block
    apply_at     = fields.DatetimeField(null=True)  # patch lands
    applied_at   = fields.DatetimeField(null=True)
    created_at   = fields.DatetimeField(auto_now_add=True)

    class Meta:  # type: ignore
        table = "game_patches"

    def __str__(self) -> str:
        return f"GamePatch({self.version}, {self.hash}, {self.status})"


class LegionUpgradeCost(Model):
    """The upgrade requirement sheet: materials needed to reach ``level``.
    Actual quantity scales with member count (see constants)."""

    level    = fields.IntField()
    material = fields.ForeignKeyField("legion.Material", related_name="upgrade_costs")
    base_qty = fields.IntField(default=1)

    class Meta:  # type: ignore
        table = "legion_upgrade_costs"
        unique_together = ("level", "material")

    def __str__(self) -> str:
        return f"LegionUpgradeCost(Level: {self.level}, Material: {self.material.name}, BaseQty: {self.base_qty})"