"""Online-payment orders the customer abandoned are cancelled and give back what they held.

An order for a card or other online payment is created when the payment window opens, which
reserves stock and takes the points and coupons. If the customer closes the window the order
stays "주문" with no transaction id forever. `expire_pending_payment_orders` cancels those after
a grace period; bank-transfer orders (waiting for a deposit) and issued virtual accounts are
left alone.
"""

import json
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from gnu_jango.shop.models import ShopCategory, ShopCoupon, ShopCouponLog, ShopOrder, ShopOrderItem, ShopProduct
from gnu_jango.users.models import Profile, User_Point


class ExpirePendingPaymentOrdersTests(TestCase):
    def setUp(self):
        self.member = get_user_model().objects.create_user(username="pending-member", email="pending@example.test", password="password-1234")
        self.profile, _ = Profile.objects.get_or_create(user=self.member)
        self.profile.user_point = 1000
        self.profile.save()
        category = ShopCategory.objects.create(ca_id="40", ca_name="Pending")
        self.product = ShopProduct.objects.create(it_id="PD001", category=category, it_name="Pending product", it_price=5000, it_stock_qty=8, it_use="1")

    def make_order(self, od_id, *, minutes_ago=180, settle="신용카드", status="주문", tno="", vbank_status="", points=0, coupon=None):
        order = ShopOrder.objects.create(
            od_id=od_id, user=self.member, od_name="Pending", od_settle_case=settle, od_status=status,
            od_cart_price=10000, od_receipt_price=10000 - points, od_receipt_point=points, od_misu=10000 - points,
            od_tno=tno, od_vbank_status=vbank_status, od_pg="toss",
        )
        ShopOrder.objects.filter(pk=order.pk).update(od_datetime=timezone.now() - timedelta(minutes=minutes_ago))
        ShopOrderItem.objects.create(order=order, product=self.product, ct_id=f"ct-{od_id}", it_id=self.product.it_id, it_name=self.product.it_name, ct_price=5000, ct_qty=2, stock_adjusted=True)
        if points:
            self.profile.user_point -= points
            self.profile.save(update_fields=["user_point"])
        if coupon:
            ShopCouponLog.objects.create(cl_id=900000 + ShopCouponLog.objects.count() + 1, coupon=coupon, cp_id=coupon.cp_id, user=self.member, mb_id=self.member.username, order=order, od_id=od_id, cp_price=1000, cl_datetime=timezone.now())
        return order

    def run_command(self, *args):
        out = StringIO()
        call_command("expire_pending_payment_orders", "--json", *args, stdout=out)
        return json.loads(out.getvalue())

    def test_dry_run_reports_without_changing_anything(self):
        order = self.make_order("P1")
        summary = self.run_command()
        order.refresh_from_db()
        self.assertEqual(summary["expired"], 1)
        self.assertEqual(order.od_status, "주문")

    def test_apply_cancels_and_returns_stock_points_and_coupon(self):
        coupon = ShopCoupon.objects.create(user=self.member, cp_subject="Held", cp_method=2, cp_price=1000, cp_used="1")
        order = self.make_order("P2", points=300, coupon=coupon)
        summary = self.run_command("--apply")
        order.refresh_from_db()
        self.product.refresh_from_db()
        self.profile.refresh_from_db()
        coupon.refresh_from_db()
        self.assertEqual(summary["cancelled"], 1)
        self.assertEqual(order.od_status, "취소")
        self.assertEqual(self.product.it_stock_qty, 10)
        self.assertEqual(self.profile.user_point, 1000)
        self.assertEqual(coupon.cp_used, "")
        self.assertTrue(User_Point.objects.filter(user=self.member, po_rel_table="@order-cancel", po_rel_action="P2").exists())

    def test_recent_orders_are_left_alone(self):
        order = self.make_order("P3", minutes_ago=10)
        self.run_command("--apply")
        order.refresh_from_db()
        self.assertEqual(order.od_status, "주문")

    def test_bank_transfer_orders_waiting_for_a_deposit_are_left_alone(self):
        order = self.make_order("P4", settle="무통장")
        self.run_command("--apply")
        order.refresh_from_db()
        self.assertEqual(order.od_status, "주문")

    def test_orders_with_a_payment_transaction_are_left_alone(self):
        paid = self.make_order("P5", tno="tx-123")
        vbank = self.make_order("P6", settle="가상계좌", tno="", vbank_status="WAITING_FOR_DEPOSIT")
        self.run_command("--apply")
        paid.refresh_from_db()
        vbank.refresh_from_db()
        self.assertEqual(paid.od_status, "주문")
        self.assertEqual(vbank.od_status, "주문")

    def test_the_grace_period_is_configurable(self):
        order = self.make_order("P7", minutes_ago=40)
        self.run_command("--apply", "--minutes", "30")
        order.refresh_from_db()
        self.assertEqual(order.od_status, "취소")

    def test_running_twice_refunds_once(self):
        self.make_order("P8", points=200)
        self.run_command("--apply")
        self.run_command("--apply")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.user_point, 1000)
