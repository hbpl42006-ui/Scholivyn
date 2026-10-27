from django.db import migrations, router


def create_missing_user_m2m_tables(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    connection = schema_editor.connection
    existing_tables = set(connection.introspection.table_names())

    for field_name in ("groups", "user_permissions"):
        through_model = User._meta.get_field(field_name).remote_field.through
        table_name = through_model._meta.db_table
        if (
            table_name not in existing_tables
            and router.allow_migrate_model(connection.alias, through_model)
        ):
            schema_editor.create_model(through_model)
            existing_tables.add(table_name)


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_user_auth_metadata")]

    # The model state already contains both M2M fields from 0001. This repairs
    # only their physical tables and intentionally makes no state changes.
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    create_missing_user_m2m_tables,
                    reverse_code=migrations.RunPython.noop,
                ),
            ],
            state_operations=[],
        ),
    ]
