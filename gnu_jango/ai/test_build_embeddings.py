import json
from io import StringIO

import pytest
from django.core.management import CommandError, call_command
from django.db import connection

from gnu_jango.ai.client import EmbeddingError
from gnu_jango.ai.models import Embedding
from gnu_jango.ai.store import cosine, nearest, normalize
from gnu_jango.testing.factories import BoardFactory, PostFactory, ShopProductFactory


def run(*args):
    out = StringIO()
    call_command("build_embeddings", "--json", *args, stdout=out)
    return json.loads(out.getvalue())


def stored(kind):
    return set(Embedding.objects.filter(kind=kind).values_list("object_id", flat=True))


def test_builds_docs_and_on_sale_products_only(fake_provider, handbook, catalogue):
    PostFactory(board=BoardFactory(bo_table="free"), wr_subject="일반 글", wr_content="노트북 반품")
    report = run()
    assert report["embedded"] == 4
    assert stored("docs") == {str(handbook.refund.pk), str(handbook.shipping.pk)}
    assert stored("product") == {"NB-1", "MS-1"}
    texts = " ".join(fake_provider.embedded_texts)
    assert "비밀" not in texts and "단종" not in texts and "일반 글" not in texts
    row = Embedding.objects.get(kind="docs", object_id=str(handbook.refund.pk))
    assert (row.board_id, row.model, row.dimensions) == (handbook.board.pk, "fake-embedding", 1024)
    # Batches follow the provider's batch size (2).
    assert all(len(batch) <= 2 for batch in fake_provider.calls)


def test_second_run_skips_unchanged_text_and_re_embeds_edits(fake_provider, handbook, catalogue):
    run()
    fake_provider.calls.clear()
    assert run()["embedded"] == 0
    assert fake_provider.calls == []

    catalogue.mouse.it_name = "무선 게이밍 마우스"
    catalogue.mouse.save()
    report = run()
    assert report["embedded"] == 1 and report["unchanged"] == 3
    assert fake_provider.embedded_texts[0].startswith("무선 게이밍 마우스")


def test_deleted_hidden_and_secret_sources_are_pruned(fake_provider, handbook, catalogue):
    run()
    catalogue.laptop.it_use = "0"
    catalogue.laptop.save()
    catalogue.mouse.delete()
    handbook.shipping.wr_option = "secret"
    handbook.shipping.save()
    report = run()
    assert report["pruned"] == 3
    assert stored("product") == set()
    assert stored("docs") == {str(handbook.refund.pk)}


def test_limit_defers_and_rebuild_re_embeds_everything(fake_provider, handbook, catalogue):
    report = run("--kind", "products", "--limit", "1")
    assert (report["embedded"], report["deferred"]) == (1, 1)
    assert run("--kind", "products")["embedded"] == 1
    assert run("--kind", "products", "--rebuild")["embedded"] == 2
    assert stored("docs") == set()


def test_dry_run_counts_without_calling_the_endpoint(fake_provider, handbook, catalogue):
    report = run("--dry-run")
    assert report["dry_run"] is True
    assert sum(kind["would_embed"] for kind in report["kinds"]) == 4
    assert fake_provider.calls == [] and not Embedding.objects.exists()


def test_model_change_re_embeds(fake_provider, catalogue):
    run("--kind", "products")
    fake_provider.model = "fake-embedding-v2"
    assert run("--kind", "products")["embedded"] == 2
    assert set(Embedding.objects.values_list("model", flat=True)) == {"fake-embedding-v2"}


def test_unconfigured_endpoint(db):
    assert run() == {"configured": False}
    with pytest.raises(CommandError, match="No embedding endpoint"):
        call_command("build_embeddings", stdout=StringIO())


def test_provider_failure_keeps_finished_batches(fake_provider, catalogue):
    ShopProductFactory(it_id="X-3", it_name="세 번째 상품", category=catalogue.category)
    original = fake_provider.embed

    def fail_second_batch(texts):
        if fake_provider.calls:
            fake_provider.calls.append(list(texts))
            raise EmbeddingError("timeout")
        return original(texts)

    fake_provider.embed = fail_second_batch
    with pytest.raises(CommandError, match="timeout"):
        call_command("build_embeddings", "--kind", "products", stdout=StringIO())
    assert Embedding.objects.filter(kind="product").count() == 2


def test_negative_limit_is_rejected(fake_provider):
    with pytest.raises(CommandError):
        call_command("build_embeddings", "--limit", "-1", stdout=StringIO())


def test_text_output(fake_provider, catalogue):
    out = StringIO()
    call_command("build_embeddings", "--kind", "products", stdout=out)
    assert "product: embedded 2" in out.getvalue()


def test_cosine_and_normalize():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([0, 0], [1, 0]) == 0.0
    assert normalize([3, 4]) == pytest.approx([0.6, 0.8])
    with pytest.raises(ValueError):
        normalize([0, 0])


@pytest.mark.skipif(connection.vendor == "postgresql", reason="portable (SQLite/MySQL) storage path")
def test_portable_storage_round_trip_and_nearest(db):
    def save(object_id, vector, *, model="m", dimensions=3):
        Embedding.objects.create(kind="product", object_id=object_id, model=model, dimensions=dimensions,
                                 text_hash="h", embedding=normalize(vector))

    save("a", [1, 0, 0])
    save("b", [1, 1, 0])
    save("c", [0, 0, 1])
    save("other-model", [1, 0, 0], model="old")
    with connection.cursor() as cursor:
        cursor.execute("SELECT embedding FROM ai_embedding WHERE object_id = 'a'")
        assert bytes(cursor.fetchone()[0]) == b"\x00\x00\x80?" + b"\x00" * 8  # float32 little-endian
    assert Embedding.objects.get(object_id="b").embedding == pytest.approx([0.7071068, 0.7071068, 0.0])

    found = nearest("product", [1, 0.1, 0], model="m", dimensions=3, limit=2)
    assert [object_id for object_id, _ in found] == ["a", "b"]
    assert found[0][1] == pytest.approx(cosine([1, 0.1, 0], [1, 0, 0]), rel=1e-5)
    assert nearest("product", [1, 0], model="m", dimensions=3, limit=2) == []

    # The decoded copy follows edits and deletes.
    Embedding.objects.filter(object_id="c").update(embedding=normalize([1, 0.2, 0]))
    Embedding.objects.filter(object_id="a").delete()
    assert nearest("product", [1, 0.1, 0], model="m", dimensions=3, limit=1)[0][0] == "c"
