"""One embedding column for every backend.

PostgreSQL with the pgvector extension stores a ``vector`` (no fixed size, so one table can hold
another model's vectors; the migration adds an HNSW cosine index on ``embedding::vector(1024)``).
Everywhere else, including a PostgreSQL server without pgvector, the column holds the same numbers
as little-endian float32 bytes and :mod:`gnu_jango.ai.store` computes cosine similarity in Python,
so the migration never blocks a deployment that has no use for AI search. Python code always sees
a ``list[float]``.
"""
import sys
from array import array

from django.db import models
from pgvector import Vector
from pgvector.django import VectorField

TABLE = "ai_embedding"
# The default model (bge-m3) has 1024 dimensions. Another size still works (exact scan);
# docs/04-deploy/ai-semantic-search.md shows the matching CREATE INDEX for it.
HNSW_DIMENSIONS = 1024
HNSW_INDEX = "ai_embedding_hnsw_1024"
_VECTOR_COLUMNS = {}


def pack(vector):
    values = array("f", vector)
    if sys.byteorder == "big":
        values.byteswap()
    return values.tobytes()


def unpack(data):
    values = array("f")
    values.frombytes(bytes(data))
    if sys.byteorder == "big":
        values.byteswap()
    return values


def pgvector_installed(connection):
    if connection.vendor != "postgresql":
        return False
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        return cursor.fetchone() is not None


def vector_column(connection, table=TABLE):
    """Whether ``table.embedding`` is a pgvector column on this connection (cached per database)."""
    if connection.vendor != "postgresql":
        return False
    key = (connection.alias, connection.settings_dict.get("NAME"), table)
    if key not in _VECTOR_COLUMNS:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = to_regclass(%s) AND attname = 'embedding' AND NOT attisdropped",
                [table],
            )
            row = cursor.fetchone()
        if row is None:
            return False  # Not migrated yet; do not remember that.
        _VECTOR_COLUMNS[key] = row[0].startswith("vector")
    return _VECTOR_COLUMNS[key]


def hnsw_index_sql(quote_name, table=TABLE):
    return (
        f"CREATE INDEX IF NOT EXISTS {quote_name(HNSW_INDEX)} ON {quote_name(table)} "
        f"USING hnsw ((embedding::vector({HNSW_DIMENSIONS})) vector_cosine_ops) "
        f"WHERE dimensions = {HNSW_DIMENSIONS}"
    )


def forget_column_types():
    _VECTOR_COLUMNS.clear()


class EmbeddingVectorField(VectorField):
    description = "Embedding vector (pgvector when available, float32 bytes otherwise)"

    def db_type(self, connection):
        if pgvector_installed(connection):
            return super().db_type(connection)
        return models.BinaryField().db_type(connection)

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def to_python(self, value):
        if value is None or isinstance(value, list):
            return value
        if isinstance(value, (bytes, bytearray, memoryview)):
            return unpack(value).tolist()
        return Vector._from_db(value)

    def get_prep_value(self, value):
        return None if value is None else [float(item) for item in value]

    def get_db_prep_value(self, value, connection, prepared=False):
        if not prepared:
            value = self.get_prep_value(value)
        if value is None:
            return None
        if vector_column(connection, self.model._meta.db_table):
            return Vector._to_db(value)
        return connection.Database.Binary(pack(value))

    def value_to_string(self, obj):
        value = self.value_from_object(obj)
        return "" if value is None else Vector._to_db(self.get_prep_value(value))
