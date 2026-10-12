from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bbs", "0042_alter_gnu_auto_save_options_alter_post_scrap_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="comment",
            name="wr_comment",
            field=models.BigIntegerField(
                blank=True,
                default=None,
                null=True,
                verbose_name="Gnuboard comment group order",
            ),
        ),
    ]
