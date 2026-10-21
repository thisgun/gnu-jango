"""Payment flow of the shop API: config, prepare, confirm, cancel, callbacks and the Toss webhook.

No test talks to a real payment provider: the Toss and adapter calls are patched, and the keys and
secrets below are obviously fake. Assertions look at the database (order status, amounts, stock,
points, coupons, raw logs), not only at status codes.
"""

import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch
from urllib import error as urllib_error
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api import shop_payments
from gnu_jango.config.models import Config
from gnu_jango.shop.models import (
    ShopCategory,
    ShopCoupon,
    ShopCouponLog,
    ShopOrder,
    ShopOrderData,
    ShopProduct,
    ShopShippingPolicy,
)
from gnu_jango.users.models import Profile, User_Point

PREPARE_URL = "/api/v1/shop/payment/prepare"
CONFIRM_URL = "/api/v1/shop/payment/confirm"
CANCEL_URL = "/api/v1/shop/payment/cancel"
CONFIG_URL = "/api/v1/shop/payment/config"
WEBHOOK_URL = "/api/v1/shop/payment/toss/vbank/webhook"


def callback_url(provider):
    return f"/api/v1/shop/payment/callback/{provider}"


FAKE_TOSS = {
    "SHOP_TOSS_CLIENT_KEY": "test_ck_fake_client",
    "SHOP_TOSS_SECRET_KEY": "test_sk_fake_secret",
}
FAKE_TOSS_VBANK = {**FAKE_TOSS, "SHOP_TOSS_VBANK_ENABLED": True}
FAKE_ADAPTER = {
    "SHOP_PAYMENT_ADAPTER_BASE_URL": "https://adapter.invalid/verify",
    "SHOP_PAYMENT_ADAPTER_SECRET": "fake-adapter-secret",
}
CALLBACK_SECRET = "fake-callback-secret"
BANK_ACCOUNT = "Test Bank 000-00 Holder"
PRODUCT_PRICE = 100000

ORDERED = "주문"
PAID = "입금"
SHIPPING = "배송"
CANCELLED = "취소"
VBANK_CASE = "가상계좌"

ORDER_FIELDS = {
    "od_name": "Pay Member",
    "od_tel": "010-1111-2222",
    "od_hp": "010-1111-2222",
    "od_email": "pay-member@example.test",
    "od_zip": "06236",
    "od_addr1": "Seoul",
    "od_addr2": "1",
    "od_b_name": "Pay Member",
    "od_b_tel": "010-1111-2222",
    "od_b_hp": "010-1111-2222",
    "od_b_zip": "06236",
    "od_b_addr1": "Seoul",
    "od_b_addr2": "1",
}


class PaymentTestBase(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.member = user_model.objects.create_user(username="pay-member", email="pay-member@example.test", password="password")
        self.other = user_model.objects.create_user(username="pay-other", email="pay-other@example.test", password="password")
        self.profile, _ = Profile.objects.get_or_create(user=self.member)
        self.profile.user_point = 80000
        self.profile.save(update_fields=["user_point"])
        category = ShopCategory.objects.create(ca_id="40", ca_name="Payment category")
        self.product = ShopProduct.objects.create(
            it_id="PAY001", category=category, it_name="Payment product", it_price=PRODUCT_PRICE, it_stock_qty=10, it_use="1"
        )
        ShopShippingPolicy.objects.update_or_create(
            pk=1,
            # 3,000 below 50,000 (youngcart get_sendcost charges a shared fee only for 차등)
            defaults={"de_send_cost_case": "차등", "de_send_cost_limit": "50000", "de_send_cost_list": "3000", "de_delivery_company": "Courier", "de_settle_min_point": 5000, "de_settle_max_point": 50000, "de_settle_point_unit": 100},
        )
        Config.objects.update_or_create(name="de_bank_use", defaults={"value": "1"})
        Config.objects.update_or_create(name="de_bank_account", defaults={"value": BANK_ACCOUNT})
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    # helpers -----------------------------------------------------------------
    def post(self, url, body, client=None, **extra):
        return (client or self.client).post(url, body, format="json", **extra)

    def add_to_cart(self, client=None, qty=1):
        response = self.post("/api/v1/shop/cart", {"it_id": self.product.it_id, "ct_qty": qty}, client=client)
        self.assertIn(response.status_code, (200, 201), response.content[:300])

    def prepare(self, client=None, qty=1, add=True, **fields):
        if add:
            self.add_to_cart(client=client, qty=qty)
        body = {**ORDER_FIELDS, "od_settle_case": "card", "pg_service": "toss", **fields}
        return self.post(PREPARE_URL, body, client=client)

    def prepared_order(self, **fields):
        response = self.prepare(**fields)
        self.assertEqual(response.status_code, 200, response.content[:400])
        return ShopOrder.objects.get(pk=response.json()["data"]["order_id"])

    def make_coupon(self, **extra):
        values = {
            "user": self.member,
            "cp_subject": "Order coupon",
            "cp_method": 2,
            "cp_type": 0,
            "cp_price": 7000,
            "cp_minimum": 0,
            "cp_start": timezone.localdate() - timedelta(days=5),
            "cp_end": timezone.localdate() + timedelta(days=5),
        }
        values.update(extra)
        return ShopCoupon.objects.create(**values)

    def toss_payment(self, order, **over):
        payment = {
            "orderId": order.od_id,
            "paymentKey": "pay_fake_key_1",
            "method": "card",
            "status": "DONE",
            "totalAmount": order.od_receipt_price,
        }
        payment.update(over)
        return payment

    def confirm_body(self, order, **over):
        body = {"pg_service": "toss", "order_id": order.od_id, "amount": order.od_receipt_price, "payment_key": "pay_fake_key_1"}
        body.update(over)
        return body

    def confirm_toss(self, order, payment=None, error=None, client=None, **over):
        """Confirm through the API with toss_api_confirm patched; returns (response, mock)."""
        with patch("gnu_jango.api.shop_payments.toss_api_confirm") as confirm:
            confirm.return_value = (None, error) if error else (payment or self.toss_payment(order), None)
            response = self.post(CONFIRM_URL, self.confirm_body(order, **over), client=client)
        return response, confirm

    def make_vbank_order(self, *, order_id="ODPAY-VB1", status=ORDERED, **extra):
        values = {
            "od_id": order_id,
            "user": self.member,
            "od_name": "Virtual account buyer",
            "od_cart_price": 1000,
            "od_receipt_price": 1000,
            "od_misu": 1000,
            "od_status": status,
            "od_settle_case": VBANK_CASE,
            "od_pg": "toss",
            "od_tno": "pay_vb_key_1",
            "od_vbank_bank_code": "20",
            "od_vbank_account": "12345678901234",
            "od_vbank_secret_hash": hashlib.sha256(b"vbank-fake-secret").hexdigest(),
            "od_vbank_status": "WAITING_FOR_DEPOSIT",
        }
        values.update(extra)
        return ShopOrder.objects.create(**values)

    def stock(self):
        self.product.refresh_from_db()
        return self.product.it_stock_qty

    def points(self):
        self.profile.refresh_from_db()
        return self.profile.user_point

    def assertUnpaid(self, order, status=ORDERED):
        order.refresh_from_db()
        self.assertEqual(order.od_status, status)
        self.assertEqual(order.od_receipt_time, "")


# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------
class PaymentConfigTests(PaymentTestBase):
    def config(self):
        response = self.client.get(CONFIG_URL)
        self.assertEqual(response.status_code, 200)
        return response.json()["data"]

    def test_unconfigured_shop_offers_only_bank_transfer(self):
        data = self.config()

        self.assertEqual(data["pg_service"], "bank")
        self.assertEqual(data["client"]["client_key"], "")
        self.assertTrue(data["payment_methods"]["bank"])
        self.assertFalse(data["payment_methods"]["card"])
        self.assertFalse(data["payment_methods"]["vbank"])
        self.assertFalse(data["providers"]["toss"]["enabled"])
        self.assertEqual(data["bank_accounts"], [BANK_ACCOUNT])

    def test_bank_method_is_hidden_when_no_bank_account_is_configured(self):
        Config.objects.filter(name="de_bank_use").update(value="0")

        self.assertFalse(self.config()["payment_methods"]["bank"])
        self.assertEqual(self.config()["bank_accounts"], [])

    @override_settings(**FAKE_TOSS)
    def test_toss_keys_enable_card_payments_but_not_virtual_accounts(self):
        data = self.config()

        self.assertEqual(data["pg_service"], "toss")
        self.assertEqual(data["client"]["client_key"], "test_ck_fake_client")
        self.assertTrue(data["payment_methods"]["card"])
        self.assertFalse(data["payment_methods"]["vbank"])
        self.assertTrue(data["is_test_mode"])
        self.assertTrue(data["providers"]["toss"]["has_secret_key"])

    @override_settings(**FAKE_TOSS_VBANK)
    def test_virtual_accounts_need_the_vbank_flag_and_both_keys(self):
        self.assertTrue(self.config()["payment_methods"]["vbank"])

    @override_settings(SHOP_TOSS_CLIENT_KEY="test_ck_fake_client", SHOP_TOSS_SECRET_KEY="", SHOP_TOSS_VBANK_ENABLED=True)
    def test_a_client_key_without_a_secret_key_enables_nothing(self):
        data = self.config()

        self.assertEqual(data["pg_service"], "bank")
        self.assertEqual(data["client"]["client_key"], "")
        self.assertFalse(data["payment_methods"]["card"])
        self.assertFalse(data["payment_methods"]["vbank"])

    @override_settings(**FAKE_TOSS)
    def test_the_secret_key_never_appears_in_the_config_response(self):
        body = self.client.get(CONFIG_URL).content.decode("utf-8")

        self.assertNotIn("test_sk_fake_secret", body)

    @override_settings(**FAKE_ADAPTER, SHOP_PAYMENT_PROVIDER="kcp")
    def test_adapter_provider_is_reported_but_does_not_start_card_checkout(self):
        response = self.client.get(CONFIG_URL)
        data = response.json()["data"]

        self.assertEqual(data["pg_service"], "kcp")
        self.assertTrue(data["providers"]["adapter"]["enabled"])
        self.assertIn("kcp", data["providers"]["adapter"]["providers"])
        self.assertFalse(data["payment_methods"]["card"])
        self.assertNotIn("fake-adapter-secret", response.content.decode("utf-8"))

    @override_settings(**FAKE_ADAPTER, SHOP_PAYMENT_PROVIDER="kcp", SHOP_PAYMENT_ADAPTER_PROVIDERS="inicis")
    def test_a_provider_outside_the_adapter_allow_list_is_not_selected(self):
        self.assertEqual(self.config()["pg_service"], "bank")

    @override_settings(**FAKE_ADAPTER, SHOP_PAYMENT_ADAPTER_PROVIDERS="kcp|nicepay,unknown", SHOP_PAYMENT_ADAPTER_TIMEOUT=999)
    def test_adapter_config_filters_providers_and_clamps_the_timeout(self):
        config = shop_payments.payment_adapter_config()

        self.assertEqual(config["providers"], ["kcp", "nicepay"])
        self.assertEqual(config["timeout"], 30)
        self.assertTrue(shop_payments.payment_adapter_enabled("KCP"))
        self.assertFalse(shop_payments.payment_adapter_enabled("inicis"))


# ---------------------------------------------------------------------------
# prepare
# ---------------------------------------------------------------------------
class PaymentPrepareTests(PaymentTestBase):
    @override_settings(**FAKE_TOSS)
    def test_prepare_creates_a_pending_order_for_the_cart_total(self):
        response = self.prepare()

        self.assertEqual(response.status_code, 200, response.content[:400])
        data = response.json()["data"]
        order = ShopOrder.objects.get(pk=data["order_id"])
        self.assertEqual(data["amount"], PRODUCT_PRICE)
        self.assertEqual(data["pg_service"], "toss")
        self.assertEqual(data["uid"], order.uid)
        self.assertEqual(order.user, self.member)
        self.assertEqual(order.od_status, ORDERED)
        self.assertEqual(order.od_cart_price, PRODUCT_PRICE)
        self.assertEqual(order.od_send_cost + order.od_send_cost2, 0)
        self.assertEqual(order.od_receipt_price, PRODUCT_PRICE)
        self.assertEqual(order.od_misu, PRODUCT_PRICE)
        self.assertEqual(order.od_pg, "toss")
        self.assertEqual(order.od_receipt_time, "")
        self.assertEqual(self.stock(), 9)

    @override_settings(**FAKE_TOSS)
    def test_prepare_empties_the_cart_rows_it_ordered(self):
        self.prepared_order()

        cart = self.client.get("/api/v1/shop/cart").json()["data"]
        self.assertEqual(cart["items"], [])

    @override_settings(**FAKE_TOSS)
    def test_prepare_adds_shipping_below_the_free_threshold(self):
        ShopProduct.objects.filter(pk=self.product.pk).update(it_price=10000)

        data = self.prepare().json()["data"]

        order = ShopOrder.objects.get(pk=data["order_id"])
        self.assertEqual(order.od_send_cost, 3000)
        self.assertEqual(data["amount"], 13000)
        self.assertEqual(order.od_receipt_price, 13000)

    @override_settings(**FAKE_TOSS)
    def test_prepare_applies_the_order_coupon_and_points_to_the_amount(self):
        coupon = self.make_coupon()

        data = self.prepare(cp_id=coupon.cp_id, point_use=20000).json()["data"]

        order = ShopOrder.objects.get(pk=data["order_id"])
        self.assertEqual(data["amount"], PRODUCT_PRICE - 7000 - 20000)
        self.assertEqual(order.od_receipt_price, 73000)
        self.assertEqual(order.od_misu, 73000)
        self.assertEqual(order.od_coupon, 7000)
        self.assertEqual(order.od_receipt_point, 20000)
        self.assertEqual(order.coupon_logs.get().cp_price, 7000)
        self.assertEqual(self.points(), 60000)
        row = User_Point.objects.get(user=self.member, po_rel_table="@order", po_rel_action=order.od_id)
        self.assertEqual(row.po_point, -20000)

    @override_settings(**FAKE_TOSS)
    def test_prepare_caps_points_at_the_configured_maximum(self):
        data = self.prepare(point_use=70000).json()["data"]

        self.assertEqual(data["amount"], PRODUCT_PRICE - 50000)
        self.assertEqual(self.points(), 30000)

    @override_settings(**FAKE_TOSS)
    def test_prepare_ignores_another_members_coupon(self):
        coupon = self.make_coupon(user=self.other)

        data = self.prepare(cp_id=coupon.cp_id).json()["data"]

        self.assertEqual(data["amount"], PRODUCT_PRICE)
        self.assertFalse(ShopCouponLog.objects.exists())

    @override_settings(**FAKE_TOSS)
    def test_client_sent_amounts_cannot_lower_the_price(self):
        data = self.prepare(amount=1, od_receipt_price=1, od_cart_price=1, od_misu=0).json()["data"]

        order = ShopOrder.objects.get(pk=data["order_id"])
        self.assertEqual(data["amount"], PRODUCT_PRICE)
        self.assertEqual(order.od_receipt_price, PRODUCT_PRICE)

    def test_prepare_refuses_toss_when_it_is_not_configured(self):
        self.add_to_cart()
        response = self.prepare(add=False)

        self.assertEqual(response.status_code, 503)
        self.assertFalse(ShopOrder.objects.exists())
        self.assertEqual(self.stock(), 10)
        self.assertEqual(len(self.client.get("/api/v1/shop/cart").json()["data"]["items"]), 1)

    def test_prepare_refuses_a_card_order_when_nothing_is_configured(self):
        response = self.prepare(pg_service="")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ShopOrder.objects.exists())
        self.assertEqual(self.stock(), 10)

    @override_settings(**FAKE_TOSS)
    def test_prepare_refuses_a_payment_method_disabled_by_shop_settings(self):
        Config.objects.update_or_create(name="de_card_use", defaults={"value": ""})

        response = self.prepare()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "payment_method_disabled")
        self.assertFalse(ShopOrder.objects.exists())
        self.assertEqual(self.stock(), 10)

    @override_settings(**FAKE_TOSS)
    def test_prepare_refuses_an_unknown_provider(self):
        response = self.prepare(pg_service="mystery-pay")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ShopOrder.objects.exists())

    def test_prepare_refuses_an_adapter_provider_that_is_not_configured(self):
        response = self.prepare(pg_service="kcp")

        self.assertEqual(response.status_code, 503)
        self.assertFalse(ShopOrder.objects.exists())

    @override_settings(**FAKE_ADAPTER)
    def test_prepare_accepts_a_configured_adapter_provider(self):
        data = self.prepare(pg_service="kcp").json()["data"]

        self.assertEqual(data["pg_service"], "kcp")
        self.assertEqual(ShopOrder.objects.get(pk=data["order_id"]).od_status, ORDERED)

    @override_settings(**FAKE_TOSS)
    def test_prepare_refuses_virtual_account_unless_it_is_enabled(self):
        response = self.prepare(od_settle_case=VBANK_CASE)

        self.assertEqual(response.status_code, 503)
        self.assertFalse(ShopOrder.objects.exists())

    @override_settings(**FAKE_TOSS_VBANK)
    def test_prepare_refuses_virtual_account_with_another_provider(self):
        response = self.prepare(od_settle_case=VBANK_CASE, pg_service="kcp")

        self.assertEqual(response.status_code, 503)
        self.assertFalse(ShopOrder.objects.exists())

    @override_settings(**FAKE_TOSS_VBANK)
    def test_prepare_creates_a_virtual_account_order_when_enabled(self):
        data = self.prepare(od_settle_case=VBANK_CASE).json()["data"]

        order = ShopOrder.objects.get(pk=data["order_id"])
        self.assertEqual(order.od_settle_case, VBANK_CASE)
        self.assertEqual(order.od_pg, "toss")
        self.assertEqual(order.od_status, ORDERED)
        self.assertEqual(order.od_receipt_price, PRODUCT_PRICE)

    def test_prepare_bank_transfer_does_not_need_a_payment_provider(self):
        data = self.prepare(
            od_settle_case="bank", pg_service="", od_bank_account=BANK_ACCOUNT, od_deposit_name="Pay Member"
        ).json()["data"]

        order = ShopOrder.objects.get(pk=data["order_id"])
        self.assertEqual(data["pg_service"], "bank")
        self.assertEqual(order.od_bank_account, BANK_ACCOUNT)
        self.assertEqual(order.od_deposit_name, "Pay Member")

    @override_settings(**FAKE_TOSS)
    def test_prepare_refuses_bank_transfer_with_a_card_provider(self):
        response = self.prepare(od_settle_case="bank", od_bank_account=BANK_ACCOUNT, od_deposit_name="Pay Member")

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ShopOrder.objects.exists())

    def test_prepare_bank_transfer_requires_a_configured_account_and_depositor(self):
        self.add_to_cart()
        bad_account = self.prepare(add=False, od_settle_case="bank", pg_service="", od_bank_account="Elsewhere 1", od_deposit_name="x")
        no_depositor = self.prepare(add=False, od_settle_case="bank", pg_service="", od_bank_account=BANK_ACCOUNT)

        self.assertEqual(bad_account.status_code, 400)
        self.assertEqual(no_depositor.status_code, 400)
        self.assertFalse(ShopOrder.objects.exists())

    @override_settings(**FAKE_TOSS)
    def test_prepare_with_an_empty_cart_creates_nothing(self):
        response = self.prepare(add=False)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ShopOrder.objects.exists())

    @override_settings(**FAKE_TOSS)
    def test_prepare_refuses_more_than_the_stock_and_changes_nothing(self):
        self.add_to_cart(qty=3)
        ShopProduct.objects.filter(pk=self.product.pk).update(it_stock_qty=2)

        response = self.prepare(add=False)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ShopOrder.objects.exists())
        self.assertEqual(self.stock(), 2)

    @override_settings(**FAKE_TOSS)
    def test_a_failed_prepare_does_not_spend_points_or_coupons(self):
        coupon = self.make_coupon()
        self.add_to_cart(qty=3)
        ShopProduct.objects.filter(pk=self.product.pk).update(it_stock_qty=2)

        response = self.prepare(add=False, cp_id=coupon.cp_id, point_use=20000)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.points(), 80000)
        coupon.refresh_from_db()
        self.assertEqual(coupon.cp_used, "")
        self.assertFalse(ShopCouponLog.objects.exists())

    @override_settings(**FAKE_TOSS)
    def test_cash_receipt_is_refused_for_card_payments(self):
        response = self.prepare(od_cash_request=1)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ShopOrder.objects.exists())

    @override_settings(**FAKE_TOSS)
    def test_guest_prepare_requires_an_order_password(self):
        guest = APIClient()

        response = self.prepare(client=guest)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(ShopOrder.objects.exists())

    @override_settings(**FAKE_TOSS)
    def test_guest_prepare_creates_an_order_without_a_member(self):
        guest = APIClient()

        response = self.prepare(client=guest, od_pwd="guest-pass-1")

        self.assertEqual(response.status_code, 200, response.content[:300])
        order = ShopOrder.objects.get(pk=response.json()["data"]["order_id"])
        self.assertIsNone(order.user)
        self.assertEqual(order.od_receipt_price, PRODUCT_PRICE)
        self.assertEqual(order.od_receipt_point, 0)

    @override_settings(**FAKE_TOSS)
    def test_guests_cannot_use_points_or_coupons(self):
        guest = APIClient()
        coupon = self.make_coupon()

        data = self.prepare(client=guest, od_pwd="guest-pass-1", point_use=20000, cp_id=coupon.cp_id).json()["data"]

        self.assertEqual(data["amount"], PRODUCT_PRICE)
        self.assertEqual(self.points(), 80000)


# ---------------------------------------------------------------------------
# confirm (Toss)
# ---------------------------------------------------------------------------
@override_settings(**FAKE_TOSS)
class PaymentConfirmTossTests(PaymentTestBase):
    def test_confirm_marks_the_order_paid_and_records_the_payment_key(self):
        order = self.prepared_order()

        response, confirm = self.confirm_toss(order)

        self.assertEqual(response.status_code, 200, response.content[:300])
        confirm.assert_called_once_with("pay_fake_key_1", order.od_id, PRODUCT_PRICE)
        order.refresh_from_db()
        self.assertEqual(order.od_status, PAID)
        self.assertEqual(order.od_misu, 0)
        self.assertEqual(order.od_tno, "pay_fake_key_1")
        self.assertEqual(order.od_pg, "toss")
        self.assertNotEqual(order.od_receipt_time, "")
        self.assertEqual(order.od_receipt_price, PRODUCT_PRICE)
        self.assertEqual(set(order.items.values_list("ct_status", flat=True)), {PAID})
        self.assertEqual(response.json()["data"]["status"], PAID)

    def test_confirm_marks_the_orders_coupons_as_used_and_keeps_points_spent(self):
        coupon = self.make_coupon()
        order = self.prepared_order(cp_id=coupon.cp_id, point_use=20000)

        response, _ = self.confirm_toss(order)

        self.assertEqual(response.status_code, 200, response.content[:300])
        coupon.refresh_from_db()
        self.assertEqual(coupon.cp_used, "1")
        self.assertEqual(ShopCouponLog.objects.filter(order=order).count(), 1)
        self.assertEqual(self.points(), 60000)
        self.assertEqual(order.od_receipt_price, 73000)

    def test_a_replayed_confirm_does_not_double_apply_anything(self):
        coupon = self.make_coupon()
        order = self.prepared_order(cp_id=coupon.cp_id, point_use=20000)
        first, _ = self.confirm_toss(order)
        order.refresh_from_db()
        # the replay rewrites od_receipt_time, so it is only checked to stay set

        second, _ = self.confirm_toss(order)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.od_status, PAID)
        self.assertEqual(order.od_misu, 0)
        self.assertNotEqual(order.od_receipt_time, "")
        self.assertEqual(order.od_receipt_price, 73000)
        self.assertEqual(self.points(), 60000)
        self.assertEqual(User_Point.objects.filter(user=self.member).count(), 1)
        self.assertEqual(ShopCouponLog.objects.filter(order=order).count(), 1)
        self.assertEqual(self.stock(), 9)
        self.assertEqual(ShopOrder.objects.count(), 1)
        self.assertEqual(ShopOrderData.objects.filter(log_id__startswith="pay-").count(), 1)

    def test_confirm_refuses_a_lower_amount_than_the_order(self):
        order = self.prepared_order()

        response, confirm = self.confirm_toss(order, amount=1)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["errors"]["expected_amount"], PRODUCT_PRICE)
        confirm.assert_not_called()
        self.assertUnpaid(order)
        self.assertTrue(ShopOrderData.objects.filter(log_id__startswith="toss-reject").exists())

    def test_confirm_refuses_a_missing_or_garbage_amount(self):
        order = self.prepared_order()

        for amount in (None, "abc", "", -5, 0):
            with self.subTest(amount=amount):
                body = self.confirm_body(order, amount=amount)
                if amount is None:
                    del body["amount"]
                with patch("gnu_jango.api.shop_payments.toss_api_confirm") as confirm:
                    response = self.post(CONFIRM_URL, body)
                self.assertEqual(response.status_code, 409)
                confirm.assert_not_called()
                self.assertUnpaid(order)

    def test_confirm_accepts_the_amount_with_thousands_separators(self):
        order = self.prepared_order()

        response, _ = self.confirm_toss(order, amount="100,000")

        self.assertEqual(response.status_code, 200, response.content[:300])
        order.refresh_from_db()
        self.assertEqual(order.od_status, PAID)

    def test_confirm_refuses_a_payment_key_that_is_missing(self):
        order = self.prepared_order()

        with patch("gnu_jango.api.shop_payments.toss_api_confirm") as confirm:
            response = self.post(CONFIRM_URL, {"pg_service": "toss", "order_id": order.od_id, "amount": PRODUCT_PRICE})

        self.assertEqual(response.status_code, 422)
        confirm.assert_not_called()
        self.assertUnpaid(order)

    def test_confirm_refuses_when_toss_reports_another_order(self):
        order = self.prepared_order()

        response, _ = self.confirm_toss(order, payment=self.toss_payment(order, orderId="SOMEOTHERORDER"))

        self.assertEqual(response.status_code, 409)
        self.assertUnpaid(order)

    def test_confirm_refuses_when_toss_returns_no_order_id(self):
        order = self.prepared_order()

        response, _ = self.confirm_toss(order, payment={"status": "DONE", "paymentKey": "pay_fake_key_1"})

        self.assertEqual(response.status_code, 502)
        self.assertUnpaid(order)

    def test_confirm_refuses_when_toss_reports_another_payment_key(self):
        order = self.prepared_order()

        response, _ = self.confirm_toss(order, payment=self.toss_payment(order, paymentKey="pay_other_key"))

        self.assertEqual(response.status_code, 409)
        self.assertUnpaid(order)
        order.refresh_from_db()
        self.assertEqual(order.od_tno, "")

    def test_confirm_refuses_when_toss_approved_a_different_amount(self):
        order = self.prepared_order()

        response, _ = self.confirm_toss(order, payment=self.toss_payment(order, totalAmount=PRODUCT_PRICE - 1))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["errors"]["approved_amount"], PRODUCT_PRICE - 1)
        self.assertUnpaid(order)

    def test_confirm_refuses_a_payment_that_is_not_done(self):
        order = self.prepared_order()

        response, _ = self.confirm_toss(order, payment=self.toss_payment(order, status="IN_PROGRESS"))

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["errors"]["provider_status"], "IN_PROGRESS")
        self.assertUnpaid(order)

    def test_confirm_refuses_a_virtual_account_payment_for_a_card_order(self):
        order = self.prepared_order()

        response, _ = self.confirm_toss(order, payment=self.toss_payment(order, method="가상계좌", status="WAITING_FOR_DEPOSIT"))

        self.assertEqual(response.status_code, 409)
        self.assertUnpaid(order)

    def test_confirm_refuses_a_card_payment_for_a_virtual_account_order(self):
        order = self.make_vbank_order(od_tno="")

        response, _ = self.confirm_toss(order, payment=self.toss_payment(order, method="card"))

        self.assertEqual(response.status_code, 409)
        self.assertUnpaid(order)

    def test_confirm_returns_the_provider_error_and_leaves_the_order_unpaid(self):
        from gnu_jango.api.response import api_error

        order = self.prepared_order()

        response, _ = self.confirm_toss(order, error=api_error("rejected", status=400, code="toss_payment_rejected"))

        self.assertEqual(response.status_code, 400)
        self.assertUnpaid(order)
        self.assertTrue(ShopOrderData.objects.filter(log_id__startswith="toss-reject").exists())

    def test_confirm_refuses_a_cancelled_order_without_calling_toss(self):
        order = self.prepared_order()
        ShopOrder.objects.filter(pk=order.pk).update(od_status=CANCELLED)

        response, confirm = self.confirm_toss(order)

        self.assertEqual(response.status_code, 409)
        confirm.assert_not_called()
        order.refresh_from_db()
        self.assertEqual(order.od_status, CANCELLED)
        self.assertEqual(order.od_receipt_time, "")

    def test_confirm_for_an_unknown_order_is_not_found(self):
        with patch("gnu_jango.api.shop_payments.toss_api_confirm") as confirm:
            response = self.post(CONFIRM_URL, {"pg_service": "toss", "order_id": "NOSUCHORDER", "amount": 1000, "payment_key": "k"})

        self.assertEqual(response.status_code, 404)
        confirm.assert_not_called()

    def test_confirm_without_an_order_id_is_not_found(self):
        response = self.post(CONFIRM_URL, {"pg_service": "toss", "amount": 1000, "payment_key": "k"})

        self.assertEqual(response.status_code, 404)

    def test_confirm_refuses_someone_elses_order(self):
        order = self.prepared_order()
        stranger = APIClient()
        stranger.force_authenticate(user=self.other)

        response, confirm = self.confirm_toss(order, client=stranger)

        self.assertEqual(response.status_code, 404)
        confirm.assert_not_called()
        self.assertUnpaid(order)

    def test_confirm_refuses_an_anonymous_caller_for_a_member_order(self):
        order = self.prepared_order()

        response, confirm = self.confirm_toss(order, client=APIClient())

        self.assertEqual(response.status_code, 404)
        confirm.assert_not_called()
        self.assertUnpaid(order)

    def test_staff_can_confirm_a_members_order(self):
        order = self.prepared_order()
        staff = get_user_model().objects.create_user(username="pay-staff", password="password", is_staff=True)
        staff_client = APIClient()
        staff_client.force_authenticate(user=staff)

        response, _ = self.confirm_toss(order, client=staff_client)

        self.assertEqual(response.status_code, 200, response.content[:300])
        order.refresh_from_db()
        self.assertEqual(order.od_status, PAID)

    def test_a_guest_confirms_only_with_the_order_uid(self):
        guest = APIClient()
        response = self.prepare(client=guest, od_pwd="guest-pass-1")
        order = ShopOrder.objects.get(pk=response.json()["data"]["order_id"])
        stranger = APIClient()

        refused, refused_confirm = self.confirm_toss(order, client=stranger, uid="wrong-uid")
        allowed, _ = self.confirm_toss(order, client=stranger, uid=order.uid)

        self.assertEqual(refused.status_code, 404)
        refused_confirm.assert_not_called()
        self.assertEqual(allowed.status_code, 200, allowed.content[:300])
        order.refresh_from_db()
        self.assertEqual(order.od_status, PAID)

    def test_a_guest_session_may_confirm_the_order_it_created(self):
        guest = APIClient()
        response = self.prepare(client=guest, od_pwd="guest-pass-1")
        order = ShopOrder.objects.get(pk=response.json()["data"]["order_id"])

        confirmed, _ = self.confirm_toss(order, client=guest)

        self.assertEqual(confirmed.status_code, 200, confirmed.content[:300])

    def test_confirm_refuses_providers_that_cannot_verify_a_payment(self):
        order = self.prepared_order(od_settle_case="bank", pg_service="", od_bank_account=BANK_ACCOUNT, od_deposit_name="Pay Member")

        for provider in ("", "bank", "client", "card"):
            with self.subTest(provider=provider):
                response = self.post(
                    CONFIRM_URL, {"pg_service": provider, "order_id": order.od_id, "amount": order.od_receipt_price, "transaction_id": "x"}
                )
                self.assertEqual(response.status_code, 409)
                self.assertUnpaid(order)
        self.assertTrue(ShopOrderData.objects.filter(log_id__startswith="pay-reject").exists())

    def test_the_stored_payment_log_hides_provider_secrets(self):
        order = self.prepared_order()
        payment = self.toss_payment(order, secret="provider-only-secret-value")
        payment["card"] = {"number": "1234", "approveNo": "99"}

        response, _ = self.confirm_toss(order, payment=payment)

        self.assertEqual(response.status_code, 200, response.content[:300])
        log = ShopOrderData.objects.get(order=order, log_id__startswith="pay-")
        self.assertNotIn("provider-only-secret-value", log.dt_data)
        stored = json.loads(log.dt_data)
        self.assertEqual(stored["toss_payment"]["secret"], "***redacted***")
        self.assertEqual(stored["toss_payment"]["card"]["approveNo"], "99")
        self.assertEqual(log.dt_pg, "toss")
        self.assertEqual(log.od_id, order.od_id)
        self.assertEqual(log.mb_id, self.member.get_username())

    def test_a_virtual_account_confirmation_waits_for_the_deposit(self):
        order = self.make_vbank_order(od_tno="", od_vbank_status="", od_vbank_secret_hash="", od_misu=0)
        payment = self.toss_payment(
            order,
            paymentKey="pay_vb_key_1",
            method="가상계좌",
            status="WAITING_FOR_DEPOSIT",
            secret="vbank-fake-secret",
            virtualAccount={"accountNumber": "12345678901234", "bankCode": "20", "customerName": "Buyer", "dueDate": "2026-12-01T00:00:00+09:00"},
        )

        response, _ = self.confirm_toss(order, payment=payment, payment_key="pay_vb_key_1")

        self.assertEqual(response.status_code, 200, response.content[:300])
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)
        self.assertEqual(order.od_misu, 1000)
        self.assertEqual(order.od_tno, "pay_vb_key_1")
        self.assertEqual(order.od_vbank_account, "12345678901234")
        self.assertEqual(order.od_vbank_secret_hash, hashlib.sha256(b"vbank-fake-secret").hexdigest())
        self.assertEqual(order.od_receipt_time, "")

    def test_a_virtual_account_confirmation_without_details_is_refused(self):
        order = self.make_vbank_order(od_tno="", od_vbank_status="", od_vbank_secret_hash="")
        payment = self.toss_payment(order, paymentKey="pay_vb_key_1", method="가상계좌", status="WAITING_FOR_DEPOSIT")

        response, _ = self.confirm_toss(order, payment=payment, payment_key="pay_vb_key_1")

        self.assertEqual(response.status_code, 502)
        order.refresh_from_db()
        self.assertEqual(order.od_vbank_secret_hash, "")
        self.assertEqual(order.od_status, ORDERED)

    def test_a_virtual_account_confirmation_with_incomplete_details_is_refused(self):
        order = self.make_vbank_order(od_tno="", od_vbank_status="", od_vbank_secret_hash="")
        payment = self.toss_payment(
            order, paymentKey="pay_vb_key_1", method="가상계좌", status="WAITING_FOR_DEPOSIT",
            secret="s", virtualAccount={"accountNumber": "", "bankCode": "20"},
        )

        response, _ = self.confirm_toss(order, payment=payment, payment_key="pay_vb_key_1")

        self.assertEqual(response.status_code, 502)
        order.refresh_from_db()
        self.assertEqual(order.od_vbank_secret_hash, "")

    def test_a_virtual_account_cannot_be_authorized_on_a_cancelled_order(self):
        order = self.make_vbank_order(od_tno="", od_vbank_status="", od_vbank_secret_hash="")
        payment = self.toss_payment(
            order, paymentKey="pay_vb_key_1", method="가상계좌", status="WAITING_FOR_DEPOSIT",
            secret="s", virtualAccount={"accountNumber": "123", "bankCode": "20"},
        )
        # the order is cancelled between the pre-check and the provider call
        def cancel_during_call(*args, **kwargs):
            ShopOrder.objects.filter(pk=order.pk).update(od_status=CANCELLED)
            return payment, None

        with patch("gnu_jango.api.shop_payments.toss_api_confirm", side_effect=cancel_during_call):
            response = self.post(CONFIRM_URL, self.confirm_body(order, payment_key="pay_vb_key_1"))

        self.assertEqual(response.status_code, 409)
        order.refresh_from_db()
        self.assertEqual(order.od_status, CANCELLED)
        self.assertEqual(order.od_vbank_secret_hash, "")

    def test_waiting_for_deposit_is_refused_for_a_non_virtual_account_order(self):
        order = self.prepared_order()

        with patch("gnu_jango.api.shop_payments.toss_api_confirm") as confirm:
            confirm.return_value = (self.toss_payment(order, status="WAITING_FOR_DEPOSIT"), None)
            response = self.post(CONFIRM_URL, self.confirm_body(order))

        self.assertEqual(response.status_code, 409)
        self.assertUnpaid(order)


# ---------------------------------------------------------------------------
# confirm (signed adapter providers)
# ---------------------------------------------------------------------------
@override_settings(**FAKE_ADAPTER)
class PaymentConfirmAdapterTests(PaymentTestBase):
    def confirm_adapter(self, order, adapter_result, error=None, client=None, **over):
        body = {"pg_service": "kcp", "order_id": order.od_id, "amount": order.od_receipt_price, "transaction_id": "tid-fake-1"}
        body.update(over)
        with patch("gnu_jango.api.shop_payments.payment_adapter_request") as adapter:
            adapter.return_value = (None, error) if error else (adapter_result, None)
            response = self.post(CONFIRM_URL, body, client=client)
        return response, adapter

    def test_a_verified_adapter_payment_marks_the_order_paid(self):
        order = self.prepared_order(pg_service="kcp")

        response, adapter = self.confirm_adapter(
            order, {"verified": True, "order_id": order.od_id, "amount": order.od_receipt_price, "transaction_id": "tid-adapter-9"}
        )

        self.assertEqual(response.status_code, 200, response.content[:300])
        adapter.assert_called_once()
        self.assertEqual(adapter.call_args.args[:2], ("confirm", "kcp"))
        order.refresh_from_db()
        self.assertEqual(order.od_status, PAID)
        self.assertEqual(order.od_misu, 0)
        self.assertEqual(order.od_tno, "tid-adapter-9")
        self.assertEqual(order.od_pg, "kcp")

    def test_an_unverified_adapter_result_leaves_the_order_unpaid(self):
        order = self.prepared_order(pg_service="kcp")

        response, _ = self.confirm_adapter(order, {"verified": False, "status": "failed"})

        self.assertEqual(response.status_code, 422)
        self.assertUnpaid(order)
        self.assertTrue(ShopOrderData.objects.filter(log_id__startswith="adapter-reject").exists())

    def test_a_non_object_adapter_result_is_not_a_verification(self):
        order = self.prepared_order(pg_service="kcp")

        response, _ = self.confirm_adapter(order, ["verified"])

        self.assertEqual(response.status_code, 422)
        self.assertUnpaid(order)

    def test_an_adapter_error_is_returned_and_the_order_stays_unpaid(self):
        from gnu_jango.api.response import api_error

        order = self.prepared_order(pg_service="kcp")

        response, _ = self.confirm_adapter(order, None, error=api_error("down", status=502, code="payment_adapter_unavailable"))

        self.assertEqual(response.status_code, 502)
        self.assertUnpaid(order)

    def test_an_adapter_amount_that_differs_from_the_order_is_refused(self):
        order = self.prepared_order(pg_service="kcp")

        response, _ = self.confirm_adapter(order, {"verified": True, "order_id": order.od_id, "amount": 1})

        self.assertEqual(response.status_code, 409)
        self.assertUnpaid(order)

    def test_an_adapter_result_for_someone_elses_order_is_refused(self):
        mine = self.prepared_order(pg_service="kcp")
        self.add_to_cart(client=self.other_client())
        theirs = self.prepared_order_for(self.other, pg_service="kcp")

        response, _ = self.confirm_adapter(
            mine, {"verified": True, "order_id": theirs.od_id, "amount": theirs.od_receipt_price}, amount=theirs.od_receipt_price
        )

        self.assertEqual(response.status_code, 404)
        self.assertUnpaid(theirs)
        self.assertUnpaid(mine)

    def other_client(self):
        client = APIClient()
        client.force_authenticate(user=self.other)
        return client

    def prepared_order_for(self, user, **fields):
        client = APIClient()
        client.force_authenticate(user=user)
        response = self.prepare(client=client, **fields)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return ShopOrder.objects.get(pk=response.json()["data"]["order_id"])

    def test_the_adapter_log_hides_signatures_and_secrets(self):
        order = self.prepared_order(pg_service="kcp")

        response, _ = self.confirm_adapter(
            order,
            {"verified": True, "order_id": order.od_id, "amount": order.od_receipt_price, "signature": "sig-fake-value", "client_secret": "cs-fake"},
        )

        self.assertEqual(response.status_code, 200, response.content[:300])
        dt_data = ShopOrderData.objects.get(order=order, log_id__startswith="pay-").dt_data
        self.assertNotIn("sig-fake-value", dt_data)
        self.assertNotIn("cs-fake", dt_data)


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------
@override_settings(**FAKE_TOSS)
class PaymentCancelTests(PaymentTestBase):
    def cancel(self, order, client=None, **extra):
        return self.post(CANCEL_URL, {"order_id": order.od_id, **extra}, client=client)

    def test_cancel_restores_stock_points_coupon_and_cart_exactly_once(self):
        coupon = self.make_coupon()
        order = self.prepared_order(qty=2, cp_id=coupon.cp_id, point_use=20000)
        self.assertEqual(self.stock(), 8)
        self.assertEqual(self.points(), 60000)

        first = self.cancel(order)
        second = self.cancel(order)

        self.assertEqual(first.status_code, 200, first.content[:300])
        self.assertEqual(first.json()["data"]["restored_rows"], 1)
        self.assertEqual(second.status_code, 400)
        order.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(order.od_status, CANCELLED)
        self.assertEqual(order.od_receipt_price, 0)
        self.assertEqual(order.od_misu, 0)
        self.assertEqual(set(order.items.values_list("ct_status", flat=True)), {CANCELLED})
        self.assertEqual(self.stock(), 10)
        self.assertEqual(self.points(), 80000)
        self.assertEqual(User_Point.objects.filter(user=self.member, po_rel_table="@order-cancel").count(), 1)
        self.assertEqual(coupon.cp_used, "")
        self.assertFalse(ShopCouponLog.objects.filter(od_id=order.od_id).exists())
        cart = self.client.get("/api/v1/shop/cart").json()["data"]["items"]
        self.assertEqual(len(cart), 1)
        self.assertEqual(cart[0]["ct_qty"], 2)

    def test_cancel_accepts_the_od_id_field_and_a_reason(self):
        order = self.prepared_order()

        response = self.post(CANCEL_URL, {"od_id": order.od_id, "reason": "changed my mind"})

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertIn("changed my mind", order.od_memo)

    def test_cancel_without_an_order_id_is_not_found(self):
        response = self.post(CANCEL_URL, {})

        self.assertEqual(response.status_code, 404)

    def test_cancel_refuses_someone_elses_order(self):
        coupon = self.make_coupon()
        order = self.prepared_order(cp_id=coupon.cp_id, point_use=20000)
        stranger = APIClient()
        stranger.force_authenticate(user=self.other)

        response = self.cancel(order, client=stranger)

        self.assertEqual(response.status_code, 404)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)
        self.assertEqual(self.stock(), 9)
        self.assertEqual(self.points(), 60000)
        self.assertTrue(ShopCouponLog.objects.filter(od_id=order.od_id).exists())

    def test_cancel_refuses_an_anonymous_caller_for_a_member_order(self):
        order = self.prepared_order()

        response = self.cancel(order, client=APIClient())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.stock(), 9)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)

    def test_cancel_for_a_member_order_ignores_a_guessed_uid_of_another_order(self):
        # an anonymous caller who knows only a member order's uid still cannot cancel it
        order = self.prepared_order()

        response = self.cancel(order, client=APIClient(), uid=order.uid)

        self.assertEqual(response.status_code, 404)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)

    def test_a_paid_order_cannot_be_cancelled_through_the_payment_api(self):
        order = self.prepared_order(point_use=20000)
        self.confirm_toss(order)

        response = self.cancel(order)

        self.assertEqual(response.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.od_status, PAID)
        self.assertEqual(self.stock(), 9)
        self.assertEqual(self.points(), 60000)

    def test_a_guest_cancels_with_the_order_uid_and_the_cart_comes_back(self):
        guest = APIClient()
        response = self.prepare(client=guest, od_pwd="guest-pass-1")
        order = ShopOrder.objects.get(pk=response.json()["data"]["order_id"])
        stranger = APIClient()

        refused = self.cancel(order, client=stranger, uid="wrong-uid")
        allowed = self.cancel(order, client=stranger, uid=order.uid)

        self.assertEqual(refused.status_code, 404)
        self.assertEqual(allowed.status_code, 200, allowed.content[:300])
        order.refresh_from_db()
        self.assertEqual(order.od_status, CANCELLED)
        self.assertEqual(self.stock(), 10)

    def test_a_guest_session_cancels_the_order_it_created(self):
        guest = APIClient()
        response = self.prepare(client=guest, od_pwd="guest-pass-1")
        order = ShopOrder.objects.get(pk=response.json()["data"]["order_id"])

        cancelled = self.cancel(order, client=guest)
        other_guest = self.cancel(order, client=APIClient())

        self.assertEqual(cancelled.status_code, 200, cancelled.content[:300])
        self.assertEqual(other_guest.status_code, 404)
        self.assertEqual(self.stock(), 10)


@override_settings(**FAKE_TOSS_VBANK)
class PaymentCancelVirtualAccountTests(PaymentTestBase):
    def waiting_payment(self, order, **over):
        payment = {
            "orderId": order.od_id,
            "paymentKey": order.od_tno,
            "method": "가상계좌",
            "status": "WAITING_FOR_DEPOSIT",
            "totalAmount": order.od_receipt_price,
        }
        payment.update(over)
        return payment

    def provider_cancel(self, order, provider_payment, urlopen_result=None):
        """Cancel through the API with the Toss status lookup and cancel call patched."""
        with patch("gnu_jango.api.shop_payments.toss_api_get_payment_by_order") as lookup, patch(
            "gnu_jango.api.shop_payments.urllib_request.urlopen"
        ) as urlopen:
            lookup.return_value = provider_payment if isinstance(provider_payment, tuple) else (provider_payment, None)
            if isinstance(urlopen_result, Exception):
                urlopen.side_effect = urlopen_result
            else:
                body = json.dumps(urlopen_result if urlopen_result is not None else {"orderId": order.od_id, "status": "CANCELED"})
                response = MagicMock()
                response.read.return_value = body.encode("utf-8")
                urlopen.return_value.__enter__.return_value = response
            result = self.post(CANCEL_URL, {"order_id": order.od_id})
        return result, urlopen

    def vbank_order(self):
        order = self.make_vbank_order(od_cart_price=PRODUCT_PRICE, od_receipt_price=PRODUCT_PRICE, od_misu=PRODUCT_PRICE)
        return order

    def test_cancelling_a_waiting_virtual_account_cancels_it_at_toss_then_locally(self):
        order = self.vbank_order()

        response, urlopen = self.provider_cancel(order, self.waiting_payment(order))

        self.assertEqual(response.status_code, 200, response.content[:300])
        request = urlopen.call_args.args[0]
        self.assertTrue(request.full_url.endswith("/v1/payments/pay_vb_key_1/cancel"))
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))
        self.assertEqual(request.get_header("Idempotency-key"), f"vbank-cancel-{order.od_id}")
        order.refresh_from_db()
        self.assertEqual(order.od_status, CANCELLED)
        self.assertEqual(order.od_vbank_status, "CANCELED")

    def test_a_toss_failure_leaves_the_virtual_account_order_untouched(self):
        order = self.vbank_order()
        failure = urllib_error.HTTPError("https://api.invalid", 500, "boom", {}, None)
        failure.read = lambda: b"{}"

        response, _ = self.provider_cancel(order, self.waiting_payment(order), urlopen_result=failure)

        self.assertEqual(response.status_code, 502)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)
        self.assertEqual(order.od_vbank_status, "WAITING_FOR_DEPOSIT")

    def test_a_network_failure_leaves_the_virtual_account_order_untouched(self):
        order = self.vbank_order()

        response, _ = self.provider_cancel(order, self.waiting_payment(order), urlopen_result=urllib_error.URLError("offline"))

        self.assertEqual(response.status_code, 502)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)

    def test_an_unconfirmed_toss_cancellation_leaves_the_order_untouched(self):
        order = self.vbank_order()

        response, _ = self.provider_cancel(order, self.waiting_payment(order), urlopen_result={"orderId": order.od_id, "status": "WAITING_FOR_DEPOSIT"})

        self.assertEqual(response.status_code, 502)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)

    def test_a_toss_payment_that_does_not_match_blocks_the_cancellation(self):
        order = self.vbank_order()

        for override in ({"orderId": "OTHER"}, {"totalAmount": 5}, {"paymentKey": "pay_other"}, {"method": "card"}):
            with self.subTest(override=override):
                response, urlopen = self.provider_cancel(order, self.waiting_payment(order, **override))
                self.assertEqual(response.status_code, 409)
                urlopen.assert_not_called()
                order.refresh_from_db()
                self.assertEqual(order.od_status, ORDERED)

    def test_a_deposit_that_already_arrived_blocks_the_cancellation(self):
        order = self.vbank_order()

        response, urlopen = self.provider_cancel(order, self.waiting_payment(order, status="DONE"))

        self.assertEqual(response.status_code, 409)
        urlopen.assert_not_called()
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)

    def test_a_virtual_account_toss_already_cancelled_is_cancelled_locally(self):
        order = self.vbank_order()

        response, urlopen = self.provider_cancel(order, self.waiting_payment(order, status="EXPIRED"))

        self.assertEqual(response.status_code, 200, response.content[:300])
        urlopen.assert_not_called()
        order.refresh_from_db()
        self.assertEqual(order.od_status, CANCELLED)

    def test_a_toss_status_lookup_failure_leaves_the_order_untouched(self):
        from gnu_jango.api.response import api_error

        order = self.vbank_order()

        response, _ = self.provider_cancel(order, (None, api_error("down", status=502, code="toss_payment_status_unavailable")))

        self.assertEqual(response.status_code, 502)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)

    def test_a_virtual_account_order_without_a_payment_key_is_cancelled_locally_only(self):
        order = self.make_vbank_order(od_tno="")

        with patch("gnu_jango.api.shop_payments.toss_api_get_payment_by_order") as lookup:
            response = self.post(CANCEL_URL, {"order_id": order.od_id})

        self.assertEqual(response.status_code, 200)
        lookup.assert_not_called()
        order.refresh_from_db()
        self.assertEqual(order.od_status, CANCELLED)


# ---------------------------------------------------------------------------
# Toss virtual account webhook
# ---------------------------------------------------------------------------
@override_settings(**FAKE_TOSS_VBANK)
class TossVirtualAccountWebhookTests(PaymentTestBase):
    SECRET = "vbank-fake-secret"

    def event(self, order, status="DONE", secret=None, event_type="DEPOSIT_CALLBACK"):
        return {
            "eventType": event_type,
            "data": {"orderId": order.od_id, "secret": secret if secret is not None else self.SECRET, "status": status},
        }

    def provider(self, order, **over):
        payment = {
            "orderId": order.od_id,
            "paymentKey": order.od_tno,
            "method": "가상계좌",
            "status": "DONE",
            "totalAmount": order.od_receipt_price,
        }
        payment.update(over)
        return payment

    def send(self, body, provider_result=None, raw=None):
        with patch("gnu_jango.api.v1_shop.toss_api_get_payment_by_order") as lookup:
            lookup.return_value = provider_result if provider_result is not None else (None, None)
            response = self.client.post(WEBHOOK_URL, data=raw if raw is not None else json.dumps(body), content_type="application/json")
        return response, lookup

    def make_order_with_stock(self, **extra):
        """A virtual account order backed by a real reserved cart row, for stock/points/coupon checks."""
        coupon = self.make_coupon()
        order = self.prepared_order(od_settle_case=VBANK_CASE, cp_id=coupon.cp_id, point_use=20000)
        ShopOrder.objects.filter(pk=order.pk).update(
            od_tno="pay_vb_key_1",
            od_vbank_secret_hash=hashlib.sha256(self.SECRET.encode()).hexdigest(),
            od_vbank_status="WAITING_FOR_DEPOSIT",
            **extra,
        )
        order.refresh_from_db()
        return order, coupon

    def test_a_deposit_marks_the_order_paid_once_even_when_the_webhook_repeats(self):
        order, coupon = self.make_order_with_stock()
        provider = self.provider(order)

        first, _ = self.send(self.event(order), (provider, None))
        order.refresh_from_db()
        # the replay rewrites od_receipt_time, so it is only checked to stay set
        second, _ = self.send(self.event(order), (provider, None))

        self.assertEqual(first.status_code, 200, first.content[:300])
        self.assertEqual(second.status_code, 200)
        self.assertTrue(first.json()["data"]["processed"])
        order.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(order.od_status, PAID)
        self.assertEqual(order.od_misu, 0)
        self.assertEqual(order.od_vbank_status, "DONE")
        self.assertNotEqual(order.od_receipt_time, "")
        self.assertEqual(order.od_receipt_price, 73000)
        self.assertEqual(coupon.cp_used, "1")
        self.assertEqual(self.points(), 60000)
        self.assertEqual(self.stock(), 9)
        self.assertEqual(ShopOrderData.objects.filter(log_id__startswith="toss-vbank-").count(), 1)

    def test_the_webhook_trusts_the_provider_state_not_the_posted_status(self):
        order = self.make_vbank_order()

        response, _ = self.send(self.event(order, status="DONE"), (self.provider(order, status="WAITING_FOR_DEPOSIT"), None))

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)
        self.assertEqual(order.od_misu, 1000)

    def test_a_wrong_secret_is_refused_and_not_logged_in_clear(self):
        order = self.make_vbank_order()

        response, lookup = self.send(self.event(order, secret="guessed-secret-value"))

        self.assertEqual(response.status_code, 403)
        lookup.assert_not_called()
        self.assertUnpaid(order)
        log = ShopOrderData.objects.get(order=order)
        self.assertNotIn("guessed-secret-value", log.dt_data)
        self.assertTrue(log.log_id.startswith("toss-vbank-reject"))

    def test_the_stored_hash_is_never_accepted_as_the_secret(self):
        order = self.make_vbank_order()

        response, lookup = self.send(self.event(order, secret=order.od_vbank_secret_hash))

        self.assertEqual(response.status_code, 403)
        lookup.assert_not_called()

    def test_malformed_events_are_rejected(self):
        order = self.make_vbank_order()
        cases = {
            "wrong type": self.event(order, event_type="PAYMENT_STATUS_CHANGED"),
            "no secret": {"eventType": "DEPOSIT_CALLBACK", "data": {"orderId": order.od_id}},
            "no order": {"eventType": "DEPOSIT_CALLBACK", "data": {"secret": self.SECRET}},
            "data not an object": {"eventType": "DEPOSIT_CALLBACK", "data": "text"},
            "empty": {},
        }
        for name, body in cases.items():
            with self.subTest(name):
                response, lookup = self.send(body)
                self.assertEqual(response.status_code, 400)
                lookup.assert_not_called()
        self.assertUnpaid(order)

    def test_a_non_json_body_is_not_accepted(self):
        response = self.client.post(WEBHOOK_URL, data="eventType=DEPOSIT_CALLBACK", content_type="application/x-www-form-urlencoded")

        self.assertEqual(response.status_code, 415)

    def test_an_unknown_order_is_not_found(self):
        order = self.make_vbank_order()
        event = self.event(order)
        event["data"]["orderId"] = "NOSUCHORDER"

        response, lookup = self.send(event)

        self.assertEqual(response.status_code, 404)
        lookup.assert_not_called()

    def test_an_order_that_never_got_a_virtual_account_secret_is_not_found(self):
        order = self.make_vbank_order(od_vbank_secret_hash="")

        response, _ = self.send(self.event(order))

        self.assertEqual(response.status_code, 404)
        self.assertUnpaid(order)

    def test_an_order_of_another_provider_is_not_found(self):
        order = self.make_vbank_order(od_pg="kcp")

        response, _ = self.send(self.event(order))

        self.assertEqual(response.status_code, 404)
        self.assertUnpaid(order)

    def test_a_provider_lookup_failure_is_retryable_and_changes_nothing(self):
        from gnu_jango.api.response import api_error

        order = self.make_vbank_order()

        response, _ = self.send(self.event(order), (None, api_error("down", status=502, code="toss_payment_status_unavailable")))

        self.assertEqual(response.status_code, 502)
        self.assertUnpaid(order)
        self.assertTrue(ShopOrderData.objects.filter(log_id__startswith="toss-vbank-retry").exists())

    def test_provider_data_that_does_not_match_the_order_is_flagged_for_review(self):
        order = self.make_vbank_order()
        mismatches = {
            "order id": {"orderId": "OTHERORDER"},
            "amount": {"totalAmount": 1},
            "payment key": {"paymentKey": "pay_other"},
            "method": {"method": "card"},
        }
        for name, override in mismatches.items():
            with self.subTest(name):
                response, _ = self.send(self.event(order), (self.provider(order, **override), None))
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.json()["data"]["processed"])
                self.assertTrue(response.json()["data"]["manual_review"])
                self.assertUnpaid(order)

    def test_a_deposit_for_a_cancelled_order_is_not_applied(self):
        order, coupon = self.make_order_with_stock()
        ShopOrder.objects.filter(pk=order.pk).update(od_status=CANCELLED)

        response, _ = self.send(self.event(order), (self.provider(order), None))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["manual_review"])
        order.refresh_from_db()
        self.assertEqual(order.od_status, CANCELLED)
        self.assertEqual(order.od_receipt_time, "")
        self.assertTrue(ShopOrderData.objects.filter(log_id__startswith="toss-vbank-late-paid").exists())

    def test_an_expired_virtual_account_cancels_the_order_and_gives_everything_back_once(self):
        order, coupon = self.make_order_with_stock()
        self.assertEqual(self.stock(), 9)
        self.assertEqual(self.points(), 60000)
        expired = self.provider(order, status="EXPIRED")

        first, _ = self.send(self.event(order, status="EXPIRED"), (expired, None))
        second, _ = self.send(self.event(order, status="EXPIRED"), (expired, None))

        self.assertEqual(first.status_code, 200, first.content[:300])
        self.assertEqual(second.status_code, 200)
        order.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(order.od_status, CANCELLED)
        self.assertEqual(order.od_vbank_status, "EXPIRED")
        self.assertEqual(self.stock(), 10)
        self.assertEqual(self.points(), 80000)
        self.assertEqual(User_Point.objects.filter(user=self.member, po_rel_table="@order-cancel").count(), 1)
        self.assertEqual(coupon.cp_used, "")
        self.assertFalse(ShopCouponLog.objects.filter(od_id=order.od_id).exists())

    def test_a_cancelled_virtual_account_for_a_paid_order_is_flagged_not_cancelled(self):
        order, _ = self.make_order_with_stock(od_status=PAID, od_misu=0)

        response, _ = self.send(self.event(order, status="CANCELED"), (self.provider(order, status="CANCELED"), None))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["manual_review"])
        order.refresh_from_db()
        self.assertEqual(order.od_status, PAID)
        self.assertEqual(self.stock(), 9)
        self.assertEqual(self.points(), 60000)

    def test_waiting_for_deposit_keeps_a_pending_order_pending(self):
        order = self.make_vbank_order()

        response, _ = self.send(self.event(order, status="WAITING_FOR_DEPOSIT"), (self.provider(order, status="WAITING_FOR_DEPOSIT"), None))

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)
        self.assertEqual(order.od_vbank_status, "WAITING_FOR_DEPOSIT")

    def test_waiting_for_deposit_sends_a_paid_order_back_to_pending(self):
        order = self.make_vbank_order(od_status=PAID, od_misu=0, od_receipt_time="2026-10-10 10:00:00")

        response, _ = self.send(self.event(order, status="WAITING_FOR_DEPOSIT"), (self.provider(order, status="WAITING_FOR_DEPOSIT"), None))

        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)
        self.assertEqual(order.od_misu, 1000)
        self.assertEqual(order.od_receipt_time, "")

    def test_waiting_for_deposit_is_flagged_for_a_shipped_or_cancelled_order(self):
        for status in (SHIPPING, CANCELLED):
            with self.subTest(status=status):
                order = self.make_vbank_order(order_id=f"ODPAY-W-{status}", od_status=status, od_misu=0)
                response, _ = self.send(self.event(order, status="WAITING_FOR_DEPOSIT"), (self.provider(order, status="WAITING_FOR_DEPOSIT"), None))
                self.assertTrue(response.json()["data"]["manual_review"])
                order.refresh_from_db()
                self.assertEqual(order.od_status, status)

    def test_an_unknown_provider_status_is_ignored(self):
        order = self.make_vbank_order()

        response, _ = self.send(self.event(order), (self.provider(order, status="PARTIAL_CANCELED"), None))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["processed"])
        self.assertEqual(response.json()["data"]["provider_status"], "PARTIAL_CANCELED")
        self.assertUnpaid(order)

    def test_a_non_object_provider_payload_is_flagged_for_review(self):
        order = self.make_vbank_order()

        response, _ = self.send(self.event(order), ("not-a-dict", None))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["manual_review"])
        self.assertUnpaid(order)


# ---------------------------------------------------------------------------
# generic provider callback
# ---------------------------------------------------------------------------
class PaymentCallbackTests(PaymentTestBase):
    def secret_header(self, value=CALLBACK_SECRET):
        return {"HTTP_X_PAYMENT_CALLBACK_SECRET": value}

    def callback(self, order, provider="kcp", body=None, headers=None):
        payload = {
            "order_id": order.od_id,
            "amount": order.od_receipt_price,
            "success": "true",
            "transaction_id": "tid-cb-1",
        }
        payload.update(body or {})
        return self.client.post(
            callback_url(provider),
            data=payload,
            format="json",
            **(self.secret_header() if headers is None else headers),
        )

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET)
    def test_a_secret_in_the_query_string_is_not_accepted(self):
        order = self.pending_order()
        response = self.client.post(
            callback_url("kcp") + f"?secret={CALLBACK_SECRET}",
            data={"order_id": order.od_id, "amount": order.od_receipt_price, "success": "true", "transaction_id": "tid-q"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertUnpaid(order)

    def sign(self, provider, body, secret="fake-signature-secret"):
        canonical = json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        return hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET="")
    def test_callbacks_are_refused_while_no_secret_is_configured(self):
        order = self.pending_order()

        response = self.callback(order)

        self.assertEqual(response.status_code, 503)
        self.assertUnpaid(order)

    def pending_order(self, **fields):
        self.add_to_cart()
        return self.make_card_order(**fields)

    def make_card_order(self, **fields):
        with override_settings(**FAKE_ADAPTER):
            response = self.prepare(add=False, pg_service="kcp", **fields)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return ShopOrder.objects.get(pk=response.json()["data"]["order_id"])

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET)
    def test_a_callback_with_the_secret_marks_the_order_paid(self):
        coupon = self.make_coupon()
        order = self.pending_order(cp_id=coupon.cp_id, point_use=20000)

        response = self.callback(order)

        self.assertEqual(response.status_code, 200, response.content[:300])
        order.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(order.od_status, PAID)
        self.assertEqual(order.od_misu, 0)
        self.assertEqual(order.od_tno, "tid-cb-1")
        self.assertEqual(order.od_pg, "callback:kcp")
        self.assertEqual(coupon.cp_used, "1")
        self.assertEqual(set(order.items.values_list("ct_status", flat=True)), {PAID})
        self.assertTrue(ShopOrderData.objects.filter(order=order, log_id__startswith="cb-").exists())

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET)
    def test_a_replayed_callback_leaves_the_paid_order_as_it_was(self):
        order = self.pending_order(point_use=20000)
        first = self.callback(order)
        order.refresh_from_db()
        # the replay rewrites od_receipt_time, so it is only checked to stay set

        second = self.callback(order)

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.od_status, PAID)
        self.assertNotEqual(order.od_receipt_time, "")
        self.assertEqual(self.points(), 60000)
        self.assertEqual(ShopOrderData.objects.filter(log_id__startswith="cb-pay").count(), 1)

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET)
    def test_a_callback_without_or_with_the_wrong_secret_is_forged(self):
        order = self.pending_order()

        for name, headers in {"missing": {}, "wrong": self.secret_header("not-the-secret"), "empty": self.secret_header("")}.items():
            with self.subTest(name):
                response = self.callback(order, headers=headers)
                self.assertEqual(response.status_code, 403)
                self.assertUnpaid(order)
        self.assertTrue(ShopOrderData.objects.filter(log_id__startswith="cb-reject").exists())

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET)
    def test_the_secret_may_come_from_any_of_the_documented_headers(self):
        for header in ("HTTP_X_GNUJANGO_PAYMENT_CALLBACK_SECRET", "HTTP_X_PAYMENT_CALLBACK_SECRET", "HTTP_X_WEBHOOK_SECRET"):
            with self.subTest(header=header):
                order = self.pending_order() if header == "HTTP_X_GNUJANGO_PAYMENT_CALLBACK_SECRET" else self.make_card_order_with_cart()
                response = self.callback(order, headers={header: CALLBACK_SECRET})
                self.assertEqual(response.status_code, 200, response.content[:300])

    def make_card_order_with_cart(self):
        self.add_to_cart()
        return self.make_card_order()

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET)
    def test_a_wrong_secret_in_the_body_is_not_stored_in_clear_in_the_reject_log(self):
        order = self.pending_order()

        response = self.callback(order, body={"secret": "body-guess-secret"}, headers={})

        self.assertEqual(response.status_code, 403)
        logs = ShopOrderData.objects.filter(log_id__startswith="cb-reject")
        self.assertTrue(logs.exists())
        for log in logs:
            self.assertNotIn("body-guess-secret", log.dt_data)

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET)
    def test_a_callback_with_a_wrong_amount_does_not_pay_the_order(self):
        order = self.pending_order()

        response = self.callback(order, body={"amount": order.od_receipt_price - 1})

        self.assertEqual(response.status_code, 409)
        self.assertUnpaid(order)

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET)
    def test_a_callback_that_does_not_report_success_does_not_pay_the_order(self):
        order = self.pending_order()

        for name, body in {
            "failed flag": {"success": "false"},
            "failed status": {"success": "", "status": "FAILED"},
            "error code": {"success": "", "res_cd": "9999"},
        }.items():
            with self.subTest(name):
                response = self.callback(order, body=body)
                self.assertEqual(response.status_code, 422)
                self.assertUnpaid(order)
        self.assertTrue(ShopOrderData.objects.filter(log_id__startswith="cb-fail").exists())

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET)
    def test_a_callback_for_a_cancelled_order_is_refused(self):
        order = self.pending_order()
        ShopOrder.objects.filter(pk=order.pk).update(od_status=CANCELLED)

        response = self.callback(order)

        self.assertEqual(response.status_code, 409)
        order.refresh_from_db()
        self.assertEqual(order.od_status, CANCELLED)
        self.assertEqual(order.od_receipt_time, "")

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET)
    def test_a_callback_for_an_unknown_order_or_without_an_order_id_is_refused(self):
        order = self.pending_order()

        unknown = self.callback(order, body={"order_id": "NOSUCHORDER"})
        missing = self.callback(order, body={"order_id": "", "orderId": ""})

        self.assertEqual(unknown.status_code, 404)
        self.assertEqual(missing.status_code, 422)
        self.assertUnpaid(order)

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET)
    def test_a_form_encoded_callback_with_gateway_field_names_is_understood(self):
        order = self.pending_order()

        response = self.client.post(
            callback_url("inicis"),
            data=urlencode({"MOID": order.od_id, "TotPrice": str(order.od_receipt_price), "ResultCode": "00", "TID": "inicis-tid-1"}),
            content_type="application/x-www-form-urlencoded",
            **self.secret_header(),
        )

        self.assertEqual(response.status_code, 200, response.content[:300])
        order.refresh_from_db()
        self.assertEqual(order.od_status, PAID)
        self.assertEqual(order.od_tno, "inicis-tid-1")

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET, SHOP_PAYMENT_CALLBACK_SIGNATURE_SECRET="fake-signature-secret")
    def test_a_signed_callback_requires_a_valid_signature(self):
        order = self.pending_order()
        signed_body = {
            "amount": order.od_receipt_price,
            "order_id": order.od_id,
            "provider": "kcp",
            "success": True,
            "transaction_id": "tid-cb-1",
        }
        good = self.sign("kcp", signed_body)

        missing = self.callback(order)
        wrong = self.callback(order, headers={**self.secret_header(), "HTTP_X_PAYMENT_SIGNATURE": "0" * 64})
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(wrong.status_code, 403)
        self.assertUnpaid(order)

        accepted = self.callback(order, headers={**self.secret_header(), "HTTP_X_PAYMENT_SIGNATURE": f"sha256={good.upper()}"})
        self.assertEqual(accepted.status_code, 200, accepted.content[:300])
        order.refresh_from_db()
        self.assertEqual(order.od_status, PAID)

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET, SHOP_PAYMENT_CALLBACK_SIGNATURE_SECRET="fake-signature-secret")
    def test_a_signature_cannot_be_reused_for_another_amount_order_or_provider(self):
        order = self.pending_order()
        signed_body = {
            "amount": order.od_receipt_price,
            "order_id": order.od_id,
            "provider": "kcp",
            "success": True,
            "transaction_id": "tid-cb-1",
        }
        signature = {"HTTP_X_PAYMENT_SIGNATURE": self.sign("kcp", signed_body), **self.secret_header()}

        other_provider = self.callback(order, provider="nicepay", headers=signature)
        other_transaction = self.callback(order, body={"transaction_id": "tid-cb-2"}, headers=signature)
        other_amount = self.callback(order, body={"amount": 1}, headers=signature)

        self.assertEqual(other_provider.status_code, 403)
        self.assertEqual(other_transaction.status_code, 403)
        self.assertEqual(other_amount.status_code, 403)
        self.assertUnpaid(order)
        self.assertTrue(ShopOrderData.objects.filter(log_id__startswith="cb-reject").exists())

    @override_settings(SHOP_PAYMENT_CALLBACK_SECRET=CALLBACK_SECRET, SHOP_PAYMENT_CALLBACK_SIGNATURE_SECRET="fake-signature-secret")
    def test_the_signature_may_be_sent_in_the_body_and_is_redacted_from_logs(self):
        order = self.pending_order()
        signed_body = {
            "amount": order.od_receipt_price,
            "order_id": order.od_id,
            "provider": "kcp",
            "success": True,
            "transaction_id": "tid-cb-1",
        }
        good = self.sign("kcp", signed_body)

        response = self.callback(order, body={"signature": good})

        self.assertEqual(response.status_code, 200, response.content[:300])
        log = ShopOrderData.objects.get(order=order, log_id__startswith="cb-")
        self.assertNotIn(good, log.dt_data)


# ---------------------------------------------------------------------------
# helper functions and provider HTTP calls
# ---------------------------------------------------------------------------
class PaymentHelperTests(TestCase):
    def test_redaction_hides_secret_signature_authorization_and_token_keys_at_any_depth(self):
        data = {
            "Secret": "a",
            "client_secret": "b",
            "X-Hub-Signature-256": "c",
            "Authorization": "d",
            "access_token": "e",
            "plain": "visible",
            "nested": {"payment_signature": "f", "list": [{"callback-secret": "g"}, ("h", {"secret": "i"})]},
        }

        redacted = shop_payments.redact_payment_data(data)
        text = json.dumps(redacted)

        for leaked in ("\"a\"", "\"b\"", "\"c\"", "\"d\"", "\"e\"", "\"f\"", "\"g\"", "\"i\""):
            self.assertNotIn(leaked, text)
        self.assertEqual(redacted["plain"], "visible")
        self.assertEqual(redacted["nested"]["list"][1][0], "h")
        self.assertEqual(data["Secret"], "a")

    def test_redaction_leaves_scalars_alone(self):
        self.assertEqual(shop_payments.redact_payment_data(5), 5)
        self.assertIsNone(shop_payments.redact_payment_data(None))

    def test_raw_log_without_an_order_keeps_the_order_id_and_is_updated_not_duplicated(self):
        shop_payments.record_payment_raw_log(None, "ORD-X", "toss", "key1", {"secret": "s", "a": 1}, prefix="toss-reject")
        shop_payments.record_payment_raw_log(None, "ORD-X", "toss", "key1", {"secret": "s", "a": 2}, prefix="toss-reject")

        log = ShopOrderData.objects.get()
        self.assertEqual(log.od_id, "ORD-X")
        self.assertIsNone(log.order)
        self.assertEqual(json.loads(log.dt_data), {"secret": "***redacted***", "a": 2})
        self.assertLessEqual(len(log.log_id), 40)
        self.assertTrue(log.log_id.startswith("toss-reject-pay-ORD-X"))

    def test_payment_log_ids_fit_the_column_and_are_unique_without_a_transaction_id(self):
        long_id = "9" * 60

        first = shop_payments.payment_log_id(long_id, "")
        second = shop_payments.payment_log_id(long_id, "")

        self.assertEqual(len(first), 40)
        self.assertNotEqual(shop_payments.payment_log_id("A", ""), shop_payments.payment_log_id("A", ""))
        self.assertEqual(shop_payments.payment_log_id("A", "T1"), "pay-A-T1")
        self.assertEqual(len(second), 40)

    def test_field_aliases_of_the_gateways_are_understood(self):
        self.assertEqual(shop_payments.payment_order_id({"MOID": " 123 "}), "123")
        self.assertEqual(shop_payments.payment_order_id({"orderId": "o1", "order_id": "o2"}), "o2")
        self.assertEqual(shop_payments.payment_order_id({}), "")
        self.assertEqual(shop_payments.payment_amount({"TotPrice": "1,500"}), 1500)
        self.assertEqual(shop_payments.payment_amount({"LGD_AMOUNT": 7}), 7)
        self.assertEqual(shop_payments.payment_amount({"amount": "abc"}), -1)
        self.assertEqual(shop_payments.payment_amount({}), -1)
        self.assertEqual(shop_payments.payment_transaction_id({"tno": " T9 "}), "T9")
        self.assertEqual(shop_payments.payment_transaction_id({}), "")
        self.assertEqual(shop_payments.payment_key({"payment_key": " pk "}), "pk")
        self.assertEqual(shop_payments.payment_key({}), "")

    def test_success_detection_only_accepts_known_success_markers(self):
        for data in ({"success": "Y"}, {"status": "DONE"}, {"P_STATUS": "00"}, {"ResultCode": "0000"}, {"res_cd": "0000"}, {"LGD_RESPCODE": "0000"}):
            with self.subTest(data=data):
                self.assertTrue(shop_payments.payment_callback_success(data))
        for data in ({}, {"success": "no"}, {"status": "FAILED"}, {"res_cd": "1001"}, {"status": "canceled"}):
            with self.subTest(data=data):
                self.assertFalse(shop_payments.payment_callback_success(data))

    def test_adapter_success_requires_a_dict_with_a_positive_flag(self):
        self.assertTrue(shop_payments.payment_adapter_success({"verified": True}))
        self.assertTrue(shop_payments.payment_adapter_success({"approved": True}))
        self.assertTrue(shop_payments.payment_adapter_success({"ok": True}))
        self.assertTrue(shop_payments.payment_adapter_success({"status": "approved"}))
        self.assertFalse(shop_payments.payment_adapter_success({"verified": False}))
        self.assertFalse(shop_payments.payment_adapter_success({"verified": "false"}))
        self.assertFalse(shop_payments.payment_adapter_success(None))
        self.assertFalse(shop_payments.payment_adapter_success("ok"))

    def test_settle_case_classification(self):
        self.assertTrue(shop_payments.settle_case_is_bank(""))
        self.assertTrue(shop_payments.settle_case_is_bank("bank"))
        self.assertFalse(shop_payments.settle_case_is_bank("card"))
        self.assertTrue(shop_payments.settle_case_is_vbank("virtual_account"))
        self.assertTrue(shop_payments.settle_case_is_vbank("V-Bank"))
        self.assertFalse(shop_payments.settle_case_is_vbank("bank"))
        self.assertTrue(shop_payments.settle_case_supports_cash_receipt("iche"))
        self.assertFalse(shop_payments.settle_case_supports_cash_receipt("card"))
        self.assertTrue(shop_payments.toss_method_is_vbank("Virtual-Account"))
        self.assertFalse(shop_payments.toss_method_is_vbank("card"))

    def test_signature_normalisation_and_payload_are_stable(self):
        self.assertEqual(shop_payments.normalize_payment_signature(" SHA256=ABCdef "), "abcdef")
        self.assertEqual(shop_payments.normalize_payment_signature(None), "")
        payload = shop_payments.payment_callback_signature_payload("KCP", {"order_id": "1", "amount": "5", "success": "1", "tno": "T"})
        self.assertEqual(
            json.loads(payload),
            {"amount": 5, "order_id": "1", "provider": "kcp", "success": True, "transaction_id": "T"},
        )
        self.assertEqual(
            shop_payments.payment_adapter_signature("k", "100", "body"),
            hmac.new(b"k", b"100.body", hashlib.sha256).hexdigest(),
        )

    @override_settings(SHOP_PAYMENT_CALLBACK_SIGNATURE_SECRET="")
    def test_no_signature_is_demanded_when_no_signature_secret_is_configured(self):
        request = MagicMock()
        request.META = {}

        self.assertIsNone(shop_payments.payment_callback_signature_error(request, "kcp", {}))


def fake_http_response(payload):
    response = MagicMock()
    response.read.return_value = (payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8"))
    context = MagicMock()
    context.__enter__.return_value = response
    return context


def http_error(code, payload=b"{}"):
    error = urllib_error.HTTPError("https://provider.invalid", code, "err", {}, None)
    error.read = lambda: payload
    return error


class TossHttpCallTests(TestCase):
    @override_settings(SHOP_TOSS_CLIENT_KEY="", SHOP_TOSS_SECRET_KEY="")
    def test_calls_are_refused_while_toss_is_not_configured(self):
        with patch("gnu_jango.api.shop_payments.urllib_request.urlopen") as urlopen:
            confirm, confirm_error = shop_payments.toss_api_confirm("pk", "o1", 1000)
            lookup, lookup_error = shop_payments.toss_api_get_payment_by_order("o1")

        self.assertIsNone(confirm)
        self.assertIsNone(lookup)
        self.assertEqual(confirm_error.status_code, 503)
        self.assertEqual(lookup_error.status_code, 503)
        urlopen.assert_not_called()

    @override_settings(**FAKE_TOSS)
    def test_confirm_sends_the_authorised_idempotent_request(self):
        with patch("gnu_jango.api.shop_payments.urllib_request.urlopen", return_value=fake_http_response({"status": "DONE"})) as urlopen:
            payment, error = shop_payments.toss_api_confirm("pk_fake", "order-1", 1000)

        self.assertIsNone(error)
        self.assertEqual(payment, {"status": "DONE"})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.tosspayments.com/v1/payments/confirm")
        self.assertEqual(json.loads(request.data), {"paymentKey": "pk_fake", "orderId": "order-1", "amount": 1000})
        self.assertEqual(request.get_header("Idempotency-key"), "confirm-order-1-pk_fake")
        self.assertTrue(request.get_header("Authorization").startswith("Basic "))

    @override_settings(**FAKE_TOSS)
    def test_confirm_maps_provider_failures_to_api_errors(self):
        cases = [
            (http_error(400, b'{"code":"INVALID_CARD","message":"card declined"}'), 400),
            (http_error(500, b"gateway down"), 502),
            (urllib_error.URLError("offline"), 502),
            (TimeoutError("slow"), 502),
        ]
        for failure, expected in cases:
            with self.subTest(failure=repr(failure)):
                with patch("gnu_jango.api.shop_payments.urllib_request.urlopen", side_effect=failure):
                    payment, error = shop_payments.toss_api_confirm("pk", "o1", 1)
                self.assertIsNone(payment)
                self.assertEqual(error.status_code, expected)

    @override_settings(**FAKE_TOSS)
    def test_network_failure_details_stay_in_the_server_log(self):
        # The exception text can name internal hosts and ports; the client gets a generic message.
        failure = urllib_error.URLError("[Errno 111] Connection refused: internal-pg:9443")
        with patch("gnu_jango.api.shop_payments.urllib_request.urlopen", side_effect=failure):
            with self.assertLogs("gnu_jango.api.shop_payments", level="WARNING") as logs:
                _, error = shop_payments.toss_api_confirm("pk", "o1", 1)

        self.assertNotIn("internal-pg", json.dumps(error.data))
        self.assertIn("internal-pg", "\n".join(logs.output))

    @override_settings(**FAKE_TOSS)
    def test_confirm_reports_the_provider_message_of_a_rejection(self):
        with patch("gnu_jango.api.shop_payments.urllib_request.urlopen", side_effect=http_error(400, b'{"code":"X","message":"card declined"}')):
            _, error = shop_payments.toss_api_confirm("pk", "o1", 1)

        self.assertEqual(error.data["message"], "card declined")
        self.assertEqual(error.data["errors"]["provider_code"], "X")

    @override_settings(**FAKE_TOSS)
    def test_confirm_refuses_an_unreadable_provider_response(self):
        with patch("gnu_jango.api.shop_payments.urllib_request.urlopen", return_value=fake_http_response(b"<html>")):
            payment, error = shop_payments.toss_api_confirm("pk", "o1", 1)

        self.assertIsNone(payment)
        self.assertEqual(error.status_code, 502)

    @override_settings(**FAKE_TOSS)
    def test_status_lookup_quotes_the_order_id_and_validates_the_answer(self):
        with patch("gnu_jango.api.shop_payments.urllib_request.urlopen", return_value=fake_http_response({"status": "DONE"})) as urlopen:
            payment, error = shop_payments.toss_api_get_payment_by_order("a/b c")

        self.assertIsNone(error)
        self.assertEqual(payment, {"status": "DONE"})
        self.assertTrue(urlopen.call_args.args[0].full_url.endswith("/v1/payments/orders/a%2Fb%20c"))

    @override_settings(**FAKE_TOSS)
    def test_status_lookup_failures_are_reported_as_unavailable(self):
        cases = [
            http_error(404),
            urllib_error.URLError("offline"),
            TimeoutError("slow"),
        ]
        for failure in cases:
            with self.subTest(failure=repr(failure)):
                with patch("gnu_jango.api.shop_payments.urllib_request.urlopen", side_effect=failure):
                    payment, error = shop_payments.toss_api_get_payment_by_order("o1")
                self.assertIsNone(payment)
                self.assertEqual(error.status_code, 502)
        for body in (b"[]", b"not json"):
            with self.subTest(body=body):
                with patch("gnu_jango.api.shop_payments.urllib_request.urlopen", return_value=fake_http_response(body)):
                    payment, error = shop_payments.toss_api_get_payment_by_order("o1")
                self.assertIsNone(payment)
                self.assertEqual(error.status_code, 502)

    @override_settings(**FAKE_TOSS)
    def test_a_virtual_account_cancel_with_an_unreadable_answer_is_not_trusted(self):
        order = ShopOrder(od_id="o1", od_settle_case=VBANK_CASE, od_tno="pk", od_receipt_price=1000)
        waiting = {"orderId": "o1", "paymentKey": "pk", "method": "가상계좌", "status": "WAITING_FOR_DEPOSIT", "totalAmount": 1000}
        for answer in (fake_http_response(b"[]"), fake_http_response(b"not json"), fake_http_response({"orderId": "other", "status": "CANCELED"})):
            with patch("gnu_jango.api.shop_payments.toss_api_get_payment_by_order", return_value=(waiting, None)), patch(
                "gnu_jango.api.shop_payments.urllib_request.urlopen", return_value=answer
            ):
                error = shop_payments.cancel_pending_toss_vbank(order, "reason")
            self.assertEqual(error.status_code, 502)

    def test_cancel_pending_vbank_does_nothing_for_other_payment_methods(self):
        card = ShopOrder(od_id="o1", od_settle_case="card", od_tno="pk")
        vbank_without_key = ShopOrder(od_id="o2", od_settle_case=VBANK_CASE, od_tno="")

        self.assertIsNone(shop_payments.cancel_pending_toss_vbank(card, "r"))
        self.assertIsNone(shop_payments.cancel_pending_toss_vbank(vbank_without_key, "r"))


@override_settings(**FAKE_ADAPTER)
class AdapterHttpCallTests(TestCase):
    def test_an_unconfigured_adapter_refuses_without_a_request(self):
        with override_settings(SHOP_PAYMENT_ADAPTER_BASE_URL="", SHOP_PAYMENT_ADAPTER_SECRET=""), patch(
            "gnu_jango.api.shop_payments.urllib_request.urlopen"
        ) as urlopen:
            result, error = shop_payments.payment_adapter_request("confirm", "kcp", {})

        self.assertIsNone(result)
        self.assertEqual(error.status_code, 503)
        urlopen.assert_not_called()

    def test_a_provider_outside_the_allow_list_is_refused(self):
        with override_settings(SHOP_PAYMENT_ADAPTER_PROVIDERS="kcp"):
            result, error = shop_payments.payment_adapter_request("confirm", "inicis", {})

        self.assertIsNone(result)
        self.assertEqual(error.status_code, 503)

    def test_the_request_is_signed_with_the_adapter_secret(self):
        with patch("gnu_jango.api.shop_payments.urllib_request.urlopen", return_value=fake_http_response({"verified": True})) as urlopen:
            result, error = shop_payments.payment_adapter_request("confirm", "KCP", {"order_id": "o1"})

        self.assertIsNone(error)
        self.assertEqual(result, {"verified": True})
        request = urlopen.call_args.args[0]
        timestamp = request.get_header("X-gnujango-adapter-timestamp")
        body = request.data.decode("utf-8")
        expected = shop_payments.payment_adapter_signature("fake-adapter-secret", timestamp, body)
        self.assertEqual(request.get_header("X-gnujango-adapter-signature"), f"sha256={expected}")
        self.assertEqual(json.loads(body), {"action": "confirm", "provider": "kcp", "payload": {"order_id": "o1"}})
        self.assertNotIn("fake-adapter-secret", body)

    def test_adapter_failures_become_api_errors(self):
        cases = [
            (http_error(403, b'{"message":"nope"}'), 400),
            (http_error(500, b"oops"), 502),
            (urllib_error.URLError("offline"), 502),
        ]
        for failure, expected in cases:
            with self.subTest(failure=repr(failure)):
                with patch("gnu_jango.api.shop_payments.urllib_request.urlopen", side_effect=failure):
                    result, error = shop_payments.payment_adapter_request("confirm", "kcp", {})
                self.assertIsNone(result)
                self.assertEqual(error.status_code, expected)

    def test_an_unreadable_adapter_answer_is_refused(self):
        with patch("gnu_jango.api.shop_payments.urllib_request.urlopen", return_value=fake_http_response(b"<html>")):
            result, error = shop_payments.payment_adapter_request("confirm", "kcp", {})

        self.assertIsNone(result)
        self.assertEqual(error.status_code, 502)


# ---------------------------------------------------------------------------
# fixes for defects these tests found
# ---------------------------------------------------------------------------
@override_settings(**FAKE_TOSS)
class PaymentDefectFixTests(PaymentTestBase):
    def test_a_repeated_confirmation_does_not_move_a_shipped_order_back(self):
        order = self.prepared_order()
        self.assertEqual(self.confirm_toss(order)[0].status_code, 200)
        ShopOrder.objects.filter(pk=order.pk).update(od_status=SHIPPING)
        order.items.update(ct_status=SHIPPING)
        response, _ = self.confirm_toss(order)
        self.assertEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.od_status, SHIPPING)
        self.assertEqual(set(order.items.values_list("ct_status", flat=True)), {SHIPPING})

    def test_one_coupon_cannot_discount_two_pending_orders(self):
        coupon = self.make_coupon()
        first = self.prepared_order(cp_id=coupon.cp_id)
        coupon.refresh_from_db()
        self.assertEqual(coupon.cp_used, "1")
        second = self.prepared_order(cp_id=coupon.cp_id)
        self.assertEqual(first.od_coupon, 7000)
        self.assertEqual(second.od_coupon, 0)

    def test_cancelling_a_pending_order_gives_the_coupon_back(self):
        coupon = self.make_coupon()
        order = self.prepared_order(cp_id=coupon.cp_id)
        response = self.post("/api/v1/shop/payment/cancel", {"order_id": order.od_id})
        self.assertEqual(response.status_code, 200, response.content[:300])
        coupon.refresh_from_db()
        self.assertEqual(coupon.cp_used, "")


@override_settings(**FAKE_ADAPTER)
class AdapterAmountTests(PaymentTestBase):
    def test_an_adapter_result_without_an_amount_is_not_trusted(self):
        order = self.prepared_order(pg_service="kcp")
        with patch("gnu_jango.api.shop_payments.payment_adapter_request") as adapter:
            adapter.return_value = ({"verified": True, "order_id": order.od_id, "transaction_id": "tid-x"}, None)
            response = self.post(CONFIRM_URL, {"pg_service": "kcp", "order_id": order.od_id, "amount": order.od_receipt_price})
        self.assertNotEqual(response.status_code, 200)
        order.refresh_from_db()
        self.assertEqual(order.od_status, ORDERED)
