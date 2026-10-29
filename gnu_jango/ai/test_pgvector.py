"""PostgreSQL storage path (CI runs the suite on the pgvector/pgvector image)."""
import pytest
from django.db import connection

from gnu_jango.ai.models import Embedding
from gnu_jango.ai.store import nearest, normalize, postgresql_queryset
from gnu_jango.ai.testing import FakeEmbeddingProvider

pytestmark = pytest.mark.skipif(connection.vendor != "postgresql", reason="pgvector runs on PostgreSQL only")


def save(provider, object_id, text, *, kind="product"):
    return Embedding.objects.create(kind=kind, object_id=object_id, model=provider.model, dimensions=provider.dimensions,
                                    text_hash="h", embedding=normalize(provider.vector(text)))


def test_migration_installs_the_extension_column_and_hnsw_index(db):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        assert cursor.fetchone() == (1,)
        cursor.execute(
            "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
            "WHERE attrelid = 'ai_embedding'::regclass AND attname = 'embedding'"
        )
        assert cursor.fetchone() == ("vector",)
        cursor.execute("SELECT indexdef FROM pg_indexes WHERE indexname = 'ai_embedding_hnsw_1024'")
        definition = cursor.fetchone()[0]
    assert "hnsw" in definition and "vector_cosine_ops" in definition and "1024" in definition


def test_pgvector_nearest_neighbours_and_round_trip(db):
    provider = FakeEmbeddingProvider(synonyms={"랩탑": "노트북"})
    save(provider, "laptop", "가벼운 노트북")
    save(provider, "mouse", "무선 마우스")
    save(provider, "docs-1", "노트북", kind="docs")
    stored = Embedding.objects.get(object_id="laptop").embedding
    assert len(stored) == 1024 and stored == pytest.approx(normalize(provider.vector("가벼운 노트북")), abs=1e-6)

    found = nearest("product", provider.vector("랩탑"), model=provider.model, dimensions=1024, limit=2)
    assert [object_id for object_id, _ in found] == ["laptop", "mouse"]
    assert found[0][1] == pytest.approx(0.7071, abs=1e-3)
    assert nearest("product", provider.vector("랩탑"), model="other", dimensions=1024, limit=2) == []


def test_vector_query_can_use_the_hnsw_index(db):
    provider = FakeEmbeddingProvider()
    save(provider, "a", "노트북")
    queryset = postgresql_queryset("product", normalize(provider.vector("노트북")), model=provider.model,
                                   dimensions=1024, limit=5)
    sql, params = queryset.query.sql_with_params()
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off")
        cursor.execute(f"EXPLAIN {sql}", params)
        plan = " ".join(row[0] for row in cursor.fetchall())
    assert "ai_embedding_hnsw_1024" in plan
