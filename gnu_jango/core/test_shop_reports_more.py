"""youngcart shop reports: 매출현황 with the payment-method split (sale1today / sale1date /
sale1month / sale1year), 보관함 현황 (wishlist.php) and the price comparison feed (price.php,
shop/price/naver.php)."""

import csv
import io
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from gnu_jango.config.models import Config
from gnu_jango.shop import price_feed
from gnu_jango.shop.models import ShopCategory, ShopOrder, ShopProduct, ShopWishlist
from gnu_jango.shop.sales_report import PERIOD_DAY, PERIOD_MONTH, PERIOD_TODAY, PERIOD_YEAR, sales_table, settle_method

SEOUL = ZoneInfo("Asia/Seoul")


def at(year, month, day, hour=12):
    return datetime(year, month, day, hour, tzinfo=SEOUL)


def staff_with(*codenames):
    user = get_user_model().objects.create_user("staff-" + "-".join(codenames)[:100], "s@example.test", "pw", is_staff=True)
    for codename in codenames:
        user.user_permissions.add(Permission.objects.get(codename=codename, content_type__app_label="shop"))
    return user


@override_settings(TIME_ZONE="Asia/Seoul")
class SalesTableTests(TestCase):
    def setUp(self):
        def order(od_id, when, settle_case, receipt, **values):
            return ShopOrder.objects.create(
                od_id=od_id, od_datetime=when, od_settle_case=settle_case, od_receipt_price=receipt, **values
            )

        order("A1", at(2026, 10, 1), "무통장", 10000, od_cart_price=10000)
        order("A2", at(2026, 10, 1, 23), "신용카드", 20000, od_cart_price=18000, od_send_cost=2000, od_coupon=1000)
        order("A3", at(2026, 10, 2), "card", 5000, od_cart_price=5000, od_refund_price=5000, od_cancel_price=5000)
        order("A4", at(2026, 10, 2), "KAKAOPAY", 7000, od_cart_price=7000, od_receipt_point=500)
        order("A5", at(2026, 9, 30), "가상계좌", 3000, od_cart_price=4000, od_misu=1000)
        order("A6", at(2025, 3, 3), "계좌이체", 1000, od_cart_price=1000)
        order("A7", at(2026, 10, 2), "외상", 900, od_cart_price=900)

    def test_settle_cases_map_to_youngcart_columns(self):
        cases = {"무통장": "bank", "": "bank", "가상계좌": "vbank", "vbank": "vbank", "계좌이체": "iche", "신용카드": "card",
                 "card": "card", "간편결제": "easy", "inicis_kakaopay": "easy", "휴대폰": "hp", "외상": "other"}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(settle_method(value), expected)

    def test_daily_rows_split_net_receipts_by_method(self):
        table = sales_table(PERIOD_DAY, at(2026, 10, 1).date(), at(2026, 10, 2).date())
        rows = {row["label"]: row for row in table["rows"]}
        self.assertEqual(list(rows), ["2026-10-02", "2026-10-01"])
        first = rows["2026-10-01"]
        self.assertEqual((first["order_count"], first["order_price"], first["coupon"]), (2, 30000, 1000))
        self.assertEqual((first["methods"]["bank"], first["methods"]["card"], first["receipt"]), (10000, 20000, 30000))
        second = rows["2026-10-02"]
        # the refunded card payment nets to 0; the easy-pay point and the unknown method stay visible
        self.assertEqual((second["methods"]["card"], second["methods"]["easy"], second["methods"]["other"]), (0, 7000, 900))
        self.assertEqual((second["point"], second["refund"], second["cancel"]), (500, 5000, 5000))
        self.assertEqual(table["total"]["receipt"], 37900)

    def test_today_month_and_year_views(self):
        today = sales_table(PERIOD_TODAY, at(2026, 10, 1).date(), at(2026, 10, 1).date())
        self.assertEqual([row["od_id"] for row in today["rows"]], ["A2", "A1"])
        month = sales_table(PERIOD_MONTH, at(2026, 1, 1).date(), at(2026, 12, 31).date())
        self.assertEqual([(row["label"], row["order_count"]) for row in month["rows"]], [("2026-10", 5), ("2026-09", 1)])
        self.assertEqual(month["rows"][1]["misu"], 1000)
        year = sales_table(PERIOD_YEAR, at(2017, 1, 1).date(), at(2026, 12, 31).date())
        self.assertEqual([(row["label"], row["methods"]["iche"]) for row in year["rows"]], [("2026", 0), ("2025", 1000)])


@override_settings(TIME_ZONE="Asia/Seoul")
class SalesViewTests(TestCase):
    def setUp(self):
        ShopOrder.objects.create(od_id="V1", od_name="홍길동", od_datetime=at(2026, 10, 1), od_settle_case="무통장",
                                 od_receipt_price=1000, od_cart_price=1000)
        self.url = reverse("admin:shop_shoporder_sales")

    def test_needs_the_order_view_permission(self):
        self.client.force_login(staff_with("view_shopproduct"))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(staff_with("view_shoporder"))
        response = self.client.get(self.url, {"period": "day", "date_from": "2026-10-01", "date_to": "2026-10-31"})
        self.assertContains(response, "2026-10-01")
        self.assertContains(response, "period=today")

    def test_today_view_links_orders_and_csv_has_method_columns(self):
        self.client.force_login(get_user_model().objects.create_superuser("sales", "sales@example.test", "pw"))
        response = self.client.get(self.url, {"period": "today", "date_from": "2026-10-01"})
        self.assertContains(response, reverse("admin:shop_shoporder_change", args=["V1"]))
        response = self.client.get(self.url, {"period": "month", "date_from": "2026-01-01", "date_to": "2026-12-31", "export": "csv"})
        rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))
        self.assertEqual(rows[0][:7], ["기간", "주문수", "주문합계", "쿠폰", "무통장", "가상계좌", "계좌이체"])
        self.assertEqual(rows[1][:5], ["2026-10", "1", "1000", "0", "1000"])
        self.assertEqual(rows[-1][0], "합계")

    def test_long_day_ranges_are_cut(self):
        self.client.force_login(get_user_model().objects.create_superuser("sales2", "sales2@example.test", "pw"))
        response = self.client.get(self.url, {"period": "day", "date_from": "2020-01-01", "date_to": "2026-10-01"})
        self.assertContains(response, "400일까지")


class WishlistReportTests(TestCase):
    def setUp(self):
        self.url = reverse("admin:shop_shopproduct_wishlist_report")
        self.popular = ShopProduct.objects.create(it_id="W1", it_name="인기 상품", it_price=1000)
        self.other = ShopProduct.objects.create(it_id="W2", it_name="덜 인기", it_price=2000)
        members = [get_user_model().objects.create_user(f"m{n}", f"m{n}@example.test", "pw") for n in range(2)]
        for member in members:
            ShopWishlist.objects.create(user=member, product=self.popular, it_id="W1")
        ShopWishlist.objects.create(session_key="guest", product=self.popular, it_id="W1")
        old = ShopWishlist.objects.create(user=members[0], product=self.other, it_id="W2")
        ShopWishlist.objects.filter(pk=old.pk).update(wi_time=timezone.now() - timedelta(days=60))

    def test_ranks_products_by_wishlist_count_with_a_date_filter(self):
        self.client.force_login(staff_with("view_shopwishlist"))
        response = self.client.get(self.url)
        content = response.content.decode()
        self.assertLess(content.index("인기 상품"), content.index("덜 인기"))
        recent = (timezone.localdate() - timedelta(days=7)).isoformat()
        response = self.client.get(self.url, {"date_from": recent})
        self.assertContains(response, "인기 상품")
        self.assertNotContains(response, "덜 인기")
        rows = list(csv.reader(io.StringIO(self.client.get(self.url, {"export": "csv"}).content.decode("utf-8-sig"))))
        self.assertEqual(rows[1][:2], ["1", "W1"])
        self.assertEqual(rows[1][5:8], ["3", "2", "1"])

    def test_needs_the_wishlist_view_permission(self):
        self.client.force_login(staff_with("view_shopproduct"))
        self.assertEqual(self.client.get(self.url).status_code, 403)


@override_settings(SOCIAL_APP_BASE_URL="https://shop.example.test", LEGACY_GNUBOARD5_BASE_URL="")
class PriceFeedTests(TestCase):
    def setUp(self):
        cache.clear()
        ShopCategory.objects.create(ca_id="10", ca_name="의류")
        ShopCategory.objects.create(ca_id="1020", ca_name="바지")
        ShopCategory.objects.create(ca_id="30", ca_name="숨김", ca_use=False)
        category = ShopCategory.objects.get(pk="1020")
        ShopProduct.objects.create(it_id="F1", it_name="청바지\t특가", it_price=30000, category=category, it_stock_qty=5,
                                   image_url="/data/item/F1/a.jpg", it_brand="브랜드", it_point_type=0, it_point=300,
                                   it_sc_type=3, it_sc_price=2500, it_use_cnt=4)
        ShopProduct.objects.create(it_id="F2", it_name="품절", it_price=1000, it_soldout="1")
        ShopProduct.objects.create(it_id="F3", it_name="판매안함", it_price=1000, it_use="0")
        ShopProduct.objects.create(it_id="F4", it_name="전화문의", it_price=1000, it_tel_inq="1")
        ShopProduct.objects.create(it_id="F5", it_name="재고없음", it_price=1000, it_stock_qty=0)
        ShopProduct.objects.create(it_id="F6", it_name="숨긴분류", it_price=1000, category_id="30")
        ShopProduct.objects.create(it_id="F7", it_name="옵션재고", it_price=1000, it_stock_qty=0,
                                   options=[{"io_id": "S", "io_type": 0, "io_stock_qty": 2, "io_use": 1}], it_sc_type=2,
                                   it_sc_method=1)

    def test_feed_is_off_until_enabled(self):
        self.assertEqual(self.client.get(reverse("api_v1:shop-price-naver")).status_code, 404)
        self.assertEqual(self.client.get("/shop/price/naver.php").status_code, 404)

    def test_naver_ep_lists_only_orderable_products(self):
        price_feed.set_feed_enabled(True)
        response = self.client.get(reverse("api_v1:shop-price-naver"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("public", response["Cache-Control"])
        lines = response.content.decode("utf-8").splitlines()
        self.assertEqual(lines[0].split("\t"), list(price_feed.COLUMNS))
        rows = {line.split("\t")[0]: line.split("\t") for line in lines[1:]}
        self.assertEqual(set(rows), {"F1", "F7"})
        first = dict(zip(price_feed.COLUMNS, rows["F1"]))
        self.assertEqual(first["title"], "청바지 특가")
        self.assertEqual(first["link"], "https://shop.example.test/shop/F1")
        self.assertEqual(first["image_link"], "https://shop.example.test/data/item/F1/a.jpg")
        self.assertEqual((first["category_name1"], first["category_name2"], first["category_name3"]), ("의류", "바지", ""))
        self.assertEqual((first["point"], first["review_count"], first["shipping"], first["class"]), ("300", "4", "2500", "I"))
        self.assertEqual(dict(zip(price_feed.COLUMNS, rows["F7"]))["shipping"], "-1")
        self.assertEqual(self.client.get("/shop/price/naver.php").content, response.content)

    def test_feed_is_cached_until_cleared(self):
        price_feed.set_feed_enabled(True)
        self.client.get(reverse("api_v1:shop-price-naver"))
        ShopProduct.objects.filter(pk="F1").update(it_name="바뀐 이름")
        self.assertNotIn("바뀐 이름", self.client.get(reverse("api_v1:shop-price-naver")).content.decode())
        price_feed.clear_feed_cache()
        self.assertIn("바뀐 이름", self.client.get(reverse("api_v1:shop-price-naver")).content.decode())

    def feed(self):
        return self.client.get(reverse("api_v1:shop-price-naver"))

    def test_saving_or_deleting_a_product_refreshes_the_feed(self):
        price_feed.set_feed_enabled(True)
        self.assertIn("청바지", self.feed().content.decode())
        product = ShopProduct.objects.get(pk="F1")
        product.it_name = "새 청바지"
        product.save()
        self.assertIn("새 청바지", self.feed().content.decode())
        ShopProduct.objects.get(pk="F7").delete()
        self.assertNotIn("옵션재고", self.feed().content.decode())
        category = ShopCategory.objects.get(pk="10")
        category.ca_name = "옷"
        category.save()
        self.assertIn("\t옷\t", self.feed().content.decode())

    def test_only_one_request_builds_a_generation_the_others_get_the_last_text(self):
        price_feed.set_feed_enabled(True)
        first = self.feed().content
        price_feed.clear_feed_cache()
        base = "https://shop.example.test"
        lock = price_feed.LOCK_KEY.format(generation=price_feed._generation(), base=base)
        self.assertTrue(cache.add(lock, "1", 60))  # another worker is building
        with patch.object(price_feed, "build_feed", side_effect=AssertionError("built twice")):
            self.assertEqual(self.feed().content, first)
            cache.delete(price_feed.STALE_KEY.format(base=base))
            response = self.feed()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response["Retry-After"], str(price_feed.RETRY_AFTER_SECONDS))
        cache.delete(lock)
        self.assertEqual(self.feed().status_code, 200)

    def test_one_address_cannot_fetch_the_feed_without_limit(self):
        price_feed.set_feed_enabled(True)
        with patch.object(price_feed, "THROTTLE_LIMIT", 2):
            statuses = [self.feed().status_code for _ in range(3)]
        self.assertEqual(statuses, [200, 200, 429])

    def test_admin_page_toggles_the_feed_with_product_change_permission(self):
        url = reverse("admin:shop_shopproduct_price_compare")
        viewer = staff_with("view_shopproduct")
        self.client.force_login(viewer)
        response = self.client.get(url)
        self.assertContains(response, "https://shop.example.test/api/v1/shop/price/naver.tsv")
        self.assertEqual(self.client.post(url, {"action": "enable"}).status_code, 403)
        self.client.force_login(staff_with("view_shopproduct", "change_shopproduct"))
        self.client.post(url, {"action": "enable"})
        self.assertEqual(Config.objects.get(name=price_feed.ENABLED_CONFIG).value, "1")
        self.client.post(url, {"action": "disable"})
        self.assertFalse(price_feed.feed_enabled())
        self.client.force_login(staff_with("view_shoporder"))
        self.assertEqual(self.client.get(url).status_code, 403)
