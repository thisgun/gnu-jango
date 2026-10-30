"""Customer return (반품) and exchange (교환) requests (shop/returns.py, api/shop_returns.py): who may
ask, which lines and until when, the request statuses, the refund through the admin line change
(order_lines.change_locked_order_lines), the stock put back, and the customer's notifications."""

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.config.models import Config
from gnu_jango.core.models import Notification
from gnu_jango.core.test_shop_payments_api import FAKE_TOSS, fake_http_response
from gnu_jango.shop import returns
from gnu_jango.shop.models import (
    ShopOrder,
    ShopOrderItem,
    ShopProduct,
    ShopReturnRequest,
    ShopReturnRequestLine,
    ShopShippingPolicy,
)
from gnu_jango.shop.order_lines import admin_return_order, change_order_lines

URLOPEN = "gnu_jango.api.shop_payments.urllib_request.urlopen"
OD_ID = "YC-R"


def returns_url(od_id=OD_ID, uid=""):
    return f"/api/v1/shop/orders/{od_id}/returns" + (f"?uid={uid}" if uid else "")


def withdraw_url(request_id, od_id=OD_ID, uid=""):
    return f"/api/v1/shop/orders/{od_id}/returns/{request_id}/withdraw" + (f"?uid={uid}" if uid else "")


class ReturnRequestBase(TestCase):
    """Order YC-R: shirt 20,000 × 2 and cap 10,000 × 1 = 50,000, shipped free (the shop's 차등 rule
    charges 3,000 below 50,000), paid by bank deposit and delivered (완료) yesterday."""

    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.member = user_model.objects.create_user(username="buyer", email="buyer@example.test", password="pw")
        self.stranger = user_model.objects.create_user(username="stranger", email="stranger@example.test", password="pw")
        self.shirt = ShopProduct.objects.create(it_id="R-SHIRT", it_name="Shirt", it_price=20000, it_use="1", it_stock_qty=5)
        self.cap = ShopProduct.objects.create(it_id="R-CAP", it_name="Cap", it_price=10000, it_use="1", it_stock_qty=5)
        ShopShippingPolicy.objects.update_or_create(
            pk=1, defaults={"de_send_cost_case": "차등", "de_send_cost_limit": "50000", "de_send_cost_list": "3000"}
        )
        Config.objects.update_or_create(name="cf_email_use", defaults={"value": "1"})
        Config.objects.update_or_create(name="cf_admin_email", defaults={"value": "shop-admin@example.test"})
        self.api = APIClient()
        self.api.force_authenticate(self.member)

    def make_order(self, status="완료", *, user="member", completed_days_ago=1, settle_case="무통장", **fields):
        values = {
            "od_name": "Buyer",
            "od_email": "buyer@example.test",
            "user": self.member if user == "member" else user,
            "od_status": status,
            "od_settle_case": settle_case,
            "od_cart_price": 50000,
            "od_send_cost": 0,
            "od_receipt_price": 50000,
            "od_misu": 0,
            **fields,
        }
        order = ShopOrder.objects.create(od_id=OD_ID, **values)
        self.shirt_line = ShopOrderItem.objects.create(
            order=order, product=self.shirt, ct_id="1", it_id="R-SHIRT", it_name="Shirt",
            ct_price=20000, ct_qty=2, ct_status=status, stock_adjusted=True,
        )
        self.cap_line = ShopOrderItem.objects.create(
            order=order, product=self.cap, ct_id="2", it_id="R-CAP", it_name="Cap",
            ct_price=10000, ct_qty=1, ct_status=status, stock_adjusted=True,
        )
        if status == "완료":
            ShopOrderItem.objects.filter(order=order).update(
                ct_complete_time=timezone.now() - timedelta(days=completed_days_ago)
            )
        return order

    def ask(self, kind="return", reason="defective", lines=None, detail="", client=None, uid=""):
        lines = lines if lines is not None else [{"line_id": self.cap_line.pk, "qty": 1}]
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.api).post(
                returns_url(uid=uid),
                {"kind": kind, "reason": reason, "detail": detail, "lines": lines},
                format="json",
            )

    def open_request(self, **kwargs):
        response = self.ask(**kwargs)
        self.assertEqual(response.status_code, 201, response.content[:400])
        return ShopReturnRequest.objects.get(pk=response.json()["data"]["requests"][0]["id"])

    def run_on_commit(self, callback, *args, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return callback(*args, **kwargs)

    def reload(self, *objects):
        for obj in objects:
            obj.refresh_from_db()


class ReturnEligibilityTests(ReturnRequestBase):
    def test_delivered_lines_within_the_window_can_be_asked_for(self):
        self.make_order("완료", completed_days_ago=6)

        data = self.api.get(returns_url()).json()["data"]

        self.assertTrue(data["enabled"])
        self.assertTrue(data["can_request"])
        self.assertEqual(data["request_days"], 7)
        self.assertEqual(data["return_shipping_fee"], 0)
        self.assertEqual({line["line_id"]: line["eligible"] for line in data["lines"]}, {self.shirt_line.pk: True, self.cap_line.pk: True})
        self.assertTrue(all(line["deadline"] for line in data["lines"]))
        self.assertEqual([reason["value"] for reason in data["reasons"]], ["change_of_mind", "defective", "wrong_item", "other"])
        self.assertEqual(data["requests"], [])

    def test_the_window_counts_from_when_the_line_was_completed(self):
        self.make_order("완료", completed_days_ago=8)

        data = self.api.get(returns_url()).json()["data"]
        self.assertFalse(any(line["eligible"] for line in data["lines"]))
        self.assertIn("신청 기간", data["lines"][0]["block_reason"])
        response = self.ask()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "return_period_ended")

        Config.objects.update_or_create(name="de_return_request_days", defaults={"value": "10"})
        self.assertEqual(self.ask().status_code, 201)

    def test_a_shipped_line_has_no_clock_yet_and_an_unshipped_line_cannot_be_asked_for(self):
        order = self.make_order("배송")
        ShopOrderItem.objects.filter(pk=self.shirt_line.pk).update(ct_status="준비")

        lines = {line["line_id"]: line for line in self.api.get(returns_url()).json()["data"]["lines"]}

        self.assertTrue(lines[self.cap_line.pk]["eligible"])
        self.assertEqual(lines[self.cap_line.pk]["deadline"], "")
        self.assertFalse(lines[self.shirt_line.pk]["eligible"])
        response = self.ask(lines=[{"line_id": self.shirt_line.pk, "qty": 1}])
        self.assertEqual((response.status_code, response.json()["code"]), (400, "return_line_not_eligible"))
        self.assertEqual(order.return_requests.count(), 0)

    def test_a_completed_line_without_its_timestamp_falls_back_to_the_shipment_time(self):
        order = self.make_order("완료")
        ShopOrderItem.objects.filter(order=order).update(ct_complete_time=None)
        order.od_invoice_time = (timezone.localtime() - timedelta(days=9)).strftime("%Y-%m-%d %H:%M:%S")
        order.save(update_fields=["od_invoice_time"])

        data = self.api.get(returns_url()).json()["data"]

        self.assertFalse(any(line["eligible"] for line in data["lines"]))

    def test_a_cancelled_or_returned_line_and_a_closed_order_cannot_be_asked_for(self):
        order = self.make_order("완료")
        self.assertTrue(change_order_lines(order, [self.cap_line.pk], "반품"))
        self.assertEqual(self.ask().json()["code"], "return_line_not_eligible")

        ShopOrder.objects.filter(pk=order.pk).update(od_status="반품")
        data = self.api.get(returns_url()).json()["data"]
        self.assertFalse(data["can_request"])
        self.assertIn("반품", data["block_reason"])

    def test_requests_can_be_switched_off(self):
        self.make_order("완료")
        Config.objects.update_or_create(name="de_return_request_use", defaults={"value": "0"})

        data = self.api.get(returns_url()).json()["data"]
        self.assertFalse(data["enabled"])
        self.assertFalse(data["can_request"])
        response = self.ask()
        self.assertEqual((response.status_code, response.json()["code"]), (400, "return_requests_disabled"))


class ReturnRequestApiTests(ReturnRequestBase):
    def test_a_member_asks_to_return_a_line(self):
        self.make_order("완료")

        response = self.ask(reason="defective", detail="  박음질이 터졌습니다  ")

        self.assertEqual(response.status_code, 201, response.content[:400])
        request = ShopReturnRequest.objects.get()
        self.assertEqual(
            (request.kind, request.status, request.reason, request.detail, request.user),
            ("return", "requested", "defective", "박음질이 터졌습니다", self.member),
        )
        line = request.lines.get()
        self.assertEqual((line.item, line.qty, line.it_name, line.amount, line.is_open), (self.cap_line, 1, "Cap", 10000, True))
        shown = response.json()["data"]["requests"][0]
        self.assertEqual((shown["status"], shown["status_label"], shown["kind_label"], shown["can_withdraw"]), ("requested", "신청", "반품", True))
        self.assertEqual(shown["lines"][0]["line_id"], self.cap_line.pk)
        # the line is held by the open request
        cap = next(line for line in response.json()["data"]["lines"] if line["line_id"] == self.cap_line.pk)
        self.assertFalse(cap["eligible"])
        self.assertEqual(cap["open_request_id"], request.pk)
        # nothing changes on the order until the shop completes it
        self.reload(self.cap_line, self.cap)
        self.assertEqual((self.cap_line.ct_status, self.cap.it_stock_qty), ("완료", 5))

    def test_one_open_request_per_line(self):
        self.make_order("완료")
        self.open_request()

        again = self.ask(kind="exchange")

        self.assertEqual((again.status_code, again.json()["code"]), (400, "return_line_already_requested"))
        self.assertEqual(ShopReturnRequest.objects.count(), 1)
        # the database refuses a second open line too
        with self.assertRaises(IntegrityError), transaction.atomic():
            other = ShopReturnRequest.objects.create(order_id=OD_ID, kind="exchange", reason="other")
            ShopReturnRequestLine.objects.create(request=other, item=self.cap_line, qty=1)

    def test_the_request_is_validated(self):
        self.make_order("완료")
        cases = [
            ({"kind": "swap"}, "invalid_return_kind"),
            ({"reason": "bored"}, "invalid_return_reason"),
            ({"reason": "other", "detail": " "}, "return_detail_required"),
            ({"detail": "x" * 1001}, "return_detail_too_long"),
            ({"lines": []}, "return_lines_required"),
            ({"lines": [{"line_id": "abc", "qty": 1}]}, "invalid_return_lines"),
            ({"lines": "CAP"}, "invalid_return_lines"),
            ({"lines": [{"line_id": 999999, "qty": 1}]}, "return_line_not_found"),
            ({"lines": [{"line_id": "SHIRT", "qty": 3}]}, "invalid_return_quantity"),
            ({"lines": [{"line_id": "SHIRT", "qty": 0}]}, "invalid_return_quantity"),
            ({"lines": [{"line_id": "CAP", "qty": 1}, {"line_id": "CAP", "qty": 1}]}, "invalid_return_lines"),
        ]
        names = {"SHIRT": self.shirt_line.pk, "CAP": self.cap_line.pk}
        for values, code in cases:
            if isinstance(values.get("lines"), list):
                values = {
                    **values,
                    "lines": [{**line, "line_id": names.get(line["line_id"], line["line_id"])} for line in values["lines"]],
                }
            with self.subTest(code=code, values=str(values)[:60]):
                response = self.ask(**values)
                self.assertEqual((response.status_code, response.json().get("code")), (400, code), response.content[:300])
        self.assertEqual(ShopReturnRequest.objects.count(), 0)

    def test_the_customer_withdraws_a_waiting_request_and_may_ask_again(self):
        self.make_order("완료")
        request = self.open_request()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.api.post(withdraw_url(request.pk), format="json")

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.reload(request)
        self.assertEqual(request.status, "withdrawn")
        self.assertIsNotNone(request.closed_at)
        self.assertFalse(request.lines.get().is_open)
        self.assertFalse(response.json()["data"]["requests"][0]["can_withdraw"])
        self.assertEqual(self.ask(kind="exchange").status_code, 201)

    def test_an_approved_request_can_no_longer_be_withdrawn(self):
        self.make_order("완료")
        request = self.open_request()
        self.assertTrue(returns.approve_request(request.pk, actor="admin"))

        response = self.api.post(withdraw_url(request.pk), format="json")

        self.assertEqual((response.status_code, response.json()["code"]), (400, "return_request_not_withdrawable"))
        self.reload(request)
        self.assertEqual(request.status, "approved")

    def test_another_member_cannot_see_or_ask_for_or_withdraw_on_the_order(self):
        self.make_order("완료")
        request = self.open_request()
        other = APIClient()
        other.force_authenticate(self.stranger)

        self.assertEqual(other.get(returns_url()).status_code, 404)
        self.assertEqual(self.ask(client=other).status_code, 404)
        self.assertEqual(other.post(withdraw_url(request.pk), format="json").status_code, 404)
        # nor with the order's uid: a member order is never opened by uid
        order = ShopOrder.objects.get()
        self.assertEqual(other.get(returns_url(uid=order.uid)).status_code, 404)
        self.assertEqual(APIClient().get(returns_url()).status_code, 404)
        self.reload(request)
        self.assertEqual(request.status, "requested")

    def test_a_request_id_of_another_order_is_not_found(self):
        self.make_order("완료")
        own = self.open_request()
        foreign_order = ShopOrder.objects.create(od_id="YC-OTHER", user=self.stranger, od_status="완료")
        foreign = ShopReturnRequest.objects.create(order=foreign_order, kind="return", reason="other")

        response = self.api.post(withdraw_url(foreign.pk), format="json")

        self.assertEqual((response.status_code, response.json()["code"]), (404, "return_request_not_found"))
        self.reload(own, foreign)
        self.assertEqual((own.status, foreign.status), ("requested", "requested"))

    def test_a_guest_asks_with_the_order_uid(self):
        order = self.make_order("완료", user=None)
        guest = APIClient()

        self.assertEqual(guest.get(returns_url()).status_code, 404)
        self.assertEqual(guest.get(returns_url(uid="wrong")).status_code, 404)
        response = self.ask(client=guest, uid=order.uid)

        self.assertEqual(response.status_code, 201, response.content[:300])
        request = ShopReturnRequest.objects.get()
        self.assertIsNone(request.user)
        with self.captureOnCommitCallbacks(execute=True):
            withdrawn = guest.post(withdraw_url(request.pk, uid=order.uid), format="json")
        self.assertEqual(withdrawn.status_code, 200)
        # a guest has no inbox: the mails only
        self.assertFalse(Notification.objects.exists())

    def test_the_order_list_and_detail_show_the_latest_request(self):
        self.make_order("완료")
        self.open_request(kind="exchange")

        row = self.api.get("/api/v1/shop/orders").json()["data"][0]
        detail = self.api.get(f"/api/v1/shop/orders/{OD_ID}").json()["data"]

        self.assertEqual((row["return_request_kind"], row["return_request_status"]), ("exchange", "requested"))
        self.assertEqual(detail["return_request_status"], "requested")


class ReturnRequestWorkflowTests(ReturnRequestBase):
    def test_statuses_move_only_along_the_workflow(self):
        self.make_order("완료")
        request = self.open_request()

        self.assertFalse(returns.complete_request(request.pk, actor="admin"))
        self.assertFalse(returns.reject_request(request.pk, " ", actor="admin"))
        self.assertTrue(returns.approve_request(request.pk, actor="admin"))
        self.assertFalse(returns.approve_request(request.pk, actor="admin"))
        self.reload(request)
        self.assertEqual((request.status, request.processed_by), ("approved", "admin"))
        self.assertIsNotNone(request.approved_at)

        result = returns.reject_request(request.pk, "사용 흔적이 있어 반품할 수 없습니다.", actor="admin")
        self.assertTrue(result, result.message)
        self.reload(request)
        self.assertEqual((request.status, request.reject_reason), ("rejected", "사용 흔적이 있어 반품할 수 없습니다."))
        self.assertFalse(request.lines.get().is_open)
        self.assertFalse(returns.approve_request(request.pk, actor="admin"))
        self.assertFalse(returns.complete_request(request.pk, actor="admin"))
        shown = self.api.get(returns_url()).json()["data"]["requests"][0]
        self.assertEqual((shown["status"], shown["reject_reason"]), ("rejected", "사용 흔적이 있어 반품할 수 없습니다."))

    def test_completing_a_bank_return_returns_the_line_puts_stock_back_and_records_a_manual_refund(self):
        order = self.make_order("완료")
        request = self.open_request()
        returns.approve_request(request.pk, actor="admin")

        result = self.run_on_commit(returns.complete_request, request.pk, actor="admin")

        self.assertTrue(result, result.message)
        self.assertTrue(result.manual_refund)
        self.reload(order, request, self.cap_line, self.shirt_line, self.cap)
        self.assertEqual((self.cap_line.ct_status, self.cap_line.stock_adjusted, self.shirt_line.ct_status), ("반품", False, "완료"))
        self.assertEqual(self.cap.it_stock_qty, 6)
        # 40,000 left: the 3,000 fee comes back, so 7,000 of the 50,000 goes back (as an admin 반품)
        self.assertEqual((order.od_refund_price, order.od_cancel_price, order.od_send_cost, order.od_status), (7000, 10000, 3000, "완료"))
        self.assertIn("무통장 환불 필요 (수동) 7,000원", order.od_mod_history)
        self.assertEqual((request.status, request.refund_amount, request.return_fee), ("completed", 7000, 0))
        self.assertIsNotNone(request.closed_at)
        self.assertFalse(request.lines.get().is_open)
        # completing twice refunds once
        self.assertFalse(returns.complete_request(request.pk, actor="admin"))
        self.reload(order)
        self.assertEqual(order.od_refund_price, 7000)

    @override_settings(**FAKE_TOSS)
    def test_completing_a_card_return_refunds_at_toss_once(self):
        order = self.make_order("완료", settle_case="신용카드", od_pg="toss", od_tno="tpk_ret_1")
        request = self.open_request(lines=[{"line_id": self.shirt_line.pk, "qty": 2}])
        returns.approve_request(request.pk, actor="admin")
        reply = fake_http_response({"orderId": order.od_id, "paymentKey": order.od_tno, "status": "PARTIAL_CANCELED"})

        with patch(URLOPEN, return_value=reply) as urlopen:
            result = self.run_on_commit(returns.complete_request, request.pk, actor="admin")
            again = returns.complete_request(request.pk, actor="admin")

        self.assertTrue(result, result.message)
        self.assertFalse(again)
        self.assertEqual(urlopen.call_count, 1)
        sent = json.loads(urlopen.call_args.args[0].data)
        # 10,000 cap + 3,000 shipping stay: 37,000 goes back at Toss
        self.assertEqual(sent["cancelAmount"], 37000)
        self.assertIn(f"반품 신청 #{request.pk}", sent["cancelReason"])
        self.reload(order, request, self.shirt)
        self.assertEqual((order.od_refund_price, request.refund_amount, self.shirt.it_stock_qty), (37000, 37000, 7))

    def test_a_change_of_mind_return_keeps_the_return_shipping_fee(self):
        order = self.make_order("완료")
        Config.objects.update_or_create(name="de_return_shipping_fee", defaults={"value": "2500"})
        request = self.open_request(reason="change_of_mind")
        returns.approve_request(request.pk, actor="admin")

        result = returns.complete_request(request.pk, actor="admin")

        self.assertTrue(result, result.message)
        self.reload(order, request)
        # 7,000 overpaid less the 2,500 fee; the fee is charged as 추가배송비 so the order adds up
        self.assertEqual((order.od_refund_price, order.od_send_cost2, order.od_misu), (4500, 2500, 0))
        self.assertEqual((request.refund_amount, request.return_fee), (4500, 2500))
        self.assertIn("반품 배송비 2,500원 차감", order.od_mod_history)
        api_order = self.api.get(f"/api/v1/shop/orders/{OD_ID}").json()["data"]
        self.assertEqual(api_order["od_misu_price"], 0)

    def test_the_fee_is_not_kept_for_a_defect_and_never_exceeds_the_refund(self):
        self.make_order("완료")
        Config.objects.update_or_create(name="de_return_shipping_fee", defaults={"value": "2500"})
        self.assertEqual(returns.default_return_fee(ShopReturnRequest(kind="return", reason="defective")), 0)
        self.assertEqual(returns.default_return_fee(ShopReturnRequest(kind="exchange", reason="change_of_mind")), 0)
        request = self.open_request(reason="change_of_mind")
        returns.approve_request(request.pk, actor="admin")

        self.assertTrue(returns.complete_request(request.pk, actor="admin", return_fee=99999))

        self.reload(request)
        self.assertEqual((request.return_fee, request.refund_amount), (7000, 0))

    def test_returning_every_line_closes_the_order_and_keeps_an_earlier_fee(self):
        order = self.make_order("완료")
        Config.objects.update_or_create(name="de_return_shipping_fee", defaults={"value": "2500"})
        first = self.open_request(reason="change_of_mind")
        returns.approve_request(first.pk, actor="admin")
        self.assertTrue(returns.complete_request(first.pk, actor="admin"))
        second = self.open_request(reason="defective", lines=[{"line_id": self.shirt_line.pk, "qty": 2}])
        returns.approve_request(second.pk, actor="admin")

        result = returns.complete_request(second.pk, actor="admin")

        self.assertTrue(result, result.message)
        self.reload(order, second, self.shirt)
        self.assertEqual(order.od_status, "반품")
        # 50,000 paid: 4,500 went back first, the rest less the 2,500 kept fee now
        self.assertEqual((order.od_refund_price, second.refund_amount), (47500, 43000))
        self.assertEqual(self.shirt.it_stock_qty, 7)

    def test_returning_some_units_of_a_line_splits_it(self):
        order = self.make_order("완료")
        request = self.open_request(lines=[{"line_id": self.shirt_line.pk, "qty": 1}])
        returns.approve_request(request.pk, actor="admin")

        result = returns.complete_request(request.pk, actor="admin")

        self.assertTrue(result, result.message)
        self.reload(self.shirt_line, self.shirt, request)
        self.assertEqual((self.shirt_line.ct_qty, self.shirt_line.ct_status), (1, "완료"))
        returned = order.items.get(ct_status="반품")
        self.assertEqual((returned.it_id, returned.ct_qty), ("R-SHIRT", 1))
        self.assertEqual(self.shirt.it_stock_qty, 6)
        # 30,000 left keeps the 3,000 fee: 17,000 of the 50,000 goes back
        self.assertEqual(request.refund_amount, 17000)
        # the unit left may be asked for again
        self.assertEqual(self.ask(lines=[{"line_id": self.shirt_line.pk, "qty": 1}]).status_code, 201)

    def test_a_line_the_shop_already_changed_is_not_returned_twice(self):
        order = self.make_order("완료")
        request = self.open_request()
        returns.approve_request(request.pk, actor="admin")
        # returning the line on the order settles the request (closed as completed) ...
        self.run_on_commit(change_order_lines, order, [self.cap_line.pk], "반품", actor="admin")

        # ... so completing it again refunds nothing
        result = returns.complete_request(request.pk, actor="admin")

        self.assertFalse(result)
        self.reload(order, request, self.cap)
        self.assertEqual((order.od_refund_price, self.cap.it_stock_qty, request.status), (7000, 6, "completed"))

    def test_a_return_the_shop_settles_on_the_order_is_closed_as_completed(self):
        order = self.make_order("완료")
        request = self.open_request()
        mail.outbox.clear()

        self.run_on_commit(change_order_lines, order, [self.cap_line.pk], "반품", actor="admin")

        self.reload(order, request)
        self.assertEqual(request.status, "completed")
        self.assertFalse(request.lines.filter(is_open=True).exists())
        self.assertIn("주문에서 직접 반품 처리", order.od_mod_history)
        self.assertTrue(any(message.to == ["buyer@example.test"] for message in mail.outbox))

    def test_an_exchange_the_shop_settles_as_a_return_is_closed_with_the_reason(self):
        order = self.make_order("완료")
        request = self.open_request(kind="exchange")

        self.assertTrue(self.run_on_commit(admin_return_order, order, actor="admin"))

        self.reload(request)
        self.assertEqual(request.status, "rejected")
        self.assertEqual(request.reject_reason, returns.SETTLED_ON_ORDER_REASON)

    def test_a_request_with_a_line_still_active_stays_open(self):
        order = self.make_order("완료")
        request = self.open_request(lines=[{"line_id": self.cap_line.pk, "qty": 1}, {"line_id": self.shirt_line.pk, "qty": 2}])

        self.run_on_commit(change_order_lines, order, [self.cap_line.pk], "반품", actor="admin")

        self.reload(request)
        self.assertEqual(request.status, "requested")

    @override_settings(**FAKE_TOSS)
    def test_a_refund_made_before_a_failed_line_change_still_counts_on_the_request(self):
        order = self.make_order("완료", settle_case="신용카드", od_pg="toss", od_tno="tpk_ret_2")
        request = self.open_request()
        returns.approve_request(request.pk, actor="admin")
        reply = fake_http_response({"orderId": order.od_id, "paymentKey": order.od_tno, "status": "PARTIAL_CANCELED"})

        with patch(URLOPEN, return_value=reply), patch(
            "gnu_jango.shop.order_lines._apply_plan", side_effect=RuntimeError("boom")
        ):
            failed = returns.complete_request(request.pk, actor="admin")

        self.assertFalse(failed)
        self.reload(order, request)
        self.assertEqual((order.od_refund_price, request.refund_amount, request.status), (7000, 7000, "approved"))
        # the retry refunds nothing more at Toss and the request keeps the 7,000 already paid out
        with patch(URLOPEN, return_value=reply) as urlopen:
            retried = returns.complete_request(request.pk, actor="admin")
        self.assertTrue(retried, retried.message)
        urlopen.assert_not_called()
        self.reload(order, request, self.cap_line)
        self.assertEqual((order.od_refund_price, request.refund_amount, request.status), (7000, 7000, "completed"))
        self.assertEqual(self.cap_line.ct_status, "반품")

    def test_completing_an_exchange_records_the_reshipment_and_keeps_the_lines(self):
        order = self.make_order("완료")
        request = self.open_request(kind="exchange", reason="wrong_item")
        returns.approve_request(request.pk, actor="admin")

        self.assertFalse(returns.complete_request(request.pk, actor="admin", delivery_company="", invoice=""))
        result = returns.complete_request(request.pk, actor="admin", delivery_company="CJ대한통운", invoice="1234-5678")

        self.assertTrue(result, result.message)
        self.reload(order, request, self.cap_line, self.cap)
        self.assertEqual((request.status, request.exchange_delivery_company, request.exchange_invoice), ("completed", "CJ대한통운", "1234-5678"))
        self.assertEqual((self.cap_line.ct_status, self.cap.it_stock_qty, order.od_refund_price), ("완료", 5, 0))
        self.assertIn("교환 신청", order.od_mod_history)
        shown = self.api.get(returns_url()).json()["data"]["requests"][0]
        self.assertTrue(shown["exchange_inquiry_url"].endswith("1234-5678"))


class ReturnNotificationTests(ReturnRequestBase):
    def test_every_status_change_mails_the_customer_and_fills_the_inbox(self):
        self.make_order("완료")
        request = self.open_request()
        self.run_on_commit(returns.approve_request, request.pk, actor="admin")
        self.run_on_commit(returns.complete_request, request.pk, actor="admin")

        customer_subjects = [message.subject for message in mail.outbox if message.to == ["buyer@example.test"]]
        self.assertEqual(len(customer_subjects), 3, customer_subjects)
        self.assertTrue(any("접수" in subject for subject in customer_subjects))
        self.assertTrue(any("승인" in subject for subject in customer_subjects))
        self.assertTrue(any("완료" in subject for subject in customer_subjects))
        # the shop hears of the new request
        self.assertTrue(any(message.to == ["shop-admin@example.test"] for message in mail.outbox))
        notes = list(Notification.objects.filter(user=self.member).order_by("nt_id"))
        self.assertEqual(len(notes), 3)
        self.assertEqual(notes[0].nt_data["href"], f"/shop/orders/{OD_ID}")
        self.assertEqual(notes[-1].nt_data["status"], "completed")

    def test_a_rejection_tells_the_customer_why(self):
        self.make_order("완료")
        request = self.open_request()
        mail.outbox.clear()

        self.run_on_commit(returns.reject_request, request.pk, "수거 불가 지역입니다.", actor="admin")

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("수거 불가 지역입니다.", mail.outbox[0].body)
        self.assertIn("수거 불가 지역입니다.", Notification.objects.filter(user=self.member).latest("nt_id").nt_body)

    def test_no_mail_while_mail_is_switched_off(self):
        self.make_order("완료")
        Config.objects.update_or_create(name="cf_email_use", defaults={"value": "0"})

        self.open_request()

        self.assertEqual(mail.outbox, [])
        self.assertEqual(Notification.objects.filter(user=self.member).count(), 1)


class ReturnRequestAdminTests(ReturnRequestBase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(
            username="return-admin", email="return-admin@example.test", password="password"
        )
        self.client.force_login(self.admin)

    def test_the_list_and_the_request_page_render(self):
        self.make_order("완료")
        request = self.open_request(detail="불량입니다")

        listing = self.client.get(reverse("admin:shop_shopreturnrequest_changelist"), {"status__exact": "requested"})
        page = self.client.get(reverse("admin:shop_shopreturnrequest_change", args=[request.pk]))

        self.assertEqual(listing.status_code, 200)
        self.assertContains(listing, OD_ID)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Cap")
        self.assertContains(page, reverse("admin:shop_shopreturnrequest_process", args=[request.pk, "approve"]))

    def test_approving_asks_for_confirmation_first(self):
        self.make_order("완료")
        request = self.open_request()
        url = reverse("admin:shop_shopreturnrequest_process", args=[request.pk, "approve"])

        confirm = self.client.get(url)
        self.assertEqual(confirm.status_code, 200)
        self.reload(request)
        self.assertEqual(request.status, "requested")

        with self.captureOnCommitCallbacks(execute=True):
            done = self.client.post(url, {"confirm": "1"})
        self.assertRedirects(done, reverse("admin:shop_shopreturnrequest_change", args=[request.pk]), fetch_redirect_response=False)
        self.reload(request)
        self.assertEqual((request.status, request.processed_by), ("approved", "return-admin"))

    def test_the_completion_page_previews_the_refund_and_applies_it(self):
        order = self.make_order("완료")
        Config.objects.update_or_create(name="de_return_shipping_fee", defaults={"value": "1000"})
        request = self.open_request(reason="change_of_mind")
        returns.approve_request(request.pk, actor="admin")
        url = reverse("admin:shop_shopreturnrequest_process", args=[request.pk, "complete"])

        preview = self.client.get(url)
        self.assertContains(preview, "6,000")
        self.assertContains(preview, 'name="return_fee"')

        self.client.post(url, {"confirm": "1", "return_fee": "500"})
        self.reload(order, request)
        self.assertEqual((request.status, request.return_fee, order.od_refund_price), ("completed", 500, 6500))

    def test_rejecting_needs_a_reason(self):
        self.make_order("완료")
        request = self.open_request()
        url = reverse("admin:shop_shopreturnrequest_process", args=[request.pk, "reject"])

        refused = self.client.post(url, {"confirm": "1", "reject_reason": ""})
        self.assertEqual(refused.status_code, 200)
        self.reload(request)
        self.assertEqual(request.status, "requested")

        self.client.post(url, {"confirm": "1", "reject_reason": "기간이 지났습니다."})
        self.reload(request)
        self.assertEqual((request.status, request.reject_reason), ("rejected", "기간이 지났습니다."))

    def test_the_change_permission_is_required(self):
        self.make_order("완료")
        request = self.open_request()
        viewer = get_user_model().objects.create_user(username="viewer", password="pw", is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(codename="view_shopreturnrequest"))
        self.client.force_login(viewer)

        response = self.client.post(
            reverse("admin:shop_shopreturnrequest_process", args=[request.pk, "approve"]), {"confirm": "1"}
        )

        self.assertEqual(response.status_code, 403)
        self.reload(request)
        self.assertEqual(request.status, "requested")

    def test_completing_also_needs_the_order_change_permission(self):
        self.make_order("완료")
        request = self.open_request()
        returns.approve_request(request.pk, actor="admin")
        staff = get_user_model().objects.create_user(username="returns-staff", password="pw", is_staff=True)
        staff.user_permissions.add(
            *Permission.objects.filter(codename__in=["view_shopreturnrequest", "change_shopreturnrequest"])
        )
        self.client.force_login(staff)
        url = reverse("admin:shop_shopreturnrequest_process", args=[request.pk, "complete"])

        self.assertEqual(self.client.post(url, {"confirm": "1"}).status_code, 403)
        page = self.client.get(reverse("admin:shop_shopreturnrequest_change", args=[request.pk]))
        self.assertNotContains(page, url)
        self.assertContains(page, reverse("admin:shop_shopreturnrequest_process", args=[request.pk, "reject"]))
        self.reload(request)
        self.assertEqual(request.status, "approved")
