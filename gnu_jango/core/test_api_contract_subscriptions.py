"""OpenAPI contract tests for the 정기구독 API (gnu_jango/api/contracts/subscriptions.py)."""

from unittest.mock import patch

from gnu_jango.core.contract_testing import ContractAssertions
from gnu_jango.core.test_shop_subscriptions import (
    AUTH_URL,
    CHARGE,
    ISSUE,
    LIST_URL,
    SubscriptionTestBase,
    approved,
    billing_object,
)

LIST = "/api/v1/shop/subscriptions"
DETAIL = "/api/v1/shop/subscriptions/{id}"
START = "/api/v1/shop/subscriptions/start"
CARD = "/api/v1/shop/subscriptions/{id}/card"
BILLING_AUTH = "/api/v1/shop/subscriptions/billing-auth"
ACTION = "/api/v1/shop/subscriptions/{id}/action"

CONTRACT_OPERATIONS = {
    ("GET", LIST),
    ("GET", DETAIL),
    ("POST", START),
    ("POST", CARD),
    ("POST", BILLING_AUTH),
    ("POST", ACTION),
}


class SubscriptionContractTests(ContractAssertions, SubscriptionTestBase):
    def test_start_and_billing_auth_match_their_contracts(self):
        response = self.start()
        self.assertMatchesContract(response, START, method="post", status="201")
        registration = response.json()["data"]
        with patch(ISSUE, return_value=billing_object(registration["customer_key"])), patch(CHARGE, side_effect=approved()):
            response = self.client.post(AUTH_URL, {
                "registration_token": registration["registration_token"],
                "authKey": "auth_fake",
                "customerKey": registration["customer_key"],
            }, format="json")
        self.assertMatchesContract(response, BILLING_AUTH, method="post")

    def test_list_detail_card_and_action_match_their_contracts(self):
        sub, _ = self.subscribe()
        self.assertMatchesContract(self.client.get(LIST_URL), LIST)
        self.assertMatchesContract(self.client.get(f"{LIST_URL}/{sub.pk}"), DETAIL)
        self.assertMatchesContract(self.client.post(f"{LIST_URL}/{sub.pk}/card", {}, format="json"), CARD, method="post")
        paused = self.client.post(f"{LIST_URL}/{sub.pk}/action", {"action": "pause"}, format="json")
        self.assertMatchesContract(paused, ACTION, method="post")
        cancelled = self.client.post(f"{LIST_URL}/{sub.pk}/action", {"action": "cancel"}, format="json")
        self.assertMatchesContract(cancelled, ACTION, method="post")

    def test_product_detail_with_a_subscription_offer_matches_its_contract(self):
        response = self.client.get(f"/api/v1/shop/products/{self.product.it_id}")
        self.assertIsNotNone(response.json()["data"]["subscription"])
        self.assertMatchesContract(response, "/api/v1/shop/products/{it_id}")
