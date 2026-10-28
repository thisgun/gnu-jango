"""Coupon invariants across whole order flows.

A member's coupon discounts at most one live order at a time: it is used up when the order is
placed, a second checkout (another order, a stale cart, a replayed request) gets no discount from
it, and it comes back only when the whole order is cancelled - a partial cancel keeps it used, as
youngcart does. A discount never makes a line, the goods or the shipping fee negative, and the
minimum/maximum of the coupon hold at checkout and again after line cancels.
"""

import pytest

from gnu_jango.shop.models import ShopCoupon, ShopCouponLog, ShopOrder
from gnu_jango.shop.order_coupons import order_coupon_totals
from gnu_jango.shop.order_lines import change_order_lines
from gnu_jango.testing.factories import MemberFactory, ShopCouponFactory, ShopProductFactory
from gnu_jango.testing.shop_flows import (
    SHIPPING_FEE,
    admin_status,
    assert_fully_cancelled,
    assert_order_money_consistent,
    assert_stock_conserved,
    checkout,
    client_for,
    configure_shop,
    line_of,
    pay,
    place_bank_order,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop(db):
    configure_shop()
    return {
        "shirt": ShopProductFactory(it_price=20000, it_stock_qty=10),
        "cap": ShopProductFactory(it_price=10000, it_stock_qty=10),
    }


@pytest.fixture
def buyer(db):
    return MemberFactory()


def live_orders_discounted_by(coupon):
    """Orders not cancelled that carry a discount from ``coupon``."""
    return (
        ShopCouponLog.objects.filter(coupon=coupon, cp_price__gt=0)
        .exclude(order__od_status__in=("취소", "반품"))
        .values_list("order_id", flat=True)
        .distinct()
        .count()
    )


def close_by_customer(order, shop):
    client_for(order.user).post("/api/v1/shop/payment/cancel", {"order_id": order.od_id}, format="json")


def close_paid_by_admin(order, shop):
    pay(order)
    admin_status(order, "취소")


def close_line_by_line(order, shop):
    pay(order)
    for product in ("cap", "shirt"):
        assert change_order_lines(order, [line_of(order, shop[product]).pk], "취소")


def close_by_return(order, shop):
    for status in ("입금", "준비", "배송", "완료", "반품"):
        assert admin_status(order, status)


CLOSE_PATHS = {
    "customer cancel": close_by_customer,
    "admin cancel after payment": close_paid_by_admin,
    "line by line": close_line_by_line,
    "return after delivery": close_by_return,
}


@pytest.mark.parametrize("close", CLOSE_PATHS.values(), ids=list(CLOSE_PATHS))
def test_an_order_coupon_discounts_one_live_order_until_that_order_closes(buyer, shop, close):
    coupon = ShopCouponFactory(user=buyer, cp_price=3000)
    items = [(shop["shirt"], 2), (shop["cap"], 1)]

    first = place_bank_order(client_for(buyer), items, cp_id=coupon.cp_id)
    second = place_bank_order(client_for(buyer), items, cp_id=coupon.cp_id)  # the same coupon again
    assert (first.od_coupon, second.od_coupon) == (3000, 0)
    assert live_orders_discounted_by(coupon) == 1
    coupon.refresh_from_db()
    assert coupon.cp_used == "1"

    close(first, shop)
    coupon.refresh_from_db()
    assert coupon.cp_used == ""
    assert live_orders_discounted_by(coupon) == 0
    assert_order_money_consistent(first)

    third = place_bank_order(client_for(buyer), items, cp_id=coupon.cp_id)
    assert third.od_coupon == 3000
    assert live_orders_discounted_by(coupon) == 1


def test_a_partial_cancel_keeps_the_coupon_used_and_the_full_close_releases_it(buyer, shop):
    # the minimum (45,000) no longer holds once the cap goes: the discount drops, the coupon stays used
    coupon = ShopCouponFactory(user=buyer, cp_price=5000, cp_minimum=45000)
    order = place_bank_order(client_for(buyer), [(shop["shirt"], 2), (shop["cap"], 1)], cp_id=coupon.cp_id)
    pay(order)
    assert order.od_receipt_price == 45000

    assert change_order_lines(order, [line_of(order, shop["cap"]).pk], "취소")
    order.refresh_from_db()
    coupon.refresh_from_db()
    # 40,000 + 3,000 shipping without the coupon: 2,000 of the 45,000 paid goes back
    assert (order.od_coupon, order.od_send_cost, order.od_refund_price, order.od_misu) == (0, SHIPPING_FEE, 2000, 0)
    assert coupon.cp_used == "1"
    assert list(order.coupon_logs.values_list("cp_price", flat=True)) == [0]
    assert_order_money_consistent(order)
    assert place_bank_order(client_for(buyer), [(shop["shirt"], 3)], cp_id=coupon.cp_id).od_coupon == 0

    assert change_order_lines(order, [line_of(order, shop["shirt"]).pk], "취소")
    coupon.refresh_from_db()
    assert coupon.cp_used == ""
    assert_fully_cancelled(order, paid=45000)


def test_a_product_coupon_in_a_replayed_cart_gives_no_second_discount(buyer, shop):
    """Two checkouts that read the same cart (a double submit racing, or a replayed request): the
    second one still carries the coupon in its cart line, yet gets no discount from it."""
    from gnu_jango.api.shop_common import auth_cart_config_name
    from gnu_jango.config.models import Config

    coupon = ShopCouponFactory(user=buyer, cp_method=0, cp_target=shop["shirt"].it_id, cp_price=4000)
    client = client_for(buyer)
    client.post("/api/v1/shop/cart", {"it_id": shop["shirt"].it_id, "ct_qty": 1}, format="json")
    ct_id = client.get("/api/v1/shop/cart").json()["data"]["items"][0]["ct_id"]
    applied = client.post("/api/v1/shop/coupons/apply-to-cart", {"ct_id": ct_id, "cp_id": coupon.cp_id}, format="json")
    assert applied.status_code == 200, applied.content[:300]
    cart = Config.objects.get(name=auth_cart_config_name(buyer)).value
    assert coupon.cp_id in cart

    first = place_bank_order(client, [])
    Config.objects.filter(name=auth_cart_config_name(buyer)).update(value=cart)  # the second read
    second = place_bank_order(client, [])

    assert [order_coupon_totals(order).cart for order in (first, second)] == [4000, 0]
    assert [order.od_misu for order in (first, second)] == [16000 + SHIPPING_FEE, 20000 + SHIPPING_FEE]
    assert live_orders_discounted_by(coupon) == 1
    for order in (first, second):
        assert_order_money_consistent(order)
    # the second order took its own stock: the replay is a real second order, never a free one
    assert_stock_conserved(shop["shirt"], 10)


def test_a_product_coupon_stops_counting_when_its_line_is_cancelled(buyer, shop):
    coupon = ShopCouponFactory(user=buyer, cp_method=0, cp_target=shop["cap"].it_id, cp_price=2000)
    client = client_for(buyer)
    client.post("/api/v1/shop/cart", {"it_id": shop["cap"].it_id, "ct_qty": 1}, format="json")
    ct_id = client.get("/api/v1/shop/cart").json()["data"]["items"][0]["ct_id"]
    client.post("/api/v1/shop/coupons/apply-to-cart", {"ct_id": ct_id, "cp_id": coupon.cp_id}, format="json")
    order = place_bank_order(client, [(shop["shirt"], 3)])  # 60,000 + cap 10,000 - 2,000
    pay(order)
    assert order.od_receipt_price == 68000

    assert change_order_lines(order, [line_of(order, shop["cap"]).pk], "취소")
    order.refresh_from_db()
    # the shirts alone: 60,000, free shipping; the cap and its 2,000 discount go back together
    assert order_coupon_totals(order).cart == 0
    assert (order.od_refund_price, order.od_misu) == (8000, 0)
    assert_order_money_consistent(order)


# (cp_type, cp_price, cp_maximum, cp_minimum, cp_trunc) -> the discount on a 10,000 cap, or None
# when the checkout refuses the coupon (youngcart dies rather than shrink it to the amount)
ORDER_COUPON_CASES = {
    "fixed below the amount": ((0, 3000, 0, 0, 1), 3000),
    "fixed equal to the amount": ((0, 10000, 0, 0, 1), 10000),
    "fixed above the amount is refused": ((0, 15000, 0, 0, 1), None),
    "rate capped by the maximum": ((1, 30, 2000, 0, 1), 2000),
    "rate rounded down to the unit": ((1, 33, 0, 0, 100), 3300),
    "rate of the whole amount": ((1, 100, 0, 0, 1), 10000),
    "minimum not reached": ((0, 3000, 0, 20000, 1), 0),
}


@pytest.mark.parametrize("values, expected", ORDER_COUPON_CASES.values(), ids=list(ORDER_COUPON_CASES))
def test_an_order_coupon_never_discounts_more_than_the_goods(buyer, shop, values, expected):
    cp_type, cp_price, cp_maximum, cp_minimum, cp_trunc = values
    coupon = ShopCouponFactory(
        user=buyer, cp_type=cp_type, cp_price=cp_price, cp_maximum=cp_maximum, cp_minimum=cp_minimum, cp_trunc=cp_trunc
    )
    response = checkout(client_for(buyer), [(shop["cap"], 1)], cp_id=coupon.cp_id)
    coupon.refresh_from_db()

    if expected is None:
        assert response.status_code == 400
        assert response.json()["code"] == "order_coupon_exceeds_amount"
        assert not ShopOrder.objects.exists()
        assert coupon.cp_used == ""
        assert_stock_conserved(shop["cap"], 10)
        return
    assert response.status_code == 201, response.content[:300]
    order = ShopOrder.objects.get(pk=response.json()["data"]["od_id"])
    assert order.od_coupon == expected
    assert order.od_misu == 10000 + SHIPPING_FEE - expected >= SHIPPING_FEE
    assert coupon.cp_used == ("1" if expected else "")
    assert order.coupon_logs.count() == (1 if expected else 0)
    assert_order_money_consistent(order)


@pytest.mark.parametrize("cp_price, expected", [(2000, 2000), (5000, SHIPPING_FEE)])
def test_a_shipping_coupon_never_discounts_more_than_the_shipping_fee(buyer, shop, cp_price, expected):
    coupon = ShopCouponFactory(user=buyer, cp_method=3, cp_price=cp_price)
    order = place_bank_order(client_for(buyer), [(shop["cap"], 1)], cp_id_send=coupon.cp_id)
    assert (order.od_send_cost, order.od_send_coupon) == (SHIPPING_FEE, expected)
    assert order.od_misu == 10000 + SHIPPING_FEE - expected
    assert_order_money_consistent(order)


def test_a_shipping_coupon_on_free_shipping_is_not_used_up(buyer, shop):
    coupon = ShopCouponFactory(user=buyer, cp_method=3, cp_price=3000)
    order = place_bank_order(client_for(buyer), [(shop["shirt"], 3)], cp_id_send=coupon.cp_id)
    coupon.refresh_from_db()
    assert (order.od_send_cost, order.od_send_coupon, coupon.cp_used) == (0, 0, "")


def test_a_shipping_coupon_falls_away_when_a_cancel_drops_the_order_below_its_minimum(buyer, shop):
    # shirt 20,000 + cap 10,000 = 30,000, shipping 3,000 covered by a coupon needing 25,000 of goods
    coupon = ShopCouponFactory(user=buyer, cp_method=3, cp_price=3000, cp_minimum=25000)
    order = place_bank_order(client_for(buyer), [(shop["shirt"], 1), (shop["cap"], 1)], cp_id_send=coupon.cp_id)
    assert (order.od_send_coupon, order.od_misu) == (3000, 30000)
    pay(order)

    assert change_order_lines(order, [line_of(order, shop["cap"]).pk], "취소")
    order.refresh_from_db()
    # 20,000 + 3,000 shipping without the coupon: 7,000 of the 30,000 goes back, never more
    assert (order.od_send_coupon, order.od_send_cost, order.od_refund_price, order.od_misu) == (0, 3000, 7000, 0)
    assert_order_money_consistent(order)


def test_an_all_member_coupon_is_used_once_per_member_and_comes_back_on_cancel(shop):
    coupon = ShopCouponFactory(cp_all_members=True, cp_price=2000)
    members = [MemberFactory(), MemberFactory()]
    first = [place_bank_order(client_for(member), [(shop["cap"], 1)], cp_id=coupon.cp_id) for member in members]
    again = place_bank_order(client_for(members[0]), [(shop["cap"], 1)], cp_id=coupon.cp_id)
    assert [order.od_coupon for order in first] == [2000, 2000]
    assert again.od_coupon == 0
    coupon.refresh_from_db()
    assert coupon.cp_used == ""  # an all-member coupon stays open; the use is in the member's log

    client_for(members[0]).post("/api/v1/shop/payment/cancel", {"order_id": first[0].od_id}, format="json")
    assert place_bank_order(client_for(members[0]), [(shop["cap"], 1)], cp_id=coupon.cp_id).od_coupon == 2000
    assert ShopCoupon.objects.get(pk=coupon.pk).cp_used == ""
