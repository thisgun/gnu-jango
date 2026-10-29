import logging
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.test import override_settings
from rest_framework.test import APIClient

from gnu_jango.ai.recommend import similar_products
from gnu_jango.shop.models import ShopProduct, ShopProductRelation
from gnu_jango.testing.factories import ShopProductFactory

# The fake vectors of two laptops sharing "노트북" and the category score about 0.58; the laptop and
# the mouse share only the category name (0.25), which alone should not make them similar.
SIMILAR_ON = {"G5_AI_SIMILAR_PRODUCTS": True, "G5_AI_SIMILAR_MIN_SIMILARITY": 0.4}


@pytest.fixture
def embedded(fake_provider, catalogue):
    catalogue.gaming = ShopProductFactory(it_id="NB-2", it_name="게이밍 노트북", category=catalogue.category)
    call_command("build_embeddings", stdout=StringIO())
    fake_provider.calls.clear()
    return catalogue


def similar_ids(it_id):
    response = APIClient().get(f"/api/v1/shop/products/{it_id}")
    assert response.status_code == 200, response.content[:500]
    return [row["it_id"] for row in response.json()["data"]["similar_items"]]


def test_similar_items_are_on_sale_neighbours_found_without_calling_the_endpoint(embedded, fake_provider):
    with override_settings(**SIMILAR_ON):
        found = similar_ids("NB-1")
    # the mouse is under the floor; the hidden laptop is off sale; never the product itself
    assert found == ["NB-2"]
    assert fake_provider.calls == []


def test_similar_items_stay_empty_when_the_setting_is_off(embedded):
    with override_settings(G5_AI_SIMILAR_PRODUCTS=False, G5_AI_SIMILAR_MIN_SIMILARITY=0.1):
        assert similar_ids("NB-1") == []


def test_the_default_floor_is_stricter_than_the_search_floor(embedded):
    # the two laptops (about 0.58) clear the 0.5 search floor but not the 0.65 similar-products one
    with override_settings(G5_AI_SIMILAR_PRODUCTS=True):
        assert similar_ids("NB-1") == []


def test_similar_items_leave_out_the_admin_related_products(embedded):
    ShopProductRelation.objects.create(product=embedded.laptop, related=embedded.gaming, ir_no=1)
    with override_settings(**SIMILAR_ON), mock.patch("gnu_jango.api.v1_shop.related_list_enabled", return_value=True):
        response = APIClient().get("/api/v1/shop/products/NB-1")
    data = response.json()["data"]
    assert [row["it_id"] for row in data["related_items"]] == ["NB-2"]
    assert data["similar_items"] == []


def test_a_product_without_an_embedding_gets_no_similar_items(embedded):
    ShopProductFactory(it_id="NB-NEW", it_name="새 노트북", category=embedded.category)
    with override_settings(**SIMILAR_ON):
        assert similar_ids("NB-NEW") == []


def test_a_vector_query_failure_is_logged_and_the_page_still_answers(embedded, caplog):
    caplog.set_level(logging.WARNING, logger="gnu_jango.ai.recommend")
    with override_settings(**SIMILAR_ON), mock.patch("gnu_jango.ai.recommend.store.nearest", side_effect=RuntimeError):
        assert similar_ids("NB-1") == []
    assert "Similar products unavailable" in caplog.text


def test_similar_products_returns_at_most_the_limit_best_first(fake_provider, catalogue):
    for number in range(6):
        ShopProductFactory(it_id=f"NB-{10 + number}", it_name=f"노트북 {'가벼운 ' * (number % 2)}모델{number}",
                           category=catalogue.category)
    call_command("build_embeddings", stdout=StringIO())
    with override_settings(**SIMILAR_ON):
        found = similar_products(catalogue.laptop, ShopProduct.objects.filter(it_use="1"))
    assert len(found) == 4
    # products sharing two words with "가벼운 노트북" come before those sharing one
    assert {item.it_id for item in found[:3]} == {"NB-11", "NB-13", "NB-15"}
