import hashlib
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.api.v1_shop import ORDER_STATUS_PAID, cancel_shop_order_locally, redact_payment_data
from gnu_jango.shop.models import ShopOrder, ShopOrderData
from gnu_jango.users.models import Profile


class TossVirtualAccountTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="vbankuser", password="password123")
        access = RefreshToken.for_user(self.user).access_token
        self.auth_headers = {"HTTP_AUTHORIZATION": f"Bearer {access}"}

    def create_vbank_order(self, *, order_id="ODVBANK1", status="order"):
        return ShopOrder.objects.create(
            od_id=order_id,
            user=self.user,
            od_name="Virtual account buyer",
            od_receipt_price=1000,
            od_misu=1000,
            od_status=status,
            od_settle_case="가상계좌",
            od_pg="toss",
            od_tno="pay-test-1",
            od_vbank_bank_code="20",
            od_vbank_account="12345678901234",
            od_vbank_customer_name="Virtual account buyer",
            od_vbank_due_date="2026-10-10T12:00:00+09:00",
            od_vbank_secret_hash=hashlib.sha256(b"vbank-secret").hexdigest(),
            od_vbank_status="WAITING_FOR_DEPOSIT",
        )

    @override_settings(
        SHOP_TOSS_CLIENT_KEY="test_client_key",
        SHOP_TOSS_SECRET_KEY="test_secret_key",
        SHOP_TOSS_VBANK_ENABLED=True,
    )
    @patch("gnu_jango.api.shop_payments.toss_api_confirm")
    def test_confirm_stores_virtual_account_and_keeps_order_pending(self, confirm):
        order = self.create_vbank_order()
        confirm.return_value = ({
            "orderId": order.od_id,
            "paymentKey": "pay-test-1",
            "method": "가상계좌",
            "status": "WAITING_FOR_DEPOSIT",
            "totalAmount": 1000,
            "secret": "provider-only-secret",
            "virtualAccount": {
                "bankCode": "20",
                "accountNumber": "12345678901234",
                "customerName": "Virtual account buyer",
                "dueDate": "2026-10-10T12:00:00+09:00",
            },
        }, None)

        response = self.client.post(
            "/api/v1/shop/payment/confirm",
            data=json.dumps({
                "pg_service": "toss",
                "order_id": order.od_id,
                "amount": 1000,
                "payment_key": "pay-test-1",
            }),
            content_type="application/json",
            **self.auth_headers,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["data"]
        self.assertEqual(payload["payment_status"], "WAITING_FOR_DEPOSIT")
        self.assertEqual(payload["vbank"]["account_number"], "12345678901234")
        order.refresh_from_db()
        self.assertEqual(order.od_status, "order")
        self.assertEqual(order.od_misu, 1000)
        self.assertEqual(order.od_vbank_status, "WAITING_FOR_DEPOSIT")
        self.assertEqual(order.od_vbank_secret_hash, hashlib.sha256(b"provider-only-secret").hexdigest())
        self.assertNotIn("provider-only-secret", ShopOrderData.objects.get(order=order).dt_data)

    @override_settings(
        SHOP_TOSS_CLIENT_KEY="test_client_key",
        SHOP_TOSS_SECRET_KEY="test_secret_key",
        SHOP_TOSS_VBANK_ENABLED=True,
    )
    @patch("gnu_jango.api.v1_shop.toss_api_get_payment_by_order")
    def test_deposit_webhook_uses_provider_state_and_is_idempotent(self, get_payment):
        order = self.create_vbank_order()
        get_payment.return_value = ({
            "orderId": order.od_id,
            "paymentKey": order.od_tno,
            "method": "가상계좌",
            "status": "DONE",
            "totalAmount": 1000,
        }, None)
        body = {
            "eventType": "DEPOSIT_CALLBACK",
            "data": {"orderId": order.od_id, "secret": "vbank-secret", "status": "DONE"},
        }

        first = self.client.post(
            "/api/v1/shop/payment/toss/vbank/webhook",
            data=json.dumps(body),
            content_type="application/json",
        )
        second = self.client.post(
            "/api/v1/shop/payment/toss/vbank/webhook",
            data=json.dumps(body),
            content_type="application/json",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDER_STATUS_PAID)
        self.assertEqual(order.od_misu, 0)
        self.assertEqual(order.od_vbank_status, "DONE")
        self.assertEqual(get_payment.call_count, 2)

    @override_settings(
        SHOP_TOSS_CLIENT_KEY="test_client_key",
        SHOP_TOSS_SECRET_KEY="test_secret_key",
        SHOP_TOSS_VBANK_ENABLED=True,
    )
    @patch("gnu_jango.api.v1_shop.toss_api_get_payment_by_order")
    def test_deposit_webhook_rejects_wrong_secret(self, get_payment):
        order = self.create_vbank_order()
        response = self.client.post(
            "/api/v1/shop/payment/toss/vbank/webhook",
            data=json.dumps({
                "eventType": "DEPOSIT_CALLBACK",
                "data": {"orderId": order.od_id, "secret": "wrong-secret", "status": "DONE"},
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 403)
        get_payment.assert_not_called()
        order.refresh_from_db()
        self.assertEqual(order.od_status, "order")

    @override_settings(
        SHOP_TOSS_CLIENT_KEY="test_client_key",
        SHOP_TOSS_SECRET_KEY="test_secret_key",
        SHOP_TOSS_VBANK_ENABLED=False,
    )
    def test_disabled_vbank_is_rejected_before_order_creation(self):
        response = self.client.post(
            "/api/v1/shop/payment/prepare",
            data=json.dumps({"od_settle_case": "가상계좌"}),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 503)
        self.assertFalse(ShopOrder.objects.exists())

    def test_payment_redaction_recurses_into_nested_payloads(self):
        redacted = redact_payment_data({
            "toss_payment": {"secret": "hidden", "virtualAccount": {"accountNumber": "1234"}},
            "headers": [{"Authorization": "Bearer hidden"}],
        })

        self.assertEqual(redacted["toss_payment"]["secret"], "***redacted***")
        self.assertEqual(redacted["headers"][0]["Authorization"], "***redacted***")
        self.assertEqual(redacted["toss_payment"]["virtualAccount"]["accountNumber"], "1234")

    def test_repeated_local_cancel_restores_points_only_once(self):
        order = self.create_vbank_order()
        order.od_receipt_point = 250
        order.save(update_fields=["od_receipt_point"])
        profile, _ = Profile.objects.get_or_create(user=self.user)
        profile.user_point = 2000
        profile.save(update_fields=["user_point"])

        first, _, first_error = cancel_shop_order_locally(order.od_id, "customer requested cancellation")
        second, _, second_error = cancel_shop_order_locally(order.od_id, "customer requested cancellation")

        self.assertIsNone(first_error)
        self.assertIsNone(second_error)
        self.assertEqual(first.od_status, second.od_status)
        profile.refresh_from_db()
        self.assertEqual(profile.user_point, 2250)
