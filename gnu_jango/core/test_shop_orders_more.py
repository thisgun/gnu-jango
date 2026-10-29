"""More behaviour tests for gnu_jango/api/v1_shop.py (orders, shipping, catalog, personal pay).

Everything goes through the public /api/v1/shop/... routes. The cart, coupon, payment and
point-setting rules already have their own modules (test_shop_cart_api, test_shop_coupons_api,
test_shop_payments_api, test_shop_order_points); this file covers order creation and money
fields, order detail / list / cancel for members and guests, the guest order lookup, the
shipping quote, personal pay and the product catalogue views.

A test marked ``expectedFailure`` pins the behaviour YoungCart (Gnuboard5 shop) has and names
the source defect that stops it from holding today.
"""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.config.models import Config
from gnu_jango.shop.models import (
    ShopBanner,
    ShopCategory,
    ShopEvent,
    ShopEventItem,
    ShopOrder,
    ShopOrderItem,
    ShopPersonalPay,
    ShopProduct,
    ShopProductRelation,
    ShopShippingCost,
    ShopShippingPolicy,
    ShopStockNotification,
)
from gnu_jango.users.models import Profile, User_Point

API = "/api/v1/shop"
BANK = "Test Bank 000-00 Holder"
ZIP_PLAIN = "06236"
ZIP_REMOTE = "63000"
REMOTE_FEE = 4000

ORDER_FORM = {
    "od_name": "Buyer",
    "od_tel": "010-1111-2222",
    "od_hp": "010-1111-2222",
    "od_email": "buyer@example.test",
    "od_zip": ZIP_PLAIN,
    "od_addr1": "Seoul",
    "od_addr2": "1",
    "od_b_name": "Buyer",
    "od_b_tel": "010-1111-2222",
    "od_b_hp": "010-1111-2222",
    "od_b_zip": ZIP_PLAIN,
    "od_b_addr1": "Seoul",
    "od_b_addr2": "1",
    "od_settle_case": "bank",
    "od_bank_account": BANK,
    "od_deposit_name": "Buyer",
}


class ShopOrderBase(TestCase):
    """A member, a guest client, one 10000 won product and a bank account."""

    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.member = user_model.objects.create_user(username="more-member", email="more-member@example.test")
        self.other = user_model.objects.create_user(username="more-other", email="more-other@example.test")
        self.staff = user_model.objects.create_user(username="more-staff", email="more-staff@example.test", is_staff=True)
        self.profile, _ = Profile.objects.get_or_create(user=self.member)
        self.category = ShopCategory.objects.create(ca_id="40", ca_name="More category")
        self.product = self.make_product("MO001", "More product", it_price=10000, it_stock_qty=20)
        ShopShippingPolicy.objects.update_or_create(
            pk=1,
            # 3,000 below 50,000 (youngcart get_sendcost charges a shared fee only for 차등)
            defaults={"de_send_cost_case": "차등", "de_send_cost_limit": "50000", "de_send_cost_list": "3000", "de_delivery_company": "Courier", "de_settle_min_point": 1000, "de_settle_max_point": 100000, "de_settle_point_unit": 100},
        )
        Config.objects.update_or_create(name="de_bank_use", defaults={"value": "1"})
        Config.objects.update_or_create(name="de_bank_account", defaults={"value": BANK})
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)
        self.other_client = APIClient()
        self.other_client.force_authenticate(user=self.other)
        self.staff_client = APIClient()
        self.staff_client.force_authenticate(user=self.staff)
        self.guest = APIClient()

    def make_product(self, it_id, name, **fields):
        fields.setdefault("category", self.category)
        fields.setdefault("it_use", "1")
        return ShopProduct.objects.create(it_id=it_id, it_name=name, **fields)

    def add(self, client, product=None, qty=1, **extra):
        response = client.post(f"{API}/cart", {"it_id": (product or self.product).it_id, "ct_qty": qty, **extra}, format="json")
        self.assertIn(response.status_code, (200, 201), response.content[:300])
        return response

    def place(self, client=None, **fields):
        client = client or self.client
        payload = {**ORDER_FORM, **fields}
        return client.post(f"{API}/orders", payload, format="json")

    def place_ok(self, client=None, **fields):
        response = self.place(client, **fields)
        self.assertEqual(response.status_code, 201, response.content[:500])
        return ShopOrder.objects.get(pk=response.json()["data"]["od_id"])

    def order_of(self, client=None, product=None, qty=1, **fields):
        self.add(client or self.client, product, qty)
        return self.place_ok(client, **fields)

    def guest_order(self, product=None, qty=1, password="guest-pass", **fields):
        self.add(self.guest, product, qty)
        return self.place_ok(self.guest, od_pwd=password, **fields)

    def error_code(self, response):
        return response.json().get("code")

    def set_points(self, balance):
        self.profile.user_point = balance
        self.profile.save(update_fields=["user_point"])

    def reload(self, *objects):
        for obj in objects:
            obj.refresh_from_db()


class OrderCreationMoneyTests(ShopOrderBase):
    def test_a_bank_order_is_unpaid_and_owes_items_plus_shipping(self):
        order = self.order_of(qty=2)
        self.assertEqual(order.od_status, "주문")
        self.assertEqual(order.od_cart_price, 20000)
        self.assertEqual(order.od_send_cost, 3000)
        self.assertEqual(order.od_misu, 23000)
        self.assertEqual(order.od_receipt_price, 0)
        self.assertEqual(order.user, self.member)
        self.assertEqual(order.items.get().ct_qty, 2)

    def test_client_supplied_amounts_and_status_are_ignored(self):
        order = self.order_of(
            od_send_cost=0, od_send_cost2=0, od_receipt_price=1, od_misu=0, od_cart_price=1,
            od_status="입금", od_cancel_price=0, od_tno="x", ct_price=1, od_coupon=9999, od_send_coupon=9999,
        )
        self.assertEqual(order.od_status, "주문")
        self.assertEqual(order.od_cart_price, 10000)
        self.assertEqual(order.od_send_cost, 3000)
        self.assertEqual(order.od_receipt_price, 0)
        self.assertEqual(order.od_misu, 13000)
        self.assertEqual(order.od_coupon, 0)
        self.assertEqual(order.od_send_coupon, 0)
        self.assertEqual(order.od_tno, "")

    def test_a_client_supplied_cart_line_price_is_ignored(self):
        self.add(self.client, ct_price=1)
        order = self.place_ok()
        self.assertEqual(order.od_cart_price, 10000)
        self.assertEqual(order.items.get().ct_price, 10000)

    def test_shipping_is_free_from_the_default_threshold(self):
        order = self.order_of(qty=5)
        self.assertEqual(order.od_cart_price, 50000)
        self.assertEqual(order.od_send_cost, 0)
        self.assertEqual(order.od_misu, 50000)

    def test_a_tiered_shipping_policy_prices_each_step(self):
        ShopShippingPolicy.objects.filter(pk=1).update(
            de_send_cost_case="차등", de_send_cost_limit="20000;60000", de_send_cost_list="5000;2000"
        )
        self.assertEqual(self.order_of(qty=1).od_send_cost, 5000)
        self.assertEqual(self.order_of(qty=3).od_send_cost, 2000)
        self.assertEqual(self.order_of(qty=6).od_send_cost, 0)

    def test_a_free_shipping_policy_charges_nothing(self):
        ShopShippingPolicy.objects.filter(pk=1).update(de_send_cost_case="무료")
        order = self.order_of(qty=1)
        self.assertEqual((order.od_send_cost, order.od_send_cost2, order.od_misu), (0, 0, 10000))

    def test_remote_area_extra_is_added_for_the_recipient_zip(self):
        ShopShippingCost.objects.create(sc_id=1, sc_name="Island", sc_zip1="63000", sc_zip2="63999", sc_price=REMOTE_FEE)
        order = self.order_of(od_b_zip=ZIP_REMOTE)
        self.assertEqual(order.od_send_cost2, REMOTE_FEE)
        self.assertEqual(order.od_misu, 10000 + 3000 + REMOTE_FEE)

    def test_the_extra_follows_the_recipient_not_the_orderer_zip(self):
        ShopShippingCost.objects.create(sc_id=1, sc_name="Island", sc_zip1="63000", sc_zip2="63999", sc_price=REMOTE_FEE)
        self.assertEqual(self.order_of(od_zip=ZIP_REMOTE, od_b_zip=ZIP_PLAIN).od_send_cost2, 0)
        self.assertEqual(self.order_of(od_zip=ZIP_PLAIN, od_b_zip=ZIP_REMOTE).od_send_cost2, REMOTE_FEE)

    def test_split_zip_fields_are_combined_for_the_extra(self):
        ShopShippingCost.objects.create(sc_id=1, sc_name="Island", sc_zip1="63000", sc_zip2="63999", sc_price=REMOTE_FEE)
        form = {key: value for key, value in ORDER_FORM.items() if key not in ("od_zip", "od_b_zip")}
        self.add(self.client)
        response = self.client.post(f"{API}/orders", {**form, "od_b_zip1": "630", "od_b_zip2": "00"}, format="json")
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertEqual(response.json()["data"]["order"]["od_send_cost2"], REMOTE_FEE)

    def test_a_zip_outside_every_remote_range_costs_nothing_extra(self):
        ShopShippingCost.objects.create(sc_id=1, sc_name="Island", sc_zip1="63000", sc_zip2="63999", sc_price=REMOTE_FEE)
        self.assertEqual(self.order_of(od_b_zip="64000").od_send_cost2, 0)

    def test_cancel_clears_the_shipping_and_the_amount_owed(self):
        order = self.order_of()
        self.client.patch(f"{API}/orders/{order.od_id}", {"reason": "changed my mind"}, format="json")
        self.reload(order)
        self.assertEqual(order.od_status, "취소")
        self.assertEqual((order.od_send_cost, order.od_misu, order.od_receipt_price), (0, 0, 0))
        self.assertEqual(order.od_cancel_price, 10000)

    def test_the_created_order_payload_reports_totals_and_redirects(self):
        self.add(self.client)
        body = self.place().json()["data"]
        order = body["order"]
        self.assertEqual(body["redirect_url"], f"/shop/orders/{body['od_id']}")
        self.assertEqual(order["od_total_price"], 13000)
        self.assertEqual(order["od_misu_price"], 13000)
        self.assertEqual(order["od_bank_account"], BANK)
        self.assertTrue(order["can_cancel"])
        self.assertEqual(len(order["items"]), 1)
        self.assertEqual(order["items"][0]["line_total"], 10000)

    def test_a_non_bank_order_made_directly_is_not_marked_paid(self):
        # DEFECT v1_shop.py:692 create_order_from_request: any od_settle_case other than a bank
        # transfer gets ORDER_STATUS_PAID, od_receipt_price = the whole amount and od_misu = 0, so
        # POST /shop/orders {"od_settle_case": "card"} yields a paid order without any payment.
        # YoungCart orderformupdate.php sets od_status 입금 only after the gateway approval.
        self.add(self.client)
        response = self.place(od_settle_case="card")
        if response.status_code == 201:
            order = ShopOrder.objects.get(pk=response.json()["data"]["od_id"])
            self.assertNotIn(order.od_status, ("입금", "배송"))
            self.assertEqual(order.od_receipt_price, 0)
            self.assertGreater(order.od_misu, 0)
        else:
            self.assertEqual(response.status_code, 400)


class OrderCreationValidationTests(ShopOrderBase):
    def test_an_empty_cart_cannot_be_ordered(self):
        response = self.place()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.error_code(response), "cart_empty")
        self.assertEqual(ShopOrder.objects.count(), 0)

    def test_ct_ids_of_another_members_cart_order_nothing(self):
        self.add(self.other_client)
        foreign = self.other_client.get(f"{API}/cart").json()["data"]["items"][0]["ct_id"]
        response = self.place(ct_ids=[foreign])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.error_code(response), "cart_empty")
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 20)

    def test_ct_ids_order_only_the_selected_lines_and_keep_the_rest(self):
        second = self.make_product("MO002", "Second", it_price=7000, it_stock_qty=5)
        self.add(self.client)
        self.add(self.client, second)
        rows = self.client.get(f"{API}/cart").json()["data"]["items"]
        picked = next(row["ct_id"] for row in rows if row["it_id"] == "MO002")
        order = self.place_ok(ct_ids=[picked])
        self.assertEqual(order.od_cart_price, 7000)
        self.assertEqual([item.it_id for item in order.items.all()], ["MO002"])
        remaining = self.client.get(f"{API}/cart").json()["data"]["items"]
        self.assertEqual([row["it_id"] for row in remaining], ["MO001"])

    def test_the_cart_is_emptied_after_the_order(self):
        self.order_of()
        self.assertEqual(self.client.get(f"{API}/cart").json()["data"]["items"], [])

    def test_a_bank_order_needs_a_configured_account(self):
        Config.objects.filter(name="de_bank_use").update(value="0")
        self.add(self.client)
        response = self.place()
        self.assertEqual(self.error_code(response), "bank_transfer_unavailable")
        self.assertEqual(ShopOrder.objects.count(), 0)

    def test_a_bank_account_that_is_not_configured_is_refused(self):
        self.add(self.client)
        response = self.place(od_bank_account="Evil Bank 999")
        self.assertEqual(self.error_code(response), "bank_account_invalid")

    def test_a_depositor_name_is_required_and_bounded(self):
        self.add(self.client)
        self.assertEqual(self.error_code(self.place(od_deposit_name="  ")), "deposit_name_required")
        self.assertEqual(self.error_code(self.place(od_deposit_name="x" * 101)), "deposit_name_too_long")
        self.assertEqual(ShopOrder.objects.count(), 0)

    def test_guests_cannot_request_receipts(self):
        self.add(self.guest)
        for field in ("od_cash_request", "od_tax_invoice_request"):
            response = self.place(self.guest, od_pwd="guest-pass", **{field: 1})
            self.assertEqual(self.error_code(response), "receipt_request_requires_member", field)
        self.assertEqual(ShopOrder.objects.count(), 0)

    def test_a_guest_needs_an_order_password(self):
        self.add(self.guest)
        response = self.place(self.guest)
        self.assertEqual(self.error_code(response), "guest_order_password_required")
        self.assertEqual(self.error_code(self.place(self.guest, od_pwd="   ")), "guest_order_password_required")

    def test_a_product_disabled_after_it_was_carted_is_not_orderable(self):
        self.add(self.client)
        ShopProduct.objects.filter(pk=self.product.pk).update(it_use="0")
        response = self.place()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.error_code(response), "product_unavailable")
        self.assertEqual(ShopOrder.objects.count(), 0)

    def test_a_product_sold_out_after_it_was_carted_is_not_orderable(self):
        self.add(self.client)
        ShopProduct.objects.filter(pk=self.product.pk).update(it_soldout="1")
        self.assertEqual(self.error_code(self.place()), "product_unavailable")

    def test_stock_that_ran_out_stops_the_order_and_changes_nothing(self):
        second = self.make_product("MO002", "Second", it_price=7000, it_stock_qty=5)
        self.add(self.client, qty=3)
        self.add(self.client, second, qty=2)
        ShopProduct.objects.filter(pk=second.pk).update(it_stock_qty=1)
        response = self.place()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.error_code(response), "insufficient_stock")
        self.assertEqual(ShopOrder.objects.count(), 0)
        self.assertEqual(ShopOrderItem.objects.count(), 0)
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 20)

    def test_ordering_the_last_unit_marks_the_product_sold_out(self):
        last = self.make_product("MO003", "Last one", it_price=5000, it_stock_qty=1)
        self.order_of(product=last)
        last.refresh_from_db()
        self.assertEqual(last.it_stock_qty, 0)
        self.assertEqual(last.it_soldout, "1")

    def test_ordering_reserves_the_stock(self):
        self.order_of(qty=4)
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 16)

    def test_saving_the_address_with_an_order_stores_it_once_as_default(self):
        from gnu_jango.shop.models import ShopAddress

        first = ShopAddress.objects.create(user=self.member, ad_subject="Old", ad_default=True, ad_name="Old", ad_zip="11111", ad_addr1="Old road")
        self.order_of(ad_default=1, ad_subject="Home")
        first.refresh_from_db()
        self.assertFalse(first.ad_default)
        saved = ShopAddress.objects.get(user=self.member, ad_subject="Home")
        self.assertTrue(saved.ad_default)
        self.assertEqual(saved.ad_zip, ZIP_PLAIN)

    def test_a_guest_order_is_remembered_in_the_session_and_never_listed(self):
        order = self.guest_order()
        self.assertIsNone(order.user)
        self.assertIn(order.od_id, self.guest.session["g5_guest_order_ids"])
        listing = self.guest.get(f"{API}/orders")
        self.assertEqual(listing.json()["data"], [])
        redirect = self.guest.get(f"{API}/orders/{order.od_id}?uid={order.uid}")
        self.assertEqual(redirect.status_code, 200)

    def test_guest_order_redirect_carries_the_uid(self):
        self.add(self.guest)
        body = self.place(self.guest, od_pwd="guest-pass").json()["data"]
        self.assertTrue(body["redirect_url"].endswith(f"?uid={body['uid']}"))

    def test_guests_cannot_spend_points_even_by_asking(self):
        order = self.guest_order(point_use=5000, od_receipt_point=5000)
        self.assertEqual(order.od_receipt_point, 0)

    def test_the_order_is_recorded_with_the_callers_address(self):
        order = self.order_of()
        self.assertEqual(order.od_ip, "127.0.0.1")
        self.assertEqual(order.od_b_addr1, "Seoul")
        self.assertEqual(order.od_email, "buyer@example.test")


class OrderPointEdgeTests(ShopOrderBase):
    def test_negative_and_garbage_point_requests_use_nothing(self):
        self.set_points(50000)
        for requested in (-5000, "lots", None, "", [1], {"a": 1}):
            order = self.order_of(point_use=requested)
            self.assertEqual(order.od_receipt_point, 0, repr(requested))
        self.reload(self.profile)
        self.assertEqual(self.profile.user_point, 50000)

    def test_points_never_pay_the_shipping(self):
        # the use is capped by the item amount (YoungCart $tot_od_price), so shipping stays payable
        self.set_points(100000)
        order = self.order_of(point_use=100000)
        self.assertEqual(order.od_receipt_point, 10000)
        self.assertEqual(order.od_misu, 3000)

    def test_switching_points_off_ignores_the_request(self):
        Config.objects.update_or_create(name="cf_use_point", defaults={"value": "0"})
        self.set_points(50000)
        order = self.order_of(point_use=5000)
        self.assertEqual(order.od_receipt_point, 0)
        self.reload(self.profile)
        self.assertEqual(self.profile.user_point, 50000)
        self.assertFalse(User_Point.objects.filter(user=self.member, po_rel_table="@order").exists())

    def test_the_amount_owed_drops_by_the_points_used(self):
        self.set_points(50000)
        order = self.order_of(point_use=4000)
        self.assertEqual(order.od_receipt_point, 4000)
        self.assertEqual(order.od_misu, 10000 + 3000 - 4000)

    def test_a_member_cancel_through_the_order_route_returns_the_points_and_stock(self):
        self.set_points(50000)
        order = self.order_of(qty=2, point_use=5000)
        response = self.client.patch(f"{API}/orders/{order.od_id}", {"reason": "mind"}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.reload(self.profile, self.product, order)
        self.assertEqual(self.profile.user_point, 50000)
        self.assertEqual(self.product.it_stock_qty, 20)
        self.assertEqual(order.od_status, "취소")
        self.assertEqual(order.od_receipt_point, 0)
        self.assertEqual(User_Point.objects.filter(user=self.member, po_rel_table="@order-cancel").count(), 1)
        self.assertEqual(response.json()["data"]["od_status"], "취소")
        self.assertEqual(response.json()["data"]["items"][0]["ct_status"], "취소")


class OrderDirectCreateMixin:
    """Orders written straight to the database in a given state (admin-side states)."""

    def make_order(self, status, user=None, qty=2, od_id="MORE-ORD-1", **fields):
        order = ShopOrder.objects.create(
            od_id=od_id,
            user=user,
            od_name="Direct",
            od_cart_price=10000 * qty,
            od_send_cost=3000,
            od_receipt_price=10000 * qty + 3000,
            od_misu=0,
            od_status=status,
            od_settle_case="bank",
            **fields,
        )
        ShopProduct.objects.filter(pk=self.product.pk).update(it_stock_qty=20 - qty)
        ShopOrderItem.objects.create(
            order=order, product=self.product, ct_id=f"{od_id}-1", it_id=self.product.it_id,
            it_name=self.product.it_name, ct_price=10000, ct_qty=qty, ct_status=status, stock_adjusted=True,
        )
        return order


class OrderDetailAccessTests(OrderDirectCreateMixin, ShopOrderBase):
    def test_the_owner_reads_the_order_with_its_lines(self):
        order = self.order_of(qty=2)
        body = self.client.get(f"{API}/orders/{order.od_id}").json()["data"]
        self.assertEqual(body["od_id"], order.od_id)
        self.assertEqual(body["mb_id"], "more-member")
        self.assertEqual([(row["it_id"], row["ct_qty"], row["line_total"]) for row in body["items"]], [("MO001", 2, 20000)])

    def test_another_member_gets_not_found_for_get_and_patch(self):
        order = self.order_of()
        self.assertEqual(self.other_client.get(f"{API}/orders/{order.od_id}").status_code, 404)
        self.assertEqual(self.other_client.patch(f"{API}/orders/{order.od_id}", {"reason": "x"}, format="json").status_code, 404)
        self.reload(order, self.product)
        self.assertEqual(order.od_status, "주문")
        self.assertEqual(self.product.it_stock_qty, 19)

    def test_an_anonymous_caller_cannot_read_a_member_order_even_with_its_uid(self):
        order = self.order_of()
        self.assertEqual(APIClient().get(f"{API}/orders/{order.od_id}").status_code, 404)
        self.assertEqual(APIClient().get(f"{API}/orders/{order.od_id}?uid={order.uid}").status_code, 404)
        self.assertEqual(APIClient().patch(f"{API}/orders/{order.od_id}?uid={order.uid}", {}, format="json").status_code, 404)

    def test_another_member_cannot_use_a_member_orders_uid(self):
        order = self.order_of()
        self.assertEqual(self.other_client.get(f"{API}/orders/{order.od_id}?uid={order.uid}").status_code, 404)

    def test_a_guest_reads_the_order_with_its_uid_only(self):
        order = self.guest_order()
        fresh = APIClient()
        self.assertEqual(fresh.get(f"{API}/orders/{order.od_id}").status_code, 404)
        self.assertEqual(fresh.get(f"{API}/orders/{order.od_id}?uid=wrong").status_code, 404)
        shown = fresh.get(f"{API}/orders/{order.od_id}?uid={order.uid}")
        self.assertEqual(shown.status_code, 200)
        self.assertEqual(shown.json()["data"]["mb_id"], "")

    def test_a_uid_opens_only_its_own_order(self):
        first = self.guest_order()
        second = self.guest_order(password="other-pass")
        self.assertEqual(APIClient().get(f"{API}/orders/{second.od_id}?uid={first.uid}").status_code, 404)

    def test_order_ids_cannot_be_enumerated_by_guessing_neighbours(self):
        order = self.guest_order()
        neighbour = str(int(order.od_id) + 1)
        self.assertEqual(APIClient().get(f"{API}/orders/{neighbour}").status_code, 404)
        self.assertEqual(APIClient().get(f"{API}/orders/{order.od_id}%20").status_code, 404)

    def test_a_signed_in_member_may_open_a_guest_order_with_its_uid(self):
        order = self.guest_order()
        self.assertEqual(self.client.get(f"{API}/orders/{order.od_id}?uid={order.uid}").status_code, 200)

    def test_an_unknown_order_is_not_found(self):
        self.assertEqual(self.client.get(f"{API}/orders/nope").status_code, 404)

    def test_staff_cannot_read_a_customers_order_through_the_shop_route(self):
        order = self.order_of()
        self.assertEqual(self.staff_client.get(f"{API}/orders/{order.od_id}").status_code, 404)


class OrderListTests(ShopOrderBase):
    def test_a_member_lists_only_their_own_orders(self):
        mine = self.order_of()
        self.order_of(client=self.other_client)
        rows = self.client.get(f"{API}/orders").json()["data"]
        self.assertEqual([row["od_id"] for row in rows], [mine.od_id])

    def test_per_page_is_capped_and_bad_paging_values_do_not_crash(self):
        self.order_of()
        meta = self.client.get(f"{API}/orders?per_page=100000").json()["meta"]
        self.assertEqual(meta["per_page"], 100)
        for query in ("per_page=abc", "per_page=-4", "per_page=0", "page=abc", "page=-1", "page=9999&limit=x"):
            response = self.client.get(f"{API}/orders?{query}")
            self.assertEqual(response.status_code, 200, query)
        self.assertEqual(self.client.get(f"{API}/orders?page=9999").json()["data"], [])

    def test_the_list_pages_through_the_orders(self):
        for _ in range(3):
            self.order_of()
        first = self.client.get(f"{API}/orders?per_page=2").json()
        second = self.client.get(f"{API}/orders?per_page=2&page=2").json()
        self.assertEqual((first["meta"]["total"], len(first["data"]), len(second["data"])), (3, 2, 1))
        self.assertEqual(first["meta"]["last_page"], 2)

    def test_an_anonymous_caller_sees_an_empty_list(self):
        self.order_of()
        self.assertEqual(APIClient().get(f"{API}/orders").json()["data"], [])


class OrderCancelTests(OrderDirectCreateMixin, ShopOrderBase):
    def test_cancelling_twice_puts_the_stock_back_once(self):
        order = self.order_of(qty=3)
        first = self.client.patch(f"{API}/orders/{order.od_id}", {}, format="json")
        second = self.client.patch(f"{API}/orders/{order.od_id}", {}, format="json")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(self.error_code(second), "order_cancel_blocked")
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 20)

    def test_the_cancel_reason_is_kept_on_the_order(self):
        order = self.order_of()
        self.client.patch(f"{API}/orders/{order.od_id}", {"reason": "wrong size"}, format="json")
        order.refresh_from_db()
        self.assertIn("wrong size", order.od_memo)

    def test_a_paid_order_cannot_be_cancelled_by_the_customer_at_any_step(self):
        # YoungCart orderinquirycancel.php: only od_status == '주문' with every line still '주문'.
        # 준비 (preparing) and 완료 (delivered) are paid like 입금/배송, so the customer is sent to the
        # shop rather than told the order is not cancellable for some other reason.
        for index, status in enumerate(("입금", "준비", "배송", "완료")):
            order = self.make_order(status, user=self.member, od_id=f"MORE-P{index}")
            response = self.client.patch(f"{API}/orders/{order.od_id}", {}, format="json")
            self.assertEqual(response.status_code, 400, status)
            self.assertEqual(self.error_code(response), "order_cancel_blocked", status)
            self.assertEqual(response.json()["message"], "입금 이후 주문은 관리자에게 문의해 주세요.", status)
            self.reload(order, self.product)
            self.assertEqual(order.od_status, status)
            self.assertEqual(order.items.get().ct_status, status)
            self.assertEqual(self.product.it_stock_qty, 18)

    def test_an_order_already_partly_cancelled_cannot_be_cancelled_again(self):
        # DEFECT shop_common.py:257: od_cancel_price > 0 or a line that is no longer '주문' is not
        # checked. YoungCart orderinquirycancel.php refuses
        # (od_cancel_price > 0 || od_status != '주문' || count of '주문' lines != count of lines).
        order = self.make_order("주문", user=self.member, od_id="MORE-PART", od_cancel_price=10000)
        order.items.update(ct_status="완료")
        response = self.client.patch(f"{API}/orders/{order.od_id}", {}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_a_cancelled_order_stays_readable_and_reports_why_it_is_closed(self):
        order = self.order_of()
        self.client.patch(f"{API}/orders/{order.od_id}", {}, format="json")
        body = self.client.get(f"{API}/orders/{order.od_id}").json()["data"]
        self.assertFalse(body["can_cancel"])
        self.assertTrue(body["cancel_block_reason"])
        self.assertEqual(body["od_total_price"], 0)

    def test_a_guest_cancels_with_the_uid_and_stock_comes_back(self):
        order = self.guest_order(qty=2)
        response = APIClient().patch(f"{API}/orders/{order.od_id}?uid={order.uid}", {"reason": "guest"}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.reload(order, self.product)
        self.assertEqual(order.od_status, "취소")
        self.assertEqual(self.product.it_stock_qty, 20)

    def test_a_guest_with_a_wrong_uid_cancels_nothing(self):
        order = self.guest_order(qty=2)
        for client, query in ((APIClient(), "?uid=wrong"), (APIClient(), ""), (self.guest, "")):
            response = client.patch(f"{API}/orders/{order.od_id}{query}", {}, format="json")
            self.assertEqual(response.status_code, 404, query)
        self.reload(order, self.product)
        self.assertEqual(order.od_status, "주문")
        self.assertEqual(self.product.it_stock_qty, 18)

    def test_a_uid_in_the_body_works_like_one_in_the_query(self):
        order = self.guest_order()
        response = APIClient().patch(f"{API}/orders/{order.od_id}", {"uid": order.uid}, format="json")
        self.assertEqual(response.status_code, 200)

    def test_a_member_cannot_cancel_a_guest_order_without_its_uid(self):
        order = self.guest_order()
        self.assertEqual(self.client.patch(f"{API}/orders/{order.od_id}", {}, format="json").status_code, 404)

    def test_the_payment_cancel_route_does_not_cancel_a_shipped_order_either(self):
        order = self.make_order("배송", user=self.member, od_id="MORE-SHIP")
        response = self.client.post(f"{API}/payment/cancel", {"order_id": order.od_id}, format="json")
        self.assertEqual(response.status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.od_status, "배송")

    def test_a_manually_sold_out_product_stays_sold_out_after_a_cancel(self):
        # DEFECT inventory.py cancel_order_with_stock_restore: any cancel that brings the stock
        # above zero clears it_soldout, also when an administrator set 품절 on purpose. YoungCart
        # keeps it_soldout as the admin set it (the stock restore only touches the quantity).
        order = self.order_of(qty=2)
        ShopProduct.objects.filter(pk=self.product.pk).update(it_soldout="1")
        self.client.patch(f"{API}/orders/{order.od_id}", {}, format="json")
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 20)
        self.assertEqual(self.product.it_soldout, "1")

    def test_cancelling_restores_option_stock_not_product_stock(self):
        option = {"io_id": "Red", "io_type": 0, "io_price": 500, "io_stock_qty": 5, "io_use": 1}
        product = self.make_product("MO010", "Optioned", it_price=2000, it_stock_qty=0, options=[option])
        response = self.client.post(f"{API}/cart", {"it_id": product.it_id, "options": [{"io_id": "Red", "ct_qty": 2}]}, format="json")
        self.assertEqual(response.status_code, 201, response.content[:300])
        order = self.place_ok()
        product.refresh_from_db()
        self.assertEqual(product.options[0]["io_stock_qty"], 3)
        self.client.patch(f"{API}/orders/{order.od_id}", {}, format="json")
        product.refresh_from_db()
        self.assertEqual(product.options[0]["io_stock_qty"], 5)
        self.assertEqual(product.it_stock_qty, 0)


class GuestOrderLookupTests(ShopOrderBase):
    def lookup(self, **body):
        return APIClient().post(f"{API}/orders/lookup", body, format="json")

    def test_the_right_password_returns_the_uid_and_redirect(self):
        order = self.guest_order(password="s3cret!")
        response = self.lookup(od_id=order.od_id, od_pwd="s3cret!")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual(data["uid"], order.uid)
        self.assertEqual(data["redirect_url"], f"/shop/orders/{order.od_id}?uid={order.uid}")

    def test_wrong_empty_and_missing_passwords_are_all_not_found(self):
        order = self.guest_order(password="s3cret!")
        for body in ({"od_pwd": "S3cret!"}, {"od_pwd": ""}, {}, {"od_pwd": None}, {"od_pwd": ["s3cret!"]}, {"od_pwd": {"a": 1}}, {"od_pwd": 0}):
            response = self.lookup(od_id=order.od_id, **body)
            self.assertEqual(response.status_code, 404, body)
            self.assertNotIn(order.uid, response.content.decode())

    def test_an_unknown_or_malformed_order_id_is_not_found(self):
        for od_id in ("", "999", None, 12, ["a"], {"a": 1}, "x" * 500):
            self.assertEqual(self.lookup(od_id=od_id, od_pwd="s3cret!").status_code, 404, repr(od_id))

    def test_a_member_order_cannot_be_opened_this_way(self):
        from gnu_jango.api.shop_common import guest_order_password_config_name

        order = self.order_of()
        Config.objects.update_or_create(name=guest_order_password_config_name(order.od_id), defaults={"value": "plain"})
        self.assertEqual(self.lookup(od_id=order.od_id, od_pwd="plain").status_code, 404)

    def test_an_order_without_a_stored_password_cannot_be_opened(self):
        order = ShopOrder.objects.create(od_id="MORE-NOPWD", od_name="Legacy")
        for password in ("", "anything", None):
            self.assertEqual(self.lookup(od_id=order.od_id, od_pwd=password).status_code, 404)

    def test_one_orders_password_does_not_open_another_order(self):
        first = self.guest_order(password="same-pass")
        second = self.guest_order(password="different")
        self.assertEqual(self.lookup(od_id=second.od_id, od_pwd="same-pass").status_code, 404)
        self.assertEqual(self.lookup(od_id=first.od_id, od_pwd="same-pass").status_code, 200)

    def test_the_stored_password_is_a_hash_not_the_password(self):
        from gnu_jango.api.shop_common import guest_order_password_config_name

        order = self.guest_order(password="visible-pass")
        stored = Config.objects.get(name=guest_order_password_config_name(order.od_id)).value
        self.assertNotIn("visible-pass", stored)

    def test_many_wrong_guesses_never_reveal_the_order(self):
        order = self.guest_order(password="s3cret!")
        statuses = {self.lookup(od_id=order.od_id, od_pwd=f"guess-{index}").status_code for index in range(15)}
        # wrong passwords give 404, and past the rate limit 429 - never the order
        self.assertTrue(statuses <= {404, 429}, statuses)


class ShippingQuoteTests(ShopOrderBase):
    def quote(self, client=None, query=""):
        return (client or self.client).get(f"{API}/shipping/quote{query}")

    def test_an_empty_cart_cannot_be_quoted(self):
        response = self.quote()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.error_code(response), "cart_empty")

    def test_below_the_threshold_the_base_fee_applies_and_the_gap_is_reported(self):
        self.add(self.client, qty=2)
        data = self.quote().json()["data"]
        self.assertEqual((data["item_total"], data["base"], data["extra"], data["total"]), (20000, 3000, 0, 3000))
        self.assertEqual((data["free_threshold"], data["free_remaining"]), (50000, 30000))

    def test_from_the_threshold_on_shipping_is_free(self):
        self.add(self.client, qty=5)
        data = self.quote().json()["data"]
        self.assertEqual((data["base"], data["total"], data["free_remaining"]), (0, 0, 0))

    def test_a_remote_zip_adds_the_extra_fee_by_zip_or_split_zip(self):
        ShopShippingCost.objects.create(sc_id=1, sc_name="Island", sc_zip1="63000", sc_zip2="63999", sc_price=REMOTE_FEE)
        self.add(self.client)
        for query in (f"?zip={ZIP_REMOTE}", f"?od_b_zip={ZIP_REMOTE}", "?zip1=630&zip2=00"):
            data = self.quote(query=query).json()["data"]
            self.assertEqual((data["extra"], data["total"]), (REMOTE_FEE, 3000 + REMOTE_FEE), query)
        self.assertEqual(self.quote(query=f"?zip={ZIP_PLAIN}").json()["data"]["extra"], 0)

    def test_the_quote_matches_what_the_order_then_charges(self):
        ShopShippingCost.objects.create(sc_id=1, sc_name="Island", sc_zip1="63000", sc_zip2="63999", sc_price=REMOTE_FEE)
        self.add(self.client, qty=3)
        quoted = self.quote(query=f"?zip={ZIP_REMOTE}").json()["data"]
        order = self.place_ok(od_b_zip=ZIP_REMOTE)
        self.assertEqual((order.od_send_cost, order.od_send_cost2), (quoted["base"], quoted["extra"]))

    def test_the_quote_follows_the_selected_cart_lines(self):
        second = self.make_product("MO002", "Second", it_price=45000, it_stock_qty=5)
        self.add(self.client)
        self.add(self.client, second)
        rows = self.client.get(f"{API}/cart").json()["data"]["items"]
        picked = next(row["ct_id"] for row in rows if row["it_id"] == "MO002")
        self.assertEqual(self.quote().json()["data"]["total"], 0)
        self.assertEqual(self.quote(query=f"?ct_ids={picked}").json()["data"]["item_total"], 45000)

    def test_a_guest_can_quote_the_session_cart(self):
        self.add(self.guest)
        self.assertEqual(self.quote(self.guest).json()["data"]["total"], 3000)

    def test_bad_zip_values_do_not_crash_the_quote(self):
        self.add(self.client)
        for zip_value in ("abc", "", "0", "99999999999999999999", "%27%20OR%201=1"):
            self.assertEqual(self.quote(query=f"?zip={zip_value}").status_code, 200, zip_value)

    def test_overlapping_ranges_use_the_first_rule(self):
        ShopShippingCost.objects.create(sc_id=1, sc_name="A", sc_zip1="63000", sc_zip2="63999", sc_price=2500)
        ShopShippingCost.objects.create(sc_id=2, sc_name="B", sc_zip1="63000", sc_zip2="63999", sc_price=9000)
        self.add(self.client)
        self.assertEqual(self.quote(query=f"?zip={ZIP_REMOTE}").json()["data"]["extra"], 2500)


class ItemShippingTypeTests(ShopOrderBase):
    """YoungCart get_item_sendcost: a product's own shipping type overrides the shop default.

    DEFECT (all four tests): shipping_quote() in gnu_jango/shop/shipping.py, used by
    v1_shop.py:646 create_order_from_request and by the cart and quote views, only looks at the
    cart total and the shop-wide rule. ShopProduct.it_sc_type / it_sc_price / it_sc_minimum /
    it_sc_qty are stored and shown but never change the shipping money.
    PHP reference: lib/shop.lib.php get_sendcost() and get_item_sendcost().
    """

    def test_a_free_shipping_product_ships_free_below_the_shop_threshold(self):
        # type 1: shipping 0
        product = self.make_product("MO020", "Free ship", it_price=10000, it_stock_qty=50, it_sc_type=1)
        self.add(self.client, product, qty=2)
        self.assertEqual(self.place_ok().od_send_cost, 0)

    def test_a_paid_shipping_product_charges_its_own_fee_even_above_the_free_threshold(self):
        # type 3: always it_sc_price
        product = self.make_product("MO021", "Paid ship", it_price=30000, it_stock_qty=50, it_sc_type=3, it_sc_price=7000)
        self.add(self.client, product, qty=3)
        self.assertEqual(self.place_ok().od_send_cost, 7000)

    def test_a_conditional_free_product_is_free_only_from_its_own_minimum(self):
        # type 2: free when the item amount reaches it_sc_minimum, else it_sc_price
        product = self.make_product("MO022", "Cond ship", it_price=10000, it_stock_qty=50, it_sc_type=2, it_sc_price=2500, it_sc_minimum=15000)
        self.add(self.client, product, qty=1)
        self.assertEqual(self.place_ok().od_send_cost, 2500)

    def test_a_per_quantity_product_charges_its_fee_for_each_started_batch(self):
        # type 4: it_sc_price * ceil(qty / it_sc_qty)
        product = self.make_product("MO023", "Per qty ship", it_price=1000, it_stock_qty=50, it_sc_type=4, it_sc_price=1500, it_sc_qty=3)
        self.add(self.client, product, qty=7)
        self.assertEqual(self.place_ok().od_send_cost, 4500)


class CatalogBase(ShopOrderBase):
    def names(self, response):
        self.assertEqual(response.status_code, 200, response.content[:300])
        return [row["it_name"] for row in response.json()["data"]]


class ProductListTests(CatalogBase):
    def setUp(self):
        super().setUp()
        self.cheap = self.make_product("CAT-A", "Alpha lamp", it_price=1000, it_stock_qty=5, it_basic="soft light", it_sum_qty=9, it_type1="1")
        self.dear = self.make_product("CAT-B", "Beta chair", it_price=9000, it_stock_qty=5, it_type2="1", it_sum_qty=2)
        self.hidden = self.make_product("CAT-H", "Hidden lamp", it_price=500, it_stock_qty=5, it_use="0")
        self.product.delete()

    def test_unsold_products_are_not_listed(self):
        self.assertEqual(sorted(self.names(self.client.get(f"{API}/products"))), ["Alpha lamp", "Beta chair"])

    def test_the_list_is_public(self):
        self.assertEqual(APIClient().get(f"{API}/products").status_code, 200)

    def test_search_matches_name_description_and_id_but_not_unsold_products(self):
        self.assertEqual(self.names(self.client.get(f"{API}/products?q=lamp")), ["Alpha lamp"])
        self.assertEqual(self.names(self.client.get(f"{API}/products?stx=soft")), ["Alpha lamp"])
        self.assertEqual(self.names(self.client.get(f"{API}/products?q=CAT-B")), ["Beta chair"])
        self.assertEqual(self.names(self.client.get(f"{API}/products?q=nothing-like-this")), [])

    def test_search_input_with_quotes_and_percent_signs_does_not_crash(self):
        for text in ("%27%20OR%201%3D1--", "%25", "%22", "%5C", "%F0%9F%98%80"):
            self.assertEqual(self.client.get(f"{API}/products?q={text}").status_code, 200, text)

    def test_type_and_price_filters(self):
        self.assertEqual(self.names(self.client.get(f"{API}/products?type=1")), ["Alpha lamp"])
        self.assertEqual(self.names(self.client.get(f"{API}/products?it_type2=1")), ["Beta chair"])
        self.assertEqual(self.names(self.client.get(f"{API}/products?qfrom=2000")), ["Beta chair"])
        self.assertEqual(self.names(self.client.get(f"{API}/products?qto=2000")), ["Alpha lamp"])
        self.assertEqual(self.names(self.client.get(f"{API}/products?qfrom=abc&qto=-5")), [])

    def test_sorting_by_price_name_and_sales(self):
        self.assertEqual(self.names(self.client.get(f"{API}/products?sort=price_asc")), ["Alpha lamp", "Beta chair"])
        self.assertEqual(self.names(self.client.get(f"{API}/products?sort=price_desc")), ["Beta chair", "Alpha lamp"])
        self.assertEqual(self.names(self.client.get(f"{API}/products?sort=it_price&sortodr=desc")), ["Beta chair", "Alpha lamp"])
        self.assertEqual(self.names(self.client.get(f"{API}/products?sort=name")), ["Alpha lamp", "Beta chair"])
        self.assertEqual(self.names(self.client.get(f"{API}/products?sort=popular")), ["Alpha lamp", "Beta chair"])

    def test_an_unknown_sort_falls_back_to_the_default_order(self):
        for sort in ("password", "it_price;drop", "-it_price", "0"):
            self.assertEqual(self.client.get(f"{API}/products?sort={sort}").status_code, 200, sort)

    def test_per_page_is_capped_and_bad_values_do_not_crash(self):
        self.assertEqual(self.client.get(f"{API}/products?per_page=9999999").json()["meta"]["per_page"], 100)
        for query in ("per_page=abc", "page=zz", "per_page=-1", "page=0"):
            self.assertEqual(self.client.get(f"{API}/products?{query}").status_code, 200, query)
        one = self.client.get(f"{API}/products?per_page=1&page=2").json()
        self.assertEqual(len(one["data"]), 1)
        self.assertEqual(one["meta"]["total"], 2)

    def test_a_page_offset_beyond_the_database_integer_range_is_empty(self):
        response = self.client.get(f"{API}/products", {"page": "9000000000000000000"})

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"], [])

    def test_filtering_by_category_includes_secondary_assignments(self):
        other = ShopCategory.objects.create(ca_id="41", ca_name="Other")
        ShopProduct.objects.filter(pk="CAT-B").update(category2=other)
        self.assertEqual(self.names(self.client.get(f"{API}/products?ca_id=41")), ["Beta chair"])
        self.assertEqual(sorted(self.names(self.client.get(f"{API}/products?category=40"))), ["Alpha lamp", "Beta chair"])

    def test_products_of_a_hidden_category_are_not_listed(self):
        # DEFECT v1_shop.py:923 products_view (also product_detail_view, product_by_seo_view,
        # product_suggest_view, events) filters it_use only. A product whose category has
        # ca_use=0 stays visible and searchable. YoungCart search.php joins the category with
        # b.ca_use = 1 and item.php refuses `!($it['ca_use'] && $it['it_use'])` for non-admins.
        ShopCategory.objects.filter(pk="40").update(ca_use=False)
        self.assertEqual(self.names(self.client.get(f"{API}/products")), [])

    def test_a_product_of_a_hidden_category_cannot_be_opened(self):
        # DEFECT v1_shop.py:961 product_detail_view: see the hidden category test above (item.php).
        ShopCategory.objects.filter(pk="40").update(ca_use=False)
        self.assertEqual(self.client.get(f"{API}/products/CAT-A").status_code, 404)

    def test_every_list_row_has_the_review_and_coupon_summary(self):
        row = self.client.get(f"{API}/products?q=CAT-A").json()["data"][0]
        self.assertEqual((row["review_count"], row["qa_count"], row["has_coupon"]), (0, 0, False))


class ProductDetailTests(CatalogBase):
    def setUp(self):
        super().setUp()
        self.first = self.make_product("DET-1", "First", it_price=1000, it_stock_qty=5, it_seo_title="first-item")
        self.middle = self.make_product("DET-2", "Middle", it_price=2000, it_stock_qty=5, it_seo_title="middle-item")
        self.gap = self.make_product("DET-3", "Gap (unsold)", it_price=3000, it_stock_qty=5, it_use="0")
        self.last = self.make_product("DET-4", "Last", it_price=4000, it_stock_qty=5)

    def test_detail_returns_the_product_and_its_neighbours_without_unsold_ones(self):
        data = self.client.get(f"{API}/products/DET-2").json()["data"]
        self.assertEqual((data["it_name"], data["it_price"]), ("Middle", 2000))
        self.assertEqual(data["prev_item"]["it_id"], "DET-1")
        self.assertEqual(data["next_item"]["it_id"], "DET-4")

    def test_related_items_are_listed_in_order_and_skip_unsold_ones(self):
        for number, it_id in enumerate(("DET-4", "DET-3", "DET-1"), 1):
            ShopProductRelation.objects.create(product_id="DET-2", related_id=it_id, ir_no=number)
        data = self.client.get(f"{API}/products/DET-2").json()["data"]
        self.assertEqual([row["it_id"] for row in data["related_items"]], ["DET-4", "DET-1"])

    def test_the_legacy_smoke_relation_setting_is_no_longer_read(self):
        Config.objects.update_or_create(name="nextjs_smoke_rel_DET-2", defaults={"value": json.dumps({"related_csv": "DET-4"})})
        self.assertEqual(self.client.get(f"{API}/products/DET-2").json()["data"]["related_items"], [])

    def test_an_unsold_or_unknown_product_is_not_found_by_id_and_by_slug(self):
        self.assertEqual(self.client.get(f"{API}/products/DET-3").status_code, 404)
        self.assertEqual(self.client.get(f"{API}/products/NOPE").status_code, 404)
        ShopProduct.objects.filter(pk="DET-1").update(it_use="0")
        self.assertEqual(self.client.get(f"{API}/products/seo/first-item").status_code, 404)

    def test_the_seo_route_finds_a_sold_product(self):
        response = self.client.get(f"{API}/products/seo/middle-item")
        self.assertEqual(response.json()["data"]["it_id"], "DET-2")
        self.assertEqual(self.client.get(f"{API}/products/seo/nope").status_code, 404)

    def test_the_info_notice_is_unpacked_and_garbage_is_kept_as_text(self):
        ShopProduct.objects.filter(pk="DET-2").update(it_info_value=[{"key": "Origin", "title": "Origin", "value": "Korea"}])
        ShopProduct.objects.filter(pk="DET-4").update(it_info_title="plain text")
        middle = self.client.get(f"{API}/products/DET-2").json()["data"]
        last = self.client.get(f"{API}/products/DET-4").json()["data"]
        self.assertEqual(middle["it_info_items"], [{"key": "Origin", "title": "Origin", "value": "Korea", "example": ""}])
        self.assertEqual((last["it_info_title"], last["it_info_items"]), ("plain text", []))

    def test_option_subjects_are_derived_when_the_shop_left_them_empty(self):
        options = [
            {"io_id": "Red\x1eL", "io_type": 0, "io_price": 0, "io_stock_qty": 2, "io_use": 1},
            {"io_id": "Wrap", "io_type": 1, "io_price": 300, "io_stock_qty": 2, "io_use": 1},
        ]
        ShopProduct.objects.filter(pk="DET-2").update(options=options)
        data = self.client.get(f"{API}/products/DET-2").json()["data"]
        self.assertEqual(data["it_option_subject"], "선택 옵션 1,선택 옵션 2")
        self.assertEqual(data["it_supply_subject"], "추가 옵션")

    def test_images_are_deduplicated_and_fall_back_to_the_main_image(self):
        ShopProduct.objects.filter(pk="DET-2").update(images=["/a.jpg", {"url": "/a.jpg"}, {"src": "/b.jpg"}, 5, None])
        data = self.client.get(f"{API}/products/DET-2").json()["data"]
        self.assertEqual(data["images"], ["/a.jpg", "/b.jpg"])
        ShopProduct.objects.filter(pk="DET-4").update(images=[], image_url="/main.jpg")
        self.assertEqual(self.client.get(f"{API}/products/DET-4").json()["data"]["images"], ["/main.jpg"])

    def test_a_coupon_badge_shows_for_a_product_or_category_coupon(self):
        from gnu_jango.shop.models import ShopCoupon

        today = timezone.localdate()
        ShopCoupon.objects.create(user=self.member, cp_subject="Item", cp_method=0, cp_target="DET-1", cp_type=0, cp_price=100, cp_start=today, cp_end=today)
        ShopCoupon.objects.create(user=self.member, cp_subject="Cat", cp_method=1, cp_target="999", cp_type=0, cp_price=100, cp_start=today, cp_end=today)
        self.assertTrue(self.client.get(f"{API}/products/DET-1").json()["data"]["has_coupon"])
        self.assertFalse(self.client.get(f"{API}/products/DET-2").json()["data"]["has_coupon"])
        flags = {row["it_id"]: row["has_coupon"] for row in self.client.get(f"{API}/products").json()["data"]}
        self.assertTrue(flags["DET-1"])
        self.assertFalse(flags["DET-4"])


class ProductHitSuggestNotifyTests(CatalogBase):
    def test_a_hit_counts_once_per_session_and_day_per_product(self):
        other = self.make_product("HIT-2", "Other", it_price=1000, it_stock_qty=3)
        first = self.client.post(f"{API}/products/MO001/hit")
        again = self.client.post(f"{API}/products/MO001/hit")
        second = self.client.post(f"{API}/products/HIT-2/hit")
        self.assertEqual([first.json()["data"]["recorded"], again.json()["data"]["recorded"], second.json()["data"]["recorded"]], [True, False, True])
        self.product.refresh_from_db()
        other.refresh_from_db()
        self.assertEqual((self.product.it_hit, other.it_hit), (1, 1))

    def test_hits_of_unsold_or_unknown_products_are_refused(self):
        ShopProduct.objects.filter(pk="MO001").update(it_use="0")
        self.assertEqual(self.client.post(f"{API}/products/MO001/hit").status_code, 404)
        self.assertEqual(self.client.post(f"{API}/products/NOPE/hit").status_code, 404)

    def test_a_hit_from_a_new_session_counts_again(self):
        self.client.post(f"{API}/products/MO001/hit")
        self.assertTrue(APIClient().post(f"{API}/products/MO001/hit").json()["data"]["recorded"])

    def test_suggestions_need_two_characters_and_skip_unsold_products(self):
        self.make_product("SUG-1", "Sugar bowl", it_price=100, it_stock_qty=1)
        self.make_product("SUG-2", "Sugar hidden", it_price=100, it_stock_qty=1, it_use="0")
        self.assertEqual(self.client.get(f"{API}/products/suggest?q=s").json()["data"], [])
        self.assertEqual(self.client.get(f"{API}/products/suggest").json()["data"], [])
        rows = self.client.get(f"{API}/products/suggest?q=Sugar").json()["data"]
        self.assertEqual([row["it_id"] for row in rows], ["SUG-1"])
        self.assertEqual(rows[0]["it_price"], 100)

    def test_the_suggestion_limit_is_clamped(self):
        for index in range(25):
            self.make_product(f"LIM-{index:02d}", f"Limit item {index}", it_price=1, it_stock_qty=1)
        self.assertEqual(len(self.client.get(f"{API}/products/suggest?q=Limit&limit=500").json()["data"]), 20)
        self.assertEqual(len(self.client.get(f"{API}/products/suggest?q=Limit&limit=0").json()["data"]), 1)
        self.assertEqual(len(self.client.get(f"{API}/products/suggest?q=Limit&limit=abc").json()["data"]), 10)

    def test_recommend_needs_a_member_and_an_existing_product(self):
        self.assertEqual(APIClient().post(f"{API}/products/MO001/recommend").status_code, 401)
        self.assertEqual(self.client.post(f"{API}/products/NOPE/recommend").status_code, 404)
        # an empty form is refused; the mail itself is covered in test_shop_mails
        self.assertEqual(self.client.post(f"{API}/products/MO001/recommend").status_code, 422)


class StockNotifyTests(CatalogBase):
    def setUp(self):
        super().setUp()
        self.sold = self.make_product("SMS-1", "Sold out", it_price=1000, it_stock_qty=0, it_soldout="1", it_stock_sms="1")

    def notify(self, it_id="SMS-1", **body):
        return APIClient().post(f"{API}/products/{it_id}/stock-notify", {"agree": True, "hp": "010-1234-5678", **body}, format="json")

    def test_a_consenting_customer_is_registered_once(self):
        first = self.notify()
        again = self.notify(hp="01012345678")
        self.assertEqual(first.status_code, 201, first.content[:300])
        self.assertEqual(again.status_code, 409)
        self.assertEqual(self.error_code(again), "already_subscribed")
        self.assertEqual(ShopStockNotification.objects.filter(it_id="SMS-1").count(), 1)

    def test_consent_is_required(self):
        for agree in (None, False, "no", "", "0"):
            response = self.notify(agree=agree)
            self.assertEqual(response.status_code, 422, repr(agree))
        self.assertEqual(ShopStockNotification.objects.count(), 0)
        self.assertEqual(self.notify(agree="yes").status_code, 201)

    def test_only_korean_mobile_numbers_are_accepted(self):
        for hp in ("", "123", "02-123-4567", "010-12", "abc", "011234567890123", None):
            self.assertEqual(self.notify(hp=hp).status_code, 422, repr(hp))
        self.assertEqual(ShopStockNotification.objects.count(), 0)

    def test_a_product_in_stock_or_without_the_notice_enabled_is_refused(self):
        self.make_product("SMS-2", "In stock", it_price=1000, it_stock_qty=4, it_stock_sms="1")
        self.make_product("SMS-3", "Notice off", it_price=1000, it_stock_qty=0, it_soldout="1")
        self.assertEqual(self.error_code(self.notify("SMS-2")), "stock_available")
        self.assertEqual(self.error_code(self.notify("SMS-3")), "stock_notification_disabled")
        self.assertEqual(self.notify("NOPE").status_code, 404)

    def test_the_phone_number_is_not_echoed_back(self):
        response = self.notify()
        self.assertNotIn("1234", response.content.decode())


class BannerAndMiscTests(ShopOrderBase):
    def banner(self, **fields):
        values = {"bn_alt": "Banner", "bn_url": "/shop/sale", "image_url": "/data/banner/1.jpg"}
        values.update(fields)
        return ShopBanner.objects.create(**values)

    def test_banners_respect_position_device_and_the_active_window(self):
        now = timezone.now()
        shown = self.banner(bn_alt="Shown", bn_device="both")
        self.banner(bn_alt="Pc only", bn_device="pc")
        self.banner(bn_alt="Mobile only", bn_device="mobile")
        self.banner(bn_alt="Off", is_active=False)
        self.banner(bn_alt="Later", begin_at=now + timedelta(days=1))
        self.banner(bn_alt="Over", end_at=now - timedelta(days=1))
        self.banner(bn_alt="Elsewhere", bn_position="Side")
        alts = lambda query: sorted(row["bn_alt"] for row in APIClient().get(f"{API}/banners{query}").json()["data"])
        self.assertEqual(alts(""), ["Mobile only", "Pc only", "Shown"])
        self.assertEqual(alts("?device=mobile"), ["Mobile only", "Shown"])
        self.assertEqual(alts("?device=desktop"), ["Pc only", "Shown"])
        self.assertEqual(alts("?device=tablet"), ["Mobile only", "Pc only", "Shown"])
        self.assertEqual(alts("?position=Side"), ["Elsewhere"])
        row = APIClient().get(f"{API}/banners").json()["data"][0]
        self.assertTrue(row["image_url"].startswith("http"))
        self.assertEqual(row["hit_url"], f"/shop/bannerhit.php?bn_id={shown.bn_id}" if row["bn_id"] == shown.bn_id else row["hit_url"])

    def test_a_banner_click_is_counted_only_when_asked_and_inactive_ones_are_hidden(self):
        banner = self.banner()
        off = self.banner(is_active=False)
        anonymous = APIClient()
        self.assertEqual(anonymous.get(f"{API}/banners/{banner.bn_id}/hit").json()["data"]["redirect_url"], "/shop/sale")
        banner.refresh_from_db()
        self.assertEqual(banner.hit_count, 0)
        anonymous.get(f"{API}/banners/{banner.bn_id}/hit?count=1")
        banner.refresh_from_db()
        self.assertEqual(banner.hit_count, 1)
        self.assertEqual(anonymous.get(f"{API}/banners/{off.bn_id}/hit?count=1").status_code, 404)
        self.assertEqual(anonymous.get(f"{API}/banners/99999/hit").status_code, 404)

    def test_popups_policy_and_point_summary(self):
        self.assertEqual(APIClient().get(f"{API}/popups").json()["data"], [])
        policy = APIClient().get(f"{API}/policy").json()["data"]
        self.assertEqual((policy["free_threshold"], policy["settle_point_unit"]), (50000, 100))
        self.set_points(1234)
        self.assertEqual(self.client.get(f"{API}/points/summary").json()["data"], {"balance": 1234, "usable": 1234})
        self.assertEqual(APIClient().get(f"{API}/points/summary").json()["data"]["balance"], 0)

    def test_the_order_form_data_is_kept_in_the_session(self):
        response = self.guest.post(f"{API}/orders/legacy-data", {"od_name": "Kim", "od_memo": "door"}, format="json")
        self.assertTrue(response.json()["data"]["saved"])
        self.assertEqual(self.guest.session["g5_shop_order_data"]["od_name"], "Kim")

    def test_the_naverpay_stubs_report_that_it_is_off(self):
        self.assertFalse(APIClient().get(f"{API}/naverpay").json()["data"]["enabled"])
        self.assertEqual(APIClient().post(f"{API}/naverpay/order", {}, format="json").json()["data"]["order_id"], "")
        many = APIClient().post(f"{API}/naverpay/wish", {"it_ids": ["A", "B"]}, format="json").json()["data"]
        one = APIClient().post(f"{API}/naverpay/wish", {"it_id": "A"}, format="json").json()["data"]
        none = APIClient().post(f"{API}/naverpay/wish", {}, format="json").json()["data"]
        self.assertEqual((many["item_ids"], one["item_ids"], none["item_ids"]), (["A", "B"], ["A"], []))

    def test_product_image_upload_is_for_staff_and_needs_a_known_product_and_a_file(self):
        self.assertEqual(self.client.post(f"{API}/products/MO001/images", {}, format="multipart").status_code, 403)
        self.assertEqual(self.staff_client.post(f"{API}/products/NOPE/images", {}, format="multipart").status_code, 404)
        response = self.staff_client.post(f"{API}/products/MO001/images", {}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.error_code(response), "image_required")


class CategoryAndEventTests(CatalogBase):
    def setUp(self):
        super().setUp()
        self.parent = ShopCategory.objects.create(ca_id="50", ca_name="Parent", ca_order=1)
        self.child = ShopCategory.objects.create(ca_id="5010", ca_name="Child", ca_parent="50")
        self.off = ShopCategory.objects.create(ca_id="60", ca_name="Off", ca_use=False)
        self.in_parent = self.make_product("CAT-P", "In parent", category=self.parent, it_price=100, it_stock_qty=1)
        self.in_child = self.make_product("CAT-C", "In child", category=self.child, it_price=200, it_stock_qty=1)
        self.unsold = self.make_product("CAT-U", "Unsold in parent", category=self.parent, it_price=300, it_stock_qty=1, it_use="0")

    def test_the_tree_lists_root_categories_with_their_children(self):
        rows = APIClient().get(f"{API}/categories").json()["data"]
        ids = [row["ca_id"] for row in rows]
        self.assertIn("50", ids)
        self.assertNotIn("5010", ids)
        self.assertNotIn("60", ids)
        parent = next(row for row in rows if row["ca_id"] == "50")
        self.assertEqual([child["ca_id"] for child in parent["children"]], ["5010"])

    def test_a_category_counts_on_sale_products_in_its_category_tree(self):
        # The count includes visible descendants but excludes the unsold parent product.
        rows = APIClient().get(f"{API}/categories").json()["data"]
        self.assertEqual(next(row for row in rows if row["ca_id"] == "50")["item_count"], 2)

    def test_a_category_page_lists_its_sold_products_and_subcategories(self):
        data = APIClient().get(f"{API}/categories/50?sort=price_desc").json()["data"]
        self.assertEqual([row["it_id"] for row in data["items"]], ["CAT-C", "CAT-P"])
        self.assertEqual([row["ca_id"] for row in data["subcategories"]], ["5010"])
        self.assertEqual(data["category"]["ca_name"], "Parent")

    def test_a_hidden_or_unknown_category_page_is_not_found(self):
        self.assertEqual(APIClient().get(f"{API}/categories/60").status_code, 404)
        self.assertEqual(APIClient().get(f"{API}/categories/nope").status_code, 404)

    def test_an_event_lists_its_sold_products_and_unused_events_are_hidden(self):
        event = ShopEvent.objects.create(ev_subject="Spring sale", ev_use=True, ev_subject_strong=True)
        hidden = ShopEvent.objects.create(ev_subject="Draft", ev_use=False)
        ShopEventItem.objects.create(event=event, product=self.in_parent, it_id="CAT-P")
        ShopEventItem.objects.create(event=event, product=self.unsold, it_id="CAT-U")
        ShopEventItem.objects.create(event=hidden, product=self.in_child, it_id="CAT-C")
        listing = APIClient().get(f"{API}/events").json()["data"]
        self.assertEqual([(row["ev_subject"], row["item_count"], row["ev_subject_strong"]) for row in listing], [("Spring sale", 1, 1)])
        detail = APIClient().get(f"{API}/events/{event.ev_id}?sort=price_asc").json()["data"]
        self.assertEqual([row["it_id"] for row in detail["products"]], ["CAT-P"])
        self.assertEqual(detail["ev_head_image_url"], "")
        self.assertEqual(APIClient().get(f"{API}/events/{hidden.ev_id}").status_code, 404)
        self.assertEqual(APIClient().get(f"{API}/events/99999").status_code, 404)
        self.assertEqual(APIClient().get(f"{API}/events/abc").status_code, 404)

    def test_the_smoke_event_stands_in_when_no_event_exists(self):
        smoke = {"event_id": 777, "product_id": "CAT-P", "ev_subject": "Smoke", "ev_subject_strong": True}
        Config.objects.update_or_create(name="nextjs_smoke_event", defaults={"value": json.dumps(smoke)})
        listing = APIClient().get(f"{API}/events").json()["data"]
        self.assertEqual([(row["ev_id"], row["item_count"]) for row in listing], [(777, 1)])
        detail = APIClient().get(f"{API}/events/777").json()["data"]
        self.assertEqual((detail["ev_subject"], [row["it_id"] for row in detail["products"]]), ("Smoke", ["CAT-P"]))
        self.assertEqual(APIClient().get(f"{API}/events/778").status_code, 404)

    def test_a_non_object_smoke_event_setting_is_ignored(self):
        Config.objects.update_or_create(name="nextjs_smoke_event", defaults={"value": json.dumps(["invalid"])})

        listing = APIClient().get(f"{API}/events")
        detail = APIClient().get(f"{API}/events/777")

        self.assertEqual(listing.status_code, 200, listing.content[:300])
        self.assertEqual(listing.json()["data"], [])
        self.assertEqual(detail.status_code, 404)


class PersonalPayTests(ShopOrderBase):
    def make_pay(self, pp_id="PP-1", **fields):
        values = {"pp_name": "Customer", "pp_price": 5000, "user": self.member}
        values.update(fields)
        return ShopPersonalPay.objects.create(pp_id=pp_id, **values)

    def test_the_owner_sees_a_payable_request(self):
        self.make_pay()
        data = self.client.get(f"{API}/personalpay/PP-1").json()["data"]
        self.assertEqual((data["payment_state"], data["can_pay"], data["pp_misu_price"]), ("ready", True, 5000))

    def test_someone_elses_request_is_forbidden_but_staff_may_look(self):
        self.make_pay()
        self.assertEqual(self.other_client.get(f"{API}/personalpay/PP-1").status_code, 403)
        self.assertEqual(APIClient().get(f"{API}/personalpay/PP-1").status_code, 403)
        self.assertEqual(self.staff_client.get(f"{API}/personalpay/PP-1").status_code, 200)

    def test_unknown_and_inactive_requests_are_not_found(self):
        self.make_pay(active=False)
        self.assertEqual(self.client.get(f"{API}/personalpay/PP-1").status_code, 404)
        self.assertEqual(self.client.get(f"{API}/personalpay/NOPE").status_code, 404)
        self.assertEqual(self.client.post(f"{API}/personalpay/PP-1/start").status_code, 404)

    def test_a_request_without_an_owner_is_open_to_whoever_has_its_id(self):
        self.make_pay(user=None)
        self.assertEqual(APIClient().get(f"{API}/personalpay/PP-1").status_code, 200)
        self.assertEqual(APIClient().post(f"{API}/personalpay/PP-1/start").status_code, 200)

    def test_start_hands_over_the_payment_path_for_a_payable_request(self):
        self.make_pay()
        data = self.client.post(f"{API}/personalpay/PP-1/start").json()["data"]
        self.assertTrue(data["can_pay"])
        self.assertIn("pp_id=PP-1", data["payment_url"])

    def test_nobody_else_can_start_the_payment(self):
        self.make_pay()
        self.assertEqual(self.other_client.post(f"{API}/personalpay/PP-1/start").status_code, 403)
        self.assertEqual(APIClient().post(f"{API}/personalpay/PP-1/start").status_code, 403)

    def test_an_already_paid_request_cannot_be_paid_again(self):
        self.make_pay(pp_receipt_price=5000, pp_tno="TNO1")
        detail = self.client.get(f"{API}/personalpay/PP-1").json()["data"]
        self.assertEqual((detail["payment_state"], detail["already_paid"], detail["pp_misu_price"]), ("paid", True, 0))
        self.assertIn("TNO1", detail["receipt_url"])
        response = self.client.post(f"{API}/personalpay/PP-1/start")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.error_code(response), "personalpay_not_payable")

    def test_a_request_with_a_payment_in_progress_cannot_be_started_again(self):
        self.make_pay(pp_tno="TNO2")
        detail = self.client.get(f"{API}/personalpay/PP-1").json()["data"]
        self.assertEqual((detail["payment_state"], detail["payment_in_progress"], detail["can_pay"]), ("processing", True, False))
        self.assertEqual(self.client.post(f"{API}/personalpay/PP-1/start").status_code, 409)

    def test_a_request_without_an_amount_cannot_be_paid(self):
        # DEFECT v1_shop.py:410 personalpay_payload: with pp_price <= 0 the request is neither
        # "paid" nor "processing", so it reads as "ready", can_pay is True and /start hands out
        # the payment path for a 0 (or negative) amount. YoungCart personalpayform.php only loads
        # a request with `pp_price > 0` ("개인결제 정보가 존재하지 않습니다.").
        for index, price in enumerate((0, -3000)):
            self.make_pay(pp_id=f"PP-Z{index}", pp_price=price)
            self.assertNotEqual(self.client.post(f"{API}/personalpay/PP-Z{index}/start").status_code, 200, price)

    def test_the_list_hides_paid_in_progress_inactive_and_free_requests(self):
        self.make_pay("PP-OK")
        self.make_pay("PP-PAID", pp_receipt_price=5000)
        self.make_pay("PP-BUSY", pp_app_no="APP1")
        self.make_pay("PP-OFF", active=False)
        self.make_pay("PP-ZERO", pp_price=0)
        rows = self.client.get(f"{API}/personalpay").json()["data"]
        self.assertEqual([row["pp_id"] for row in rows], ["PP-OK"])
        self.assertEqual(self.client.get(f"{API}/personalpay?per_page=100000").json()["meta"]["per_page"], 100)

    def test_a_cash_receipt_link_appears_only_with_an_issued_receipt(self):
        self.make_pay(pp_receipt_price=5000, pp_tno="T", pp_cash=1, pp_cash_no="CASH9")
        data = self.client.get(f"{API}/personalpay/PP-1").json()["data"]
        self.assertTrue(data["cash_receipt_url"].endswith("CASH9"))
        self.make_pay("PP-2")
        self.assertEqual(self.client.get(f"{API}/personalpay/PP-2").json()["data"]["cash_receipt_url"], "")


class OrderBadInputTests(OrderDirectCreateMixin, ShopOrderBase):
    def test_malformed_bodies_are_answered_with_a_client_error_not_a_crash(self):
        self.add(self.client)
        for body in ("[]", "null", '"text"', "12", "{not json"):
            response = self.client.post(f"{API}/orders", body, content_type="application/json")
            self.assertLess(response.status_code, 500, body)
        self.assertEqual(ShopOrder.objects.count(), 0)

    def test_odd_typed_fields_do_not_crash_order_creation(self):
        self.add(self.client)
        response = self.place(
            ct_ids={"a": 1}, od_zip=["1", "2"], od_b_zip={"x": 1}, od_name=12345, od_memo=["a"],
            cp_id=[1], cp_id_send={"a": 1}, point_use=10 ** 30,
        )
        self.assertLess(response.status_code, 500, response.content[:300])

    def test_an_oversized_name_is_refused_or_cut_to_the_column_size(self):
        # DEFECT v1_shop.py:758 create_order_from_request copies free text into bounded columns
        # (od_name is 100 characters) without validating it. PostgreSQL then fails the insert with
        # a server error (after the stock was touched, inside the rolled back transaction); other
        # databases silently keep an over-long value. Input must be validated at the boundary.
        self.add(self.client)
        try:
            response = self.place(od_name="N" * 300)
        except Exception as exc:  # the test client re-raises a server error
            self.fail(f"server error: {exc!r}")
        if response.status_code == 201:
            self.assertLessEqual(len(ShopOrder.objects.get().od_name), 100)
        else:
            self.assertLess(response.status_code, 500)

    def test_points_are_returned_on_cancel_even_after_points_were_switched_off(self):
        self.set_points(50000)
        order = self.order_of(point_use=5000)
        Config.objects.update_or_create(name="cf_use_point", defaults={"value": "0"})
        self.client.patch(f"{API}/orders/{order.od_id}", {}, format="json")
        self.reload(self.profile)
        self.assertEqual(self.profile.user_point, 50000)

    def test_payment_links_show_for_toss_and_shipped_orders(self):
        order = self.make_order("주문", user=self.member, od_id="MORE-LINK", od_tno="PAYKEY1", od_pg="toss", od_delivery_company="CJ대한통운", od_invoice="INV123", od_cash_no="C77")
        data = self.client.get(f"{API}/orders/{order.od_id}").json()["data"]
        self.assertIn("PAYKEY1", data["receipt_url"])
        self.assertIn("INV123", data["delivery_inquiry_url"])
        self.assertEqual(data["od_cash"], 1)

    def test_an_old_bank_order_without_a_stored_account_shows_the_current_one(self):
        order = self.make_order("주문", user=self.member, od_id="MORE-OLD", od_bank_account="")
        data = self.client.get(f"{API}/orders/{order.od_id}").json()["data"]
        self.assertEqual(data["od_bank_account"], BANK)

    def test_a_cancel_brings_back_only_cart_rows_that_are_not_already_there(self):
        from gnu_jango.shop.models import ShopOrderData

        order = self.order_of()
        snapshot = ShopOrderData.objects.get(order=order)
        rows = json.loads(snapshot.dt_data)
        snapshot.dt_data = json.dumps(["junk", 5, None, *rows, rows[0]])
        snapshot.save(update_fields=["dt_data"])
        self.add(self.client)
        before = len(self.client.get(f"{API}/cart").json()["data"]["items"])
        response = self.client.post(f"{API}/payment/cancel", {"order_id": order.od_id}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"]["restored_rows"], 1)
        self.assertEqual(len(self.client.get(f"{API}/cart").json()["data"]["items"]), before + 1)

    def test_an_unreadable_cart_snapshot_does_not_block_the_cancel(self):
        from gnu_jango.shop.models import ShopOrderData

        for index, text in enumerate(("{broken", '{"a": 1}')):
            order = self.order_of()
            ShopOrderData.objects.filter(order=order).update(dt_data=text)
            response = self.client.post(f"{API}/payment/cancel", {"order_id": order.od_id}, format="json")
            self.assertEqual(response.status_code, 200, index)
            self.assertEqual(response.json()["data"]["restored_rows"], 0)


class GuestOrderLookupThrottleTests(ShopOrderBase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)

    def test_guessing_a_guest_order_password_is_rate_limited(self):
        client = APIClient()
        statuses = [
            client.post(f"{API}/orders/lookup", {"od_id": "20260101000000000000", "od_pwd": f"guess{n}"}, format="json").status_code
            for n in range(11)
        ]

        self.assertNotIn(429, statuses[:10])
        self.assertEqual(statuses[10], 429)
