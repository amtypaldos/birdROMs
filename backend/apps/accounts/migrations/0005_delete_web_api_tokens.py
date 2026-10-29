from django.db import migrations


def delete_api_tokens(apps, schema_editor):
    """Web sign-in moved to cookie sessions: drop the old never-expiring DRF tokens, so a leaked one is dead.

    `rest_framework.authtoken` is no longer installed, so its table is cleared with SQL (it is absent on
    installs that never had it).
    """
    connection = schema_editor.connection
    if "authtoken_token" in connection.introspection.table_names():
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM authtoken_token")


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_invite")]

    operations = [migrations.RunPython(delete_api_tokens, migrations.RunPython.noop)]
