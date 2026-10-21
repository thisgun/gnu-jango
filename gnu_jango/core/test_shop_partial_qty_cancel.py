"""Partial quantity cancels in the shop admin: 취소, 반품 or 품절 of only some units of an order
line. The line is split (shop/order_line_split.py) and the split-off units go through the line
change of shop/order_lines.py: stock, repricing, coupons, purchase points and the Toss refund
follow the cancelled quantity only."""

import json
from unittest.mock import patch
from urllib import error as urllib_error

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from gnu_jango.core.test_shop_payments_api import FAKE_TOSS, fake_http_response, http_error
from gnu_jango.shop.models import (
    ShopCoupon,
    ShopCouponLog,
    ShopOrder,
    ShopOrderItem,
    ShopProduct,
    ShopShippingPolicy,
)
from gnu_jango.shop.order_coupons import order_coupon_totals
from gnu_jango.shop.order_flow import order_misu
from gnu_jango.shop.order_lines import change_order_lines, preview_line_change
from gnu_jango.shop.order_points import DELIVERY_POINT_TABLE
from gnu_jango.users import point_ledger
from gnu_jango.users.models import Profile

URLOPEN = "gnu_jango.api.shop_payments.urllib_request.urlopen"


class PartialQtyBase(TestCase):
    """Order YC-Q: shirt 20,000 × 3 and cap 10,000 × 1 = 70,000, shipped free (the shop's 차등
    rule charges 3,000 below 50,000)."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="qty-admin", email="qty-admin@example.test", password="password"
        )
        self.client.force_login(self.admin)
        self.member = get_user_model().objects.create_user(username="qty-buyer", email="qty@example.test", password="pw")
        self.shirt = ShopProduct.objects.create(it_id="Q-SHIRT", it_name="Shirt", it_price=20000, it_use="1", it_stock_qty=5)
        self.cap = ShopProduct.objects.create(it_id="Q-CAP", it_name="Cap", it_price=10000, it_use="1", it_stock_qty=5)
        ShopShippingPolicy.objects.update_or_create(
            pk=1, defaults={"de_send_cost_case": "차등", "de_send_cost_limit": "50000", "de_send_cost_list": "3000"}
        )

    def make_order(self, status="입금", *, settle_case="무통장", paid=70000, **fields):
        values = {
            "od_name": "Buyer",
            "user": self.member,
            "od_status": status,
            "od_settle_case": settle_case,
            "od_cart_price": 70000,
            "od_receipt_price": paid,
            "od_misu": max(0, 70000 - paid),
            **fields,
        }
        order = ShopOrder.objects.create(od_id="YC-Q", **values)
        self.shirt_line = ShopOrderItem.objects.create(
            order=order, product=self.shirt, ct_id="11", it_id="Q-SHIRT", it_name="Shirt",
            ct_price=20000, ct_qty=3, ct_status=status, stock_adjusted=True,
        )
        self.cap_line = ShopOrderItem.objects.create(
            order=order, product=self.cap, ct_id="12", it_id="Q-CAP", it_name="Cap",
            ct_price=10000, ct_qty=1, ct_status=status, stock_adjusted=True,
        )
        return order

    def toss_order(self, status="입금", **fields):
        return self.make_order(status, settle_case="신용카드", od_pg="toss", od_tno="tpk_qty_1", **fields)

    def split_line(self, order):
        return order.items.exclude(pk__in=[self.shirt_line.pk, self.cap_line.pk]).get()

    def reload(self, *objects):
        for obj in objects:
            obj.refresh_from_db()


class UnpaidPartialQtyTests(PartialQtyBase):
    def test_cancelling_one_of_three_splits_the_line_and_restores_one_unit(self):
        order = self.make_order("주문", paid=0)
        with patch(URLOPEN) as urlopen:
            result = change_order_lines(
                order, [self.shirt_line.pk], "취소", "1개만 취소", actor="qty-admin",
                quantities={self.shirt_line.pk: 1}, expected={self.shirt_line.pk: 3},
            )
        urlopen.assert_not_called()
        self.assertTrue(result, result.message)
        self.reload(order, self.shirt_line, self.shirt)
        split = self.split_line(order)
        self.assertEqual((self.shirt_line.ct_qty, self.shirt_line.ct_status, self.shirt_line.stock_adjusted), (2, "주문", True))
        self.assertEqual((split.ct_qty, split.ct_status, split.stock_adjusted, split.ct_id), (1, "취소", False, "11-c1"))
        self.assertEqual((split.it_id, split.ct_price, split.product_id), ("Q-SHIRT", 20000, "Q-SHIRT"))
        self.assertEqual(self.shirt.it_stock_qty, 6)  # one unit back, not three
        # 50,000 left keeps free shipping
        self.assertEqual((order.od_cart_price, order.od_cancel_price, order.od_send_cost, order.od_misu), (70000, 20000, 0, 50000))
        self.assertEqual(order_misu(order), 50000)
        self.assertIn("qty-admin Shirt 수량 3→2 (1개 분리)", order.od_mod_history)
        self.assertIn("Shirt 1개 주문→취소", order.od_mod_history)

    def test_a_second_split_takes_the_next_ct_id_and_the_whole_quantity_needs_no_split(self):
        order = self.make_order("주문", paid=0)
        for _ in range(2):
            qty = ShopOrderItem.objects.get(pk=self.shirt_line.pk).ct_qty
            self.assertTrue(change_order_lines(order, [self.shirt_line.pk], "품절", quantities={self.shirt_line.pk: 1}, expected={self.shirt_line.pk: qty}))
        self.assertEqual(sorted(order.items.values_list("ct_id", flat=True)), ["11", "11-c1", "11-c2", "12"])
        self.assertTrue(change_order_lines(order, [self.cap_line.pk], "취소", quantities={self.cap_line.pk: 1}))
        self.assertEqual(order.items.count(), 4)
        self.reload(self.cap_line, self.shirt)
        self.assertEqual((self.cap_line.ct_status, self.shirt.it_stock_qty), ("취소", 7))

    def test_a_quantity_outside_the_line_is_refused_and_nothing_changes(self):
        order = self.make_order("주문", paid=0)
        for qty in (0, 4, -1):
            with self.subTest(qty=qty):
                result = change_order_lines(order, [self.shirt_line.pk], "취소", quantities={self.shirt_line.pk: qty})
                self.assertFalse(result)
                self.assertIn("1~3개", result.message)
        self.assertEqual(order.items.count(), 2)
        self.reload(self.shirt_line)
        self.assertEqual(self.shirt_line.ct_qty, 3)

    def test_the_preview_shows_the_split_without_saving_it(self):
        order = self.make_order("입금")
        plan, error = preview_line_change(
            order, [self.shirt_line.pk], "취소", quantities={self.shirt_line.pk: 1}, expected={self.shirt_line.pk: 3}
        )
        self.assertEqual(error, "")
        self.assertEqual((plan.cancel_price, plan.refund, plan.method), (20000, 20000, "manual"))
        self.assertEqual([(split.before, split.moved, split.kept) for split in plan.splits], [(3, 1, 2)])
        self.assertEqual(order.items.count(), 2)
        self.reload(self.shirt_line, self.shirt, order)
        self.assertEqual((self.shirt_line.ct_qty, self.shirt.it_stock_qty, order.od_mod_history), (3, 5, ""))


class ProductCouponPartialQtyTests(PartialQtyBase):
    def add_coupon(self, order, stored, **fields):
        coupon = ShopCoupon.objects.create(user=self.member, cp_subject="셔츠", cp_method=0, cp_target="Q-SHIRT", cp_used="1", **fields)
        log = ShopCouponLog.objects.create(
            cl_id=1, coupon=coupon, cp_id=coupon.cp_id, user=self.member, order=order, od_id=order.od_id, cp_price=stored
        )
        return coupon, log

    def test_a_fixed_coupon_stays_on_the_units_left_and_drops_with_the_last_of_them(self):
        order = self.make_order("주문", paid=0, od_misu=68000)
        _, log = self.add_coupon(order, 2000, cp_price=2000)
        self.assertTrue(change_order_lines(order, [self.shirt_line.pk], "취소", quantities={self.shirt_line.pk: 1}))
        self.reload(order, log)
        self.assertEqual(log.cp_price, 2000)
        self.assertEqual(order_coupon_totals(order).cart_by_line, {self.shirt_line.pk: 2000})
        self.assertEqual((order.od_misu, order_misu(order)), (48000, 48000))

        self.assertTrue(change_order_lines(order, [self.shirt_line.pk], "취소"))
        self.reload(order)
        # cap 10,000 + 3,000 shipping, without the shirt coupon
        self.assertEqual(order_coupon_totals(order).cart, 0)
        self.assertEqual((order.od_misu, order_misu(order)), (13000, 13000))

    def test_a_coupon_judged_on_the_product_total_is_worked_out_again(self):
        # 10% of the shirts (60,000) with a 50,000 minimum: 6,000; after one shirt goes the
        # remaining 40,000 misses the minimum and the coupon drops
        order = self.make_order("입금", paid=64000, od_misu=0)
        coupon, log = self.add_coupon(order, 6000, cp_type=1, cp_price=10, cp_minimum=50000)
        plan, error = preview_line_change(order, [self.shirt_line.pk], "취소", quantities={self.shirt_line.pk: 1})
        self.assertEqual(error, "")
        self.assertEqual((plan.cart_coupon, plan.total, plan.refund), (0, 50000, 14000))
        self.assertTrue(change_order_lines(order, [self.shirt_line.pk], "취소", quantities={self.shirt_line.pk: 1}))
        self.reload(order, log, coupon)
        self.assertEqual((log.cp_price, coupon.cp_used), (0, "1"))
        self.assertEqual((order.od_refund_price, order.od_misu, order_misu(order)), (14000, 0, 0))

    def test_a_percentage_coupon_follows_the_units_left(self):
        order = self.make_order("입금", paid=64000, od_misu=0)
        _, log = self.add_coupon(order, 6000, cp_type=1, cp_price=10)
        self.assertTrue(change_order_lines(order, [self.shirt_line.pk], "취소", quantities={self.shirt_line.pk: 1}))
        self.reload(order, log)
        # 40,000 shirts + 10,000 cap (free shipping, judged before coupons) - 4,000 coupon = 46,000
        self.assertEqual(log.cp_price, 4000)
        self.assertEqual((order.od_send_cost, order.od_refund_price, order_misu(order)), (0, 18000, 0))


class PaidPointPartialQtyTests(PartialQtyBase):
    def completed_order(self):
        order = self.make_order("완료")
        ShopOrderItem.objects.filter(order=order).update(ct_point=100, ct_point_use=True)
        Profile.objects.get_or_create(user=self.member)
        for line in (self.shirt_line, self.cap_line):
            line.refresh_from_db()
            point_ledger.insert_point(
                self.member, 100 * line.ct_qty, f"주문번호 {order.od_id} ({line.ct_id}) 배송완료",
                DELIVERY_POINT_TABLE, line.pk, order.od_id, force=True,
            )
        return order

    def test_returning_one_unit_takes_back_its_share_of_a_paid_purchase_point(self):
        order = self.completed_order()
        self.assertEqual(point_ledger.point_balance(self.member), 400)
        result = change_order_lines(order, [self.shirt_line.pk], "반품", quantities={self.shirt_line.pk: 1})
        self.assertTrue(result, result.message)
        self.reload(order, self.shirt_line)
        split = self.split_line(order)
        self.assertEqual(point_ledger.point_balance(self.member), 300)
        self.assertEqual((self.shirt_line.ct_qty, self.shirt_line.ct_point_use, self.shirt_line.ct_status), (2, True, "완료"))
        self.assertEqual((split.ct_qty, split.ct_point_use, split.ct_status, split.ct_complete_time), (1, False, "반품", None))
        self.assertIn("구매포인트 100점 회수", order.od_mod_history)
        self.assertEqual(order.od_refund_price, 20000)

        # the rest of the shirts later: exactly what they still earned goes back
        self.assertTrue(change_order_lines(order, [self.shirt_line.pk], "반품"))
        self.assertEqual(point_ledger.point_balance(self.member), 100)


@override_settings(**FAKE_TOSS)
class TossPartialQtyTests(PartialQtyBase):
    def partial_reply(self, order):
        return fake_http_response({"orderId": order.od_id, "paymentKey": order.od_tno, "status": "PARTIAL_CANCELED"})

    def test_toss_refunds_only_the_cancelled_units(self):
        order = self.toss_order()
        with patch(URLOPEN, return_value=self.partial_reply(order)) as urlopen:
            result = change_order_lines(
                order, [self.shirt_line.pk], "취소", "1개 품절", quantities={self.shirt_line.pk: 1}, expected={self.shirt_line.pk: 3}
            )
        self.assertTrue(result, result.message)
        self.assertEqual(json.loads(urlopen.call_args.args[0].data), {"cancelReason": "1개 품절", "cancelAmount": 20000})
        self.reload(order, self.shirt_line, self.shirt)
        self.assertEqual((order.od_refund_price, order.od_cancel_price, order.od_misu), (20000, 20000, 0))
        self.assertEqual((self.shirt_line.ct_qty, self.shirt.it_stock_qty), (2, 6))
        self.assertIn("PG 신용카드 부분취소 20,000원", order.od_mod_history)

    def test_a_toss_refusal_puts_the_line_back_together(self):
        order = self.toss_order()
        refusal = http_error(400, b'{"code":"NOT_CANCELABLE_AMOUNT","message":"no"}')
        with patch(URLOPEN, side_effect=refusal):
            result = change_order_lines(order, [self.shirt_line.pk], "취소", quantities={self.shirt_line.pk: 1})
        self.assertFalse(result)
        self.assertIn("아무것도 바꾸지 않았습니다", result.message)
        self.assertEqual(order.items.count(), 2)
        self.reload(self.shirt_line, self.shirt, order)
        self.assertEqual((self.shirt_line.ct_qty, self.shirt.it_stock_qty, order.od_refund_price), (3, 5, 0))

    def test_a_retry_after_a_lost_toss_answer_reuses_the_idempotency_key(self):
        # Toss may have refunded although its answer never came back: the retry must not refund again
        order = self.toss_order()
        form = {"quantities": {self.shirt_line.pk: 1}, "expected": {self.shirt_line.pk: 3}}
        with patch(URLOPEN, side_effect=urllib_error.URLError("timed out")) as lost:
            self.assertFalse(change_order_lines(order, [self.shirt_line.pk], "취소", **form))
        self.assertEqual(order.items.count(), 2)
        with patch(URLOPEN, return_value=self.partial_reply(order)) as retried:
            self.assertTrue(change_order_lines(order, [self.shirt_line.pk], "취소", **form))
        first_key = lost.call_args.args[0].get_header("Idempotency-key")
        self.assertEqual(retried.call_args.args[0].get_header("Idempotency-key"), first_key)

    def test_a_double_submit_of_the_same_form_splits_and_refunds_once(self):
        order = self.toss_order()
        form = {"quantities": {self.shirt_line.pk: 1}, "expected": {self.shirt_line.pk: 3}}
        with patch(URLOPEN, return_value=self.partial_reply(order)) as urlopen:
            self.assertTrue(change_order_lines(order, [self.shirt_line.pk], "취소", **form))
            second = change_order_lines(order, [self.shirt_line.pk], "취소", **form)
        self.assertFalse(second)
        self.assertIn("3개에서 2개로 바뀌었습니다", second.message)
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(order.items.count(), 3)
        self.reload(order, self.shirt)
        self.assertEqual((order.od_refund_price, self.shirt.it_stock_qty), (20000, 6))


class PartialQtyViewTests(PartialQtyBase):
    def url(self, order):
        return reverse("admin:shop_shoporder_lines", args=[order.pk])

    def test_the_line_page_previews_and_applies_a_partial_quantity(self):
        order = self.make_order("입금")
        page = self.client.get(self.url(order))
        self.assertContains(page, f'name="ct_qty_{self.shirt_line.pk}"')
        self.assertNotContains(page, f'name="ct_qty_{self.cap_line.pk}"')  # a single unit has nothing to split
        form = {
            "ct_chk": [self.shirt_line.pk],
            "ct_status": "취소",
            f"ct_qty_{self.shirt_line.pk}": "1",
            f"ct_cur_{self.shirt_line.pk}": "3",
        }
        preview = self.client.post(self.url(order), {**form, "step": "preview"})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.context["plan"].refund, 20000)
        self.assertContains(preview, "3개 중 1개를 취소 처리하고 2개는 그대로 둡니다")
        self.assertEqual(order.items.count(), 2)

        applied = self.client.post(self.url(order), {**form, "step": "apply"})
        self.assertRedirects(applied, reverse("admin:shop_shoporder_change", args=[order.pk]), fetch_redirect_response=False)
        self.reload(self.shirt_line, order)
        self.assertEqual((self.shirt_line.ct_qty, order.od_refund_price), (2, 20000))

        again = self.client.post(self.url(order), {**form, "step": "apply"})
        self.assertEqual(again.status_code, 200)
        self.assertIn("3개에서 2개로 바뀌었습니다", again.context["error"])
        self.assertEqual(order.items.count(), 3)

    def test_a_quantity_that_is_not_a_number_is_refused(self):
        order = self.make_order("입금")
        response = self.client.post(
            self.url(order),
            {"ct_chk": [self.shirt_line.pk], "ct_status": "취소", f"ct_qty_{self.shirt_line.pk}": "x", "step": "apply"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("숫자로 입력", response.context["error"])
        self.assertEqual(order.items.count(), 2)
