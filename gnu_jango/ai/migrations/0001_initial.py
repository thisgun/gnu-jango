import logging

from django.db import DatabaseError, migrations, models, transaction

import gnu_jango.ai.fields
from gnu_jango.ai.fields import HNSW_INDEX, hnsw_index_sql, vector_column

logger = logging.getLogger(__name__)


def create_vector_extension(apps, schema_editor):
    """PostgreSQL only: install pgvector when the server offers it.

    A server without pgvector (or a role that may not create extensions) still migrates: the
    column then holds float32 bytes and similarity is computed in Python. ``configure_ai_postgres``
    switches it to pgvector later. On Supabase enable "vector" under Database > Extensions first;
    this IF NOT EXISTS is then a no-op. SQLite/MySQL need nothing.
    """
    connection = schema_editor.connection
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
        if cursor.fetchone() is None:
            logger.warning("pgvector is not available on this PostgreSQL server; AI embeddings use a bytea column.")
            return
    try:
        with transaction.atomic(using=connection.alias):
            schema_editor.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except DatabaseError as exc:
        logger.warning("Could not create the pgvector extension (%s); AI embeddings use a bytea column.",
                       type(exc).__name__)


def create_hnsw_index(apps, schema_editor):
    table = apps.get_model("ai", "Embedding")._meta.db_table
    if not vector_column(schema_editor.connection, table):
        return
    schema_editor.execute(hnsw_index_sql(schema_editor.quote_name, table))


def drop_hnsw_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    schema_editor.execute(f"DROP INDEX IF EXISTS {schema_editor.quote_name(HNSW_INDEX)}")


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        # Reversing leaves the extension installed: other schemas on a shared database may use it.
        migrations.RunPython(create_vector_extension, migrations.RunPython.noop, elidable=False),
        migrations.CreateModel(
            name="Embedding",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("docs", "Handbook chapter"), ("product", "Shop product")], max_length=16)),
                ("object_id", models.CharField(max_length=64)),
                ("board_id", models.BigIntegerField(blank=True, null=True)),
                ("model", models.CharField(max_length=128)),
                ("dimensions", models.PositiveIntegerField()),
                ("text_hash", models.CharField(max_length=64)),
                ("embedding", gnu_jango.ai.fields.EmbeddingVectorField()),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "AI embedding",
                "verbose_name_plural": "AI embeddings",
                "indexes": [models.Index(fields=["kind", "model", "dimensions"], name="ai_embedding_lookup")],
                "constraints": [models.UniqueConstraint(fields=("kind", "object_id"), name="ai_embedding_one_per_object")],
            },
        ),
        migrations.RunPython(create_hnsw_index, drop_hnsw_index),
    ]
