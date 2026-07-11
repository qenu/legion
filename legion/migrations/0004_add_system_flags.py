from tortoise import migrations
from tortoise.migrations import operations as ops
from tortoise import fields


class Migration(migrations.Migration):
    dependencies = [('legion', '0003_add_last_supply_at')]

    operations = [
        ops.CreateModel(
            name='SystemFlag',
            fields=[
                ('id', fields.IntField(generated=True, primary_key=True, unique=True, db_index=True)),
                ('key', fields.CharField(unique=True, max_length=64)),
                ('enabled', fields.BooleanField(default=False)),
            ],
            options={'table': 'system_flags', 'app': 'legion', 'pk_attr': 'id'},
            bases=['Model'],
        ),
    ]
