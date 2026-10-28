"""OpenAPI contract tests for the shop cart and order reads (gnu_jango/api/contracts/orders.py)."""

import json

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api.shop_common import SHOP_CART_SESSION_KEY, auth_cart_config_name
from gnu_jango.config.models import Config
from gnu_jango.core.contract_testing import ContractAssertions
from gnu_jango.shop.models import (
    ShopCategory,
    ShopCoupon,
    ShopCouponLog,
    ShopOrder,
    ShopOrderItem,
    ShopProduct,
    ShopShippingPolicy,
)

CART = "/api/v1/shop/cart"
ORDERS = "/api/v1/shop/orders"
ORDER_DETAIL = "/api/v1/shop/orders/{od_id}"

CONTRACT_OPERATIONS = {
    ("GET", CART),
    ("GET", ORDERS),
    ("GET", ORDER_DETAIL),
}

BANK = "계약은행 000-00-0000 예금주"
RED = {"io_no": 1, "io_id": "빨강", "io_type": 0, "io_price": 500, "io_stock_qty": 10, "io_noti_qty": 1, "io_use": 1}
WRAP = {"io_no": 2, "io_id": "선물포장", "io_type": 1, "io_price": 300, "io_stock_qty": 10, "io_noti_qty": 1, "io_use": 1}


class ShopOrderContractFixture(ContractAssertions, TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.member = user_model.objects.create(username="contract-buyer")
        cls.category = ShopCategory.objects.create(ca_id="70", ca_name="계약 분류")
        cls.plain = ShopProduct.objects.create(
            it_id="OC001", category=cls.category, it_name="기본 상품", it_price=1000, it_stock_qty=50
        )
        cls.optioned = ShopProduct.objects.create(
            it_id="OC002",
            category=cls.category,
            it_name="옵션 상품",
            it_price=2000,
            it_basic_price=2500,
            it_notax=1,
            it_option_subject="색상",
            it_supply_subject="포장",
            options=[RED, WRAP],
        )
        # its own fee, paid on delivery: the line's ct_send_cost becomes 1
        cls.cod = ShopProduct.objects.create(
            it_id="OC003", category=cls.category, it_name="착불 상품", it_price=3000, it_sc_type=3, it_sc_method=1
        )
        ShopShippingPolicy.objects.update_or_create(
            pk=1, defaults={"de_send_cost_case": "차등", "de_send_cost_limit": "50000", "de_send_cost_list": "3000"}
        )
        Config.objects.update_or_create(name="de_bank_use", defaults={"value": "1"})
        Config.objects.update_or_create(name="de_bank_account", defaults={"value": BANK})

    def setUp(self):
        cache.clear()
        self.member_client = APIClient()
        self.member_client.force_authenticate(user=self.member)


class ShopCartContractTests(ShopOrderContractFixture):
    def test_empty_guest_cart_matches_the_contract(self):
        response = self.client.get(CART)

        data = response.json()["data"]
        self.assertEqual(data["items"], [])
        self.assertEqual((data["total_price"], data["send_cost"]), (0, 0))
        self.assertMatchesContract(response, CART)

    def test_guest_cart_with_option_supply_and_cod_lines_matches_the_contract(self):
        added = self.client.post(
            CART,
            {"it_id": "OC002", "options": [{"io_id": "빨강", "ct_qty": 2}, {"io_id": "선물포장", "io_type": 1, "ct_qty": 1}]},
            content_type="application/json",
        )
        self.assertEqual(added.status_code, 201, added.content[:300])
        self.client.post(CART, {"it_id": "OC003", "ct_qty": 1}, content_type="application/json")

        response = self.client.get(CART)

        lines = response.json()["data"]["items"]
        self.assertEqual([(line["it_id"], line["io_type"]) for line in lines], [("OC002", 0), ("OC002", 1), ("OC003", 0)])
        self.assertEqual(lines[0]["ct_option"], "빨강")
        self.assertEqual(lines[1]["line_total"], 300)
        self.assertEqual(lines[2]["ct_send_cost"], 1)
        self.assertEqual(response.json()["data"]["total_price"], (2000 + 500) * 2 + 300 + 3000)
        self.assertMatchesContract(response, CART)

    def test_guest_cart_line_of_a_deleted_product_with_a_coupon_matches_the_contract(self):
        session = self.client.session
        session[SHOP_CART_SESSION_KEY] = [
            {"ct_id": "100000000001", "it_id": "GONE", "it_name": "삭제된 상품", "ct_price": 4000, "ct_qty": 1},
            {"ct_id": "100000000002", "it_id": "OC001", "ct_price": 1000, "ct_qty": 2, "cp_id": "7", "cp_price": 500},
        ]
        session.save()

        response = self.client.get(CART)

        gone, couponed = response.json()["data"]["items"]
        self.assertEqual((gone["it_name"], gone["image_url"], gone["it_use"]), ("삭제된 상품", "/icon-192.png", "1"))
        self.assertEqual((couponed["cp_id"], couponed["cp_price"]), ("7", 500))
        self.assertEqual(response.json()["data"]["cart_coupon"], 500)
        self.assertMatchesContract(response, CART)

    def test_member_cart_matches_the_contract(self):
        Config.objects.update_or_create(
            name=auth_cart_config_name(self.member),
            defaults={"value": json.dumps([{"ct_id": "200000000001", "it_id": "OC001", "ct_price": 1000, "ct_qty": 3}])},
        )

        response = self.member_client.get(CART)

        data = response.json()["data"]
        self.assertEqual([line["ct_qty"] for line in data["items"]], [3])
        self.assertEqual(data["shipping_cost"], 3000)
        self.assertMatchesContract(response, CART)


class ShopOrderContractTests(ShopOrderContractFixture):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # a bank-deposit order of several lines, one of them cancelled; no coupons or points
        cls.bank_order = ShopOrder.objects.create(
            od_id="2026102800000000000001",
            user=cls.member,
            od_name="구매자",
            od_status="준비",
            od_settle_case="무통장",
            od_bank_account=BANK,
            od_cart_price=6300,
            od_send_cost=3000,
            od_receipt_price=9300,
            od_cancel_price=1000,
            od_hope_date=timezone.localdate(),
        )
        ShopOrderItem.objects.create(
            order=cls.bank_order, product=cls.optioned, ct_id="L1", it_id="OC002", it_name="옵션 상품",
            ct_price=2000, ct_qty=2, ct_option="빨강", io_price=500, ct_point=20, ct_status="준비",
            stock_adjusted=True, ct_notax=1,
        )
        ShopOrderItem.objects.create(
            order=cls.bank_order, product=cls.optioned, ct_id="L2", it_id="OC002", it_name="옵션 상품",
            ct_price=0, ct_qty=1, ct_option="선물포장", io_type=1, io_price=300, ct_status="준비",
        )
        # the product was deleted afterwards
        ShopOrderItem.objects.create(
            order=cls.bank_order, product=None, ct_id="L3", it_id="GONE", it_name="삭제된 상품",
            ct_price=1000, ct_qty=1, ct_status="취소",
        )
        # a card order paid through Toss with a coupon, points, a cash receipt number and an invoice
        cls.card_order = ShopOrder.objects.create(
            od_id="2026102800000000000002",
            user=cls.member,
            od_name="구매자",
            od_status="배송",
            od_settle_case="신용카드",
            od_pg="toss",
            od_tno="tgen_20261028",
            od_app_no="00012345",
            od_cart_price=20000,
            od_coupon=2000,
            od_receipt_point=1000,
            od_receipt_price=17000,
            od_receipt_time="2026-10-28 10:00:00",
            od_delivery_company="로젠택배",
            od_invoice="123-456",
            od_invoice_time="2026-10-28 12:00:00",
            od_cash_no="CASH-1",
            od_cash_res="https://example.test/receipt/1",
            od_ip="127.0.0.1",
            od_tax_invoice_request=True,
        )
        ShopOrderItem.objects.create(
            order=cls.card_order, product=cls.plain, ct_id="L4", it_id="OC001", it_name="기본 상품",
            ct_price=1000, ct_qty=20, ct_status="배송", stock_adjusted=True,
        )
        # a product coupon on the line: counted as od_cart_coupon (od_coupon is the order coupon)
        coupon = ShopCoupon.objects.create(cp_id="OCCP1", cp_subject="상품 쿠폰", cp_method=0, cp_target="OC001", cp_price=1500)
        ShopCouponLog.objects.create(
            cl_id=901, coupon=coupon, cp_id=coupon.cp_id, order=cls.card_order, od_id=cls.card_order.od_id, cp_price=1500
        )
        # a guest's cancelled virtual-account order
        cls.guest_order = ShopOrder.objects.create(
            od_id="2026102800000000000003",
            od_name="손님",
            od_status="취소",
            od_settle_case="가상계좌",
            od_cart_price=5000,
            od_coupon=500,
            od_vbank_bank_code="088",
            od_vbank_account="56211111111111",
            od_vbank_customer_name="손님",
            od_vbank_due_date="2026-10-30T23:59:59+09:00",
            od_vbank_status="CANCELED",
        )
        ShopOrderItem.objects.create(
            order=cls.guest_order, product=cls.plain, ct_id="L5", it_id="OC001", it_name="기본 상품",
            ct_price=1000, ct_qty=5, ct_status="취소",
        )

    def detail(self, order, client=None, **params):
        return (client or self.member_client).get(f"/api/v1/shop/orders/{order.od_id}", params)

    def test_member_order_list_matches_the_contract(self):
        response = self.member_client.get(ORDERS)

        rows = {row["od_id"]: row for row in response.json()["data"]}
        self.assertEqual(set(rows), {self.bank_order.od_id, self.card_order.od_id})
        self.assertIsNone(rows[self.bank_order.od_id]["cash_receipt"])
        self.assertNotIn("items", rows[self.bank_order.od_id])
        self.assertEqual(response.json()["meta"]["total"], 2)
        self.assertMatchesContract(response, ORDERS)

    def test_guest_order_list_is_an_empty_page_matching_the_contract(self):
        response = self.client.get(ORDERS)

        self.assertEqual(response.json()["data"], [])
        self.assertIsNone(response.json()["meta"]["from"])
        self.assertMatchesContract(response, ORDERS)

    def test_bank_order_with_a_cancelled_line_and_no_benefits_matches_the_contract(self):
        response = self.detail(self.bank_order)

        data = response.json()["data"]
        self.assertEqual([line["ct_id"] for line in data["items"]], ["L1", "L2", "L3"])
        self.assertEqual(data["items"][1]["line_total"], 300)
        self.assertEqual(data["items"][2]["it_seo_title"], "")
        self.assertEqual(data["od_bank_account"], BANK)
        self.assertEqual((data["od_cart_coupon"], data["od_receipt_point"]), (0, 0))
        self.assertIs(data["can_cancel"], False)
        self.assertIsInstance(data["cash_receipt"], dict)
        self.assertMatchesContract(response, ORDER_DETAIL)

    def test_card_order_with_coupon_points_receipt_and_invoice_matches_the_contract(self):
        response = self.detail(self.card_order)

        data = response.json()["data"]
        self.assertEqual(data["od_cart_coupon"], 1500)
        self.assertEqual(data["od_payment_app_label"], "승인번호")
        self.assertTrue(data["receipt_url"].startswith("https://dashboard.tosspayments.com/"))
        self.assertTrue(data["delivery_inquiry_url"])
        self.assertEqual((data["od_cash"], data["cash_receipt_url"]), (1, "https://example.test/receipt/1"))
        self.assertEqual(data["od_bank_account"], "")
        self.assertIs(data["od_tax_invoice_request"], True)
        self.assertMatchesContract(response, ORDER_DETAIL)

    def test_guest_cancelled_vbank_order_by_uid_matches_the_contract(self):
        response = self.detail(self.guest_order, client=self.client, uid=self.guest_order.uid)

        data = response.json()["data"]
        self.assertEqual((data["mb_id"], data["od_status"]), ("", "취소"))
        self.assertEqual(data["od_vbank_account"], "56211111111111")
        self.assertEqual(data["od_ip"], "")
        self.assertMatchesContract(response, ORDER_DETAIL)
