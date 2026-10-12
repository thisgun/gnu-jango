from django.db import migrations, models
from django.db.models import Count


def deduplicate_config_names(apps, schema_editor):
    Config = apps.get_model("config", "Config")
    duplicates = (
        Config.objects.values("name")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    for item in duplicates:
        rows = list(Config.objects.filter(name=item["name"]).order_by("-id"))
        keep = rows[0]
        Config.objects.filter(name=item["name"]).exclude(pk=keep.pk).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("config", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(deduplicate_config_names, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="config",
            name="name",
            field=models.CharField(db_index=True, max_length=50, unique=True),
        ),
        migrations.AlterField(
            model_name="config",
            name="value",
            field=models.TextField(),
        ),
    ]
