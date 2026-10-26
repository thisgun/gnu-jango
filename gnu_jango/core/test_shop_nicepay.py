"""NICEPAY 인증결제 tests. No test calls NICEPAY; transport is patched and the keys are fake."""

import hashlib
import json
from unittest.mock import patch

from django.test import override_settings
from rest_framework.test import APIClient

from gnu_jango.api import shop_nicepay
from gnu_jango.core.test_shop_payments_api import (
    CONFIRM_URL,
    CONFIG_URL,
    ORDERED,
    PAID,
    PREPARE_URL,
    PaymentTestBase,
)
from gnu_jango.core.test_shop_pg_settings import NO_ENV, ShopSettingsPgAdminTests
from gnu_jango.shop import pg_settings
from gnu_jango.shop.models import ShopOrder, ShopPaymentAttempt

FAKE_NICEPAY = {
    "SHOP_PAYMENT_PROVIDER": "nicepay",
    "SHOP_NICEPAY_TEST_MID": "NICETEST01",
    "SHOP_NICEPAY_TEST_MERCHANT_KEY": "NICEMERCHANTKEY001",
    "SHOP_NICEPAY_RETURN_URL": "https://shop.example.test/api/v1/shop/payment/nicepay/return",
    "SHOP_NICEPAY_SUCCESS_URL": "https://shop.example.test/shop/payment/success",
}
MID = FAKE_NICEPAY["SHOP_NICEPAY_TEST_MID"]
MERCHANT_KEY = FAKE_NICEPAY["SHOP_NICEPAY_TEST_MERCHANT_KEY"]
APPROVAL_URL = "https://dc1-api.nicepay.co.kr/webapi/pay_process.jsp"
NET_CANCEL_URL = "https://dc1-api.nicepay.co.kr/webapi/cancel_process.jsp"


def sign(*parts):
    return hashlib.sha256("".join(str(part) for part in parts + (MERCHANT_KEY,)).encode()).hexdigest()


def auth_response(order, attempt_token, **over):
    amount = str(order.od_receipt_price)
    token = "AUTHTOKEN-FAKE-0001"
    values = {
        "AuthResultCode": "0000",
        "AuthResultMsg": "인증 성공",
        "AuthToken": token,
        "PayMethod": "CARD",
        "MID": MID,
        "Moid": order.od_id,
        "Amt": amount,
        "TxTid": "NICTESTTID0000000000000001",
        "NextAppURL": APPROVAL_URL,
        "NetCancelURL": NET_CANCEL_URL,
        "Signature": sign(token, MID, amount),
        "ReqReserved": f"gnu-nicepay:{over.pop('attempt_id', '')}:{attempt_token}",
    }
    values.update(over)
    return values


def approval_response(order, tid="NICTESTTID0000000000000001", **over):
    amount = f"{order.od_receipt_price:012d}"
    values = {
        "ResultCode": "3001",
        "ResultMsg": "카드 결제 성공",
        "MID": MID,
        "Moid": order.od_id,
        "Amt": amount,
        "TID": tid,
        "PayMethod": "CARD",
        "Signature": sign(tid, MID, amount),
    }
    values.update(over)
    return values


def cancel_response(order, amount, **over):
    text = str(amount)
    tid = over.pop("TID", order.od_tno or "NICTESTTID0000000000000001")
    values = {
        "ResultCode": "2001",
        "ResultMsg": "취소 성공",
        "MID": MID,
        "TID": tid,
        "CancelAmt": text,
        "Signature": sign(tid, MID, text),
    }
    values.update(over)
    return values


@override_settings(**FAKE_NICEPAY)
class NicepayPaymentTests(PaymentTestBase):
    def prepare_nicepay(self, **fields):
        body = {"pg_service": "nicepay", "od_settle_case": "card", **fields}
        response = self.prepare(**body)
        self.assertEqual(response.status_code, 200, response.content[:500])
        data = response.json()["data"]
        order = ShopOrder.objects.get(pk=data["order_id"])
        extra = data["pg_extra"]["nicepay"]
        attempt = ShopPaymentAttempt.objects.get(order=order)
        return order, data, extra, attempt

    def confirm_body(self, order, extra, attempt, **over):
        body = {
            "pg_service": "nicepay",
            "order_id": order.od_id,
            "amount": order.od_receipt_price,
            "attempt_token": extra["attempt_token"],
            "ReqReserved": extra["req_reserved"],
            **auth_response(order, extra["attempt_token"], attempt_id=attempt.pk),
        }
        body.update(over)
        return body

    def test_config_offers_nicepay_and_never_returns_the_merchant_key(self):
        response = self.client.get(CONFIG_URL)
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["pg_service"], "nicepay")
        self.assertTrue(data["payment_methods"]["card"])
        self.assertEqual(data["client"]["mid"], MID)
        self.assertIn("nicepay", data["providers"])
        rendered = response.content.decode()
        self.assertNotIn(MERCHANT_KEY, rendered)

    def test_prepare_creates_a_server_attempt_and_server_signature(self):
        order, data, extra, attempt = self.prepare_nicepay()
        self.assertEqual(order.od_pg, "nicepay")
        self.assertEqual(order.od_test, "1")
        self.assertEqual(extra["mid"], MID)
        self.assertEqual(attempt.amount, order.od_receipt_price)
        self.assertEqual(attempt.state, "prepared")
        expected = sign(extra["edi_date"], MID, str(order.od_receipt_price))
        self.assertEqual(extra["sign_data"], expected)
        self.assertNotIn("merchant_key", json.dumps(extra))

    def test_approval_marks_paid_once_and_verifies_response(self):
        order, data, extra, attempt = self.prepare_nicepay()
        with patch("gnu_jango.api.shop_nicepay._nicepay_post") as post:
            post.return_value = (approval_response(order), 200)
            response = self.client.post(
                CONFIRM_URL, self.confirm_body(order, extra, attempt), format="json"
            )
        self.assertEqual(response.status_code, 200, response.content[:500])
        order.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(order.od_status, PAID)
        self.assertEqual(order.od_tno, "NICTESTTID0000000000000001")
        self.assertEqual(attempt.state, "approved")
        post.assert_called_once()
        payload = post.call_args.args[1]
        self.assertEqual(payload["MID"], MID)
        self.assertEqual(payload["TID"], "NICTESTTID0000000000000001")
        self.assertEqual(
            payload["SignData"],
            sign("AUTHTOKEN-FAKE-0001", MID, str(order.od_receipt_price), payload["EdiDate"]),
        )

    def test_replayed_approval_does_not_call_nicepay_again(self):
        order, data, extra, attempt = self.prepare_nicepay()
        with patch("gnu_jango.api.shop_nicepay._nicepay_post") as post:
            post.return_value = (approval_response(order), 200)
            first = self.client.post(CONFIRM_URL, self.confirm_body(order, extra, attempt), format="json")
            second = self.client.post(CONFIRM_URL, self.confirm_body(order, extra, attempt), format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(post.call_count, 1)
        order.refresh_from_db()
        self.assertEqual(order.od_status, PAID)

    def test_mobile_return_approves_without_a_session_and_redirects(self):
        order, data, extra, attempt = self.prepare_nicepay()
        body = self.confirm_body(order, extra, attempt)
        with patch("gnu_jango.api.shop_nicepay._nicepay_post") as post:
            post.return_value = (approval_response(order), 200)
            response = APIClient().post(
                "/api/v1/shop/payment/nicepay/return", body
            )
        self.assertEqual(response.status_code, 302, response.content[:400])
        self.assertIn("payment_status=paid", response.url)
        order.refresh_from_db()
        self.assertEqual(order.od_status, PAID)

    def test_return_without_the_attempt_token_cannot_approve(self):
        order, data, extra, attempt = self.prepare_nicepay()
        body = self.confirm_body(order, extra, attempt)
        body.pop("attempt_token")
        body.pop("ReqReserved")
        with patch("gnu_jango.api.shop_nicepay._nicepay_post") as post:
            response = APIClient().post("/api/v1/shop/payment/nicepay/return", body)
        self.assertEqual(response.status_code, 302)
        self.assertIn("payment_status=error", response.url)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)
        post.assert_not_called()

    def test_tampered_auth_signature_leaves_the_order_unpaid(self):
        order, data, extra, attempt = self.prepare_nicepay()
        body = self.confirm_body(order, extra, attempt, Signature="0" * 64)
        with patch("gnu_jango.api.shop_nicepay._nicepay_post") as post:
            response = self.client.post(CONFIRM_URL, body, format="json")
        self.assertEqual(response.status_code, 400, response.content[:400])
        order.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)
        self.assertEqual(attempt.state, "failed")
        post.assert_not_called()

    def test_tampered_approval_signature_is_rejected(self):
        order, data, extra, attempt = self.prepare_nicepay()
        with patch("gnu_jango.api.shop_nicepay._nicepay_post") as post:
            post.side_effect = [
                (approval_response(order, Signature="0" * 64), 200),
                (cancel_response(order, order.od_receipt_price), 200),
            ]
            response = self.client.post(CONFIRM_URL, self.confirm_body(order, extra, attempt), format="json")
        self.assertEqual(response.status_code, 502, response.content[:400])
        order.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)
        self.assertEqual(attempt.state, "net_canceled")

    def test_approval_timeout_uses_net_cancel_and_keeps_order_unpaid(self):
        order, data, extra, attempt = self.prepare_nicepay()
        with patch("gnu_jango.api.shop_nicepay._nicepay_post") as post:
            post.side_effect = [
                shop_nicepay.NicepayTransportError("timeout", kind="timeout"),
                (cancel_response(order, order.od_receipt_price), 200),
            ]
            response = self.client.post(CONFIRM_URL, self.confirm_body(order, extra, attempt), format="json")
        self.assertEqual(response.status_code, 502, response.content[:400])
        order.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)
        self.assertEqual(attempt.state, "net_canceled")
        self.assertEqual(post.call_count, 2)

    def test_approved_but_local_save_failure_is_recoverable(self):
        order, data, extra, attempt = self.prepare_nicepay()
        with patch("gnu_jango.api.shop_nicepay._nicepay_post") as post, patch(
            "gnu_jango.api.shop_nicepay.confirm_order_payment", side_effect=RuntimeError("db down")
        ):
            post.return_value = (approval_response(order), 200)
            response = self.client.post(CONFIRM_URL, self.confirm_body(order, extra, attempt), format="json")
        self.assertEqual(response.status_code, 500)
        order.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)
        self.assertEqual(attempt.state, "approved_local_failed")
        self.assertIn("TID", attempt.provider_data)

    def test_cancel_request_has_full_and_partial_signatures(self):
        order = ShopOrder.objects.create(
            od_id="ODNICECANCEL",
            user=self.member,
            od_name="Cancel buyer",
            od_receipt_price=10000,
            od_status=PAID,
            od_settle_case="신용카드",
            od_pg="nicepay",
            od_tno="NICTESTTID0000000000000002",
        )
        with patch("gnu_jango.api.shop_nicepay._nicepay_post") as post:
            post.return_value = (cancel_response(order, 10000), 200)
            answer = shop_nicepay.nicepay_api_cancel_payment(order, "고객 요청")
        self.assertEqual(answer["ResultCode"], "2001")
        payload = post.call_args.args[1]
        self.assertEqual(payload["PartialCancelCode"], "0")
        self.assertEqual(payload["SignData"], sign(MID, "10000", payload["EdiDate"]))
        with patch("gnu_jango.api.shop_nicepay._nicepay_post") as post:
            post.return_value = (cancel_response(order, 4000, ResultCode="2211"), 200)
            shop_nicepay.nicepay_api_partial_cancel_payment(order, 4000, "부분 환불")
        self.assertEqual(post.call_args.args[1]["PartialCancelCode"], "1")

    def test_vbank_notification_requires_a_successful_lookup(self):
        order = ShopOrder.objects.create(
            od_id="ODNICEVBANK",
            user=self.member,
            od_name="VBANK buyer",
            od_receipt_price=5000,
            od_misu=5000,
            od_status=ORDERED,
            od_settle_case="가상계좌",
            od_pg="nicepay",
            od_tno="NICTESTTID0000000000000003",
            od_vbank_status="WAITING_FOR_DEPOSIT",
        )
        attempt = ShopPaymentAttempt.objects.create(
            order=order,
            od_id=order.od_id,
            provider="nicepay",
            mode="test",
            mid=MID,
            amount=5000,
            pay_method="VBANK",
            tid=order.od_tno,
            state="pending_deposit",
        )
        payload = {
            "MOID": order.od_id,
            "TID": order.od_tno,
            "MID": MID,
            "Amt": "000000005000",
            "ResultCode": "4110",
            "StateCd": "0",
            "PayMethod": "VBANK",
        }
        with patch("gnu_jango.api.shop_nicepay._lookup_transaction") as lookup:
            lookup.return_value = {"ResultCode": "0000", "Status": "0", "TID": order.od_tno}
            error = shop_nicepay.process_nicepay_vbank_notification(payload)
        self.assertIsNone(error)
        order.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(order.od_status, PAID)
        self.assertEqual(order.od_vbank_status, "DONE")
        self.assertEqual(attempt.state, "approved")

    def test_vbank_notification_with_wrong_amount_is_rejected(self):
        order = ShopOrder.objects.create(
            od_id="ODNICEVBANK2",
            user=self.member,
            od_name="VBANK buyer 2",
            od_receipt_price=5000,
            od_status=ORDERED,
            od_settle_case="가상계좌",
            od_pg="nicepay",
            od_tno="NICTESTTID0000000000000004",
        )
        ShopPaymentAttempt.objects.create(
            order=order,
            od_id=order.od_id,
            provider="nicepay",
            mode="test",
            mid=MID,
            amount=5000,
            pay_method="VBANK",
            tid=order.od_tno,
            state="pending_deposit",
        )
        error = shop_nicepay.process_nicepay_vbank_notification(
            {"MOID": order.od_id, "TID": order.od_tno, "MID": MID, "Amt": "000000000001"}
        )
        self.assertIsNotNone(error)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)

    def test_external_urls_are_limited_to_nicepay_hosts_paths_and_https(self):
        self.assertTrue(shop_nicepay.nicepay_approval_url_allowed(APPROVAL_URL))
        self.assertFalse(shop_nicepay.nicepay_approval_url_allowed("http://dc1-api.nicepay.co.kr/webapi/pay_process.jsp"))
        self.assertFalse(shop_nicepay.nicepay_approval_url_allowed("https://127.0.0.1/webapi/pay_process.jsp"))
        self.assertFalse(shop_nicepay.nicepay_approval_url_allowed("https://dc1-api.nicepay.co.kr/other"))
        self.assertTrue(shop_nicepay.nicepay_net_cancel_url_allowed(NET_CANCEL_URL))


@override_settings(**NO_ENV)
class NicepayAdminSettingsTests(ShopSettingsPgAdminTests):
    def test_nicepay_keys_are_sealed_write_only_and_selectable(self):
        response = self.save(
            cf_nicepay_test_mid=MID,
            cf_nicepay_test_merchant_key=MERCHANT_KEY,
            de_pg_service="nicepay",
        )
        self.assertEqual(response.status_code, 302)
        stored = pg_settings.stored_rows()
        self.assertEqual(stored["de_pg_service"], "nicepay")
        self.assertTrue(stored["cf_nicepay_test_merchant_key"].startswith("sv2:"))
        self.assertNotEqual(stored["cf_nicepay_test_merchant_key"], MERCHANT_KEY)
        keys = pg_settings.effective_nicepay_keys(mode="test")
        self.assertEqual(keys.mid, MID)
        self.assertEqual(keys.merchant_key, MERCHANT_KEY)
        page = self.client.get(self.url).content.decode()
        self.assertNotIn(MERCHANT_KEY, page)
        self.assertIn(MID, page)
        self.assertIn("NICEPAY 테스트 MerchantKey", page)

    def test_nicepay_merchant_key_delete_does_not_remove_the_mid(self):
        self.save(cf_nicepay_test_mid=MID, cf_nicepay_test_merchant_key=MERCHANT_KEY)
        self.assertEqual(self.save(cf_nicepay_test_merchant_key_delete="on").status_code, 302)
        stored = pg_settings.stored_rows()
        self.assertEqual(stored["cf_nicepay_test_mid"], MID)
        self.assertNotIn("cf_nicepay_test_merchant_key", stored)
