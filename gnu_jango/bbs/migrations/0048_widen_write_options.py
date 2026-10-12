from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bbs", "0047_enable_board_search"),
    ]

    operations = [
        migrations.AlterField(
            model_name="post",
            name="wr_option",
            field=models.CharField(default="both", max_length=100, verbose_name="글쓰기옵션"),
        ),
        migrations.AlterField(
            model_name="comment",
            name="wr_option",
            field=models.CharField(default="both", max_length=100, verbose_name="글쓰기옵션"),
        ),
    ]
