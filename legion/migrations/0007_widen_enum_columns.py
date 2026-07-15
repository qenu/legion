from tortoise import migrations
from tortoise.migrations import operations as ops
from tortoise import fields

from maki.cogs.legion.constants import EffectType, StatBonusType


class Migration(migrations.Migration):
    """Widen the enum-backed varchar columns.

    CharEnumField auto-sizes to the longest enum value at CREATE time, so the
    original columns froze at varchar(5)/(6) -- and the new values outgrew
    them ('poison_res' = 10 chars broke inserts; 'shield' fit varchar(6)
    exactly, with zero room left). Pinned to 16 across the board so the next
    enum addition doesn't need another ALTER. Postgres widens varchar as a
    metadata-only change -- instant, no table rewrite.
    """

    dependencies = [("legion", "0006_add_ground_encounters")]

    operations = [
        ops.AlterField(
            "ActiveSkill",
            "effect_type",
            fields.CharEnumField(enum_type=EffectType, max_length=16),
        ),
        ops.AlterField(
            "PassiveSkill",
            "stat_bonus_type",
            fields.CharEnumField(enum_type=StatBonusType, max_length=16),
        ),
        ops.AlterField(
            "Material",
            "stat_bonus_type",
            fields.CharEnumField(enum_type=StatBonusType, null=True, max_length=16),
        ),
    ]
