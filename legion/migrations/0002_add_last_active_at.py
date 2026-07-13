from tortoise import migrations
from tortoise.migrations import operations as ops
from tortoise import fields


class Migration(migrations.Migration):
    dependencies = [("legion", "0001_initial")]

    operations = [
        ops.AddField(
            "Player",
            "last_active_at",
            fields.DatetimeField(null=True, auto_now=False, auto_now_add=False),
        ),
    ]
