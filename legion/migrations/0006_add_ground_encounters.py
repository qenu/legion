from tortoise import migrations
from tortoise.migrations import operations as ops
from tortoise import fields
from tortoise.fields.base import OnDelete
from tortoise.fields.data import JSON_DUMPS
from orjson import loads


class Migration(migrations.Migration):
    dependencies = [("legion", "0005_add_stat_buffs")]

    operations = [
        # Encounter packs: one weighted pool entry -> 1..4 mobs at once.
        # Supersedes GroundMob (table kept, no longer written).
        ops.CreateModel(
            name="GroundEncounter",
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
                        related_name="encounters",
                        on_delete=OnDelete.CASCADE,
                    ),
                ),
                (
                    "mob_ids",
                    fields.JSONField(default=list, encoder=JSON_DUMPS, decoder=loads),
                ),
                ("weight", fields.FloatField(default=1)),
            ],
            options={
                "table": "ground_encounters",
                "app": "legion",
                "pk_attr": "id",
                "table_description": (
                    "A hunting ground encounter pool entry: one weighted "
                    "roll spawns the whole pack."
                ),
            },
            bases=["Model"],
        ),
        # The instance's full pack (ordered, duplicates allowed); null =
        # legacy single-mob row, which falls back to the `mob` FK.
        ops.AddField(
            "DungeonInstance",
            "mob_ids",
            fields.JSONField(null=True, encoder=JSON_DUMPS, decoder=loads),
        ),
    ]
