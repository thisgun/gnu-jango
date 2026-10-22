"""Personal pay checkout (youngcart personalpayform.php / personalpayformupdate.php).

무통장입금 is chosen by the customer and confirmed by the shop admin; Toss is prepared with the
server's amount and confirmed against what Toss approved. No test talks to Toss: toss_api_confirm
and toss_api_cancel_payment are patched.
"""

from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core import mail
from django.test import RequestFactory, override_settings
from rest_framework.test import APIClient

from gnu_jango.config.models import Config
from gnu_jango.core.test_shop_orders_more import API, BANK, ShopOrderBase
from gnu_jango.shop.admin.orders import ShopPersonalPayAdmin
from gnu_jango.shop.models import ShopOrder, ShopOrderData, ShopPersonalPay

FAKE_TOSS = {"SHOP_TOSS_CLIENT_KEY": "test_ck_fake_client", "SHOP_TOSS_SECRET_KEY": "test_sk_fake_secret"}
PP_ID = "2026102100000001"
TOSS_ORDER_ID = f"pp-{PP_ID}"


def toss_done(amount=5000, *, order_id=TOSS_ORDER_ID, key="pay-key-1", method="카드", status="DONE"):
    return {
        "orderId": order_id,
        "paymentKey": key,
        "totalAmount": amount,
        "status": status,
        "method": method,
        "approvedAt": "2026-10-21T10:20:30+09:00",
        "card": {"approveNo": "APPROVE-9"},
    }


class PersonalPayCheckoutBase(ShopOrderBase):
    def setUp(self):
        super().setUp()
        self.staff.is_superuser = True
        self.staff.save(update_fields=["is_superuser"])

    def make_pay(self, pp_id=PP_ID, **fields):
        values = {"pp_name": "Customer", "pp_price": 5000, "user": self.member, "pp_email": "pp@example.test"}
        values.update(fields)
        return ShopPersonalPay.objects.create(pp_id=pp_id, **values)

    def bank(self, client=None, pp_id=PP_ID, **fields):
        body = {"bank_account": BANK, "deposit_name": "Depositor", "agree": True, **fields}
        return (client or self.client).post(f"{API}/personalpay/{pp_id}/bank", body, format="json")

    def detail(self, pp_id=PP_ID):
        return self.client.get(f"{API}/personalpay/{pp_id}").json()["data"]

    def code(self, response):
        return response.json().get("code")


class BankDepositCheckoutTests(PersonalPayCheckoutBase):
    def test_choosing_a_bank_account_waits_for_the_deposit(self):
        self.make_pay()

        response = self.bank()

        self.assertEqual(response.status_code, 200, response.content[:300])
        data = response.json()["data"]
        self.assertEqual(data["payment_state"], "awaiting_deposit")
        self.assertEqual((data["pp_settle_case"], data["pp_bank_account"], data["pp_deposit_name"]), ("무통장", BANK, "Depositor"))
        self.assertEqual((data["can_pay"], data["can_change_deposit"], data["already_paid"]), (False, True, False))
        self.assertEqual(ShopPersonalPay.objects.get(pk=PP_ID).pp_receipt_price, 0)

    def test_the_depositor_can_be_corrected_while_waiting(self):
        self.make_pay()
        self.bank()
        response = self.bank(deposit_name="  Other   Name ")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ShopPersonalPay.objects.get(pk=PP_ID).pp_deposit_name, "Other Name")

    def test_the_account_must_be_one_of_the_shop_and_the_form_complete(self):
        self.make_pay()
        cases = (
            {"bank_account": "Fake Bank 999"},
            {"deposit_name": "   "},
            {"deposit_name": "x" * 101},
            {"agree": False},
        )
        for fields in cases:
            with self.subTest(fields=fields):
                response = self.bank(**fields)
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.detail()["payment_state"], "ready")

    def test_without_bank_accounts_the_bank_deposit_is_unavailable(self):
        Config.objects.filter(name="de_bank_use").update(value="0")
        self.make_pay()
        self.assertEqual(self.bank().status_code, 503)

    def test_only_the_owner_may_choose_and_paid_requests_are_closed(self):
        self.make_pay()
        self.assertEqual(self.bank(self.other_client).status_code, 403)
        self.assertEqual(self.bank(APIClient()).status_code, 403)
        self.make_pay("PAID-1", pp_receipt_price=5000)
        response = self.bank(pp_id="PAID-1")
        self.assertEqual((response.status_code, self.code(response)), (409, "personalpay_not_payable"))
        self.make_pay("ZERO-1", pp_price=0)
        self.assertEqual(self.bank(pp_id="ZERO-1").status_code, 409)

    def test_an_online_payment_is_refused_while_a_deposit_is_awaited(self):
        self.make_pay()
        self.bank()
        with override_settings(**FAKE_TOSS):
            response = self.client.post(f"{API}/personalpay/{PP_ID}/toss/prepare", {"method": "card", "agree": True}, format="json")
        self.assertEqual((response.status_code, self.code(response)), (409, "personalpay_not_payable"))
        self.assertEqual(self.client.post(f"{API}/personalpay/{PP_ID}/start").status_code, 409)


class AdminDepositConfirmTests(PersonalPayCheckoutBase):
    def run_action(self, *pp_ids):
        request = RequestFactory().post("/admin/shop/shoppersonalpay/")
        request.user = self.staff
        request.session = {}
        request._messages = FallbackStorage(request)
        admin = ShopPersonalPayAdmin(ShopPersonalPay, AdminSite())
        admin.confirm_selected_bank_deposits(request, ShopPersonalPay.objects.filter(pk__in=pp_ids))
        return [str(message) for message in request._messages]

    def test_the_admin_confirms_the_deposit(self):
        self.make_pay()
        self.bank()

        messages = self.run_action(PP_ID)

        pay = ShopPersonalPay.objects.get(pk=PP_ID)
        self.assertEqual((pay.pp_receipt_price, pay.pp_settle_case), (5000, "무통장"))
        self.assertRegex(pay.pp_receipt_time, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertIn("1건", messages[0])
        self.assertEqual(self.detail()["payment_state"], "paid")

    def test_a_paid_or_gateway_request_is_left_alone(self):
        self.make_pay("PAID-1", pp_receipt_price=5000)
        self.make_pay("TNO-1", pp_tno="T-1")
        messages = self.run_action("PAID-1", "TNO-1")
        self.assertEqual(ShopPersonalPay.objects.get(pk="TNO-1").pp_receipt_price, 0)
        self.assertTrue(any("처리하지 않았습니다" in message for message in messages))

    def test_the_deposit_is_credited_to_the_linked_order(self):
        self.add(self.client)
        order = ShopOrder.objects.get(pk=self.place().json()["data"]["od_id"])
        owed = order.od_misu
        self.assertGreater(owed, 0)
        self.make_pay(order=order, pp_price=owed)
        self.bank()

        with self.captureOnCommitCallbacks(execute=True):
            self.run_action(PP_ID)

        order.refresh_from_db()
        self.assertEqual((order.od_status, order.od_misu, order.od_receipt_price), ("입금", 0, owed))
        self.assertIn(f"개인결제 {PP_ID} 로 결제완료", order.od_shop_memo)
        self.assertTrue(order.items.filter(ct_status="입금").exists())


@override_settings(**FAKE_TOSS)
class TossPersonalPayTests(PersonalPayCheckoutBase):
    def prepare(self, method="card", client=None):
        return (client or self.client).post(
            f"{API}/personalpay/{PP_ID}/toss/prepare", {"method": method, "agree": True}, format="json"
        )

    def confirm(self, *, amount=5000, order_id=TOSS_ORDER_ID, key="pay-key-1", toss=None, client=None):
        toss = toss if toss is not None else toss_done(amount)
        with (
            patch("gnu_jango.api.shop_payments.toss_api_confirm", return_value=(toss, None)) as toss_confirm,
            patch("gnu_jango.api.shop_payments.toss_api_cancel_payment") as toss_cancel,
        ):
            response = (client or self.client).post(
                f"{API}/personalpay/{PP_ID}/toss/confirm",
                {"paymentKey": key, "orderId": order_id, "amount": amount},
                format="json",
            )
        return response, toss_confirm, toss_cancel

    def test_prepare_hands_out_the_server_amount_and_the_request_order_id(self):
        self.make_pay(pp_price=7700)
        data = self.prepare().json()["data"]
        self.assertEqual((data["order_id"], data["amount"], data["pg_service"]), (TOSS_ORDER_ID, 7700, "toss"))
        self.assertEqual(data["client_key"], "test_ck_fake_client")

    def test_prepare_needs_the_keys_an_enabled_method_and_the_agreement(self):
        self.make_pay()
        with override_settings(SHOP_TOSS_CLIENT_KEY="", SHOP_TOSS_SECRET_KEY=""):
            self.assertEqual(self.prepare().status_code, 503)
        Config.objects.create(name="de_hp_use", value="0")
        self.assertEqual(self.prepare("hp").status_code, 400)
        self.assertEqual(self.prepare("vbank").status_code, 400)
        response = self.client.post(f"{API}/personalpay/{PP_ID}/toss/prepare", {"method": "card"}, format="json")
        self.assertEqual(response.status_code, 422)

    def test_a_pp_id_toss_cannot_carry_is_refused(self):
        self.make_pay("bad.id")
        response = self.client.post(f"{API}/personalpay/bad.id/toss/prepare", {"method": "card", "agree": True}, format="json")
        self.assertEqual((response.status_code, self.code(response)), (409, "personalpay_online_unavailable"))

    def test_confirm_records_the_approved_payment(self):
        self.make_pay()

        response, toss_confirm, toss_cancel = self.confirm()

        self.assertEqual(response.status_code, 200, response.content[:400])
        toss_confirm.assert_called_once()
        self.assertEqual(toss_confirm.call_args.args, ("pay-key-1", TOSS_ORDER_ID, 5000))
        toss_cancel.assert_not_called()
        pay = ShopPersonalPay.objects.get(pk=PP_ID)
        self.assertEqual(
            (pay.pp_receipt_price, pay.pp_tno, pay.pp_app_no, pay.pp_pg, pay.pp_settle_case, pay.pp_receipt_time),
            (5000, "pay-key-1", "APPROVE-9", "toss", "신용카드", "2026-10-21 10:20:30"),
        )
        self.assertEqual(response.json()["data"]["payment_state"], "paid")
        self.assertTrue(ShopOrderData.objects.filter(od_id=TOSS_ORDER_ID, dt_pg="toss").exists())

    def test_a_reloaded_success_page_does_not_confirm_twice(self):
        self.make_pay()
        self.confirm()
        response, toss_confirm, _ = self.confirm()
        self.assertEqual(response.status_code, 200)
        toss_confirm.assert_not_called()

    def test_the_client_amount_must_match_before_toss_is_asked(self):
        self.make_pay()
        response, toss_confirm, _ = self.confirm(amount=100)
        self.assertEqual((response.status_code, self.code(response)), (409, "payment_amount_mismatch"))
        toss_confirm.assert_not_called()

    def test_a_foreign_order_id_is_refused(self):
        self.make_pay()
        response, toss_confirm, _ = self.confirm(order_id="20261021000001")
        self.assertEqual((response.status_code, self.code(response)), (409, "toss_order_mismatch"))
        toss_confirm.assert_not_called()

    def test_a_different_approved_amount_is_cancelled_at_toss(self):
        self.make_pay()
        response, _, toss_cancel = self.confirm(toss=toss_done(4000))
        self.assertEqual((response.status_code, self.code(response)), (409, "toss_payment_mismatch"))
        toss_cancel.assert_called_once()
        self.assertEqual(ShopPersonalPay.objects.get(pk=PP_ID).pp_receipt_price, 0)

    def test_a_virtual_account_answer_is_not_recorded(self):
        self.make_pay()
        response, _, toss_cancel = self.confirm(toss=toss_done(status="WAITING_FOR_DEPOSIT", method="가상계좌"))
        self.assertEqual((response.status_code, self.code(response)), (409, "toss_payment_not_done"))
        toss_cancel.assert_called_once()
        self.assertEqual(ShopPersonalPay.objects.get(pk=PP_ID).pp_tno, "")

    def test_a_request_paid_while_toss_approved_is_refunded(self):
        self.make_pay()

        def approve_after_admin_confirmed(*_args, **_kwargs):
            ShopPersonalPay.objects.filter(pk=PP_ID).update(pp_receipt_price=5000)
            return toss_done(), None

        with (
            patch("gnu_jango.api.shop_payments.toss_api_confirm", side_effect=approve_after_admin_confirmed),
            patch("gnu_jango.api.shop_payments.toss_api_cancel_payment") as toss_cancel,
        ):
            response = self.client.post(
                f"{API}/personalpay/{PP_ID}/toss/confirm",
                {"paymentKey": "pay-key-1", "orderId": TOSS_ORDER_ID, "amount": 5000},
                format="json",
            )

        self.assertEqual((response.status_code, self.code(response)), (409, "personalpay_not_payable"))
        toss_cancel.assert_called_once()
        self.assertEqual(ShopPersonalPay.objects.get(pk=PP_ID).pp_tno, "")

    def test_paid_cancelled_and_foreign_requests_cannot_be_confirmed(self):
        self.make_pay(pp_receipt_price=5000, pp_tno="older-key")
        response, toss_confirm, _ = self.confirm()
        self.assertEqual(response.status_code, 409)
        toss_confirm.assert_not_called()
        ShopPersonalPay.objects.filter(pk=PP_ID).update(pp_receipt_price=0, pp_tno="", active=False)
        self.assertEqual(self.confirm()[0].status_code, 404)
        ShopPersonalPay.objects.filter(pk=PP_ID).update(active=True)
        self.assertEqual(self.confirm(client=self.other_client)[0].status_code, 403)

    def test_a_toss_payment_credits_the_linked_order(self):
        self.add(self.client)
        order = ShopOrder.objects.get(pk=self.place().json()["data"]["od_id"])
        self.make_pay(order=order, pp_price=order.od_misu)
        mail.outbox.clear()
        amount = order.od_misu
        with self.captureOnCommitCallbacks(execute=True):
            response, _, _ = self.confirm(amount=amount, toss=toss_done(amount))
        self.assertEqual(response.status_code, 200, response.content[:300])
        order.refresh_from_db()
        self.assertEqual((order.od_status, order.od_misu), ("입금", 0))


class GuestPersonalPayAccessTests(PersonalPayCheckoutBase):
    """A request issued without a member is public by its link (youngcart), but its contact details
    are hidden and changing it needs the payer check."""

    def guest_pay(self, pp_id=PP_ID, **fields):
        return self.make_pay(pp_id, user=None, pp_name="홍길동", pp_hp="010-1234-5678", **fields)

    def test_a_visitor_sees_the_request_without_its_contact_details(self):
        self.guest_pay()
        data = self.guest.get(f"{API}/personalpay/{PP_ID}").json()["data"]
        self.assertEqual((data["pp_name"], data["pp_email"], data["pp_hp"]), ("홍길동", "", ""))
        self.assertEqual((data["pii_masked"], data["payer_check"]), (True, "hp"))
        staff_view = self.staff_client.get(f"{API}/personalpay/{PP_ID}").json()["data"]
        self.assertEqual((staff_view["pp_hp"], staff_view["pii_masked"]), ("010-1234-5678", False))

    def test_the_bank_choice_needs_the_phone_digits(self):
        self.guest_pay()
        missing = self.bank(self.guest)
        self.assertEqual((missing.status_code, self.code(missing)), (403, "payer_check_failed"))
        self.assertIn("끝 4자리", missing.json()["message"])
        wrong = self.bank(self.guest, payer_hp_last4="0000")
        self.assertEqual(wrong.status_code, 403)
        self.assertIn("맞지 않습니다", wrong.json()["message"])
        self.assertEqual(ShopPersonalPay.objects.get(pk=PP_ID).pp_deposit_name, "")

        ok = self.bank(self.guest, payer_hp_last4="5678", deposit_name="홍길동")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(ok.json()["data"]["pp_deposit_name"], "홍*동")
        self.assertEqual(ShopPersonalPay.objects.get(pk=PP_ID).pp_deposit_name, "홍길동")
        # changing the depositor of the waiting request needs the same check
        self.assertEqual(self.bank(self.guest, deposit_name="Someone").status_code, 403)
        self.assertEqual(ShopPersonalPay.objects.get(pk=PP_ID).pp_deposit_name, "홍길동")

    def test_the_email_is_the_check_when_there_is_no_phone(self):
        self.make_pay(user=None, pp_name="Guest", pp_hp="", pp_email="Payer@Example.test")
        self.assertEqual(self.guest.get(f"{API}/personalpay/{PP_ID}").json()["data"]["payer_check"], "email")
        self.assertEqual(self.bank(self.guest, payer_email="other@example.test").status_code, 403)
        self.assertEqual(self.bank(self.guest, payer_email="payer@example.test").status_code, 200)

    def test_a_request_without_contact_details_keeps_its_first_depositor(self):
        self.make_pay(user=None, pp_name="Guest", pp_hp="", pp_email="")
        self.assertEqual(self.bank(self.guest).status_code, 200)
        locked = self.bank(self.guest, deposit_name="Someone else")
        self.assertEqual((locked.status_code, self.code(locked)), (403, "personalpay_deposit_locked"))
        self.assertEqual(ShopPersonalPay.objects.get(pk=PP_ID).pp_deposit_name, "Depositor")
        self.assertFalse(self.guest.get(f"{API}/personalpay/{PP_ID}").json()["data"]["can_change_deposit"])

    @override_settings(**FAKE_TOSS)
    def test_the_toss_prepare_needs_the_check_and_keeps_the_contact_details(self):
        self.guest_pay()
        url = f"{API}/personalpay/{PP_ID}/toss/prepare"
        self.assertEqual(self.guest.post(url, {"method": "card", "agree": True}, format="json").status_code, 403)
        response = self.guest.post(url, {"method": "card", "agree": True, "payer_hp_last4": "5678"}, format="json")
        self.assertEqual(response.status_code, 200)
        data = response.json()["data"]
        self.assertEqual((data["buyer_name"], data["buyer_email"], data["buyer_tel"]), ("홍길동", "", ""))

    def test_lookups_are_throttled_per_address(self):
        from rest_framework.throttling import ScopedRateThrottle

        self.guest_pay()
        with patch.dict(ScopedRateThrottle.THROTTLE_RATES, {"shop-personalpay": "2/min"}):
            codes = [self.guest.get(f"{API}/personalpay/{PP_ID}").status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])


@override_settings(**FAKE_TOSS)
class PersonalPayRefundFailureTests(PersonalPayCheckoutBase):
    def test_a_payment_that_can_neither_be_recorded_nor_cancelled_is_logged_and_reported(self):
        from gnu_jango.api.shop_payments import PaymentCancelError

        self.make_pay()

        def approve_after_admin_confirmed(*_args, **_kwargs):
            ShopPersonalPay.objects.filter(pk=PP_ID).update(pp_receipt_price=5000)
            return toss_done(), None

        with (
            patch("gnu_jango.api.shop_payments.toss_api_confirm", side_effect=approve_after_admin_confirmed),
            patch("gnu_jango.api.shop_payments.toss_api_cancel_payment", side_effect=PaymentCancelError("down")),
        ):
            response = self.client.post(
                f"{API}/personalpay/{PP_ID}/toss/confirm",
                {"paymentKey": "pay-key-1", "orderId": TOSS_ORDER_ID, "amount": 5000},
                format="json",
            )

        self.assertEqual((response.status_code, self.code(response)), (502, "personalpay_refund_failed"))
        self.assertIn(f"쇼핑몰에 결제번호 {PP_ID}로 문의", response.json()["message"])
        log = ShopOrderData.objects.get(log_id__startswith="pp-refund-failed-")
        self.assertEqual(log.od_id, TOSS_ORDER_ID)
        self.assertIn('"pp_id": "2026102100000001"', log.dt_data)
        self.assertIn('"amount": 5000', log.dt_data)

        request = RequestFactory().get("/admin/shop/shoppersonalpay/")
        request.user = self.staff
        request.session = {}
        request._messages = FallbackStorage(request)
        ShopPersonalPayAdmin(ShopPersonalPay, AdminSite()).warn_failed_refunds(request)
        messages = [str(message) for message in request._messages]
        self.assertTrue(any("자동 취소도 하지 못한" in message and TOSS_ORDER_ID in message for message in messages))

    def test_a_returned_order_is_not_credited_by_a_late_deposit(self):
        order = ShopOrder.objects.create(od_id="PP-RETURNED", od_status="반품", od_receipt_price=0, od_misu=0)
        self.make_pay(order=order)
        self.bank()
        from gnu_jango.shop.personal_pay import confirm_bank_deposit

        pay, reason = confirm_bank_deposit(PP_ID, actor="staff")
        self.assertEqual(reason, "")
        order.refresh_from_db()
        self.assertEqual((order.od_status, order.od_receipt_price, order.od_shop_memo), ("반품", 0, ""))


@override_settings(**FAKE_TOSS)
class LinkedOrderBalanceTests(PersonalPayCheckoutBase):
    """A 미수금 request must not pay (or credit) more than its order still owes."""

    def linked_pay(self, extra=0):
        self.add(self.client)
        order = ShopOrder.objects.get(pk=self.place().json()["data"]["od_id"])
        self.make_pay(order=order, pp_price=order.od_misu + extra)
        return order

    def test_bank_choice_and_toss_are_refused_when_the_order_owes_less(self):
        order = self.linked_pay(extra=1000)
        response = self.bank()
        self.assertEqual(response.status_code, 409)
        self.assertIn("남은 결제금액", response.json()["message"])
        self.assertFalse(self.detail()["can_pay"])
        prepare = self.client.post(f"{API}/personalpay/{PP_ID}/toss/prepare", {"method": "card", "agree": True}, format="json")
        self.assertEqual(prepare.status_code, 409)
        with patch("gnu_jango.api.shop_payments.toss_api_confirm") as toss_confirm:
            confirm = self.client.post(
                f"{API}/personalpay/{PP_ID}/toss/confirm",
                {"paymentKey": "pay-key-1", "orderId": TOSS_ORDER_ID, "amount": order.od_misu + 1000},
                format="json",
            )
        self.assertEqual(confirm.status_code, 409)
        toss_confirm.assert_not_called()

    def test_a_deposit_over_the_balance_credits_only_the_balance_and_flags_the_rest(self):
        order = self.linked_pay()
        owed = order.od_misu
        self.assertEqual(self.bank().status_code, 200)
        # the order is partly paid another way while the deposit is on its way
        ShopOrder.objects.filter(pk=order.pk).update(od_receipt_price=order.od_receipt_price + 1000)
        from gnu_jango.shop.personal_pay import confirm_bank_deposit

        with self.captureOnCommitCallbacks(execute=True):
            pay, reason = confirm_bank_deposit(PP_ID, actor="staff")
        self.assertEqual(reason, "")
        self.assertEqual(pay.pp_receipt_price, owed)
        order.refresh_from_db()
        self.assertEqual(order.od_receipt_price, owed)  # 1000 + (owed - 1000), not 1000 + owed
        self.assertEqual(order.od_misu, 0)
        self.assertIn("환불 필요 (수동, 개인결제 초과)", order.od_shop_memo)
        self.assertIn("1,000원", order.od_shop_memo)
        self.assertIn("환불 필요 (수동, 개인결제 초과)", order.od_mod_history)


class PersonalPayAdminAddTests(PersonalPayCheckoutBase):
    def test_a_request_added_by_hand_gets_a_pp_id(self):
        from django.test import Client
        from django.urls import reverse

        admin_client = Client()
        admin_client.force_login(self.staff)
        response = admin_client.post(
            reverse("admin:shop_shoppersonalpay_add"),
            {"pp_name": "수기 고객", "pp_price": "3000", "pp_receipt_price": "0", "active": "on", "pp_cash": "0",
             "pp_time_0": "2026-10-21", "pp_time_1": "10:00:00", "pp_content": "추가 결제"},
        )
        errors = response.context["adminform"].form.errors if response.status_code == 200 else {}
        self.assertIn(response.status_code, {302, 303}, errors)
        pay = ShopPersonalPay.objects.get(pp_name="수기 고객")
        self.assertRegex(pay.pp_id, r"^\d{20}$")
        self.assertFalse(ShopPersonalPay.objects.filter(pk="").exists())
