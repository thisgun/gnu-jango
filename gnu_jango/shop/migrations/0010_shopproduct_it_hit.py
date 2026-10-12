from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0009_shopproduct_option_subjects"),
    ]

    operations = [
        migrations.AddField(
            model_name="shopproduct",
            name="it_hit",
            field=models.PositiveIntegerField(default=0),
        ),
    ]
