from django.db import migrations


def replace_indexes(apps, schema_editor, *, stored):
    if schema_editor.connection.vendor != "postgresql":
        return
    quote = schema_editor.quote_name
    for model_name, prefix in (("SearchDocument", "search"), ("SearchSnapshot", "search_snap")):
        table = quote(apps.get_model("site_search", model_name)._meta.db_table)
        for field in ("title", "body"):
            index = quote(f"{prefix}_{field}_fts")
            column = quote(f"{field}_vector") if stored else f"to_tsvector('simple'::regconfig, COALESCE({quote(field + '_tokens')}, ''))"
            schema_editor.execute(f"DROP INDEX IF EXISTS {index}")
            schema_editor.execute(f"CREATE INDEX {index} ON {table} USING gin ({column})")


def forwards(apps, schema_editor):
    replace_indexes(apps, schema_editor, stored=True)


def backwards(apps, schema_editor):
    replace_indexes(apps, schema_editor, stored=False)


class Migration(migrations.Migration):
    dependencies = [("site_search", "0006_stored_vectors")]
    operations = [migrations.RunPython(forwards, backwards)]
