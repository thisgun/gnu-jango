import uuid

from django.db import migrations, models
import django.utils.timezone


def protect_private_outbox(apps, schema_editor):
    # Supabase may grant API roles access to newly created public-schema tables.
    # Keep message contents and quarantined images private even on such projects.
    if schema_editor.connection.vendor != "postgresql":
        return
    table = schema_editor.quote_name("gnu_jango_background_job")
    schema_editor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    schema_editor.execute(f"REVOKE ALL ON TABLE {table} FROM PUBLIC")
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")
        for (role,) in cursor.fetchall():
            schema_editor.execute(f"REVOKE ALL ON TABLE {table} FROM {schema_editor.quote_name(role)}")


class Migration(migrations.Migration):
    dependencies = [("core", "0014_notification_delivery")]
    operations = [migrations.CreateModel(
        name="BackgroundJob",
        fields=[
            ("id", models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
            ("kind", models.CharField(max_length=32, db_index=True)),
            ("operation", models.CharField(max_length=80, blank=True, default="")),
            ("resource_key", models.CharField(max_length=64, blank=True, default="", db_index=True)),
            ("queue", models.CharField(max_length=32)),
            ("status", models.CharField(max_length=12, default="pending", choices=[("pending", "대기"), ("running", "실행 중"), ("succeeded", "완료"), ("dead", "최종 실패")])),
            ("payload", models.JSONField(default=dict)),
            ("dedupe_key", models.CharField(max_length=160, unique=True, null=True, blank=True)),
            ("active_key", models.CharField(max_length=160, unique=True, null=True, blank=True)),
            ("attempts", models.PositiveIntegerField(default=0)),
            ("max_attempts", models.PositiveIntegerField(default=5)),
            ("available_at", models.DateTimeField(default=django.utils.timezone.now)),
            ("dispatched_at", models.DateTimeField(null=True, blank=True)),
            ("lease_until", models.DateTimeField(null=True, blank=True)),
            ("claim_token", models.UUIDField(null=True, blank=True)),
            ("error_code", models.CharField(max_length=80, blank=True)),
            ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ("updated_at", models.DateTimeField(default=django.utils.timezone.now)),
            ("finished_at", models.DateTimeField(null=True, blank=True)),
        ],
        options={"db_table": "gnu_jango_background_job", "ordering": ["created_at"],
                 "verbose_name": "백그라운드 작업", "verbose_name_plural": "백그라운드 작업 / 실패 큐",
                 "indexes": [models.Index(fields=["status", "available_at"], name="bg_status_available"),
                             models.Index(fields=["status", "lease_until"], name="bg_status_lease")]},
    ), migrations.RunPython(protect_private_outbox, migrations.RunPython.noop)]
