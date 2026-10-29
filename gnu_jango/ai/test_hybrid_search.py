import logging
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APIClient

from gnu_jango.ai.client import EmbeddingError
from gnu_jango.ai.conftest import SEMANTIC_ON
from gnu_jango.ai.search import reciprocal_rank_fusion
from gnu_jango.testing.factories import MemberFactory

UNIFIED = "/api/v1/search/unified"
ASK = "/api/v1/docs/ask"
PRODUCTS = "/api/v1/shop/products"


@pytest.fixture(autouse=True)
def bigram_tokenizer():
    # Same as the site_search tests: deterministic bigrams instead of the optional Kiwi analyser.
    with mock.patch("gnu_jango.docs_search.tokenizer._get_kiwi", return_value=None):
        yield


@pytest.fixture
def indexed(fake_provider, handbook, catalogue):
    call_command("rebuild_search_index", stdout=StringIO())
    call_command("build_embeddings", stdout=StringIO())
    fake_provider.calls.clear()
    return handbook, catalogue


def unified(query, client=None, **params):
    response = (client or APIClient()).get(UNIFIED, {"q": query, **params})
    assert response.status_code == 200, response.content[:500]
    return response.json()


def ids(payload):
    return [(row["type"], row["id"]) for row in payload["data"]["results"]]


def without_click_tokens(payload):
    # click tokens are timestamp-signed, so two identical searches a second apart differ there
    results = [{key: value for key, value in row.items() if key != "click_token"} for row in payload["data"]["results"]]
    return {**payload, "data": {**payload["data"], "results": results}}


def product_ids(query, **params):
    response = APIClient().get(PRODUCTS, {"q": query, **params})
    assert response.status_code == 200, response.content[:500]
    return [row["it_id"] for row in response.json()["data"]]


def ask(query, client=None):
    response = (client or APIClient()).get(ASK, {"q": query})
    assert response.status_code == 200, response.content[:500]
    return response.json()["data"]["results"]


def test_reciprocal_rank_fusion_rewards_agreement():
    scores = reciprocal_rank_fusion([["a", "b", "c"], ["c", "d"]], k=60)
    assert scores["c"] == pytest.approx(1 / 63 + 1 / 61)
    assert max(scores, key=scores.get) == "c"
    assert scores["a"] > scores["b"] and scores["d"] == pytest.approx(1 / 62)


def test_unified_search_finds_a_synonym_lexical_search_misses(indexed):
    _, catalogue = indexed
    assert ("product", "NB-1") not in ids(unified("랩탑"))
    with override_settings(**SEMANTIC_ON):
        payload = unified("랩탑")
    assert ("product", "NB-1") in ids(payload)
    assert ("product", "NB-HIDDEN") not in ids(payload)
    assert ("product", "MS-1") not in ids(payload)
    assert payload["meta"]["total"] >= 1


def test_unified_search_ranks_lexical_and_semantic_agreement_first(indexed):
    with override_settings(**SEMANTIC_ON):
        rows = ids(unified("노트북", type="product"))
    assert rows[0] == ("product", "NB-1")


def test_disabled_ai_returns_identical_results_and_never_calls_the_provider(indexed, fake_provider):
    for query in ("랩탑", "노트북", "반품"):
        before = without_click_tokens(unified(query))
        assert without_click_tokens(unified(query)) == before
    assert product_ids("랩탑") == []
    assert [row["wr_id"] for row in ask("환불 방법")] == [row["wr_id"] for row in ask("환불 방법")]
    assert fake_provider.calls == []


def test_ai_error_falls_back_to_lexical_results(indexed, fake_provider, caplog):
    lexical = unified("노트북")
    lexical_products = product_ids("노트북")
    lexical_ask = ask("배송 조회")
    fake_provider.error = EmbeddingError("timeout")
    with override_settings(**SEMANTIC_ON), caplog.at_level(logging.WARNING, logger="gnu_jango.ai.search"):
        assert ids(unified("노트북")) == ids(lexical)
        assert product_ids("노트북") == lexical_products
        assert ask("배송 조회") == lexical_ask
    assert "Semantic search unavailable" in caplog.text


def test_handbook_permissions_apply_to_semantic_matches(indexed):
    handbook, _ = indexed
    handbook.board.bo_read_level = 3
    handbook.board.save()
    member = MemberFactory(level=3)
    member_client = APIClient()
    member_client.force_authenticate(member)
    refund = ("document", str(handbook.refund.pk))
    secret = ("document", str(handbook.secret.pk))
    with override_settings(**SEMANTIC_ON):
        assert refund not in ids(unified("환불", type="document"))
        assert refund in ids(unified("환불", member_client, type="document"))
        assert secret not in ids(unified("환불", member_client, type="document"))
        assert handbook.refund.pk not in [row["wr_id"] for row in ask("환불 절차")]
        assert handbook.refund.pk in [row["wr_id"] for row in ask("환불 절차", member_client)]


def test_type_and_board_filters_limit_semantic_matches(indexed):
    handbook, _ = indexed
    with override_settings(**SEMANTIC_ON):
        assert ("product", "NB-1") not in ids(unified("랩탑", type="post"))
        assert ("product", "NB-1") not in ids(unified("랩탑", type="document"))
        assert ("product", "NB-1") not in ids(unified("랩탑", bo_table=handbook.board.bo_table))


def test_docs_ask_adds_a_chapter_found_by_meaning(indexed):
    handbook, _ = indexed
    assert handbook.refund.pk not in [row["wr_id"] for row in ask("환불 절차")]
    with override_settings(**SEMANTIC_ON):
        results = ask("환불 절차")
    chapter = next(row for row in results if row["wr_id"] == handbook.refund.pk)
    assert "반품" in chapter["snippet"]
    assert chapter["score"] > 0
    assert handbook.secret.pk not in [row["wr_id"] for row in results]


def test_product_search_adds_semantic_matches_inside_storefront_filters(indexed):
    assert product_ids("랩탑") == []
    with override_settings(**SEMANTIC_ON):
        assert product_ids("랩탑") == ["NB-1"]
        assert product_ids("랩탑", ca_id="99") == []
        assert product_ids("랩탑", qname="1") == []  # a single-column search stays literal
        assert product_ids("노트북")[0] == "NB-1"


def test_query_embeddings_are_cached(indexed, fake_provider):
    with override_settings(**SEMANTIC_ON):
        unified("랩탑")
        # One query embedding serves both products and handbook chapters.
        assert len(fake_provider.calls) == 1
        unified("랩탑")
    assert len(fake_provider.calls) == 1


def test_a_failed_endpoint_is_skipped_for_a_while(indexed, fake_provider):
    fake_provider.error = EmbeddingError("timeout")
    with override_settings(**SEMANTIC_ON):
        unified("랩탑")
        unified("노트북")
        product_ids("마우스")
    assert len(fake_provider.calls) == 1


def test_similarity_floor_drops_weak_neighbours(indexed):
    with override_settings(**{**SEMANTIC_ON, "G5_AI_SEMANTIC_MIN_SIMILARITY": 0.99}):
        assert ("product", "NB-1") not in ids(unified("랩탑"))
