"""NICEPAY money safety: the branches where a lost, refused, forged or late answer must leave the
order, the stock, the points and the refunds exactly as they were - or record precisely what
NICEPAY did. No test calls NICEPAY: ``_nicepay_post`` (or the HTTPS connection below it) is
patched, the keys are fake (gnu_jango/core/test_shop_nicepay.py has the happy paths)."""

import json
import socket
from unittest.mock import MagicMock, patch

import pytest

from gnu_jango.api import shop_nicepay
from gnu_jango.api.shop_payments import PaymentCancelError
from gnu_jango.core.test_shop_nicepay import (
    APPROVAL_URL,
    FAKE_NICEPAY,
    MID,
    NET_CANCEL_URL,
    approval_response,
    auth_response,
    cancel_response,
    sign,
)
from gnu_jango.shop.models import ShopOrder, ShopOrderData, ShopPaymentAttempt, ShopProduct
from gnu_jango.shop.order_lines import change_order_lines
from gnu_jango.testing.factories import (
    MemberFactory,
    ShopCouponFactory,
    ShopOrderFactory,
    ShopProductFactory,
    give_points,
)
from gnu_jango.testing.shop_flows import (
    CHECKOUT_FIELDS,
    admin_status,
    assert_fully_cancelled,
    assert_order_money_consistent,
    assert_point_ledger_matches,
    assert_stock_conserved,
    balance,
    client_for,
    configure_shop,
    line_of,
)

pytestmark = pytest.mark.django_db

POST = "gnu_jango.api.shop_nicepay._nicepay_post"
TID = "NICTESTTID0000000000000001"
STOCK = 10


@pytest.fixture
def nicepay(settings):
    for name, value in FAKE_NICEPAY.items():
        setattr(settings, name, value)
    configure_shop()


@pytest.fixture
def buyer(db):
    member = MemberFactory()
    give_points(member, 10000)
    return member


@pytest.fixture
def shop(db):
    return {
        "shirt": ShopProductFactory(it_price=20000, it_stock_qty=STOCK),
        "cap": ShopProductFactory(it_price=10000, it_stock_qty=STOCK),
    }


class Checkout:
    """A NICEPAY checkout prepared through the API: the order, the attempt and the browser fields."""

    def __init__(self, buyer, shop, *, settle_case="card", **fields):
        self.buyer = buyer
        self.client = client_for(buyer)
        for key, qty in (("shirt", 2), ("cap", 1)):
            self.client.post("/api/v1/shop/cart", {"it_id": shop[key].it_id, "ct_qty": qty}, format="json")
        response = self.client.post(
            "/api/v1/shop/payment/prepare",
            {**CHECKOUT_FIELDS, "od_settle_case": settle_case, "pg_service": "nicepay", **fields},
            format="json",
        )
        assert response.status_code == 200, response.content[:400]
        data = response.json()["data"]
        self.order = ShopOrder.objects.get(pk=data["order_id"])
        self.extra = data["pg_extra"]["nicepay"]
        self.attempt = ShopPaymentAttempt.objects.get(order=self.order)

    def auth(self, **over):
        """The authentication result the browser posts back (ReturnURL)."""
        return {
            "pg_service": "nicepay",
            "order_id": self.order.od_id,
            "amount": self.order.od_receipt_price,
            "attempt_token": self.extra["attempt_token"],
            "ReqReserved": self.extra["req_reserved"],
            **auth_response(self.order, self.extra["attempt_token"], attempt_id=self.attempt.pk, **over),
        }

    def confirm(self, answers, *, body=None, **over):
        """POST the confirmation with ``answers`` as NICEPAY's replies (see replies); returns
        (response, post mock)."""
        with patch(POST, side_effect=replies(answers)) as post:
            response = self.client.post("/api/v1/shop/payment/confirm", body or self.auth(**over), format="json")
        self.order.refresh_from_db()
        self.attempt.refresh_from_db()
        return response, post

    def approve(self):
        response, _ = self.confirm([(approval_response(self.order), 200)])
        assert response.status_code == 200, response.content[:300]
        return self.order


def replies(answers):
    """A ``_nicepay_post`` stand-in answering in turn: an exception is raised, a callable is called
    at that moment (to change the order while NICEPAY is answering), anything else is returned."""
    answers = list(answers)

    def post(*args, **kwargs):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer() if callable(answer) else answer

    return post


def net_cancel_answer(order, **over):
    amount = str(order.od_receipt_price)
    values = {"ResultCode": "2001", "TID": TID, "MID": MID, "CancelAmt": amount, "Signature": sign(TID, MID, amount)}
    values.update(over)
    return values


def assert_still_unpaid(checkout, shop):
    """Nothing was taken for good: the order waits for its payment, stock stays reserved once, the
    points spent at checkout stay spent once (they come back with the order's cancel)."""
    order = checkout.order
    order.refresh_from_db()
    assert order.od_status == "주문"
    assert order.od_tno == ""
    assert order.od_receipt_time == ""
    assert order.od_misu == order.od_receipt_price
    for product in shop.values():
        assert_stock_conserved(product, STOCK)
    assert_point_ledger_matches(checkout.buyer)


# the transport ---------------------------------------------------------------------------------


def fake_connection(*, status=200, body=b"", error=None):
    connection = MagicMock()
    response = MagicMock(status=status)
    response.read.return_value = body
    if error is not None:
        connection.getresponse.side_effect = error
    else:
        connection.getresponse.return_value = response
    return connection


TRANSPORT_CASES = {
    "a JSON answer": (dict(body=json.dumps({"ResultCode": "3001"}).encode()), {"ResultCode": "3001"}),
    "a key=value answer": (dict(body=b"ResultCode=3001&ResultMsg=ok"), {"ResultCode": "3001", "ResultMsg": "ok"}),
    "an EUC-KR answer": (dict(body='{"ResultMsg": "성공"}'.encode("euc-kr")), {"ResultMsg": "성공"}),
    "an error answer with a body is still an answer": (dict(status=400, body=b'{"ResultCode": "F100"}'), {"ResultCode": "F100"}),
    "a redirect": (dict(status=302, body=b'{"ResultCode": "3001"}'), "redirect"),
    "an empty server error": (dict(status=502, body=b""), "server"),
    "an empty client error": (dict(status=403, body=b""), "http"),
    "a blank answer is no answer": (dict(status=200, body=b"   "), "http"),
    "broken JSON is not an answer": (dict(status=500, body=b"{oops"), "server"),
    "a read timeout": (dict(error=socket.timeout("timed out")), "timeout"),
    "a dropped connection": (dict(error=ConnectionResetError("reset")), "network"),
}


@pytest.mark.parametrize("connection, expected", TRANSPORT_CASES.values(), ids=list(TRANSPORT_CASES))
def test_only_a_parsed_nicepay_answer_counts_as_an_answer(connection, expected):
    conn = fake_connection(**connection)
    with patch("gnu_jango.api.shop_nicepay.HTTPSConnection", return_value=conn) as https:
        if isinstance(expected, dict):
            parsed, status = shop_nicepay._nicepay_post(
                APPROVAL_URL, {"TID": TID}, allowed_urls=shop_nicepay.NICEPAY_APPROVAL_URLS
            )
            assert parsed == expected
            assert status == connection.get("status", 200)
        else:
            with pytest.raises(shop_nicepay.NicepayTransportError) as raised:
                shop_nicepay._nicepay_post(APPROVAL_URL, {"TID": TID}, allowed_urls=shop_nicepay.NICEPAY_APPROVAL_URLS)
            assert raised.value.kind == expected
    assert https.call_args.args[:2] == ("dc1-api.nicepay.co.kr", 443)
    method, path = conn.request.call_args.args
    assert (method, path) == ("POST", "/webapi/pay_process.jsp")
    conn.close.assert_called_once()


@pytest.mark.parametrize(
    "url, payload, kind",
    [
        ("https://evil.example.test/webapi/pay_process.jsp", {"TID": TID}, "url"),
        ("http://dc1-api.nicepay.co.kr/webapi/pay_process.jsp", {"TID": TID}, "url"),
        (APPROVAL_URL, {"CancelMsg": "환불 🙂"}, "encoding"),
    ],
    ids=["another host", "plain http", "a character EUC-KR cannot carry"],
)
def test_a_request_nicepay_must_not_receive_is_never_sent(url, payload, kind):
    with patch("gnu_jango.api.shop_nicepay.HTTPSConnection") as https:
        with pytest.raises(shop_nicepay.NicepayTransportError) as raised:
            shop_nicepay._nicepay_post(url, payload, allowed_urls=shop_nicepay.NICEPAY_APPROVAL_URLS)
    assert raised.value.kind == kind
    https.assert_not_called()


# authentication results that must not reach the approval API -----------------------------------

AUTH_CASES = {
    "authentication failed": ({"AuthResultCode": "9999", "AuthResultMsg": "사용자 취소"}, 400, "nicepay_auth_failed"),
    "no auth token": ({"AuthToken": ""}, 400, "nicepay_auth_incomplete"),
    "another MID": ({"MID": "OTHERMID01"}, 400, "nicepay_mid_mismatch"),
    "another order": ({"Moid": "SOMEOTHERORDER"}, 400, "nicepay_order_mismatch"),
    "a lower amount": ({"Amt": "100"}, 409, "nicepay_amount_mismatch"),
    "another method": ({"PayMethod": "BANK"}, 400, "nicepay_method_mismatch"),
    "a forged signature": ({"Signature": "0" * 64}, 400, "nicepay_auth_signature_invalid"),
    "an approval URL off the allow-list": ({"NextAppURL": "https://evil.example.test/pay"}, 400, "nicepay_approval_url_invalid"),
    "a net-cancel URL off the allow-list": ({"NetCancelURL": "https://evil.example.test/cancel"}, 400, "nicepay_net_cancel_url_invalid"),
}


@pytest.mark.parametrize("over, status, code", AUTH_CASES.values(), ids=list(AUTH_CASES))
def test_a_bad_authentication_result_never_calls_the_approval_api(nicepay, buyer, shop, over, status, code):
    checkout = Checkout(buyer, shop, point_use=3000)
    response, post = checkout.confirm([], **over)

    assert (response.status_code, response.json()["code"]) == (status, code)
    post.assert_not_called()
    assert checkout.attempt.state == "failed"
    assert_still_unpaid(checkout, shop)
    assert ShopOrderData.objects.filter(od_id=checkout.order.od_id, log_id__startswith="nicepay-reject").exists()
    # the failure is final: replaying the same result is refused without calling NICEPAY either
    again, post = checkout.confirm([])
    assert again.status_code == 409
    post.assert_not_called()


# approval answers that cannot be trusted -------------------------------------------------------

UNVERIFIED_APPROVALS = {
    "an empty answer": lambda order: {},
    "another MID": lambda order: approval_response(order, MID="OTHERMID01"),
    "another order": lambda order: approval_response(order, Moid="OTHERORDER"),
    "another TID": lambda order: approval_response(order, tid="NICTESTTID9999999999999999"),
    "another amount": lambda order: approval_response(order, Amt="000000000100"),
    "another method": lambda order: approval_response(order, PayMethod="BANK"),
    "a forged signature": lambda order: approval_response(order, Signature="f" * 64),
}


@pytest.mark.parametrize("answer", UNVERIFIED_APPROVALS.values(), ids=list(UNVERIFIED_APPROVALS))
def test_an_unverifiable_approval_is_net_cancelled_and_the_order_stays_unpaid(nicepay, buyer, shop, answer):
    checkout = Checkout(buyer, shop)
    response, post = checkout.confirm([(answer(checkout.order), 200), (net_cancel_answer(checkout.order), 200)])

    assert (response.status_code, response.json()["code"]) == (502, "nicepay_approval_unverified")
    assert post.call_count == 2
    net_cancel = post.call_args_list[1].args[1]
    assert (net_cancel["NetCancel"], net_cancel["TID"], net_cancel["Amt"]) == ("1", TID, str(checkout.order.od_receipt_price))
    assert checkout.attempt.state == "net_canceled"
    assert_still_unpaid(checkout, shop)


def test_a_declined_approval_fails_without_a_net_cancel(nicepay, buyer, shop):
    checkout = Checkout(buyer, shop)
    declined = approval_response(checkout.order, ResultCode="3011", ResultMsg="카드 한도 초과")
    response, post = checkout.confirm([(declined, 200)])

    assert (response.status_code, response.json()["code"]) == (400, "nicepay_payment_rejected")
    assert "한도 초과" in response.json()["message"]
    post.assert_called_once()
    assert checkout.attempt.state == "failed"
    assert_still_unpaid(checkout, shop)


def test_a_declined_approval_with_a_server_error_status_is_treated_as_unknown(nicepay, buyer, shop):
    checkout = Checkout(buyer, shop)
    declined = approval_response(checkout.order, ResultCode="9999")
    response, post = checkout.confirm([(declined, 503), (net_cancel_answer(checkout.order), 200)])

    assert response.json()["code"] == "nicepay_approval_unverified"
    assert post.call_count == 2
    assert checkout.attempt.state == "net_canceled"


NET_CANCEL_FAILURES = {
    "refused": lambda order: (net_cancel_answer(order, ResultCode="2015", ResultMsg="취소 불가"), 200),
    "another amount": lambda order: (net_cancel_answer(order, CancelAmt="1"), 200),
    "a forged signature": lambda order: (net_cancel_answer(order, Signature="0" * 64), 200),
    "lost too": lambda order: shop_nicepay.NicepayTransportError("timeout", kind="timeout"),
}


@pytest.mark.parametrize("failure", NET_CANCEL_FAILURES.values(), ids=list(NET_CANCEL_FAILURES))
def test_an_unconfirmed_net_cancel_leaves_the_attempt_for_review_and_blocks_a_new_payment(nicepay, buyer, shop, failure):
    checkout = Checkout(buyer, shop)
    lost = shop_nicepay.NicepayTransportError("timeout", kind="timeout")
    response, post = checkout.confirm([lost, failure(checkout.order)])

    assert (response.status_code, response.json()["code"]) == (502, "nicepay_result_unknown")
    assert post.call_count == 2
    assert checkout.attempt.state == "uncertain"
    assert checkout.attempt.recovery_attempts == 1
    assert_still_unpaid(checkout, shop)
    # the money may have moved at NICEPAY: no second payment window until this one is settled
    with pytest.raises(shop_nicepay.NicepayConfigError):
        shop_nicepay.create_nicepay_attempt(checkout.order, "CARD")


def test_a_lost_approval_without_a_net_cancel_url_is_left_for_review(nicepay, buyer, shop):
    checkout = Checkout(buyer, shop)
    lost = shop_nicepay.NicepayTransportError("timeout", kind="timeout")
    response, post = checkout.confirm([lost], NetCancelURL="")

    assert response.json()["code"] == "nicepay_result_unknown"
    post.assert_called_once()
    assert checkout.attempt.state == "uncertain"
    assert "incomplete" in checkout.attempt.last_error
    assert_still_unpaid(checkout, shop)


# races between the approval and the order ------------------------------------------------------


def approval_while(checkout, change):
    """The approval answer, with ``change`` applied to the order while NICEPAY was answering."""

    def answer(*args, **kwargs):
        change(checkout.order)
        return approval_response(checkout.order), 200

    return answer


def test_an_order_cancelled_while_the_approval_was_in_flight_is_net_cancelled(nicepay, buyer, shop):
    checkout = Checkout(buyer, shop, point_use=3000)

    def cancel(order):
        client_for(buyer).post("/api/v1/shop/payment/cancel", {"order_id": order.od_id}, format="json")

    response, post = checkout.confirm([approval_while(checkout, cancel), (net_cancel_answer(checkout.order), 200)])

    assert (response.status_code, response.json()["code"]) == (409, "order_cancelled_during_approval")
    assert post.call_count == 2
    checkout.attempt.refresh_from_db()
    assert checkout.attempt.state == "superseded"
    order = ShopOrder.objects.get(pk=checkout.order.pk)
    assert (order.od_status, order.od_tno, order.od_refund_price) == ("취소", "", 0)
    assert balance(buyer) == 10000
    for product in shop.values():
        assert ShopProduct.objects.get(pk=product.pk).it_stock_qty == STOCK


@pytest.mark.parametrize(
    "change, expected_code, net_cancelled",
    [
        (lambda order: ShopOrder.objects.filter(pk=order.pk).update(od_status="입금", od_tno="NICTESTOTHERTID000000001"),
         "nicepay_attempt_superseded", True),
        (lambda order: ShopOrder.objects.filter(pk=order.pk).update(od_tno="NICTESTOTHERTID000000001"),
         "nicepay_attempt_superseded", True),
        (lambda order: ShopOrder.objects.filter(pk=order.pk).update(od_status="배송"),
         "nicepay_attempt_superseded", True),
        (lambda order: ShopOrder.objects.filter(pk=order.pk).update(od_receipt_price=1),
         "nicepay_attempt_superseded", True),
        (lambda order: ShopOrder.objects.filter(pk=order.pk).update(od_status="입금", od_tno=TID),
         None, False),
    ],
    ids=["paid by another TID", "another TID pending", "moved on", "amount changed", "this TID recorded already"],
)
def test_a_second_approval_never_pays_an_order_twice(nicepay, buyer, shop, change, expected_code, net_cancelled):
    checkout = Checkout(buyer, shop)
    answers = [approval_while(checkout, change)]
    if net_cancelled:
        answers.append((net_cancel_answer(checkout.order), 200))
    before = ShopOrder.objects.filter(pk=checkout.order.pk).values("od_status", "od_tno", "od_receipt_price").get()
    response, post = checkout.confirm(answers)

    checkout.attempt.refresh_from_db()
    order = ShopOrder.objects.get(pk=checkout.order.pk)
    assert post.call_count == len(answers)
    if expected_code is None:
        assert response.status_code == 200, response.content[:300]
        assert checkout.attempt.state == "approved"
    else:
        assert (response.status_code, response.json()["code"]) == (409, expected_code)
        assert checkout.attempt.state == "superseded"
        # the order kept whatever the winning change wrote; this approval added nothing
        assert order.od_tno != TID
        assert order.od_receipt_time == ""
    assert before["od_tno"] == ""


def test_an_approval_for_an_order_deleted_meanwhile_is_kept_for_review(nicepay, buyer, shop):
    checkout = Checkout(buyer, shop)
    answer = approval_while(checkout, lambda order: ShopOrder.objects.filter(pk=order.pk).delete())
    with patch(POST, side_effect=replies([answer])):
        attempt, error = shop_nicepay.confirm_nicepay_payment(checkout.auth())

    assert attempt is None
    assert (error.status_code, error.data["code"]) == (409, "nicepay_order_missing")
    # the attempt outlives the order (SET_NULL) and keeps NICEPAY's answer for the admin
    stored = ShopPaymentAttempt.objects.get(pk=checkout.attempt.pk)
    assert (stored.state, stored.order_id) == ("uncertain", None)
    assert TID in stored.provider_data


@pytest.mark.parametrize("state", ["failed", "net_canceled", "canceled", "superseded", "approving", "uncertain"])
def test_a_finished_or_in_flight_attempt_is_never_approved_again(nicepay, buyer, shop, state):
    checkout = Checkout(buyer, shop)
    ShopPaymentAttempt.objects.filter(pk=checkout.attempt.pk).update(state=state)
    response, post = checkout.confirm([])

    assert (response.status_code, response.json()["code"]) == (409, f"nicepay_attempt_{state}")
    post.assert_not_called()
    assert_still_unpaid(checkout, shop)


@pytest.mark.parametrize(
    "change, code",
    [
        ({"od_status": "취소"}, "order_cancelled"),
        ({"od_status": "입금", "od_tno": "NICTESTOTHERTID000000001"}, "nicepay_attempt_superseded"),
        ({"od_tno": "NICTESTOTHERTID000000001"}, "nicepay_attempt_superseded"),
    ],
    ids=["cancelled", "paid by another TID", "another TID pending"],
)
def test_an_order_that_no_longer_waits_for_this_payment_is_not_approved(nicepay, buyer, shop, change, code):
    checkout = Checkout(buyer, shop)
    ShopOrder.objects.filter(pk=checkout.order.pk).update(**change)
    response, post = checkout.confirm([])

    assert (response.status_code, response.json()["code"]) == (409, code)
    post.assert_not_called()
    assert checkout.attempt.state in {"failed", "superseded"}


def test_an_attempt_started_with_other_keys_is_not_approved_with_the_new_ones(nicepay, buyer, shop):
    checkout = Checkout(buyer, shop)
    ShopPaymentAttempt.objects.filter(pk=checkout.attempt.pk).update(key_fingerprint="rotated-away")
    response, post = checkout.confirm([])

    assert (response.status_code, response.json()["code"]) == (503, "nicepay_payment_unconfigured")
    post.assert_not_called()
    assert checkout.attempt.state == "failed"


def test_an_unknown_attempt_token_is_not_found_and_logged(nicepay, buyer, shop):
    checkout = Checkout(buyer, shop)
    response, post = checkout.confirm([], body={**checkout.auth(), "attempt_token": "forged", "ReqReserved": ""})
    assert (response.status_code, response.json()["code"]) == (404, "nicepay_attempt_not_found")
    post.assert_not_called()


def test_a_replayed_confirmation_of_an_order_cancelled_after_payment_is_refused(nicepay, buyer, shop):
    checkout = Checkout(buyer, shop)
    checkout.approve()
    with patch(POST, return_value=(cancel_response(checkout.order, checkout.order.od_receipt_price), 200)):
        assert admin_status(checkout.order, "취소")
    checkout.attempt.refresh_from_db()
    assert checkout.attempt.state == "canceled"
    response, post = checkout.confirm([])
    assert (response.status_code, response.json()["code"]) == (409, "nicepay_attempt_canceled")
    post.assert_not_called()
    assert_fully_cancelled(checkout.order, paid=checkout.order.od_receipt_price)


# refunds -------------------------------------------------------------------------------------


class FakeNicepayLedger:
    """Stands in for NICEPAY's cancel API: checks the signature of each request, refuses a refund
    above what the payment still holds, answers with a signed response."""

    def __init__(self, paid):
        self.balance = paid
        self.refunds = []

    def __call__(self, url, payload, *, allowed_urls):
        assert url == shop_nicepay.NICEPAY_CANCEL_URL
        assert payload["SignData"] == sign(MID, payload["CancelAmt"], payload["EdiDate"])
        amount = int(payload["CancelAmt"])
        if amount > self.balance:
            return {"ResultCode": "2032", "ResultMsg": "취소금액이 취소가능금액보다 큽니다."}, 200
        self.balance -= amount
        self.refunds.append((amount, payload["PartialCancelCode"]))
        text = payload["CancelAmt"]
        return {
            "ResultCode": "2211" if payload["PartialCancelCode"] == "1" else "2001",
            "TID": payload["TID"], "MID": MID, "CancelAmt": text, "Signature": sign(payload["TID"], MID, text),
        }, 200


def test_nicepay_refunds_of_a_card_order_add_up_to_the_payment(nicepay, buyer, shop):
    coupon = ShopCouponFactory(user=buyer, cp_price=3000)
    checkout = Checkout(buyer, shop, cp_id=coupon.cp_id, point_use=2000)
    order = checkout.approve()
    paid = order.od_receipt_price
    assert paid == 50000 - 3000 - 2000
    ledger = FakeNicepayLedger(paid)

    with patch(POST, side_effect=ledger):
        shirt, cap = line_of(order, shop["shirt"]), line_of(order, shop["cap"])
        steps = [
            lambda: change_order_lines(order, [cap.pk], "취소"),
            lambda: change_order_lines(order, [shirt.pk], "취소", quantities={shirt.pk: 1}, expected={shirt.pk: 2}),
            lambda: admin_status(order, "취소"),
        ]
        for step in steps:
            assert step()
            assert_order_money_consistent(order)
            assert ledger.balance == order.od_receipt_price - order.od_refund_price
            assert not step(), "a repeated refund went through"
            assert ledger.balance == order.od_receipt_price - order.od_refund_price

    assert [code for _, code in ledger.refunds] == ["1", "1", "1"]
    assert sum(amount for amount, _ in ledger.refunds) == paid
    assert_fully_cancelled(order, paid=paid)
    assert balance(buyer) == 10000
    assert_point_ledger_matches(buyer)


def test_a_whole_nicepay_order_cancel_is_one_full_refund_and_closes_the_attempt(nicepay, buyer, shop):
    checkout = Checkout(buyer, shop)
    order = checkout.approve()
    ledger = FakeNicepayLedger(order.od_receipt_price)
    with patch(POST, side_effect=ledger):
        assert admin_status(order, "취소")
        assert not admin_status(order, "취소")

    assert ledger.refunds == [(order.od_receipt_price, "0")]
    assert_fully_cancelled(order, paid=order.od_receipt_price)
    checkout.attempt.refresh_from_db()
    assert checkout.attempt.state == "canceled"


@pytest.mark.parametrize(
    "answer",
    [
        lambda order, amount: {},
        lambda order, amount: {"ResultCode": "2013", "ResultMsg": "이미 취소된 거래"},
        lambda order, amount: cancel_response(order, amount, TID="NICTESTOTHERTID000000001"),
        lambda order, amount: cancel_response(order, amount, MID="OTHERMID01"),
        lambda order, amount: cancel_response(order, amount - 1),
        lambda order, amount: cancel_response(order, amount, Signature="0" * 64),
    ],
    ids=["empty", "refused", "another TID", "another MID", "another amount", "forged signature"],
)
def test_an_unconfirmed_nicepay_refund_changes_nothing_in_the_shop(nicepay, buyer, shop, answer):
    checkout = Checkout(buyer, shop)
    order = checkout.approve()
    before = ShopOrder.objects.filter(pk=order.pk).values().get()
    cap = line_of(order, shop["cap"])

    with patch(POST, return_value=(answer(order, 10000), 200)):
        partial = change_order_lines(order, [cap.pk], "취소")
    with patch(POST, return_value=(answer(order, order.od_receipt_price), 200)):
        full = admin_status(order, "취소")

    assert not partial and not full
    assert "결제" in partial.message and "결제" in full.message
    assert ShopOrder.objects.filter(pk=order.pk).values().get() == before
    assert line_of(order, shop["cap"]).ct_status == "입금"
    for product in shop.values():
        assert_stock_conserved(product, STOCK)
    assert ShopOrderData.objects.filter(od_id=order.od_id, log_id__startswith="nicepay-cancel-reject").exists()


def paid_nicepay_order(user, **fields):
    values = {
        "user": user, "od_status": "입금", "od_settle_case": "신용카드", "od_pg": "nicepay", "od_tno": TID,
        "od_receipt_price": 10000, "od_test": "1", **fields,
    }
    return ShopOrderFactory(**values)


@pytest.mark.parametrize(
    "lookup, partial, outcome",
    [
        ({"ResultCode": "0000", "TID": TID, "Status": "1"}, False, "already_canceled"),
        ({"ResultCode": "0000", "TID": TID, "Status": "1"}, True, "부분취소 결과가 불명확"),
        ({"ResultCode": "0000", "TID": TID, "Status": "0"}, False, "취소 결과를 확인할 수 없습니다"),
        ({"ResultCode": "3011", "ResultMsg": "조회 실패"}, False, "취소 결과를 확인할 수 없습니다"),
        ({"ResultCode": "0000", "TID": "NICTESTOTHERTID000000001", "Status": "1"}, False, "취소 결과를 확인할 수 없습니다"),
    ],
    ids=["full cancel found cancelled", "partial cancel found cancelled", "still approved", "lookup refused", "lookup of another TID"],
)
def test_a_lost_cancel_answer_is_settled_by_the_lookup_never_by_a_second_cancel(nicepay, buyer, lookup, partial, outcome):
    order = paid_nicepay_order(buyer)
    lost = shop_nicepay.NicepayTransportError("timeout", kind="timeout")
    with patch(POST, side_effect=[lost, (lookup, 200)]) as post:
        if outcome == "already_canceled":
            answer = shop_nicepay.nicepay_cancel_payment(order, "고객 요청", amount=None, partial=partial)
            assert answer["already_canceled"] is True
            assert answer["CancelAmt"] == "10000"
        else:
            with pytest.raises(PaymentCancelError) as raised:
                shop_nicepay.nicepay_cancel_payment(order, "고객 요청", amount=4000 if partial else None, partial=partial)
            assert outcome in str(raised.value)
    assert post.call_count == 2
    assert post.call_args_list[1].args[0] == shop_nicepay.NICEPAY_LOOKUP_URL
    assert ShopOrderData.objects.filter(od_id=order.od_id, log_id__startswith="nicepay-cancel-unknown").exists()


def test_an_admin_cancel_whose_answer_was_lost_but_nicepay_cancelled_records_the_refund(nicepay, buyer):
    order = paid_nicepay_order(buyer)
    lost = shop_nicepay.NicepayTransportError("timeout", kind="timeout")
    with patch(POST, side_effect=[lost, ({"ResultCode": "0000", "TID": TID, "Status": "1"}, 200)]):
        result = admin_status(order, "취소")
    assert result, result.message
    assert_fully_cancelled(order, paid=10000)


@pytest.mark.parametrize(
    "fields, kwargs, message",
    [
        ({"od_tno": ""}, {}, "거래번호가 없어"),
        ({"od_pg": "toss"}, {}, "거래번호가 없어"),
        ({"od_refund_price": 10000}, {}, "잔액"),
        ({"od_refund_price": 6000}, {"amount": 5000}, "잔액"),
        ({}, {"amount": 0}, "잔액"),
        ({"od_settle_case": "가상계좌", "od_vbank_status": "DONE"}, {}, "환불 계좌"),
        ({"od_settle_case": "가상계좌", "od_vbank_status": "DONE"},
         {"refund_account": {"account_no": "123", "bank_code": "", "holder": "홍길동"}}, "완전하지 않습니다"),
    ],
    ids=["no TID", "not a NICEPAY payment", "nothing left", "more than is left", "zero", "deposit without a refund account",
         "an incomplete refund account"],
)
def test_a_refund_nicepay_cannot_take_is_refused_before_any_request(nicepay, buyer, fields, kwargs, message):
    order = paid_nicepay_order(buyer, **fields)
    with patch(POST) as post, pytest.raises(PaymentCancelError) as raised:
        shop_nicepay.nicepay_cancel_payment(order, "환불", **kwargs)
    assert message in str(raised.value)
    post.assert_not_called()


def test_a_deposited_virtual_account_refund_carries_the_customers_account(nicepay, buyer):
    order = paid_nicepay_order(buyer, od_settle_case="가상계좌", od_vbank_status="DONE")
    with patch(POST, return_value=(cancel_response(order, 10000), 200)) as post:
        shop_nicepay.nicepay_cancel_payment(
            order, "환불", refund_account={"account_no": "1234567890123456789", "bank_code": "0040", "holder": "홍길동홍길동홍길동"}
        )
    payload = post.call_args.args[1]
    assert (payload["RefundAcctNo"], payload["RefundBankCd"], payload["RefundAcctNm"]) == (
        "1234567890123456", "004", "홍길동홍길동홍길동"[:10]
    )


def test_keys_rotated_since_the_payment_refuse_the_refund(nicepay, buyer, shop):
    checkout = Checkout(buyer, shop)
    order = checkout.approve()
    ShopPaymentAttempt.objects.filter(pk=checkout.attempt.pk).update(key_fingerprint="rotated-away")
    with patch(POST) as post:
        result = admin_status(order, "취소")
    assert not result
    assert "MID/MerchantKey" in result.message
    post.assert_not_called()
    order.refresh_from_db()
    assert order.od_status == "입금"


# virtual accounts --------------------------------------------------------------------------


def vbank_approval(order, **over):
    amount = f"{order.od_receipt_price:012d}"
    values = {
        "ResultCode": "4100", "ResultMsg": "가상계좌 발급 성공", "MID": MID, "Moid": order.od_id, "Amt": amount,
        "TID": TID, "PayMethod": "VBANK", "Signature": sign(TID, MID, amount),
        "VbankBankCode": "004", "VbankBankName": "국민은행", "VbankNum": "12345678901234",
        "VbankExpDate": "20261031", "VbankExpTime": "235959",
    }
    values.update(over)
    return values


@pytest.fixture
def vbank_checkout(nicepay, buyer, shop):
    from gnu_jango.testing.shop_flows import set_config

    set_config("de_vbank_use", "1")
    return Checkout(buyer, shop, settle_case="vbank")


def test_an_issued_virtual_account_waits_for_the_deposit_and_pays_nothing(vbank_checkout, shop):
    checkout = vbank_checkout
    assert checkout.attempt.pay_method == "VBANK"
    response, post = checkout.confirm([(vbank_approval(checkout.order), 200)], PayMethod="VBANK")

    assert response.status_code == 200, response.content[:300]
    assert response.json()["data"]["payment_status"] == "WAITING_FOR_DEPOSIT"
    order = checkout.order
    assert (order.od_status, order.od_tno, order.od_vbank_account, order.od_vbank_status) == (
        "주문", TID, "12345678901234", "WAITING_FOR_DEPOSIT"
    )
    assert order.od_misu == order.od_receipt_price
    assert order.od_vbank_due_date == "20261031235959"
    assert checkout.attempt.state == "pending_deposit"
    # replaying the return page does not issue a second account
    again, post = checkout.confirm([], PayMethod="VBANK")
    assert again.status_code == 200
    post.assert_not_called()


def test_a_virtual_account_answer_without_the_account_is_not_saved(vbank_checkout, shop):
    checkout = vbank_checkout
    answer = vbank_approval(checkout.order, VbankNum="")
    response, _ = checkout.confirm([(answer, 200)], PayMethod="VBANK")
    assert (response.status_code, response.json()["code"]) == (502, "nicepay_vbank_details_missing")
    assert_still_unpaid(checkout, shop)


@pytest.mark.parametrize("cancelled", [True, False], ids=["NICEPAY closes it", "NICEPAY refuses"])
def test_cancelling_an_unpaid_virtual_account_order_closes_the_account_first(vbank_checkout, shop, cancelled):
    checkout = vbank_checkout
    checkout.confirm([(vbank_approval(checkout.order), 200)], PayMethod="VBANK")
    order = checkout.order
    answer = cancel_response(order, order.od_receipt_price) if cancelled else {"ResultCode": "2015", "ResultMsg": "불가"}

    with patch(POST, return_value=(answer, 200)) as post:
        result = admin_status(order, "취소")

    assert post.call_args.args[1]["PartialCancelCode"] == "0"
    if cancelled:
        assert result, result.message
        assert_fully_cancelled(order, paid=0)
        assert order.od_vbank_status == "CANCELED"
        for product in shop.values():
            assert ShopProduct.objects.get(pk=product.pk).it_stock_qty == STOCK
    else:
        assert not result
        assert "가상계좌를 취소하지 못해" in result.message
        order.refresh_from_db()
        assert (order.od_status, order.od_tno, order.od_vbank_status) == ("주문", TID, "WAITING_FOR_DEPOSIT")
        for product in shop.values():
            assert_stock_conserved(product, STOCK)


# recovery against the transaction lookup ---------------------------------------------------


def uncertain_card_attempt(checkout):
    lost = shop_nicepay.NicepayTransportError("timeout", kind="timeout")
    checkout.confirm([lost, shop_nicepay.NicepayTransportError("timeout", kind="timeout")])
    assert checkout.attempt.state == "uncertain"
    return checkout.attempt


@pytest.mark.parametrize(
    "lookup, state, code",
    [
        (shop_nicepay.NicepayTransportError("down", kind="network"), "uncertain", "nicepay_lookup_failed"),
        ({"ResultCode": "9999", "ResultMsg": "조회 오류"}, "uncertain", "nicepay_lookup_failed"),
        ({"ResultCode": "0000", "TID": "NICTESTOTHERTID000000001", "Status": "0"}, "uncertain", "nicepay_lookup_failed"),
        ({"ResultCode": "0000", "TID": TID, "Status": "9"}, "failed", "nicepay_transaction_not_found"),
        ({"ResultCode": "0000", "TID": TID, "Status": "7"}, "uncertain", "nicepay_lookup_unknown"),
        ({"ResultCode": "0000", "TID": TID, "Status": "0", "Amt": "100"}, "uncertain", "nicepay_lookup_mismatch"),
        ({"ResultCode": "0000", "TID": TID, "Status": "0", "MID": "OTHERMID01"}, "uncertain", "nicepay_lookup_mismatch"),
        ({"ResultCode": "0000", "TID": TID, "Status": "0", "Moid": "OTHERORDER"}, "uncertain", "nicepay_lookup_mismatch"),
        ({"ResultCode": "0000", "TID": TID, "Status": "0", "PayMethod": "BANK"}, "uncertain", "nicepay_lookup_mismatch"),
    ],
    ids=["lookup lost", "lookup refused", "lookup of another TID", "no such payment", "unknown status",
         "another amount", "another MID", "another order", "another method"],
)
def test_recovery_pays_an_order_only_on_a_matching_approved_lookup(nicepay, buyer, shop, lookup, state, code):
    checkout = Checkout(buyer, shop)
    attempt = uncertain_card_attempt(checkout)
    answer = lookup if isinstance(lookup, Exception) else (lookup, 200)
    with patch(POST, side_effect=[answer]):
        attempt, error = shop_nicepay.recover_nicepay_attempt(attempt)

    assert error.data["code"] == code
    assert attempt.state == state
    assert_still_unpaid(checkout, shop)


def test_recovery_applies_a_matching_approved_lookup_once(nicepay, buyer, shop):
    checkout = Checkout(buyer, shop)
    attempt = uncertain_card_attempt(checkout)
    lookup = {"ResultCode": "0000", "TID": TID, "Status": "0", "Amt": str(checkout.order.od_receipt_price), "MID": MID}
    with patch(POST, return_value=(lookup, 200)):
        attempt, error = shop_nicepay.recover_nicepay_attempt(attempt)
        assert error is None
        again, error = shop_nicepay.recover_nicepay_attempt(attempt)
    assert error is None
    assert again.state == "approved"
    order = ShopOrder.objects.get(pk=checkout.order.pk)
    assert (order.od_status, order.od_tno, order.od_misu) == ("입금", TID, 0)
    assert order.od_receipt_price == 50000
    for product in shop.values():
        assert_stock_conserved(product, STOCK)


def test_recovery_of_a_net_cancelled_card_attempt_leaves_the_order_waiting(nicepay, buyer, shop):
    checkout = Checkout(buyer, shop)
    attempt = uncertain_card_attempt(checkout)
    with patch(POST, return_value=({"ResultCode": "0000", "TID": TID, "Status": "1"}, 200)):
        attempt, error = shop_nicepay.recover_nicepay_attempt(attempt)
    # the cancelled TID was never the order's payment: the order keeps waiting, nothing comes back twice
    assert error is None
    assert attempt.state == "canceled"
    assert_still_unpaid(checkout, shop)


def test_recovery_without_a_tid_cannot_look_anything_up(nicepay, buyer, shop):
    checkout = Checkout(buyer, shop)
    ShopPaymentAttempt.objects.filter(pk=checkout.attempt.pk).update(state="uncertain", tid="")
    with patch(POST) as post:
        _, error = shop_nicepay.recover_nicepay_attempt(checkout.attempt)
    assert error.data["code"] == "nicepay_tid_missing"
    post.assert_not_called()


@pytest.mark.parametrize("provider_data", ["", "{not json"], ids=["missing", "unreadable"])
def test_an_approved_but_unsaved_attempt_without_its_answer_needs_an_admin(nicepay, buyer, shop, provider_data):
    checkout = Checkout(buyer, shop)
    ShopPaymentAttempt.objects.filter(pk=checkout.attempt.pk).update(
        state="approved_local_failed", tid=TID, provider_data=provider_data
    )
    with patch(POST) as post:
        response, _ = checkout.confirm([])
    assert (response.status_code, response.json()["code"]) == (500, "nicepay_local_recovery_required")
    post.assert_not_called()
    assert_still_unpaid(checkout, shop)


# virtual account notifications --------------------------------------------------------------


@pytest.fixture
def waiting_vbank(nicepay, buyer):
    order = ShopOrderFactory(
        user=buyer, od_status="주문", od_receipt_price=5000, od_misu=5000, od_settle_case="가상계좌", od_pg="nicepay", od_tno=TID,
        od_vbank_status="WAITING_FOR_DEPOSIT", od_test="1",
    )
    attempt = ShopPaymentAttempt.objects.create(
        order=order, od_id=order.od_id, provider="nicepay", mode="test", mid=MID, amount=5000, pay_method="VBANK",
        tid=TID, state="pending_deposit",
    )
    return order, attempt


def deposit(order, **over):
    values = {"MOID": order.od_id, "TID": TID, "MID": MID, "Amt": "000000005000", "ResultCode": "4110",
              "StateCd": "0", "PayMethod": "VBANK"}
    values.update(over)
    return values


@pytest.mark.parametrize(
    "over, status, code",
    [
        ({"TID": ""}, 400, "nicepay_vbank_notification_invalid"),
        ({"MOID": "NOSUCHORDER"}, 404, "order_not_found"),
        ({"TID": "NICTESTOTHERTID000000001"}, 404, "nicepay_attempt_not_found"),
        ({"MID": "OTHERMID01"}, 409, "nicepay_vbank_notification_mismatch"),
        ({"PayMethod": "CARD"}, 409, "nicepay_vbank_notification_mismatch"),
        ({"ResultCode": "9999"}, 400, "nicepay_vbank_notification_result_invalid"),
        ({"StateCd": ""}, 409, "nicepay_vbank_not_deposited"),
    ],
    ids=["no TID", "unknown order", "unknown TID", "another MID", "not a virtual account", "unknown result",
         "deposit not completed"],
)
def test_a_notification_that_does_not_match_the_order_never_pays_it(waiting_vbank, over, status, code):
    order, _ = waiting_vbank
    with patch(POST) as post:
        error = shop_nicepay.process_nicepay_vbank_notification(deposit(order, **over))
    assert (error.status_code, error.data["code"]) == (status, code)
    post.assert_not_called()
    order.refresh_from_db()
    assert (order.od_status, order.od_misu) == ("주문", 5000)


def test_a_notification_whose_lookup_fails_asks_nicepay_to_retry(waiting_vbank):
    order, _ = waiting_vbank
    with patch(POST, side_effect=[shop_nicepay.NicepayTransportError("down", kind="network")]):
        error = shop_nicepay.process_nicepay_vbank_notification(deposit(order))
    assert (error.status_code, error.data["code"]) == (503, "nicepay_vbank_lookup_unavailable")
    order.refresh_from_db()
    assert order.od_status == "주문"


def test_a_cancel_notification_confirmed_by_the_lookup_cancels_the_waiting_order_once(waiting_vbank, buyer):
    order, attempt = waiting_vbank
    lookup = ({"ResultCode": "0000", "TID": TID, "Status": "1"}, 200)
    with patch(POST, side_effect=[lookup, lookup]):
        assert shop_nicepay.process_nicepay_vbank_notification(deposit(order, ResultCode="2001", StateCd="")) is None
        assert shop_nicepay.process_nicepay_vbank_notification(deposit(order, ResultCode="2001", StateCd="")) is None
    order.refresh_from_db()
    attempt.refresh_from_db()
    assert (order.od_status, order.od_vbank_status, order.od_refund_price) == ("취소", "CANCELED", 0)
    assert attempt.state == "canceled"


def test_a_deposit_for_an_order_cancelled_meanwhile_is_recorded_not_applied(waiting_vbank):
    order, _ = waiting_vbank
    ShopOrder.objects.filter(pk=order.pk).update(od_status="취소")
    lookup = {"ResultCode": "0000", "TID": TID, "Status": "0"}
    with patch(POST, return_value=(lookup, 200)):
        assert shop_nicepay.process_nicepay_vbank_notification(deposit(order)) is None
    order.refresh_from_db()
    assert (order.od_status, order.od_receipt_time) == ("취소", "")
    assert ShopOrderData.objects.filter(od_id=order.od_id, log_id__startswith="nicepay-vbank-late-paid").exists()


def test_a_cancel_code_notification_with_an_approved_lookup_pays_nothing(waiting_vbank):
    order, _ = waiting_vbank
    with patch(POST, return_value=({"ResultCode": "0000", "TID": TID, "Status": "0"}, 200)):
        error = shop_nicepay.process_nicepay_vbank_notification(deposit(order, ResultCode="2001"))
    assert error.data["code"] == "nicepay_vbank_not_deposited"
    order.refresh_from_db()
    assert order.od_status == "주문"


@pytest.mark.parametrize(
    "allowed, answer, status, body",
    [
        ("", None, 403, "FORBIDDEN"),
        ("127.0.0.1", ({"ResultCode": "0000", "TID": TID, "Status": "0"}, 200), 200, "OK"),
        ("127.0.0.1", shop_nicepay.NicepayTransportError("down", kind="network"), 503, "RETRY"),
        ("127.0.0.1", ({"ResultCode": "0000", "TID": TID, "Status": "0", "Amt": "100"}, 200), 409, "FAIL"),
    ],
    ids=["no allow-list", "deposit applied", "lookup down", "mismatch"],
)
def test_the_notification_endpoint_tells_nicepay_whether_to_retry(waiting_vbank, client, settings, allowed, answer, status, body):
    order, _ = waiting_vbank
    settings.DEBUG = False
    settings.SHOP_NICEPAY_VBANK_NOTIFY_ALLOWED_IPS = allowed
    with patch(POST, side_effect=[answer] if answer is not None else []):
        response = client.post("/api/v1/shop/payment/nicepay/vbank/notification", deposit(order), REMOTE_ADDR="127.0.0.1")
    assert (response.status_code, response.content.decode()) == (status, body)
    order.refresh_from_db()
    assert order.od_status == ("입금" if body == "OK" else "주문")


# recovery of virtual accounts against the lookup ----------------------------------------------

APPROVED_LOOKUP = {"ResultCode": "0000", "TID": TID, "Status": "0"}
CANCELLED_LOOKUP = {"ResultCode": "0000", "TID": TID, "Status": "1"}


@pytest.mark.parametrize(
    "order_change, lookup, state, code, order_status",
    [
        ({}, APPROVED_LOOKUP, "approved", None, "입금"),
        ({"od_status": "취소"}, APPROVED_LOOKUP, "canceled", "order_cancelled", "취소"),
        ({"od_status": "입금"}, APPROVED_LOOKUP, "approved", None, "입금"),
        ({"od_status": "입금", "od_tno": "NICTESTOTHERTID000000001"}, APPROVED_LOOKUP, "uncertain",
         "nicepay_vbank_duplicate_deposit", "입금"),
        ({"od_status": "준비"}, APPROVED_LOOKUP, "uncertain", "nicepay_order_not_payable", "준비"),
        ({"od_tno": "NICTESTOTHERTID000000001"}, APPROVED_LOOKUP, "uncertain", "nicepay_attempt_superseded", "주문"),
        ({"od_receipt_price": 6000}, APPROVED_LOOKUP, "uncertain", "payment_amount_mismatch", "주문"),
        ({}, CANCELLED_LOOKUP, "canceled", None, "취소"),
        ({"od_status": "취소"}, CANCELLED_LOOKUP, "canceled", None, "취소"),
        ({"od_status": "입금"}, CANCELLED_LOOKUP, "uncertain", "nicepay_vbank_cancel_paid_order", "입금"),
        ({"od_tno": "NICTESTOTHERTID000000001"}, CANCELLED_LOOKUP, "canceled", None, "주문"),
        ({"od_status": "준비"}, CANCELLED_LOOKUP, "uncertain", "nicepay_vbank_cancel_state", "준비"),
        ({}, {"ResultCode": "0000", "TID": TID, "Status": "9"}, "pending_deposit", None, "주문"),
    ],
    ids=[
        "deposit found", "deposit for a cancelled order", "deposit recorded already", "deposit next to another payment",
        "deposit for an order being prepared", "deposit while another TID waits", "deposit of another amount",
        "account closed", "account closed for a cancelled order", "account closed but the order is paid",
        "an old account closed", "account closed for an order being prepared", "nothing deposited yet",
    ],
)
def test_virtual_account_recovery_moves_money_only_for_the_orders_current_account(
    waiting_vbank, buyer, order_change, lookup, state, code, order_status
):
    order, attempt = waiting_vbank
    if order_change:
        ShopOrder.objects.filter(pk=order.pk).update(**order_change)
    with patch(POST, return_value=(lookup, 200)):
        attempt, error = shop_nicepay.recover_nicepay_attempt(attempt)

    assert (error.data["code"] if error else None) == code
    assert attempt.state == state
    order.refresh_from_db()
    assert order.od_status == order_status
    if order_status == "입금" and not order_change:
        assert (order.od_misu, order.od_vbank_status, order.od_tno) == (0, "DONE", TID)
    if order_status == "취소" and not order_change:
        assert (order.od_vbank_status, order.od_refund_price, order.od_misu) == ("CANCELED", 0, 0)


def test_a_failing_local_cancel_keeps_the_closed_account_for_review(waiting_vbank):
    order, attempt = waiting_vbank
    with patch(POST, return_value=(CANCELLED_LOOKUP, 200)), patch(
        "gnu_jango.api.v1_shop.cancel_order_and_refund_benefits", side_effect=RuntimeError("db down")
    ):
        attempt, error = shop_nicepay.recover_nicepay_attempt(attempt)
    assert error.data["code"] == "nicepay_vbank_cancel_failed"
    assert attempt.state == "uncertain"
    order.refresh_from_db()
    assert order.od_status == "주문"


def test_a_failing_local_deposit_keeps_the_deposit_for_review(waiting_vbank):
    order, attempt = waiting_vbank
    with patch(POST, return_value=(APPROVED_LOOKUP, 200)), patch(
        "gnu_jango.api.shop_nicepay.confirm_order_payment", side_effect=RuntimeError("db down")
    ):
        attempt, error = shop_nicepay.recover_nicepay_attempt(attempt)
    assert (error.status_code, error.data["code"]) == (500, "nicepay_local_save_failed")
    assert attempt.state == "uncertain"
    order.refresh_from_db()
    assert (order.od_status, order.od_misu) == ("주문", 5000)


def lookup_attempt(**fields):
    values = {"tid": TID, "mid": MID, "amount": 5000, "pay_method": "VBANK", **fields}
    return ShopPaymentAttempt(**values)


@pytest.mark.parametrize(
    "attempt_fields, lookup, kwargs, problem",
    [
        ({"tid": ""}, {}, {}, "has no TID"),
        ({"mid": ""}, {}, {}, "has no MID"),
        ({"amount": 0}, {}, {}, "no valid amount"),
        ({}, {"TID": TID}, {"strict_identity": True}, "MID is missing"),
        ({}, {"TID": TID, "MID": MID}, {"strict_identity": True}, "order id is missing"),
        ({}, {"TID": TID, "MID": MID, "Moid": "ORDER"}, {"strict_identity": True}, "amount is missing"),
        ({}, {"TID": TID, "MID": MID, "Moid": "ORDER", "Amt": "5000"}, {"strict_identity": True, "require_pay_method": True},
         "payment method is missing"),
        ({"pay_method": "CARD"}, {"TID": TID}, {"require_pay_method": True}, "is not a virtual account"),
        ({}, {"TID": TID, "PayMethod": "CARD"}, {"require_pay_method": True}, "not a virtual account"),
        ({}, {"TID": TID, "StateCd": "1"}, {}, "not an approved deposit"),
        ({}, {"TID": TID, "VbankStatus": "WAIT"}, {}, "not deposited"),
        ({}, {"TID": TID, "MID": MID, "Moid": "ORDER", "Amt": "5000", "PayMethod": "VBANK", "StateCd": "0",
              "VbankStatus": "입금완료"}, {"strict_identity": True, "require_pay_method": True}, ""),
    ],
    ids=["no TID", "no MID", "no amount", "strict: no MID", "strict: no order", "strict: no amount", "strict: no method",
         "not a virtual account attempt", "lookup of a card", "state not approved", "not deposited", "everything matches"],
)
def test_a_lookup_must_name_this_very_payment(attempt_fields, lookup, kwargs, problem):
    order = ShopOrder(od_id="ORDER")
    found = shop_nicepay._lookup_mismatch(lookup, lookup_attempt(**attempt_fields), order, **kwargs)
    assert (problem in found) if problem else found == ""
    assert shop_nicepay._lookup_mismatch(lookup, None, order) == "NICEPAY lookup has no local attempt."
    assert shop_nicepay._lookup_mismatch({"TID": TID}, lookup_attempt(), None) == "NICEPAY lookup has no local order."


@pytest.mark.parametrize(
    "lookup, code",
    [
        ({**APPROVED_LOOKUP, "Amt": "5000"}, None),
        ({**APPROVED_LOOKUP, "Amt": "7000"}, "nicepay_vbank_lookup_mismatch"),
        ({**APPROVED_LOOKUP, "Moid": "OTHERORDER"}, "nicepay_vbank_lookup_mismatch"),
        ({"ResultCode": "0000", "TID": TID, "Status": "9"}, "nicepay_vbank_deposit_pending"),
        ({"ResultCode": "0000", "TID": TID, "Status": "5"}, None),
    ],
    ids=["amount confirmed", "lookup reports another amount", "lookup of another order", "not reflected yet",
         "unknown state is logged only"],
)
def test_a_deposit_notification_pays_the_amount_the_lookup_confirms(waiting_vbank, lookup, code):
    order, attempt = waiting_vbank
    with patch(POST, return_value=(lookup, 200)):
        error = shop_nicepay.process_nicepay_vbank_notification(deposit(order))
    assert (error.data["code"] if error else None) == code
    order.refresh_from_db()
    paid = code is None and lookup["Status"] == "0"
    assert order.od_status == ("입금" if paid else "주문")
    assert order.od_misu == (0 if paid else 5000)


@pytest.mark.xfail(
    strict=True,
    reason="BUG: PAID_STATUSES (api/shop_common.py:40) leaves out 준비/완료, so a repeated deposit "
    "notification flips the approved attempt to uncertain (shop_nicepay.py:1761/1851) and the recovery "
    "job then net-cancels the paid order's payment (shop_nicepay.py:816 -> superseded -> _net_cancel_attempt)",
)
def test_a_repeated_deposit_notification_after_the_order_moved_on_never_refunds_it(vbank_checkout, shop):
    checkout = vbank_checkout
    checkout.confirm([(vbank_approval(checkout.order), 200)], PayMethod="VBANK")
    amount = f"{checkout.order.od_receipt_price:012d}"
    with patch(POST, return_value=(APPROVED_LOOKUP, 200)):
        assert shop_nicepay.process_nicepay_vbank_notification(deposit(checkout.order, Amt=amount)) is None
    assert admin_status(checkout.order, "준비")  # the shop starts packing the paid order

    # NICEPAY sends the same 입금통보 again (it retries until it reads OK)
    with patch(POST, return_value=(APPROVED_LOOKUP, 200)):
        repeated = shop_nicepay.process_nicepay_vbank_notification(deposit(checkout.order, Amt=amount))
    # ...and the scheduled recover_nicepay_attempts job looks at whatever is left in flight
    checkout.attempt.refresh_from_db()
    with patch(POST, side_effect=replies([(APPROVED_LOOKUP, 200), (net_cancel_answer(checkout.order), 200)])) as post:
        shop_nicepay.recover_nicepay_attempt(checkout.attempt)

    sent = [call.args[0] for call in post.call_args_list]
    assert NET_CANCEL_URL not in sent  # a paid order's payment is never net-cancelled
    assert repeated is None  # a duplicate deposit notification is a no-op
    checkout.attempt.refresh_from_db()
    assert checkout.attempt.state == "approved"
