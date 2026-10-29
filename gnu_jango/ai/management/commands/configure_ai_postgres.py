from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from gnu_jango.ai.fields import forget_column_types, hnsw_index_sql, vector_column
from gnu_jango.ai.models import Embedding


class Command(BaseCommand):
    help = (
        "Install pgvector and switch the AI embedding column to it (with the HNSW cosine index). "
        "Needed only when the database was migrated before pgvector was available."
    )

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        connection = connections[options["database"]]
        if connection.vendor != "postgresql":
            raise CommandError("pgvector is PostgreSQL-only; this database already uses the portable byte column.")
        table = Embedding._meta.db_table
        quote = connection.ops.quote_name
        forget_column_types()
        with transaction.atomic(using=connection.alias), connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            dropped = 0
            if not vector_column(connection, table):
                # Byte rows cannot be cast; they are rebuilt by build_embeddings afterwards.
                dropped = Embedding.objects.using(connection.alias).count()
                cursor.execute(f"DELETE FROM {quote(table)}")
                cursor.execute(f"ALTER TABLE {quote(table)} ALTER COLUMN embedding TYPE vector USING NULL")
            cursor.execute(hnsw_index_sql(quote, table))
        forget_column_types()
        message = "pgvector ready. Restart web and worker processes (they cache the column type)."
        if dropped:
            message += f" Removed {dropped} byte-stored embeddings; run build_embeddings to rebuild them."
        self.stdout.write(self.style.SUCCESS(message))
