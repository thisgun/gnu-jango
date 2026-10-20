"""The ct_send_cost flag of a cart line is the server's call, never the client's.

YoungCart cartupdate.php sets it from the product: 2 (무료) for it_sc_type 1, 1 (착불) for a product
with its own fee paid on delivery (it_sc_type > 1, it_sc_method 1), else 0. get_sendcost then leaves
flagged lines out of the prepaid shipping. A client that could post ct_send_cost=1 got free shipping;
these tests pin that the posted value, a tampered stored row and a stale row are all corrected.
"""

import json

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from gnu_jango.api.shop_common import SHOP_CART_SESSION_KEY, auth_cart_config_name
from gnu_jango.config.models import Config
from gnu_jango.core.test_shop_orders_more import API, ShopOrderBase
from gnu_jango.shop.models import ShopProduct
from gnu_jango.shop.shipping import cart_send_cost_flag, items_shipping_cost

DEFAULT_FEE = 3000
OWN_FEE = 7000
PASSWORD = "Str0ng-pass-99"


class SendCostFlagRuleTests(ShopOrderBase):
    def flag(self, chosen=0, **fields):
        return cart_send_cost_flag(ShopProduct(it_id="X", **fields), chosen)

    def test_the_flag_follows_the_youngcart_rule(self):
        self.assertEqual(self.flag(it_sc_type=0, it_sc_method=1), 0)
        self.assertEqual(self.flag(it_sc_type=1), 2)
        self.assertEqual(self.flag(it_sc_type=3, it_sc_method=0), 0)
        self.assertEqual(self.flag(it_sc_type=3, it_sc_method=1), 1)
        self.assertEqual(self.flag(it_sc_type=2, it_sc_method=1), 1)

    def test_a_client_value_only_counts_where_the_customer_may_choose(self):
        for chosen in (1, 2, "1", "junk", None):
            self.assertEqual(self.flag(chosen, it_sc_type=0, it_sc_method=2), 0)
            self.assertEqual(self.flag(chosen, it_sc_type=3, it_sc_method=0), 0)
        self.assertEqual(self.flag(1, it_sc_type=3, it_sc_method=2), 1)
        self.assertEqual(self.flag("1", it_sc_type=3, it_sc_method=2), 1)
        self.assertEqual(self.flag(2, it_sc_type=3, it_sc_method=2), 0)
        self.assertEqual(self.flag(0, it_sc_type=3, it_sc_method=2), 0)

    def test_a_missing_product_is_prepaid(self):
        self.assertEqual(cart_send_cost_flag(None, 1), 0)

    def test_the_shipping_sum_ignores_a_stored_flag_the_product_does_not_allow(self):
        items = [{"it_id": self.product.it_id, "line_total": 10000, "ct_qty": 1, "ct_send_cost": 1}]
        self.assertEqual(items_shipping_cost(items), DEFAULT_FEE)


class TamperedAddToCartTests(ShopOrderBase):
    def cart(self, client=None):
        return (client or self.client).get(f"{API}/cart").json()["data"]

    def test_a_posted_collect_flag_does_not_waive_the_shop_fee(self):
        self.add(self.client, ct_send_cost=1)

        cart = self.cart()
        self.assertEqual(cart["items"][0]["ct_send_cost"], 0)
        self.assertEqual(cart["send_cost"], DEFAULT_FEE)
        order = self.place_ok()
        self.assertEqual(order.od_send_cost, DEFAULT_FEE)
        self.assertEqual(order.od_misu, 10000 + DEFAULT_FEE)
        self.assertEqual(order.items.get().ct_send_cost, 0)

    def test_a_posted_free_flag_does_not_waive_a_products_own_fee(self):
        product = self.make_product("SF001", "Own fee", it_price=30000, it_stock_qty=10, it_sc_type=3, it_sc_price=OWN_FEE)
        self.add(self.guest, product, ct_send_cost=2)

        self.assertEqual(self.cart(self.guest)["send_cost"], OWN_FEE)
        self.assertEqual(self.guest.session[SHOP_CART_SESSION_KEY][0]["ct_send_cost"], 0)
        order = self.place_ok(self.guest, od_pwd="guest-pass")
        self.assertEqual(order.od_send_cost, OWN_FEE)

    def test_the_quote_also_charges_the_fee(self):
        self.add(self.client, ct_send_cost=1)
        data = self.client.get(f"{API}/shipping/quote").json()["data"]
        self.assertEqual(data["base"], DEFAULT_FEE)


class FreeAndCollectProductTests(ShopOrderBase):
    def test_a_free_shipping_product_is_flagged_free_and_ships_free(self):
        product = self.make_product("SF010", "Free", it_price=10000, it_stock_qty=10, it_sc_type=1)
        self.add(self.client, product)

        cart = self.client.get(f"{API}/cart").json()["data"]
        self.assertEqual(cart["items"][0]["ct_send_cost"], 2)
        self.assertEqual(cart["send_cost"], 0)
        order = self.place_ok()
        self.assertEqual(order.od_send_cost, 0)
        self.assertEqual(order.items.get().ct_send_cost, 2)

    def test_a_collect_on_delivery_product_adds_no_prepaid_shipping(self):
        # the client sends no flag: the server still knows the fee is paid to the courier
        product = self.make_product(
            "SF011", "Collect", it_price=10000, it_stock_qty=10, it_sc_type=3, it_sc_method=1, it_sc_price=OWN_FEE
        )
        self.add(self.client, product)

        cart = self.client.get(f"{API}/cart").json()["data"]
        self.assertEqual(cart["items"][0]["ct_send_cost"], 1)
        self.assertEqual(cart["send_cost"], 0)
        order = self.place_ok()
        self.assertEqual(order.od_send_cost, 0)
        self.assertEqual(order.od_misu, 10000)
        self.assertEqual(order.items.get().ct_send_cost, 1)

    def test_a_collect_line_beside_a_prepaid_line_only_charges_the_prepaid_one(self):
        collect = self.make_product(
            "SF012", "Collect", it_price=10000, it_stock_qty=10, it_sc_type=3, it_sc_method=1, it_sc_price=OWN_FEE
        )
        self.add(self.client, collect)
        self.add(self.client)

        order = self.place_ok()
        self.assertEqual(order.od_send_cost, DEFAULT_FEE)
        self.assertEqual(sorted(order.items.values_list("ct_send_cost", flat=True)), [0, 1])

    def test_a_customer_choice_product_keeps_the_choice_between_prepaid_and_collect(self):
        product = self.make_product(
            "SF013", "Choice", it_price=10000, it_stock_qty=10, it_sc_type=3, it_sc_method=2, it_sc_price=OWN_FEE
        )
        self.add(self.client, product, ct_send_cost=1)
        self.assertEqual(self.place_ok().od_send_cost, 0)

        self.add(self.client, product, ct_send_cost=2)
        order = self.place_ok()
        self.assertEqual(order.od_send_cost, OWN_FEE)
        self.assertEqual(order.items.get().ct_send_cost, 0)


class StoredRowCorrectionTests(ShopOrderBase):
    def member_rows(self):
        return json.loads(Config.objects.get(name=auth_cart_config_name(self.member)).value)

    def tamper_member_cart(self, flag):
        rows = self.member_rows()
        rows[0]["ct_send_cost"] = flag
        Config.objects.filter(name=auth_cart_config_name(self.member)).update(value=json.dumps(rows))

    def test_a_tampered_member_row_is_charged_at_order_time(self):
        self.add(self.client)
        self.tamper_member_cart(1)

        order = self.place_ok()
        self.assertEqual(order.od_send_cost, DEFAULT_FEE)
        self.assertEqual(order.items.get().ct_send_cost, 0)

    def test_a_tampered_guest_session_row_is_charged_at_order_time(self):
        self.add(self.guest)
        session = self.guest.session
        rows = session[SHOP_CART_SESSION_KEY]
        rows[0]["ct_send_cost"] = 2
        session[SHOP_CART_SESSION_KEY] = rows
        session.save()

        order = self.place_ok(self.guest, od_pwd="guest-pass")
        self.assertEqual(order.od_send_cost, DEFAULT_FEE)

    def test_a_product_switched_to_collect_after_it_was_added_is_not_prepaid(self):
        product = self.make_product("SF020", "Later collect", it_price=10000, it_stock_qty=10, it_sc_type=3, it_sc_price=OWN_FEE)
        self.add(self.client, product)
        ShopProduct.objects.filter(pk=product.pk).update(it_sc_method=1)

        order = self.place_ok()
        self.assertEqual(order.od_send_cost, 0)
        self.assertEqual(order.items.get().ct_send_cost, 1)

    def test_saving_the_cart_rewrites_a_tampered_flag(self):
        self.add(self.client)
        self.tamper_member_cart(1)
        ct_id = self.member_rows()[0]["ct_id"]

        response = self.client.patch(f"{API}/cart/{ct_id}", {"ct_qty": 2}, format="json")

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(self.member_rows()[0]["ct_send_cost"], 0)

    def test_a_tampered_guest_row_is_recomputed_when_merged_at_login(self):
        get_user_model().objects.create_user(username="flag-login", email="flag-login@example.test", password=PASSWORD)
        client = APIClient()
        session = client.session
        session[SHOP_CART_SESSION_KEY] = [{"ct_id": "1", "it_id": self.product.it_id, "ct_qty": 1, "ct_send_cost": 1}]
        session.save()

        response = client.post("/api/v1/auth/login", {"mb_id": "flag-login", "mb_password": PASSWORD}, format="json")

        self.assertEqual(response.status_code, 200, response.content[:200])
        user = get_user_model().objects.get(username="flag-login")
        rows = json.loads(Config.objects.get(name=auth_cart_config_name(user)).value)
        self.assertEqual(rows[0]["ct_send_cost"], 0)
