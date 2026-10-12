from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0008_shopbanner"),
    ]

    operations = [
        migrations.AddField(
            model_name="shopproduct",
            name="it_option_subject",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="shopproduct",
            name="it_supply_subject",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
