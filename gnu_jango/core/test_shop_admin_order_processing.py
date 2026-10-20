"""youngcart order processing in the shop admin (adm/shop_admin/orderlistupdate.php,
orderformcartupdate.php, orderlistdelete.php): status transitions, payment and refund records,
PG cancellation, permission checks on the order reports, and order lines that cannot be edited
by hand."""

import io
import json
from unittest.mock import patch
from urllib import error as urllib_error

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from gnu_jango.core.test_shop_payments_api import FAKE_TOSS, fake_http_response, http_error
from gnu_jango.shop.admin.orders import set_order_status
from gnu_jango.shop.models import (
    ShopCoupon,
    ShopCouponLog,
    ShopOrder,
    ShopOrderData,
    ShopOrderItem,
    ShopProduct,
)
from gnu_jango.users.models import Profile, User_Point

REPORT_URLS = (
    "admin:shop_shoporder_reports",
    "admin:shop_shoporder_sales_rank",
    "admin:shop_shoporder_print",
    "admin:shop_shoporder_unresolved",
)
URLOPEN = "gnu_jango.api.shop_payments.urllib_request.urlopen"


class OrderReportPermissionTests(TestCase):
    def setUp(self):
        ShopOrder.objects.create(od_id="PERM1", od_name="홍길동", od_hp="010-1234-5678", od_misu=1000)
        self.staff = get_user_model().objects.create_user(
            username="community", email="community@example.test", password="pw", is_staff=True
        )
        call_command("setup_admin_role_presets", stdout=io.StringIO())
        self.staff.groups.add(Group.objects.get(name="커뮤니티 운영자"))
        self.client.force_login(self.staff)

    def test_staff_without_order_permissions_get_403_on_every_report_and_export(self):
        for name in REPORT_URLS:
            for query in ("", "?export=csv"):
                with self.subTest(name=name, query=query):
                    response = self.client.get(reverse(name) + query)
                    self.assertEqual(response.status_code, 403)
                    self.assertNotIn("010-1234-5678", response.content.decode("utf-8", "replace"))

    def test_the_order_view_permission_opens_the_reports(self):
        self.staff.user_permissions.add(Permission.objects.get(codename="view_shoporder"))
        for name in REPORT_URLS:
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        response = self.client.get(reverse("admin:shop_shoporder_unresolved") + "?export=csv")
        self.assertEqual(response.status_code, 200)
        self.assertIn("PERM1", response.content.decode("utf-8-sig"))

    def test_anonymous_visitors_are_sent_to_the_login_page(self):
        self.client.logout()
        response = self.client.get(reverse("admin:shop_shoporder_reports"))
        self.assertEqual(response.status_code, 302)


class OrderAdminBase(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="order-admin", email="order-admin@example.test", password="password"
        )
        self.client.force_login(self.admin)
        self.member = get_user_model().objects.create_user(username="buyer", email="buyer@example.test", password="pw")
        self.profile, _ = Profile.objects.get_or_create(user=self.member)
        self.product = ShopProduct.objects.create(
            it_id="YC100", it_name="Shirt", it_price=5000, it_use="1", it_stock_qty=5
        )

    def make_order(self, status="주문", *, od_id="YC-1", settle_case="무통장", qty=2, **fields):
        cart_price = self.product.it_price * qty
        values = {
            "od_name": "Buyer",
            "user": self.member,
            "od_status": status,
            "od_settle_case": settle_case,
            "od_cart_price": cart_price,
            "od_send_cost": 3000,
            "od_misu": cart_price + 3000,
            **fields,
        }
        order = ShopOrder.objects.create(od_id=od_id, **values)
        ShopOrderItem.objects.create(
            order=order, product=self.product, ct_id="1", it_id=self.product.it_id, it_name="Shirt",
            ct_price=self.product.it_price, ct_qty=qty, ct_status=status, stock_adjusted=True,
        )
        return order

    def paid_order(self, status="입금", **fields):
        values = {"od_receipt_price": 13000, "od_misu": 0, "od_receipt_time": "2026-10-20 10:00:00", **fields}
        return self.make_order(status, **values)

    def toss_order(self, status="입금", **fields):
        values = {"od_pg": "toss", "od_tno": "tpk_test_123", "settle_case": "신용카드", **fields}
        return self.paid_order(status, **values)

    def bulk(self, orders, status):
        return self.client.post(
            reverse("admin:shop_shoporder_changelist"),
            {"action": "change_selected_order_status", "_selected_action": [o.pk for o in orders], "od_status": status},
            follow=True,
        )

    def messages_of(self, response):
        return [str(message) for message in response.context["messages"]]

    def reload(self, *objects):
        for obj in objects:
            obj.refresh_from_db()


@override_settings(**FAKE_TOSS)
class AdminCancelTests(OrderAdminBase):
    def test_a_paid_toss_order_is_cancelled_at_toss_first_and_keeps_its_payment_record(self):
        order = self.toss_order()
        reply = fake_http_response({"orderId": order.od_id, "paymentKey": order.od_tno, "status": "CANCELED"})
        with patch(URLOPEN, return_value=reply) as urlopen:
            result = set_order_status(order, "취소", "고객 요청", actor="order-admin")

        self.assertTrue(result, result.message)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, f"https://api.tosspayments.com/v1/payments/{order.od_tno}/cancel")
        self.assertEqual(json.loads(request.data), {"cancelReason": "고객 요청"})
        self.assertEqual(request.get_header("Idempotency-key"), f"admin-cancel-{order.od_id}-{order.od_tno}")
        self.reload(order, self.product)
        self.assertEqual(order.od_status, "취소")
        self.assertEqual((order.od_receipt_price, order.od_refund_price, order.od_misu), (13000, 13000, 0))
        self.assertEqual(order.od_cancel_price, 10000)
        self.assertEqual(self.product.it_stock_qty, 7)
        self.assertIn("order-admin 주문취소 처리 PG 신용카드 승인취소 처리 - 고객 요청", order.od_mod_history)
        self.assertNotIn("고객 요청", order.od_memo)
        self.assertTrue(ShopOrderData.objects.filter(order=order, log_id__startswith="toss-cancel").exists())

    def test_a_toss_refusal_leaves_the_order_as_it_was(self):
        order = self.toss_order()
        refusal = http_error(400, '{"code":"NOT_CANCELABLE_PAYMENT","message":"취소 할 수 없는 결제 입니다."}'.encode())
        with patch(URLOPEN, side_effect=refusal):
            response = self.bulk([order], "취소")

        self.reload(order, self.product)
        self.assertEqual(order.od_status, "입금")
        self.assertEqual((order.od_receipt_price, order.od_refund_price, order.od_cancel_price), (13000, 0, 0))
        self.assertEqual(order.items.get().ct_status, "입금")
        self.assertEqual(self.product.it_stock_qty, 5)
        self.assertTrue(any("NOT_CANCELABLE_PAYMENT" in message for message in self.messages_of(response)))

    def test_an_unreachable_toss_leaves_the_order_as_it_was(self):
        order = self.toss_order()
        with patch(URLOPEN, side_effect=urllib_error.URLError("down")):
            result = set_order_status(order, "취소", actor="order-admin")
        self.assertFalse(result)
        self.assertIn("토스페이먼츠에 연결하지 못했습니다", result.message)
        self.reload(order)
        self.assertEqual(order.od_status, "입금")

    def test_a_payment_toss_cancelled_already_is_cancelled_here_too(self):
        order = self.toss_order()
        already = http_error(400, b'{"code":"ALREADY_CANCELED_PAYMENT","message":"already"}')
        with patch(URLOPEN, side_effect=already):
            self.assertTrue(set_order_status(order, "취소"))
        self.reload(order)
        self.assertEqual((order.od_status, order.od_refund_price), ("취소", 13000))

    @override_settings(SHOP_TOSS_CLIENT_KEY="", SHOP_TOSS_SECRET_KEY="")
    def test_without_toss_keys_a_toss_order_is_not_cancelled(self):
        order = self.toss_order()
        with patch(URLOPEN) as urlopen:
            result = set_order_status(order, "취소")
        urlopen.assert_not_called()
        self.assertFalse(result)
        self.reload(order)
        self.assertEqual(order.od_status, "입금")

    def test_a_paid_bank_order_is_cancelled_and_recorded_as_a_manual_refund(self):
        order = self.paid_order()
        with patch(URLOPEN) as urlopen:
            response = self.bulk([order], "취소")
        urlopen.assert_not_called()
        self.reload(order, self.product)
        self.assertEqual(order.od_status, "취소")
        self.assertEqual((order.od_receipt_price, order.od_refund_price, order.od_misu), (13000, 13000, 0))
        self.assertIn("무통장 환불 필요 (수동)", order.od_mod_history)
        self.assertEqual(self.product.it_stock_qty, 7)
        self.assertTrue(any("직접 환불" in message for message in self.messages_of(response)))

    def test_a_pending_online_payment_is_not_treated_as_paid(self):
        # a card order waiting for its payment carries the amount due in od_receipt_price
        order = self.make_order(od_pg="toss", settle_case="신용카드", od_receipt_price=13000)
        with patch(URLOPEN) as urlopen:
            self.assertTrue(set_order_status(order, "취소"))
        urlopen.assert_not_called()
        self.reload(order)
        self.assertEqual((order.od_status, order.od_receipt_price, order.od_refund_price), ("취소", 0, 0))

    def test_an_unpaid_order_gives_stock_coupon_and_points_back_once(self):
        coupon = ShopCoupon.objects.create(
            cp_id="YC-CP1", cp_subject="Coupon", cp_method=2, cp_price=1000, user=self.member, cp_used="1"
        )
        order = self.make_order(od_receipt_point=2000, od_coupon=1000)
        ShopCouponLog.objects.create(
            cl_id=1, coupon=coupon, cp_id=coupon.cp_id, user=self.member, order=order, od_id=order.od_id, cp_price=1000
        )
        for _ in range(2):
            set_order_status(order, "취소", actor="order-admin")

        self.reload(order, self.product, coupon, self.profile)
        self.assertEqual(order.od_status, "취소")
        self.assertEqual((order.od_receipt_price, order.od_refund_price, order.od_misu), (0, 0, 0))
        self.assertEqual(self.product.it_stock_qty, 7)
        self.assertEqual(coupon.cp_used, "")
        self.assertEqual(self.profile.user_point, 2000)
        self.assertEqual(User_Point.objects.filter(user=self.member, po_rel_table="@order-cancel").count(), 1)
        self.assertEqual(order.od_mod_history.count("주문취소 처리"), 1)

    def test_a_cancelled_order_is_not_reopened(self):
        order = self.make_order("취소")
        result = set_order_status(order, "입금")
        self.assertFalse(result)
        self.reload(order)
        self.assertEqual(order.od_status, "취소")

    def test_the_customer_cancel_still_writes_its_reason_to_the_memo(self):
        order = self.make_order()
        api = APIClient()
        api.force_authenticate(self.member)
        response = api.patch(f"/api/v1/shop/orders/{order.od_id}", {"reason": "wrong size"}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.reload(order)
        self.assertEqual(order.od_status, "취소")
        self.assertIn("wrong size", order.od_memo)
        self.assertIn("주문취소 처리 - wrong size", order.od_mod_history)
        self.assertNotIn("od_mod_history", response.json()["data"])
