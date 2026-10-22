from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0012_searchkeyworddaily")]
    operations = [
        migrations.AddIndex(
            model_name="notification",
            index=models.Index(fields=["user", "nt_read_at", "-nt_sent_at", "-nt_id"], name="notification_unread_idx"),
        ),
    ]
