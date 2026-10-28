"""Money, stock and idempotency invariants across whole order flows.

An order is driven through realistic sequences of line cancels, sold-out marks, partial-quantity
cancels, returns and whole-order cancels, paid by bank deposit (manual refunds) or through Toss
(the refund goes out through the cancel API, faked by a ledger that behaves like Toss). After
every step:

- the order's stored totals agree with its lines (od_cart_price, od_cancel_price, od_misu);
- the cash refunded never exceeds the cash paid, and only grows;
- stock on the shelf plus stock held by order lines is what the shop started with;
- repeating the step (double submit, retried request) changes nothing - no second refund at the
  PG, no second stock restore, no second point refund.

At the end the order is closed with every won paid back, the coupon released and the points
returned.
"""

import json
from unittest.mock import patch

import pytest

from gnu_jango.api.shop_payments import PaymentCancelError
from gnu_jango.shop.models import ShopOrder, ShopProduct
from gnu_jango.shop.order_lines import change_order_lines
from gnu_jango.testing.factories import MemberFactory, ShopCouponFactory, ShopProductFactory, give_points
from gnu_jango.testing.shop_flows import (
    CHECKOUT_FIELDS,
    admin_status,
    assert_fully_cancelled,
    assert_order_money_consistent,
    assert_point_ledger_matches,
    assert_stock_conserved,
    balance,
    checkout,
    client_for,
    configure_shop,
    deliver,
    line_of,
    pay,
    place_bank_order,
)

pytestmark = pytest.mark.django_db

STOCK = 10
GOODS = 2 * 20000 + 10000 + 3 * 5000  # 65,000: free shipping
COUPON = 3000
POINTS = 2000
CASH = GOODS - COUPON - POINTS  # 60,000
START_POINTS = 10000


@pytest.fixture
def shop(db):
    configure_shop()
    return {
        "shirt": ShopProductFactory(it_price=20000, it_stock_qty=STOCK),
        "cap": ShopProductFactory(it_price=10000, it_stock_qty=STOCK),
        "sock": ShopProductFactory(it_price=5000, it_stock_qty=STOCK),
    }


@pytest.fixture
def buyer(db):
    member = MemberFactory()
    give_points(member, START_POINTS)
    return member


ITEMS = (("shirt", 2), ("cap", 1), ("sock", 3))


def order_fields(buyer):
    coupon = ShopCouponFactory(user=buyer, cp_price=COUPON)
    return {"cp_id": coupon.cp_id, "point_use": POINTS}, coupon


def snapshot(order, shop, buyer):
    order.refresh_from_db()
    return (
        order.od_status,
        order.od_receipt_price,
        order.od_refund_price,
        order.od_cancel_price,
        order.od_misu,
        order.od_coupon,
        tuple(order.items.order_by("pk").values_list("pk", "ct_status", "ct_qty", "stock_adjusted")),
        tuple(ShopProduct.objects.get(pk=product.pk).it_stock_qty for product in shop.values()),
        balance(buyer),
    )


def run_step(order, shop, step):
    """One admin action; returns a callable that repeats it exactly as a double submit would."""
    if step == "cancel order":
        def action():
            return admin_status(order, "취소")
    elif step == "return order":
        def action():
            return admin_status(order, "반품")
    else:
        target, product, *units = step
        line = line_of(order, shop[product])
        assert line is not None, step
        if units:
            pk, before = line.pk, line.ct_qty

            def action():
                return change_order_lines(order, [pk], target, quantities={pk: units[0]}, expected={pk: before})
        else:
            def action():
                return change_order_lines(order, [line.pk], target)
    result = action()
    assert result, f"{step}: {result.message}"
    return action


def assert_invariants(order, shop, buyer, refunded_before):
    assert_order_money_consistent(order)
    for product in shop.values():
        assert_stock_conserved(product, STOCK)
    assert_point_ledger_matches(buyer)
    assert order.od_refund_price >= refunded_before
    # cash and points out never exceed cash and points in
    points_back = balance(buyer) - (START_POINTS - POINTS)
    assert order.od_refund_price + points_back <= order.od_receipt_price + POINTS


BEFORE_SHIPPING = {
    "lines one by one": [("취소", "cap"), ("품절", "sock"), ("취소", "shirt")],
    "units then lines": [("취소", "shirt", 1), ("취소", "sock", 2), ("품절", "sock"), ("취소", "cap"), ("취소", "shirt")],
    "whole order": ["cancel order"],
    "one unit then the whole order": [("품절", "sock", 1), "cancel order"],
}
AFTER_DELIVERY = {
    "returned line by line": [("반품", "cap"), ("반품", "shirt", 1), ("반품", "sock"), ("반품", "shirt")],
    "returned whole": ["return order"],
    "one line then the whole order back": [("반품", "sock", 2), "return order"],
}


def drive(order, shop, buyer, steps, *, pg=None):
    for step in steps:
        refunded_before = order.od_refund_price
        repeat = run_step(order, shop, step)
        after = snapshot(order, shop, buyer)
        calls = len(pg.refunds) if pg else 0
        again = repeat()
        assert not again, f"{step} was applied twice"
        assert snapshot(order, shop, buyer) == after, f"repeating {step} changed the order"
        if pg:
            assert len(pg.refunds) == calls, f"repeating {step} refunded at the PG again"
            assert pg.balance == order.od_receipt_price - order.od_refund_price
        assert_invariants(order, shop, buyer, refunded_before)


@pytest.mark.parametrize("steps", [*BEFORE_SHIPPING.values(), *AFTER_DELIVERY.values()],
                         ids=[*BEFORE_SHIPPING, *AFTER_DELIVERY])
def test_a_bank_order_closed_by_any_sequence_pays_back_exactly_what_was_paid(buyer, shop, steps):
    fields, coupon = order_fields(buyer)
    order = place_bank_order(client_for(buyer), [(shop[key], qty) for key, qty in ITEMS], **fields)
    for product in shop.values():
        assert_stock_conserved(product, STOCK)
    if steps in AFTER_DELIVERY.values():
        deliver(order)
    else:
        pay(order)
    assert (order.od_receipt_price, order.od_misu) == (CASH, 0)

    drive(order, shop, buyer, steps)

    returned = steps in AFTER_DELIVERY.values()
    assert_fully_cancelled(order, paid=CASH, status="반품" if returned else "취소")
    assert balance(buyer) == START_POINTS
    coupon.refresh_from_db()
    assert coupon.cp_used == ""
    for product in shop.values():
        assert ShopProduct.objects.get(pk=product.pk).it_stock_qty == STOCK


def test_an_unpaid_bank_order_cancelled_line_by_line_refunds_nothing_and_owes_nothing(buyer, shop):
    fields, _ = order_fields(buyer)
    order = place_bank_order(client_for(buyer), [(shop[key], qty) for key, qty in ITEMS], **fields)
    drive(order, shop, buyer, [("취소", "cap"), ("취소", "sock", 1), ("품절", "sock"), ("취소", "shirt")])
    assert_fully_cancelled(order, paid=0)
    assert balance(buyer) == START_POINTS


# Toss --------------------------------------------------------------------------------------------


class FakeTossLedger:
    """Stands in for Toss's cancel API (_toss_cancel_request): it holds the payment's balance,
    refuses a refund above it like Toss does, and answers a repeated Idempotency-Key with the first
    answer without refunding again."""

    def __init__(self, paid):
        self.balance = paid
        self.refunds = []
        self.answers = {}
        self.refuse = False

    def __call__(self, order, body, idempotency_key):
        if idempotency_key in self.answers:
            return self.answers[idempotency_key]
        if self.refuse:
            raise PaymentCancelError("토스페이먼츠 응답: 일시적인 오류")
        amount = json.loads(body).get("cancelAmount", self.balance)
        if amount > self.balance:
            raise PaymentCancelError("NOT_CANCELABLE_AMOUNT")
        self.balance -= amount
        self.refunds.append(amount)
        answer = {"status": "CANCELED" if self.balance == 0 else "PARTIAL_CANCELED", "balanceAmount": self.balance}
        self.answers[idempotency_key] = answer
        return answer


TOSS_SETTINGS = {"SHOP_TOSS_CLIENT_KEY": "test_ck_fake_client", "SHOP_TOSS_SECRET_KEY": "test_sk_fake_secret"}


def place_toss_order(buyer, shop, settings, **fields):
    for name, value in TOSS_SETTINGS.items():
        setattr(settings, name, value)
    client = client_for(buyer)
    for key, qty in ITEMS:
        client.post("/api/v1/shop/cart", {"it_id": shop[key].it_id, "ct_qty": qty}, format="json")
    prepared = client.post(
        "/api/v1/shop/payment/prepare",
        {**CHECKOUT_FIELDS, "od_settle_case": "card", "pg_service": "toss", **fields},
        format="json",
    )
    assert prepared.status_code == 200, prepared.content[:400]
    order = ShopOrder.objects.get(pk=prepared.json()["data"]["order_id"])
    payment = {
        "orderId": order.od_id, "paymentKey": "pay_fake_key_1", "method": "card", "status": "DONE",
        "totalAmount": order.od_receipt_price,
    }
    body = {"pg_service": "toss", "order_id": order.od_id, "amount": order.od_receipt_price, "payment_key": "pay_fake_key_1"}
    with patch("gnu_jango.api.shop_payments.toss_api_confirm", return_value=(payment, None)):
        for _ in range(2):  # the success page reloaded: confirmed once
            confirmed = client.post("/api/v1/shop/payment/confirm", body, format="json")
            assert confirmed.status_code == 200, confirmed.content[:400]
    order.refresh_from_db()
    return order


TOSS_SEQUENCES = {
    "lines one by one": [("취소", "cap"), ("품절", "sock"), ("취소", "shirt")],
    "units then the whole order": [("취소", "shirt", 1), ("품절", "sock", 2), "cancel order"],
    "whole order": ["cancel order"],
}


@pytest.mark.parametrize("steps", TOSS_SEQUENCES.values(), ids=list(TOSS_SEQUENCES))
def test_toss_refunds_add_up_to_the_payment_and_never_repeat(buyer, shop, settings, steps):
    fields, coupon = order_fields(buyer)
    order = place_toss_order(buyer, shop, settings, **fields)
    assert (order.od_status, order.od_receipt_price, order.od_tno) == ("입금", CASH, "pay_fake_key_1")
    toss = FakeTossLedger(order.od_receipt_price)

    with patch("gnu_jango.api.shop_payments._toss_cancel_request", side_effect=toss):
        drive(order, shop, buyer, steps, pg=toss)

    assert toss.balance == 0
    assert sum(toss.refunds) == order.od_refund_price == CASH
    assert_fully_cancelled(order, paid=CASH)
    assert balance(buyer) == START_POINTS
    coupon.refresh_from_db()
    assert coupon.cp_used == ""


@pytest.mark.parametrize("step", [("취소", "cap"), ("취소", "shirt", 1), "cancel order"], ids=["line", "units", "order"])
def test_a_refund_toss_refuses_changes_nothing(buyer, shop, settings, step):
    fields, _ = order_fields(buyer)
    order = place_toss_order(buyer, shop, settings, **fields)
    toss = FakeTossLedger(order.od_receipt_price)
    toss.refuse = True
    before = snapshot(order, shop, buyer)

    with patch("gnu_jango.api.shop_payments._toss_cancel_request", side_effect=toss):
        if step == "cancel order":
            result = admin_status(order, "취소")
        else:
            target, product, *units = step
            line = line_of(order, shop[product])
            quantities = {line.pk: units[0]} if units else None
            result = change_order_lines(order, [line.pk], target, quantities=quantities)

    assert not result
    assert snapshot(order, shop, buyer) == before
    assert order.items.count() == 3  # a split made for the refused change is rolled back
    assert toss.refunds == []


def test_a_toss_refund_that_succeeds_while_the_local_change_fails_is_still_recorded(buyer, shop, settings):
    fields, _ = order_fields(buyer)
    order = place_toss_order(buyer, shop, settings, **fields)
    toss = FakeTossLedger(order.od_receipt_price)
    stock_before = snapshot(order, shop, buyer)[7]

    with patch("gnu_jango.api.shop_payments._toss_cancel_request", side_effect=toss), patch(
        "gnu_jango.shop.order_lines._apply_plan", side_effect=RuntimeError("database went away")
    ):
        result = change_order_lines(order, [line_of(order, shop["cap"]).pk], "취소")

    assert not result
    assert "환불은 주문에 기록했으니" in result.message
    order.refresh_from_db()
    # the money left: the order says so, so a retry can never refund the same 10,000 again
    assert toss.refunds == [10000]
    assert order.od_refund_price == 10000 == order.od_receipt_price - toss.balance
    assert snapshot(order, shop, buyer)[7] == stock_before


def test_a_confirm_replayed_after_the_admin_cancel_reopens_nothing(buyer, shop, settings):
    fields, coupon = order_fields(buyer)
    order = place_toss_order(buyer, shop, settings, **fields)
    toss = FakeTossLedger(order.od_receipt_price)
    with patch("gnu_jango.api.shop_payments._toss_cancel_request", side_effect=toss):
        assert admin_status(order, "취소")
    closed = snapshot(order, shop, buyer)

    payment = {"orderId": order.od_id, "paymentKey": "pay_fake_key_1", "method": "card", "status": "DONE",
               "totalAmount": order.od_receipt_price}
    body = {"pg_service": "toss", "order_id": order.od_id, "amount": order.od_receipt_price, "payment_key": "pay_fake_key_1"}
    with patch("gnu_jango.api.shop_payments.toss_api_confirm", return_value=(payment, None)) as confirm:
        response = client_for(buyer).post("/api/v1/shop/payment/confirm", body, format="json")

    assert response.status_code == 409
    confirm.assert_not_called()
    assert snapshot(order, shop, buyer) == closed
    coupon.refresh_from_db()
    assert coupon.cp_used == ""  # the confirm did not mark the released coupon used again
    assert_fully_cancelled(order, paid=CASH)


# status moves and stock ----------------------------------------------------------------------


def test_recording_the_deposit_twice_records_it_once(buyer, shop):
    order = place_bank_order(client_for(buyer), [(shop["cap"], 1)])
    assert pay(order)
    again = admin_status(order, "입금")
    assert not again
    order.refresh_from_db()
    assert (order.od_receipt_price, order.od_misu) == (10000 + 3000, 0)
    assert_order_money_consistent(order)


@pytest.mark.parametrize("status", ["주문", "입금", "준비"])
def test_cancelling_an_order_twice_restores_stock_once(buyer, shop, status):
    order = place_bank_order(client_for(buyer), [(shop["shirt"], 3), (shop["cap"], 2)])
    for step in ("입금", "준비")[: ("주문", "입금", "준비").index(status)]:
        assert admin_status(order, step)
    assert_stock_conserved(shop["shirt"], STOCK)

    assert admin_status(order, "취소")
    assert not admin_status(order, "취소")
    assert not admin_status(order, "입금")  # a cancelled order is never reopened

    for product, qty in (("shirt", 3), ("cap", 2)):
        assert ShopProduct.objects.get(pk=shop[product].pk).it_stock_qty == STOCK
    assert_fully_cancelled(order, paid=order.od_receipt_price)


def test_the_sold_out_flag_follows_the_stock_it_set_but_not_one_set_by_hand(buyer, shop):
    last_two = ShopProductFactory(it_price=7000, it_stock_qty=2)
    order = place_bank_order(client_for(buyer), [(last_two, 2)])
    last_two.refresh_from_db()
    assert (last_two.it_stock_qty, last_two.it_soldout) == (0, "1")
    refused = client_for(MemberFactory()).post("/api/v1/shop/cart", {"it_id": last_two.it_id, "ct_qty": 1}, format="json")
    assert (refused.status_code, refused.json()["code"]) == (400, "product_unavailable")

    # one unit back: the shop has stock again, so the automatic sold-out mark goes
    line = line_of(order, last_two)
    assert change_order_lines(order, [line.pk], "취소", quantities={line.pk: 1}, expected={line.pk: 2})
    last_two.refresh_from_db()
    assert (last_two.it_stock_qty, last_two.it_soldout) == (1, "")

    # marked sold out by hand while it still has stock: a cancel puts stock back but keeps the mark
    ShopProduct.objects.filter(pk=last_two.pk).update(it_soldout="1")
    assert admin_status(order, "취소")
    last_two.refresh_from_db()
    assert (last_two.it_stock_qty, last_two.it_soldout) == (2, "1")
    assert_stock_conserved(last_two, 2)


def test_checkout_never_takes_more_stock_than_is_left_when_another_order_got_there_first(buyer, shop):
    scarce = ShopProductFactory(it_price=7000, it_stock_qty=3)
    other = MemberFactory()
    give_points(other, 5000)
    coupon = ShopCouponFactory(user=other, cp_price=1000)
    added = client_for(other).post("/api/v1/shop/cart", {"it_id": scarce.it_id, "ct_qty": 2}, format="json")
    assert added.status_code in (200, 201)  # 3 in stock when the cart took them

    first = place_bank_order(client_for(buyer), [(scarce, 2)])  # 1 left
    late = checkout(client_for(other), [], cp_id=coupon.cp_id, point_use=5000)

    assert late.status_code in (400, 409), late.content[:300]
    assert not ShopOrder.objects.filter(user=other).exists()
    coupon.refresh_from_db()
    assert (coupon.cp_used, balance(other)) == ("", 5000)  # nothing was spent on the refused order
    assert_point_ledger_matches(other)
    assert_stock_conserved(scarce, 3)
    assert admin_status(first, "취소")
    assert ShopProduct.objects.get(pk=scarce.pk).it_stock_qty == 3


def test_the_shared_cancel_path_run_twice_gives_everything_back_once(buyer, shop):
    """The customer cancel, the expiry jobs and the admin all end in cancel_order_and_refund_benefits;
    two of them racing for one order (each passing its own checks first) give back once."""
    from gnu_jango.api.v1_shop import cancel_order_and_refund_benefits

    fields, coupon = order_fields(buyer)
    order = place_bank_order(client_for(buyer), [(shop[key], qty) for key, qty in ITEMS], **fields)
    pay(order)

    cancel_order_and_refund_benefits(order, "", refund_price=CASH)
    closed = snapshot(order, shop, buyer)
    _, restored = cancel_order_and_refund_benefits(ShopOrder.objects.get(pk=order.pk), "late job", refund_price=1)

    assert restored == 0
    assert snapshot(order, shop, buyer) == closed
    assert_fully_cancelled(order, paid=CASH)
    assert balance(buyer) == START_POINTS
    assert_point_ledger_matches(buyer)
