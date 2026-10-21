"""Cash receipts asked for after the order (youngcart shop/taxsave.php): the customer's request
from the order page (member owner or guest with the order's uid), issuance through the Toss cash
receipt API or as a request issued by hand, the admin's cash receipt page, and the cancellation
when the order is cancelled or returned."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from gnu_jango.config.models import Config
from gnu_jango.core.test_shop_payments_api import FAKE_TOSS, fake_http_response, http_error
from gnu_jango.shop import cash_receipts
from gnu_jango.shop.admin.orders import set_order_status
from gnu_jango.shop.models import ShopOrder, ShopOrderData, ShopOrderItem, ShopProduct, ShopShippingPolicy
from gnu_jango.shop.order_lines import change_order_lines

URLOPEN = "gnu_jango.api.shop_payments.urllib_request.urlopen"
PHONE = "010-1234-5678"
NO_TOSS = {"SHOP_TOSS_CLIENT_KEY": "", "SHOP_TOSS_SECRET_KEY": ""}


def toss_receipt(order_id, **fields):
    return {
        "receiptKey": "rk_cash_1",
        "issueNumber": "CR-100",
        "receiptUrl": "https://dashboard.tosspayments.com/receipt/cash-receipt/rk_cash_1",
        "orderId": order_id,
        "amount": 50000,
        "type": "소득공제",
        "issueStatus": "COMPLETED",
        "transactionType": "CONFIRM",
        "customerIdentityNumber": "01012345678",
        **fields,
    }


class CashReceiptBase(TestCase):
    """Order YC-C: one 50,000 line paid by bank deposit (입금)."""

    def setUp(self):
        cache.clear()
        user_model = get_user_model()
        self.member = user_model.objects.create_user(username="cash-member", email="cash@example.test", password="pw")
        self.other = user_model.objects.create_user(username="cash-other", email="other@example.test", password="pw")
        self.api = APIClient()
        self.api.force_authenticate(self.member)
        self.product = ShopProduct.objects.create(it_id="C-ITEM", it_name="Coat", it_price=50000, it_use="1", it_stock_qty=5)
        ShopShippingPolicy.objects.update_or_create(pk=1, defaults={"de_send_cost_case": "무료"})

    def make_order(self, od_id="YC-C", *, user="member", status="입금", settle_case="무통장", paid=50000, **fields):
        order = ShopOrder.objects.create(
            od_id=od_id,
            user=self.member if user == "member" else user,
            od_name="Buyer",
            od_status=status,
            od_settle_case=settle_case,
            od_cart_price=50000,
            od_receipt_price=paid,
            od_misu=50000 - paid,
            **fields,
        )
        ShopOrderItem.objects.create(
            order=order, product=self.product, ct_id=f"{od_id}-1", it_id="C-ITEM", it_name="Coat",
            ct_price=50000, ct_qty=1, ct_status=status, stock_adjusted=True,
        )
        return order

    def url(self, order):
        return f"/api/v1/shop/orders/{order.od_id}/cash-receipt"

    def ask(self, order, client=None, **fields):
        body = {"od_cash_type": "income", "cash_receipt_registration_number": PHONE, **fields}
        return (client or self.api).post(self.url(order), body, format="json")

    def reload(self, *objects):
        for obj in objects:
            obj.refresh_from_db()


@override_settings(**FAKE_TOSS)
class TossIssueTests(CashReceiptBase):
    def test_a_paid_bank_order_gets_a_toss_cash_receipt_and_the_number_is_not_stored(self):
        order = self.make_order()
        with patch(URLOPEN, return_value=fake_http_response(toss_receipt(order.od_id))) as urlopen:
            response = self.ask(order)
        self.assertEqual(response.status_code, 200, response.content[:300])
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.tosspayments.com/v1/cash-receipts")
        self.assertEqual(
            json.loads(request.data),
            {"amount": 50000, "orderId": "YC-C", "orderName": "Coat", "customerIdentityNumber": "01012345678", "type": "소득공제"},
        )
        self.assertTrue(request.get_header("Idempotency-key").startswith("cash-receipt-YC-C-"))
        self.reload(order)
        self.assertEqual((order.od_cash_request, order.od_cash_type, order.od_cash_no), (True, "income", "CR-100"))
        self.assertEqual(order.od_cash_res, "https://dashboard.tosspayments.com/receipt/cash-receipt/rk_cash_1")
        self.assertIn("현금영수증 발급 (토스페이먼츠, 소득공제) 50,000원 승인번호 CR-100", order.od_mod_history)
        stored = json.dumps(list(ShopOrder.objects.filter(pk=order.pk).values()), default=str)
        stored += "".join(ShopOrderData.objects.filter(od_id=order.od_id).values_list("dt_data", flat=True))
        self.assertNotIn("01012345678", stored)
        self.assertIn("rk_cash_1", stored)  # kept for the cancellation
        data = response.json()["data"]
        self.assertTrue(data["issued"])
        self.assertEqual(data["order"]["cash_receipt"]["state"], "issued")
        self.assertEqual(data["order"]["cash_receipt_url"], order.od_cash_res)
        self.assertEqual(data["order"]["cash_receipt_issue_url"], "")

    def test_the_amount_is_the_cash_paid_less_refunds_within_the_tax_split(self):
        order = self.make_order(od_cancel_price=5000, od_refund_price=5000, od_tax_mny=30000, od_vat_mny=3000, od_free_mny=12000)
        self.assertEqual(cash_receipts.receipt_amounts(order), (45000, 12000))
        with patch(URLOPEN, return_value=fake_http_response(toss_receipt(order.od_id, amount=45000))) as urlopen:
            self.assertEqual(self.ask(order, od_cash_type="expense", cash_receipt_registration_number="123-45-67890").status_code, 200)
        body = json.loads(urlopen.call_args.args[0].data)
        self.assertEqual((body["amount"], body["taxFreeAmount"], body["type"]), (45000, 12000, "지출증빙"))
        self.assertEqual(body["customerIdentityNumber"], "1234567890")

    def test_a_toss_transfer_order_is_issued_through_toss_and_another_pg_is_left_for_the_admin(self):
        transfer = self.make_order("YC-T", settle_case="계좌이체", od_pg="toss", od_tno="tpk_t")
        with patch(URLOPEN, return_value=fake_http_response(toss_receipt("YC-T"))) as urlopen:
            self.assertEqual(self.ask(transfer).status_code, 200)
        urlopen.assert_called_once()
        other_pg = self.make_order("YC-V", settle_case="가상계좌", od_pg="inicis", od_tno="ini_1")
        with patch(URLOPEN) as urlopen:
            response = self.ask(other_pg)
        urlopen.assert_not_called()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["issued"])
        self.assertEqual(cash_receipts.pending_request(other_pg)["identity"], "01012345678")

    def test_a_toss_refusal_stores_nothing(self):
        order = self.make_order()
        refusal = http_error(400, '{"code":"INVALID_IDENTITY_NUMBER","message":"식별번호 오류"}'.encode())
        with patch(URLOPEN, side_effect=refusal):
            response = self.ask(order)
        self.assertEqual(response.status_code, 502)
        self.assertIn("INVALID_IDENTITY_NUMBER", response.json()["message"])
        self.reload(order)
        self.assertEqual((order.od_cash_request, order.od_cash_no, order.od_mod_history), (False, "", ""))

    def test_a_second_request_finds_the_receipt_issued(self):
        order = self.make_order()
        with patch(URLOPEN, return_value=fake_http_response(toss_receipt(order.od_id))) as urlopen:
            self.assertEqual(self.ask(order).status_code, 200)
            again = self.ask(order)
        self.assertEqual(again.status_code, 400)
        self.assertIn("이미 현금영수증이 발급", again.json()["message"])
        self.assertEqual(urlopen.call_count, 1)


@override_settings(**NO_TOSS)
class ManualRequestTests(CashReceiptBase):
    def test_without_toss_the_request_is_kept_for_the_admin(self):
        order = self.make_order()
        response = self.ask(order)
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertFalse(response.json()["data"]["issued"])
        self.assertEqual(response.json()["data"]["order"]["cash_receipt"]["state"], "requested")
        self.reload(order)
        self.assertEqual((order.od_cash_request, order.od_cash_no), (True, ""))
        self.assertIn("현금영수증 요청 (수동 발급, 소득공제, 고객 신청)", order.od_mod_history)
        self.assertEqual(cash_receipts.admin_risk(order)["label"], "현금영수증 요청 (수동 발급)")
        again = self.ask(order)
        self.assertEqual(again.status_code, 400)
        self.assertIn("이미 현금영수증 발급을 신청", again.json()["message"])

    def test_the_order_page_offers_the_request_only_where_youngcart_does(self):
        eligible = self.make_order()
        card = self.make_order("YC-CARD", settle_case="신용카드", od_pg="toss", od_tno="tpk_c")
        unpaid = self.make_order("YC-UNPAID", status="주문", paid=0)
        payload = self.api.get(f"/api/v1/shop/orders/{eligible.od_id}").json()["data"]
        self.assertTrue(payload["cash_receipt"]["can_request"])
        self.assertEqual(payload["cash_receipt_issue_url"], "/api/v1/shop/orders/YC-C/cash-receipt")
        self.assertEqual(payload["cash_receipt"]["amount"], 50000)
        for order in (card, unpaid):
            with self.subTest(order=order.od_id):
                data = self.api.get(f"/api/v1/shop/orders/{order.od_id}").json()["data"]
                self.assertFalse(data["cash_receipt"]["can_request"])
                self.assertEqual(data["cash_receipt_issue_url"], "")
                self.assertEqual(self.ask(order).status_code, 400)
        # the order list stays light: no receipt state there
        listed = self.api.get("/api/v1/shop/orders").json()["data"]
        self.assertTrue(all(row["cash_receipt"] is None for row in listed))

    def test_shop_settings_and_identification_numbers_are_checked(self):
        order = self.make_order()
        for fields in (
            {"cash_receipt_registration_number": "1234"},
            {"od_cash_type": "expense", "cash_receipt_registration_number": PHONE},
            {"od_cash_type": "gift"},
        ):
            with self.subTest(fields=fields):
                self.assertEqual(self.ask(order, **fields).status_code, 400)
        Config.objects.update_or_create(name="de_taxsave_types", defaults={"value": "vbank,transfer"})
        response = self.ask(order)
        self.assertEqual(response.status_code, 400)
        self.assertIn("현금영수증 발급을 받지 않습니다", response.json()["message"])
        self.reload(order)
        self.assertFalse(order.od_cash_request)

    def test_only_the_owner_may_ask(self):
        order = self.make_order()
        stranger = APIClient()
        stranger.force_authenticate(self.other)
        self.assertEqual(self.ask(order, client=stranger).status_code, 404)
        self.assertEqual(self.ask(order, client=APIClient(), uid=order.uid).status_code, 404)  # a member's order
        guest = self.make_order("YC-G", user=None)
        anonymous = APIClient()
        self.assertEqual(self.ask(guest, client=anonymous).status_code, 404)
        self.assertEqual(self.ask(guest, client=anonymous, uid="wrong").status_code, 404)
        self.assertEqual(self.ask(guest, client=stranger, uid="").status_code, 404)
        response = anonymous.post(f"{self.url(guest)}?uid={guest.uid}", {"od_cash_type": "income", "cash_receipt_registration_number": PHONE}, format="json")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertTrue(ShopOrder.objects.get(pk=guest.pk).od_cash_request)
        self.assertEqual(self.ask(ShopOrder(od_id="NOPE")).status_code, 404)

    def test_requests_are_throttled(self):
        order = self.make_order(status="주문", paid=0)
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"shop-cash-receipt": "2/min"}):
            codes = [self.ask(order).status_code for _ in range(3)]
        self.assertEqual(codes, [400, 400, 429])


class AdminCashReceiptTests(CashReceiptBase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser(username="cash-admin", email="a@example.test", password="pw")
        self.client.force_login(self.admin)

    def page(self, order):
        return reverse("admin:shop_shoporder_cash_receipt", args=[order.pk])

    @override_settings(**NO_TOSS)
    def test_the_admin_sees_a_manual_request_and_records_the_issued_number(self):
        order = self.make_order()
        self.assertEqual(self.ask(order).status_code, 200)
        change_page = self.client.get(reverse("admin:shop_shoporder_change", args=[order.pk])).content.decode()
        self.assertIn(self.page(order), change_page)
        self.assertIn("현금영수증 요청 (수동 발급)", change_page)
        page = self.client.get(self.page(order))
        self.assertContains(page, "현금영수증 요청 (수동 발급)")
        self.assertContains(page, 'value="01012345678"')  # the admin needs it to issue
        response = self.client.post(self.page(order), {"action": "mark_issued", "cash_no": "HT-777", "receipt_url": "https://hometax.example/r"})
        self.assertRedirects(response, self.page(order), fetch_redirect_response=False)
        self.reload(order)
        self.assertEqual((order.od_cash_no, order.od_cash_res), ("HT-777", "https://hometax.example/r"))
        self.assertIsNone(cash_receipts.pending_request(order))  # the number is gone with the request
        self.assertIn("현금영수증 발급 등록 (수동) 승인번호 HT-777", order.od_mod_history)
        payload = self.api.get(f"/api/v1/shop/orders/{order.od_id}").json()["data"]
        self.assertEqual((payload["cash_receipt"]["state"], payload["od_cash_no"]), ("issued", "HT-777"))

    @override_settings(**FAKE_TOSS)
    def test_the_admin_issues_through_toss_even_when_customers_cannot_and_cancels_it(self):
        Config.objects.update_or_create(name="de_taxsave_use", defaults={"value": "0"})
        order = self.make_order()
        self.assertEqual(self.ask(order).status_code, 400)
        with patch(URLOPEN, return_value=fake_http_response(toss_receipt(order.od_id))):
            response = self.client.post(self.page(order), {"action": "issue", "cash_type": "income", "identity": PHONE})
        self.assertRedirects(response, self.page(order), fetch_redirect_response=False)
        self.reload(order)
        self.assertEqual(order.od_cash_no, "CR-100")
        self.assertEqual(cash_receipts.issued_kind(order), "toss")

        cancelled = fake_http_response({"receiptKey": "rk_cash_1", "transactionType": "CANCEL"})
        with patch(URLOPEN, return_value=cancelled) as urlopen:
            response = self.client.post(self.page(order), {"action": "cancel", "reason": "번호 오류"})
        self.assertRedirects(response, self.page(order), fetch_redirect_response=False)
        self.assertEqual(urlopen.call_args.args[0].full_url, "https://api.tosspayments.com/v1/cash-receipts/rk_cash_1/cancel")
        self.reload(order)
        self.assertEqual((order.od_cash_no, order.od_cash_res, order.od_cash_request), ("", "", False))
        self.assertIn("현금영수증 취소 승인번호 CR-100 (토스페이먼츠 취소) - 번호 오류", order.od_mod_history)

        # issued again after the cancel: a fresh Toss orderId
        with patch(URLOPEN, return_value=fake_http_response(toss_receipt("YC-C-r1", receiptKey="rk_cash_2", issueNumber="CR-101"))) as urlopen:
            self.client.post(self.page(order), {"action": "issue", "cash_type": "income", "identity": PHONE})
        self.assertEqual(json.loads(urlopen.call_args.args[0].data)["orderId"], "YC-C-r1")
        self.reload(order)
        self.assertEqual(order.od_cash_no, "CR-101")

    @override_settings(**NO_TOSS)
    def test_a_request_can_be_turned_down_and_errors_are_shown(self):
        order = self.make_order()
        self.assertEqual(self.ask(order).status_code, 200)
        self.client.post(self.page(order), {"action": "withdraw", "reason": "사업자번호 확인 불가"})
        self.reload(order)
        self.assertFalse(order.od_cash_request)
        self.assertIsNone(cash_receipts.pending_request(order))
        response = self.client.post(self.page(order), {"action": "mark_issued", "cash_no": "X", "receipt_url": "javascript:alert(1)"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("http:// 또는 https://", response.context["error"])

    def test_the_change_permission_is_required(self):
        order = self.make_order()
        staff = get_user_model().objects.create_user(username="cash-viewer", email="v@example.test", password="pw", is_staff=True)
        staff.user_permissions.add(Permission.objects.get(codename="view_shoporder"))
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.page(order)).status_code, 403)
        self.assertEqual(self.client.post(self.page(order), {"action": "mark_issued", "cash_no": "X"}).status_code, 403)
        self.reload(order)
        self.assertEqual(order.od_cash_no, "")


class CancelledOrderReceiptTests(CashReceiptBase):
    def issued_order(self, **fields):
        order = self.make_order(**fields)
        with patch(URLOPEN, return_value=fake_http_response(toss_receipt(order.od_id))):
            self.assertEqual(self.ask(order).status_code, 200)
        order.refresh_from_db()
        return order

    @override_settings(**FAKE_TOSS)
    def test_cancelling_the_order_cancels_its_toss_receipt(self):
        order = self.issued_order()
        cancelled = fake_http_response({"receiptKey": "rk_cash_1", "transactionType": "CANCEL"})
        with patch(URLOPEN, return_value=cancelled) as urlopen, self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(set_order_status(order, "취소", actor="cash-admin"))
        self.assertEqual(urlopen.call_args.args[0].full_url, "https://api.tosspayments.com/v1/cash-receipts/rk_cash_1/cancel")
        self.reload(order)
        self.assertEqual((order.od_status, order.od_cash_no, order.od_cash_res), ("취소", "", ""))
        self.assertIn("현금영수증 취소 승인번호 CR-100 (토스페이먼츠 취소) - 주문 취소·반품", order.od_mod_history)

    @override_settings(**FAKE_TOSS)
    def test_a_refused_receipt_cancel_is_flagged_for_the_admin(self):
        order = self.issued_order()
        with patch(URLOPEN, side_effect=http_error(500, b"{}")), self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(set_order_status(order, "취소"))
        self.reload(order)
        self.assertEqual((order.od_status, order.od_cash_no), ("취소", "CR-100"))
        self.assertIn("현금영수증 취소 필요 (수동) 승인번호 CR-100", order.od_mod_history)
        self.assertEqual(cash_receipts.admin_risk(order)["label"], "현금영수증 취소 필요")
        self.assertEqual(cash_receipts.receipt_state(order), "cancel_needed")

    @override_settings(**NO_TOSS)
    def test_a_receipt_issued_by_hand_is_flagged_and_a_pending_request_is_dropped(self):
        manual = self.make_order(od_cash_request=True, od_cash_type="income", od_cash_no="HT-1")
        pending = self.make_order("YC-PENDING")
        self.assertEqual(self.ask(pending).status_code, 200)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertTrue(set_order_status(manual, "취소"))
            self.assertTrue(set_order_status(pending, "취소"))
        self.reload(manual, pending)
        self.assertIn("현금영수증 취소 필요 (수동) 승인번호 HT-1", manual.od_mod_history)
        self.assertEqual(manual.od_cash_no, "HT-1")
        self.assertIsNone(cash_receipts.pending_request(pending))
        self.assertIsNone(cash_receipts.admin_risk(pending))

    @override_settings(**FAKE_TOSS)
    def test_a_partial_refund_notes_that_the_receipt_needs_a_correction(self):
        order = self.issued_order()
        line = order.items.get()
        line.ct_qty = 2
        line.save(update_fields=["ct_qty"])
        ShopOrder.objects.filter(pk=order.pk).update(od_cart_price=100000, od_receipt_price=100000)
        order.refresh_from_db()
        with patch(URLOPEN) as urlopen:
            result = change_order_lines(order, [line.pk], "취소", quantities={line.pk: 1})
        urlopen.assert_not_called()
        self.assertTrue(result, result.message)
        self.reload(order)
        self.assertEqual(order.od_refund_price, 50000)
        self.assertIn("현금영수증 금액 조정 필요 (환불 50,000원, 승인번호 CR-100)", order.od_mod_history)
