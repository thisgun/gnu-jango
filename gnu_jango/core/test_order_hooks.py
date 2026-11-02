"""Plugin hooks for orders: shop.order.placed, shop.order.status_changed and shop.order.paid.

They are sent once the change commits, so the tests run the on_commit callbacks explicitly.
"""

import pytest
from django.db import transaction

from gnu_jango.api.shop_payments import confirm_order_payment
from gnu_jango.plugins import hooks
from gnu_jango.shop.models import ShopOrder
from gnu_jango.testing.factories import MemberFactory, ShopProductFactory
from gnu_jango.testing.shop_flows import admin_status, client_for, configure_shop, deliver, pay, place_bank_order

pytestmark = pytest.mark.django_db


@pytest.fixture
def events(monkeypatch):
    """Record every order hook as (hook, od_id, old, new, source)."""
    monkeypatch.setattr(hooks, "_listeners", {})
    seen = []

    @hooks.on("shop.order.placed")
    def placed(order, **kwargs):
        seen.append(("placed", order.od_id, None, None, None))

    @hooks.on("shop.order.status_changed")
    def changed(order, old_status, new_status, source, **kwargs):
        seen.append(("status", order.od_id, old_status, new_status, source))

    @hooks.on("shop.order.paid")
    def paid(order, source, **kwargs):
        seen.append(("paid", order.od_id, None, None, source))

    return seen


@pytest.fixture
def order(db, django_capture_on_commit_callbacks):
    configure_shop()
    product = ShopProductFactory(it_price=20000, it_stock_qty=10)
    with django_capture_on_commit_callbacks(execute=True):
        return place_bank_order(client_for(MemberFactory()), [(product, 1)])


def test_placing_an_order_sends_placed(events, django_capture_on_commit_callbacks):
    configure_shop()
    product = ShopProductFactory(it_price=20000, it_stock_qty=10)

    with django_capture_on_commit_callbacks(execute=True):
        placed = place_bank_order(client_for(MemberFactory()), [(product, 1)])

    assert events == [("placed", placed.od_id, None, None, None)]


def test_an_admin_deposit_sends_status_changed_then_paid(order, events, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        pay(order)

    assert events == [
        ("status", order.od_id, "주문", "입금", "admin"),
        ("paid", order.od_id, None, None, "admin"),
    ]


def test_each_admin_step_sends_status_changed(order, events, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        deliver(order)

    assert [(old, new) for hook, _id, old, new, _source in events if hook == "status"] == [
        ("주문", "입금"),
        ("입금", "준비"),
        ("준비", "배송"),
        ("배송", "완료"),
    ]
    assert [event[0] for event in events].count("paid") == 1


def test_a_confirmed_payment_sends_paid_once(order, events, django_capture_on_commit_callbacks):
    amount = 23000
    ShopOrder.objects.filter(pk=order.pk).update(od_receipt_price=amount)

    with django_capture_on_commit_callbacks(execute=True):
        confirm_order_payment(order.pk, amount, "toss", "tx-1", {})
        confirm_order_payment(order.pk, amount, "toss", "tx-1", {})  # a repeated webhook

    assert events == [
        ("status", order.od_id, "주문", "입금", "payment"),
        ("paid", order.od_id, None, None, "payment"),
    ]


def test_a_cancellation_sends_status_changed(order, events, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        assert admin_status(order, "취소", reason="test")

    assert events == [("status", order.od_id, "주문", "취소", "cancel")]


def test_a_rolled_back_change_sends_nothing(order, events, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(RuntimeError), transaction.atomic():
            pay(order)
            raise RuntimeError("the request failed after the deposit")

    assert events == []
    order.refresh_from_db()
    assert order.od_status == "주문"
