"""YoungCart money rules and product counters of the shop.

- product coupons judged on the product's total over all its lines, and refused (not shrunk) when
  worth more than it (shop/orderformupdate.php, orderitemcoupon.php, orderform.sub.php)
- the shipping coupon minimum compared with the order amount after the other coupons
- the shared shipping fee only for 금액별차등 (lib/shop.lib.php get_sendcost)
- migrated orders count their product coupons once
- it_use_cnt / it_use_avg (update_use_cnt / update_use_avg) and it_sum_qty kept from the source rows
- the sales rank: supplement lines at io_price, cancelled lines out of the sales
"""

import io
import json
from datetime import timedelta
from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api.v1_shop import order_payload
from gnu_jango.config.models import Config
from gnu_jango.core.management.commands.migrate_gnuboard5 import Command as ImportCommand
from gnu_jango.shop.admin._common import order_line_sales_expression
from gnu_jango.shop.admin_settings import ShopSettingsForm
from gnu_jango.shop.models import (
    ShopCategory,
    ShopCoupon,
    ShopCouponLog,
    ShopOrder,
    ShopOrderData,
    ShopOrderItem,
    ShopProduct,
    ShopReview,
    ShopShippingPolicy,
)
from gnu_jango.shop.order_coupons import order_coupon_totals
from gnu_jango.shop.order_flow import order_misu
from gnu_jango.shop.product_counters import recount_product_reviews, recount_product_sales
from gnu_jango.shop.shipping import (
    base_shipping_cost,
    current_shipping_policy,
    shipping_free_threshold,
    shipping_policy_payload,
)

API = "/api/v1/shop"
BANK = "Test Bank 000-00 Holder"
RED = {"io_id": "Red", "io_type": 0, "io_price": 2000, "io_stock_qty": 50, "io_use": 1}
BLUE = {"io_id": "Blue", "io_type": 0, "io_price": 0, "io_stock_qty": 50, "io_use": 1}
WRAP = {"io_id": "Wrap", "io_type": 1, "io_price": 5000, "io_stock_qty": 50, "io_use": 1}
TIERED_3000_UNDER_50000 = {"de_send_cost_case": "차등", "de_send_cost_limit": "50000", "de_send_cost_list": "3000"}


def today():
    return timezone.localdate()


class CheckoutBase(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.member = user_model.objects.create_user(username="money-member", email="money@example.test", password="pw")
        self.category = ShopCategory.objects.create(ca_id="50", ca_name="Money")
        self.shirt = ShopProduct.objects.create(
            it_id="SHIRT", category=self.category, it_name="Shirt", it_price=20000, it_stock_qty=50, it_use="1",
            it_option_subject="Color", options=[RED, BLUE, WRAP],
        )
        self.small = ShopProduct.objects.create(
            it_id="SMALL", category=self.category, it_name="Small", it_price=10000, it_stock_qty=50, it_use="1"
        )
        ShopShippingPolicy.objects.update_or_create(pk=1, defaults={**TIERED_3000_UNDER_50000, "de_delivery_company": "Courier"})
        Config.objects.update_or_create(name="de_bank_use", defaults={"value": "1"})
        Config.objects.update_or_create(name="de_bank_account", defaults={"value": BANK})
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def coupon(self, **extra):
        values = {
            "user": self.member, "cp_subject": "Coupon", "cp_method": 0, "cp_target": "SHIRT", "cp_type": 0,
            "cp_price": 3000, "cp_minimum": 0, "cp_start": today() - timedelta(days=1), "cp_end": today() + timedelta(days=1),
        }
        values.update(extra)
        return ShopCoupon.objects.create(**values)

    def add_options(self, product, *options):
        response = self.client.post(f"{API}/cart", {"it_id": product.it_id, "options": list(options)}, format="json")
        self.assertIn(response.status_code, (200, 201), response.content[:300])
        return [row["ct_id"] for row in response.json()["data"]["items_created"]]

    def add(self, product, qty=1):
        response = self.client.post(f"{API}/cart", {"it_id": product.it_id, "ct_qty": qty}, format="json")
        self.assertIn(response.status_code, (200, 201), response.content[:300])
        return response.json()["data"]["ct_id"]

    def apply(self, ct_id, cp_id):
        return self.client.post(f"{API}/coupons/apply-to-cart", {"ct_id": ct_id, "cp_id": cp_id}, format="json")

    def cart(self):
        return self.client.get(f"{API}/cart").json()["data"]

    def place(self, **fields):
        base = {
            "od_name": "Member", "od_tel": "010-1111-2222", "od_hp": "010-1111-2222", "od_email": "money@example.test",
            "od_zip": "06236", "od_addr1": "Seoul", "od_addr2": "1", "od_b_name": "Member", "od_b_tel": "010-1111-2222",
            "od_b_hp": "010-1111-2222", "od_b_zip": "06236", "od_b_addr1": "Seoul", "od_b_addr2": "1",
            "od_settle_case": "bank", "od_bank_account": BANK, "od_deposit_name": "Member",
        }
        return self.client.post(f"{API}/orders", {**base, **fields}, format="json")

    def placed(self, **fields):
        response = self.place(**fields)
        self.assertEqual(response.status_code, 201, response.content[:400])
        return ShopOrder.objects.get(pk=response.json()["data"]["od_id"])

    def used(self, coupon):
        coupon.refresh_from_db()
        return coupon.cp_used


class ProductLevelItemCouponTests(CheckoutBase):
    """orderformupdate.php: SUM(IF(io_type = 1, io_price * ct_qty, (ct_price + io_price) * ct_qty)) of
    the product's lines is the base of its one coupon."""

    def test_the_minimum_is_met_by_all_the_lines_of_the_product(self):
        red, wrap = self.add_options(self.shirt, {"io_id": "Red"}, {"io_id": "Wrap", "io_type": 1})
        # Red 20,000 + 2,000; the supplement line is its own 5,000 (not 20,000 + 5,000)
        coupon = self.coupon(cp_minimum=25000)
        response = self.apply(red, coupon.cp_id)
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"]["discount"], 3000)

        order = self.placed()
        self.assertEqual(order.coupon_logs.get().cp_price, 3000)
        self.assertEqual(order.od_cart_price, 27000)
        self.assertEqual(order_payload(order)["od_cart_coupon"], 3000)
        self.assertEqual(order.od_misu, 27000 + 3000 - 3000)

    def test_a_percent_coupon_takes_its_share_of_every_line_of_the_product(self):
        red, blue = self.add_options(self.shirt, {"io_id": "Red"}, {"io_id": "Blue"})
        coupon = self.coupon(cp_type=1, cp_price=10)
        self.assertEqual(self.apply(blue, coupon.cp_id).json()["data"]["discount"], 4200)  # 10% of 42,000

        order = self.placed()
        self.assertEqual(order.coupon_logs.get().cp_price, 4200)
        self.assertEqual(order.od_misu, 42000 - 4200 + 3000)

    def test_the_discount_is_stored_once_on_the_first_line_of_the_product(self):
        red, blue = self.add_options(self.shirt, {"io_id": "Red"}, {"io_id": "Blue"})
        coupon = self.coupon(cp_price=3000)
        self.apply(blue, coupon.cp_id)
        order = self.placed()
        snapshot = json.loads(ShopOrderData.objects.get(order=order).dt_data)
        self.assertEqual([(row["ct_id"], row["cp_price"]) for row in snapshot], [(red, 3000), (blue, 0)])
        self.assertEqual(sum(log.cp_price for log in order.coupon_logs.all()), 3000)

    def test_a_coupon_put_on_another_line_of_the_product_replaces_the_first(self):
        red, blue = self.add_options(self.shirt, {"io_id": "Red"}, {"io_id": "Blue"})
        first = self.coupon(cp_price=1000)
        second = self.coupon(cp_price=2000)
        self.apply(red, first.cp_id)
        self.apply(blue, second.cp_id)
        lines = {line["ct_id"]: (line["cp_id"], line["cp_price"]) for line in self.cart()["items"]}
        self.assertEqual(lines, {red: ("", 0), blue: (second.cp_id, 2000)})
        self.assertEqual(self.cart()["cart_coupon"], 2000)

    def test_a_fixed_coupon_worth_more_than_the_product_is_refused_on_the_cart(self):
        ct_id = self.add(self.small)
        coupon = self.coupon(cp_target="SMALL", cp_price=15000)
        response = self.apply(ct_id, coupon.cp_id)
        self.assertEqual((response.status_code, response.json()["code"]), (400, "coupon_exceeds_item_price"))
        self.assertEqual(self.cart()["items"][0]["cp_id"], "")

    def test_a_coupon_below_the_product_minimum_is_refused_on_the_cart(self):
        ct_id = self.add(self.small)
        coupon = self.coupon(cp_target="SMALL", cp_minimum=20000)
        response = self.apply(ct_id, coupon.cp_id)
        self.assertEqual((response.status_code, response.json()["code"]), (400, "coupon_minimum_not_met"))

    def test_a_coupon_that_outgrew_the_product_after_the_cart_changed_is_dropped_at_checkout(self):
        ct_id = self.add(self.small, qty=2)
        coupon = self.coupon(cp_target="SMALL", cp_price=15000)
        self.assertEqual(self.apply(ct_id, coupon.cp_id).status_code, 200)
        # the cart now holds one unit (10,000): YoungCart skips the coupon ('continue'), not caps it
        response = self.client.patch(f"{API}/cart/{ct_id}", {"ct_qty": 1}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        order = self.placed()
        self.assertEqual(order.od_cart_price, 10000)
        self.assertFalse(order.coupon_logs.exists())
        self.assertEqual(self.used(coupon), "")
        self.assertEqual(order.od_misu, 10000 + 3000)

    def test_the_item_coupon_list_shows_the_discount_on_the_product_total(self):
        red, _blue = self.add_options(self.shirt, {"io_id": "Red"}, {"io_id": "Blue"})
        coupon = self.coupon(cp_type=1, cp_price=10)
        rows = self.client.get(f"{API}/coupons/applicable?ct_id={red}").json()["data"]
        self.assertEqual([(row["cp_id"], row["discount"]) for row in rows], [(coupon.cp_id, 4200)])


class OrderAndShippingCouponBaseTests(CheckoutBase):
    def test_an_order_coupon_worth_more_than_the_order_is_refused(self):
        self.add(self.small)
        coupon = self.coupon(cp_method=2, cp_target="", cp_price=12000)
        response = self.place(cp_id=coupon.cp_id)
        self.assertEqual((response.status_code, response.json()["code"]), (400, "order_coupon_exceeds_amount"))
        self.assertEqual(self.used(coupon), "")

    def test_the_order_coupon_is_judged_after_the_product_coupons(self):
        ct_id = self.add(self.small)
        self.apply(ct_id, self.coupon(cp_target="SMALL", cp_price=4000).cp_id)
        order_coupon = self.coupon(cp_method=2, cp_target="", cp_price=7000)
        # 10,000 - 4,000 = 6,000 left: a 7,000 order coupon is refused
        response = self.place(cp_id=order_coupon.cp_id)
        self.assertEqual(response.json()["code"], "order_coupon_exceeds_amount")

    def test_the_shipping_coupon_minimum_is_checked_after_the_order_coupon(self):
        self.add(self.small)
        order_coupon = self.coupon(cp_method=2, cp_target="", cp_price=3000)
        shipping_coupon = self.coupon(cp_method=3, cp_target="", cp_price=3000, cp_minimum=8000)
        order = self.placed(cp_id=order_coupon.cp_id, cp_id_send=shipping_coupon.cp_id)
        # tot_od_price = 10,000 - 3,000 = 7,000 < 8,000
        self.assertEqual((order.od_coupon, order.od_send_coupon), (3000, 0))
        self.assertEqual(self.used(shipping_coupon), "")

    def test_the_shipping_coupon_minimum_is_checked_after_the_product_coupon(self):
        ct_id = self.add(self.small)
        self.apply(ct_id, self.coupon(cp_target="SMALL", cp_price=2500).cp_id)
        shipping_coupon = self.coupon(cp_method=3, cp_target="", cp_price=3000, cp_minimum=8000)
        self.assertEqual(self.placed(cp_id_send=shipping_coupon.cp_id).od_send_coupon, 0)

    def test_the_shipping_coupon_applies_when_the_amount_after_coupons_reaches_its_minimum(self):
        self.add(self.small)
        order_coupon = self.coupon(cp_method=2, cp_target="", cp_price=2000)
        shipping_coupon = self.coupon(cp_method=3, cp_target="", cp_price=3000, cp_minimum=8000)
        order = self.placed(cp_id=order_coupon.cp_id, cp_id_send=shipping_coupon.cp_id)
        self.assertEqual((order.od_coupon, order.od_send_coupon), (2000, 3000))


class ShippingFallbackTests(TestCase):
    """get_sendcost: a shared fee only under 금액별차등 with tiers; otherwise 0."""

    def policy(self, **fields):
        policy, _ = ShopShippingPolicy.objects.update_or_create(pk=1, defaults=fields)
        return policy

    def test_an_empty_case_charges_no_shared_fee(self):
        policy = self.policy(de_send_cost_case="")
        self.assertEqual((base_shipping_cost(10000, policy), shipping_free_threshold(policy)), (0, 0))

    def test_tiers_left_behind_by_another_case_are_not_used(self):
        policy = self.policy(de_send_cost_case="", de_send_cost_limit="50000", de_send_cost_list="3000")
        self.assertEqual(base_shipping_cost(10000, policy), 0)
        self.assertEqual(shipping_policy_payload(policy)["shipping_rules"], [])

    def test_tiered_without_tiers_charges_nothing(self):
        policy = self.policy(de_send_cost_case="차등", de_send_cost_limit="", de_send_cost_list="")
        self.assertEqual(base_shipping_cost(1000, policy), 0)

    def test_free_charges_nothing(self):
        self.assertEqual(base_shipping_cost(1000, self.policy(de_send_cost_case="무료")), 0)

    def test_tiered_charges_the_first_tier_the_amount_is_under(self):
        policy = self.policy(de_send_cost_case="차등", de_send_cost_limit="20000;30000", de_send_cost_list="4000;2500")
        self.assertEqual([base_shipping_cost(amount, policy) for amount in (19999, 20000, 29999, 30000)], [4000, 2500, 2500, 0])
        self.assertEqual(shipping_free_threshold(policy), 30000)

    def test_a_shop_that_never_saved_its_settings_uses_the_youngcart_install_tiers(self):
        policy = current_shipping_policy()
        self.assertIsNone(ShopShippingPolicy.objects.filter(pk=1).first())
        self.assertEqual((policy.de_send_cost_case, policy.de_send_cost_limit, policy.de_send_cost_list),
                         ("차등", "20000;30000;40000", "4000;3000;2000"))
        self.assertEqual([base_shipping_cost(amount) for amount in (10000, 25000, 35000, 40000)], [4000, 3000, 2000, 0])
        self.assertEqual(shipping_free_threshold(), 40000)

    def test_the_settings_form_names_the_empty_case_as_no_shared_fee(self):
        choices = dict(ShopSettingsForm(instance=current_shipping_policy()).fields["de_send_cost_case"].choices)
        self.assertEqual(choices[""], "배송비 없음 (공통 배송비 미부과)")


class MigratedOrderCouponTests(TestCase):
    """An imported order keeps od_coupon (order coupon) apart from od_cart_coupon (product coupons);
    the product coupons come from its coupon logs, so they are subtracted once."""

    def import_order(self, **row):
        command = ImportCommand()
        command.stdout = io.StringIO()
        source = {
            "od_id": "2026101100001", "mb_id": "", "od_name": "Buyer", "od_cart_price": "30000", "od_send_cost": "3000",
            "od_coupon": "2000", "od_cart_coupon": "1500", "od_send_coupon": "0", "od_receipt_price": "29500",
            "od_status": "완료", "od_settle_case": "무통장", "od_time": "2026-10-11 12:30:00",
        }
        source.update(row)
        command.import_shop_orders([source])
        return command, ShopOrder.objects.get(pk=source["od_id"])

    def log(self, command, cl_id, cp_id, cp_price):
        command.import_shop_coupon_logs([
            {"cl_id": cl_id, "cp_id": cp_id, "mb_id": "", "od_id": "2026101100001", "cp_price": cp_price, "cl_datetime": "2026-10-11 12:30:00"}
        ])

    def test_the_product_coupon_is_subtracted_once(self):
        command, order = self.import_order()
        ShopCoupon.objects.create(cp_id="ITEMCP", cp_subject="Item", cp_method=0, cp_target="X", cp_used="1")
        ShopCoupon.objects.create(cp_id="ORDERCP", cp_subject="Order", cp_method=2, cp_used="1")
        self.log(command, 1, "ITEMCP", "1500")
        self.log(command, 2, "ORDERCP", "2000")

        self.assertEqual(order.od_coupon, 2000)
        payload = order_payload(order)
        self.assertEqual((payload["od_cart_coupon"], payload["od_coupon"]), (1500, 2000))
        self.assertEqual(payload["od_total_price"], 30000 + 3000 - 1500 - 2000)
        self.assertEqual(order_misu(order), 0)

    def test_a_product_coupon_whose_coupon_row_is_gone_still_counts_once(self):
        command, order = self.import_order()
        ShopCoupon.objects.create(cp_id="ORDERCP", cp_subject="Order", cp_method=2, cp_used="1")
        self.log(command, 1, "DELETED-ITEM", "1500")
        self.log(command, 2, "ORDERCP", "2000")
        self.assertEqual(order_coupon_totals(order).cart, 1500)
        self.assertEqual(order_payload(order)["od_total_price"], 29500)

    def test_an_order_coupon_whose_coupon_row_is_gone_is_not_counted_twice(self):
        command, order = self.import_order(od_cart_coupon="0", od_receipt_price="31000")
        self.log(command, 1, "DELETED-ORDER", "2000")
        totals = order_coupon_totals(order)
        self.assertEqual((totals.cart, totals.order), (0, 2000))
        self.assertEqual(order_payload(order)["od_total_price"], 31000)


class ReviewCounterTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.member = user_model.objects.create_user(username="reviewer", email="reviewer@example.test", password="pw")
        self.admin_user = user_model.objects.create_superuser(username="review-admin", email="ra@example.test", password="pw")
        self.product = ShopProduct.objects.create(it_id="REV1", it_name="Reviewed", it_price=1000, it_use="1")
        self.other = ShopProduct.objects.create(it_id="REV2", it_name="Other", it_price=1000, it_use="1")
        ShopShippingPolicy.objects.update_or_create(pk=1, defaults={"de_item_use_use": 0, "de_item_use_write": 0})
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def write(self, score, it_id="REV1"):
        response = self.client.post(f"{API}/reviews", {"it_id": it_id, "is_score": score, "is_subject": "S", "is_content": "C"}, format="json")
        self.assertEqual(response.status_code, 201, response.content[:300])
        return response.json()["data"]["is_id"]

    def counters(self, product=None):
        product = product or self.product
        product.refresh_from_db()
        return product.it_use_cnt, product.it_use_avg

    def test_writing_editing_and_deleting_a_review_keeps_the_counters(self):
        first = self.write(5)
        self.write(4)
        self.assertEqual(self.counters(), (2, Decimal("4.5")))
        self.client.patch(f"{API}/reviews/{first}", {"is_score": 1}, format="json")
        self.assertEqual(self.counters(), (2, Decimal("2.5")))
        self.client.delete(f"{API}/reviews/{first}")
        self.assertEqual(self.counters(), (1, Decimal("4.0")))
        self.assertEqual(self.counters(self.other), (0, Decimal("0.0")))

    def test_a_review_waiting_for_approval_counts_once_the_admin_publishes_it(self):
        ShopShippingPolicy.objects.filter(pk=1).update(de_item_use_use=1)
        self.write(3)
        self.assertEqual(self.counters(), (0, Decimal("0.0")))

        review = ShopReview.objects.get()
        model_admin = admin.site._registry[ShopReview]
        request = RequestFactory().post("/")
        request.user = self.admin_user
        review.is_confirm = "1"
        model_admin.save_model(request, review, None, True)
        self.assertEqual(self.counters(), (1, Decimal("3.0")))

        review.is_confirm = "0"
        model_admin.save_model(request, review, None, True)
        self.assertEqual(self.counters(), (0, Decimal("0.0")))

    def test_deleting_reviews_in_the_admin_recounts_their_products(self):
        self.write(5)
        self.write(2, it_id="REV2")
        model_admin = admin.site._registry[ShopReview]
        request = RequestFactory().post("/")
        request.user = self.admin_user
        model_admin.delete_queryset(request, ShopReview.objects.all())
        self.assertEqual((self.counters(), self.counters(self.other)), ((0, Decimal("0.0")), (0, Decimal("0.0"))))

    def test_the_admin_change_form_publishing_a_review_recounts(self):
        review = ShopReview.objects.create(product=self.product, is_subject="S", is_score=4, is_confirm="0")
        self.client.force_login(self.admin_user)
        response = self.client.post(reverse("admin:shop_shopreview_change", args=[review.pk]), {"is_confirm": "1"})
        self.assertEqual(response.status_code, 302, response.content[:500])
        self.assertEqual(self.counters(), (1, Decimal("4.0")))

    def test_the_average_rounds_to_one_decimal_like_decimal_2_1(self):
        for score in (5, 4, 4):
            ShopReview.objects.create(product=self.product, is_subject="S", is_score=score, is_confirm="1")
        recount_product_reviews(["REV1"])
        self.assertEqual(self.counters(), (3, Decimal("4.3")))

    def test_the_backfill_command_fixes_every_product(self):
        ShopReview.objects.create(product=self.product, is_subject="S", is_score=2, is_confirm="1")
        ShopReview.objects.create(product=self.product, is_subject="S", is_score=5, is_confirm="0")
        ShopProduct.objects.filter(pk="REV2").update(it_use_cnt=9, it_use_avg=Decimal("5.0"))
        out = io.StringIO()
        call_command("recount_product_reviews", stdout=out)
        self.assertEqual((self.counters(), self.counters(self.other)), ((1, Decimal("2.0")), (0, Decimal("0.0"))))
        self.assertIn("products=2", out.getvalue())

    def test_sorting_by_reviews_and_rating_follows_the_counters(self):
        for _ in range(2):
            ShopReview.objects.create(product=self.other, is_subject="S", is_score=3, is_confirm="1")
        ShopReview.objects.create(product=self.product, is_subject="S", is_score=5, is_confirm="1")
        recount_product_reviews()
        by_reviews = [row["it_id"] for row in APIClient().get(f"{API}/products?sort=reviews").json()["data"]]
        by_rating = [row["it_id"] for row in APIClient().get(f"{API}/products?sort=rating").json()["data"]]
        self.assertEqual((by_reviews[:2], by_rating[:2]), (["REV2", "REV1"], ["REV1", "REV2"]))


class SalesCounterTests(TestCase):
    def setUp(self):
        self.product = ShopProduct.objects.create(it_id="SOLD1", it_name="Sold", it_price=1000, it_use="1", it_sum_qty=99)

    def line(self, od_id, status, qty, **extra):
        order = ShopOrder.objects.get_or_create(od_id=od_id, defaults={"od_name": "B", "od_status": status})[0]
        values = {"order": order, "product": self.product, "ct_id": f"{od_id}-{status}", "it_id": "SOLD1", "it_name": "Sold",
                  "ct_price": 1000, "ct_qty": qty, "ct_status": status}
        values.update(extra)
        return ShopOrderItem.objects.create(**values)

    def test_only_completed_lines_count_and_a_returned_line_drops_out(self):
        self.line("S1", "완료", 2)
        returned = self.line("S2", "완료", 3)
        self.line("S3", "취소", 4)
        self.line("S4", "배송", 5)
        recount_product_sales(["SOLD1"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_sum_qty, 5)

        ShopOrderItem.objects.filter(pk=returned.pk).update(ct_status="반품")
        recount_product_sales(["SOLD1"])
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_sum_qty, 2)

    def test_the_backfill_command_recounts_every_product(self):
        self.line("S1", "완료", 2)
        call_command("recount_product_sales", stdout=io.StringIO())
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_sum_qty, 2)


class SalesRankTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser(username="rank-admin", email="rank@example.test", password="pw")
        self.product = ShopProduct.objects.create(it_id="RANK1", it_name="Ranked", it_price=10000, it_use="1")
        self.order = ShopOrder.objects.create(od_id="R1", od_name="B", od_status="완료")
        self.cancelled = ShopOrder.objects.create(od_id="R2", od_name="B", od_status="취소")

    def line(self, order, ct_id, status, **extra):
        values = {"order": order, "product": self.product, "ct_id": ct_id, "it_id": "RANK1", "it_name": "Ranked",
                  "ct_price": 10000, "ct_qty": 1, "ct_status": status}
        values.update(extra)
        return ShopOrderItem.objects.create(**values)

    def test_a_supplement_line_sells_at_its_own_price(self):
        self.line(self.order, "1", "완료", ct_qty=2, io_price=1000)  # option line: (10,000 + 1,000) x 2
        self.line(self.order, "2", "완료", ct_qty=3, io_type=1, io_price=500)  # supplement: 500 x 3
        amounts = sorted(ShopOrderItem.objects.annotate(amount=order_line_sales_expression()).values_list("amount", flat=True))
        self.assertEqual(amounts, [1500, 22000])

    def test_cancelled_lines_are_left_out_of_the_sales_and_shown_per_status(self):
        self.line(self.order, "1", "완료", ct_qty=2)
        self.line(self.cancelled, "2", "취소", ct_qty=5)
        self.line(self.order, "3", "반품", ct_qty=1)
        model_admin = admin.site._registry[ShopOrder]
        rows = model_admin.product_sales_rank_rows(ShopOrderItem.objects.all())
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row["quantity"], row["gross_sales"], row["order_count"], row["line_count"]), ("2", "20,000", "1", "1"))
        # 주문 입금 준비 배송 완료 취소 반품 품절
        self.assertEqual(row["status_quantities"], ["0", "0", "0", "0", "2", "5", "1", "0"])

    def test_the_sales_rank_page_and_export_show_the_status_columns(self):
        self.line(self.order, "1", "완료", ct_qty=2)
        self.line(self.cancelled, "2", "취소", ct_qty=5)
        self.client.force_login(self.admin_user)
        page = self.client.get(reverse("admin:shop_shoporder_sales_rank"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "<th scope=\"col\">반품</th>", html=False)
        self.assertEqual(page.context["metrics"][2]["value"], "20,000")
        export = self.client.get(reverse("admin:shop_shoporder_sales_rank") + "?export=csv").content.decode("utf-8-sig")
        header, first = export.splitlines()[:2]
        self.assertIn("qty_취소", header)
        self.assertTrue(first.endswith(",0,0,0,0,2,5,0,0"), first)
