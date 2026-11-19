"""paid_amount() (one order) and received_price() / awaiting_online_payment() (a query) are the same
rule: an online-payment order still waiting for the PG has received nothing. Reports, the admin and
the customer pages read one or the other, so they must agree on every spelling an order row holds."""

import itertools

import pytest

from gnu_jango.shop.models import ShopOrder
from gnu_jango.shop.order_flow import awaiting_online_payment, paid_amount, received_price

pytestmark = pytest.mark.django_db

STATUSES = ("주문", " 주문 ", "order", "ORDER", "Pending", " ordered", "입금", "paid", "준비", "취소", "cancel")
SETTLE_CASES = ("", "bank", "무통장", " 무통장 ", "무통장입금", "BANK", "신용카드", "가상계좌", " card", "vbank")


def test_the_query_and_the_order_agree_on_what_was_received():
    cases = list(itertools.product(STATUSES, SETTLE_CASES))
    for index, (status, settle_case) in enumerate(cases):
        ShopOrder.objects.create(
            od_id=f"RCV{index:04d}", od_status=status, od_settle_case=settle_case, od_receipt_price=1000
        )

    received = dict(ShopOrder.objects.annotate(received=received_price()).values_list("od_id", "received"))
    awaiting = set(ShopOrder.objects.filter(awaiting_online_payment()).values_list("od_id", flat=True))

    mismatches = []
    for order in ShopOrder.objects.order_by("od_id"):
        expected = paid_amount(order)
        if (received[order.od_id], order.od_id in awaiting) != (expected, expected == 0):
            mismatches.append((order.od_status, order.od_settle_case, expected, received[order.od_id]))
    assert mismatches == []
