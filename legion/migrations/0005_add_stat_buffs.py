from tortoise import migrations
from tortoise.migrations import operations as ops
from tortoise import fields
from tortoise.fields.data import JSON_DUMPS
from orjson import loads


class Migration(migrations.Migration):
    dependencies = [("legion", "0004_add_system_flags")]

    operations = [
        ops.AddField(
            "Player",
            "stat_buffs",
            fields.JSONField(
                null=True, default=dict, encoder=JSON_DUMPS, decoder=loads
            ),
        ),
    ]
