"""정기구독 (Toss card billing): registration, charging, the scheduler, member changes and the admin.

Toss is never called: gnu_jango.shop.toss_billing is patched, and the keys are fake test keys.
Assertions look at the database (subscription, charges, orders, stock) as well as the responses.
"""

import importlib
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.config.models import Config
from gnu_jango.core.models import Notification
from gnu_jango.shop import subscriptions as service
from gnu_jango.shop.models import (
    ShopBillingCustomer,
    ShopOrder,
    ShopProduct,
    ShopShippingPolicy,
    ShopSubscription,
    ShopSubscriptionCharge,
)
from gnu_jango.shop.toss_billing import TossBillingError

FEATURE_ON = {
    "SHOP_SUBSCRIPTIONS_ENABLED": True,
    "SHOP_TOSS_CLIENT_KEY": "test_ck_fake_client",
    "SHOP_TOSS_SECRET_KEY": "test_sk_fake_secret",
}
START_URL = "/api/v1/shop/subscriptions/start"
AUTH_URL = "/api/v1/shop/subscriptions/billing-auth"
LIST_URL = "/api/v1/shop/subscriptions"
BILLING_KEY = "bk_fake_billing_key_0001"
PRICE = 20000
ADDRESS = {
    "od_b_name": "Sub Member",
    "od_b_hp": "010-1234-5678",
    "od_b_zip": "06236",
    "od_b_addr1": "Seoul",
    "od_b_addr2": "101",
}
ISSUE = "gnu_jango.shop.toss_billing.issue_billing_key"
CHARGE = "gnu_jango.shop.toss_billing.charge_billing_key"
LOOKUP = "gnu_jango.shop.toss_billing.payment_by_order_id"
DELETE = "gnu_jango.shop.toss_billing.delete_billing_key"


def billing_object(customer_key, key=BILLING_KEY):
    return {
        "mId": "tosspayments",
        "customerKey": customer_key,
        "billingKey": key,
        "method": "카드",
        "card": {"issuerCode": "41", "acquirerCode": "41", "number": "43301234****123*", "cardType": "신용", "ownerType": "개인"},
    }


def approved(**kwargs):
    """A charge_billing_key side effect answering like Toss: DONE for the amount asked."""
    def answer(billing_key, **call):
        return {
            "orderId": call["order_id"],
            "paymentKey": f"pay_{call['order_id']}",
            "status": "DONE",
            "method": "카드",
            "totalAmount": call["amount"],
            **kwargs,
        }
    return answer


@override_settings(**FEATURE_ON)
class SubscriptionTestBase(TestCase):
    def setUp(self):
        cache.clear()  # the registration throttle counts per member
        users = get_user_model()
        self.member = users.objects.create_user(username="sub-member", email="sub@example.test", password="pw-unused")
        self.other = users.objects.create_user(username="sub-other", email="other@example.test", password="pw-unused")
        self.product = ShopProduct.objects.create(
            it_id="SUB001", it_name="Coffee beans", it_price=PRICE, it_stock_qty=10, it_use="1",
            it_subscription_use=True, it_subscription_cycles="1w,2w,1m", it_subscription_discount=10,
        )
        # no shared shipping fee: a charge is the goods amount
        ShopShippingPolicy.objects.update_or_create(pk=1, defaults={"de_send_cost_case": ""})
        Config.objects.update_or_create(name="de_subscription_use", defaults={"value": "1"})
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def start(self, client=None, **fields):
        body = {"it_id": self.product.it_id, "qty": 2, "cycle": "2w", **ADDRESS, **fields}
        return (client or self.client).post(START_URL, body, format="json")

    def subscribe(self, *, charge=None):
        """Start and finish a registration with the first charge approved; returns the subscription."""
        registration = self.start().json()["data"]
        with patch(ISSUE, return_value=billing_object(registration["customer_key"])), \
                patch(CHARGE, side_effect=charge or approved()), self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(AUTH_URL, {
                "registration_token": registration["registration_token"],
                "authKey": "auth_fake_1",
                "customerKey": registration["customer_key"],
            }, format="json")
        self.assertEqual(response.status_code, 200, response.content[:500])
        return ShopSubscription.objects.get(pk=registration["subscription_id"]), response

    def run_job(self, today, **patches):
        with patch(CHARGE, **patches) as charge, self.captureOnCommitCallbacks(execute=True):
            summary = service.run_scheduled(today=today, apply=True)
        return summary, charge


class FeatureSwitchTests(SubscriptionTestBase):
    def test_off_by_default_nothing_is_offered_or_reachable(self):
        Config.objects.filter(name="de_subscription_use").delete()

        detail = self.client.get(f"/api/v1/shop/products/{self.product.it_id}").json()["data"]
        self.assertIsNone(detail["subscription"])
        self.assertEqual(self.client.get(LIST_URL).status_code, 404)
        self.assertEqual(self.start().status_code, 404)
        self.assertFalse(service.run_scheduled(apply=True)["enabled"])

    @override_settings(SHOP_SUBSCRIPTIONS_ENABLED=False)
    def test_the_server_switch_wins_over_the_admin_switch(self):
        self.assertFalse(service.feature_enabled())
        self.assertEqual(self.start().status_code, 404)

    def test_on_the_product_detail_offers_its_cycles_and_discounted_price(self):
        offer = self.client.get(f"/api/v1/shop/products/{self.product.it_id}").json()["data"]["subscription"]

        self.assertEqual([cycle["value"] for cycle in offer["cycles"]], ["1w", "2w", "1m"])
        self.assertEqual(offer["discount_rate"], 10)
        self.assertEqual(offer["price"], 18000)

    def test_the_charge_job_is_registered_only_with_the_server_switch(self):
        from gnu_jango.core import scheduled_jobs

        try:
            with override_settings(SHOP_SUBSCRIPTIONS_ENABLED=False):
                self.assertNotIn("charge_shop_subscriptions", importlib.reload(scheduled_jobs).JOB_NAMES)
            with override_settings(SHOP_SUBSCRIPTIONS_ENABLED=True):
                self.assertIn("charge_shop_subscriptions", importlib.reload(scheduled_jobs).JOB_NAMES)
        finally:
            importlib.reload(scheduled_jobs)


class RegistrationTests(SubscriptionTestBase):
    def test_start_opens_a_pending_registration_with_a_random_customer_key(self):
        response = self.start()

        self.assertEqual(response.status_code, 201, response.content[:300])
        data = response.json()["data"]
        sub = ShopSubscription.objects.get(pk=data["subscription_id"])
        self.assertEqual(sub.status, ShopSubscription.STATUS_PENDING)
        self.assertEqual(data["client_key"], "test_ck_fake_client")
        customer_key = ShopBillingCustomer.objects.get(user=self.member).customer_key
        self.assertEqual(data["customer_key"], customer_key)
        self.assertNotIn(self.member.username, customer_key)
        self.assertNotIn(str(self.member.pk), customer_key.split("_"))
        self.assertTrue(22 <= len(customer_key) <= 50)
        self.assertNotIn(data["registration_token"], sub.auth_token_hash)
        self.assertEqual(sub.billing_key_sealed, "")

    def test_start_refuses_a_cycle_the_product_does_not_offer_and_missing_stock(self):
        self.assertEqual(self.start(cycle="4w").status_code, 422)
        self.assertEqual(self.start(qty=11).status_code, 409)
        self.assertEqual(self.start(od_b_addr1="").status_code, 422)
        self.assertFalse(ShopSubscription.objects.exists())

    def test_guests_cannot_start(self):
        self.assertEqual(self.start(client=APIClient()).status_code, 401)

    def test_widget_keys_cannot_be_used_for_billing(self):
        with override_settings(SHOP_TOSS_CLIENT_KEY="test_gck_widget", SHOP_TOSS_SECRET_KEY="test_gsk_widget"):
            self.assertEqual(self.start().status_code, 503)

    def test_success_issues_a_sealed_billing_key_and_charges_the_first_cycle(self):
        sub, response = self.subscribe()

        payload = response.json()["data"]
        self.assertNotIn(BILLING_KEY, response.content.decode())
        self.assertNotIn(BILLING_KEY, sub.billing_key_sealed)
        self.assertEqual(service.billing_key(sub), BILLING_KEY)
        self.assertEqual(sub.status, ShopSubscription.STATUS_ACTIVE)
        self.assertEqual((sub.card_company, sub.card_number), ("신한", "43301234****123*"))
        self.assertEqual(payload["charge_status"], "charged")
        order = ShopOrder.objects.get(pk=payload["order_id"])
        # 2 x (20,000 less 10%), a normal paid card order of the member
        self.assertEqual(order.od_status, "입금")
        self.assertEqual(order.od_receipt_price, 36000)
        self.assertEqual((order.od_pg, order.od_tno, order.od_settle_case), ("toss", f"pay_{order.od_id}", "신용카드"))
        self.assertEqual(order.od_test, "1")
        self.assertEqual(order.user, self.member)
        self.assertEqual(order.items.get().ct_qty, 2)
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 8)
        charge = sub.charges.get()
        self.assertEqual((charge.status, charge.order_id, charge.amount), ("done", order.od_id, 36000))
        self.assertEqual(sub.cycle_no, 2)
        self.assertEqual(sub.next_charge_date, timezone.localdate() + timedelta(weeks=2))
        self.assertTrue(Notification.objects.filter(user=self.member, nt_type="subscription").exists())
        self.assertTrue(any("정기구독 결제가 완료" in message.subject for message in mail.outbox))

    def test_the_server_computes_the_amount_whatever_the_browser_sends(self):
        sub, response = self.subscribe()
        self.assertEqual(sub.charges.get().amount, 36000)

        other = self.start(amount=10, it_price=1).json()["data"]
        self.assertEqual(ShopSubscription.objects.get(pk=other["subscription_id"]).qty, 2)

    def test_a_registration_token_works_once_and_only_for_its_member(self):
        registration = self.start().json()["data"]
        body = {"registration_token": registration["registration_token"], "authKey": "a", "customerKey": registration["customer_key"]}
        stranger = APIClient()
        stranger.force_authenticate(user=self.other)
        with patch(ISSUE) as issue:
            self.assertEqual(stranger.post(AUTH_URL, body, format="json").status_code, 404)
            issue.assert_not_called()

        with patch(ISSUE, return_value=billing_object(registration["customer_key"])), patch(CHARGE, side_effect=approved()):
            self.assertEqual(self.client.post(AUTH_URL, body, format="json").status_code, 200)
        with patch(ISSUE) as issue:
            self.assertEqual(self.client.post(AUTH_URL, body, format="json").status_code, 404)
            issue.assert_not_called()

    def test_a_customer_key_that_is_not_the_registrations_is_refused_before_toss(self):
        registration = self.start().json()["data"]
        with patch(ISSUE) as issue:
            response = self.client.post(AUTH_URL, {
                "registration_token": registration["registration_token"], "authKey": "a", "customerKey": "gj_someone_else_key_123",
            }, format="json")
        self.assertEqual(response.status_code, 409)
        issue.assert_not_called()

    def test_an_expired_registration_is_refused(self):
        registration = self.start().json()["data"]
        ShopSubscription.objects.filter(pk=registration["subscription_id"]).update(
            auth_expires_at=timezone.now() - timedelta(minutes=1)
        )
        with patch(ISSUE) as issue:
            response = self.client.post(AUTH_URL, {
                "registration_token": registration["registration_token"], "authKey": "a", "customerKey": registration["customer_key"],
            }, format="json")
        self.assertEqual(response.status_code, 404)
        issue.assert_not_called()

    def test_a_declined_first_charge_does_not_start_the_subscription(self):
        registration = self.start().json()["data"]
        declined = TossBillingError("한도초과 또는 잔액부족으로 결제에 실패했습니다.", code="REJECT_CARD_PAYMENT", status=403)
        with patch(ISSUE, return_value=billing_object(registration["customer_key"])), patch(CHARGE, side_effect=declined), \
                patch(DELETE) as delete, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(AUTH_URL, {
                "registration_token": registration["registration_token"], "authKey": "a", "customerKey": registration["customer_key"],
            }, format="json")

        self.assertEqual(response.status_code, 402)
        sub = ShopSubscription.objects.get(pk=registration["subscription_id"])
        self.assertEqual(sub.status, ShopSubscription.STATUS_CANCELLED)
        self.assertEqual(sub.billing_key_sealed, "")
        delete.assert_called_once_with(BILLING_KEY, mode="1")
        order = sub.charges.get().order
        self.assertEqual(order.od_status, "취소")
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 10)

    def test_a_card_registration_the_toss_refused_leaves_nothing_charged(self):
        registration = self.start().json()["data"]
        with patch(ISSUE, side_effect=TossBillingError("카드 정보를 다시 확인해주세요.", code="INVALID_CARD_NUMBER", status=400)), \
                patch(CHARGE) as charge:
            response = self.client.post(AUTH_URL, {
                "registration_token": registration["registration_token"], "authKey": "a", "customerKey": registration["customer_key"],
            }, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"]["provider_code"], "INVALID_CARD_NUMBER")
        charge.assert_not_called()
        self.assertFalse(ShopOrder.objects.exists())

    def test_changing_the_card_replaces_the_key_and_drops_the_old_one(self):
        sub, _ = self.subscribe()
        registration = self.client.post(f"{LIST_URL}/{sub.pk}/card", {}, format="json").json()["data"]
        new_billing = {**billing_object(registration["customer_key"], key="bk_new_key"), "card": {"issuerCode": "11", "number": "53****"}}
        with patch(ISSUE, return_value=new_billing), patch(CHARGE) as charge, patch(DELETE) as delete, \
                self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(AUTH_URL, {
                "registration_token": registration["registration_token"], "authKey": "b", "customerKey": registration["customer_key"],
            }, format="json")

        self.assertEqual(response.status_code, 200, response.content[:300])
        sub.refresh_from_db()
        self.assertEqual(service.billing_key(sub), "bk_new_key")
        self.assertEqual(sub.card_company, "국민")
        delete.assert_called_once_with(BILLING_KEY, mode="1")
        charge.assert_not_called()


class SchedulerTests(SubscriptionTestBase):
    def test_only_due_active_subscriptions_are_charged(self):
        sub, _ = self.subscribe()
        later = ShopSubscription.objects.get(pk=self.subscribe()[0].pk)
        ShopSubscription.objects.filter(pk=later.pk).update(next_charge_date=timezone.localdate() + timedelta(days=30))
        due_day = sub.next_charge_date

        summary, charge = self.run_job(due_day, side_effect=approved())

        self.assertEqual((summary["due"], summary["charged"]), (1, 1))
        self.assertEqual(charge.call_count, 1)
        sub.refresh_from_db()
        self.assertEqual(sub.cycle_no, 3)
        self.assertEqual(sub.next_charge_date, due_day + timedelta(weeks=2))

    def test_a_rerun_or_a_second_runner_never_charges_a_cycle_twice(self):
        sub, _ = self.subscribe()
        due_day = sub.next_charge_date
        self.run_job(due_day, side_effect=approved())
        summary, charge = self.run_job(due_day, side_effect=approved())
        self.assertEqual(summary["due"], 0)
        charge.assert_not_called()

        # a runner that read the subscription before the first one finished finds the cycle taken
        ShopSubscription.objects.filter(pk=sub.pk).update(cycle_no=2, next_charge_date=due_day)
        with patch(CHARGE) as charge:
            self.assertEqual(service.charge_subscription(sub.pk, today=due_day).status, "already")
        charge.assert_not_called()

    def test_the_database_allows_one_open_charge_per_cycle(self):
        sub, _ = self.subscribe()
        done = sub.charges.get()
        with self.assertRaises(IntegrityError), transaction.atomic():
            ShopSubscriptionCharge.objects.create(
                subscription=sub, cycle_no=done.cycle_no, attempt=2, scheduled_date=done.scheduled_date,
                status="pending", idempotency_key="another-key",
            )

    def test_each_attempt_has_its_own_idempotency_key(self):
        sub, _ = self.subscribe()
        declined = TossBillingError("거절", code="REJECT_CARD_PAYMENT", status=403)
        day = sub.next_charge_date
        self.run_job(day, side_effect=declined)
        _, charge = self.run_job(day + timedelta(days=1), side_effect=approved())

        keys = list(sub.charges.values_list("idempotency_key", flat=True))
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(charge.call_args.kwargs["idempotency_key"], sub.charges.get(status="done", cycle_no=2).idempotency_key)

    def test_failures_retry_the_next_day_then_pause_and_tell_the_member(self):
        sub, _ = self.subscribe()
        declined = TossBillingError("한도초과", code="REJECT_CARD_PAYMENT", status=403)
        day = sub.next_charge_date
        for offset in range(3):
            summary, _ = self.run_job(day + timedelta(days=offset), side_effect=declined)
            self.assertEqual(summary["failed"], 1)
            sub.refresh_from_db()
            if offset < 2:
                self.assertEqual(sub.retry_date, day + timedelta(days=offset + 1))
                self.assertEqual(sub.status, ShopSubscription.STATUS_ACTIVE)

        self.assertEqual((sub.status, sub.pause_reason), (ShopSubscription.STATUS_PAUSED, ShopSubscription.PAUSE_PAYMENT))
        self.assertEqual(sub.charges.filter(status="failed").count(), 3)
        # every failed charge's order was cancelled and its stock put back
        self.assertEqual(ShopOrder.objects.filter(od_status="취소").count(), 3)
        self.product.refresh_from_db()
        self.assertEqual(self.product.it_stock_qty, 8)
        self.assertTrue(Notification.objects.filter(user=self.member, nt_title__contains="일시정지").exists())
        summary, charge = self.run_job(day + timedelta(days=3), side_effect=approved())
        charge.assert_not_called()

    def test_the_admin_retry_charges_a_payment_paused_subscription(self):
        sub, _ = self.subscribe()
        ShopSubscription.objects.filter(pk=sub.pk).update(status="paused", pause_reason="payment_failed", failure_count=3)
        with patch(CHARGE, side_effect=approved()), self.captureOnCommitCallbacks(execute=True):
            result = service.admin_retry(sub.pk)
        self.assertEqual(result.status, "charged")
        sub.refresh_from_db()
        self.assertEqual((sub.status, sub.failure_count), ("active", 0))

    def test_the_charge_uses_the_price_on_the_day_of_the_charge(self):
        sub, _ = self.subscribe()
        ShopProduct.objects.filter(pk=self.product.pk).update(it_price=30000)
        self.run_job(sub.next_charge_date, side_effect=approved())

        self.assertEqual(sub.charges.get(cycle_no=2).amount, 2 * 27000)

    def test_an_out_of_stock_cycle_is_skipped_with_a_notice(self):
        sub, _ = self.subscribe()
        ShopProduct.objects.filter(pk=self.product.pk).update(it_stock_qty=1)
        day = sub.next_charge_date
        summary, charge = self.run_job(day, side_effect=approved())

        self.assertEqual(summary["skipped"], 1)
        charge.assert_not_called()
        sub.refresh_from_db()
        self.assertEqual(sub.next_charge_date, day + timedelta(weeks=2))
        self.assertEqual(sub.charges.get(cycle_no=2).status, "skipped")
        self.assertTrue(Notification.objects.filter(user=self.member, nt_title__contains="건너뛰").exists())

    def test_a_lost_answer_stays_pending_until_the_payment_is_looked_up(self):
        sub, _ = self.subscribe()
        lost = TossBillingError("Toss Payments did not answer.", code="toss_unavailable", uncertain=True)
        summary, _ = self.run_job(sub.next_charge_date, side_effect=lost)
        self.assertEqual(summary["pending"], 1)
        charge = sub.charges.get(cycle_no=2)
        self.assertEqual(charge.status, "pending")
        ShopSubscriptionCharge.objects.filter(pk=charge.pk).update(updated_at=timezone.now() - timedelta(minutes=30))

        payment = {"orderId": charge.od_id, "paymentKey": "pay_late", "status": "DONE", "totalAmount": charge.amount}
        with patch(LOOKUP, return_value=payment), self.captureOnCommitCallbacks(execute=True):
            report = service.reconcile_stale_charges()
        self.assertEqual(report["charged"], 1)
        charge.refresh_from_db()
        self.assertEqual(charge.status, "done")
        self.assertEqual(charge.order.od_status, "입금")

    def test_a_lost_answer_without_a_payment_at_toss_counts_as_a_failure(self):
        sub, _ = self.subscribe()
        lost = TossBillingError("Toss Payments did not answer.", code="toss_unavailable", uncertain=True)
        self.run_job(sub.next_charge_date, side_effect=lost)
        ShopSubscriptionCharge.objects.filter(status="pending").update(updated_at=timezone.now() - timedelta(minutes=30))
        with patch(LOOKUP, return_value=None), self.captureOnCommitCallbacks(execute=True):
            report = service.reconcile_stale_charges()

        self.assertEqual(report["failed"], 1)
        sub.refresh_from_db()
        self.assertEqual(sub.failure_count, 1)
        self.assertEqual(sub.charges.get(cycle_no=2).order.od_status, "취소")

    def test_an_approval_that_does_not_match_is_left_for_review(self):
        sub, _ = self.subscribe()
        self.run_job(sub.next_charge_date, side_effect=approved(totalAmount=1))
        charge = sub.charges.get(cycle_no=2)
        self.assertEqual(charge.status, "review")
        self.assertEqual(charge.order.od_status, "주문")

    def test_the_upcoming_notice_goes_once_per_cycle(self):
        sub, _ = self.subscribe()
        notice_day = sub.next_charge_date - timedelta(days=3)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(service.send_upcoming_notices(notice_day), 1)
            self.assertEqual(service.send_upcoming_notices(notice_day), 0)
        self.assertEqual(Notification.objects.filter(nt_title__contains="결제 예정").count(), 1)

    def test_the_command_dry_run_changes_nothing(self):
        from io import StringIO

        from django.core.management import call_command

        sub, _ = self.subscribe()
        out = StringIO()
        with patch(CHARGE) as charge:
            call_command("charge_shop_subscriptions", "--json", "--date", sub.next_charge_date.isoformat(), stdout=out)
        charge.assert_not_called()
        self.assertIn('"due": 1', out.getvalue())
        self.assertIn('"applied": false', out.getvalue())


class EdgeCaseTests(SubscriptionTestBase):
    def test_the_admin_retry_never_charges_a_cycle_early(self):
        sub, _ = self.subscribe()
        with patch(CHARGE) as charge:
            self.assertEqual(service.admin_retry(sub.pk).status, "not_due")
        charge.assert_not_called()

    def test_the_admin_retry_charges_a_failed_current_cycle(self):
        sub, _ = self.subscribe()
        self.run_job(sub.next_charge_date, side_effect=TossBillingError("거절", code="REJECT_CARD_PAYMENT", status=403))
        with patch(CHARGE, side_effect=approved()), self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(service.admin_retry(sub.pk).status, "charged")

    def test_a_first_charge_under_review_keeps_the_subscription_and_its_order(self):
        registration = self.start().json()["data"]
        with patch(ISSUE, return_value=billing_object(registration["customer_key"])), \
                patch(CHARGE, side_effect=approved(totalAmount=1)), patch(DELETE) as delete, \
                self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(AUTH_URL, {
                "registration_token": registration["registration_token"], "authKey": "a", "customerKey": registration["customer_key"],
            }, format="json")

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"]["charge_status"], "review")
        delete.assert_not_called()
        sub = ShopSubscription.objects.get(pk=registration["subscription_id"])
        self.assertEqual(sub.status, "active")
        order = sub.charges.get().order
        # the paymentKey keeps the unpaid-order expiry away from it and allows a Toss refund
        self.assertEqual(order.od_tno, f"pay_{order.od_id}")

    def test_a_first_charge_that_reconcile_finds_missing_ends_the_subscription(self):
        registration = self.start().json()["data"]
        lost = TossBillingError("Toss Payments did not answer.", code="toss_unavailable", uncertain=True)
        with patch(ISSUE, return_value=billing_object(registration["customer_key"])), patch(CHARGE, side_effect=lost):
            response = self.client.post(AUTH_URL, {
                "registration_token": registration["registration_token"], "authKey": "a", "customerKey": registration["customer_key"],
            }, format="json")
        self.assertEqual(response.json()["data"]["charge_status"], "pending")
        ShopSubscriptionCharge.objects.update(updated_at=timezone.now() - timedelta(minutes=30))
        with patch(LOOKUP, return_value=None), patch(DELETE) as delete, self.captureOnCommitCallbacks(execute=True):
            service.reconcile_stale_charges()

        sub = ShopSubscription.objects.get(pk=registration["subscription_id"])
        self.assertEqual(sub.status, "cancelled")
        delete.assert_called_once_with(BILLING_KEY, mode="1")
        with patch(CHARGE) as charge:
            service.run_scheduled(apply=True)
        charge.assert_not_called()

    def test_an_order_error_counts_as_a_failed_attempt(self):
        sub, _ = self.subscribe()
        with patch("gnu_jango.shop.subscriptions._create_order", side_effect=ValueError("boom")), \
                patch(CHARGE) as charge, self.captureOnCommitCallbacks(execute=True):
            result = service.charge_subscription(sub.pk, today=sub.next_charge_date)

        self.assertEqual(result.status, "failed")
        charge.assert_not_called()
        sub.refresh_from_db()
        self.assertEqual((sub.failure_count, sub.retry_date), (1, sub.next_charge_date + timedelta(days=1)))

    def test_a_member_cannot_lift_an_admin_pause(self):
        sub, _ = self.subscribe()
        self.assertTrue(service.admin_pause(sub.pk))
        response = self.client.post(f"{LIST_URL}/{sub.pk}/action", {"action": "resume"}, format="json")
        self.assertEqual(response.status_code, 409)

    def test_the_card_is_not_replaced_under_a_charge_in_flight(self):
        sub, _ = self.subscribe()
        registration = self.client.post(f"{LIST_URL}/{sub.pk}/card", {}, format="json").json()["data"]
        ShopSubscriptionCharge.objects.create(
            subscription=sub, cycle_no=sub.cycle_no, attempt=1, scheduled_date=sub.next_charge_date,
            status="pending", idempotency_key="in-flight-card",
        )
        with patch(ISSUE, return_value=billing_object(registration["customer_key"], key="bk_new")), \
                patch(DELETE) as delete, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(AUTH_URL, {
                "registration_token": registration["registration_token"], "authKey": "b", "customerKey": registration["customer_key"],
            }, format="json")

        self.assertEqual(response.status_code, 409)
        delete.assert_called_once_with("bk_new", mode="1")
        sub.refresh_from_db()
        self.assertEqual(service.billing_key(sub), BILLING_KEY)


class MemberActionTests(SubscriptionTestBase):
    def action(self, sub, action, client=None, **fields):
        return (client or self.client).post(f"{LIST_URL}/{sub.pk}/action", {"action": action, **fields}, format="json")

    def test_list_and_detail_show_the_card_and_history_but_never_the_key(self):
        sub, _ = self.subscribe()
        listing = self.client.get(LIST_URL)
        detail = self.client.get(f"{LIST_URL}/{sub.pk}")

        self.assertEqual(listing.json()["data"][0]["card"]["number"], "43301234****123*")
        self.assertEqual(len(detail.json()["data"]["charges"]), 1)
        for response in (listing, detail):
            self.assertNotIn(BILLING_KEY, response.content.decode())
            self.assertNotIn(sub.customer_key, response.content.decode())

    def test_another_member_cannot_see_or_change_a_subscription(self):
        sub, _ = self.subscribe()
        stranger = APIClient()
        stranger.force_authenticate(user=self.other)

        self.assertEqual(stranger.get(f"{LIST_URL}/{sub.pk}").status_code, 404)
        self.assertEqual(self.action(sub, "cancel", client=stranger).status_code, 404)
        self.assertEqual(stranger.post(f"{LIST_URL}/{sub.pk}/card", {}, format="json").status_code, 404)
        self.assertEqual(stranger.get(LIST_URL).json()["data"], [])
        sub.refresh_from_db()
        self.assertEqual(sub.status, "active")

    def test_pause_and_resume(self):
        sub, _ = self.subscribe()
        self.assertEqual(self.action(sub, "pause").json()["data"]["status"], "paused")
        with patch(CHARGE) as charge:
            service.run_scheduled(today=sub.next_charge_date, apply=True)
        charge.assert_not_called()
        ShopSubscription.objects.filter(pk=sub.pk).update(next_charge_date=timezone.localdate())

        data = self.action(sub, "resume").json()["data"]
        self.assertEqual(data["status"], "active")
        # never charged on the click: tomorrow at the earliest
        self.assertEqual(data["next_charge_date"], (timezone.localdate() + timedelta(days=1)).isoformat())

    def test_skip_moves_to_the_next_cycle_without_charging(self):
        sub, _ = self.subscribe()
        day = sub.next_charge_date
        with patch(CHARGE) as charge:
            data = self.action(sub, "skip").json()["data"]
        charge.assert_not_called()
        self.assertEqual(data["next_charge_date"], (day + timedelta(weeks=2)).isoformat())
        self.assertEqual(sub.charges.get(cycle_no=2).status, "skipped")

    def test_change_cycle_only_to_one_the_product_offers(self):
        sub, _ = self.subscribe()
        self.assertEqual(self.action(sub, "cycle", cycle="4w").status_code, 422)
        self.assertEqual(self.action(sub, "cycle", cycle="1m").json()["data"]["cycle"], "1m")

    def test_cancel_drops_the_billing_key(self):
        sub, _ = self.subscribe()
        with patch(DELETE) as delete, self.captureOnCommitCallbacks(execute=True):
            data = self.action(sub, "cancel").json()["data"]
        self.assertEqual(data["status"], "cancelled")
        delete.assert_called_once_with(BILLING_KEY, mode="1")
        sub.refresh_from_db()
        self.assertEqual(sub.billing_key_sealed, "")
        self.assertEqual(self.action(sub, "resume").status_code, 409)

    def test_no_change_while_a_charge_is_in_progress(self):
        sub, _ = self.subscribe()
        ShopSubscriptionCharge.objects.create(
            subscription=sub, cycle_no=sub.cycle_no, attempt=1, scheduled_date=sub.next_charge_date,
            status="pending", idempotency_key="in-flight",
        )
        self.assertEqual(self.action(sub, "cancel").status_code, 409)
        self.assertEqual(self.action(sub, "skip").status_code, 409)


class AdminTests(SubscriptionTestBase):
    def setUp(self):
        super().setUp()
        self.admin = get_user_model().objects.create_superuser("sub-admin", "admin@example.test", "pw-unused")
        self.client.force_login(self.admin)

    def test_admin_pages_render_without_the_key(self):
        member_client = APIClient()
        member_client.force_authenticate(user=self.member)
        self.client, admin_client = member_client, self.client
        sub, _ = self.subscribe()
        for path in (
            "/admin/shop/shopsubscription/",
            f"/admin/shop/shopsubscription/{sub.pk}/change/",
            "/admin/shop/shopsubscriptioncharge/",
            f"/admin/shop/shopsubscriptioncharge/{sub.charges.get().pk}/change/",
        ):
            response = admin_client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertNotIn(BILLING_KEY, response.content.decode())
            self.assertNotIn(sub.billing_key_sealed, response.content.decode())

    def test_admin_cancel_action(self):
        member_client = APIClient()
        member_client.force_authenticate(user=self.member)
        self.client, admin_client = member_client, self.client
        sub, _ = self.subscribe()
        with patch(DELETE), self.captureOnCommitCallbacks(execute=True):
            response = admin_client.post(
                "/admin/shop/shopsubscription/", {"action": "cancel_selected", "_selected_action": [sub.pk]}
            )
        self.assertEqual(response.status_code, 302)
        sub.refresh_from_db()
        self.assertEqual(sub.status, "cancelled")


class MessageTests(TestCase):
    def test_every_unavailable_reason_has_a_korean_message(self):
        from gnu_jango.core.test_api_messages_localized import translated_messages

        missing = {message for message, _ in service.UNAVAILABLE.values()} - translated_messages()
        self.assertEqual(missing, set())
