"""Behaviour tests for the public read endpoints in gnu_jango/api/v1_views.py.

Covers /api/v1/status, /config and /menus, the removal of the unused /posts and /posts/<pk>
views, and the writer side-menu data.
"""

import itertools
import warnings
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import CacheKeyWarning, cache
from django.test import TestCase
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.api import v1_views
from gnu_jango.bbs.models import Board, Group, Post
from gnu_jango.config import config as site_config
from gnu_jango.config.models import Config
from gnu_jango.core.models import Site_menu
from gnu_jango.users.models import Profile
from gnu_jango.utils import users as user_utils

API = "/api/v1"

SECRET_CONFIG_VALUES = {
    "cf_recaptcha_secret_key": "recaptcha-secret-value",
    "cf_recaptcha_site_key": "recaptcha-site-value",
    "cf_kakao_client_secret": "kakao-client-secret-value",
    "cf_kakao_rest_key": "kakao-rest-key-value",
    "cf_naver_secret": "naver-secret-value",
    "cf_google_secret": "google-secret-value",
    "cf_facebook_secret": "facebook-secret-value",
    "cf_twitter_secret": "twitter-secret-value",
    "cf_payco_secret": "payco-secret-value",
}


def make_user(username, level=2, **fields):
    user = get_user_model().objects.create(username=username, email=f"{username}@example.test", **fields)
    profile, _ = Profile.objects.get_or_create(user=user)
    profile.user_level = level
    profile.save()
    return user


def bearer(user):
    return {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}


_slug_counter = itertools.count(1)


def make_post(board, subject="A post", user=None, wr_num=-1, **fields):
    now = timezone.now()
    fields.setdefault("wr_content", f"{subject} body")
    fields.setdefault("wr_name", user.username if user else "guest")
    fields.setdefault("wr_slug", f"post-{next(_slug_counter)}")
    post = Post.objects.create(
        board=board, wr_num=wr_num, wr_subject=subject, user=user, wr_datetime=now, wr_last=now, **fields
    )
    post.wr_parent = post.pk
    post.save(update_fields=["wr_parent"])
    return post


class V1ViewsTestCase(TestCase):
    """Shared fixtures: one open board, an author, another member, a superuser."""

    @classmethod
    def setUpTestData(cls):
        cls.group = Group.objects.create(gr_id="v1grp", gr_subject="V1 group")
        cls.board = Board.objects.create(
            group=cls.group, bo_subject="Open board", bo_table="v1open", bo_skin="basic", bo_mobile_skin="basic"
        )
        cls.author = make_user("v1author")
        cls.reader = make_user("v1reader")
        cls.admin = make_user("v1admin", is_superuser=True, is_staff=True)

    def setUp(self):
        # The menu cache and the site config live in process-wide caches.
        cache.clear()
        site_config.clear()
        self.addCleanup(site_config.clear)
        self.addCleanup(cache.clear)

    def get(self, route, user=None, **params):
        extra = bearer(user) if user else {}
        return self.client.get(f"{API}/{route}", params, **extra)

    def body(self, response, status=200):
        self.assertEqual(response.status_code, status, response.content[:300])
        return response.json()


class StatusEndpointTests(V1ViewsTestCase):
    def test_a_guest_gets_the_service_summary_in_the_standard_envelope(self):
        payload = self.body(self.get("status"))

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["success"])
        data = payload["data"]
        self.assertEqual(data["service"], "gnu_jango")
        self.assertEqual(data["api_version"], "v1")
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["capabilities"]["auth"])
        self.assertEqual(data["capabilities"]["shop"], "planned")

    def test_the_counts_follow_the_stored_rows(self):
        make_post(self.board, "Counted", user=self.author)
        Site_menu.objects.create(me_code="10", me_name="Home", me_link="/", me_use=1)

        data = self.body(self.get("status"))["data"]

        self.assertEqual(data["counts"]["groups"], 1)
        self.assertEqual(data["counts"]["boards"], 1)
        self.assertEqual(data["counts"]["posts"], 1)
        self.assertEqual(data["counts"]["comments"], 0)
        self.assertEqual(data["counts"]["members"], 3)
        self.assertEqual(data["counts"]["menus"], 1)

    def test_latest_post_time_is_null_without_posts(self):
        data = self.body(self.get("status"))["data"]

        self.assertIsNone(data["latest_post_at"])

    def test_latest_post_time_is_the_newest_post(self):
        older = make_post(self.board, "Older", wr_num=-1)
        newer = make_post(self.board, "Newer", wr_num=-2)
        Post.objects.filter(pk=older.pk).update(wr_datetime=timezone.now() - timedelta(days=3))
        newer.refresh_from_db()

        data = self.body(self.get("status"))["data"]

        self.assertEqual(data["latest_post_at"], newer.wr_datetime.isoformat())

    def test_status_cannot_be_written_to(self):
        response = self.client.post(f"{API}/status", {}, **bearer(self.author))

        self.assertEqual(response.status_code, 405)


class ConfigEndpointTests(V1ViewsTestCase):
    def test_the_public_site_settings_are_returned_to_guests(self):
        Config.objects.create(name="cf_title", value="Test Shop")
        Config.objects.create(name="cf_cut_name", value="7")

        data = self.body(self.get("config"))["data"]

        self.assertEqual(data["cf_title"], "Test Shop")
        self.assertEqual(data["cf_cut_name"], 7)
        self.assertIn("cf_use_point", data)

    def test_a_site_title_is_always_present(self):
        data = self.body(self.get("config"))["data"]

        self.assertTrue(data["cf_title"])

    def test_only_the_whitelisted_keys_are_exposed(self):
        data = self.body(self.get("config"))["data"]

        self.assertLessEqual(set(data), set(v1_views.PUBLIC_CONFIG_KEYS))

    def test_third_party_secrets_stored_in_the_config_are_not_exposed(self):
        for name, value in SECRET_CONFIG_VALUES.items():
            Config.objects.create(name=name, value=value)
        site_config.clear()

        response = self.get("config")

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        for name, value in SECRET_CONFIG_VALUES.items():
            self.assertNotIn(value, body, name)
            self.assertNotIn(name, body)

    def test_mail_and_payment_settings_are_not_exposed(self):
        data = self.body(self.get("config"))["data"]

        for key in data:
            lowered = key.lower()
            for forbidden in ("pass", "secret", "smtp", "_key", "pg_", "kcp", "inicis", "toss"):
                self.assertNotIn(forbidden, lowered, key)

    def test_config_cannot_be_written_to(self):
        response = self.client.post(f"{API}/config", {"cf_title": "x"}, **bearer(self.admin))

        self.assertEqual(response.status_code, 405)


class MenusEndpointTests(V1ViewsTestCase):
    def setUp(self):
        super().setUp()
        self.shop = Site_menu.objects.create(
            me_code="20", me_name="Shop", me_link="/shop", me_type="Link", me_order=2, me_use=1, me_mobile_use=1
        )
        self.home = Site_menu.objects.create(
            me_code="10", me_name="Home", me_link="/", me_type="Link", me_order=1, me_use=1, me_mobile_use=1
        )
        self.sale = Site_menu.objects.create(
            me_code="2010", me_name="Sale", me_link="/shop/sale", me_type="Link", me_order=1, me_use=1
        )
        self.news = Site_menu.objects.create(
            me_code="2020", me_name="News", me_link="/shop/news", me_type="Link", me_order=2, me_use=1
        )

    def test_top_level_menus_are_returned_in_display_order_with_their_children(self):
        data = self.body(self.get("menus"))["data"]

        self.assertEqual([item["me_name"] for item in data], ["Home", "Shop"])
        self.assertEqual(data[0]["children"], [])
        self.assertEqual([child["me_name"] for child in data[1]["children"]], ["Sale", "News"])
        self.assertEqual(data[1]["children"][0]["me_link"], "/shop/sale")

    def test_each_item_carries_the_documented_fields(self):
        item = self.body(self.get("menus"))["data"][0]

        self.assertEqual(
            set(item),
            {
                "id", "me_id", "me_code", "me_name", "me_link", "me_type", "me_type_pk",
                "me_target", "me_order", "me_use", "me_mobile_use", "children",
            },
        )

    def test_a_board_menu_links_to_the_boards_page(self):
        Site_menu.objects.create(
            me_code="30", me_name="Board", me_link="ignored", me_type="Board",
            me_type_pk=self.board.pk, me_order=3, me_use=1,
        )

        data = self.body(self.get("menus"))["data"]

        link = next(item["me_link"] for item in data if item["me_name"] == "Board")
        self.assertNotEqual(link, "ignored")
        self.assertIn(self.board.bo_table, link)

    def test_an_empty_menu_table_returns_an_empty_list(self):
        Site_menu.objects.all().delete()

        data = self.body(self.get("menus"))["data"]

        self.assertEqual(data, [])

    def test_a_child_whose_parent_is_missing_is_not_listed(self):
        Site_menu.objects.create(me_code="9910", me_name="Orphan", me_link="/o", me_use=1)

        names = [child["me_name"] for item in self.body(self.get("menus"))["data"] for child in item["children"]]

        self.assertNotIn("Orphan", names)

    def test_the_path_parameter_does_not_change_the_menu(self):
        plain = self.body(self.get("menus"))["data"]
        with_path = self.body(self.get("menus", path="/shop/sale"))["data"]

        self.assertEqual(plain, with_path)

    def test_an_oversized_or_odd_path_parameter_does_not_break_the_endpoint(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            for path in ("x" * 5000, "line\nbreak and spaces", "éè\U0001f600"):
                response = self.get("menus", path=path)
                self.assertEqual(response.status_code, 200, path[:20])

    # Fixed: the visitor-supplied ?path= was is used verbatim in the menu cache key
    # (gnu_jango/templatetags/gnu_menus.py:68), so any request can create unbounded cache
    # entries, and a long path or one with spaces/newlines raises CacheKeyWarning (an error on
    # memcached-style backends, where the endpoint would then answer 500).
    def test_a_visitor_supplied_path_does_not_produce_an_invalid_cache_key(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.get("menus", path="line\nbreak and spaces")
            self.get("menus", path="x" * 5000)

        self.assertEqual([w for w in caught if issubclass(w.category, CacheKeyWarning)], [])

    def test_members_get_the_same_menu_as_guests(self):
        guest = self.body(self.get("menus"))["data"]
        member = self.body(self.get("menus", user=self.reader))["data"]

        self.assertEqual(guest, member)

    # Fixed: _menu_payload()/get_items() did not filter on me_use, so menus an administrator
    # switched off (gnu_jango/templatetags/gnu_menus.py:78-82, gnu_jango/api/v1_views.py:51-72)
    # are published. The PHP original selects only me_use = '1'
    # (gnuboard5_3/lib/get_data.lib.php:108).
    def test_menus_switched_off_by_the_administrator_are_not_published(self):
        Site_menu.objects.create(me_code="40", me_name="Hidden", me_link="/hidden", me_order=4, me_use=0)
        Site_menu.objects.filter(pk=self.sale.pk).update(me_use=0)

        data = self.body(self.get("menus"))["data"]

        names = [item["me_name"] for item in data] + [c["me_name"] for item in data for c in item["children"]]
        self.assertNotIn("Hidden", names)
        self.assertNotIn("Sale", names)

    # Fixed: get_items() cached the menu for MENU_CACHE_TIME (30 minutes) and nothing
    # invalidates the cache when a Site_menu row is saved, so an edit made in the admin is not
    # visible to the Next.js site (gnu_jango/templatetags/gnu_menus.py:57-70,121-122).
    def test_a_menu_added_after_the_first_request_is_visible_on_the_next_one(self):
        self.body(self.get("menus"))
        Site_menu.objects.create(me_code="50", me_name="Fresh", me_link="/fresh", me_order=5, me_use=1)

        names = [item["me_name"] for item in self.body(self.get("menus"))["data"]]

        self.assertIn("Fresh", names)


class RemovedPostViewsTests(V1ViewsTestCase):
    """/posts and /posts/<pk> duplicated the board API with weaker rules and had no client."""

    def test_the_old_post_list_and_detail_routes_are_gone(self):
        post = make_post(self.board, "Old route")

        self.assertEqual(self.get("posts").status_code, 404)
        self.assertEqual(self.get(f"posts/{post.pk}").status_code, 404)

    def test_the_board_post_detail_still_answers(self):
        post = make_post(self.board, "Board route")

        self.assertEqual(self.get(f"posts/{self.board.bo_table}/{post.pk}").status_code, 200)


class SideviewDataTests(V1ViewsTestCase):
    """Gnuboard5 get_sideview: a form-mail link, never the member's account e-mail."""

    def test_the_member_account_email_is_not_included(self):
        data = user_utils.get_sideview_data(self.author)

        self.assertTrue(data["is_user"])
        self.assertNotIn(self.author.email, data.values())
        self.assertEqual(data["email"], "")

    def test_a_changed_nickname_shows_on_the_next_call(self):
        user_utils.get_sideview_data(self.author)
        Profile.objects.filter(user=self.author).update(nickname="Renamed")
        self.author.refresh_from_db()

        self.assertEqual(user_utils.get_sideview_data(self.author)["name"], "Renamed")

    def test_guests_do_not_share_one_cached_entry(self):
        with_mail = user_utils.get_sideview_data(None, name="Guest A", email="a@example.test")
        without = user_utils.get_sideview_data(None, name="Guest B")

        self.assertEqual(with_mail["mail_url"], "#")
        self.assertEqual(without["mail_url"], "")
