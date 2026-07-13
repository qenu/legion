from tortoise import migrations
from tortoise.migrations import operations as ops
from tortoise import fields


class Migration(migrations.Migration):
    dependencies = [("legion", "0002_add_last_active_at")]

    operations = [
        ops.AddField(
            "Player",
            "last_supply_at",
            fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
        ),
    ]
