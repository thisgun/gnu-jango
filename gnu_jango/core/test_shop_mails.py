"""Shop mails: the product recommendation (itemrecommendmail.php), the order mails
(ordermail1/2.inc.php) and the 입금 / 배송 processing mail (adm/shop_admin/ordermail.inc.php).

Mail goes to Django's locmem outbox; nothing leaves the test run.
"""

from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api.shop_payments import confirm_order_payment, save_toss_vbank_authorization
from gnu_jango.config.models import Config
from gnu_jango.core.test_shop_orders_more import API, ShopOrderBase
from gnu_jango.shop.models import ShopOrder
from gnu_jango.shop.order_flow import move_order_status
from gnu_jango.users.models import Profile

ADMIN = "shop-admin@example.test"
SITE = "https://shop.example.test"


@override_settings(SOCIAL_APP_BASE_URL=SITE)
class ShopMailBase(ShopOrderBase):
    def setUp(self):
        super().setUp()
        Config.objects.update_or_create(name="cf_title", defaults={"value": "테스트몰"})
        Config.objects.update_or_create(name="cf_admin_email", defaults={"value": ADMIN})
        Config.objects.update_or_create(name="cf_admin_email_name", defaults={"value": "테스트몰 운영자"})
        mail.outbox.clear()

    def disable_mail(self):
        Config.objects.update_or_create(name="cf_email_use", defaults={"value": "0"})

    def html_of(self, message):
        return next(content for content, mimetype in message.alternatives if mimetype == "text/html")


class ProductRecommendMailTests(ShopMailBase):
    def setUp(self):
        super().setUp()
        # a member for more than a day (fresh accounts cannot send)
        type(self.member).objects.filter(pk=self.member.pk).update(date_joined=timezone.now() - timedelta(days=2))
        self.member.refresh_from_db()

    def recommend(self, client=None, it_id="MO001", **fields):
        body = {"to_email": "friend@example.test", "subject": "이거 봐", "content": "좋은 상품이야", **fields}
        # the mail leaves once the request's transaction commits (the test case holds one open)
        with self.captureOnCommitCallbacks(execute=True):
            return (client or self.client).post(f"{API}/products/{it_id}/recommend", body, format="json")

    def test_a_member_recommends_a_product_to_one_address(self):
        response = self.recommend(content="<script>alert(1)</script>\n두 번째 줄")

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertTrue(response.json()["data"]["queued"])
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ["friend@example.test"])
        self.assertEqual(message.reply_to, ["more-member@example.test"])
        self.assertIn(ADMIN, message.from_email)
        self.assertEqual(message.subject, "[테스트몰] 이거 봐")
        self.assertIn("More product", message.body)
        self.assertIn(f"{SITE}/shop/products/MO001", message.body)
        html = self.html_of(message)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("<br>두 번째 줄", html)
        self.assertIn(f'href="{SITE}/shop/products/MO001"', html)

    def test_guests_unknown_products_and_hidden_products_are_refused(self):
        self.assertEqual(self.recommend(APIClient()).status_code, 401)
        self.assertEqual(self.recommend(it_id="NOPE").status_code, 404)
        self.make_product("HIDDEN1", "Hidden", it_use="0")
        self.assertEqual(self.recommend(it_id="HIDDEN1").status_code, 404)
        self.assertEqual(mail.outbox, [])

    def test_one_valid_recipient_and_a_complete_form_are_required(self):
        cases = (
            {"to_email": "a@example.test, b@example.test"},
            {"to_email": "a@example.test\nBcc: b@example.test"},
            {"to_email": "not-an-address"},
            {"subject": ""},
            {"subject": "x" * 201},
            {"content": "   "},
            {"content": "x" * 1001},
        )
        for fields in cases:
            with self.subTest(fields=fields):
                self.assertEqual(self.recommend(**fields).status_code, 422)
        self.assertEqual(mail.outbox, [])

    def test_a_line_break_in_the_subject_cannot_add_headers(self):
        self.assertEqual(self.recommend(subject="Hi\r\nBcc: victim@example.test").status_code, 200)
        self.assertEqual(mail.outbox[0].subject, "[테스트몰] Hi Bcc: victim@example.test")
        self.assertEqual(mail.outbox[0].bcc, [])

    def test_mail_off_answers_service_unavailable(self):
        self.disable_mail()
        response = self.recommend()
        self.assertEqual((response.status_code, response.json()["code"]), (503, "mail_disabled"))
        self.assertEqual(mail.outbox, [])

    def test_a_member_may_send_five_an_hour(self):
        cache.clear()
        for _ in range(5):
            self.assertEqual(self.recommend().status_code, 200)
        self.assertEqual(self.recommend().status_code, 429)
        self.assertEqual(len(mail.outbox), 5)

    def test_a_new_account_cannot_send_yet(self):
        self.member.date_joined = timezone.now()
        self.member.save(update_fields=["date_joined"])
        response = self.recommend()
        self.assertEqual((response.status_code, response.json()["code"]), (403, "recommend_account_too_new"))
        self.assertEqual(mail.outbox, [])

    def test_an_uncertified_address_cannot_send_while_certification_is_on(self):
        Config.objects.update_or_create(name="cf_use_email_certify", defaults={"value": "1"})
        Profile.objects.filter(user=self.member).update(email_certify=None)
        response = self.recommend()
        # the sign-in itself already refuses an uncertified member (401); the view checks it again (403)
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(mail.outbox, [])
        Profile.objects.filter(user=self.member).update(email_certify=timezone.now())
        self.assertEqual(self.recommend().status_code, 200)

    def test_one_address_is_limited_across_accounts(self):
        cache.clear()
        senders = []
        for index in range(3):
            user = type(self.member).objects.create_user(username=f"sender{index}", email=f"sender{index}@example.test")
            type(user).objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=2))
            client = APIClient()
            client.force_authenticate(user=type(user).objects.get(pk=user.pk))
            senders.append(client)
        with patch("gnu_jango.api.shop_recommend._configured_rate", side_effect=lambda scope, default: "2/hour" if scope == "shop-recommend-ip" else default):
            codes = [self.recommend(client).status_code for client in senders]
        self.assertEqual(codes, [200, 200, 429])

    def test_a_mail_server_failure_is_logged_not_raised(self):
        with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp down")):
            response = self.recommend()
        # sent after the response was built (on_commit): the failure is logged, the request still ends
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox, [])

    def test_outside_a_transaction_the_send_result_is_answered(self):
        from gnu_jango.api import shop_recommend

        def run_now(callback, using=None, robust=False):
            callback()

        with patch.object(shop_recommend.transaction, "on_commit", side_effect=run_now), patch(
            "django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp down")
        ):
            response = self.client.post(
                f"{API}/products/MO001/recommend",
                {"to_email": "friend@example.test", "subject": "이거 봐", "content": "좋은 상품이야"},
                format="json",
            )
        self.assertEqual((response.status_code, response.json()["code"]), (502, "mail_send_failed"))


class OrderPlacedMailTests(ShopMailBase):
    def place_order(self):
        self.add(self.client)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.place()
        self.assertEqual(response.status_code, 201, response.content[:300])
        return ShopOrder.objects.get(pk=response.json()["data"]["od_id"])

    def test_a_bank_order_mails_the_admin_and_the_customer(self):
        order = self.place_order()

        self.assertEqual(len(mail.outbox), 2)
        admin_mail, customer_mail = mail.outbox
        self.assertEqual(admin_mail.to, [ADMIN])
        self.assertEqual(admin_mail.subject, "테스트몰 - 주문 알림 메일 (Buyer)")
        self.assertEqual(admin_mail.reply_to, ["buyer@example.test"])
        self.assertEqual(customer_mail.to, ["buyer@example.test"])
        self.assertEqual(customer_mail.subject, "테스트몰 - 주문 내역 안내 메일")
        for message in (admin_mail, customer_mail):
            self.assertIn(order.od_id, message.body)
            self.assertIn("More product", message.body)
            self.assertIn("Test Bank 000-00 Holder", message.body)
        self.assertIn(f"{SITE}/shop/orders/{order.od_id}", customer_mail.body)
        self.assertIn("주문 상세 보기", self.html_of(customer_mail))

    def test_without_an_admin_address_only_the_customer_is_mailed(self):
        Config.objects.filter(name="cf_admin_email").update(value="")
        self.place_order()
        self.assertEqual([message.to for message in mail.outbox], [["buyer@example.test"]])

    def test_mail_off_sends_nothing(self):
        self.disable_mail()
        self.place_order()
        self.assertEqual(mail.outbox, [])

    def test_a_mail_failure_does_not_break_the_order(self):
        with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp down")):
            order = self.place_order()
        self.assertEqual(order.od_status, "주문")

    def test_a_confirmed_pg_payment_mails_once(self):
        order = ShopOrder.objects.create(
            od_id="PG-MAIL-1", od_name="Card buyer", od_email="card@example.test",
            od_status="주문", od_settle_case="신용카드", od_receipt_price=1000, od_cart_price=1000,
        )
        with self.captureOnCommitCallbacks(execute=True):
            confirm_order_payment(order.od_id, 1000, "toss", "pay-key", {})
        with self.captureOnCommitCallbacks(execute=True):
            confirm_order_payment(order.od_id, 1000, "toss", "pay-key", {})  # a repeated confirmation
        self.assertEqual(sorted(tuple(message.to) for message in mail.outbox), [("card@example.test",), (ADMIN,)])

    def test_an_issued_virtual_account_is_mailed_once_with_its_account(self):
        order = ShopOrder.objects.create(
            od_id="VB-ISSUE-1", od_name="Vbank buyer", od_email="vbank@example.test",
            od_status="주문", od_settle_case="가상계좌", od_receipt_price=1000, od_cart_price=1000,
        )
        toss_payment = {
            "paymentKey": "vbank-key", "status": "WAITING_FOR_DEPOSIT", "secret": "s",
            "virtualAccount": {"accountNumber": "12345678901234", "bankCode": "20", "dueDate": "2026-10-22"},
        }
        for _ in range(2):  # a repeated confirmation keeps the same account
            with self.captureOnCommitCallbacks(execute=True):
                save_toss_vbank_authorization(order, toss_payment)
        customer = [message for message in mail.outbox if message.to == ["vbank@example.test"]]
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("가상계좌: 20 12345678901234", customer[0].body)

    def test_a_virtual_account_deposit_sends_the_deposit_mail(self):
        order = ShopOrder.objects.create(
            od_id="VB-MAIL-1", od_name="Vbank buyer", od_email="vbank@example.test",
            od_status="주문", od_settle_case="가상계좌", od_receipt_price=1000, od_cart_price=1000,
        )
        with self.captureOnCommitCallbacks(execute=True):
            confirm_order_payment(order.od_id, 1000, "toss", "pay-key", {})
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].subject, "테스트몰 - Vbank buyer님 주문 처리 내역 안내")


class OrderStatusMailTests(ShopMailBase):
    def setUp(self):
        super().setUp()
        self.add(self.client)
        self.order = ShopOrder.objects.get(pk=self.place().json()["data"]["od_id"])
        mail.outbox.clear()

    def move(self, status):
        with self.captureOnCommitCallbacks(execute=True):
            result = move_order_status(self.order, status, actor="admin")
        self.assertTrue(result, result.message)
        self.order.refresh_from_db()

    def test_the_deposit_and_the_shipment_are_mailed(self):
        self.move("입금")
        self.assertEqual(len(mail.outbox), 1)
        paid = mail.outbox[0]
        self.assertEqual(paid.to, ["buyer@example.test"])
        self.assertEqual(paid.subject, "테스트몰 - Buyer님 주문 처리 내역 안내")
        self.assertIn("입금액", paid.body)
        self.assertIn("결제/배송내역 메일발송", self.order.od_shop_memo)

        self.move("준비")
        self.assertEqual(len(mail.outbox), 1)

        ShopOrder.objects.filter(pk=self.order.pk).update(od_delivery_company="Courier", od_invoice="INV-123")
        self.move("배송")
        self.assertEqual(len(mail.outbox), 2)
        shipped = mail.outbox[1]
        self.assertIn("INV-123", shipped.body)
        self.assertIn("Courier", shipped.body)
        self.assertIn("배송중", shipped.body)

    def test_mail_off_or_no_address_sends_nothing(self):
        self.disable_mail()
        self.move("입금")
        Config.objects.filter(name="cf_email_use").update(value="1")
        ShopOrder.objects.filter(pk=self.order.pk).update(od_email="")
        self.move("준비")
        ShopOrder.objects.filter(pk=self.order.pk).update(od_delivery_company="Courier", od_invoice="INV-1")
        self.move("배송")
        self.assertEqual(mail.outbox, [])

    def test_a_mail_failure_does_not_undo_the_status_change(self):
        with patch("django.core.mail.EmailMultiAlternatives.send", side_effect=OSError("smtp down")):
            self.move("입금")
        self.assertEqual(self.order.od_status, "입금")
        self.assertNotIn("메일발송", self.order.od_shop_memo)
