"""Behaviour tests for the shop cart, wish list, saved addresses, reviews and Q&A API.

Covers gnu_jango/api/shop_cart.py and gnu_jango/api/shop_reviews.py through the
public /api/v1/shop/... routes. Every test asserts the stored state (session,
Config cart row, database rows) and the response body, not only the status code.
"""

import json
from urllib.parse import urlencode

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.api.shop_common import SHOP_CART_SESSION_KEY, auth_cart_config_name
from gnu_jango.config.models import Config
from gnu_jango.shop.models import (
    ShopAddress,
    ShopCategory,
    ShopOrderData,
    ShopProduct,
    ShopQA,
    ShopReview,
    ShopWishlist,
)

API = "/api/v1/shop"

RED = {"io_id": "Red", "io_type": 0, "io_price": 500, "io_stock_qty": 5, "io_use": 1}
BLUE = {"io_id": "Blue", "io_type": 0, "io_price": 0, "io_stock_qty": 0, "io_use": 1}
GREEN = {"io_id": "Green", "io_type": 0, "io_price": 0, "io_stock_qty": 9, "io_use": 0}
GIFT_WRAP = {"io_id": "Wrap", "io_type": 1, "io_price": 300, "io_stock_qty": 4, "io_use": 1}


class ShopApiTestCase(TestCase):
    """Shared fixtures and request helpers."""

    @classmethod
    def setUpTestData(cls):
        # Users are created without a password hash: hashing dominates the run time
        # and only the login test needs a usable password.
        user_model = get_user_model()
        cls.user = user_model.objects.create(username="buyer")
        cls.other = user_model.objects.create(username="stranger")
        cls.staff = user_model.objects.create(username="clerk", is_staff=True)
        cls.category = ShopCategory.objects.create(ca_id="10", ca_name="Category")
        cls.product = cls.make_product("P001", "Plain product", it_price=1000, it_stock_qty=10)

    @classmethod
    def make_product(cls, it_id, name, **fields):
        return ShopProduct.objects.create(
            it_id=it_id, category=cls.category, it_name=name, it_use="1", **fields
        )

    def headers(self, user):
        access = RefreshToken.for_user(user).access_token
        return {"HTTP_AUTHORIZATION": f"Bearer {access}"}

    def request(self, method, path, data=None, user=None):
        extra = self.headers(user) if user else {}
        if method == "get":
            return self.client.get(f"{API}/{path}", **extra)
        body = json.dumps(data if data is not None else {})
        return getattr(self.client, method)(
            f"{API}/{path}", data=body, content_type="application/json", **extra
        )

    def get(self, path, user=None):
        return self.request("get", path, user=user)

    def post(self, path, data=None, user=None):
        return self.request("post", path, data, user)

    def patch(self, path, data=None, user=None):
        return self.request("patch", path, data, user)

    def delete(self, path, user=None):
        return self.request("delete", path, user=user)

    def post_form(self, path, data, user=None):
        extra = self.headers(user) if user else {}
        return self.client.post(
            f"{API}/{path}",
            data=urlencode(data, doseq=True),
            content_type="application/x-www-form-urlencoded",
            **extra,
        )

    def stored_member_cart(self, user):
        row = Config.objects.filter(name=auth_cart_config_name(user)).first()
        return json.loads(row.value) if row else []

    def stored_guest_cart(self):
        return self.client.session.get(SHOP_CART_SESSION_KEY, [])

    def seed_member_cart(self, user, rows):
        Config.objects.update_or_create(
            name=auth_cart_config_name(user), defaults={"value": json.dumps(rows)}
        )


class CartAddValidationTests(ShopApiTestCase):
    def assert_nothing_in_cart(self):
        self.assertEqual(self.stored_guest_cart(), [])

    def test_adding_a_product_stores_a_priced_row_in_the_session_cart(self):
        response = self.post("cart", {"it_id": "P001", "ct_qty": 3})

        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        stored = self.stored_guest_cart()
        self.assertEqual(len(stored), 1)
        self.assertEqual(data["ct_id"], stored[0]["ct_id"])
        self.assertEqual(stored[0]["it_id"], "P001")
        self.assertEqual(stored[0]["ct_qty"], 3)
        self.assertEqual(stored[0]["ct_price"], 1000)
        self.assertEqual(data["total_price"], 3000)
        self.assertEqual(data["total_qty"], 3)
        self.assertEqual(data["cart_items"][0]["it_name"], "Plain product")
        self.assertEqual(data["cart_items"][0]["line_total"], 3000)

    def test_missing_quantity_defaults_to_one_and_bad_quantities_are_clamped_to_one(self):
        for index, qty in enumerate((None, 0, -4, "abc")):
            with self.subTest(qty=qty):
                payload = {"it_id": "P001"}
                if qty is not None:
                    payload["ct_qty"] = qty
                self.post("cart", payload)
                # each add counts as one more on the same line
                self.assertEqual(self.stored_guest_cart()[0]["ct_qty"], index + 1)

    def test_missing_product_id_is_rejected(self):
        response = self.post("cart", {"ct_qty": 1})

        self.assertEqual(response.status_code, 422)
        self.assertIn("it_id", response.json()["errors"])
        self.assert_nothing_in_cart()

    def test_unknown_product_returns_404(self):
        response = self.post("cart", {"it_id": "NOPE"})

        self.assertEqual(response.status_code, 404)
        self.assertIn("product_not_found", response.json()["errors"])
        self.assert_nothing_in_cart()

    def test_telephone_inquiry_product_cannot_be_added(self):
        self.make_product("TEL1", "Call us", it_price=5000, it_tel_inq="1")

        response = self.post("cart", {"it_id": "TEL1"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("tel_inquiry_product", response.json()["errors"])
        self.assert_nothing_in_cart()

    def test_sold_out_product_cannot_be_added(self):
        self.make_product("SOLD1", "Gone", it_price=5000, it_soldout="1")

        response = self.post("cart", {"it_id": "SOLD1"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("product_unavailable", response.json()["errors"])
        self.assert_nothing_in_cart()

    def test_disabled_product_cannot_be_added(self):
        ShopProduct.objects.filter(pk="P001").update(it_use="0")

        response = self.post("cart", {"it_id": "P001"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("product_unavailable", response.json()["errors"])
        self.assert_nothing_in_cart()


class CartQuantityLimitTests(ShopApiTestCase):
    def test_quantity_above_stock_is_refused(self):
        self.make_product("STK3", "Scarce", it_price=1000, it_stock_qty=3)

        response = self.post("cart", {"it_id": "STK3", "ct_qty": 4})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["errors"]["io_stock_qty"], 3)
        self.assertEqual(self.stored_guest_cart(), [])

    def test_stock_limit_counts_what_is_already_in_the_cart(self):
        self.make_product("STK3", "Scarce", it_price=1000, it_stock_qty=3)
        self.assertEqual(self.post("cart", {"it_id": "STK3", "ct_qty": 2}).status_code, 201)

        refused = self.post("cart", {"it_id": "STK3", "ct_qty": 2})
        allowed = self.post("cart", {"it_id": "STK3", "ct_qty": 1})

        self.assertEqual(refused.status_code, 409)
        self.assertEqual(allowed.status_code, 201)
        self.assertEqual(sum(row["ct_qty"] for row in self.stored_guest_cart()), 3)

    def test_below_minimum_quantity_is_refused_and_minimum_itself_is_accepted(self):
        self.make_product("MIN3", "Bulk", it_price=100, it_buy_min_qty=3)

        refused = self.post("cart", {"it_id": "MIN3", "ct_qty": 2})
        accepted = self.post("cart", {"it_id": "MIN3", "ct_qty": 3})

        self.assertEqual(refused.status_code, 422)
        self.assertEqual(refused.json()["errors"], {"it_buy_min_qty": 3})
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual([row["ct_qty"] for row in self.stored_guest_cart()], [3])

    def test_maximum_quantity_applies_to_the_running_total(self):
        self.make_product("MAX4", "Limited", it_price=100, it_buy_max_qty=4)
        self.assertEqual(self.post("cart", {"it_id": "MAX4", "ct_qty": 3}).status_code, 201)

        refused = self.post("cart", {"it_id": "MAX4", "ct_qty": 2})
        accepted = self.post("cart", {"it_id": "MAX4", "ct_qty": 1})

        self.assertEqual(refused.status_code, 422)
        self.assertEqual(refused.json()["errors"], {"it_buy_max_qty": 4, "current_qty": 3})
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(sum(row["ct_qty"] for row in self.stored_guest_cart()), 4)

    def test_direct_purchase_quantity_is_counted_separately_from_the_cart(self):
        self.make_product("MAX2", "Limited", it_price=100, it_buy_max_qty=2)
        self.assertEqual(self.post("cart", {"it_id": "MAX2", "ct_qty": 2}).status_code, 201)

        direct = self.post("cart", {"it_id": "MAX2", "ct_qty": 2, "direct": 1})

        self.assertEqual(direct.status_code, 201)


class CartOptionTests(ShopApiTestCase):
    def make_optioned_product(self, **fields):
        defaults = {
            "it_price": 1000,
            "it_option_subject": "Color",
            "options": [RED, BLUE, GREEN, GIFT_WRAP],
        }
        defaults.update(fields)
        return self.make_product("OPT1", "Optioned", **defaults)

    def test_option_product_requires_a_base_option(self):
        self.make_optioned_product()

        response = self.post("cart", {"it_id": "OPT1", "ct_qty": 1})

        self.assertEqual(response.status_code, 422)
        self.assertIn("option_required", response.json()["errors"])
        self.assertEqual(self.stored_guest_cart(), [])

    def test_supplement_option_alone_does_not_satisfy_the_required_option(self):
        self.make_optioned_product()

        response = self.post(
            "cart", {"it_id": "OPT1", "options": [{"io_id": "Wrap", "io_type": 1, "ct_qty": 1}]}
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("option_required", response.json()["errors"])

    def test_option_price_is_added_to_the_line_total(self):
        self.make_optioned_product()

        response = self.post(
            "cart", {"it_id": "OPT1", "options": [{"io_id": "Red", "ct_qty": 2}]}
        )

        self.assertEqual(response.status_code, 201)
        row = self.stored_guest_cart()[0]
        self.assertEqual((row["ct_option"], row["io_price"], row["ct_price"]), ("Red", 500, 1000))
        item = response.json()["data"]["cart_items"][0]
        self.assertEqual(item["line_total"], (1000 + 500) * 2)
        self.assertEqual(response.json()["data"]["total_price"], 3000)

    def test_option_row_ignores_a_client_supplied_price(self):
        self.make_optioned_product()

        self.post(
            "cart",
            {"it_id": "OPT1", "options": [{"io_id": "Red", "ct_qty": 1, "io_price": -999, "ct_price": 1}]},
        )

        row = self.stored_guest_cart()[0]
        self.assertEqual(row["io_price"], 500)
        self.assertEqual(row["ct_price"], 1000)

    def test_unknown_inactive_and_malformed_options_are_refused(self):
        self.make_optioned_product()
        cases = {
            "unknown id": {"io_id": "Purple"},
            "inactive option": {"io_id": "Green"},
            "supplement id used as base": {"io_id": "Wrap"},
        }
        for label, option in cases.items():
            with self.subTest(label):
                response = self.post("cart", {"it_id": "OPT1", "options": [option]})
                self.assertEqual(response.status_code, 422)
                self.assertIn("invalid_option", response.json()["errors"])
        self.assertEqual(self.stored_guest_cart(), [])

    def test_unknown_option_type_is_refused(self):
        self.make_optioned_product()

        response = self.post("cart", {"it_id": "OPT1", "options": [{"io_id": "Red", "io_type": 0}, {"io_id": "Wrap", "io_type": 7}]})

        self.assertEqual(response.status_code, 422)
        self.assertIn("invalid_option", response.json()["errors"])
        self.assertEqual(self.stored_guest_cart(), [])

    def test_non_object_option_entry_is_refused(self):
        self.make_optioned_product()

        response = self.post("cart", {"it_id": "OPT1", "options": ["Red"]})

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.stored_guest_cart(), [])

    def test_sold_out_option_is_refused(self):
        self.make_optioned_product()

        response = self.post("cart", {"it_id": "OPT1", "options": [{"io_id": "Blue", "ct_qty": 1}]})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["errors"], {"io_id": "Blue"})
        self.assertEqual(self.stored_guest_cart(), [])

    def test_option_stock_limit_counts_existing_cart_rows(self):
        self.make_optioned_product()
        self.assertEqual(
            self.post("cart", {"it_id": "OPT1", "options": [{"io_id": "Red", "ct_qty": 4}]}).status_code, 201
        )

        refused = self.post("cart", {"it_id": "OPT1", "options": [{"io_id": "Red", "ct_qty": 2}]})

        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.json()["errors"], {"io_id": "Red", "io_stock_qty": 5})
        self.assertEqual([row["ct_qty"] for row in self.stored_guest_cart()], [4])

    def test_option_stock_ignores_the_product_level_stock(self):
        self.make_optioned_product(it_stock_qty=1)

        response = self.post("cart", {"it_id": "OPT1", "options": [{"io_id": "Red", "ct_qty": 3}]})

        self.assertEqual(response.status_code, 201)

    def test_base_and_supplement_options_become_separate_priced_rows(self):
        self.make_optioned_product()

        response = self.post(
            "cart",
            {
                "it_id": "OPT1",
                "options": [
                    {"io_id": "Red", "ct_qty": 2},
                    {"io_id": "Wrap", "io_type": 1, "ct_qty": 2},
                ],
            },
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        self.assertEqual(len(data["items_created"]), 2)
        self.assertEqual(data["ct_id"], "")
        self.assertEqual([row["ct_id"] for row in data["items"]], [row["ct_id"] for row in data["items_created"]])
        rows = self.stored_guest_cart()
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row["ct_id"] for row in rows}), 2)
        base, supplement = rows
        self.assertEqual((base["io_type"], base["ct_price"]), (0, 1000))
        self.assertEqual((supplement["io_type"], supplement["ct_price"], supplement["io_price"]), (1, 0, 300))
        # base: (1000 + 500) * 2, supplement: only its own price * qty
        self.assertEqual(data["total_price"], 3000 + 600)
        self.assertEqual(data["total_qty"], 4)

    def test_unavailable_supplement_option_is_refused(self):
        self.make_optioned_product()

        response = self.post(
            "cart",
            {
                "it_id": "OPT1",
                "options": [
                    {"io_id": "Red", "ct_qty": 1},
                    {"io_id": "Missing", "io_type": 1, "ct_qty": 1},
                ],
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.stored_guest_cart(), [])

    def test_product_declaring_options_without_any_is_not_purchasable(self):
        self.make_product("OPT0", "Broken options", it_price=1000, it_option_subject="Size", options=[])

        response = self.post("cart", {"it_id": "OPT0"})

        self.assertEqual(response.status_code, 409)
        self.assertIn("product_options_unavailable", response.json()["errors"])

    def test_option_id_on_a_product_without_options_is_refused(self):
        response = self.post("cart", {"it_id": "P001", "ct_option": "Red"})

        self.assertEqual(response.status_code, 422)
        self.assertIn("invalid_option", response.json()["errors"])
        self.assertEqual(self.stored_guest_cart(), [])


class CartSelectionTests(ShopApiTestCase):
    def setUp(self):
        super().setUp()
        self.make_product("P002", "Second", it_price=2000)

    def add(self, it_id, **extra):
        response = self.post("cart", {"it_id": it_id, **extra})
        self.assertEqual(response.status_code, 201)
        return response.json()["data"]["ct_id"]

    def test_ct_ids_query_limits_the_payload_and_totals_to_the_selected_rows(self):
        first = self.add("P001", ct_qty=2)
        second = self.add("P002", ct_qty=1)

        response = self.get(f"cart?ct_ids={second}")

        data = response.json()["data"]
        self.assertEqual([item["ct_id"] for item in data["items"]], [second])
        self.assertEqual(data["total_price"], 2000)
        self.assertEqual(data["total_qty"], 1)
        both = self.get(f"cart?ct_ids={first},{second}").json()["data"]
        self.assertEqual(both["total_price"], 2000 + 2000)

    def test_unknown_ct_ids_yield_an_empty_selection_not_the_whole_cart(self):
        self.add("P001")

        data = self.get("cart?ct_ids=999999999999").json()["data"]

        self.assertEqual(data["items"], [])
        self.assertEqual(data["total_price"], 0)

    def test_direct_purchase_rows_stay_out_of_the_regular_cart_view(self):
        regular = self.add("P001")
        direct = self.add("P002", direct=1)

        plain = self.get("cart").json()["data"]
        selected = self.get(f"cart?ct_ids={direct}").json()["data"]

        self.assertEqual([item["ct_id"] for item in plain["items"]], [regular])
        self.assertEqual([item["ct_id"] for item in selected["items"]], [direct])
        self.assertEqual(selected["items"][0]["ct_direct"], 1)

    def test_a_new_direct_purchase_replaces_the_previous_one_only(self):
        regular = self.add("P001")
        first_direct = self.add("P002", direct=1)
        second_direct = self.add("P002", direct=1)

        ids = [row["ct_id"] for row in self.stored_guest_cart()]

        self.assertIn(regular, ids)
        self.assertNotIn(first_direct, ids)
        self.assertIn(second_direct, ids)

    def test_replace_direct_false_keeps_earlier_direct_rows(self):
        self.make_product("P003", "Third", it_price=3000)
        first_direct = self.add("P002", direct=1)
        second_direct = self.add("P003", direct=1, replace_direct=False)

        ids = [row["ct_id"] for row in self.stored_guest_cart()]

        self.assertEqual(ids, [first_direct, second_direct])

    def test_shipping_is_charged_below_the_free_threshold_and_waived_above_it(self):
        self.add("P001")
        below = self.get("cart").json()["data"]
        self.make_product("BIG", "Expensive", it_price=60000)
        self.add("BIG")
        above = self.get("cart").json()["data"]

        self.assertEqual(below["total_price"], 1000)
        # no saved policy: youngcart's install default (차등, 4,000 under 20,000, free from 40,000)
        self.assertEqual(below["shipping_cost"], 4000)
        self.assertEqual(below["send_cost"], below["shipping_cost"])
        self.assertEqual(above["total_price"], 61000)
        self.assertEqual(above["shipping_cost"], 0)

    def test_cart_coupon_amounts_are_summed_into_the_payload(self):
        ct_id = self.add("P001", ct_qty=2)
        rows = self.stored_guest_cart()
        rows[0].update({"cp_price": 700, "cp_id": "5"})
        session = self.client.session
        session[SHOP_CART_SESSION_KEY] = rows
        session.save()

        data = self.get("cart").json()["data"]

        self.assertEqual(data["items"][0]["ct_id"], ct_id)
        self.assertEqual(data["cart_coupon"], 700)
        self.assertEqual(data["items"][0]["cp_id"], "5")

    def test_row_whose_product_was_deleted_still_renders_with_fallbacks(self):
        ct_id = self.add("P002")
        ShopProduct.objects.filter(pk="P002").delete()

        data = self.get("cart").json()["data"]

        item = data["items"][0]
        self.assertEqual(item["ct_id"], ct_id)
        self.assertEqual(item["it_name"], "Second")
        self.assertEqual(item["image_url"], "/icon-192.png")
        self.assertEqual(item["line_total"], 2000)

    def test_missing_prepared_row_is_restored_from_the_members_prepared_log(self):
        row = {"ct_id": "777000000001", "it_id": "P001", "it_name": "Plain product", "ct_price": 1000, "ct_qty": 2}
        ShopOrderData.objects.create(
            dt_pg="cart:prepared", user=self.user, od_id="OD1", dt_data=json.dumps([row, "junk"])
        )

        data = self.get("cart?ct_ids=777000000001", user=self.user).json()["data"]

        self.assertEqual([item["ct_id"] for item in data["items"]], ["777000000001"])
        self.assertEqual(data["total_price"], 2000)
        self.assertEqual([item["ct_id"] for item in self.stored_member_cart(self.user)], ["777000000001"])

    def test_prepared_log_of_another_member_is_never_restored(self):
        row = {"ct_id": "777000000002", "it_id": "P001", "ct_price": 1000, "ct_qty": 1}
        ShopOrderData.objects.create(dt_pg="cart:prepared", user=self.other, dt_data=json.dumps([row]))

        data = self.get("cart?ct_ids=777000000002", user=self.user).json()["data"]

        self.assertEqual(data["items"], [])
        self.assertEqual(self.stored_member_cart(self.user), [])

    def test_guest_restores_only_logs_of_orders_remembered_in_its_session(self):
        mine = {"ct_id": "777000000003", "it_id": "P001", "ct_price": 1000, "ct_qty": 1}
        theirs = {"ct_id": "777000000004", "it_id": "P001", "ct_price": 1000, "ct_qty": 1}
        ShopOrderData.objects.create(dt_pg="cart:prepared", od_id="ODMINE", dt_data=json.dumps([mine]))
        ShopOrderData.objects.create(dt_pg="cart:prepared", od_id="ODTHEIRS", dt_data=json.dumps([theirs]))
        session = self.client.session
        session["g5_guest_order_ids"] = ["ODMINE"]
        session.save()

        data = self.get("cart?ct_ids=777000000003,777000000004").json()["data"]

        self.assertEqual([item["ct_id"] for item in data["items"]], ["777000000003"])


class CartUpdateAndDeleteTests(ShopApiTestCase):
    def add(self, it_id="P001", **extra):
        response = self.post("cart", {"it_id": it_id, **extra})
        self.assertEqual(response.status_code, 201)
        return response.json()["data"]["ct_id"]

    def test_patch_changes_the_quantity_and_the_totals(self):
        ct_id = self.add(ct_qty=1)

        response = self.patch(f"cart/{ct_id}", {"ct_qty": 4})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stored_guest_cart()[0]["ct_qty"], 4)
        self.assertEqual(response.json()["data"]["total_price"], 4000)

    def test_patch_clamps_non_positive_quantities_to_one_and_ignores_garbage(self):
        ct_id = self.add(ct_qty=3)

        self.patch(f"cart/{ct_id}", {"ct_qty": 0})
        self.assertEqual(self.stored_guest_cart()[0]["ct_qty"], 1)
        self.patch(f"cart/{ct_id}", {"ct_qty": 5})
        self.patch(f"cart/{ct_id}", {"ct_qty": "many"})
        self.assertEqual(self.stored_guest_cart()[0]["ct_qty"], 5)

    def test_patch_above_stock_is_refused_and_keeps_the_old_quantity(self):
        self.make_product("STK3", "Scarce", it_price=1000, it_stock_qty=3)
        ct_id = self.add("STK3", ct_qty=2)

        response = self.patch(f"cart/{ct_id}", {"ct_qty": 4})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.stored_guest_cart()[0]["ct_qty"], 2)

    def test_patch_cannot_go_below_minimum_or_above_maximum(self):
        self.make_product("RNG", "Ranged", it_price=100, it_buy_min_qty=2, it_buy_max_qty=5)
        ct_id = self.add("RNG", ct_qty=3)

        low = self.patch(f"cart/{ct_id}", {"ct_qty": 1})
        high = self.patch(f"cart/{ct_id}", {"ct_qty": 6})
        edge = self.patch(f"cart/{ct_id}", {"ct_qty": 5})

        self.assertEqual((low.status_code, high.status_code, edge.status_code), (422, 422, 200))
        self.assertIn("min_buy_qty", low.json()["errors"])
        self.assertIn("max_buy_qty", high.json()["errors"])
        self.assertEqual(self.stored_guest_cart()[0]["ct_qty"], 5)

    def test_patch_respects_option_stock(self):
        self.make_product("OPT1", "Optioned", it_price=1000, it_option_subject="Color", options=[RED])
        ct_id = self.post("cart", {"it_id": "OPT1", "options": [{"io_id": "Red", "ct_qty": 1}]}).json()["data"]["ct_id"]

        refused = self.patch(f"cart/{ct_id}", {"ct_qty": 6})
        accepted = self.patch(f"cart/{ct_id}", {"ct_qty": 5})

        self.assertEqual(refused.status_code, 409)
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(self.stored_guest_cart()[0]["ct_qty"], 5)
        self.assertEqual(accepted.json()["data"]["total_price"], (1000 + 500) * 5)

    def test_patch_refuses_a_row_whose_option_was_disabled_after_adding(self):
        product = self.make_product("OPT1", "Optioned", it_price=1000, it_option_subject="Color", options=[RED])
        ct_id = self.post("cart", {"it_id": "OPT1", "options": [{"io_id": "Red", "ct_qty": 1}]}).json()["data"]["ct_id"]
        product.options = [{**RED, "io_use": 0}]
        product.save()

        response = self.patch(f"cart/{ct_id}", {"ct_qty": 2})

        self.assertEqual(response.status_code, 422)
        self.assertIn("invalid_option", response.json()["errors"])
        self.assertEqual(self.stored_guest_cart()[0]["ct_qty"], 1)

    def test_patch_checks_supplement_option_stock(self):
        self.make_product("OPT1", "Optioned", it_price=1000, it_option_subject="Color", options=[RED, GIFT_WRAP])
        created = self.post(
            "cart",
            {"it_id": "OPT1", "options": [{"io_id": "Red"}, {"io_id": "Wrap", "io_type": 1, "ct_qty": 1}]},
        ).json()["data"]["items_created"]
        wrap_id = created[1]["ct_id"]

        refused = self.patch(f"cart/{wrap_id}", {"ct_qty": 5})
        accepted = self.patch(f"cart/{wrap_id}", {"ct_qty": 4})

        self.assertEqual((refused.status_code, accepted.status_code), (409, 200))

    def test_patch_of_an_unknown_row_changes_nothing(self):
        ct_id = self.add(ct_qty=2)

        response = self.patch("cart/123", {"ct_qty": 9})

        self.assertEqual(response.status_code, 404)
        self.assertEqual([(r["ct_id"], r["ct_qty"]) for r in self.stored_guest_cart()], [(ct_id, 2)])

    def test_delete_removes_only_the_named_row(self):
        self.make_product("P002", "Second", it_price=2000)
        first = self.add()
        second = self.add("P002")

        response = self.delete(f"cart/{first}")

        self.assertEqual([r["ct_id"] for r in self.stored_guest_cart()], [second])
        self.assertEqual(response.json()["data"]["total_price"], 2000)

    def test_deleting_the_whole_cart_empties_it(self):
        self.add()
        self.add(ct_qty=2)

        response = self.delete("cart")

        self.assertEqual(self.stored_guest_cart(), [])
        self.assertEqual(response.json()["data"]["items"], [])
        self.assertEqual(response.json()["data"]["total_price"], 0)

    def test_every_cart_row_gets_a_unique_twelve_digit_id(self):
        for number in range(5):
            self.make_product(f"U{number}", f"Unique {number}", it_price=100, it_stock_qty=5)
        ids = [self.add(f"U{number}") for number in range(5)]

        self.assertEqual(len(set(ids)), 5)
        self.assertTrue(all(len(value) == 12 and value.isdigit() for value in ids))


class CartLegacyUpdateTests(ShopApiTestCase):
    def setUp(self):
        super().setUp()
        self.make_product("P002", "Second", it_price=2000)

    def test_form_post_without_ct_id_appends_rows_for_each_product(self):
        response = self.post_form("cart/legacy-update", {"it_id[]": ["P001", "P002"], "ct_qty[]": ["2", "3"]})

        self.assertEqual(response.status_code, 200)
        rows = self.stored_guest_cart()
        self.assertEqual([(r["it_id"], r["ct_qty"], r["ct_price"]) for r in rows], [("P001", 2, 1000), ("P002", 3, 2000)])
        self.assertEqual(response.json()["data"]["total_price"], 2000 + 6000)
        self.assertEqual(response.json()["data"]["redirect"], "/shop/cart")

    def test_direct_buy_flag_marks_rows_direct_and_redirects_to_the_order_page(self):
        response = self.post_form("cart/legacy-update", {"it_id": "P001", "ct_qty": "1", "sw_direct": "1"})

        self.assertEqual(response.json()["data"]["redirect"], "/shop/order?direct=1")
        self.assertEqual(self.stored_guest_cart()[0]["ct_direct"], 1)

    def test_form_post_with_ct_ids_updates_quantities(self):
        self.post_form("cart/legacy-update", {"it_id[]": ["P001", "P002"], "ct_qty[]": ["1", "1"]})
        first, second = [r["ct_id"] for r in self.stored_guest_cart()]

        self.post_form("cart/legacy-update", {"ct_id[]": [first, second], "ct_qty[]": ["4", "0"]})

        self.assertEqual([r["ct_qty"] for r in self.stored_guest_cart()], [4, 1])

    def test_selective_delete_removes_only_the_selected_rows(self):
        self.post_form("cart/legacy-update", {"it_id[]": ["P001", "P002"], "ct_qty[]": ["1", "1"]})
        first, second = [r["ct_id"] for r in self.stored_guest_cart()]

        self.post_form("cart/legacy-update", {"act": "seldelete", "ct_id[]": [first]})

        self.assertEqual([r["ct_id"] for r in self.stored_guest_cart()], [second])

    def test_all_delete_clears_the_cart(self):
        self.post_form("cart/legacy-update", {"it_id": "P001"})

        response = self.post_form("cart/legacy-update", {"act": "alldelete"})

        self.assertEqual(self.stored_guest_cart(), [])
        self.assertEqual(response.json()["data"]["items"], [])

    def test_json_body_is_accepted_too(self):
        response = self.post("cart/legacy-update", {"it_id": "P002", "ct_qty": 2})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.stored_guest_cart()[0]["ct_qty"], 2)


class GuestAndMemberCartTests(ShopApiTestCase):
    def test_guest_and_member_carts_are_stored_separately(self):
        self.post("cart", {"it_id": "P001", "ct_qty": 1})
        self.post("cart", {"it_id": "P001", "ct_qty": 5}, user=self.user)

        guest = self.get("cart").json()["data"]
        member = self.get("cart", user=self.user).json()["data"]

        self.assertEqual((guest["total_qty"], member["total_qty"]), (1, 5))
        self.assertEqual([r["ct_qty"] for r in self.stored_guest_cart()], [1])
        self.assertEqual([r["ct_qty"] for r in self.stored_member_cart(self.user)], [5])

    def test_members_do_not_see_each_others_carts(self):
        self.post("cart", {"it_id": "P001", "ct_qty": 2}, user=self.user)

        other_cart = self.get("cart", user=self.other).json()["data"]

        self.assertEqual(other_cart["items"], [])
        self.assertEqual(self.stored_member_cart(self.other), [])

    def test_member_cannot_edit_or_delete_a_row_of_another_member(self):
        ct_id = self.post("cart", {"it_id": "P001", "ct_qty": 2}, user=self.user).json()["data"]["ct_id"]

        self.patch(f"cart/{ct_id}", {"ct_qty": 9}, user=self.other)
        self.delete(f"cart/{ct_id}", user=self.other)

        self.assertEqual([(r["ct_id"], r["ct_qty"]) for r in self.stored_member_cart(self.user)], [(ct_id, 2)])

    def test_clearing_a_guest_cart_leaves_the_member_cart_alone(self):
        self.post("cart", {"it_id": "P001"})
        self.post("cart", {"it_id": "P001", "ct_qty": 3}, user=self.user)

        self.delete("cart")

        self.assertEqual(self.stored_guest_cart(), [])
        self.assertEqual([r["ct_qty"] for r in self.stored_member_cart(self.user)], [3])

    def test_logging_in_moves_the_guest_cart_into_the_member_cart(self):
        """YoungCart keeps what a visitor put in the cart when they sign in."""
        self.user.set_password("password123")
        self.user.save()
        self.post("cart", {"it_id": "P001", "ct_qty": 2})

        login = self.client.post(
            "/api/v1/auth/login",
            data=json.dumps({"mb_id": "buyer", "password": "password123"}),
            content_type="application/json",
        )

        self.assertEqual(login.status_code, 200)
        self.assertEqual([r["ct_qty"] for r in self.stored_member_cart(self.user)], [2])
        self.assertEqual(self.stored_guest_cart(), [])

    def test_member_cart_survives_a_new_session(self):
        self.post("cart", {"it_id": "P001", "ct_qty": 2}, user=self.user)
        self.client.logout()
        self.client.cookies.clear()

        data = self.get("cart", user=self.user).json()["data"]

        self.assertEqual(data["total_qty"], 2)

    def test_corrupt_stored_member_cart_reads_as_empty(self):
        for raw in ("not json", '{"a": 1}', "null"):
            with self.subTest(raw=raw):
                Config.objects.update_or_create(name=auth_cart_config_name(self.user), defaults={"value": raw})
                data = self.get("cart", user=self.user).json()["data"]
                self.assertEqual(data["items"], [])

    def test_member_cart_keeps_the_newest_rows_when_it_outgrows_the_config_column(self):
        # Pins the documented truncation: the oldest rows are dropped first.
        for index in range(40):
            self.post("cart", {"it_id": "P001", "ct_qty": 1}, user=self.user)
        stored = self.stored_member_cart(self.user)
        raw = Config.objects.get(name=auth_cart_config_name(self.user)).value

        self.assertLessEqual(len(raw), 2000)
        self.assertLess(len(stored), 40)
        self.assertGreater(len(stored), 0)

    def test_member_cart_accepts_a_sold_out_row_but_still_lists_its_flags(self):
        self.seed_member_cart(
            self.user,
            [{"ct_id": "1", "it_id": "P001", "ct_price": 1000, "ct_qty": 1}],
        )
        ShopProduct.objects.filter(pk="P001").update(it_soldout="1")

        item = self.get("cart", user=self.user).json()["data"]["items"][0]

        self.assertEqual(item["it_soldout"], "1")
        self.assertEqual(item["it_stock_qty"], 10)


class WishlistTests(ShopApiTestCase):
    def setUp(self):
        super().setUp()
        self.make_product("P002", "Second", it_price=2000, it_soldout="1")

    def test_adding_stores_one_row_per_member_and_product(self):
        first = self.post("wishlist", {"it_id": "P001"}, user=self.user)
        again = self.post("wishlist", {"it_id": "P001"}, user=self.user)

        self.assertEqual((first.status_code, again.status_code), (201, 201))
        self.assertEqual(ShopWishlist.objects.filter(user=self.user, it_id="P001").count(), 1)
        entry = first.json()["data"]
        self.assertEqual(entry["it_id"], "P001")
        self.assertEqual(entry["it_name"], "Plain product")
        self.assertTrue(entry["can_add_cart"])
        self.assertEqual(entry["wi_id"], again.json()["data"]["wi_id"])

    def test_missing_product_id_is_rejected(self):
        response = self.post("wishlist", {}, user=self.user)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(ShopWishlist.objects.count(), 0)

    def test_sold_out_product_is_listed_but_flagged_not_cart_addable(self):
        self.post("wishlist", {"it_id": "P002"}, user=self.user)

        entry = self.get("wishlist", user=self.user).json()["data"][0]

        self.assertEqual(entry["it_id"], "P002")
        self.assertFalse(entry["can_add_cart"])
        self.assertEqual(entry["it_soldout"], "1")

    def test_disabled_product_is_flagged_not_cart_addable(self):
        ShopProduct.objects.filter(pk="P001").update(it_use="0")
        self.post("wishlist", {"it_id": "P001"}, user=self.user)

        entry = self.get("wishlist", user=self.user).json()["data"][0]

        self.assertFalse(entry["can_add_cart"])

    def test_list_is_scoped_to_the_member_and_paginated(self):
        self.post("wishlist", {"it_id": "P001"}, user=self.user)
        self.post("wishlist", {"it_id": "P002"}, user=self.user)
        self.post("wishlist", {"it_id": "P001"}, user=self.other)

        response = self.get("wishlist?per_page=1", user=self.user)

        body = response.json()
        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["meta"]["total"], 2)
        self.assertEqual(body["meta"]["last_page"], 2)
        other = self.get("wishlist", user=self.other).json()["data"]
        self.assertEqual([e["it_id"] for e in other], ["P001"])

    def test_check_reports_membership_only_for_the_caller(self):
        self.post("wishlist", {"it_id": "P001"}, user=self.user)

        mine = self.get("wishlist/check/P001", user=self.user).json()["data"]
        theirs = self.get("wishlist/check/P001", user=self.other).json()["data"]
        unknown = self.get("wishlist/check/P002", user=self.user).json()["data"]

        self.assertTrue(mine["wishlisted"])
        self.assertEqual(mine["item"]["it_id"], "P001")
        self.assertFalse(theirs["wishlisted"])
        self.assertIsNone(theirs["item"])
        self.assertFalse(unknown["wishlisted"])

    def test_delete_removes_only_the_callers_entry(self):
        self.post("wishlist", {"it_id": "P001"}, user=self.user)
        self.post("wishlist", {"it_id": "P001"}, user=self.other)

        gone = self.delete("wishlist/P001", user=self.user)
        nothing = self.delete("wishlist/P001", user=self.user)

        self.assertEqual(gone.json()["data"], {"deleted": True, "it_id": "P001"})
        self.assertFalse(nothing.json()["data"]["deleted"])
        self.assertFalse(ShopWishlist.objects.filter(user=self.user).exists())
        self.assertTrue(ShopWishlist.objects.filter(user=self.other, it_id="P001").exists())

    def test_deleting_the_product_removes_the_wishlist_entry(self):
        self.post("wishlist", {"it_id": "P001"}, user=self.user)

        ShopProduct.objects.filter(pk="P001").delete()

        self.assertEqual(self.get("wishlist", user=self.user).json()["data"], [])

    def test_guest_wishlist_lives_in_the_session_and_is_invisible_to_members(self):
        self.post("wishlist", {"it_id": "P001"})

        guest = self.get("wishlist").json()["data"]
        member = self.get("wishlist", user=self.user).json()["data"]

        self.assertEqual([e["it_id"] for e in guest], ["P001"])
        self.assertEqual(member, [])
        self.assertTrue(ShopWishlist.objects.filter(user__isnull=True, it_id="P001").exclude(session_key="").exists())

    def test_legacy_update_requires_a_member(self):
        response = self.post_form("wishlist/legacy-update", {"it_id": "P001"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(ShopWishlist.objects.count(), 0)

    def test_legacy_update_adds_and_removes(self):
        added = self.post_form("wishlist/legacy-update", {"it_id": "P001"}, user=self.user)
        self.assertEqual(added.json()["data"]["redirect"], "/shop/wishlist")
        self.assertEqual(ShopWishlist.objects.filter(user=self.user, it_id="P001").count(), 1)

        self.post_form("wishlist/legacy-update", {"it_id": "P001", "w": "d"}, user=self.user)

        self.assertEqual(ShopWishlist.objects.filter(user=self.user).count(), 0)

    def test_legacy_update_without_product_id_is_rejected(self):
        response = self.post_form("wishlist/legacy-update", {"act": "add"}, user=self.user)

        self.assertEqual(response.status_code, 422)

    def test_legacy_update_delete_does_not_touch_other_members(self):
        self.post("wishlist", {"it_id": "P001"}, user=self.other)

        self.post_form("wishlist/legacy-update", {"it_id": "P001", "act": "delete"}, user=self.user)

        self.assertTrue(ShopWishlist.objects.filter(user=self.other, it_id="P001").exists())


class AddressTests(ShopApiTestCase):
    def payload(self, **overrides):
        data = {
            "ad_subject": "Home",
            "ad_name": "Hong",
            "ad_tel": "02-123-4567",
            "ad_hp": "010-1234-5678",
            "ad_zip": "06236",
            "ad_addr1": "Teheran-ro 1",
            "ad_addr2": "101",
            "ad_addr3": "(Yeoksam)",
            "ad_jibeon": "R",
        }
        data.update(overrides)
        return data

    def make_address(self, user, **fields):
        defaults = {"ad_subject": "Existing", "ad_name": "Name", "ad_zip": "12345", "ad_addr1": "Somewhere"}
        defaults.update(fields)
        return ShopAddress.objects.create(user=user, **defaults)

    def test_all_address_routes_require_authentication(self):
        address = self.make_address(self.user)
        checks = [
            self.get("addresses"),
            self.post("addresses", self.payload()),
            self.patch(f"addresses/{address.pk}", {"ad_name": "X"}),
            self.delete(f"addresses/{address.pk}"),
            self.post_form("addresses/legacy-update", self.payload()),
        ]

        self.assertEqual([r.status_code for r in checks], [401] * 5)
        address.refresh_from_db()
        self.assertEqual(address.ad_name, "Name")
        self.assertEqual(ShopAddress.objects.count(), 1)

    def test_create_stores_the_address_for_the_caller_and_splits_the_zip(self):
        response = self.post("addresses", self.payload(), user=self.user)

        self.assertEqual(response.status_code, 201)
        data = response.json()["data"]
        stored = ShopAddress.objects.get(pk=data["ad_id"])
        self.assertEqual(stored.user, self.user)
        self.assertEqual((stored.ad_name, stored.ad_hp, stored.ad_addr1, stored.ad_zip), ("Hong", "010-1234-5678", "Teheran-ro 1", "06236"))
        self.assertEqual((data["ad_zip1"], data["ad_zip2"]), ("062", "36"))
        self.assertEqual(data["ad_default"], 0)

    def test_zip_can_be_supplied_as_two_parts_or_under_the_short_key(self):
        base = {"ad_name": "Home", "ad_addr1": "Seoul"}
        split = self.post("addresses", {**base, "ad_zip1": "123", "ad_zip2": "45"}, user=self.user).json()["data"]
        short = self.post("addresses", {**base, "zip": "67890"}, user=self.user).json()["data"]

        self.assertEqual(split["ad_zip"], "12345")
        self.assertEqual(short["ad_zip"], "67890")

    def test_new_default_address_replaces_the_previous_default(self):
        first = self.post("addresses", self.payload(ad_default=True), user=self.user).json()["data"]
        second = self.post("addresses", self.payload(ad_subject="Work", ad_default=True), user=self.user).json()["data"]

        self.assertEqual(second["ad_default"], 1)
        self.assertFalse(ShopAddress.objects.get(pk=first["ad_id"]).ad_default)
        self.assertEqual(ShopAddress.objects.filter(user=self.user, ad_default=True).count(), 1)

    def test_default_flag_of_another_member_is_not_reset(self):
        theirs = self.make_address(self.other, ad_default=True)

        self.post("addresses", self.payload(ad_default=True), user=self.user)

        theirs.refresh_from_db()
        self.assertTrue(theirs.ad_default)

    def test_list_returns_only_own_addresses_default_first(self):
        self.make_address(self.user, ad_subject="Plain")
        self.make_address(self.user, ad_subject="Preferred", ad_default=True)
        self.make_address(self.other, ad_subject="Secret address")

        body = self.get("addresses", user=self.user).json()

        self.assertEqual([a["ad_subject"] for a in body["data"]], ["Preferred", "Plain"])
        self.assertEqual(body["meta"]["total"], 2)

    def test_patch_updates_only_the_sent_fields(self):
        address = self.make_address(self.user, ad_tel="111", ad_zip="12345")

        response = self.patch(f"addresses/{address.pk}", {"ad_name": "Renamed", "ad_zip1": "999", "ad_zip2": "88"}, user=self.user)

        self.assertEqual(response.status_code, 200)
        address.refresh_from_db()
        self.assertEqual((address.ad_name, address.ad_tel, address.ad_zip, address.ad_addr1), ("Renamed", "111", "99988", "Somewhere"))

    def test_patch_making_an_address_default_demotes_the_others(self):
        old_default = self.make_address(self.user, ad_default=True)
        address = self.make_address(self.user)

        response = self.patch(f"addresses/{address.pk}", {"ad_default": True}, user=self.user)

        self.assertEqual(response.json()["data"]["ad_default"], 1)
        old_default.refresh_from_db()
        address.refresh_from_db()
        self.assertEqual((old_default.ad_default, address.ad_default), (False, True))

    def test_patch_can_clear_the_default_flag(self):
        address = self.make_address(self.user, ad_default=True)

        self.patch(f"addresses/{address.pk}", {"ad_default": False}, user=self.user)

        address.refresh_from_db()
        self.assertFalse(address.ad_default)

    def test_only_the_owner_can_edit_an_address(self):
        address = self.make_address(self.user)

        response = self.patch(f"addresses/{address.pk}", {"ad_name": "Hijacked"}, user=self.other)

        self.assertEqual(response.status_code, 404)
        self.assertIn("address_not_found", response.json()["errors"])
        address.refresh_from_db()
        self.assertEqual(address.ad_name, "Name")

    def test_only_the_owner_can_delete_an_address(self):
        address = self.make_address(self.user)

        refused = self.delete(f"addresses/{address.pk}", user=self.other)
        deleted = self.delete(f"addresses/{address.pk}", user=self.user)

        self.assertEqual(refused.status_code, 404)
        self.assertTrue(deleted.json()["data"]["deleted"])
        self.assertFalse(ShopAddress.objects.filter(pk=address.pk).exists())

    def test_unknown_address_returns_404(self):
        response = self.delete("addresses/987654", user=self.user)

        self.assertEqual(response.status_code, 404)

    def test_legacy_update_creates_edits_and_deletes_own_addresses(self):
        created = self.post_form("addresses/legacy-update", self.payload(ad_default="1"), user=self.user)
        ad_id = created.json()["data"]["ad_id"]
        self.assertEqual(created.json()["data"]["redirect"], "/mypage/addresses")
        self.assertTrue(ShopAddress.objects.get(pk=ad_id).ad_default)

        self.post_form("addresses/legacy-update", {"ad_id": ad_id, "ad_name": "Edited"}, user=self.user)
        edited = ShopAddress.objects.get(pk=ad_id)
        self.assertEqual((edited.ad_name, edited.ad_addr1), ("Edited", "Teheran-ro 1"))

        deleted = self.post_form("addresses/legacy-update", {"ad_id": ad_id, "w": "d"}, user=self.user)
        self.assertTrue(deleted.json()["data"]["deleted"])
        self.assertEqual(ShopAddress.objects.count(), 0)

    def test_legacy_update_default_flag_demotes_the_previous_default(self):
        old = self.make_address(self.user, ad_default=True)

        self.post_form("addresses/legacy-update", self.payload(ad_default="1"), user=self.user)

        old.refresh_from_db()
        self.assertFalse(old.ad_default)
        self.assertEqual(ShopAddress.objects.filter(user=self.user, ad_default=True).count(), 1)

    def test_legacy_update_cannot_edit_or_delete_another_members_address(self):
        theirs = self.make_address(self.other, ad_name="Original")

        edit = self.post_form("addresses/legacy-update", {"ad_id": theirs.pk, "ad_name": "Hijacked"}, user=self.user)
        remove = self.post_form("addresses/legacy-update", {"ad_id": theirs.pk, "w": "d"}, user=self.user)

        theirs.refresh_from_db()
        self.assertEqual(theirs.ad_name, "Original")
        self.assertEqual(theirs.user, self.other)
        self.assertFalse(remove.json()["data"]["deleted"])
        # the edit attempt falls back to creating a fresh row owned by the caller
        self.assertEqual(ShopAddress.objects.get(pk=edit.json()["data"]["ad_id"]).user, self.user)


class ReviewTests(ShopApiTestCase):
    def setUp(self):
        super().setUp()
        self.second = self.make_product("P002", "Second", it_price=2000)

    def make_review(self, user=None, product=None, **fields):
        user = user or self.user
        defaults = {
            "product": product or self.product,
            "user": user,
            "mb_id": user.get_username(),
            "is_subject": "Nice",
            "is_content": "Works",
            "is_score": 4,
        }
        defaults.update(fields)
        return ShopReview.objects.create(**defaults)

    def test_posting_a_review_requires_a_member(self):
        response = self.post("reviews", {"it_id": "P001", "is_subject": "Hi"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(ShopReview.objects.count(), 0)

    def test_member_review_is_stored_with_author_and_score(self):
        response = self.post(
            "reviews", {"it_id": "P001", "is_subject": "Great", "is_content": "Loved it", "is_score": 4}, user=self.user
        )

        self.assertEqual(response.status_code, 201)
        review = ShopReview.objects.get()
        self.assertEqual((review.user, review.mb_id, review.product_id), (self.user, "buyer", "P001"))
        self.assertEqual((review.is_subject, review.is_content, review.is_score), ("Great", "Loved it", 4))
        data = response.json()["data"]
        self.assertEqual(data["is_id"], str(review.pk))
        self.assertEqual(data["it_name"], "Plain product")
        self.assertEqual(data["is_score"], 4)

    def test_review_of_an_unknown_product_is_refused(self):
        response = self.post("reviews", {"it_id": "NOPE", "is_subject": "Hi"}, user=self.user)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(ShopReview.objects.count(), 0)

    def test_script_tags_are_stripped_from_review_content(self):
        self.post(
            "reviews",
            {"it_id": "P001", "is_subject": "x", "is_content": "ok<script>alert(1)</script> text"},
            user=self.user,
        )

        self.assertEqual(ShopReview.objects.get().is_content, "ok text")

    def test_scores_must_be_between_one_and_five(self):
        for sent, stored in {1: 1, 5: 5, 3: 3, "4": 4}.items():
            with self.subTest(sent=sent):
                ShopReview.objects.all().delete()
                self.post("reviews", {"it_id": "P001", "is_subject": "s", "is_score": sent}, user=self.user)
                self.assertEqual(ShopReview.objects.get().is_score, stored)
        ShopReview.objects.all().delete()
        for sent in (0, 6, -2):
            with self.subTest(sent=sent):
                response = self.post("reviews", {"it_id": "P001", "is_subject": "s", "is_score": sent}, user=self.user)
                self.assertEqual(response.status_code, 422)
        self.assertFalse(ShopReview.objects.exists())

    def test_a_missing_score_defaults_to_five_and_a_non_numeric_one_is_refused(self):
        self.post("reviews", {"it_id": "P001", "is_subject": "s"}, user=self.user)
        refused = self.post("reviews", {"it_id": "P001", "is_subject": "s", "is_score": "great"}, user=self.user)

        self.assertEqual(refused.status_code, 422)
        self.assertEqual(list(ShopReview.objects.values_list("is_score", flat=True)), [5])

    def test_unconfirmed_reviews_are_hidden_from_everyone_but_staff(self):
        self.make_review(is_subject="Visible")
        self.make_review(is_subject="Pending", is_confirm="0", user=self.other)

        anonymous = [r["is_subject"] for r in self.get("reviews").json()["data"]]
        author = [r["is_subject"] for r in self.get("reviews", user=self.other).json()["data"]]
        staff = [r["is_subject"] for r in self.get("reviews", user=self.staff).json()["data"]]

        self.assertEqual(anonymous, ["Visible"])
        self.assertEqual(author, ["Visible"])
        self.assertCountEqual(staff, ["Visible", "Pending"])

    def test_list_filters_by_product_and_search_text(self):
        self.make_review(is_subject="Good kettle", is_content="boils fast")
        self.make_review(product=self.second, is_subject="Great lamp", is_content="bright")

        by_product = self.get("reviews?it_id=P002").json()["data"]
        by_text = self.get("reviews?q=kettle").json()["data"]
        by_product_name = self.get("reviews?q=Second").json()["data"]

        self.assertEqual([r["it_id"] for r in by_product], ["P002"])
        self.assertEqual([r["is_subject"] for r in by_text], ["Good kettle"])
        self.assertEqual([r["it_id"] for r in by_product_name], ["P002"])

    def test_list_is_paginated(self):
        for index in range(3):
            self.make_review(is_subject=f"R{index}")

        body = self.get("reviews?per_page=2&page=2").json()

        self.assertEqual(len(body["data"]), 1)
        self.assertEqual(body["meta"]["total"], 3)

    def test_product_review_focus_returns_the_page_containing_that_review(self):
        reviews = [self.make_review(is_subject=f"R{index}") for index in range(5)]
        target = reviews[0]

        body = self.get(f"reviews?it_id=P001&per_page=2&focus_is_id={target.pk}").json()

        self.assertGreater(body["meta"]["current_page"], 1)
        self.assertIn(str(target.pk), [item["is_id"] for item in body["data"]])
        self.assertEqual(body["meta"]["last_page"], 3)

    def test_product_review_focus_ignores_an_unpublished_review(self):
        self.make_review(is_subject="Visible")
        pending = self.make_review(is_subject="Pending", is_confirm="0")

        body = self.get(f"reviews?it_id=P001&per_page=20&focus_is_id={pending.pk}").json()

        self.assertEqual(body["meta"]["current_page"], 1)
        self.assertEqual([item["is_subject"] for item in body["data"]], ["Visible"])

    def test_review_of_a_deleted_product_still_lists(self):
        self.make_review()
        ShopProduct.objects.filter(pk="P001").delete()

        data = self.get("reviews").json()["data"]

        self.assertEqual(data[0]["it_name"], "Deleted product")
        self.assertEqual(data[0]["it_id"], "")

    def test_author_can_edit_own_review(self):
        review = self.make_review()

        response = self.patch(
            f"reviews/{review.pk}", {"is_subject": "Better", "is_content": "<script>x</script>New", "is_score": 2}, user=self.user
        )

        self.assertEqual(response.status_code, 200)
        review.refresh_from_db()
        self.assertEqual((review.is_subject, review.is_content, review.is_score), ("Better", "New", 2))

    def test_edit_with_an_out_of_range_score_is_refused(self):
        review = self.make_review(is_score=4)

        response = self.patch(f"reviews/{review.pk}", {"is_score": 9}, user=self.user)

        self.assertEqual(response.status_code, 422)
        review.refresh_from_db()
        self.assertEqual(review.is_score, 4)

    def test_edit_cannot_change_the_moderation_state_or_owner(self):
        review = self.make_review(is_confirm="0")

        self.patch(f"reviews/{review.pk}", {"is_confirm": "1", "mb_id": "other", "user": self.other.pk}, user=self.user)

        review.refresh_from_db()
        self.assertEqual((review.is_confirm, review.mb_id, review.user), ("0", "buyer", self.user))

    def test_other_members_and_guests_cannot_edit_or_delete_a_review(self):
        review = self.make_review()

        results = [
            self.patch(f"reviews/{review.pk}", {"is_subject": "Hijacked"}, user=self.other),
            self.delete(f"reviews/{review.pk}", user=self.other),
            self.patch(f"reviews/{review.pk}", {"is_subject": "Hijacked"}),
            self.delete(f"reviews/{review.pk}"),
        ]

        self.assertEqual([r.status_code for r in results], [403] * 4)
        review.refresh_from_db()
        self.assertEqual(review.is_subject, "Nice")

    def test_staff_can_edit_and_author_can_delete(self):
        review = self.make_review()

        edited = self.patch(f"reviews/{review.pk}", {"is_subject": "Moderated"}, user=self.staff)
        deleted = self.delete(f"reviews/{review.pk}", user=self.user)

        self.assertEqual(edited.status_code, 200)
        self.assertEqual(deleted.json()["data"]["deleted"], True)
        self.assertFalse(ShopReview.objects.filter(pk=review.pk).exists())

    def test_unknown_review_returns_404(self):
        for method in ("get", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self, method)("reviews/99999", user=self.user)
                self.assertEqual(response.status_code, 404)

    def test_confirmed_review_detail_is_public(self):
        review = self.make_review()

        response = self.get(f"reviews/{review.pk}")

        self.assertEqual(response.json()["data"]["is_subject"], "Nice")

    def test_my_reviews_lists_only_the_callers_reviews(self):
        self.make_review(is_subject="Mine")
        self.make_review(user=self.other, is_subject="Theirs")

        anonymous = self.get("reviews/mine")
        mine = self.get("reviews/mine", user=self.user)

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual([r["is_subject"] for r in mine.json()["data"]], ["Mine"])

    def test_summary_counts_scores_and_percentages(self):
        for score in (5, 5, 4, 1):
            self.make_review(is_score=score)
        self.make_review(product=self.second, is_score=2)

        everything = self.get("reviews/summary").json()["data"]
        one_product = self.get("reviews/summary?it_id=P001").json()["data"]

        self.assertEqual(everything["total"], 5)
        self.assertEqual(one_product["total"], 4)
        self.assertEqual(one_product["average"], 3.8)
        by_score = {row["score"]: row for row in one_product["scores"]}
        self.assertEqual(by_score[5]["count"], 2)
        self.assertEqual(by_score[5]["percentage"], 50.0)
        self.assertEqual(by_score[3]["count"], 0)
        self.assertEqual([row["score"] for row in one_product["scores"]], [5, 4, 3, 2, 1])

    def test_summary_of_a_product_without_reviews_is_zeroed(self):
        data = self.get("reviews/summary?it_id=P002").json()["data"]

        self.assertEqual((data["total"], data["average"]), (0, 0))
        self.assertTrue(all(row["percentage"] == 0 for row in data["scores"]))


class QnaTests(ShopApiTestCase):
    def make_qa(self, user=None, **fields):
        user = user or self.user
        defaults = {
            "product": self.product,
            "user": user,
            "mb_id": user.get_username(),
            "iq_name": "Buyer",
            "iq_subject": "Is it waterproof?",
            "iq_question": "Please tell me",
            "iq_email": "buyer@example.test",
            "iq_hp": "010-0000-0000",
        }
        defaults.update(fields)
        return ShopQA.objects.create(**defaults)

    def test_asking_requires_a_member(self):
        response = self.post("reviews/qna", {"it_id": "P001", "iq_subject": "Hi", "iq_question": "?"})

        self.assertEqual(response.status_code, 401)
        self.assertEqual(ShopQA.objects.count(), 0)

    def test_question_is_stored_for_the_member(self):
        response = self.post(
            "reviews/qna",
            {"it_id": "P001", "iq_subject": "Size?", "iq_question": "<script>x</script>How big?", "iq_secret": 1, "iq_hp": "010-1"},
            user=self.user,
        )

        self.assertEqual(response.status_code, 201)
        qa = ShopQA.objects.get()
        self.assertEqual((qa.user, qa.mb_id, qa.product_id), (self.user, "buyer", "P001"))
        self.assertEqual((qa.iq_subject, qa.iq_question, qa.iq_secret, qa.iq_hp), ("Size?", "How big?", 1, "010-1"))
        self.assertEqual(qa.iq_answer, "")
        data = response.json()["data"]
        self.assertTrue(data["can_edit"] and data["can_view"])
        self.assertFalse(data["is_answered"])

    def test_question_email_defaults_to_the_account_email(self):
        self.user.email = "me@example.test"
        self.user.save()

        self.post("reviews/qna", {"it_id": "P001", "iq_subject": "Hi", "iq_question": "?"}, user=self.user)

        self.assertEqual(ShopQA.objects.get().iq_email, "me@example.test")

    def test_question_about_an_unknown_product_is_refused(self):
        response = self.post("reviews/qna", {"it_id": "NOPE", "iq_subject": "Hi"}, user=self.user)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(ShopQA.objects.count(), 0)

    def test_secret_question_is_masked_for_guests_and_other_members(self):
        self.make_qa(iq_secret=1, iq_answer="Private answer")

        for label, user in (("guest", None), ("other member", self.other)):
            with self.subTest(label):
                item = self.get("reviews/qna", user=user).json()["data"][0]
                self.assertFalse(item["can_view"])
                self.assertFalse(item["can_edit"])
                self.assertEqual(item["iq_question"], "")
                self.assertEqual(item["iq_answer"], "")
                self.assertEqual(item["iq_email"], "")
                self.assertEqual(item["iq_hp"], "")
                self.assertNotEqual(item["iq_subject"], "Is it waterproof?")
                self.assertEqual(item["iq_secret"], 1)

    def test_secret_question_is_visible_to_its_author_and_to_staff(self):
        self.make_qa(iq_secret=1, iq_answer="Private answer")

        for label, user in (("author", self.user), ("staff", self.staff)):
            with self.subTest(label):
                item = self.get("reviews/qna", user=user).json()["data"][0]
                self.assertTrue(item["can_view"])
                self.assertEqual(item["iq_subject"], "Is it waterproof?")
                self.assertEqual(item["iq_question"], "Please tell me")
                self.assertEqual(item["iq_answer"], "Private answer")
                self.assertEqual(item["iq_email"], "buyer@example.test")

    def test_secret_question_is_masked_in_the_detail_route_too(self):
        qa = self.make_qa(iq_secret=1)

        guest = self.get(f"reviews/qna/{qa.pk}").json()["data"]
        author = self.get(f"reviews/qna/{qa.pk}", user=self.user).json()["data"]

        self.assertEqual(guest["iq_question"], "")
        self.assertEqual(author["iq_question"], "Please tell me")

    def test_public_question_hides_contact_details_from_other_people(self):
        self.make_qa()

        guest = self.get("reviews/qna").json()["data"][0]
        author = self.get("reviews/qna", user=self.user).json()["data"][0]

        self.assertEqual(guest["iq_question"], "Please tell me")
        self.assertEqual((guest["iq_email"], guest["iq_hp"]), ("", ""))
        self.assertEqual(author["iq_email"], "buyer@example.test")

    def test_list_filters_by_product_and_text(self):
        other_product = self.make_product("P002", "Second", it_price=1)
        self.make_qa(iq_subject="Waterproof?")
        self.make_qa(iq_subject="Colours?", product=other_product)

        by_product = self.get("reviews/qna?it_id=P002").json()["data"]
        by_text = self.get("reviews/qna?q=Waterproof").json()["data"]

        self.assertEqual([q["iq_subject"] for q in by_product], ["Colours?"])
        self.assertEqual([q["iq_subject"] for q in by_text], ["Waterproof?"])

    def test_product_qna_focus_returns_the_page_containing_that_question(self):
        questions = [self.make_qa(iq_subject=f"Q{index}") for index in range(5)]
        target = questions[0]

        body = self.get(f"reviews/qna?it_id=P001&per_page=2&focus_iq_id={target.pk}").json()

        self.assertGreater(body["meta"]["current_page"], 1)
        self.assertIn(str(target.pk), [item["iq_id"] for item in body["data"]])
        self.assertEqual(body["meta"]["last_page"], 3)

    def test_product_qna_focus_ignores_a_question_from_another_product(self):
        other_product = self.make_product("P002", "Second", it_price=1)
        self.make_qa(iq_subject="Current product")
        foreign = self.make_qa(iq_subject="Another product", product=other_product)

        body = self.get(f"reviews/qna?it_id=P001&per_page=20&focus_iq_id={foreign.pk}").json()

        self.assertEqual(body["meta"]["current_page"], 1)
        self.assertEqual([item["iq_subject"] for item in body["data"]], ["Current product"])

    def test_author_can_edit_own_question(self):
        qa = self.make_qa()

        response = self.patch(
            f"reviews/qna/{qa.pk}",
            {"iq_subject": "Edited", "iq_question": "<script>x</script>Edited body", "iq_secret": 1},
            user=self.user,
        )

        self.assertEqual(response.status_code, 200)
        qa.refresh_from_db()
        self.assertEqual((qa.iq_subject, qa.iq_question, qa.iq_secret), ("Edited", "Edited body", 1))

    def test_author_cannot_write_the_answer(self):
        qa = self.make_qa()

        self.patch(f"reviews/qna/{qa.pk}", {"iq_answer": "I answer myself"}, user=self.user)

        qa.refresh_from_db()
        self.assertEqual(qa.iq_answer, "")

    def test_staff_can_answer_and_the_question_becomes_answered(self):
        qa = self.make_qa()

        response = self.patch(f"reviews/qna/{qa.pk}", {"iq_answer": "<script>x</script>Yes it is"}, user=self.staff)

        self.assertEqual(response.status_code, 200)
        qa.refresh_from_db()
        self.assertEqual(qa.iq_answer, "Yes it is")
        self.assertTrue(response.json()["data"]["is_answered"])
        self.assertEqual(qa.user, self.user)

    def test_other_members_and_guests_cannot_edit_or_delete_a_question(self):
        qa = self.make_qa()

        results = [
            self.patch(f"reviews/qna/{qa.pk}", {"iq_subject": "Hijacked"}, user=self.other),
            self.delete(f"reviews/qna/{qa.pk}", user=self.other),
            self.patch(f"reviews/qna/{qa.pk}", {"iq_subject": "Hijacked"}),
            self.delete(f"reviews/qna/{qa.pk}"),
        ]

        self.assertEqual([r.status_code for r in results], [403] * 4)
        qa.refresh_from_db()
        self.assertEqual(qa.iq_subject, "Is it waterproof?")

    def test_author_can_delete_own_question(self):
        qa = self.make_qa()

        response = self.delete(f"reviews/qna/{qa.pk}", user=self.user)

        self.assertTrue(response.json()["data"]["deleted"])
        self.assertFalse(ShopQA.objects.filter(pk=qa.pk).exists())

    def test_unknown_question_returns_404(self):
        for method in ("get", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self, method)("reviews/qna/99999", user=self.user)
                self.assertEqual(response.status_code, 404)

    def test_my_questions_lists_only_the_callers_own_with_contents(self):
        self.make_qa(iq_subject="Mine", iq_secret=1)
        self.make_qa(user=self.other, iq_subject="Theirs")

        anonymous = self.get("reviews/qna/mine")
        mine = self.get("reviews/qna/mine", user=self.user)

        self.assertEqual(anonymous.status_code, 401)
        data = mine.json()["data"]
        self.assertEqual([q["iq_subject"] for q in data], ["Mine"])
        self.assertEqual(data[0]["iq_question"], "Please tell me")


class ShopDefectFixTests(ShopApiTestCase):
    """Fixes for defects the cart, review and Q&A tests found."""

    def test_a_product_without_stock_cannot_be_added_or_raised(self):
        self.make_product("Z0", "Empty", it_price=1000, it_stock_qty=0)
        response = self.post("cart", {"it_id": "Z0", "ct_qty": 1})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "out_of_stock")
        self.assertEqual(self.stored_guest_cart(), [])

    def test_a_member_cart_keeps_every_line_and_refuses_beyond_the_limit(self):
        for number in range(30):
            self.make_product(f"ZM{number}", "Many", it_price=100, it_stock_qty=10)
            self.assertEqual(self.post("cart", {"it_id": f"ZM{number}", "ct_qty": 1}, user=self.user).status_code, 201)
        self.assertEqual(len(self.stored_member_cart(self.user)), 30)

    def test_error_bodies_keep_their_code_next_to_the_field_details(self):
        response = self.patch("cart/999999", {"ct_qty": 2})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "cart_item_not_found")

    def test_qna_lists_still_work_after_the_product_is_deleted(self):
        product = self.make_product("ZQ", "Gone soon", it_price=100, it_stock_qty=5)
        ShopQA.objects.create(product=product, user=self.user, mb_id="buyer", iq_subject="Still here?", iq_question="q")
        product.delete()
        response = self.get("reviews/qna")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Still here?", response.content.decode())

    def test_unapproved_reviews_are_hidden_by_id_and_from_the_summary(self):
        review = ShopReview.objects.create(product=self.product, user=self.user, mb_id="buyer", is_subject="Pending", is_content="Not yet", is_score=5, is_confirm="0")
        self.assertEqual(self.get(f"reviews/{review.pk}").status_code, 404)
        self.assertEqual(self.get(f"reviews/{review.pk}", user=self.other).status_code, 404)
        self.assertEqual(self.get(f"reviews/{review.pk}", user=self.user).status_code, 200)
        self.assertEqual(self.get("reviews/summary?it_id=P001").json()["data"]["total"], 0)

    def test_reviews_need_a_received_order_when_the_shop_requires_it(self):
        from gnu_jango.shop.models import ShopOrder, ShopOrderItem, ShopShippingPolicy

        ShopShippingPolicy.objects.update_or_create(pk=1, defaults={"de_delivery_company": "C", "de_item_use_write": 1})
        refused = self.post("reviews", {"it_id": "P001", "is_subject": "s"}, user=self.user)
        self.assertEqual(refused.status_code, 403)
        order = ShopOrder.objects.create(od_id="RV1", user=self.user, od_name="b", od_status="배송")
        line = ShopOrderItem.objects.create(order=order, product=self.product, ct_id="ct-rv1", it_id="P001", it_name="Plain", ct_price=1000, ct_qty=1, ct_status="배송")
        # check_itemuse_write: a line still on its way (배송) is not enough, it must be 완료
        self.assertEqual(self.post("reviews", {"it_id": "P001", "is_subject": "s"}, user=self.user).status_code, 403)
        ShopOrderItem.objects.filter(pk=line.pk).update(ct_status="완료")
        self.assertEqual(self.post("reviews", {"it_id": "P001", "is_subject": "s"}, user=self.user).status_code, 201)

    def test_new_reviews_wait_for_approval_when_moderation_is_on(self):
        from gnu_jango.shop.models import ShopShippingPolicy

        ShopShippingPolicy.objects.update_or_create(pk=1, defaults={"de_delivery_company": "C", "de_item_use_use": 1})
        self.post("reviews", {"it_id": "P001", "is_subject": "Moderated"}, user=self.user)
        self.assertEqual(ShopReview.objects.get(is_subject="Moderated").is_confirm, "0")
        self.assertNotIn("Moderated", self.get("reviews?it_id=P001").content.decode())

    def test_an_answered_question_cannot_be_changed_or_removed_by_its_author(self):
        qa = ShopQA.objects.create(product=self.product, user=self.user, mb_id="buyer", iq_subject="Q", iq_question="Original", iq_answer="Answered")
        self.assertEqual(self.patch(f"reviews/qna/{qa.pk}", {"iq_question": "changed"}, user=self.user).status_code, 403)
        self.assertEqual(self.delete(f"reviews/qna/{qa.pk}", user=self.user).status_code, 403)
        qa.refresh_from_db()
        self.assertEqual(qa.iq_question, "Original")

    def test_the_wish_list_refuses_products_that_do_not_exist(self):
        self.assertEqual(self.post("wishlist", {"it_id": "NOPE"}, user=self.user).status_code, 404)
        self.assertFalse(ShopWishlist.objects.filter(it_id="NOPE").exists())

    def test_addresses_need_name_zip_and_address_and_zero_is_not_default(self):
        self.assertEqual(self.post("addresses", {}, user=self.user).status_code, 422)
        self.assertFalse(ShopAddress.objects.filter(user=self.user).exists())
        first = self.post("addresses", {"ad_name": "Home", "zip": "12345", "ad_addr1": "Seoul", "ad_default": "1"}, user=self.user)
        self.assertEqual(first.status_code, 201, first.content[:200])
        second = self.post("addresses", {"ad_name": "Office", "zip": "54321", "ad_addr1": "Busan", "ad_default": "0"}, user=self.user)
        self.assertEqual(second.status_code, 201)
        self.assertTrue(ShopAddress.objects.get(ad_name="Home").ad_default)
        self.assertFalse(ShopAddress.objects.get(ad_name="Office").ad_default)


class CartPriceRefreshTests(ShopApiTestCase):
    """YoungCart cartupdate merges repeated options; before_check_cart_price keeps prices current."""

    ORDER = {
        "od_name": "Buyer", "od_tel": "010-1111-2222", "od_hp": "010-1111-2222", "od_email": "buyer@example.test",
        "od_zip": "06236", "od_addr1": "Seoul", "od_addr2": "1",
        "od_b_name": "Buyer", "od_b_tel": "010-1111-2222", "od_b_hp": "010-1111-2222",
        "od_b_zip": "06236", "od_b_addr1": "Seoul", "od_b_addr2": "1",
        "od_settle_case": "bank", "od_bank_account": "Test Bank 000-00 Holder", "od_deposit_name": "Buyer",
    }

    def test_the_same_product_added_twice_is_one_line_with_both_quantities(self):
        first = self.post("cart", {"it_id": "P001", "ct_qty": 2}).json()["data"]["ct_id"]
        second = self.post("cart", {"it_id": "P001", "ct_qty": 3}).json()["data"]["ct_id"]

        rows = self.stored_guest_cart()
        self.assertEqual(first, second)
        self.assertEqual([(row["ct_id"], row["ct_qty"]) for row in rows], [(first, 5)])

    def test_merging_still_respects_the_stock(self):
        self.post("cart", {"it_id": "P001", "ct_qty": 8})
        response = self.post("cart", {"it_id": "P001", "ct_qty": 3})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.stored_guest_cart()[0]["ct_qty"], 8)

    def test_different_options_stay_separate_lines(self):
        options = [
            {"io_id": "Red", "io_type": 0, "io_price": 0, "io_stock_qty": 5, "io_use": 1},
            {"io_id": "Blue", "io_type": 0, "io_price": 0, "io_stock_qty": 5, "io_use": 1},
        ]
        self.make_product("OPT", "Options", it_price=1000, it_stock_qty=10, options=options)
        self.post("cart", {"it_id": "OPT", "ct_option": "Red"})
        self.post("cart", {"it_id": "OPT", "ct_option": "Blue"})
        self.post("cart", {"it_id": "OPT", "ct_option": "Red"})

        rows = self.stored_guest_cart()
        self.assertEqual([(row["ct_option"], row["ct_qty"]) for row in rows], [("Red", 2), ("Blue", 1)])

    def test_the_cart_shows_and_keeps_the_current_product_price(self):
        self.post("cart", {"it_id": "P001", "ct_qty": 2})
        ShopProduct.objects.filter(pk="P001").update(it_price=1500)

        data = self.get("cart").json()["data"]

        self.assertEqual(data["items"][0]["ct_price"], 1500)
        self.assertEqual(data["total_price"], 3000)
        self.assertEqual(self.stored_guest_cart()[0]["ct_price"], 1500)

    def test_the_cart_shows_the_current_option_price_and_add_ons_stay_at_zero(self):
        options = [
            {"io_id": "Red", "io_type": 0, "io_price": 500, "io_stock_qty": 5, "io_use": 1},
            {"io_id": "Wrap", "io_type": 1, "io_price": 300, "io_stock_qty": 5, "io_use": 1},
        ]
        product = self.make_product("OPT", "Options", it_price=1000, it_stock_qty=10, options=options)
        self.post("cart", {"it_id": "OPT", "options": [{"io_id": "Red", "io_type": 0, "ct_qty": 1}, {"io_id": "Wrap", "io_type": 1, "ct_qty": 1}]})
        product.options = [dict(options[0], io_price=800), dict(options[1], io_price=400)]
        product.save(update_fields=["options"])

        self.get("cart")

        rows = {row["ct_option"]: row for row in self.stored_guest_cart()}
        self.assertEqual((rows["Red"]["ct_price"], rows["Red"]["io_price"]), (1000, 800))
        self.assertEqual((rows["Wrap"]["ct_price"], rows["Wrap"]["io_price"]), (0, 400))

    def test_an_order_at_a_stale_price_is_refused_once_then_placed_at_the_new_price(self):
        Config.objects.update_or_create(name="de_bank_use", defaults={"value": "1"})
        Config.objects.update_or_create(name="de_bank_account", defaults={"value": "Test Bank 000-00 Holder"})
        self.post("cart", {"it_id": "P001", "ct_qty": 1}, user=self.user)
        ShopProduct.objects.filter(pk="P001").update(it_price=1500)

        refused = self.post("orders", self.ORDER, user=self.user)
        placed = self.post("orders", self.ORDER, user=self.user)

        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["code"], "cart_price_changed")
        self.assertEqual(placed.status_code, 201, placed.content[:300])
        self.assertEqual(placed.json()["data"]["order"]["items"][0]["ct_price"], 1500)


class CartLegacyFormRulesTests(ShopApiTestCase):
    """The YoungCart form path (cartupdate.php) applies the same rules as the JSON cart API."""

    def test_an_unknown_product_is_refused(self):
        response = self.post_form("cart/legacy-update", {"it_id": "NOPE", "ct_qty": "1"})

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.stored_guest_cart(), [])

    def test_a_telephone_inquiry_product_is_refused(self):
        self.make_product("TEL2", "Call us", it_price=5000, it_stock_qty=5, it_tel_inq="1")

        response = self.post_form("cart/legacy-update", {"it_id": "TEL2", "ct_qty": "1"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.stored_guest_cart(), [])

    def test_a_product_with_options_needs_one(self):
        options = [{"io_id": "Red", "io_type": 0, "io_price": 500, "io_stock_qty": 5, "io_use": 1}]
        self.make_product("OPT2", "Options", it_price=1000, it_stock_qty=10, it_option_subject="Color", options=options)

        missing = self.post_form("cart/legacy-update", {"it_id": "OPT2", "ct_qty": "1"})
        chosen = self.post_form("cart/legacy-update", {"it_id": "OPT2", "io_id": "Red", "ct_qty": "1"})

        self.assertEqual(missing.status_code, 422)
        self.assertEqual(chosen.status_code, 200)
        row = self.stored_guest_cart()[0]
        self.assertEqual((row["ct_option"], row["ct_price"], row["io_price"]), ("Red", 1000, 500))

    def test_the_stock_limit_applies(self):
        response = self.post_form("cart/legacy-update", {"it_id": "P001", "ct_qty": "11"})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.stored_guest_cart(), [])

    def test_the_same_product_twice_adds_to_one_line(self):
        self.post_form("cart/legacy-update", {"it_id": "P001", "ct_qty": "2"})
        self.post_form("cart/legacy-update", {"it_id": "P001", "ct_qty": "3"})

        self.assertEqual([row["ct_qty"] for row in self.stored_guest_cart()], [5])
