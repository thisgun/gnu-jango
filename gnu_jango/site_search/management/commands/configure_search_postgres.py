from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from gnu_jango.site_search.models import SearchDocument


class Command(BaseCommand):
    help = "Optionally install pg_trgm and the unified-search fuzzy-title GIN index."

    def add_arguments(self, parser):
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        connection = connections[options["database"]]
        if connection.vendor != "postgresql":
            raise CommandError("pg_trgm is PostgreSQL-only; SQLite already uses the token inverted index.")
        table = connection.ops.quote_name(SearchDocument._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            cursor.execute(f"CREATE INDEX IF NOT EXISTS search_title_trgm ON {table} USING gin (lower(title) gin_trgm_ops)")
        self.stdout.write(self.style.SUCCESS("pg_trgm ready. Set G5_SEARCH_TRIGRAM=True to enable fuzzy title fallback."))
