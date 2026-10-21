"""youngcart line-level cancellations in the shop admin (adm/shop_admin/orderformcartupdate.php,
orderpartcancelupdate.php): 취소, 반품 and 품절 of chosen order lines, the repricing of the order
(get_order_info), the refund of what was overpaid, and the whole-order return."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
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
    ShopShippingPolicy,
)
from gnu_jango.shop.order_coupons import order_coupon_totals
from gnu_jango.shop.order_flow import order_misu
from gnu_jango.shop.order_lines import change_order_lines, plan_line_change

URLOPEN = "gnu_jango.api.shop_payments.urllib_request.urlopen"


class PartialCancelBase(TestCase):
    """Order YC-P: shirt 20,000 × 2 and cap 10,000 × 1 = 50,000, shipped free (the shop's 차등
    rule charges 3,000 below 50,000)."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="order-admin", email="order-admin@example.test", password="password"
        )
        self.client.force_login(self.admin)
        self.member = get_user_model().objects.create_user(username="buyer", email="buyer@example.test", password="pw")
        self.shirt = ShopProduct.objects.create(it_id="P-SHIRT", it_name="Shirt", it_price=20000, it_use="1", it_stock_qty=5)
        self.cap = ShopProduct.objects.create(it_id="P-CAP", it_name="Cap", it_price=10000, it_use="1", it_stock_qty=5)
        ShopShippingPolicy.objects.update_or_create(
            pk=1, defaults={"de_send_cost_case": "차등", "de_send_cost_limit": "50000", "de_send_cost_list": "3000"}
        )

    def make_order(self, status="입금", *, settle_case="무통장", paid=50000, line_status=None, **fields):
        values = {
            "od_name": "Buyer",
            "user": self.member,
            "od_status": status,
            "od_settle_case": settle_case,
            "od_cart_price": 50000,
            "od_send_cost": 0,
            "od_receipt_price": paid,
            "od_misu": 50000 - paid,
            **fields,
        }
        order = ShopOrder.objects.create(od_id="YC-P", **values)
        line_status = line_status or status
        self.shirt_line = ShopOrderItem.objects.create(
            order=order, product=self.shirt, ct_id="1", it_id="P-SHIRT", it_name="Shirt",
            ct_price=20000, ct_qty=2, ct_status=line_status, stock_adjusted=True,
        )
        self.cap_line = ShopOrderItem.objects.create(
            order=order, product=self.cap, ct_id="2", it_id="P-CAP", it_name="Cap",
            ct_price=10000, ct_qty=1, ct_status=line_status, stock_adjusted=True,
        )
        return order

    def toss_order(self, status="입금", **fields):
        return self.make_order(status, settle_case="신용카드", od_pg="toss", od_tno="tpk_part_1", **fields)

    def reload(self, *objects):
        for obj in objects:
            obj.refresh_from_db()


class UnpaidPartialCancelTests(PartialCancelBase):
    def test_cancelling_a_line_restores_its_stock_and_reprices_the_order(self):
        order = self.make_order("주문", paid=0)
        with patch(URLOPEN) as urlopen:
            result = change_order_lines(order, [self.cap_line.pk], "취소", "고객 요청", actor="order-admin")
        urlopen.assert_not_called()
        self.assertTrue(result, result.message)
        self.reload(order, self.cap_line, self.shirt_line, self.cap, self.shirt)
        self.assertEqual((self.cap_line.ct_status, self.cap_line.stock_adjusted), ("취소", False))
        self.assertEqual(self.shirt_line.ct_status, "주문")
        self.assertEqual((self.cap.it_stock_qty, self.shirt.it_stock_qty), (6, 5))
        self.assertEqual(order.od_status, "주문")
        # 40,000 left: below the free-shipping line, so the 3,000 fee comes back
        self.assertEqual((order.od_cancel_price, order.od_send_cost, order.od_misu), (10000, 3000, 43000))
        self.assertEqual(order.od_refund_price, 0)
        self.assertEqual(order_misu(order), 43000)
        self.assertIn("order-admin Cap 주문→취소", order.od_mod_history)
        self.assertIn("상품 1건 취소 처리 - 고객 요청", order.od_mod_history)
        self.assertIn("남은 결제할 금액은 43,000원", result.message)

    def test_cancelling_every_line_cancels_the_order_and_gives_the_coupon_back(self):
        order = self.make_order("주문", paid=0, od_coupon=5000, od_misu=45000)
        coupon = ShopCoupon.objects.create(
            user=self.member, cp_subject="5천원", cp_method=2, cp_price=5000, cp_minimum=10000, cp_used="1"
        )
        ShopCouponLog.objects.create(cl_id=1, coupon=coupon, cp_id=coupon.cp_id, user=self.member, order=order, od_id=order.od_id, cp_price=5000)
        self.assertTrue(change_order_lines(order, [self.cap_line.pk], "품절"))
        self.reload(order)
        self.assertEqual((order.od_status, order.od_coupon, order.od_misu), ("주문", 5000, 38000))

        result = change_order_lines(order, [self.shirt_line.pk], "취소")
        self.assertTrue(result, result.message)
        self.reload(order, self.cap_line, self.shirt_line, self.shirt, self.cap, coupon)
        self.assertEqual(order.od_status, "취소")
        # the line marked 품절 keeps its status; the stock went back once each
        self.assertEqual((self.cap_line.ct_status, self.shirt_line.ct_status), ("품절", "취소"))
        self.assertEqual((self.shirt.it_stock_qty, self.cap.it_stock_qty), (7, 6))
        self.assertEqual((order.od_cancel_price, order.od_misu, order.od_coupon, order.od_send_cost), (50000, 0, 0, 0))
        self.assertEqual(coupon.cp_used, "")
        self.assertFalse(ShopCouponLog.objects.filter(order=order).exists())
        self.assertIn("주문취소 처리", order.od_mod_history)

    def test_a_pending_card_payment_cannot_be_cancelled_line_by_line(self):
        order = self.toss_order("주문", od_receipt_price=50000, od_misu=50000)
        result = change_order_lines(order, [self.cap_line.pk], "취소")
        self.assertFalse(result)
        self.assertIn("결제를 기다리는 PG", result.message)
        self.reload(self.cap_line)
        self.assertEqual(self.cap_line.ct_status, "주문")

    def test_lines_must_fit_the_status_they_change_to(self):
        order = self.make_order("배송")
        result = change_order_lines(order, [self.cap_line.pk], "취소")
        self.assertFalse(result)
        self.assertIn("반품으로 처리하세요", result.message)
        other = ShopOrder.objects.create(od_id="YC-OTHER", od_status="입금")
        stranger = ShopOrderItem.objects.create(order=other, ct_id="9", it_id="P-CAP", it_name="Cap", ct_status="입금")
        self.assertFalse(change_order_lines(order, [stranger.pk], "반품"))
        self.assertFalse(change_order_lines(order, [], "반품"))
        self.assertFalse(change_order_lines(order, [self.cap_line.pk], "주문"))


class BankPaidPartialCancelTests(PartialCancelBase):
    def test_a_paid_bank_order_records_the_overpaid_amount_as_a_manual_refund(self):
        order = self.make_order("입금")
        with patch(URLOPEN) as urlopen:
            result = change_order_lines(order, [self.cap_line.pk], "품절", actor="order-admin")
        urlopen.assert_not_called()
        self.assertTrue(result, result.message)
        self.assertTrue(result.manual_refund)
        self.reload(order, self.cap_line, self.cap)
        self.assertEqual(self.cap_line.ct_status, "품절")
        self.assertEqual(self.cap.it_stock_qty, 6)
        # 40,000 + 3,000 shipping is owed now; 7,000 of the 50,000 paid goes back by hand
        self.assertEqual((order.od_receipt_price, order.od_refund_price, order.od_misu), (50000, 7000, 0))
        self.assertIn("무통장 환불 필요 (수동) 7,000원", order.od_mod_history)
        self.assertIn("7,000원은 직접 환불해야 합니다", result.message)

    def test_a_coupon_whose_minimum_no_longer_holds_is_dropped(self):
        # 50,000 - product coupon 1,000 (on the cap) - order coupon 5,000 (minimum 45,000) = 44,000 paid
        order = self.make_order("입금", paid=44000, od_coupon=5000, od_misu=0)
        order_coupon = ShopCoupon.objects.create(
            user=self.member, cp_subject="5천원", cp_method=2, cp_price=5000, cp_minimum=45000, cp_used="1"
        )
        cap_coupon = ShopCoupon.objects.create(
            user=self.member, cp_subject="모자", cp_method=0, cp_target="P-CAP", cp_price=1000, cp_used="1"
        )
        for cl_id, coupon, price in ((1, order_coupon, 5000), (2, cap_coupon, 1000)):
            ShopCouponLog.objects.create(
                cl_id=cl_id, coupon=coupon, cp_id=coupon.cp_id, user=self.member, order=order, od_id=order.od_id, cp_price=price
            )
        self.assertEqual(order_misu(order), 0)

        plan, error = plan_line_change(order, [self.cap_line.pk], "취소")
        self.assertEqual(error, "")
        self.assertEqual((plan.cart_coupon, plan.od_coupon, plan.send_cost, plan.total), (0, 0, 3000, 43000))
        self.assertTrue(change_order_lines(order, [self.cap_line.pk], "취소"))
        self.reload(order, order_coupon)
        # the shirt alone (40,000) misses the 45,000 minimum: youngcart sets od_coupon to 0
        self.assertEqual((order.od_coupon, order.od_send_cost, order.od_refund_price, order.od_misu), (0, 3000, 1000, 0))
        self.assertEqual(order_misu(order), 0)
        # youngcart keeps the coupons used on a partial cancel
        self.assertEqual(order_coupon.cp_used, "1")
        self.assertEqual(ShopCouponLog.objects.filter(order=order).count(), 2)

    def test_points_paid_beyond_the_new_total_are_left_for_a_manual_adjustment(self):
        # 10,000 cash + 40,000 points; after the shirts go only 13,000 is owed
        order = self.make_order("입금", paid=10000, od_receipt_point=40000)
        result = change_order_lines(order, [self.shirt_line.pk], "취소")
        self.assertTrue(result, result.message)
        self.reload(order)
        self.assertEqual((order.od_refund_price, order.od_receipt_point, order.od_misu), (10000, 40000, 0))
        self.assertIn("포인트 27,000점 수동 조정 필요", order.od_mod_history)
        self.assertIn("27,000점은 회원 포인트에서 직접 조정", result.message)


class ProductCouponLineTests(PartialCancelBase):
    """A product coupon sits on its product's first line (api.shop_coupons
    items_with_product_coupon_prices) and counts while that line is active (get_order_info)."""

    def setUp(self):
        super().setUp()
        self.order = self.make_order("주문", paid=0, od_misu=49000)
        self.shirt_option = ShopOrderItem.objects.create(
            order=self.order, product=self.shirt, ct_id="3", it_id="P-SHIRT", it_name="Shirt", ct_option="XL",
            ct_price=0, io_type=1, io_price=1000, ct_qty=1, ct_status="주문", stock_adjusted=False,
        )
        coupon = ShopCoupon.objects.create(
            user=self.member, cp_subject="셔츠", cp_method=0, cp_target="P-SHIRT", cp_price=2000, cp_used="1"
        )
        ShopCouponLog.objects.create(
            cl_id=1, coupon=coupon, cp_id=coupon.cp_id, user=self.member, order=self.order, od_id=self.order.od_id, cp_price=2000
        )

    def test_the_coupon_stays_while_the_first_line_of_its_product_is_active(self):
        self.assertEqual(order_coupon_totals(self.order).cart_by_line, {self.shirt_line.pk: 2000})
        self.assertTrue(change_order_lines(self.order, [self.shirt_option.pk], "취소"))
        self.reload(self.order)
        self.assertEqual(order_coupon_totals(self.order).cart, 2000)
        self.assertEqual(order_misu(self.order), 50000 - 2000)

    def test_the_coupon_drops_with_the_first_line_of_its_product(self):
        plan, _ = plan_line_change(self.order, [self.shirt_line.pk], "취소")
        self.assertEqual(plan.cart_coupon, 0)
        self.assertTrue(change_order_lines(self.order, [self.shirt_line.pk], "취소"))
        self.reload(self.order)
        self.assertEqual(order_coupon_totals(self.order).cart, 0)
        api = APIClient()
        api.force_authenticate(self.member)
        payload = api.get(f"/api/v1/shop/orders/{self.order.od_id}").json()["data"]
        # cap 10,000 + supplement 1,000 + 3,000 shipping, without the shirt coupon
        self.assertEqual((payload["od_cart_coupon"], payload["od_total_price"], payload["od_misu_price"]), (0, 14000, 14000))
        self.assertEqual(order_misu(self.order), 14000)


@override_settings(**FAKE_TOSS)
class TossPartialCancelTests(PartialCancelBase):
    def partial_reply(self, order, status="PARTIAL_CANCELED"):
        return fake_http_response({"orderId": order.od_id, "paymentKey": order.od_tno, "status": status})

    def test_toss_refunds_the_overpaid_amount_before_the_lines_change(self):
        order = self.toss_order()
        with patch(URLOPEN, return_value=self.partial_reply(order)) as urlopen:
            result = change_order_lines(order, [self.shirt_line.pk], "취소", "사이즈 품절", actor="order-admin")
        self.assertTrue(result, result.message)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, f"https://api.tosspayments.com/v1/payments/{order.od_tno}/cancel")
        # 10,000 cap + 3,000 shipping stay; 37,000 goes back
        self.assertEqual(json.loads(request.data), {"cancelReason": "사이즈 품절", "cancelAmount": 37000})
        self.assertTrue(request.get_header("Idempotency-key").startswith("admin-part-YC-P-"))
        self.reload(order, self.shirt_line, self.shirt)
        self.assertEqual(order.od_status, "입금")
        self.assertEqual((order.od_receipt_price, order.od_refund_price, order.od_misu), (50000, 37000, 0))
        self.assertEqual((order.od_cancel_price, order.od_send_cost), (40000, 3000))
        self.assertEqual((self.shirt_line.ct_status, self.shirt.it_stock_qty), ("취소", 7))
        self.assertIn("PG 신용카드 부분취소 37,000원", order.od_mod_history)
        self.assertTrue(ShopOrderData.objects.filter(order=order, log_id__startswith="tpc-").exists())
        api = APIClient()
        api.force_authenticate(self.member)
        payload = api.get(f"/api/v1/shop/orders/{order.od_id}").json()["data"]
        self.assertEqual((payload["od_cancel_price"], payload["od_refund_price"], payload["od_misu_price"]), (40000, 37000, 0))
        self.assertEqual({item["ct_status"] for item in payload["items"]}, {"취소", "입금"})

    def test_a_toss_refusal_changes_nothing(self):
        order = self.toss_order()
        refusal = http_error(400, '{"code":"NOT_CANCELABLE_AMOUNT","message":"취소 가능 금액 초과"}'.encode())
        with patch(URLOPEN, side_effect=refusal):
            result = change_order_lines(order, [self.shirt_line.pk], "취소")
        self.assertFalse(result)
        self.assertIn("아무것도 바꾸지 않았습니다", result.message)
        self.assertIn("NOT_CANCELABLE_AMOUNT", result.message)
        self.reload(order, self.shirt_line, self.shirt)
        self.assertEqual((order.od_refund_price, order.od_cancel_price, order.od_send_cost, order.od_mod_history), (0, 0, 0, ""))
        self.assertEqual((self.shirt_line.ct_status, self.shirt_line.stock_adjusted, self.shirt.it_stock_qty), ("입금", True, 5))

    def test_a_double_submit_refunds_once(self):
        order = self.toss_order()
        first_plan, _ = plan_line_change(order, [self.shirt_line.pk], "취소")
        again_plan, _ = plan_line_change(order, [self.shirt_line.pk], "취소")
        self.assertEqual(first_plan.idempotency_key, again_plan.idempotency_key)
        with patch(URLOPEN, return_value=self.partial_reply(order)) as urlopen:
            self.assertTrue(change_order_lines(order, [self.shirt_line.pk], "취소"))
            second = change_order_lines(order, [self.shirt_line.pk], "취소")
        self.assertFalse(second)
        self.assertIn("이미 '취소' 처리된 상품", second.message)
        self.assertEqual(urlopen.call_count, 1)
        self.reload(order, self.shirt)
        self.assertEqual((order.od_refund_price, self.shirt.it_stock_qty), (37000, 7))

    def test_an_error_after_the_toss_refund_still_records_the_refund(self):
        order = self.toss_order()
        with patch(URLOPEN, return_value=self.partial_reply(order)), patch(
            "gnu_jango.shop.order_lines._apply_plan", side_effect=RuntimeError("boom")
        ):
            result = change_order_lines(order, [self.shirt_line.pk], "취소")
        self.assertFalse(result)
        self.assertIn("PG에서 37,000원을 환불했지만", result.message)
        self.reload(order, self.shirt_line)
        self.assertEqual(order.od_refund_price, 37000)
        self.assertEqual(self.shirt_line.ct_status, "입금")
        self.assertIn("확인 필요", order.od_mod_history)

    def test_cancelling_the_rest_after_a_partial_refund_refunds_only_the_rest(self):
        order = self.toss_order()
        with patch(URLOPEN, return_value=self.partial_reply(order)):
            self.assertTrue(change_order_lines(order, [self.shirt_line.pk], "취소"))
        with patch(URLOPEN, return_value=self.partial_reply(order, "CANCELED")) as urlopen:
            result = set_order_status(order, "취소", actor="order-admin")
        self.assertTrue(result, result.message)
        self.assertEqual(json.loads(urlopen.call_args.args[0].data)["cancelAmount"], 13000)
        self.reload(order, self.cap_line, self.shirt_line, self.cap)
        self.assertEqual(order.od_status, "취소")
        self.assertEqual((order.od_receipt_price, order.od_refund_price, order.od_misu), (50000, 50000, 0))
        self.assertEqual((self.shirt_line.ct_status, self.cap_line.ct_status, self.cap.it_stock_qty), ("취소", "취소", 6))


class ReturnTests(PartialCancelBase):
    def completed_order(self, **fields):
        order = self.make_order("완료", **fields)
        ShopOrderItem.objects.filter(order=order).update(ct_point=100, ct_point_use=True)
        ShopProduct.objects.filter(pk__in=["P-SHIRT", "P-CAP"]).update(it_sum_qty=7)
        return order

    @override_settings(**FAKE_TOSS)
    def test_returning_a_completed_toss_order_refunds_it_whole_and_takes_points_back(self):
        order = self.completed_order(settle_case="신용카드", od_pg="toss", od_tno="tpk_part_1")
        ShopOrderItem.objects.create(  # another delivered sale of the shirt keeps counting
            order=ShopOrder.objects.create(od_id="YC-SOLD", od_status="완료"), product=self.shirt,
            ct_id="1", it_id="P-SHIRT", it_name="Shirt", ct_qty=3, ct_status="완료",
        )
        reply = fake_http_response({"orderId": order.od_id, "paymentKey": order.od_tno, "status": "CANCELED"})
        with patch(URLOPEN, return_value=reply) as urlopen:
            result = set_order_status(order, "반품", "단순 변심", actor="order-admin")
        self.assertTrue(result, result.message)
        # nothing was refunded before: Toss cancels the whole payment
        self.assertEqual(json.loads(urlopen.call_args.args[0].data), {"cancelReason": "단순 변심"})
        self.reload(order, self.shirt_line, self.cap_line, self.shirt, self.cap)
        self.assertEqual(order.od_status, "반품")
        self.assertEqual((order.od_receipt_price, order.od_refund_price, order.od_misu, order.od_cancel_price), (50000, 50000, 0, 50000))
        self.assertEqual((self.shirt_line.ct_status, self.cap_line.ct_status), ("반품", "반품"))
        self.assertEqual((self.shirt_line.ct_point_use, self.cap_line.ct_point_use), (False, False))
        self.assertEqual((self.shirt.it_stock_qty, self.cap.it_stock_qty), (7, 6))
        self.assertEqual((self.shirt.it_sum_qty, self.cap.it_sum_qty), (3, 0))
        self.assertIn("주문반품 처리 PG 신용카드 승인취소 50,000원 - 단순 변심", order.od_mod_history)
        # a returned order is closed
        self.assertFalse(set_order_status(order, "완료"))

    def test_returning_one_delivered_line_of_a_bank_order(self):
        order = self.completed_order()
        result = change_order_lines(order, [self.cap_line.pk], "반품")
        self.assertTrue(result, result.message)
        self.reload(order, self.cap_line, self.shirt_line, self.cap)
        self.assertEqual((order.od_status, self.cap_line.ct_status, self.shirt_line.ct_status), ("완료", "반품", "완료"))
        self.assertEqual((self.cap_line.ct_point_use, self.cap_line.ct_complete_time), (False, None))
        self.assertTrue(self.shirt_line.ct_point_use)
        self.assertEqual((self.cap.it_stock_qty, self.cap.it_sum_qty), (6, 0))
        self.assertEqual((order.od_refund_price, order.od_send_cost), (7000, 3000))

    def test_the_bulk_action_returns_a_shipped_order_and_refuses_an_unshipped_one(self):
        shipped = self.make_order("배송")
        unshipped = ShopOrder.objects.create(od_id="YC-NOT-SHIPPED", od_status="입금", od_settle_case="무통장")
        response = self.client.post(
            reverse("admin:shop_shoporder_changelist"),
            {"action": "change_selected_order_status", "_selected_action": [shipped.pk, unshipped.pk], "od_status": "반품"},
            follow=True,
        )
        messages = [str(message) for message in response.context["messages"]]
        self.reload(shipped, unshipped)
        self.assertEqual((shipped.od_status, shipped.od_refund_price), ("반품", 50000))
        self.assertEqual(unshipped.od_status, "입금")
        self.assertTrue(any("배송·완료 상태에서만 반품" in message for message in messages))

    def test_the_order_form_offers_a_return_once_the_order_shipped(self):
        order = self.make_order("배송")
        response = self.client.get(reverse("admin:shop_shoporder_change", args=[order.pk]))
        choices = [value for value, _label in response.context["adminform"].form.fields["od_status"].choices]
        self.assertIn("반품", choices)
        self.assertNotIn("취소", choices)


class LineChangeViewTests(PartialCancelBase):
    def url(self, order):
        return reverse("admin:shop_shoporder_lines", args=[order.pk])

    def test_the_change_page_links_to_the_line_page_and_previews_before_applying(self):
        order = self.make_order("입금")
        change_page = self.client.get(reverse("admin:shop_shoporder_change", args=[order.pk])).content.decode()
        self.assertIn(self.url(order), change_page)
        page = self.client.get(self.url(order))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Cap")

        preview = self.client.post(self.url(order), {"ct_chk": [self.cap_line.pk], "ct_status": "취소", "step": "preview"})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.context["plan"].refund, 7000)
        self.reload(self.cap_line)
        self.assertEqual(self.cap_line.ct_status, "입금")

        applied = self.client.post(self.url(order), {"ct_chk": [self.cap_line.pk], "ct_status": "취소", "step": "apply", "reason": "재고 없음"})
        self.assertRedirects(applied, reverse("admin:shop_shoporder_change", args=[order.pk]), fetch_redirect_response=False)
        self.reload(order, self.cap_line)
        self.assertEqual((self.cap_line.ct_status, order.od_refund_price), ("취소", 7000))
        self.assertIn("재고 없음", order.od_mod_history)

    def test_a_refused_change_is_shown_on_the_page(self):
        order = self.make_order("입금")
        response = self.client.post(self.url(order), {"ct_chk": [self.cap_line.pk], "ct_status": "반품", "step": "apply"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("취소 또는 품절로 처리하세요", response.context["error"])

    def test_the_change_permission_is_required(self):
        order = self.make_order("입금")
        staff = get_user_model().objects.create_user(username="viewer", email="viewer@example.test", password="pw", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="view_shoporder"))
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url(order)).status_code, 403)
        response = self.client.post(self.url(order), {"ct_chk": [self.cap_line.pk], "ct_status": "취소", "step": "apply"})
        self.assertEqual(response.status_code, 403)
        self.reload(self.cap_line)
        self.assertEqual(self.cap_line.ct_status, "입금")
        change_page = self.client.get(reverse("admin:shop_shoporder_change", args=[order.pk])).content.decode()
        self.assertNotIn(self.url(order), change_page)
