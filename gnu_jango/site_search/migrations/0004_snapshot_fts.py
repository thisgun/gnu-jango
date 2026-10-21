from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import migrations


def indexes():
    return [GinIndex(SearchVector(f"{field}_tokens", config="simple"), name=f"search_snap_{field}_fts")
            for field in ("title", "body")]


def create_indexes(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for index in indexes():
            schema_editor.add_index(apps.get_model("site_search", "SearchSnapshot"), index)


def drop_indexes(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for index in reversed(indexes()):
            schema_editor.remove_index(apps.get_model("site_search", "SearchSnapshot"), index)


class Migration(migrations.Migration):
    dependencies = [("site_search", "0003_index_snapshots")]
    operations = [migrations.RunPython(create_indexes, drop_indexes)]
