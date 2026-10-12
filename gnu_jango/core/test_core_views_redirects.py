"""Legacy Gnuboard5 URL redirects, the Next.js static-export views, sitemap/robots/RSS and data files.

Covers gnu_jango/core/legacy_redirects.py and gnu_jango/core/views.py.  Behaviour taken from the
PHP original (C:\\xampp824\\www\\gnuboard5_3) carries a "Rule:" comment naming its source.
"""

import json
import os
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone

from gnu_jango.bbs.models import Board, Group, Post
from gnu_jango.shop.models import ShopCategory, ShopProduct

LEGACY_BASE = "https://legacy.example"
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def split_location(response):
    """Return (scheme+host, path, query dict) of a redirect response."""
    parts = urlsplit(response["Location"])
    return f"{parts.scheme}://{parts.netloc}", parts.path, parse_qs(parts.query, keep_blank_values=True)


def expected_target(target):
    parts = urlsplit(target)
    return parts.path, parse_qs(parts.query, keep_blank_values=True)


class RedirectAssertions:
    def assertLocalRedirect(self, url, target, status=307, **extra):
        response = self.client.get(url, **extra)
        self.assertEqual(response.status_code, status, f"{url}: {response.status_code}")
        origin, path, query = split_location(response)
        self.assertEqual(origin, "http://testserver", f"{url}: left the site -> {response['Location']}")
        self.assertEqual((path, query), expected_target(target), f"{url} -> {response['Location']}")
        return response

    def assertLegacyRedirect(self, url, target, status=307):
        response = self.client.get(url)
        self.assertEqual(response.status_code, status, f"{url}: {response.status_code}")
        origin, path, query = split_location(response)
        self.assertEqual(origin, LEGACY_BASE, f"{url} -> {response['Location']}")
        self.assertEqual((path, query), expected_target(target), f"{url} -> {response['Location']}")
        return response

    def assertStaysOnSite(self, url, data=None, **extra):
        response = self.client.get(url, data, **extra)
        self.assertIn(response.status_code, (301, 302, 307, 308), f"{url}: {response.status_code}")
        location = response["Location"]
        self.assertTrue(location.startswith("http://testserver/"), f"{url} -> {location}")
        self.assertFalse(location.startswith("http://testserver//"), f"{url} -> {location}")
        self.assertNotIn("\n", location)
        self.assertNotIn("\r", location)
        return response


class LegacyBbsRedirectTests(RedirectAssertions, TestCase):
    def test_bbs_php_pages_redirect_to_the_matching_nextjs_page(self):
        cases = {
            "/bbs/login.php": "/login",
            "/bbs/login.php?redirect=/mypage&rewrite=1": "/login?redirect=/mypage",
            "/bbs/login.php?url=/shop/cart": "/login?redirect=/shop/cart",
            "/bbs/register.php?rewrite=1": "/register",
            "/bbs/register_form.php": "/register",
            "/bbs/register_result.php": "/register/result",
            "/bbs/email_certify.php?mb_id=bob&mb_md5=abc123": "/email-certify?mb_id=bob&token=abc123",
            "/bbs/email_certify.php": "/email-certify",
            "/bbs/password_lost.php": "/forgot-password",
            "/bbs/poll_result.php?po_id=1": "/polls?po_id=1",
            "/bbs/qalist.php": "/mypage/qas",
            "/bbs/qaview.php?qa_id=7": "/mypage/qas/7",
            "/bbs/qaview.php?qa_id=seven": "/mypage/qas",
            "/bbs/qawrite.php": "/mypage/qas/new",
            "/bbs/qawrite.php?w=r&qa_id=3": "/mypage/qas/new?reply_to=3",
            "/bbs/qawrite.php?w=u&qa_id=3": "/mypage/qas/3",
            "/bbs/qawrite.php?w=u&qa_id=x": "/mypage/qas/new",
            "/bbs/memo.php": "/mypage/memos",
            "/bbs/memo.php?kind=send": "/mypage/memos?type=send",
            "/bbs/memo.php?kind=recv": "/mypage/memos",
            "/bbs/memo_form.php?me_recv_mb_id=bob": "/mypage/memos/new?recv=bob",
            "/bbs/memo_form.php": "/mypage/memos/new",
            "/bbs/memo_view.php?me_id=5&kind=send": "/mypage/memos/5?type=send",
            "/bbs/memo_view.php?me_id=five": "/mypage/memos",
            "/bbs/profile.php?mb_id=bob": "/members/bob",
            "/bbs/profile.php?mb_id=a/b": "/",
            "/bbs/point.php": "/mypage/points",
            "/bbs/scrap.php": "/mypage/scraps",
            "/bbs/faq.php": "/faq",
            "/bbs/new.php": "/recent",
            "/bbs/search.php?stx=hello": "/search?q=hello",
            "/bbs/search.php?q=hello": "/search?q=hello",
            "/bbs/search.php": "/search",
            "/bbs/group.php?gr_id=community": "/boards?group=community",
            "/bbs/group.php": "/boards",
        }
        for url, target in cases.items():
            with self.subTest(url=url):
                self.assertLocalRedirect(url, target)

    def test_board_php_redirects_to_the_board_or_post_page(self):
        cases = {
            "/bbs/board.php?bo_table=free": "/free",
            "/bbs/board.php?bo_table=free&wr_id=12&page=2": "/free/12?page=2",
            "/bbs/board.php?bo_table=free&wr_seo_title=hello-world": "/free/hello-world/",
            "/bbs/board.php?bo_table=free&wr_id=abc": "/free",
            "/bbs/board.php": "/boards",
            "/bbs/board.php?wr_id=12": "/boards",
            "/bbs/write.php?bo_table=free": "/free/write",
            "/bbs/write.php": "/boards",
            "/bbs/content.php?co_id=company": "/content/company",
            "/bbs/content.php?co_seo_title=about-us": "/content/about-us/",
            "/bbs/content.php": "/content",
        }
        for url, target in cases.items():
            with self.subTest(url=url):
                self.assertLocalRedirect(url, target)

    def test_huge_and_unicode_post_ids_do_not_crash_the_redirect(self):
        huge = "9" * 400
        response = self.assertLocalRedirect(f"/bbs/board.php?bo_table=free&wr_id={huge}", f"/free/{huge}")
        self.assertEqual(response.status_code, 307)
        for value in ("한글", "%F0%9F%98%80", "../..", "1;DROP TABLE", "\x00"):
            with self.subTest(wr_id=value):
                response = self.client.get("/bbs/board.php", {"bo_table": "free", "wr_id": value})
                self.assertEqual(response.status_code, 307)

    def test_board_redirect_does_not_look_the_post_up_so_a_secret_title_cannot_leak(self):
        group = Group.objects.create(gr_id="leak", gr_subject="Leak")
        board = Board.objects.create(group=group, bo_subject="Private", bo_table="private", bo_skin="basic", bo_mobile_skin="basic", bo_read_level=10)
        post = Post.objects.create(
            board=board, wr_subject="TOP-SECRET-SUBJECT", wr_content="body", wr_slug="top-secret-subject",
            wr_option="secret", wr_datetime=timezone.now(), wr_name="a",
        )

        response = self.client.get(f"/bbs/board.php?bo_table=private&wr_id={post.pk}")

        self.assertEqual(response.status_code, 307)
        self.assertNotIn("secret", response["Location"].lower())
        self.assertNotIn("TOP-SECRET-SUBJECT", response.content.decode())

    def test_user_supplied_segments_are_percent_encoded_in_the_location(self):
        response = self.client.get("/bbs/board.php", {"bo_table": "a/b?c#d e", "wr_id": "3"})
        self.assertEqual(urlsplit(response["Location"]).path, "/a%2Fb%3Fc%23d%20e/3")
        response = self.client.get("/bbs/content.php", {"co_id": "x/../y"})
        self.assertEqual(urlsplit(response["Location"]).path, "/content/x%2F..%2Fy")

    def test_crlf_in_parameters_cannot_split_the_response(self):
        for url in (
            "/bbs/board.php?bo_table=a%0d%0aSet-Cookie:%20pwn=1&wr_id=1",
            "/bbs/search.php?stx=a%0d%0aSet-Cookie:%20pwn=1",
            "/bbs/login.php?redirect=/x%0d%0aSet-Cookie:%20pwn=1",
            "/bbs/profile.php?mb_id=a%0d%0ab",
            "/shop/item.php?it_id=a%0d%0aSet-Cookie:%20pwn=1",
        ):
            with self.subTest(url=url):
                response = self.assertStaysOnSite(url)
                self.assertNotIn("Set-Cookie", dict(response.headers))
                self.assertNotIn("pwn", response.cookies)

    def test_bbs_dot_segments_do_not_escape_the_prefix(self):
        for url in ("/bbs/../etc/passwd.php", "/bbs/a/../b.php", "/bbs/./x.php", "/bbs/a/b/c/d.php", "/bbs/a b.php", "/bbs/한글.php"):
            with self.subTest(url=url):
                self.assertLocalRedirect(url, "/")

    @override_settings(LEGACY_GNUBOARD5_BASE_URL=LEGACY_BASE + "/")
    def test_unmapped_bbs_files_are_handed_to_the_legacy_php_site(self):
        self.assertLegacyRedirect("/bbs/download.php?bo_table=free&wr_id=1&no=0", "/bbs/download.php?bo_table=free&wr_id=1&no=0")
        self.assertLegacyRedirect("/bbs/ajax/thing.php?a=1", "/bbs/ajax/thing.php?a=1")

    @override_settings(LEGACY_GNUBOARD5_BASE_URL="")
    def test_unmapped_bbs_files_fall_back_to_the_home_page_without_a_legacy_site(self):
        self.assertLocalRedirect("/bbs/download.php?bo_table=free", "/?bo_table=free")

    def test_post_to_a_legacy_page_is_redirected_with_a_method_preserving_status(self):
        response = self.client.post("/bbs/login.php", {"mb_id": "a", "mb_password": "secret-pass"})
        self.assertEqual(response.status_code, 307)
        # Credentials must not be copied into the redirect URL.
        self.assertNotIn("secret-pass", response["Location"])

    def test_head_request_to_a_legacy_page_redirects_without_a_body(self):
        response = self.client.head("/bbs/board.php?bo_table=free")
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.content, b"")


class LegacyLoginRedirectParameterTests(RedirectAssertions, TestCase):
    """bbs/login.php?redirect=... must never be turned into an open redirect target."""

    UNSAFE = (
        "//evil.example",
        "///evil.example/x",
        "/\\evil.example",
        "\\\\evil.example",
        "https://evil.example",
        "https:evil.example",
        "http:/evil.example",
        "evil.example",
        "javascript:alert(1)",
        "data:text/html,x",
        "/x\r\nSet-Cookie: a=b",
        "/x\nLocation: https://evil.example",
    )

    def test_off_site_or_malformed_targets_are_dropped(self):
        for value in self.UNSAFE:
            with self.subTest(redirect=value):
                response = self.assertStaysOnSite("/bbs/login.php", {"redirect": value})
                self.assertEqual(urlsplit(response["Location"]).path, "/login")
                self.assertNotIn("redirect", parse_qs(urlsplit(response["Location"]).query))

    def test_the_url_alias_is_validated_like_redirect(self):
        for value in self.UNSAFE:
            with self.subTest(url=value):
                response = self.assertStaysOnSite("/bbs/login.php", {"url": value})
                self.assertNotIn("redirect", parse_qs(urlsplit(response["Location"]).query))

    def test_a_local_absolute_path_is_kept(self):
        response = self.client.get("/bbs/login.php", {"redirect": "/shop/cart?x=1"})
        self.assertEqual(parse_qs(urlsplit(response["Location"]).query)["redirect"], ["/shop/cart?x=1"])

    def test_a_tab_or_control_character_cannot_hide_a_second_slash(self):
        # Rule: browsers drop tab/newline characters while parsing, so "/\t/evil.example" becomes
        # "//evil.example"; a redirect target with any control character is dropped.
        bad = [value for value in ("/\t/evil.example", "/\x0b/evil.example", "/\x0c/evil.example", "/\x00/evil.example")
               if "redirect" in parse_qs(urlsplit(self.client.get("/bbs/login.php", {"redirect": value})["Location"]).query)]
        self.assertEqual(bad, [])


class LegacyShopRedirectTests(RedirectAssertions, TestCase):
    def test_shop_php_pages_redirect_to_the_matching_nextjs_page(self):
        cases = {
            "/shop/index.php": "/shop",
            "/shop/cart.php": "/shop/cart",
            "/shop/list.php?ca_id=10": "/shop/list-10",
            "/shop/category.php?ca_id=10&page=2": "/shop/list-10?page=2",
            "/shop/list.php": "/shop/products",
            "/shop/coupon.php": "/mypage/coupons",
            "/shop/couponzone.php": "/shop/couponzone",
            "/shop/event.php?ev_id=3": "/shop/events/3",
            "/shop/event.php": "/shop/events",
            "/shop/item.php?it_id=I1": "/shop/I1",
            "/shop/item.php?it_id=I1&sca=x": "/shop/I1?sca=x",
            "/shop/item.php?it_seo_title=nice-item": "/shop/nice-item/",
            "/shop/item.php": "/shop/products",
            "/shop/iteminfo.php?it_id=I1&info=use": "/shop/I1?tab=reviews",
            "/shop/iteminfo.php?it_id=I1&info=review": "/shop/I1?tab=reviews",
            "/shop/iteminfo.php?it_id=I1&info=qa": "/shop/I1?tab=qa",
            "/shop/iteminfo.php?it_id=I1&info=qna": "/shop/I1?tab=qa",
            "/shop/iteminfo.php?it_id=I1": "/shop/I1",
            "/shop/iteminfo.php": "/shop/products",
            "/shop/itemqa.php?it_id=I1": "/shop/I1?tab=qa",
            "/shop/itemqaform.php?it_id=I1": "/shop/I1?tab=qa&form=qa",
            "/shop/itemrecommend.php?it_id=I1": "/shop/I1?modal=recommend",
            "/shop/itemstocksms.php?it_id=I1": "/shop/I1?modal=restock",
            "/shop/itemuse.php?it_id=I1": "/shop/I1?tab=reviews",
            "/shop/itemuseform.php?it_id=I1": "/shop/I1?tab=reviews&form=review",
            "/shop/largeimage.php": "/shop/largeimage",
            "/shop/listtype.php?type=3": "/shop/type-3",
            "/shop/listtype.php?type=9": "/shop/products",
            "/shop/listtype.php": "/shop/products",
            "/shop/mypage.php": "/mypage",
            "/shop/orderaddress.php": "/mypage/addresses",
            "/shop/orderform.php": "/shop/order",
            "/shop/orderform.php?sw_direct=1": "/shop/order?direct=1",
            "/shop/orderform.php?sw_direct=0": "/shop/order",
            "/shop/orderinquiry.php": "/shop/orders",
            "/shop/orderinquiryview.php?od_id=2026": "/shop/orders/2026",
            "/shop/orderinquirycancel.php?od_id=2026": "/shop/orders/2026",
            "/shop/orderinquiryview.php": "/shop/orders",
            "/shop/personalpay.php": "/shop/personalpay",
            "/shop/personalpayform.php?pp_id=5": "/shop/personalpay/5/pay",
            "/shop/personalpayform.php": "/shop/personalpay",
            "/shop/personalpayresult.php?pp_id=5": "/shop/personalpay/5",
            "/shop/personalpayresult.php": "/shop/personalpay",
            "/shop/search.php": "/shop/search",
            "/shop/wishlist.php": "/shop/wishlist",
        }
        for url, target in cases.items():
            with self.subTest(url=url):
                self.assertLocalRedirect(url, target)

    def test_item_php_encodes_hostile_item_ids(self):
        for hostile in ("//evil.example", "..", "/\\evil.example", "a b", "https://evil.example", "한글", "x" * 3000):
            with self.subTest(it_id=hostile[:30]):
                response = self.assertStaysOnSite("/shop/item.php", {"it_id": hostile})
                self.assertEqual(len(urlsplit(response["Location"]).path.split("/")), 3, response["Location"][:120])

    @override_settings(LEGACY_GNUBOARD5_BASE_URL=LEGACY_BASE)
    def test_payment_and_ajax_files_are_handed_to_the_legacy_php_site(self):
        self.assertLegacyRedirect("/shop/cartupdate.php?act=buy", "/shop/cartupdate.php?act=buy")
        self.assertLegacyRedirect("/shop/orderformupdate.php", "/shop/orderformupdate.php")
        self.assertLegacyRedirect("/shop/inicis/INIstdpay.php?x=1", "/shop/inicis/INIstdpay.php?x=1")
        self.assertLegacyRedirect("/shop/kcp/a/b.php", "/shop/kcp/a/b.php")
        self.assertLegacyRedirect("/shop/unknown-page.php?x=1", "/shop/unknown-page.php?x=1")

    @override_settings(LEGACY_GNUBOARD5_BASE_URL="")
    def test_without_a_legacy_site_unmapped_shop_files_return_to_the_shop(self):
        self.assertLocalRedirect("/shop/unknown-page.php?x=1", "/shop?x=1")
        self.assertLocalRedirect("/shop/cartupdate.php", "/shop")

    def test_personalpay_handoff_page_escapes_the_payment_id_and_is_private(self):
        payload = '"><script>alert(1)</script>'

        response = self.client.get("/shop/personalpayform.php", {"nextjs_handoff": "1", "pp_id": payload})

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("noindex", body)
        self.assertIn("noindex", response["X-Robots-Tag"])

    def test_personalpay_handoff_without_an_id_reports_the_missing_id(self):
        response = self.client.get("/shop/personalpayform.php", {"nextjs_handoff": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("Missing personal payment id.", response.content.decode())


class LegacyMobileRedirectTests(RedirectAssertions, TestCase):
    def test_mobile_root_and_index_redirect_home(self):
        for url in ("/mobile", "/mobile/", "/mobile/index.php", "/mobile/INDEX.PHP"):
            with self.subTest(url=url):
                self.assertLocalRedirect(url, "/")

    def test_mobile_group_and_content_pages_map_to_nextjs_pages(self):
        cases = {
            "/mobile/group.php?gr_id=community": "/boards?group=community",
            "/mobile/group.php": "/boards",
            "/mobile/content.php?co_id=company": "/content/company",
            "/mobile/content.php?co_seo_title=about": "/content/about/",
            "/mobile/content.php": "/content",
        }
        for url, target in cases.items():
            with self.subTest(url=url):
                self.assertLocalRedirect(url, target)

    def test_mobile_shop_pages_map_to_the_desktop_nextjs_routes(self):
        cases = {
            "/mobile/shop": "/shop",
            "/mobile/shop/item.php?it_id=I1": "/shop/I1",
            "/mobile/shop/list.php?ca_id=20": "/shop/list-20",
            "/mobile/shop/coupon.php": "/mypage/coupons",
            "/mobile/shop/cartupdate.php": "/shop/cartupdate.php",
            "/mobile/shop/itemqalist.php": "/shop/itemqalist.php",
        }
        for url, target in cases.items():
            with self.subTest(url=url):
                self.assertLocalRedirect(url, target)

    @override_settings(LEGACY_GNUBOARD5_BASE_URL=LEGACY_BASE)
    def test_other_mobile_files_are_handed_to_the_legacy_php_site(self):
        self.assertLegacyRedirect("/mobile/skin/a/b.php?x=1", "/mobile/skin/a/b.php?x=1")
        self.assertLegacyRedirect("/mobile/shop/inicis/pay.php", "/mobile/shop/inicis/pay.php")
        self.assertLegacyRedirect("/mobile/shop/a/b.php", "/mobile/shop/a/b.php")

    def test_mobile_traversal_and_odd_segments_land_on_the_home_page(self):
        for url in ("/mobile/../admin", "/mobile/./x", "/mobile/a b", "/mobile/한글.php", "/mobile//x"):
            with self.subTest(url=url):
                self.assertLocalRedirect(url, "/")

    @override_settings(LEGACY_GNUBOARD5_BASE_URL="")
    def test_mobile_shop_fallback_without_a_legacy_site(self):
        self.assertLocalRedirect("/mobile/shop/inicis/pay.php", "/shop")
        self.assertLocalRedirect("/mobile/skin/x.php", "/")


class CanonicalRedirectTests(RedirectAssertions, TestCase):
    def test_boards_paths_redirect_to_the_short_board_urls(self):
        cases = {
            "/boards/free": "/free",
            "/boards/free/12": "/free/12",
            "/boards/free/write": "/free/write",
            "/boards/free/rss": "/rss/free",
            "/boards/free/RSS": "/rss/free",
            "/boards/free/12?page=3": "/free/12?page=3",
        }
        for url, target in cases.items():
            with self.subTest(url=url):
                self.assertLocalRedirect(url, target, status=308)

    def test_boards_paths_with_unsafe_segments_fall_back_to_the_board_list(self):
        for url in (
            "/boards//evil.example", "/boards/..", "/boards/a/../b", "/boards/\\evil.example",
            "/boards/a%20b", "/boards/한글", "/boards/%2e%2e/%2e%2e", "/boards/a//b", "/boards/https:evil.example",
        ):
            with self.subTest(url=url):
                response = self.assertStaysOnSite(url)
                self.assertEqual(response.status_code, 308)
                self.assertEqual(urlsplit(response["Location"]).path, "/boards")

    def test_shop_products_paths_redirect_to_product_pages(self):
        cases = {
            "/shop/products/I1": "/shop/I1",
            "/shop/products/I1?tab=qa": "/shop/I1?tab=qa",
        }
        for url, target in cases.items():
            with self.subTest(url=url):
                self.assertLocalRedirect(url, target, status=308)

    def test_shop_products_paths_with_unsafe_segments_serve_the_product_list(self):
        for url in ("/shop/products/../x", "/shop/products//evil.example", "/shop/products/a b", "/shop/products/\\evil.example"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_a_trailing_slash_still_redirects_to_the_product_page(self):
        # Rule: the trailing slash is not part of the captured product path.
        response = self.client.get("/shop/products/I1/")
        self.assertEqual((response.status_code, urlsplit(response.get("Location", "")).path), (308, "/shop/I1"))

    def test_a_trailing_slash_still_redirects_to_the_short_board_url(self):
        # Rule: the trailing slash is not part of the captured board path.
        response = self.client.get("/boards/free/")
        self.assertEqual((response.status_code, urlsplit(response.get("Location", "")).path), (308, "/free"))

    def test_mobile_shop_with_a_trailing_slash_opens_the_shop(self):
        # Rule: /mobile/shop/ is PHP mobile/shop/index.php, the shop home.
        response = self.client.get("/mobile/shop/")
        self.assertEqual(urlsplit(response.get("Location", "")).path, "/shop")

    def test_legacy_product_type_flags_redirect_to_type_pages(self):
        self.assertLocalRedirect("/shop/products?it_type3=1", "/shop/type-3", status=308)
        self.assertLocalRedirect("/shop/products?it_type2=1&page=2", "/shop/type-2?page=2", status=308)

    def test_product_type_flags_set_to_false_serve_the_product_list(self):
        for value in ("0", "false", "no", ""):
            with self.subTest(value=value):
                response = self.client.get("/shop/products", {"it_type1": value})
                self.assertEqual(response.status_code, 200)

    def test_shop_products_root_serves_the_static_page(self):
        for url in ("/shop/products", "/shop/products/"):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_shop_categories_paths_redirect_to_category_lists(self):
        self.assertLocalRedirect("/shop/categories/10", "/shop/list-10", status=308)
        self.assertLocalRedirect("/shop/categories/10/sub", "/shop/list-10", status=308)
        response = self.client.get("/shop/categories/..")
        self.assertEqual(response.status_code, 200)

    def test_a_disallowed_host_header_gets_a_400_page_not_a_server_error(self):
        # Rule: CommonMiddleware rejects the Host header before request.user is set, so the error
        # handlers must render without request.user.
        from django.test import Client

        with override_settings(ALLOWED_HOSTS=["testserver"]):
            response = Client(raise_request_exception=False).get("/boards/free", HTTP_HOST="evil.example")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("Location", response)

    def test_a_disallowed_host_with_a_cross_site_origin_is_still_a_400(self):
        # the session-cookie middleware reads the host for cross-site requests; a bad one is a 400
        from django.test import Client

        with override_settings(ALLOWED_HOSTS=["testserver"]):
            response = Client(raise_request_exception=False).get(
                "/boards/free", HTTP_HOST="evil.example", HTTP_ORIGIN="https://app.example"
            )
        self.assertEqual(response.status_code, 400)


def make_board(table="free", **extra):
    group, _ = Group.objects.get_or_create(gr_id="community", defaults={"gr_subject": "Community"})
    values = {"bo_subject": table.title(), "bo_skin": "basic", "bo_mobile_skin": "basic"}
    values.update(extra)
    return Board.objects.create(group=group, bo_table=table, **values)


def make_post(board, subject="Hello", **extra):
    values = {
        "wr_subject": subject, "wr_content": "body", "wr_slug": f"slug-{Post.objects.count()}",
        "wr_datetime": timezone.now(), "wr_name": "writer",
    }
    values.update(extra)
    return Post.objects.create(board=board, **values)


class NextjsShellViewTests(TestCase):
    def setUp(self):
        self.board = make_board("free")

    def test_public_pages_are_served_from_the_static_export(self):
        paths = (
            "/", "/login", "/login/", "/login/social-callback", "/register", "/register/result", "/forgot-password",
            "/email-certify", "/boards", "/faq", "/polls", "/recent", "/search", "/baby", "/offline", "/shop",
            "/shop/cart", "/shop/couponzone", "/shop/compare", "/shop/events", "/shop/order", "/shop/orders",
            "/shop/search", "/shop/wishlist", "/mypage", "/mypage/profile", "/mypage/orders",
            "/admin", "/admin/boards", "/admin/members", "/admin/qas", "/admin/settings", "/admin/shop/categories",
        )
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response["Content-Type"].startswith("text/html"))

    def test_dynamic_routes_map_to_the_exported_placeholder_pages(self):
        paths = (
            "/mypage/qas/5", "/mypage/qas/new", "/mypage/memos/9", "/mypage/memos/new", "/content/company",
            "/members/bob", "/shop/list-10", "/shop/categories", "/shop/type-2", "/shop/events/3", "/shop/orders/2026",
            "/shop/personalpay/5", "/shop/personalpay/5/pay", "/shop/I1", "/admin/boards/free", "/admin/members/bob",
            "/admin/qas/4", "/admin/shop/orders/12", "/admin/shop/products/abc", "/admin/shop/products",
            "/free", "/free/12", "/free/write", "/free/hello-slug/",
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_unknown_pages_are_a_404(self):
        for path in ("/mypage/no-such-page", "/shop/a/b/c/d", "/no-such-board", "/no-such-board/12", "/login/other", "/bbs/plain"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 404)
                self.assertTrue(response["Content-Type"].startswith("text/html"))

    def test_board_alias_cm_free_resolves_to_the_free_board(self):
        self.assertEqual(self.client.get("/cm_free").status_code, 200)
        self.assertEqual(self.client.get("/cm_free/3").status_code, 200)
        self.assertEqual(self.client.get("/cm_free.txt").status_code, 200)

    def test_page_scripts_carry_the_per_response_nonce_from_the_csp_header(self):
        first = self.client.get("/login")
        second = self.client.get("/login")

        nonce = first["Content-Security-Policy"].split("'nonce-")[1].split("'")[0]
        body = first.content.decode()
        self.assertGreater(body.count("<script"), 0)
        self.assertEqual(body.count("<script"), body.count(f'<script nonce="{nonce}"'))
        self.assertNotEqual(nonce, second["Content-Security-Policy"].split("'nonce-")[1].split("'")[0])

    def test_runtime_config_replaces_the_build_origin_and_adds_canonical_urls(self):
        response = self.client.get("/login?utm_source=ad&next=1&_rsc=abc")

        body = response.content.decode()
        self.assertNotIn("localhost:3000", body)
        self.assertNotIn("your-django-api.example.com", body)
        self.assertIn('href="http://testserver/login?next=1"', body)
        self.assertIn("window.__G5_NEXTJS25_CONFIG__", body)
        self.assertIn('"apiBaseUrl":"http://testserver/api/v1"', body)

    def test_short_board_pages_use_the_post_address_as_canonical_url(self):
        body = self.client.get("/free/12").content.decode()
        self.assertIn('rel="canonical"', body)
        self.assertIn("http://testserver/free/12", body)

    def test_request_path_is_kept_inside_the_runtime_config_json(self):
        hostile = "/mypage/qas/%3C/script%3E%3Cscript%3Ealert(1)%3C/script%3E%22%26"

        response = self.client.get(hostile)

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertNotRegex(body, r"<script[^>]*>alert\(1\)")
        self.assertIn(chr(92) + "u003C/script" + chr(92) + "u003E", body)

    def test_text_payloads_are_private_and_use_the_flight_content_type(self):
        for path in ("/index.txt", "/login.txt", "/mypage.txt", "/mypage/qas/5.txt", "/shop/I1.txt", "/free.txt", "/free/12.txt", "/free/write.txt", "/boards.txt"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "text/x-component; charset=utf-8")
                self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
                self.assertIn("no-store", response["Cache-Control"])

    def test_text_payload_for_unknown_board_or_page_is_a_404(self):
        for path in ("/nope.txt", "/nope/12.txt", "/mypage/none.txt"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_head_and_options_on_a_page_do_not_fail(self):
        head = self.client.head("/login")
        self.assertEqual(head.status_code, 200)
        self.assertEqual(head.content, b"")
        self.assertLess(self.client.options("/login").status_code, 500)

    def test_theme_urls_reject_dot_segments(self):
        for path in ("/nextjs25/../index", "/nextjs25/a/../../index", "/nextjs_default/../login"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_theme_urls_serve_exported_templates_by_name(self):
        for path in ("/nextjs25/", "/nextjs25/login", "/nextjs_default/", "/nextjs_default/boards/__g5_static__/0"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_theme_urls_return_404_for_absolute_nul_and_odd_names(self):
        for path in ("/nextjs25//etc/passwd", "/nextjs25/%ff%fe", "/nextjs25/index.html", "/nextjs25/nul"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)

    def test_theme_urls_do_not_render_templates_outside_the_theme_with_backslashes(self):
        # Rule: both separators count when ".." is refused; the static export must stay inside
        # theme/nextjs_default (on Windows "..\..\500" would reach templates/500.html).
        response = self.client.get("/nextjs25/..%5C..%5C500")
        self.assertEqual(response.status_code, 404)

    def test_a_very_long_page_name_is_a_404_not_a_server_error(self):
        # Rule: a page name the file system cannot hold (over 255 characters, a NUL byte) is a missing
        # page, not an OSError/ValueError from the template loader.
        from django.test import Client

        client = Client(raise_request_exception=False)
        paths = ("/nextjs25/" + "a" * 300, "/mypage/" + "a" * 300, "/nextjs25/a%00b", "/mypage/a%00b")
        statuses = {path[:20]: client.get(path).status_code for path in paths}
        self.assertEqual(set(statuses.values()), {404}, statuses)

    @unittest.skipUnless(os.name == "nt", "a colon is only an invalid file name character on Windows")
    def test_a_colon_in_a_page_name_is_a_404_not_a_server_error(self):
        # Rule: same for a Windows colon (/mypage/a:b would be OSError "Invalid argument").
        from django.test import Client

        self.assertEqual(Client(raise_request_exception=False).get("/mypage/a:b").status_code, 404)

    def test_metadata_path_maps_internal_routes_to_public_ones(self):
        from gnu_jango.core.views import _nextjs25_public_metadata_path as metadata_path

        self.assertEqual(metadata_path(""), "/")
        self.assertEqual(metadata_path("/boards/free/12?x=1"), "/free/12")
        self.assertEqual(metadata_path("/boards"), "/boards")
        self.assertEqual(metadata_path("/shop/products/I1"), "/shop/I1")
        self.assertEqual(metadata_path("/shop/categories/10"), "/shop/list-10")
        self.assertEqual(metadata_path("/shop/I1"), "/shop/I1")

    def test_root_template_mapping_for_every_dynamic_family(self):
        from gnu_jango.core.views import _map_nextjs25_root_template_path as mapped

        expected = {
            "": "index", "boards": "boards", "boards/free": "boards/__g5_static__",
            "boards/free/write": "boards/__g5_static__/write", "boards/free/9": "boards/__g5_static__/0",
            "content/x": "content/__g5_static__", "members/x": "members/__g5_static__",
            "mypage": "mypage", "mypage/qas/new": "mypage/qas/new", "mypage/qas/4": "mypage/qas/0",
            "mypage/memos/new": "mypage/memos/new", "mypage/memos/4": "mypage/memos/0",
            "shop": "shop", "shop/list-1": "shop/categories/__g5_static__", "shop/type-1": "shop/products",
            "shop/products/x": "shop/products/__g5_static__", "shop/orders/x": "shop/orders/__g5_static__",
            "shop/events/x": "shop/events/0", "shop/personalpay/x": "shop/personalpay/__g5_static__",
            "shop/personalpay/x/pay": "shop/personalpay/__g5_static__/pay", "shop/abc": "shop/products/__g5_static__",
            "admin": "admin", "admin/boards/x": "admin/boards/__g5_static__", "admin/qas/3": "admin/qas/0",
            "admin/shop/orders/3": "admin/shop/orders/__g5_static__", "admin/shop/products/3": "admin/shop/products/__g5_static__",
            "admin/shop/categories": "admin/shop/categories", "admin/other": "admin/other",
        }
        for source, target in expected.items():
            with self.subTest(source=source):
                self.assertEqual(mapped(source), target)

    def test_template_path_cleaning_rejects_dot_segments(self):
        from django.http import Http404
        from gnu_jango.core.views import _clean_nextjs25_template_path as clean

        self.assertEqual(clean(None), "index")
        self.assertEqual(clean("/a/b/"), "a/b")
        with self.assertRaises(Http404):
            clean("a/../b")


class ErrorHandlerTests(TestCase):
    def request(self):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory

        request = RequestFactory().get("/x")
        request.user = AnonymousUser()
        return request

    def test_error_handlers_render_their_status_codes(self):
        from gnu_jango.core import views

        for handler, status in ((views.error_400, 400), (views.error_403, 403), (views.error_404, 404)):
            with self.subTest(status=status):
                self.assertEqual(handler(self.request(), Exception("x")).status_code, status)
        self.assertEqual(views.error_500(self.request()).status_code, 500)

    def test_gnu_view_setup_marks_the_user_flags(self):
        from django.contrib.auth import get_user_model
        from django.http import HttpResponse
        from gnu_jango.core.views import Common_Gnu_View

        class Probe(Common_Gnu_View):
            def get(self, request):
                user = request.user
                return HttpResponse(f"{user.is_user}-{user.is_guest}-{user.is_admin}-{user.is_auth}")

        self.assertEqual(Probe.as_view()(self.request()).content, b"False-True-False-False")
        request = self.request()
        request.user = get_user_model().objects.create_superuser("probe-admin", "probe@example.test", "pw")
        self.assertEqual(Probe.as_view()(request).content, b"True-False-True-True")

    def test_index_page_renders_while_a_popup_is_active(self):
        from gnu_jango.core.models import New_win

        now = timezone.now()
        New_win.objects.create(
            nw_division="comm", nw_device="both", nw_begin_time=now - timedelta(days=1),
            nw_end_time=now + timedelta(days=1), nw_disable_hours=1, nw_left=0, nw_top=0,
            nw_height=100, nw_width=100, nw_subject="Popup", nw_content="x", nw_content_html=0,
        )
        self.assertEqual(self.client.get("/").status_code, 200)


class PublicAssetTests(TestCase):
    def test_icons_logos_and_og_image_are_served(self):
        for path in ("/icon-192.png", "/icon-512.png", "/img/logo.png", "/img/shop-logo.png", "/og-default.png"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Content-Type"], "image/png")
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_service_worker_scope_follows_the_script_prefix(self):
        root = self.client.get("/sw.js")
        prefixed = self.client.get("/sw.js", SCRIPT_NAME="/sub")

        self.assertEqual(root.status_code, 200)
        self.assertEqual(root["Service-Worker-Allowed"], "/")
        self.assertEqual(prefixed["Service-Worker-Allowed"], "/sub/")

    def test_manifest_is_rewritten_for_the_current_scope(self):
        for path, content_type in (("/manifest.json", "application/json"), ("/manifest.webmanifest", "application/manifest+json")):
            with self.subTest(path=path):
                response = self.client.get(path, SCRIPT_NAME="/sub")
                data = json.loads(response.content)
                self.assertEqual(response["Content-Type"], f"{content_type}; charset=utf-8")
                self.assertEqual((data["start_url"], data["scope"]), ("/sub/", "/sub/"))
                self.assertTrue(data["icons"])
                self.assertTrue(all(icon["src"].startswith("/sub/") for icon in data["icons"]))

    def test_manifest_falls_back_to_defaults_when_the_export_file_is_unreadable(self):
        with tempfile.TemporaryDirectory() as empty:
            with override_settings(TEMPLATES_DIR=Path(empty)):
                data = json.loads(self.client.get("/manifest.json").content)
        self.assertEqual(data["short_name"], "Gnuboard5")
        self.assertEqual(data["icons"], [])
        self.assertEqual(data["scope"], "/")

    def test_manifest_drops_malformed_icon_entries(self):
        with tempfile.TemporaryDirectory() as root:
            manifest = Path(root) / "theme" / "nextjs_default"
            manifest.mkdir(parents=True)
            (manifest / "manifest.json").write_text(
                json.dumps({"name": "x", "icons": [{"src": "/a.png"}, "junk", {"sizes": "1x1"}, {"src": ""}]}), encoding="utf-8"
            )
            with override_settings(TEMPLATES_DIR=Path(root)):
                data = json.loads(self.client.get("/manifest.json").content)
        self.assertEqual([icon["src"] for icon in data["icons"]], ["/a.png"])

    def test_unlisted_assets_cannot_be_requested_through_the_public_asset_view(self):
        from django.http import Http404
        from django.test import RequestFactory
        from gnu_jango.core.views import nextjs25_public_asset

        for path in ("../../../settings.py", "login.html", "img/other.png", "", "robots.TXT", "..\\manifest.json"):
            with self.subTest(path=path):
                with self.assertRaises(Http404):
                    nextjs25_public_asset(RequestFactory().get("/x"), path)

    def test_post_and_head_to_static_files_do_not_crash(self):
        self.assertLess(self.client.post("/robots.txt").status_code, 500)
        head = self.client.head("/icon-192.png")
        self.assertEqual(head.status_code, 200)
        self.assertEqual(b"".join(head.streaming_content) if head.streaming else head.content, b"")


class NextStaticFileTests(TestCase):
    def setUp(self):
        root = Path(settings.TEMPLATES_DIR) / "theme_static" / "nextjs_default" / "_next" / "static"
        self.css = next(root.glob("css/*.css"))
        self.relative = self.css.relative_to(root).as_posix()

    def test_exported_assets_are_served(self):
        response = self.client.get(f"/_next/static/{self.relative}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/css")

    def test_missing_assets_are_a_404(self):
        self.assertEqual(self.client.get("/_next/static/css/none.css").status_code, 404)

    def test_traversal_attempts_never_serve_files_outside_the_static_root(self):
        secret = Path(settings.TEMPLATES_DIR) / "theme" / "nextjs_default" / "index.html"
        for path in (
            "../../../../theme/nextjs_default/index.html",
            "%2e%2e/%2e%2e/%2e%2e/%2e%2e/theme/nextjs_default/index.html",
            "css/..%2f..%2f..%2f..%2f..%2ftheme/nextjs_default/index.html",
            "..%5c..%5c..%5c..%5ctheme%5cnextjs_default%5cindex.html",
            "/theme/nextjs_default/index.html",
            "css/%00.css",
        ):
            with self.subTest(path=path):
                response = self.client.get(f"/_next/static/{path}")
                self.assertIn(response.status_code, (400, 404))
                self.assertNotIn(b"g5_nextjs25_static", response.content if not response.streaming else b"")
        self.assertTrue(secret.exists())

    def test_conditional_requests_are_answered_with_304(self):
        first = self.client.get(f"/_next/static/{self.relative}")
        second = self.client.get(f"/_next/static/{self.relative}", HTTP_IF_MODIFIED_SINCE=first["Last-Modified"])
        self.assertEqual(second.status_code, 304)


class RobotsTests(TestCase):
    def test_robots_lists_private_areas_and_both_sitemaps_for_the_current_host(self):
        response = self.client.get("/robots.txt")

        lines = response.content.decode().splitlines()
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        for prefix in ("/login", "/register", "/forgot-password", "/email-certify", "/mypage", "/admin", "/api",
                       "/shop/cart", "/shop/order", "/shop/orders", "/shop/payment", "/shop/personalpay", "/shop/wishlist"):
            self.assertIn(f"Disallow: {prefix}", lines)
        self.assertIn("Sitemap: http://testserver/sitemap.xml", lines)
        self.assertIn("Sitemap: http://testserver/sitemap-posts.xml", lines)
        self.assertIn("Host: http://testserver", lines)

    def test_every_noindex_prefix_is_also_disallowed_for_crawlers(self):
        from gnu_jango.core.middleware import PRIVATE_NOINDEX_PREFIXES

        disallowed = [line.split(": ", 1)[1] for line in self.client.get("/robots.txt").content.decode().splitlines() if line.startswith("Disallow: ")]
        # /members/ pages are public profiles kept out of the index by header only (crawlers must read the header).
        for prefix in PRIVATE_NOINDEX_PREFIXES:
            if prefix == "/members/":
                continue
            with self.subTest(prefix=prefix):
                self.assertTrue(any(prefix.startswith(item) for item in disallowed), prefix)

    @override_settings(ALLOWED_HOSTS=["shop.example.test", "testserver"])
    def test_robots_reflects_the_forwarded_script_prefix(self):
        # the host must be allowed explicitly: CI has no .env widening ALLOWED_HOSTS
        response = self.client.get("/robots.txt", HTTP_HOST="shop.example.test")
        self.assertIn("Sitemap: http://shop.example.test/sitemap.xml", response.content.decode())


class PrivatePageHeaderTests(TestCase):
    PRIVATE = (
        "/login", "/register", "/forgot-password", "/email-certify", "/mypage", "/mypage/orders", "/mypage/qas/5",
        "/shop/cart", "/shop/order", "/shop/orders", "/shop/orders/2026", "/shop/personalpay", "/shop/personalpay/5/pay",
        "/shop/wishlist", "/shop/payment/success", "/shop/payment/fail", "/admin", "/admin/members", "/admin/shop/orders/3",
        "/members/bob",
    )

    def test_private_pages_are_noindex_and_never_cached(self):
        for path in self.PRIVATE:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
                self.assertIn("no-store", response["Cache-Control"])
                self.assertIn("private", response["Cache-Control"])

    def test_legacy_redirects_to_private_pages_are_not_cached_either(self):
        for url in ("/bbs/login.php", "/bbs/memo.php", "/shop/orderinquiry.php", "/shop/mypage.php", "/shop/cart.php"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 307)
                cache_control = response.get("Cache-Control", "")
                self.assertFalse(any(token in cache_control for token in ("max-age=", "public", "s-maxage")), cache_control)

    def test_public_pages_are_indexable(self):
        for path in ("/", "/boards", "/faq", "/shop", "/shop/I1"):
            with self.subTest(path=path):
                self.assertNotIn("X-Robots-Tag", self.client.get(path))

    def test_security_headers_are_present_on_pages_and_redirects(self):
        for path in ("/login", "/bbs/board.php?bo_table=free", "/robots.txt"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response["X-Content-Type-Options"], "nosniff")
                self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
                self.assertEqual(response["Referrer-Policy"], "strict-origin-when-cross-origin")


class SitemapTests(TestCase):
    def locs(self, path="/sitemap.xml"):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/xml; charset=utf-8")
        root = ET.fromstring(response.content)
        return [node.text for node in root.findall("sm:url/sm:loc", SITEMAP_NS)]

    def setUp(self):
        self.visible = ShopCategory.objects.create(ca_id="10", ca_name="Visible", ca_use=True)
        self.hidden = ShopCategory.objects.create(ca_id="20", ca_name="Hidden", ca_use=False)

    def test_static_pages_and_enabled_categories_and_products_are_listed(self):
        ShopProduct.objects.create(it_id="P1", category=self.visible, it_name="One", it_use="1")

        locs = self.locs()

        for path in ("/", "/boards", "/faq", "/shop", "/shop/products", "/content/company", "/shop/list-10", "/shop/P1"):
            self.assertIn(f"http://testserver{path}", locs)
        self.assertEqual(len(locs), len(set(locs)))

    def test_disabled_categories_and_products_are_left_out(self):
        ShopProduct.objects.create(it_id="OFF", category=self.visible, it_name="Off", it_use="0")
        ShopProduct.objects.create(it_id="BLANK", category=self.visible, it_name="Blank", it_use="")

        locs = self.locs()

        self.assertNotIn("http://testserver/shop/list-20", locs)
        self.assertNotIn("http://testserver/shop/OFF", locs)
        self.assertNotIn("http://testserver/shop/BLANK", locs)

    def test_products_of_a_hidden_category_are_left_out(self):
        # Rule: Gnuboard5 shop/item.php refuses a product whose category has ca_use = 0
        # ("!($it['ca_use'] && $it['it_use'])"), so the sitemap leaves it out.
        ShopProduct.objects.create(it_id="IN-HIDDEN", category=self.hidden, it_name="Hidden category product", it_use="1")
        self.assertNotIn("http://testserver/shop/IN-HIDDEN", self.locs())

    def test_hostile_product_ids_keep_the_xml_well_formed(self):
        ShopProduct.objects.create(it_id='a&b<c>"d\'', category=self.visible, it_name="Odd", it_use="1")

        locs = self.locs()

        # < > " are not URI characters (RFC 3986) and are %-escaped; & and ' are XML-escaped only.
        self.assertIn("http://testserver/shop/a&b%3Cc%3E%22d'", locs)

    def test_product_urls_are_percent_encoded(self):
        # Rule: the sitemap spec requires RFC 3986 escaped URLs, so an id with a space or
        # non-ASCII letters is %-escaped in <loc>.
        ShopProduct.objects.create(it_id="상품 1", category=self.visible, it_name="Odd", it_use="1")
        ShopProduct.objects.create(it_id="50%off", category=self.visible, it_name="Odd", it_use="1")
        locs = self.locs()
        self.assertIn("http://testserver/shop/%EC%83%81%ED%92%88%201", locs)
        self.assertIn("http://testserver/shop/50%25off", locs)

    def test_sitemap_uses_the_request_host_and_supports_head(self):
        locs = self.locs()
        self.assertTrue(all(loc.startswith("http://testserver/") for loc in locs))
        head = self.client.head("/sitemap.xml")
        self.assertEqual((head.status_code, head.content), (200, b""))

    def test_only_the_newest_hundred_products_are_listed(self):
        now = timezone.now()
        ShopProduct.objects.bulk_create(
            ShopProduct(it_id=f"BULK{i:03d}", category=self.visible, it_name="n", it_use="1", created_at=now - timedelta(minutes=i))
            for i in range(105)
        )

        products = [loc for loc in self.locs() if "/shop/BULK" in loc]

        self.assertEqual(len(products), 100)
        self.assertIn("http://testserver/shop/BULK000", products)
        self.assertNotIn("http://testserver/shop/BULK104", products)


class PostSitemapTests(TestCase):
    def setUp(self):
        self.open = make_board("open", bo_read_level=1)
        self.members = make_board("members", bo_read_level=2)

    def locs(self):
        response = self.client.get("/sitemap-posts.xml")
        self.assertEqual(response.status_code, 200)
        return [node.text for node in ET.fromstring(response.content).findall("sm:url/sm:loc", SITEMAP_NS)]

    def test_public_posts_are_listed_by_their_short_url(self):
        post = make_post(self.open, "Public")
        self.assertEqual(self.locs(), [f"http://testserver/open/{post.pk}"])

    def test_secret_posts_are_never_listed(self):
        make_post(self.open, "Public")
        make_post(self.open, "Hidden", wr_option="secret")
        make_post(self.open, "Hidden html", wr_option="html1,secret")

        self.assertEqual(len(self.locs()), 1)

    def test_original_post_numbers_are_used_for_imported_posts(self):
        make_post(self.open, "Imported", legacy_wr_id=4242)
        self.assertEqual(self.locs(), ["http://testserver/open/4242"])

    def test_empty_sitemap_is_valid_xml(self):
        self.assertEqual(self.locs(), [])

    def test_posts_of_boards_that_guests_cannot_read_are_left_out(self):
        # Rule: only boards a guest may read (bo_read_level < 2) are listed, as bbs/rss.php
        # ("비회원 읽기가 가능한 게시판만 RSS 지원합니다") and board.php.
        make_post(self.members, "Members only")
        self.assertEqual(self.locs(), [])

    def test_posts_of_boards_that_guests_cannot_list_are_left_out(self):
        # Rule: likewise only boards a guest may list (bo_list_level < 2).
        hidden = make_board("hidden-list", bo_read_level=1, bo_list_level=10)
        make_post(hidden, "Hidden list")
        self.assertEqual(self.locs(), [])

    def test_only_the_newest_five_hundred_posts_are_listed(self):
        now = timezone.now()
        Post.objects.bulk_create(
            Post(board=self.open, wr_subject="p", wr_content="b", wr_slug=f"s{i}", wr_datetime=now - timedelta(minutes=i), wr_name="w")
            for i in range(505)
        )
        self.assertEqual(len(self.locs()), 500)


class BoardRssTests(TestCase):
    def setUp(self):
        self.board = make_board("news", bo_use_rss_view=True, bo_read_level=1, bo_page_rows=2, bo_subject="News & Views")

    def feed(self, table="news"):
        response = self.client.get(f"/rss/{table}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/rss+xml; charset=utf-8")
        return ET.fromstring(response.content)

    def test_feed_lists_the_newest_posts_up_to_the_page_size(self):
        now = timezone.now()
        for index in range(3):
            make_post(self.board, f"Post {index}", wr_datetime=now - timedelta(hours=index))

        items = self.feed().findall("channel/item")

        self.assertEqual([item.findtext("title") for item in items], ["Post 0", "Post 1"])
        self.assertTrue(items[0].findtext("link").startswith("http://testserver/news/"))
        self.assertIn("News & Views", self.feed().findtext("channel/title"))

    def test_secret_posts_do_not_appear_in_the_feed(self):
        make_post(self.board, "Visible")
        make_post(self.board, "TOP-SECRET-TITLE", wr_content="TOP-SECRET-BODY", wr_option="secret")

        body = self.client.get("/rss/news").content.decode()

        self.assertIn("Visible", body)
        self.assertNotIn("TOP-SECRET", body)

    def test_markup_in_titles_is_escaped_in_the_xml(self):
        make_post(self.board, "<script>alert(1)</script> & more")
        item = self.feed().find("channel/item")
        self.assertEqual(item.findtext("title"), "<script>alert(1)</script> & more")
        self.assertNotIn(b"<script>", self.client.get("/rss/news").content)

    def test_unknown_boards_and_boards_without_rss_are_a_404(self):
        make_board("norss", bo_use_rss_view=False, bo_read_level=1)
        make_board("membersrss", bo_use_rss_view=True, bo_read_level=2)
        for table in ("missing", "norss", "membersrss"):
            with self.subTest(table=table):
                self.assertEqual(self.client.get(f"/rss/{table}").status_code, 404)

    def test_boards_rss_alias_and_cm_free_alias(self):
        make_board("free", bo_use_rss_view=True, bo_read_level=1)
        self.assertEqual(self.client.get("/rss/cm_free").status_code, 200)
        self.assertEqual(self.client.get("/boards/news/rss").status_code, 308)

    def test_feed_of_an_empty_board_is_valid(self):
        self.assertEqual(self.feed().findall("channel/item"), [])

    def test_head_request_returns_headers_only(self):
        response = self.client.head("/rss/news")
        self.assertEqual((response.status_code, response.content), (200, b""))

    def test_plain_text_posts_do_not_ship_raw_markup_as_item_html(self):
        # Rule: bbs/rss.php runs conv_content($content, $html), which escapes the markup of a post
        # without the html option (RSS readers render <description> as HTML).
        make_post(self.board, "Plain", wr_content="<img src=x onerror=alert(1)>", wr_option="")
        description = self.feed().findtext("channel/item/description")
        self.assertNotIn("<img", description)

    def test_html_posts_keep_sanitized_markup_in_the_item_html(self):
        make_post(self.board, "Html", wr_content="<b>bold</b><script>alert(1)</script>", wr_option="html1")
        description = self.feed().findtext("channel/item/description")
        self.assertIn("<b>bold</b>", description)
        self.assertNotIn("<script", description)


class LegacyDataAssetTests(TestCase):
    def setUp(self):
        self.media = tempfile.mkdtemp()
        self.legacy = tempfile.mkdtemp()
        self.outside = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media, True)
        self.addCleanup(shutil.rmtree, self.legacy, True)
        self.addCleanup(shutil.rmtree, self.outside, True)
        override = override_settings(MEDIA_ROOT=self.media, LEGACY_GNUBOARD5_SOURCE_ROOTS=self.legacy)
        override.enable()
        self.addCleanup(override.disable)
        # Files that must never be reachable through /data/<area>/...
        (Path(self.media) / "data").mkdir(parents=True)
        (Path(self.media) / "data" / "dbconfig.php").write_text("SECRET-DB-PASSWORD", encoding="utf-8")
        (Path(self.media) / "secret.txt").write_text("SECRET-MEDIA", encoding="utf-8")
        (Path(self.legacy) / "data" / "file").mkdir(parents=True)
        (Path(self.legacy) / "data" / "dbconfig.php").write_text("SECRET-DB-PASSWORD", encoding="utf-8")
        (Path(self.outside) / "outside.txt").write_text("SECRET-OUTSIDE", encoding="utf-8")
        self.write("file", "hello.txt", "HELLO")

    def write(self, area, name, content, root=None):
        target = Path(root or self.media) / "data" / area / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def body(self, response):
        return b"".join(response.streaming_content) if response.streaming else response.content

    def test_files_are_served_from_the_media_data_folder(self):
        response = self.client.get("/data/file/hello.txt")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.body(response), b"HELLO")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_files_are_served_from_the_legacy_gnuboard_data_folder_and_nested_folders(self):
        self.write("item", "sub/dir/pic.txt", "FROM-LEGACY", root=Path(self.legacy))
        response = self.client.get("/data/item/sub/dir/pic.txt")
        self.assertEqual(self.body(response), b"FROM-LEGACY")

    def test_the_media_copy_wins_over_the_legacy_copy(self):
        self.write("event", "e.txt", "MEDIA")
        self.write("event", "e.txt", "LEGACY", root=Path(self.legacy))
        self.assertEqual(self.body(self.client.get("/data/event/e.txt")), b"MEDIA")

    def test_only_the_public_data_areas_are_served(self):
        for area in ("session", "member", "cache", "common", "editor", "log", "FILE", "", "dbconfig.php", "..", "file/.."):
            self.write("file", "x.txt", "x")
            with self.subTest(area=area):
                response = self.client.get(f"/data/{area}/x.txt")
                self.assertEqual(response.status_code, 404)
                self.assertNotIn(b"SECRET", response.content)

    def test_traversal_never_leaves_the_area_folder(self):
        for suffix in (
            "../../secret.txt", "..%2f..%2fsecret.txt", "%2e%2e/%2e%2e/secret.txt", "..%5c..%5csecret.txt",
            "sub/../../secret.txt", "..\\..\\dbconfig.php", "....//....//secret.txt", "%2e%2e%2f%2e%2e%2fsecret.txt",
            "%252e%252e/%252e%252e/secret.txt", "./../secret.txt", "..;/..;/secret.txt",
        ):
            with self.subTest(suffix=suffix):
                response = self.client.get(f"/data/file/{suffix}")
                self.assertIn(response.status_code, (400, 404))
                self.assertNotIn(b"SECRET", b"" if response.streaming else response.content)

    def test_absolute_and_unc_paths_are_treated_as_relative_names(self):
        for suffix in ("/etc/passwd", "//server/share/x.txt", "%2Fsecret.txt"):
            with self.subTest(suffix=suffix):
                response = self.client.get(f"/data/file/{suffix}")
                self.assertEqual(response.status_code, 404)

    def test_a_windows_drive_path_gives_the_same_answer_whether_or_not_the_file_exists(self):
        # Rule: a drive path is refused before any file is looked at (`root / "C:/x"` would replace
        # the root), so an existing and a missing outside file answer the same.
        drive, rest = os.path.splitdrive(str(Path(self.outside) / "outside.txt"))
        if not drive:
            self.skipTest("drive letters only exist on Windows")
        existing = Path(self.outside, "outside.txt").as_posix()
        missing = Path(self.outside, "missing.txt").as_posix()
        self.assertEqual(
            (self.client.get(f"/data/file/{existing}").status_code, self.client.get(f"/data/file/{missing}").status_code),
            (404, 404),
        )

    def test_missing_images_fall_back_to_the_default_image_and_other_files_are_a_404(self):
        image = self.client.get("/data/file/gone.JPG")
        self.assertEqual((image.status_code, image["Content-Type"]), (200, "image/png"))
        for name in ("gone.txt", "gone.pdf", "gone", "gone.png.exe"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(f"/data/file/{name}").status_code, 404)

    def test_folders_and_nul_bytes_do_not_crash(self):
        self.write("file", "dir/inner.txt", "x")
        self.assertEqual(self.client.get("/data/file/dir").status_code, 404)
        self.assertEqual(self.client.get("/data/file/a%00.txt").status_code, 404)
        self.assertEqual(self.client.get("/data/file/a%00.png").status_code, 200)
        self.assertEqual(self.client.get("/data/file/" + "a" * 400 + ".txt").status_code, 404)
        self.assertEqual(self.client.get("/data/file/%ED%95%9C%EA%B8%80%F0%9F%98%80.txt").status_code, 404)

    def test_head_and_conditional_requests_work(self):
        head = self.client.head("/data/file/hello.txt")
        self.assertEqual(head.status_code, 200)
        self.assertEqual(self.body(head), b"")
        first = self.client.get("/data/file/hello.txt")
        second = self.client.get("/data/file/hello.txt", HTTP_IF_MODIFIED_SINCE=first["Last-Modified"])
        self.assertEqual(second.status_code, 304)

    def test_active_content_uploads_are_not_served_from_the_data_folder(self):
        # Rule: Gnuboard5 data/.htaccess (install/install_db.php:715) denies .htaccess .htpasswd .php .phtml
        # .phtm .html .htm .inc .cgi .pl .phar .svg .svgz under data/, so an uploaded HTML/SVG page can never
        # be opened on the site origin.
        names = ["a.html", "a.htm", "a.HTML", "a.shtml", "a.svg", "a.svgz", "a.php", "a.phtml", "a.phtm", "a.inc", "a.cgi", "a.pl", "a.phar", "a.htaccess"]
        for name in names:
            self.write("file", name, "<script>alert(1)</script>")
        served = [name for name in names if self.client.get(f"/data/file/{name}").status_code == 200]
        self.assertEqual(served, [])

    def test_only_images_open_inline_and_other_files_are_downloads(self):
        self.write("file", "pic.png", "png")
        image = self.client.get("/data/file/pic.png")
        document = self.client.get("/data/file/hello.txt")
        self.assertFalse(image.get("Content-Disposition", "").startswith("attachment"))
        self.assertTrue(document["Content-Disposition"].startswith("attachment"), document["Content-Disposition"])
        self.assertEqual(document["X-Content-Type-Options"], "nosniff")

    def test_legacy_data_view_rejects_unknown_areas_directly(self):
        from django.http import Http404
        from django.test import RequestFactory
        from gnu_jango.core.views import legacy_data_asset

        with self.assertRaises(Http404):
            legacy_data_asset(RequestFactory().get("/x"), "session", "a.txt")
        with self.assertRaises(Http404):
            legacy_data_asset(RequestFactory().get("/x"), "file", "")
        with self.assertRaises(Http404):
            legacy_data_asset(RequestFactory().get("/x"), "file", "a/../b")


class SubPathDeploymentTests(TestCase):
    def test_redirects_keep_the_script_prefix_when_the_site_is_mounted_below_the_root(self):
        # Rule: behind a /sub mount, legacy and canonical redirects keep SCRIPT_NAME, as the manifest
        # and service worker do.
        targets = []
        for url in ("/bbs/board.php?bo_table=free&wr_id=2", "/boards/free", "/shop/item.php?it_id=A"):
            targets.append(urlsplit(self.client.get(url, SCRIPT_NAME="/sub")["Location"]).path)
        self.assertEqual(targets, ["/sub/free/2", "/sub/free", "/sub/shop/A"])


class RedirectHelperTests(TestCase):
    def request(self, query=""):
        from django.test import RequestFactory

        return RequestFactory().get("/x" + query)

    def test_local_redirect_merges_a_query_in_the_target_with_the_request_query(self):
        from gnu_jango.core.legacy_redirects import _legacy_local_redirect

        response = _legacy_local_redirect(self.request("?a=1"), "/page?tab=qa", drop=["a"])
        self.assertEqual(response["Location"], "http://testserver/page?tab=qa")
        response = _legacy_local_redirect(self.request("?a=1"), "/page?tab=qa", status_code=308)
        self.assertEqual((response.status_code, urlsplit(response["Location"]).query), (308, "tab=qa&a=1"))

    def test_local_redirect_drops_any_scheme_or_host_in_the_target(self):
        from gnu_jango.core.legacy_redirects import _legacy_local_redirect

        response = _legacy_local_redirect(self.request(), "https://evil.example/steal?x=1")
        self.assertTrue(response["Location"].startswith("http://testserver/steal"))

    @override_settings(LEGACY_GNUBOARD5_BASE_URL=LEGACY_BASE)
    def test_php_redirect_adds_the_missing_leading_slash(self):
        from gnu_jango.core.legacy_redirects import _legacy_php_redirect

        self.assertEqual(_legacy_php_redirect(self.request("?q=1"), "bbs/x.php")["Location"], f"{LEGACY_BASE}/bbs/x.php?q=1")

    def test_query_helper_sets_and_clears_parameters(self):
        from gnu_jango.core.legacy_redirects import _legacy_query

        request = self.request("?keep=1&drop=2")
        self.assertEqual(_legacy_query(request, drop=["drop"], set_params={"flag": True, "none": None, "n": 5}), "keep=1&flag=1&n=5")

    def test_safe_relative_redirect_only_accepts_plain_site_paths(self):
        from gnu_jango.core.legacy_redirects import _legacy_safe_relative_redirect as safe

        self.assertEqual(safe("/ok?x=1"), "/ok?x=1")
        for value in ("", None, "ok", "//x", "/\\x", "/a\rb", "/a\nb", "http://x"):
            self.assertEqual(safe(value), "")

    def test_clean_segments_rejects_unsafe_names(self):
        from gnu_jango.core.legacy_redirects import _legacy_clean_segments as clean

        self.assertEqual(clean("a/b.php"), ["a", "b.php"])
        for value in ("", None, "a//b", "a/./b", "a/../b", "a b", "a/한글", "a;b", "a%2fb"):
            self.assertEqual(clean(value), [], value)
