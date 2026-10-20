"""Cart settings from the shop settings page: de_cart_keep_term and de_guest_cart_use.

YoungCart lib/shop.lib.php cart_item_clean drops cart lines put in the cart more than
de_cart_keep_term days ago, and set_cart_id keeps a guest cart for that many days when
de_guest_cart_use is on (otherwise it lives as long as the browser session).
"""

import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api.shop_cart_keep import (
    CART_TIME_KEY,
    GUEST_CART_KEEP_FLAG,
    SECONDS_PER_DAY,
    cart_now,
    prune_cart_rows,
)
from gnu_jango.api.shop_common import SHOP_CART_SESSION_KEY, auth_cart_config_name
from gnu_jango.config.models import Config
from gnu_jango.shop.models import ShopCategory, ShopProduct

API = "/api/v1/shop"
PASSWORD = "Cart-keep-pass-1"


def days_ago(days):
    return cart_now() - days * SECONDS_PER_DAY


class CartSettingsBase(TestCase):
    def setUp(self):
        category = ShopCategory.objects.create(ca_id="70", ca_name="Keep")
        self.product = ShopProduct.objects.create(
            it_id="KP001", it_name="Kept", it_price=1000, it_stock_qty=50, it_use="1", category=category
        )
        self.member = get_user_model().objects.create_user(username="keeper", password=PASSWORD)
        self.guest = APIClient()
        self.member_client = APIClient()
        self.member_client.force_authenticate(user=self.member)

    def set_option(self, name, value):
        Config.objects.update_or_create(name=name, defaults={"value": str(value)})

    def add(self, client, **extra):
        response = client.post(f"{API}/cart", {"it_id": self.product.it_id, "ct_qty": 1, **extra}, format="json")
        self.assertEqual(response.status_code, 201, response.content[:300])
        return response

    def seed_guest_cart(self, rows):
        session = self.guest.session
        session[SHOP_CART_SESSION_KEY] = rows
        session.save()

    def guest_rows(self):
        return self.guest.session.get(SHOP_CART_SESSION_KEY, [])

    def seed_member_cart(self, rows):
        self.set_option(auth_cart_config_name(self.member), json.dumps(rows))

    def member_rows(self):
        return json.loads(Config.objects.get(name=auth_cart_config_name(self.member)).value)

    def line(self, ct_id, **extra):
        return {"ct_id": ct_id, "it_id": self.product.it_id, "ct_price": 1000, "ct_qty": 1, "ct_option": "",
                "io_type": 0, "io_price": 0, "ct_direct": 0, **extra}

    def cart_ids(self, client):
        response = client.get(f"{API}/cart")
        self.assertEqual(response.status_code, 200)
        return [item["ct_id"] for item in response.json()["data"]["items"]]


class PruneCartRowsTests(TestCase):
    def test_lines_older_than_the_keep_term_are_dropped_and_others_kept(self):
        now = 2_000_000_000
        rows = [
            {"ct_id": "old", CART_TIME_KEY: now - 16 * SECONDS_PER_DAY},
            {"ct_id": "edge", CART_TIME_KEY: now - 15 * SECONDS_PER_DAY},
            {"ct_id": "new", CART_TIME_KEY: now - 60},
        ]

        kept, changed = prune_cart_rows(rows, 15, now=now)

        self.assertTrue(changed)
        self.assertEqual([row["ct_id"] for row in kept], ["edge", "new"])
        self.assertEqual(len(rows), 3, "the input list is left as it was")

    def test_a_line_without_a_time_is_kept_and_stamped_now(self):
        now = 2_000_000_000
        rows = [{"ct_id": "legacy"}, {"ct_id": "bad", CART_TIME_KEY: "x"}, "junk"]

        kept, changed = prune_cart_rows(rows, 1, now=now)

        self.assertTrue(changed)
        self.assertEqual(kept, [{"ct_id": "legacy", CART_TIME_KEY: now}, {"ct_id": "bad", CART_TIME_KEY: now}])
        self.assertNotIn(CART_TIME_KEY, rows[0])

    def test_fresh_stamped_lines_report_no_change(self):
        now = 2_000_000_000
        rows = [{"ct_id": "a", CART_TIME_KEY: now}]
        self.assertEqual(prune_cart_rows(rows, 15, now=now), (rows, False))


class CartKeepTermTests(CartSettingsBase):
    def test_a_new_cart_line_records_when_it_was_put_in_the_cart(self):
        before = cart_now()
        self.add(self.guest)

        row = self.guest_rows()[0]
        self.assertGreaterEqual(row[CART_TIME_KEY], before)
        self.assertLessEqual(row[CART_TIME_KEY], cart_now())

    def test_adding_the_same_option_again_keeps_the_original_time(self):
        self.seed_guest_cart([self.line("100000000001", **{CART_TIME_KEY: days_ago(3)})])
        original = self.guest_rows()[0][CART_TIME_KEY]

        self.add(self.guest)

        rows = self.guest_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ct_qty"], 2)
        self.assertEqual(rows[0][CART_TIME_KEY], original)

    def test_guest_lines_past_the_default_keep_term_are_removed(self):
        self.seed_guest_cart([
            self.line("100000000001", **{CART_TIME_KEY: days_ago(16)}),
            self.line("100000000002", **{CART_TIME_KEY: days_ago(14)}),
        ])

        self.assertEqual(self.cart_ids(self.guest), ["100000000002"])
        self.assertEqual([row["ct_id"] for row in self.guest_rows()], ["100000000002"])

    def test_member_lines_follow_the_configured_keep_term_and_the_pruned_cart_is_saved(self):
        self.set_option("de_cart_keep_term", 2)
        self.seed_member_cart([
            self.line("100000000001", **{CART_TIME_KEY: days_ago(3)}),
            self.line("100000000002", **{CART_TIME_KEY: days_ago(1)}),
        ])

        self.assertEqual(self.cart_ids(self.member_client), ["100000000002"])
        self.assertEqual([row["ct_id"] for row in self.member_rows()], ["100000000002"])

    def test_lines_stored_before_the_time_existed_are_kept_and_stamped(self):
        self.set_option("de_cart_keep_term", 1)
        self.seed_member_cart([self.line("100000000001")])

        self.assertEqual(self.cart_ids(self.member_client), ["100000000001"])
        self.assertIsInstance(self.member_rows()[0][CART_TIME_KEY], int)

    def test_expired_lines_are_not_ordered(self):
        Config.objects.update_or_create(name="de_bank_use", defaults={"value": "1"})
        Config.objects.update_or_create(name="de_bank_account", defaults={"value": "Bank 1-1 Holder"})
        self.seed_member_cart([self.line("100000000001", **{CART_TIME_KEY: days_ago(30)})])

        response = self.member_client.post(f"{API}/orders", {
            "od_name": "Keeper", "od_hp": "010-1111-2222", "od_b_name": "Keeper", "od_b_hp": "010-1111-2222",
            "od_b_zip": "06236", "od_b_addr1": "Seoul", "od_settle_case": "bank",
            "od_bank_account": "Bank 1-1 Holder", "od_deposit_name": "Keeper",
        }, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get("code"), "cart_empty")


class GuestCartLifetimeTests(CartSettingsBase):
    def session_key(self):
        return self.guest.cookies[settings.SESSION_COOKIE_NAME].value

    def test_without_the_option_a_guest_cart_keeps_the_default_session_lifetime(self):
        response = self.add(self.guest)

        session = self.guest.session
        self.assertEqual(session.get_expiry_age(), settings.SESSION_COOKIE_AGE)
        self.assertNotIn(GUEST_CART_KEEP_FLAG, session)
        self.assertEqual(int(response.cookies[settings.SESSION_COOKIE_NAME]["max-age"]), settings.SESSION_COOKIE_AGE)

    def test_with_the_option_a_guest_cart_session_lasts_the_keep_term(self):
        self.set_option("de_guest_cart_use", 1)
        self.set_option("de_cart_keep_term", 10)

        response = self.add(self.guest)

        keep = 10 * SECONDS_PER_DAY
        self.assertEqual(int(response.cookies[settings.SESSION_COOKIE_NAME]["max-age"]), keep)
        stored = Session.objects.get(session_key=self.session_key())
        remaining = (stored.expire_date - timezone.now()).total_seconds()
        self.assertGreater(remaining, keep - 120)
        self.assertEqual(self.guest.session.get_expiry_age(), keep)

    def test_the_long_lifetime_survives_a_later_unchanged_request(self):
        self.set_option("de_guest_cart_use", 1)
        self.add(self.guest)

        self.guest.get(f"{API}/cart")

        self.assertEqual(self.guest.session.get_expiry_age(), 15 * SECONDS_PER_DAY)

    def test_emptying_the_cart_or_turning_the_option_off_gives_back_the_default_lifetime(self):
        self.set_option("de_guest_cart_use", 1)
        self.add(self.guest)
        self.guest.delete(f"{API}/cart")
        self.assertEqual(self.guest.session.get_expiry_age(), settings.SESSION_COOKIE_AGE)

        self.add(self.guest)
        self.set_option("de_guest_cart_use", 0)
        self.add(self.guest)
        session = self.guest.session
        self.assertEqual(session.get_expiry_age(), settings.SESSION_COOKIE_AGE)
        self.assertNotIn(GUEST_CART_KEEP_FLAG, session)

    def test_signing_in_resets_the_session_to_the_default_lifetime(self):
        self.set_option("de_guest_cart_use", 1)
        self.add(self.guest)
        self.assertEqual(self.guest.session.get_expiry_age(), 15 * SECONDS_PER_DAY)

        response = self.guest.post("/api/v1/auth/login", {"mb_id": "keeper", "mb_password": PASSWORD}, format="json")

        self.assertEqual(response.status_code, 200, response.content[:300])
        session = self.guest.session
        self.assertEqual(session.get_expiry_age(), settings.SESSION_COOKIE_AGE)
        self.assertNotIn(GUEST_CART_KEEP_FLAG, session)
        self.assertNotIn(SHOP_CART_SESSION_KEY, session)
        self.assertEqual(len(self.member_rows()), 1)

    def test_a_django_session_sign_in_also_resets_the_long_lifetime(self):
        # e.g. a staff member who shopped as a guest and then signs in at /admin/login/
        self.set_option("de_guest_cart_use", 1)
        self.add(self.guest)
        self.assertEqual(self.guest.session.get_expiry_age(), 15 * SECONDS_PER_DAY)

        self.guest.force_login(get_user_model().objects.get(username="keeper"))

        session = self.guest.session
        self.assertEqual(session.get_expiry_age(), settings.SESSION_COOKIE_AGE)
        self.assertNotIn(GUEST_CART_KEEP_FLAG, session)


class LoginMergeKeepTermTests(CartSettingsBase):
    def test_expired_guest_and_member_lines_are_not_carried_over_at_sign_in(self):
        self.seed_member_cart([
            self.line("200000000001", **{CART_TIME_KEY: days_ago(20)}),
            self.line("200000000002", **{CART_TIME_KEY: days_ago(2)}),
        ])
        self.seed_guest_cart([
            self.line("100000000001", **{CART_TIME_KEY: days_ago(20)}),
            self.line("100000000002", **{CART_TIME_KEY: days_ago(2)}),
            self.line("100000000003"),
        ])

        response = self.guest.post("/api/v1/auth/login", {"mb_id": "keeper", "mb_password": PASSWORD}, format="json")

        self.assertEqual(response.status_code, 200, response.content[:300])
        rows = self.member_rows()
        self.assertEqual([row["ct_id"] for row in rows], ["200000000002", "100000000002", "100000000003"])
        self.assertTrue(all(isinstance(row[CART_TIME_KEY], int) for row in rows))
