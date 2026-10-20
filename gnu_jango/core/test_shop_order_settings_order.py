"""Order form settings from the shop settings page: hoped-for delivery date and guest privacy notice.

YoungCart orderform.sub.php / orderformupdate.php: with de_hope_date_use on the customer must pick a
date from de_hope_date_after days after today for seven days; with it off a submitted date is
ignored. de_guest_privacy is the editor HTML a guest agrees to before ordering.
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api.shop_order_options import guest_privacy_html, hope_date_range, order_hope_date
from gnu_jango.config.models import Config
from gnu_jango.shop.inventory import StockAdjustmentError
from gnu_jango.shop.models import ShopCategory, ShopOrder, ShopProduct

API = "/api/v1/shop"
BANK = "Hope Bank 000-00 Holder"
ORDER_FORM = {
    "od_name": "Buyer",
    "od_hp": "010-1111-2222",
    "od_email": "buyer@example.test",
    "od_b_name": "Buyer",
    "od_b_hp": "010-1111-2222",
    "od_b_zip": "06236",
    "od_b_addr1": "Seoul",
    "od_settle_case": "bank",
    "od_bank_account": BANK,
    "od_deposit_name": "Buyer",
}


def set_option(name, value):
    Config.objects.update_or_create(name=name, defaults={"value": str(value)})


class HopeDateRuleTests(TestCase):
    def test_the_default_rule_is_off_and_starts_three_days_out_for_seven_days(self):
        today = date(2026, 10, 20)
        self.assertEqual(
            hope_date_range(today),
            {"use": False, "after": 3, "min": "2026-10-23", "max": "2026-10-29"},
        )

    def test_the_rule_follows_the_settings(self):
        set_option("de_hope_date_use", 1)
        set_option("de_hope_date_after", 0)
        self.assertEqual(
            hope_date_range(date(2026, 12, 30)),
            {"use": True, "after": 0, "min": "2026-12-30", "max": "2027-01-05"},
        )

    def test_a_submitted_date_is_ignored_while_the_shop_does_not_use_it(self):
        self.assertIsNone(order_hope_date({"od_hope_date": "2026-10-25"}, date(2026, 10, 20)))
        self.assertIsNone(order_hope_date({"od_hope_date": "junk"}, date(2026, 10, 20)))

    def test_the_date_is_checked_while_the_shop_uses_it(self):
        set_option("de_hope_date_use", 1)
        today = date(2026, 10, 20)
        cases = {
            "": "hope_date_required",
            "  ": "hope_date_required",
            "2026-02-30": "hope_date_invalid",
            "20261025": "hope_date_invalid",
            "2026-10-25T00:00": "hope_date_invalid",
            "2026-10-22": "hope_date_out_of_range",
            "2026-10-30": "hope_date_out_of_range",
        }
        for value, code in cases.items():
            with self.subTest(value=value), self.assertRaises(StockAdjustmentError) as caught:
                order_hope_date({"od_hope_date": value}, today)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(order_hope_date({"od_hope_date": "2026-10-23"}, today), date(2026, 10, 23))
        self.assertEqual(order_hope_date({"od_hope_date": "2026-10-29"}, today), date(2026, 10, 29))


class GuestPrivacyTests(TestCase):
    def test_the_notice_is_empty_until_the_administrator_writes_one(self):
        self.assertEqual(guest_privacy_html(), "")

    def test_the_notice_is_sanitized(self):
        set_option("de_guest_privacy", '<p onclick="x()">수집 항목: 이름</p><script>alert(1)</script>')
        html = guest_privacy_html()
        self.assertIn("수집 항목: 이름", html)
        self.assertNotIn("<script", html)
        self.assertNotIn("onclick", html)


class OrderSettingsApiTests(TestCase):
    def setUp(self):
        cache.clear()
        category = ShopCategory.objects.create(ca_id="71", ca_name="Hope")
        self.product = ShopProduct.objects.create(
            it_id="HD001", it_name="Hope", it_price=5000, it_stock_qty=50, it_use="1", category=category
        )
        set_option("de_bank_use", 1)
        set_option("de_bank_account", BANK)
        self.member = get_user_model().objects.create_user(username="hoper", email="hoper@example.test")
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)
        self.today = timezone.localdate()

    def place(self, **fields):
        added = self.client.post(f"{API}/cart", {"it_id": self.product.it_id, "ct_qty": 1}, format="json")
        self.assertEqual(added.status_code, 201, added.content[:300])
        return self.client.post(f"{API}/orders", {**ORDER_FORM, **fields}, format="json")

    def day(self, offset):
        return (self.today + timedelta(days=offset)).isoformat()

    def test_payment_config_exposes_the_hope_date_rule_and_guest_notice(self):
        set_option("de_hope_date_use", 1)
        set_option("de_hope_date_after", 2)
        set_option("de_guest_privacy", "<p>비회원 안내</p><script>x</script>")

        data = APIClient().get(f"{API}/payment/config").json()["data"]

        self.assertEqual(data["hope_date"], {"use": True, "after": 2, "min": self.day(2), "max": self.day(8)})
        self.assertIn("<p>비회원 안내</p>", data["guest_privacy"])
        self.assertNotIn("<script", data["guest_privacy"])

    def test_without_the_setting_the_order_ignores_a_submitted_date(self):
        response = self.place(od_hope_date=self.day(5))

        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertEqual(response.json()["data"]["order"]["od_hope_date"], "")
        order = ShopOrder.objects.get(pk=response.json()["data"]["od_id"])
        self.assertIsNone(order.od_hope_date)

    def test_with_the_setting_an_order_without_a_date_is_refused_and_the_cart_is_kept(self):
        set_option("de_hope_date_use", 1)

        response = self.place()

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("code"), "hope_date_required")
        self.assertEqual(ShopOrder.objects.count(), 0)
        cart = self.client.get(f"{API}/cart").json()["data"]["items"]
        self.assertEqual(len(cart), 1)

    def test_with_the_setting_a_date_outside_the_range_is_refused(self):
        set_option("de_hope_date_use", 1)
        set_option("de_hope_date_after", 1)
        for value, code in ((self.day(0), "hope_date_out_of_range"), (self.day(8), "hope_date_out_of_range"),
                            ("2026/10/30", "hope_date_invalid")):
            with self.subTest(value=value):
                response = self.place(od_hope_date=value)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json().get("code"), code)
        self.assertEqual(ShopOrder.objects.count(), 0)

    def test_with_the_setting_a_date_in_the_range_is_stored_and_shown(self):
        set_option("de_hope_date_use", 1)
        set_option("de_hope_date_after", 1)

        response = self.place(od_hope_date=self.day(7))

        self.assertEqual(response.status_code, 201, response.content[:300])
        od_id = response.json()["data"]["od_id"]
        self.assertEqual(ShopOrder.objects.get(pk=od_id).od_hope_date, self.today + timedelta(days=7))
        detail = self.client.get(f"{API}/orders/{od_id}").json()["data"]
        self.assertEqual(detail["od_hope_date"], self.day(7))


class OrderAdminHopeDateTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="hope-admin", email="hope-admin@example.test", password="Admin-pass-1"
        )
        self.client.force_login(self.admin)

    def test_the_order_change_page_shows_and_edits_the_hope_date(self):
        order = ShopOrder.objects.create(od_id="2026102000001", od_name="Buyer", od_hope_date=date(2026, 10, 25))

        body = self.client.get(reverse("admin:shop_shoporder_change", args=[order.pk])).content.decode()

        self.assertIn("희망배송일", body)
        self.assertIn('name="od_hope_date"', body)
        self.assertIn("2026-10-25 (일)", body)
