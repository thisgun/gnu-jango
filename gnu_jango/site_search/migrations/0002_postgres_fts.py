from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import migrations


def indexes():
    return [GinIndex(SearchVector(f"{field}_tokens", config="simple"), name=f"search_{field}_fts")
            for field in ("title", "body")]


def create_indexes(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        model = apps.get_model("site_search", "SearchDocument")
        for index in indexes():
            schema_editor.add_index(model, index)


def drop_indexes(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        model = apps.get_model("site_search", "SearchDocument")
        for index in reversed(indexes()):
            schema_editor.remove_index(model, index)


class Migration(migrations.Migration):
    dependencies = [("site_search", "0001_initial")]
    operations = [migrations.RunPython(create_indexes, drop_indexes)]
