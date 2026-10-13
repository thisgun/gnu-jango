"""Paying part of an order with points follows the shop's point settings.

YoungCart lets a member use points only when the balance reaches the minimum, never
above the maximum or the order amount, and in multiples of the unit. Every use (and the
return on cancel) is written to the member's point history.
"""

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from gnu_jango.config.models import Config
from gnu_jango.shop.models import ShopCategory, ShopOrder, ShopProduct, ShopShippingPolicy
from gnu_jango.users.models import Profile, User_Point


class OrderTestBase(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.member = user_model.objects.create_user(username="point-member", email="point-member@example.test", password="password")
        self.profile, _ = Profile.objects.get_or_create(user=self.member)
        category = ShopCategory.objects.create(ca_id="30", ca_name="Point category")
        self.product = ShopProduct.objects.create(it_id="PT001", category=category, it_name="Point product", it_price=100000, it_stock_qty=50, it_use="1")
        ShopShippingPolicy.objects.update_or_create(
            pk=1,
            defaults={"de_delivery_company": "Courier", "de_settle_min_point": 5000, "de_settle_max_point": 50000, "de_settle_point_unit": 100},
        )
        Config.objects.update_or_create(name="de_bank_use", defaults={"value": "1"})
        Config.objects.update_or_create(name="de_bank_account", defaults={"value": "Test Bank 000-00 Holder"})
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def order(self, point_use, balance=80000):
        self.profile.user_point = balance
        self.profile.save(update_fields=["user_point"])
        self.client.post("/api/v1/shop/cart", {"it_id": self.product.it_id, "ct_qty": 1}, format="json")
        response = self.client.post(
            "/api/v1/shop/orders",
            {
                "od_name": "Point Member", "od_tel": "010-1111-2222", "od_hp": "010-1111-2222", "od_email": "point-member@example.test",
                "od_zip": "06236", "od_addr1": "Seoul", "od_addr2": "1",
                "od_b_name": "Point Member", "od_b_tel": "010-1111-2222", "od_b_hp": "010-1111-2222",
                "od_b_zip": "06236", "od_b_addr1": "Seoul", "od_b_addr2": "1",
                "od_settle_case": "bank", "od_bank_account": "Test Bank 000-00 Holder", "od_deposit_name": "Point Member",
                "point_use": point_use,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content[:400])
        order = ShopOrder.objects.get(pk=response.json()["data"]["od_id"])
        self.profile.refresh_from_db()
        return order


class OrderPointTests(OrderTestBase):
    def test_points_are_used_in_units_up_to_the_configured_maximum(self):
        order = self.order(point_use=60000)
        self.assertEqual(order.od_receipt_point, 50000)
        self.assertEqual(self.profile.user_point, 30000)

    def test_points_are_rounded_down_to_the_unit(self):
        order = self.order(point_use=12345)
        self.assertEqual(order.od_receipt_point, 12300)
        self.assertEqual(self.profile.user_point, 80000 - 12300)

    def test_balance_below_the_minimum_cannot_be_used(self):
        order = self.order(point_use=3000, balance=4000)
        self.assertEqual(order.od_receipt_point, 0)
        self.assertEqual(self.profile.user_point, 4000)

    def test_the_whole_balance_can_be_used_when_it_meets_the_minimum(self):
        order = self.order(point_use=5000, balance=5000)
        self.assertEqual(order.od_receipt_point, 5000)
        self.assertEqual(self.profile.user_point, 0)

    def test_using_points_writes_a_negative_history_row(self):
        order = self.order(point_use=20000)
        row = User_Point.objects.get(user=self.member, po_rel_table="@order", po_rel_action=order.od_id)
        self.assertEqual(row.po_point, -20000)
        self.assertEqual(row.po_mb_point, 60000)

    def test_no_history_row_when_no_points_are_used(self):
        self.order(point_use=0)
        self.assertFalse(User_Point.objects.filter(user=self.member, po_rel_table="@order").exists())

    def test_cancelling_the_order_returns_the_points_and_records_it(self):
        order = self.order(point_use=20000)
        response = self.client.post("/api/v1/shop/payment/cancel", {"order_id": order.od_id}, format="json")
        self.assertIn(response.status_code, (200, 201), response.content[:300])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.user_point, 80000)
        row = User_Point.objects.get(user=self.member, po_rel_table="@order-cancel", po_rel_action=order.od_id)
        self.assertEqual(row.po_point, 20000)
        self.assertEqual(row.po_mb_point, 80000)


class CouponOrderBase(OrderTestBase):
    """Helpers for orders that use coupons."""

    def make_coupon(self, **extra):
        from datetime import timedelta

        from django.utils import timezone

        values = {"user": self.member, "cp_subject": "Order coupon", "cp_method": 2, "cp_type": 0, "cp_price": 7000, "cp_minimum": 0, "cp_start": timezone.localdate() - timedelta(days=5), "cp_end": timezone.localdate() + timedelta(days=5)}
        values.update(extra)
        from gnu_jango.shop.models import ShopCoupon

        return ShopCoupon.objects.create(**values)

    def order_with(self, **fields):
        self.client.post("/api/v1/shop/cart", {"it_id": self.product.it_id, "ct_qty": 1}, format="json")
        base = {
            "od_name": "Point Member", "od_tel": "010-1111-2222", "od_hp": "010-1111-2222", "od_email": "point-member@example.test",
            "od_zip": "06236", "od_addr1": "Seoul", "od_addr2": "1",
            "od_b_name": "Point Member", "od_b_tel": "010-1111-2222", "od_b_hp": "010-1111-2222",
            "od_b_zip": "06236", "od_b_addr1": "Seoul", "od_b_addr2": "1",
            "od_settle_case": "bank", "od_bank_account": "Test Bank 000-00 Holder", "od_deposit_name": "Point Member",
        }
        response = self.client.post("/api/v1/shop/orders", {**base, **fields}, format="json")
        self.assertEqual(response.status_code, 201, response.content[:400])
        return ShopOrder.objects.get(pk=response.json()["data"]["od_id"])


class OrderCouponTests(CouponOrderBase):
    """Order and shipping coupons are applied only while valid, once, and come back on cancel."""

    def test_a_valid_order_coupon_discounts_the_order_and_is_used_up(self):
        coupon = self.make_coupon()
        order = self.order_with(cp_id=coupon.cp_id)
        coupon.refresh_from_db()
        self.assertEqual(order.od_coupon, 7000)
        self.assertEqual(coupon.cp_used, "1")

    def test_an_expired_order_coupon_is_ignored(self):
        from datetime import timedelta

        from django.utils import timezone

        coupon = self.make_coupon(cp_end=timezone.localdate() - timedelta(days=1))
        order = self.order_with(cp_id=coupon.cp_id)
        coupon.refresh_from_db()
        self.assertEqual(order.od_coupon, 0)
        self.assertEqual(coupon.cp_used, "")

    def test_a_coupon_that_is_not_yet_valid_is_ignored(self):
        from datetime import timedelta

        from django.utils import timezone

        coupon = self.make_coupon(cp_start=timezone.localdate() + timedelta(days=1))
        self.assertEqual(self.order_with(cp_id=coupon.cp_id).od_coupon, 0)

    def test_an_already_used_coupon_cannot_be_used_again(self):
        coupon = self.make_coupon(cp_used="1")
        self.assertEqual(self.order_with(cp_id=coupon.cp_id).od_coupon, 0)

    def test_another_members_coupon_is_ignored(self):
        other = get_user_model().objects.create_user(username="coupon-other", email="coupon-other@example.test", password="password")
        coupon = self.make_coupon(user=other)
        self.assertEqual(self.order_with(cp_id=coupon.cp_id).od_coupon, 0)

    def test_cancelling_the_order_makes_the_coupon_usable_again(self):
        coupon = self.make_coupon()
        order = self.order_with(cp_id=coupon.cp_id)
        response = self.client.post("/api/v1/shop/payment/cancel", {"order_id": order.od_id}, format="json")
        self.assertIn(response.status_code, (200, 201), response.content[:300])
        coupon.refresh_from_db()
        self.assertEqual(coupon.cp_used, "")


class OrderBenefitEdgeTests(CouponOrderBase):
    """Edges found in review: item coupons at order time, point cap base, refunds, races."""

    def put_in_cart_with_item_coupon(self, coupon):
        added = self.client.post("/api/v1/shop/cart", {"it_id": self.product.it_id, "ct_qty": 1}, format="json")
        self.assertIn(added.status_code, (200, 201), added.content[:300])
        cart = self.client.get("/api/v1/shop/cart").json()["data"]
        ct_id = cart["items"][0]["ct_id"]
        applied = self.client.post("/api/v1/shop/coupons/apply-to-cart", {"ct_id": ct_id, "cp_id": coupon.cp_id}, format="json")
        self.assertEqual(applied.status_code, 200, applied.content[:300])
        return ct_id

    def place(self, **fields):
        # same payload as order_with, without adding another cart row
        base = {
            "od_name": "Point Member", "od_tel": "010-1111-2222", "od_hp": "010-1111-2222", "od_email": "point-member@example.test",
            "od_zip": "06236", "od_addr1": "Seoul", "od_addr2": "1",
            "od_b_name": "Point Member", "od_b_tel": "010-1111-2222", "od_b_hp": "010-1111-2222",
            "od_b_zip": "06236", "od_b_addr1": "Seoul", "od_b_addr2": "1",
            "od_settle_case": "bank", "od_bank_account": "Test Bank 000-00 Holder", "od_deposit_name": "Point Member",
        }
        response = self.client.post("/api/v1/shop/orders", {**base, **fields}, format="json")
        return response

    def item_coupon(self, **extra):
        return self.make_coupon(cp_method=0, cp_target=self.product.it_id, cp_price=5000, **extra)

    def test_a_valid_item_coupon_discounts_the_order_and_is_used_up(self):
        coupon = self.item_coupon()
        self.put_in_cart_with_item_coupon(coupon)
        response = self.place()
        self.assertEqual(response.status_code, 201, response.content[:300])
        order = ShopOrder.objects.get(pk=response.json()["data"]["od_id"])
        coupon.refresh_from_db()
        self.assertEqual(order.od_receipt_price + order.od_misu, 100000 - 5000 + order.od_send_cost + order.od_send_cost2)
        self.assertEqual(order.coupon_logs.get().cp_price, 5000)
        self.assertEqual(coupon.cp_used, "1")

    def test_an_item_coupon_that_expired_after_it_was_added_gives_no_discount(self):
        from datetime import timedelta

        from django.utils import timezone

        coupon = self.item_coupon()
        self.put_in_cart_with_item_coupon(coupon)
        coupon.cp_end = timezone.localdate() - timedelta(days=1)
        coupon.save(update_fields=["cp_end"])
        order = ShopOrder.objects.get(pk=self.place().json()["data"]["od_id"])
        self.assertFalse(order.coupon_logs.exists())
        self.assertEqual(order.od_receipt_price + order.od_misu, 100000 + order.od_send_cost + order.od_send_cost2)

    def test_an_order_coupon_cannot_be_used_as_an_item_coupon_as_well(self):
        coupon = self.make_coupon()
        self.client.post("/api/v1/shop/cart", {"it_id": self.product.it_id, "ct_qty": 1}, format="json")
        ct_id = self.client.get("/api/v1/shop/cart").json()["data"]["items"][0]["ct_id"]
        attached = self.client.post("/api/v1/shop/coupons/apply-to-cart", {"ct_id": ct_id, "cp_id": coupon.cp_id}, format="json")
        order = ShopOrder.objects.get(pk=self.place(cp_id=coupon.cp_id).json()["data"]["od_id"])
        self.assertEqual(attached.status_code, 400)
        self.assertEqual(order.coupon_logs.count(), 1)

    def test_points_cannot_exceed_what_is_left_to_pay_after_an_item_coupon(self):
        from gnu_jango.shop.models import ShopShippingPolicy

        ShopShippingPolicy.objects.filter(pk=1).update(de_settle_max_point=1000000)
        coupon = self.item_coupon()
        self.put_in_cart_with_item_coupon(coupon)
        self.profile.user_point = 200000
        self.profile.save(update_fields=["user_point"])
        order = ShopOrder.objects.get(pk=self.place(point_use=200000).json()["data"]["od_id"])
        self.profile.refresh_from_db()
        self.assertEqual(order.od_receipt_point, 95000)
        self.assertEqual(self.profile.user_point, 105000)

    def test_a_failed_point_debit_leaves_no_order_stock_change_or_used_coupon(self):
        from unittest import mock

        coupon = self.make_coupon()
        self.profile.user_point = 80000
        self.profile.save(update_fields=["user_point"])
        before = ShopOrder.objects.count()
        with mock.patch("gnu_jango.api.v1_shop.change_member_point", return_value=False):
            self.client.post("/api/v1/shop/cart", {"it_id": self.product.it_id, "ct_qty": 2}, format="json")
            response = self.place(cp_id=coupon.cp_id, point_use=20000)
        self.assertEqual(response.status_code, 400, response.content[:300])
        self.assertEqual(ShopOrder.objects.count(), before)
        self.product.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 50)
        self.assertEqual(coupon.cp_used, "")

    def test_cancelling_twice_returns_the_points_only_once(self):
        order = self.order(point_use=20000)
        for _ in range(2):
            self.client.post("/api/v1/shop/payment/cancel", {"order_id": order.od_id}, format="json")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.user_point, 80000)
        self.assertEqual(User_Point.objects.filter(user=self.member, po_rel_table="@order-cancel").count(), 1)

    def test_an_administrator_cancel_gives_points_and_coupon_back(self):
        coupon = self.make_coupon()
        self.profile.user_point = 80000
        self.profile.save(update_fields=["user_point"])
        order = self.order_with(cp_id=coupon.cp_id, point_use=20000)
        admin = get_user_model().objects.create_superuser(username="point-admin", email="point-admin@example.test", password="password")
        admin_client = Client()
        admin_client.force_login(admin)
        response = admin_client.post(
            reverse("admin:shop_shoporder_changelist"),
            {"action": "change_selected_order_status", "_selected_action": [order.pk], "od_status": "취소"},
        )
        self.assertEqual(response.status_code, 302, response.content[:300])
        self.profile.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(self.profile.user_point, 80000)
        self.assertEqual(coupon.cp_used, "")

    def test_the_coupon_list_for_checkout_leaves_out_expired_and_used_coupons(self):
        from datetime import timedelta

        from django.utils import timezone

        good = self.make_coupon(cp_subject="Good")
        self.make_coupon(cp_subject="Expired", cp_end=timezone.localdate() - timedelta(days=1))
        self.make_coupon(cp_subject="Used", cp_used="1")
        everything = self.client.get("/api/v1/shop/coupons/mine").json()["data"]
        usable = self.client.get("/api/v1/shop/coupons/mine?usable=1").json()["data"]
        self.assertEqual(len(everything), 3)
        self.assertEqual([item["cp_id"] for item in usable], [good.cp_id])
