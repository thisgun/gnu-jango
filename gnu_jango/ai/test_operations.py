"""Operator surfaces: the read-only admin, the health report and the scheduled job entry."""
import importlib
import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.test import Client, override_settings
from django.urls import reverse

from gnu_jango.ai.conftest import SEMANTIC_ON
from gnu_jango.ai.fields import EmbeddingVectorField, pack, unpack
from gnu_jango.ai.models import Embedding
from gnu_jango.core import scheduled_jobs
from gnu_jango.testing.factories import MemberFactory


def test_admin_lists_embeddings_with_a_status_line(fake_provider, catalogue):
    call_command("build_embeddings", "--kind", "products", stdout=StringIO())
    client = Client()
    client.force_login(MemberFactory(is_staff=True, is_superuser=True))
    url = reverse("admin:ai_embedding_changelist")
    response = client.get(url)
    assert response.status_code == 200
    body = response.content.decode()
    assert "NB-1" in body and "의미 검색이 꺼져 있습니다" in body and "product 2개" in body
    with override_settings(**SEMANTIC_ON):
        assert "의미 검색 사용 중: fake-embedding" in client.get(url).content.decode()
    row = Embedding.objects.get(object_id="NB-1")
    assert client.get(reverse("admin:ai_embedding_change", args=[row.pk])).status_code == 200
    assert client.get(reverse("admin:ai_embedding_add")).status_code == 403


def test_admin_is_for_superusers_only(member):
    client = Client()
    client.force_login(member)
    assert client.get(reverse("admin:ai_embedding_changelist")).status_code in (302, 403)


def test_health_report_includes_embedding_counts_only_when_enabled(fake_provider, catalogue):
    call_command("rebuild_search_index", stdout=StringIO())
    call_command("build_embeddings", "--kind", "products", stdout=StringIO())

    def report():
        out = StringIO()
        call_command("check_search_health", "--json", "--audit-limit", "0", "--max-ms", "60000", stdout=out)
        return json.loads(out.getvalue())

    assert "embeddings" not in report()
    with override_settings(**SEMANTIC_ON):
        rows = report()["embeddings"]
    assert rows == [{"kind": "product", "model": "fake-embedding", "dimensions": 1024, "count": 2,
                     "updated": rows[0]["updated"]}]


def test_scheduled_job_is_added_only_for_a_configured_semantic_search():
    assert "build_embeddings" not in scheduled_jobs.JOB_NAMES
    try:
        with override_settings(G5_AI_SEMANTIC_SEARCH=True, G5_AI_BASE_URL="http://127.0.0.1:11434/v1"):
            importlib.reload(scheduled_jobs)
            job = scheduled_jobs.select_jobs(["build_embeddings"])[0]
        assert job.args(dry_run=False) == ("--json", "--limit", "200")
        assert job.args(dry_run=True) == ("--json", "--dry-run")
    finally:
        importlib.reload(scheduled_jobs)
    assert "build_embeddings" not in scheduled_jobs.JOB_NAMES


def test_configure_ai_postgres_refuses_other_databases(db):
    from django.db import connection

    if connection.vendor == "postgresql":
        pytest.skip("covered by the PostgreSQL CI job")
    with pytest.raises(CommandError, match="PostgreSQL-only"):
        call_command("configure_ai_postgres", stdout=StringIO())


def test_field_conversions():
    field = EmbeddingVectorField()
    assert unpack(pack([1.5, -2.0])).tolist() == [1.5, -2.0]
    assert field.to_python(None) is None
    assert field.to_python([1.0]) == [1.0]
    assert field.to_python(pack([0.25])) == [0.25]
    assert field.to_python("[1,2]") == [1.0, 2.0]
    assert field.get_prep_value((1, 2)) == [1.0, 2.0]

    class Row:
        embedding = [1, 2]

    field.attname = "embedding"
    assert field.value_to_string(Row()) == "[1.0,2.0]"
