from datetime import timedelta
from itertools import count
from unittest import mock

import pytest
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api.shop_common import on_sale_products
from gnu_jango.api.v1_shop import product_cards
from gnu_jango.shop.bought_together import bought_together, ranked_partner_ids
from gnu_jango.shop.models import ShopProductRelation
from gnu_jango.testing.factories import (
    MemberFactory,
    ShopOrderFactory,
    ShopOrderItemFactory,
    ShopProductFactory,
)

pytestmark = pytest.mark.django_db
guests = count(1)


def order(*products, buyer=None, days_ago=1, line_statuses=None, od_status="입금", **contact):
    if buyer is None and not contact:
        contact = {"od_email": f"guest{next(guests)}@example.test"}
    placed = ShopOrderFactory(
        user=buyer, od_status=od_status, od_datetime=timezone.now() - timedelta(days=days_ago), **contact
    )
    for product in products:
        status = (line_statuses or {}).get(product, "입금")
        ShopOrderItemFactory(order=placed, product=product, ct_status=status)
    return placed


def orders(*products, times=3, **kwargs):
    for _ in range(times):
        order(*products, **kwargs)


def partners(product, **kwargs):
    return [item.it_id for item in bought_together(product, product_cards(on_sale_products()), **kwargs)]


def api_partners(it_id):
    response = APIClient().get(f"/api/v1/shop/products/{it_id}")
    assert response.status_code == 200, response.content[:500]
    return [row["it_id"] for row in response.json()["data"]["bought_together_items"]]


@pytest.fixture
def shelf():
    return {name: ShopProductFactory(it_id=name) for name in ("P", "A", "B", "C", "D", "E")}


def test_partners_rank_by_shared_buyers_and_need_three(shelf):
    p, a, b, c = shelf["P"], shelf["A"], shelf["B"], shelf["C"]
    order(p, a, b, c, days_ago=5)
    order(p, a, b, c, days_ago=4)
    order(p, a, b, days_ago=3)
    order(p, a, days_ago=2)
    order(a, b, c, days_ago=1)
    assert partners(p) == ["A", "B"]


def test_ties_go_to_the_latest_shared_order_then_the_id(shelf):
    p, b, c, d = shelf["P"], shelf["B"], shelf["C"], shelf["D"]
    order(p, b, c, d, days_ago=20)
    order(p, b, c, d, days_ago=10)
    order(p, b, d, days_ago=9)
    order(p, c, days_ago=2)
    assert partners(p) == ["C", "B", "D"]


def test_one_member_buying_a_pair_again_and_again_shows_nothing(shelf):
    p, a = shelf["P"], shelf["A"]
    orders(p, a, buyer=MemberFactory())
    assert partners(p) == []


def test_two_buyers_hide_the_pair_and_a_third_shows_it(shelf):
    p, a = shelf["P"], shelf["A"]
    order(p, a, buyer=MemberFactory())
    order(p, a, buyer=MemberFactory())
    assert partners(p) == []
    order(p, a, buyer=MemberFactory())
    cache.clear()
    assert partners(p) == ["A"]


def test_members_and_guests_count_together(shelf):
    p, a = shelf["P"], shelf["A"]
    order(p, a, buyer=MemberFactory())
    order(p, a, od_email="guest@example.test")
    order(p, a, od_email="", od_hp="010-2222-3333")
    assert partners(p) == ["A"]


def test_one_guest_email_is_one_buyer_whatever_the_case_or_spaces(shelf):
    p, a = shelf["P"], shelf["A"]
    order(p, a, buyer=MemberFactory())
    order(p, a, od_email="Guest@Example.test", od_hp="010-1111-2222")
    order(p, a, od_email=" guest@example.test ", od_hp="010-3333-4444")
    assert partners(p) == []


@pytest.mark.parametrize(
    "typed",
    [
        "01012345678",
        "010 1234 5678",
        " 010-1234-5678 ",
        "010.1234.5678",
        "(010)1234-5678",
        "+82 10-1234-5678",
        "+82-10-1234-5678",
        "+821012345678",
        "010\t1234\t5678",
    ],
)
def test_one_guest_phone_is_one_buyer_whatever_the_format(shelf, typed):
    p, a = shelf["P"], shelf["A"]
    order(p, a, buyer=MemberFactory())
    order(p, a, od_email="", od_hp="010-1234-5678")
    order(p, a, od_email="", od_hp=typed)
    assert partners(p) == []
    order(p, a, od_email="", od_hp="010-9999-0000")
    cache.clear()
    assert partners(p) == ["A"]


def test_a_guest_without_email_or_phone_is_not_a_buyer(shelf):
    p, a = shelf["P"], shelf["A"]
    order(p, a, buyer=MemberFactory())
    order(p, a, buyer=MemberFactory())
    order(p, a, od_email="", od_hp="")
    order(p, a, od_email="", od_hp="")
    assert partners(p) == []


def test_only_paid_orders_and_sold_lines_count(shelf):
    p, a, b, c = shelf["P"], shelf["A"], shelf["B"], shelf["C"]
    orders(p, a, b, c, times=2)
    order(p, a, od_status="주문")
    order(p, a, od_status="취소")
    order(p, a, line_statuses={p: "취소"})
    order(p, b, line_statuses={b: "반품"})
    order(p, b, line_statuses={b: "returned"})
    order(p, c, line_statuses={c: "canceled"})
    order(p, c, line_statuses={c: "return"})
    order(p, a, b, c, days_ago=400)
    assert partners(p) == []
    order(p, a, b, c, od_status="완료")
    cache.clear()
    assert partners(p) == ["A", "B", "C"]


def test_a_partner_counts_once_per_buyer_even_on_several_lines_or_without_a_product_row(shelf):
    p, a = shelf["P"], shelf["A"]
    order(p, a, a)
    order(p, a)
    for _ in range(2):
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
    orders(p, a)
    assert partners(p) == []
    cache.clear()
    assert partners(p) == ["A"]


def test_hidden_products_the_product_and_exclusions_never_show(shelf):
    p = shelf["P"]
    others = [shelf[name] for name in ("A", "B", "C", "D", "E")]
    orders(p, *others)
    shelf["B"].it_use = "0"
    shelf["B"].save(update_fields=["it_use"])
    assert partners(p, exclude=["A"]) == ["C", "D", "E"]
    assert partners(p, limit=2) == ["A", "C"]


def test_sold_out_partners_never_show_and_come_back_with_stock(shelf):
    p, a, b, c = shelf["P"], shelf["A"], shelf["B"], shelf["C"]
    orders(p, a, b, c)
    a.it_soldout = "1"
    a.save(update_fields=["it_soldout"])
    b.it_stock_qty = 0
    b.save(update_fields=["it_stock_qty"])
    assert partners(p) == ["C"]
    a.it_soldout = ""
    a.save(update_fields=["it_soldout"])
    assert partners(p) == ["A", "C"]


def test_many_hidden_top_partners_do_not_starve_the_list(shelf):
    p, e = shelf["P"], shelf["E"]
    hidden = [ShopProductFactory(it_id=f"H{n:02}", it_use="0") for n in range(40)]
    for days_ago in (3, 4, 5, 6):
        order(p, *hidden, days_ago=days_ago)
    orders(p, e)
    assert partners(p) == ["E"]


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
    orders(p, a)
    with mock.patch("gnu_jango.shop.bought_together.cache") as broken:
        broken.get.side_effect = ConnectionError
        broken.set.side_effect = ConnectionError
        assert partners(p) == ["A"]


def test_product_detail_lists_bought_together_items_without_related_products(shelf):
    p, a, b = shelf["P"], shelf["A"], shelf["B"]
    assert api_partners("P") == []
    cache.clear()
    orders(p, a, b)
    ShopProductRelation.objects.create(product=p, related=a, ir_no=1)
    with mock.patch("gnu_jango.api.v1_shop.related_list_enabled", return_value=True):
        assert api_partners("P") == ["B"]
