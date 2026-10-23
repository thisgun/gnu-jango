"""JWT API changes must carry the member into the history rows.

The browser admin uses a session, but the customer storefront uses DRF's JWT authentication.
This test proves the simple-history middleware sees the member after DRF authenticates the
request, instead of recording a customer order as System.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.config.models import Config
from gnu_jango.shop.models import ShopCategory, ShopOrder, ShopOrderItem, ShopProduct, ShopShippingPolicy

API = "/api/v1/shop"
BANK = "Audit Bank 000-00 Holder"
ORDER_FORM = {
    "od_name": "Audit Buyer",
    "od_tel": "010-1111-2222",
    "od_hp": "010-1111-2222",
    "od_email": "audit-buyer@example.test",
    "od_zip": "06236",
    "od_addr1": "Seoul",
    "od_addr2": "1",
    "od_b_name": "Audit Buyer",
    "od_b_tel": "010-1111-2222",
    "od_b_hp": "010-1111-2222",
    "od_b_zip": "06236",
    "od_b_addr1": "Seoul",
    "od_b_addr2": "1",
    "od_settle_case": "bank",
    "od_bank_account": BANK,
    "od_deposit_name": "Audit Buyer",
}


class ApiHistoryAttributionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = get_user_model().objects.create_user(
            username="audit-api-member",
            email="audit-api-member@example.test",
            password="pw",
        )
        cls.category = ShopCategory.objects.create(ca_id="AUD", ca_name="Audit")
        cls.product = ShopProduct.objects.create(
            it_id="AUDIT-API-PRODUCT",
            it_name="Audit API product",
            category=cls.category,
            it_price=10000,
            it_stock_qty=5,
            it_use="1",
        )
        ShopShippingPolicy.objects.update_or_create(
            pk=1,
            defaults={
                "de_send_cost_case": "차등",
                "de_send_cost_limit": "50000",
                "de_send_cost_list": "3000",
                "de_settle_min_point": 1000,
                "de_settle_max_point": 100000,
                "de_settle_point_unit": 100,
            },
        )
        Config.objects.update_or_create(name="de_bank_use", defaults={"value": "1"})
        Config.objects.update_or_create(name="de_bank_account", defaults={"value": BANK})

    def setUp(self):
        self.client = APIClient()
        token = RefreshToken.for_user(self.member).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_jwt_order_creation_records_the_member_on_order_and_line_history(self):
        cart = self.client.post(
            f"{API}/cart",
            {"it_id": self.product.it_id, "ct_qty": 1},
            format="json",
        )
        self.assertIn(cart.status_code, (200, 201), cart.content[:500])

        response = self.client.post(f"{API}/orders", ORDER_FORM, format="json")
        self.assertEqual(response.status_code, 201, response.content[:500])

        order = ShopOrder.objects.get(pk=response.json()["data"]["od_id"])
        self.assertEqual(order.history.first().history_user, self.member)
        line = ShopOrderItem.objects.get(order=order)
        self.assertEqual(line.history.first().history_user, self.member)
