"""cancel_pending_vbank closes an issued virtual account at the PG that issued it. Only Toss and
NICEPAY accounts can be closed from this shop; a migrated youngcart account (kcp, inicis, lg) or a
payment-adapter account is refused, and the refusal names that PG."""

from unittest.mock import patch

import pytest

from gnu_jango.api.shop_payments import cancel_pending_vbank
from gnu_jango.shop.models import ShopOrder
from gnu_jango.testing.shop_flows import admin_status

pytestmark = pytest.mark.django_db

URLOPEN = "gnu_jango.api.shop_payments.urllib_request.urlopen"
NICEPAY_POST = "gnu_jango.api.shop_nicepay._nicepay_post"


def waiting_vbank(od_pg):
    return ShopOrder.objects.create(
        od_id=f"VB-{od_pg or 'none'}",
        od_name="Buyer",
        od_status="주문",
        od_settle_case="가상계좌",
        od_pg=od_pg,
        od_tno="legacy-tno-1",
        od_receipt_price=1000,
        od_misu=1000,
        od_vbank_status="WAITING_FOR_DEPOSIT",
    )


@pytest.mark.parametrize(
    "od_pg, label",
    [("kcp", "NHN KCP"), ("inicis", "KG이니시스"), ("lg", "LG유플러스"), ("kakaopay", "카카오페이"), ("", "결제대행사")],
)
def test_an_account_this_shop_cannot_close_is_refused_in_the_name_of_its_pg(od_pg, label):
    order = waiting_vbank(od_pg)

    with patch(URLOPEN) as urlopen, patch(NICEPAY_POST) as nicepay_post:
        error = cancel_pending_vbank(order, "단순 변심")
        result = admin_status(order, "취소")

    urlopen.assert_not_called()
    nicepay_post.assert_not_called()
    assert (error.status_code, error.data["code"]) == (409, "vbank_cancel_unsupported")
    assert error.data["message"].startswith(f"{label}에서 발급한 가상계좌는")
    assert "토스" not in error.data["message"]
    assert not result
    assert result.message == error.data["message"]
    order.refresh_from_db()
    assert (order.od_status, order.od_vbank_status) == ("주문", "WAITING_FOR_DEPOSIT")


@pytest.mark.parametrize("od_pg, helper", [("toss", "cancel_pending_toss_vbank"), (" NicePay ", "cancel_pending_nicepay_vbank")])
def test_toss_and_nicepay_accounts_go_to_their_own_pg(od_pg, helper):
    order = waiting_vbank(od_pg)
    module = "gnu_jango.api.shop_nicepay" if helper.endswith("nicepay_vbank") else "gnu_jango.api.shop_payments"

    with patch(f"{module}.{helper}", return_value=None) as close:
        assert cancel_pending_vbank(order, "단순 변심") is None

    close.assert_called_once_with(order, "단순 변심")


def test_an_order_without_an_issued_account_has_nothing_to_close():
    order = waiting_vbank("kcp")
    ShopOrder.objects.filter(pk=order.pk).update(od_tno="")
    order.refresh_from_db()

    assert cancel_pending_vbank(order, "단순 변심") is None
