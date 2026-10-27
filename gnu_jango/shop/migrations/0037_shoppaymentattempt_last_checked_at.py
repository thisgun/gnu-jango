from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0036_shoppaymentattempt"),
    ]

    operations = [
        migrations.AddField(
            model_name="shoppaymentattempt",
            name="last_checked_at",
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
    ]
