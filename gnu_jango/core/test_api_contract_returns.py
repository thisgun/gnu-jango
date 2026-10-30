"""OpenAPI contract tests for the customer return / exchange requests (gnu_jango/api/contracts/returns.py)."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.core.contract_testing import ContractAssertions
from gnu_jango.shop import returns
from gnu_jango.shop.models import ShopOrder, ShopOrderItem, ShopProduct

RETURNS = "/api/v1/shop/orders/{od_id}/returns"
WITHDRAW = "/api/v1/shop/orders/{od_id}/returns/{request_id}/withdraw"

CONTRACT_OPERATIONS = {
    ("GET", RETURNS),
    ("POST", RETURNS),
    ("POST", WITHDRAW),
}


class ShopReturnContractTests(ContractAssertions, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.member = get_user_model().objects.create(username="contract-returner")
        product = ShopProduct.objects.create(it_id="RC001", it_name="반품 상품", it_price=5000, it_stock_qty=10)
        cls.order = ShopOrder.objects.create(
            od_id="2026103000000000000009",
            user=cls.member,
            od_name="구매자",
            od_status="완료",
            od_settle_case="무통장",
            od_cart_price=13000,
            od_receipt_price=13000,
        )
        cls.delivered = ShopOrderItem.objects.create(
            order=cls.order, product=product, ct_id="1", it_id="RC001", it_name="반품 상품",
            ct_price=5000, ct_qty=2, ct_status="완료", stock_adjusted=True,
        )
        cls.shipping = ShopOrderItem.objects.create(
            order=cls.order, product=product, ct_id="2", it_id="RC001", it_name="반품 상품", ct_option="빨강",
            ct_price=3000, ct_qty=1, ct_status="배송", stock_adjusted=True,
        )
        ShopOrderItem.objects.filter(pk=cls.delivered.pk).update(ct_complete_time=timezone.now() - timedelta(days=1))

    def setUp(self):
        cache.clear()
        self.api = APIClient()
        self.api.force_authenticate(self.member)
        self.url = RETURNS.format(od_id=self.order.od_id)

    def test_the_return_state_without_requests_matches_the_contract(self):
        response = self.api.get(self.url)

        data = response.json()["data"]
        self.assertEqual([line["eligible"] for line in data["lines"]], [True, True])
        self.assertEqual(data["lines"][1]["deadline"], "")
        self.assertMatchesContract(response, RETURNS)

    def test_a_new_request_matches_the_contract(self):
        response = self.api.post(
            self.url,
            {"kind": "exchange", "reason": "wrong_item", "lines": [{"line_id": self.delivered.pk, "qty": 1}]},
            format="json",
        )

        self.assertEqual(response.json()["data"]["requests"][0]["status"], "requested")
        self.assertMatchesContract(response, RETURNS, method="post", status="201")

    def test_a_withdrawn_request_and_closed_requests_match_the_contract(self):
        rejected = returns.create_request(
            self.order, kind="return", reason="defective", lines=[{"line_id": self.shipping.pk, "qty": 1}], user=self.member
        )
        returns.reject_request(rejected.pk, "회수할 수 없는 상품입니다.", actor="admin")
        waiting = returns.create_request(
            self.order, kind="return", reason="change_of_mind", lines=[{"line_id": self.delivered.pk, "qty": 2}], user=self.member
        )

        response = self.api.post(WITHDRAW.format(od_id=self.order.od_id, request_id=waiting.pk), format="json")

        statuses = [request["status"] for request in response.json()["data"]["requests"]]
        self.assertEqual(statuses, ["withdrawn", "rejected"])
        self.assertMatchesContract(response, WITHDRAW, method="post")
