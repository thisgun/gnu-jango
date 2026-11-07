from datetime import timedelta
from unittest import mock

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api.shop_common import on_sale_products
from gnu_jango.api.v1_shop import product_cards
from gnu_jango.shop.bought_together import bought_together, ranked_partner_ids
from gnu_jango.shop.models import ShopProductRelation
from gnu_jango.testing.factories import ShopOrderFactory, ShopOrderItemFactory, ShopProductFactory

pytestmark = pytest.mark.django_db


def order(*products, days_ago=1, line_statuses=None):
    placed = ShopOrderFactory(od_status="입금", od_datetime=timezone.now() - timedelta(days=days_ago))
    for product in products:
        status = (line_statuses or {}).get(product, "입금")
        ShopOrderItemFactory(order=placed, product=product, ct_status=status)
    return placed


def partners(product, **kwargs):
    return [item.it_id for item in bought_together(product, product_cards(on_sale_products()), **kwargs)]


def api_partners(it_id):
    response = APIClient().get(f"/api/v1/shop/products/{it_id}")
    assert response.status_code == 200, response.content[:500]
    return [row["it_id"] for row in response.json()["data"]["bought_together_items"]]


@pytest.fixture
def shelf():
    return {name: ShopProductFactory(it_id=name) for name in ("P", "A", "B", "C", "D", "E")}


def test_partners_rank_by_shared_orders_and_need_two(shelf):
    p, a, b, c = shelf["P"], shelf["A"], shelf["B"], shelf["C"]
    order(p, a, b, days_ago=5)
    order(p, a, b, days_ago=4)
    order(p, a, c, days_ago=3)
    order(a, b, c, days_ago=2)
    assert partners(p) == ["A", "B"]


def test_ties_go_to_the_latest_shared_order_then_the_id(shelf):
    p, b, c, d = shelf["P"], shelf["B"], shelf["C"], shelf["D"]
    order(p, b, c, d, days_ago=10)
    order(p, b, d, days_ago=9)
    order(p, c, days_ago=2)
    assert partners(p) == ["C", "B", "D"]


def test_cancelled_lines_and_old_orders_are_not_counted(shelf):
    p, a, b, c = shelf["P"], shelf["A"], shelf["B"], shelf["C"]
    order(p, a, b, c)
    order(p, a, line_statuses={p: "취소"})
    order(p, b, line_statuses={b: "반품"})
    order(p, c, line_statuses={c: "cancel"})
    order(p, a, b, c, days_ago=400)
    assert partners(p) == []


def test_a_partner_counts_once_per_order_even_on_several_lines_or_without_a_product_row(shelf):
    p, a = shelf["P"], shelf["A"]
    order(p, a, a)
    gone = order(p)
    ShopOrderItemFactory(order=gone, product=None, it_id="GONE", it_name="삭제된 상품", ct_price=1000)
    assert partners(p) == []
    order(p, a)
    again = order(p)
    ShopOrderItemFactory(order=again, product=None, it_id="GONE", it_name="삭제된 상품", ct_price=1000)
    cache.clear()
    assert partners(p) == ["A"]
    assert ranked_partner_ids("P") == ["GONE", "A"]


def test_the_ranking_is_cached_for_the_hour(shelf):
    p, a = shelf["P"], shelf["A"]
    assert partners(p) == []
    order(p, a)
    order(p, a)
    assert partners(p) == []
    cache.clear()
    assert partners(p) == ["A"]


def test_hidden_products_the_product_and_exclusions_never_show(shelf):
    p = shelf["P"]
    others = [shelf[name] for name in ("A", "B", "C", "D", "E")]
    order(p, *others)
    order(p, *others)
    shelf["B"].it_use = "0"
    shelf["B"].save(update_fields=["it_use"])
    assert partners(p, exclude=["A"]) == ["C", "D", "E"]
    assert partners(p, limit=2) == ["A", "C"]


def test_ranking_runs_two_queries_whatever_the_order_count(shelf, django_assert_num_queries):
    p, a, b = shelf["P"], shelf["A"], shelf["B"]
    for days_ago in range(1, 21):
        order(p, a, b, days_ago=days_ago)
    base = product_cards(on_sale_products())
    with django_assert_num_queries(2):
        assert [item.it_id for item in bought_together(p, base)] == ["A", "B"]
    with django_assert_num_queries(1):
        assert [item.it_id for item in bought_together(p, base)] == ["A", "B"]


def test_a_cache_outage_still_ranks(shelf):
    p, a = shelf["P"], shelf["A"]
    order(p, a)
    order(p, a)
    with mock.patch("gnu_jango.shop.bought_together.cache") as broken:
        broken.get.side_effect = ConnectionError
        broken.set.side_effect = ConnectionError
        assert partners(p) == ["A"]


def test_product_detail_lists_bought_together_items_without_related_products(shelf):
    p, a, b = shelf["P"], shelf["A"], shelf["B"]
    assert api_partners("P") == []
    cache.clear()
    order(p, a, b)
    order(p, a, b)
    ShopProductRelation.objects.create(product=p, related=a, ir_no=1)
    with mock.patch("gnu_jango.api.v1_shop.related_list_enabled", return_value=True):
        assert api_partners("P") == ["B"]
