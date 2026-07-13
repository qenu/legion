from tortoise import migrations
from tortoise.migrations import operations as ops
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
from orjson import loads
from tortoise.fields.base import OnDelete
from tortoise.fields.data import JSON_DUMPS
from tortoise import fields


class Migration(migrations.Migration):
    initial = True

    operations = [
        ops.CreateModel(
            name="ActiveSkill",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("key", fields.CharField(null=True, unique=True, max_length=64)),
                (
                    "status",
                    fields.CharEnumField(
                        default=ContentStatus.ENABLED,
                        description="ENABLED: enabled\nDISABLED: disabled\nREMOVED: removed",
                        enum_type=ContentStatus,
                        max_length=8,
                    ),
                ),
                ("name", fields.CharField(max_length=32)),
                ("description", fields.TextField(null=True, unique=False)),
                (
                    "effect_type",
                    fields.CharEnumField(
                        description="DAMAGE: damage\nHEAL: heal\nSTUN: stun\nBLEED: bleed",
                        enum_type=EffectType,
                        max_length=6,
                    ),
                ),
                ("effect_value", fields.CharField(default="0", max_length=64)),
                ("cooldown", fields.IntField(default=0)),
            ],
            options={
                "table": "active_skills",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "Represents an active skill that a player can use.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="GamePatch",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("hash", fields.CharField(max_length=16)),
                ("version", fields.CharField(max_length=32)),
                ("notes", fields.TextField(null=True, unique=False)),
                (
                    "summary",
                    fields.JSONField(default=dict, encoder=JSON_DUMPS, decoder=loads),
                ),
                (
                    "status",
                    fields.CharEnumField(
                        default=PatchStatus.PENDING,
                        description="PENDING: pending\nAPPLIED: applied\nCANCELLED: cancelled",
                        enum_type=PatchStatus,
                        max_length=9,
                    ),
                ),
                (
                    "lock_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                (
                    "apply_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                (
                    "applied_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
            ],
            options={
                "table": "game_patches",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "A content patch lifecycle: what is applied, and what is scheduled.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="GatherSite",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("key", fields.CharField(null=True, unique=True, max_length=64)),
                (
                    "status",
                    fields.CharEnumField(
                        default=ContentStatus.ENABLED,
                        description="ENABLED: enabled\nDISABLED: disabled\nREMOVED: removed",
                        enum_type=ContentStatus,
                        max_length=8,
                    ),
                ),
                ("name", fields.CharField(max_length=64)),
                ("description", fields.TextField(null=True, unique=False)),
                (
                    "skill",
                    fields.CharEnumField(
                        description="MINE: mine\nGARDEN: garden\nCOOK: cook\nBREW: brew",
                        enum_type=LifeSkillType,
                        max_length=6,
                    ),
                ),
                ("min_legion_level", fields.IntField(default=1)),
            ],
            options={
                "table": "gather_sites",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "An AFK gathering area (mine/garden), unlocked by legion level.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="HuntingGround",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("key", fields.CharField(null=True, unique=True, max_length=64)),
                (
                    "status",
                    fields.CharEnumField(
                        default=ContentStatus.ENABLED,
                        description="ENABLED: enabled\nDISABLED: disabled\nREMOVED: removed",
                        enum_type=ContentStatus,
                        max_length=8,
                    ),
                ),
                ("name", fields.CharField(max_length=64)),
                ("description", fields.TextField(null=True, unique=False)),
                ("danger", fields.IntField(default=1)),
                ("min_legion_level", fields.IntField(default=1)),
            ],
            options={
                "table": "hunting_grounds",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "An expedition destination. Difficulty comes from the ground danger",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="Legion",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("guild_id", fields.BigIntField(unique=True)),
                ("name", fields.CharField(max_length=64)),
                ("level", fields.IntField(default=1)),
                ("exp", fields.IntField(default=0)),
                ("daily_kills", fields.IntField(default=0)),
                (
                    "last_reset_at",
                    fields.DatetimeField(auto_now=False, auto_now_add=True),
                ),
                ("channel_id", fields.BigIntField(null=True)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
            ],
            options={
                "table": "legions",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "Represents a legion (Discord server/world) in the game.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="Material",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("key", fields.CharField(null=True, unique=True, max_length=64)),
                (
                    "status",
                    fields.CharEnumField(
                        default=ContentStatus.ENABLED,
                        description="ENABLED: enabled\nDISABLED: disabled\nREMOVED: removed",
                        enum_type=ContentStatus,
                        max_length=8,
                    ),
                ),
                ("name", fields.CharField(max_length=64)),
                ("description", fields.TextField(null=True, unique=False)),
                (
                    "kind",
                    fields.CharEnumField(
                        default=MaterialKind.MATERIAL,
                        description="MATERIAL: material\nFOOD: food\nPOTION: potion\nCONSUMABLE: consumable\nCHEST: chest",
                        enum_type=MaterialKind,
                        max_length=10,
                    ),
                ),
                ("rarity", fields.IntField(default=1)),
                (
                    "stat_bonus_type",
                    fields.CharEnumField(
                        null=True,
                        description="ATK: atk\nSPEED: speed\nDEF: def\nHP: hp",
                        enum_type=StatBonusType,
                        max_length=5,
                    ),
                ),
                ("stat_bonus_value", fields.IntField(null=True)),
                ("duration", fields.IntField(null=True)),
            ],
            options={
                "table": "materials",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "A material in the game: crafting input, consumable, or chest.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="LegionStockpile",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "legion",
                    fields.ForeignKeyField(
                        "legion.Legion",
                        source_field="legion_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="stockpile",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "material",
                    fields.ForeignKeyField(
                        "legion.Material",
                        source_field="material_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="stockpiled_by",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("quantity", fields.IntField(default=0)),
            ],
            options={
                "table": "legion_stockpiles",
                "app": "legion",
                "unique_together": (("legion", "material"),),
                "pk_attr": "id",
                "table_description": "A legion stack of a donated material (feeds upgrades).",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="LegionUpgradeCost",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("level", fields.IntField()),
                (
                    "material",
                    fields.ForeignKeyField(
                        "legion.Material",
                        source_field="material_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="upgrade_costs",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("base_qty", fields.IntField(default=1)),
            ],
            options={
                "table": "legion_upgrade_costs",
                "app": "legion",
                "unique_together": (("level", "material"),),
                "pk_attr": "id",
                "table_description": "The upgrade requirement sheet: materials needed to reach ``level``.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="Mob",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("key", fields.CharField(null=True, unique=True, max_length=64)),
                (
                    "status",
                    fields.CharEnumField(
                        default=ContentStatus.ENABLED,
                        description="ENABLED: enabled\nDISABLED: disabled\nREMOVED: removed",
                        enum_type=ContentStatus,
                        max_length=8,
                    ),
                ),
                ("name", fields.CharField(max_length=64)),
                ("description", fields.TextField(null=True, unique=False)),
                ("tier", fields.IntField(default=1)),
                ("rounds_limit", fields.IntField(default=10)),
                ("base_hp", fields.IntField(default=100)),
                ("base_atk", fields.IntField(default=10)),
                ("base_def", fields.IntField(default=5)),
                ("base_speed", fields.IntField(default=1)),
            ],
            options={
                "table": "mobs",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "Represents a mob (enemy) in the game.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="DungeonInstance",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "legion",
                    fields.ForeignKeyField(
                        "legion.Legion",
                        source_field="legion_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="dungeon_instances",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "ground",
                    fields.ForeignKeyField(
                        "legion.HuntingGround",
                        source_field="ground_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="expeditions",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "mob",
                    fields.ForeignKeyField(
                        "legion.Mob",
                        source_field="mob_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="dungeon_instances",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("random_ground", fields.BooleanField(default=False)),
                (
                    "status",
                    fields.CharEnumField(
                        default=DungeonStatus.ACTIVE,
                        description="ACTIVE: active\nCLEARED: cleared\nFAILED: failed\nEXPIRED: expired\nVOIDED: voided",
                        enum_type=DungeonStatus,
                        max_length=7,
                    ),
                ),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                (
                    "expires_at",
                    fields.DatetimeField(auto_now=False, auto_now_add=False),
                ),
                (
                    "ended_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
            ],
            options={
                "table": "dungeon_instances",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "A single expedition run spawned by a legion member.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="GroundMob",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "ground",
                    fields.ForeignKeyField(
                        "legion.HuntingGround",
                        source_field="ground_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="mobs",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "mob",
                    fields.ForeignKeyField(
                        "legion.Mob",
                        source_field="mob_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="grounds",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("weight", fields.IntField(default=1)),
            ],
            options={
                "table": "ground_mobs",
                "app": "legion",
                "unique_together": (("ground", "mob"),),
                "pk_attr": "id",
                "table_description": "A hunting ground encounter pool entry (weighted roll at spawn).",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="MobDrop",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "mob",
                    fields.ForeignKeyField(
                        "legion.Mob",
                        source_field="mob_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="drops",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "material",
                    fields.ForeignKeyField(
                        "legion.Material",
                        source_field="material_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="dropped_by",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("weight", fields.IntField(default=1)),
                ("min_qty", fields.IntField(default=1)),
                ("max_qty", fields.IntField(default=1)),
            ],
            options={
                "table": "mob_drops",
                "app": "legion",
                "unique_together": (("mob", "material"),),
                "pk_attr": "id",
                "table_description": "A mob loot table entry. Rolled per player at settlement - outsiders",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="MobSkill",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "mob",
                    fields.ForeignKeyField(
                        "legion.Mob",
                        source_field="mob_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="skills",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "skill",
                    fields.ForeignKeyField(
                        "legion.ActiveSkill",
                        source_field="skill_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="mob_entries",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("hp_threshold", fields.FloatField(default=1.0)),
                ("cooldown", fields.IntField(default=0)),
            ],
            options={
                "table": "mob_skills",
                "app": "legion",
                "unique_together": (("mob", "skill"),),
                "pk_attr": "id",
                "table_description": "Represents the relationship between a mob and an active skill.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="PassiveSkill",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("key", fields.CharField(null=True, unique=True, max_length=64)),
                (
                    "status",
                    fields.CharEnumField(
                        default=ContentStatus.ENABLED,
                        description="ENABLED: enabled\nDISABLED: disabled\nREMOVED: removed",
                        enum_type=ContentStatus,
                        max_length=8,
                    ),
                ),
                ("name", fields.CharField(max_length=32)),
                ("description", fields.TextField(null=True, unique=False)),
                (
                    "stat_bonus_type",
                    fields.CharEnumField(
                        description="ATK: atk\nSPEED: speed\nDEF: def\nHP: hp",
                        enum_type=StatBonusType,
                        max_length=5,
                    ),
                ),
                ("stat_bonus_value", fields.CharField(default="0", max_length=64)),
            ],
            options={
                "table": "passive_skills",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "Represents a passive skill that a player can have.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="MobPassive",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "mob",
                    fields.ForeignKeyField(
                        "legion.Mob",
                        source_field="mob_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="passives",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "skill",
                    fields.ForeignKeyField(
                        "legion.PassiveSkill",
                        source_field="skill_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="mob_entries",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "requirement_type",
                    fields.CharEnumField(
                        null=True,
                        description="HP_BELOW: hp_below\nPLAYER_DEAD: player_dead\nROUND: round",
                        enum_type=RequirementType,
                        max_length=11,
                    ),
                ),
                ("requirement_value", fields.FloatField(null=True)),
            ],
            options={
                "table": "mob_passives",
                "app": "legion",
                "unique_together": (("mob", "skill"),),
                "pk_attr": "id",
                "table_description": "Represents the relationship between a mob and a passive skill.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="Player",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("discord_id", fields.BigIntField(unique=True)),
                ("created_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ("username", fields.CharField(max_length=32)),
                ("health_points", fields.IntField(default=100)),
                ("max_health_points", fields.IntField(default=100)),
                (
                    "hp_updated_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                ("regen_buff_rate", fields.IntField(default=0, db_default=0)),
                (
                    "regen_buff_until",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                (
                    "legion",
                    fields.ForeignKeyField(
                        "legion.Legion",
                        source_field="legion_id",
                        null=True,
                        db_constraint=True,
                        to_field="id",
                        on_delete=OnDelete.SET_NULL,
                    ),
                ),
                (
                    "left_legion_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                ("contribution", fields.IntField(default=0)),
                (
                    "last_daily_at",
                    fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
                ),
                ("is_legion_manager", fields.BooleanField(default=False)),
            ],
            options={
                "table": "players",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "A player in the game, identified by their Discord ID.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="DungeonParticipant",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "instance",
                    fields.ForeignKeyField(
                        "legion.DungeonInstance",
                        source_field="instance_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="participants",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "player",
                    fields.ForeignKeyField(
                        "legion.Player",
                        source_field="player_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="dungeon_entries",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("joined_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ("damage_dealt", fields.IntField(default=0)),
                ("damage_taken", fields.IntField(default=0)),
                ("died", fields.BooleanField(default=False)),
            ],
            options={
                "table": "dungeon_participants",
                "app": "legion",
                "unique_together": (("instance", "player"),),
                "pk_attr": "id",
                "table_description": "A dungeon-run participation record - per-run stats are written",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="LifeSkillMastery",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "player",
                    fields.ForeignKeyField(
                        "legion.Player",
                        source_field="player_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="life_skills",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "skill",
                    fields.CharEnumField(
                        description="MINE: mine\nGARDEN: garden\nCOOK: cook\nBREW: brew",
                        enum_type=LifeSkillType,
                        max_length=6,
                    ),
                ),
                ("level", fields.IntField(default=0)),
                ("exp", fields.IntField(default=0)),
            ],
            options={
                "table": "life_skill_masteries",
                "app": "legion",
                "unique_together": (("player", "skill"),),
                "pk_attr": "id",
                "table_description": "A weaponless life-skill mastery (cook/brew/mine).",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="PlayerActivity",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "player",
                    fields.ForeignKeyField(
                        "legion.Player",
                        source_field="player_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="activities",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "site",
                    fields.ForeignKeyField(
                        "legion.GatherSite",
                        source_field="site_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="sessions",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "skill",
                    fields.CharEnumField(
                        description="MINE: mine\nGARDEN: garden\nCOOK: cook\nBREW: brew",
                        enum_type=LifeSkillType,
                        max_length=6,
                    ),
                ),
                ("started_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                ("collected", fields.BooleanField(default=False)),
            ],
            options={
                "table": "player_activities",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "An open-ended AFK gathering session. DB-persisted so a bot restart",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="PlayerMaterial",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "player",
                    fields.ForeignKeyField(
                        "legion.Player",
                        source_field="player_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="materials",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "material",
                    fields.ForeignKeyField(
                        "legion.Material",
                        source_field="material_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="holders",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("quantity", fields.IntField(default=0)),
            ],
            options={
                "table": "player_materials",
                "app": "legion",
                "unique_together": (("player", "material"),),
                "pk_attr": "id",
                "table_description": "A player material stack.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="SiteYield",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "site",
                    fields.ForeignKeyField(
                        "legion.GatherSite",
                        source_field="site_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="yields",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "material",
                    fields.ForeignKeyField(
                        "legion.Material",
                        source_field="material_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="gathered_from",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("weight", fields.IntField(default=1)),
                ("min_qty", fields.IntField(default=1)),
                ("max_qty", fields.IntField(default=1)),
            ],
            options={
                "table": "site_yields",
                "app": "legion",
                "unique_together": (("site", "material"),),
                "pk_attr": "id",
                "table_description": "A gather site yield table entry, rolled per 30-min chunk at stop.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="WeaponCategory",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("key", fields.CharField(null=True, unique=True, max_length=64)),
                (
                    "status",
                    fields.CharEnumField(
                        default=ContentStatus.ENABLED,
                        description="ENABLED: enabled\nDISABLED: disabled\nREMOVED: removed",
                        enum_type=ContentStatus,
                        max_length=8,
                    ),
                ),
                ("name", fields.CharField(max_length=32)),
                ("description", fields.TextField(null=True, unique=False)),
            ],
            options={
                "table": "weapon_categories",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "Represents a category of weapons.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="Weapon",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("key", fields.CharField(null=True, unique=True, max_length=64)),
                (
                    "status",
                    fields.CharEnumField(
                        default=ContentStatus.ENABLED,
                        description="ENABLED: enabled\nDISABLED: disabled\nREMOVED: removed",
                        enum_type=ContentStatus,
                        max_length=8,
                    ),
                ),
                ("name", fields.CharField(max_length=32)),
                (
                    "category",
                    fields.ForeignKeyField(
                        "legion.WeaponCategory",
                        source_field="category_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="weapons",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("description", fields.TextField(null=True, unique=False)),
                ("main_weapon", fields.BooleanField(default=True, db_default=True)),
            ],
            options={
                "table": "weapons",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "Represents a weapon in the game.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="PlayerWeapon",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "player",
                    fields.ForeignKeyField(
                        "legion.Player",
                        source_field="player_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="weapons",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "weapon",
                    fields.ForeignKeyField(
                        "legion.Weapon",
                        source_field="weapon_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="instances",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("crafted_at", fields.DatetimeField(auto_now=False, auto_now_add=True)),
                (
                    "mutations",
                    fields.JSONField(default=dict, encoder=JSON_DUMPS, decoder=loads),
                ),
                (
                    "quality",
                    fields.CharEnumField(
                        default=WeaponQuality.STANDARD,
                        description="CRUDE: crude\nSTANDARD: standard\nFINE: fine\nMASTERWORK: masterwork",
                        enum_type=WeaponQuality,
                        max_length=10,
                    ),
                ),
                (
                    "equipped_slot",
                    fields.CharEnumField(
                        null=True,
                        description="MAIN: main\nSUB: sub",
                        enum_type=WeaponSlot,
                        max_length=4,
                    ),
                ),
            ],
            options={
                "table": "player_weapons",
                "app": "legion",
                "unique_together": (("player", "equipped_slot"),),
                "pk_attr": "id",
                "table_description": "A weapon instance owned by a player -- crafted (quality rolled) or a",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="Recipe",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                ("key", fields.CharField(null=True, unique=True, max_length=64)),
                (
                    "status",
                    fields.CharEnumField(
                        default=ContentStatus.ENABLED,
                        description="ENABLED: enabled\nDISABLED: disabled\nREMOVED: removed",
                        enum_type=ContentStatus,
                        max_length=8,
                    ),
                ),
                ("name", fields.CharField(max_length=64)),
                (
                    "skill",
                    fields.CharEnumField(
                        null=True,
                        description="MINE: mine\nGARDEN: garden\nCOOK: cook\nBREW: brew",
                        enum_type=LifeSkillType,
                        max_length=6,
                    ),
                ),
                ("mastery_level_required", fields.IntField(default=0)),
                (
                    "result_weapon",
                    fields.ForeignKeyField(
                        "legion.Weapon",
                        source_field="result_weapon_id",
                        null=True,
                        db_constraint=True,
                        to_field="id",
                        related_name="recipes",
                        on_delete=OnDelete.SET_NULL,
                    ),
                ),
                (
                    "result_material",
                    fields.ForeignKeyField(
                        "legion.Material",
                        source_field="result_material_id",
                        null=True,
                        db_constraint=True,
                        to_field="id",
                        related_name="recipes",
                        on_delete=OnDelete.SET_NULL,
                    ),
                ),
                ("result_qty", fields.IntField(default=1)),
            ],
            options={
                "table": "recipes",
                "app": "legion",
                "pk_attr": "id",
                "table_description": "A crafting recipe for any surface: weapon forge (skill=null, quality",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="RecipeMaterial",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "recipe",
                    fields.ForeignKeyField(
                        "legion.Recipe",
                        source_field="recipe_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="inputs",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "material",
                    fields.ForeignKeyField(
                        "legion.Material",
                        source_field="material_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="used_in",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("quantity", fields.IntField(default=1)),
            ],
            options={
                "table": "recipe_materials",
                "app": "legion",
                "unique_together": (("recipe", "material"),),
                "pk_attr": "id",
                "table_description": "A material input required by a recipe.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="WeaponActiveSkill",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "weapon",
                    fields.ForeignKeyField(
                        "legion.Weapon",
                        source_field="weapon_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="active_skills",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "active_skill",
                    fields.ForeignKeyField(
                        "legion.ActiveSkill",
                        source_field="active_skill_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="weapons",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("tier", fields.IntField(default=1)),
                ("mastery_level_required", fields.IntField(default=0)),
            ],
            options={
                "table": "weapon_active_skills",
                "app": "legion",
                "unique_together": (("weapon", "active_skill"),),
                "pk_attr": "id",
                "table_description": "Represents the relationship between a weapon and an active skill.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="WeaponMastery",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "player",
                    fields.ForeignKeyField(
                        "legion.Player",
                        source_field="player_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="weapon_masteries",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "category",
                    fields.ForeignKeyField(
                        "legion.WeaponCategory",
                        source_field="category_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="weapon_masteries",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("level", fields.IntField(default=0)),
                ("exp", fields.IntField(default=0)),
            ],
            options={
                "table": "weapon_masteries",
                "app": "legion",
                "unique_together": (("player", "category"),),
                "pk_attr": "id",
                "table_description": "Represents a player weapon-category mastery.",
            },
            bases=["Model"],
        ),
        ops.CreateModel(
            name="WeaponPassiveSkill",
            fields=[
                (
                    "id",
                    fields.IntField(
                        generated=True, primary_key=True, unique=True, db_index=True
                    ),
                ),
                (
                    "weapon",
                    fields.ForeignKeyField(
                        "legion.Weapon",
                        source_field="weapon_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="passive_skills",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "passive_skill",
                    fields.ForeignKeyField(
                        "legion.PassiveSkill",
                        source_field="passive_skill_id",
                        db_constraint=True,
                        to_field="id",
                        related_name="weapons",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                ("tier", fields.IntField(default=1)),
                ("mastery_level_required", fields.IntField(default=0)),
            ],
            options={
                "table": "weapon_passive_skills",
                "app": "legion",
                "unique_together": (("weapon", "passive_skill"),),
                "pk_attr": "id",
                "table_description": "Represents the relationship between a weapon and a passive skill.",
            },
            bases=["Model"],
        ),
    ]
