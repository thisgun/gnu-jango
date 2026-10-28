"""Point invariants across whole order flows.

Whatever sequence of checkout, payment, line cancels, returns and repeated requests an order goes
through, a member's point balance equals the sum of their point history, the points spent at
checkout come back exactly once when the order closes, and purchase points are paid once and taken
back when the goods come back. Every flow goes through the real entry points (cart/order API,
admin status change, admin line change), see gnu_jango/testing/shop_flows.py.
"""

import pytest

from gnu_jango.shop.order_lines import change_order_lines
from gnu_jango.shop.order_points import save_order_points
from gnu_jango.testing.factories import MemberFactory, ShopProductFactory, give_points
from gnu_jango.testing.shop_flows import (
    admin_status,
    assert_fully_cancelled,
    assert_order_money_consistent,
    assert_point_ledger_matches,
    balance,
    client_for,
    configure_shop,
    deliver,
    line_of,
    pay,
    place_bank_order,
)
from gnu_jango.users.models import User_Point

pytestmark = pytest.mark.django_db

START_POINTS = 30000
POINT_USE = 7000
SHIRT_POINT = 200  # purchase point per unit
CAP_POINT = 100


@pytest.fixture
def shop(db):
    configure_shop()
    return {
        "shirt": ShopProductFactory(it_price=20000, it_stock_qty=10, it_point=SHIRT_POINT),
        "cap": ShopProductFactory(it_price=10000, it_stock_qty=10, it_point=CAP_POINT),
    }


@pytest.fixture
def buyer(db):
    member = MemberFactory()
    give_points(member, START_POINTS)
    return member


def place(buyer, shop, **fields):
    """shirt 20,000 × 2 + cap 10,000 = 50,000 (free shipping), paying POINT_USE with points."""
    return place_bank_order(
        client_for(buyer), [(shop["shirt"], 2), (shop["cap"], 1)], point_use=POINT_USE, **fields
    )


def cancel_by_customer(order, buyer, shop):
    return client_for(buyer).post("/api/v1/shop/payment/cancel", {"order_id": order.od_id}, format="json")


def cancel_by_admin(order, buyer, shop):
    return admin_status(order, "취소")


def cancel_paid_by_admin(order, buyer, shop):
    if order.od_status == "주문":
        pay(order)
    return admin_status(order, "취소")


def cancel_line_by_line(order, buyer, shop):
    if order.od_status == "주문":
        pay(order)
    for product in ("cap", "shirt"):
        line = line_of(order, shop[product])
        if line is not None:
            change_order_lines(order, [line.pk], "취소")
            assert_order_money_consistent(order)


def cancel_unpaid_line_by_line(order, buyer, shop):
    for product in ("cap", "shirt"):
        line = line_of(order, shop[product])
        if line is not None:
            change_order_lines(order, [line.pk], "품절" if product == "cap" else "취소")
            assert_order_money_consistent(order)


def cancel_units_then_rest(order, buyer, shop):
    if order.od_status == "주문":
        pay(order)
    shirt = line_of(order, shop["shirt"])
    if shirt is not None and shirt.ct_qty == 2:
        assert change_order_lines(order, [shirt.pk], "취소", quantities={shirt.pk: 1}, expected={shirt.pk: 2})
        assert_order_money_consistent(order)
    order.refresh_from_db()
    if order.od_status not in ("취소", "반품"):
        admin_status(order, "취소")


def return_after_delivery(order, buyer, shop):
    order.refresh_from_db()
    if order.od_status not in ("완료", "반품"):
        deliver(order)
    return admin_status(order, "반품")


CLOSE_PATHS = {
    "customer cancels the unpaid order": (cancel_by_customer, 0),
    "admin cancels the unpaid order": (cancel_by_admin, 0),
    "admin cancels the paid order": (cancel_paid_by_admin, 50000 - POINT_USE),
    "admin cancels a paid order line by line": (cancel_line_by_line, 50000 - POINT_USE),
    "admin cancels and sells out an unpaid order line by line": (cancel_unpaid_line_by_line, 0),
    "admin cancels some units, then the rest": (cancel_units_then_rest, 50000 - POINT_USE),
    "admin takes the delivered order back": (return_after_delivery, 50000 - POINT_USE),
}


@pytest.mark.parametrize("path", CLOSE_PATHS, ids=list(CLOSE_PATHS))
def test_points_spent_at_checkout_come_back_exactly_once_however_the_order_closes(buyer, shop, path):
    close, paid = CLOSE_PATHS[path]
    order = place(buyer, shop)
    assert order.od_receipt_point == POINT_USE
    assert balance(buyer) == START_POINTS - POINT_USE
    assert_point_ledger_matches(buyer)

    close(order, buyer, shop)
    close(order, buyer, shop)  # a repeated request (double submit, retry) changes nothing

    assert balance(buyer) == START_POINTS
    assert_point_ledger_matches(buyer)
    restored = User_Point.objects.filter(user=buyer, po_rel_table="@order-cancel", po_rel_action=order.od_id)
    assert list(restored.values_list("po_point", flat=True)) == [POINT_USE]
    assert_fully_cancelled(order, paid=paid, status="반품" if "back" in path else "취소")
    assert_order_money_consistent(order)


def test_purchase_points_are_paid_once_and_taken_back_line_by_line_as_goods_return(buyer, shop):
    order = place(buyer, shop)
    deliver(order)  # 완료 pays the due points at once (de_point_days 0)
    earned = 2 * SHIRT_POINT + CAP_POINT
    assert balance(buyer) == START_POINTS - POINT_USE + earned
    for _ in range(2):  # the scheduled job running again pays nothing twice
        assert save_order_points()["awarded"] == 0
    assert balance(buyer) == START_POINTS - POINT_USE + earned
    assert_point_ledger_matches(buyer)

    # the cap comes back: its point goes, the shirts keep theirs
    assert change_order_lines(order, [line_of(order, shop["cap"]).pk], "반품")
    assert balance(buyer) == START_POINTS - POINT_USE + 2 * SHIRT_POINT
    assert_point_ledger_matches(buyer)
    assert_order_money_consistent(order)

    # one of the two shirts comes back: the line is split and keeps the point of one unit
    shirt = line_of(order, shop["shirt"])
    assert change_order_lines(order, [shirt.pk], "반품", quantities={shirt.pk: 1}, expected={shirt.pk: 2})
    assert balance(buyer) == START_POINTS - POINT_USE + SHIRT_POINT
    assert_point_ledger_matches(buyer)
    assert save_order_points()["awarded"] == 0
    assert balance(buyer) == START_POINTS - POINT_USE + SHIRT_POINT

    # the last shirt comes back: the order closes, every point earned goes and the spent ones return
    assert change_order_lines(order, [line_of(order, shop["shirt"]).pk], "반품")
    assert balance(buyer) == START_POINTS
    assert_point_ledger_matches(buyer)
    assert not User_Point.objects.filter(user=buyer, po_rel_table="@delivery").exists()
    assert save_order_points()["awarded"] == 0
    assert_fully_cancelled(order, paid=50000 - POINT_USE, status="반품")


def test_two_orders_cannot_spend_the_same_points(buyer, shop):
    first = place_bank_order(client_for(buyer), [(shop["cap"], 1)], point_use=START_POINTS)
    second = place_bank_order(client_for(buyer), [(shop["cap"], 1)], point_use=START_POINTS)

    # the first order takes what it may (capped by what is left to pay), the second gets the rest
    assert first.od_receipt_point == 10000
    assert second.od_receipt_point == 10000
    third = place_bank_order(client_for(buyer), [(shop["shirt"], 1)], point_use=START_POINTS)
    assert third.od_receipt_point == START_POINTS - 20000
    fourth = place_bank_order(client_for(buyer), [(shop["cap"], 1)], point_use=START_POINTS)
    assert fourth.od_receipt_point == 0
    assert balance(buyer) == 0
    assert_point_ledger_matches(buyer)


def test_a_partial_cancel_never_refunds_more_cash_than_was_paid_when_points_paid_most(buyer, shop):
    give_points(buyer, 20000)  # 50,000 in all
    order = place_bank_order(client_for(buyer), [(shop["shirt"], 2), (shop["cap"], 1)], point_use=45000)
    pay(order)
    assert order.od_receipt_price == 5000

    # 40,000 + 3,000 shipping is owed now; 7,000 was overpaid but only 5,000 of it is cash
    result = change_order_lines(order, [line_of(order, shop["cap"]).pk], "취소")
    assert result, result.message
    order.refresh_from_db()
    assert (order.od_refund_price, order.od_misu, order.od_receipt_point) == (5000, 0, 45000)
    assert "포인트 2,000점 수동 조정 필요" in order.od_mod_history
    assert balance(buyer) == START_POINTS + 20000 - 45000  # points are not moved by a partial cancel
    assert_order_money_consistent(order)

    assert change_order_lines(order, [line_of(order, shop["shirt"]).pk], "취소")
    # closing the order gives back every point used and no more cash than was paid
    assert balance(buyer) == START_POINTS + 20000
    assert_point_ledger_matches(buyer)
    assert_fully_cancelled(order, paid=5000)


def test_with_points_switched_off_no_flow_moves_the_point_ledger(buyer, shop):
    from gnu_jango.testing.shop_flows import set_config

    set_config("cf_use_point", "0")
    order = place(buyer, shop)
    assert order.od_receipt_point == 0
    assert all(line.ct_point == 0 for line in order.items.all())
    deliver(order)
    assert balance(buyer) == START_POINTS
    admin_status(order, "반품")
    assert balance(buyer) == START_POINTS
    assert_point_ledger_matches(buyer)
