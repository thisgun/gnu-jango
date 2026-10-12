"""Coupon rules of the shop: discount maths, matching, the coupon zone and coupons at checkout.

Covers gnu_jango/api/shop_coupons.py and the coupon parts of gnu_jango/api/v1_shop.py through the
public /api/v1/shop/... routes. The reference is YoungCart (shop/orderformupdate.php,
shop/ajax.coupondownload.php, shop/orderitemcoupon.php, shop/ordersendcostcoupon.php).

Tests marked ``expectedFailure`` pin the YoungCart behaviour that the port does not follow yet;
the comment above each one names the defect.
"""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api.shop_coupons import (
    coupon_discount,
    coupon_matches_cart_item,
    coupon_payload,
    coupon_zone_payload,
    valid_coupons_queryset,
)
from gnu_jango.config.models import Config
from gnu_jango.shop.models import (
    ShopCategory,
    ShopCoupon,
    ShopCouponLog,
    ShopCouponZone,
    ShopOrder,
    ShopProduct,
    ShopShippingCost,
    ShopShippingPolicy,
)
from gnu_jango.users.models import Profile, User_Point

API = "/api/v1/shop"
def today():
    """Read when each test runs, so a run that crosses midnight compares like with like."""
    return timezone.localdate()

RED = {"io_id": "Red", "io_type": 0, "io_price": 0, "io_stock_qty": 50, "io_use": 1}
BLUE = {"io_id": "Blue", "io_type": 0, "io_price": 0, "io_stock_qty": 50, "io_use": 1}


def unsaved_coupon(**fields):
    values = {"cp_type": 0, "cp_price": 0, "cp_minimum": 0, "cp_maximum": 0, "cp_trunc": 1}
    values.update(fields)
    return ShopCoupon(**values)


class CouponDiscountTests(SimpleTestCase):
    """coupon_discount follows the YoungCart formula: floor to the trunc unit, then the cap."""

    def test_fixed_coupon_gives_its_price(self):
        self.assertEqual(coupon_discount(unsaved_coupon(cp_price=3000), 50000), 3000)

    def test_fixed_coupon_never_exceeds_the_amount(self):
        self.assertEqual(coupon_discount(unsaved_coupon(cp_price=9000), 4000), 4000)

    def test_percent_coupon_takes_the_share_of_the_amount(self):
        self.assertEqual(coupon_discount(unsaved_coupon(cp_type=1, cp_price=10), 12345), 1234)

    def test_percent_coupon_rounds_down_to_the_trunc_unit(self):
        coupon = unsaved_coupon(cp_type=1, cp_price=10, cp_trunc=100)
        self.assertEqual(coupon_discount(coupon, 12345), 1200)

    def test_trunc_of_one_or_zero_does_not_round(self):
        for trunc in (0, 1):
            with self.subTest(trunc=trunc):
                self.assertEqual(coupon_discount(unsaved_coupon(cp_type=1, cp_price=10, cp_trunc=trunc), 12345), 1234)

    def test_maximum_caps_a_percent_coupon(self):
        coupon = unsaved_coupon(cp_type=1, cp_price=50, cp_maximum=3000)
        self.assertEqual(coupon_discount(coupon, 100000), 3000)

    def test_maximum_caps_a_fixed_coupon(self):
        self.assertEqual(coupon_discount(unsaved_coupon(cp_price=8000, cp_maximum=5000), 100000), 5000)

    def test_zero_maximum_means_no_cap(self):
        self.assertEqual(coupon_discount(unsaved_coupon(cp_type=1, cp_price=50, cp_maximum=0), 100000), 50000)

    def test_below_the_minimum_gives_nothing(self):
        coupon = unsaved_coupon(cp_price=3000, cp_minimum=30000)
        self.assertEqual(coupon_discount(coupon, 29999), 0)

    def test_exactly_the_minimum_counts(self):
        coupon = unsaved_coupon(cp_price=3000, cp_minimum=30000)
        self.assertEqual(coupon_discount(coupon, 30000), 3000)

    def test_percent_above_one_hundred_is_capped_at_the_amount(self):
        self.assertEqual(coupon_discount(unsaved_coupon(cp_type=1, cp_price=250), 4000), 4000)

    def test_negative_coupon_price_gives_nothing(self):
        self.assertEqual(coupon_discount(unsaved_coupon(cp_price=-500), 4000), 0)

    def test_zero_negative_and_unparsable_amounts_give_nothing(self):
        coupon = unsaved_coupon(cp_price=3000)
        for amount in (0, -100, None, "", "abc"):
            with self.subTest(amount=amount):
                self.assertEqual(coupon_discount(coupon, amount), 0)

    def test_amount_given_as_text_is_understood(self):
        self.assertEqual(coupon_discount(unsaved_coupon(cp_price=3000), "10000"), 3000)

    def test_large_amount_keeps_integer_precision(self):
        coupon = unsaved_coupon(cp_type=1, cp_price=33)
        self.assertEqual(coupon_discount(coupon, 9_999_999_999), 3_299_999_999)


class CouponTestBase(TestCase):
    """A member with products in two categories, bank transfer enabled and helpers for checkout."""

    def setUp(self):
        user_model = get_user_model()
        self.member = user_model.objects.create_user(username="cp-member", email="cp-member@example.test", password="password")
        self.other = user_model.objects.create_user(username="cp-other", email="cp-other@example.test", password="password")
        self.profile, _ = Profile.objects.get_or_create(user=self.member)
        self.cat_a = ShopCategory.objects.create(ca_id="30", ca_name="Category A")
        self.cat_b = ShopCategory.objects.create(ca_id="40", ca_name="Category B")
        self.big = ShopProduct.objects.create(it_id="BIG01", category=self.cat_a, it_name="Big product", it_price=100000, it_stock_qty=50, it_use="1")
        self.small = ShopProduct.objects.create(it_id="SML01", category=self.cat_b, it_name="Small product", it_price=10000, it_stock_qty=50, it_use="1")
        self.shirt = ShopProduct.objects.create(
            it_id="OPT01", category=self.cat_a, it_name="Optioned", it_price=20000, it_stock_qty=50, it_use="1",
            it_option_subject="Color", options=[RED, BLUE],
        )
        ShopShippingPolicy.objects.update_or_create(
            pk=1,
            defaults={"de_delivery_company": "Courier", "de_settle_min_point": 1000, "de_settle_max_point": 100000, "de_settle_point_unit": 100},
        )
        Config.objects.update_or_create(name="de_bank_use", defaults={"value": "1"})
        Config.objects.update_or_create(name="de_bank_account", defaults={"value": "Test Bank 000-00 Holder"})
        self.client = APIClient()
        self.client.force_authenticate(user=self.member)

    def coupon(self, **extra):
        values = {
            "user": self.member, "cp_subject": "Coupon", "cp_method": 2, "cp_type": 0, "cp_price": 7000, "cp_minimum": 0,
            "cp_start": today() - timedelta(days=5), "cp_end": today() + timedelta(days=5),
        }
        values.update(extra)
        return ShopCoupon.objects.create(**values)

    def zone(self, **extra):
        values = {
            "cz_subject": "Zone coupon", "cz_start": today() - timedelta(days=1), "cz_end": today() + timedelta(days=10),
            "cz_period": 10, "cp_method": 2, "cp_type": 0, "cp_price": 3000,
        }
        values.update(extra)
        return ShopCouponZone.objects.create(**values)

    def add(self, product, qty=1):
        response = self.client.post(f"{API}/cart", {"it_id": product.it_id, "ct_qty": qty}, format="json")
        self.assertIn(response.status_code, (200, 201), response.content[:300])
        return response.json()["data"]["ct_id"]

    def add_options(self, product, *io_ids):
        response = self.client.post(f"{API}/cart", {"it_id": product.it_id, "options": [{"io_id": io} for io in io_ids]}, format="json")
        self.assertIn(response.status_code, (200, 201), response.content[:300])
        return [row["ct_id"] for row in response.json()["data"]["items_created"]]

    def apply(self, ct_id, cp_id):
        return self.client.post(f"{API}/coupons/apply-to-cart", {"ct_id": ct_id, "cp_id": cp_id}, format="json")

    def place(self, **fields):
        base = {
            "od_name": "Member", "od_tel": "010-1111-2222", "od_hp": "010-1111-2222", "od_email": "cp-member@example.test",
            "od_zip": "06236", "od_addr1": "Seoul", "od_addr2": "1",
            "od_b_name": "Member", "od_b_tel": "010-1111-2222", "od_b_hp": "010-1111-2222",
            "od_b_zip": "06236", "od_b_addr1": "Seoul", "od_b_addr2": "1",
            "od_settle_case": "bank", "od_bank_account": "Test Bank 000-00 Holder", "od_deposit_name": "Member",
        }
        return self.client.post(f"{API}/orders", {**base, **fields}, format="json")

    def placed(self, **fields):
        response = self.place(**fields)
        self.assertEqual(response.status_code, 201, response.content[:400])
        return ShopOrder.objects.get(pk=response.json()["data"]["od_id"])

    def payable(self, order):
        return order.od_receipt_price + order.od_misu

    def used(self, coupon):
        coupon.refresh_from_db()
        return coupon.cp_used


class ValidCouponQuerysetTests(CouponTestBase):
    def ids(self, user=None):
        return {c.cp_id for c in valid_coupons_queryset(user or self.member)}

    def test_coupon_valid_today_is_listed_including_both_edge_days(self):
        starts_today = self.coupon(cp_start=today(), cp_end=today() + timedelta(days=3))
        ends_today = self.coupon(cp_start=today() - timedelta(days=3), cp_end=today())
        self.assertEqual(self.ids(), {starts_today.cp_id, ends_today.cp_id})

    def test_coupon_without_an_end_date_never_expires(self):
        open_ended = self.coupon(cp_end=None)
        self.assertEqual(self.ids(), {open_ended.cp_id})

    def test_expired_not_started_used_and_foreign_coupons_are_left_out(self):
        self.coupon(cp_end=today() - timedelta(days=1))
        self.coupon(cp_start=today() + timedelta(days=1), cp_end=today() + timedelta(days=9))
        self.coupon(cp_used="1")
        self.coupon(user=self.other)
        self.assertEqual(self.ids(), set())


class CouponMatchingTests(CouponTestBase):
    def line(self, product):
        return {"it_id": product.it_id}

    def test_product_coupon_matches_only_its_product(self):
        coupon = self.coupon(cp_method=0, cp_target="BIG01")
        self.assertTrue(coupon_matches_cart_item(coupon, self.line(self.big)))
        self.assertFalse(coupon_matches_cart_item(coupon, self.line(self.small)))

    def test_category_coupon_matches_every_category_slot_of_the_product(self):
        self.small.category2 = self.cat_a
        self.small.save()
        coupon = self.coupon(cp_method=1, cp_target="30")
        self.assertTrue(coupon_matches_cart_item(coupon, self.line(self.big)))
        self.assertTrue(coupon_matches_cart_item(coupon, self.line(self.small)))
        self.assertFalse(coupon_matches_cart_item(self.coupon(cp_method=1, cp_target="99"), self.line(self.big)))

    def test_category_coupon_does_not_match_an_unknown_product(self):
        coupon = self.coupon(cp_method=1, cp_target="30")
        self.assertFalse(coupon_matches_cart_item(coupon, {"it_id": "GONE"}))

    def test_order_and_shipping_coupons_match_any_line(self):
        for method in (2, 3):
            with self.subTest(method=method):
                self.assertTrue(coupon_matches_cart_item(self.coupon(cp_method=method), self.line(self.big)))

    def test_unknown_method_matches_nothing(self):
        self.assertFalse(coupon_matches_cart_item(self.coupon(cp_method=9), self.line(self.big)))


class CouponPayloadTests(CouponTestBase):
    def test_payload_lists_the_terms_and_the_discount_for_the_amount(self):
        coupon = self.coupon(cp_type=1, cp_price=10, cp_minimum=1000, cp_maximum=2000, cp_trunc=100)
        payload = coupon_payload(coupon, amount=50000)
        self.assertEqual(payload["cp_id"], coupon.cp_id)
        self.assertEqual((payload["cp_type"], payload["cp_price"], payload["cp_minimum"], payload["cp_maximum"], payload["cp_trunc"]), (1, 10, 1000, 2000, 100))
        self.assertEqual(payload["discount"], 2000)
        self.assertEqual(payload["cp_start"], coupon.cp_start.isoformat())
        self.assertEqual(payload["cp_end"], coupon.cp_end.isoformat())

    def test_payload_without_dates_uses_empty_strings_and_zero_discount(self):
        coupon = unsaved_coupon(cp_id="X1", cp_subject="Undated", cp_price=500, cp_start=None, cp_end=None, cp_used="")
        payload = coupon_payload(coupon)
        self.assertEqual((payload["cp_start"], payload["cp_end"], payload["discount"]), ("", "", 0))


class CouponZonePayloadTests(CouponTestBase):
    def test_product_zone_names_the_product_and_links_to_it(self):
        payload = coupon_zone_payload(self.zone(cp_method=0, cp_target="BIG01"))
        self.assertEqual((payload["target_name"], payload["target_href"]), ("Big product", "/shop/products/BIG01"))

    def test_product_zone_with_a_missing_product_falls_back_to_the_target_id(self):
        payload = coupon_zone_payload(self.zone(cp_method=0, cp_target="GONE"))
        self.assertEqual(payload["target_name"], "GONE")

    def test_category_zone_names_the_category(self):
        payload = coupon_zone_payload(self.zone(cp_method=1, cp_target="40"))
        self.assertEqual((payload["target_name"], payload["target_href"], payload["target_label"]), ("Category B", "/shop/categories/40", "Category coupon"))

    def test_category_zone_with_a_missing_category_falls_back_to_the_target_id(self):
        self.assertEqual(coupon_zone_payload(self.zone(cp_method=1, cp_target="77"))["target_name"], "77")

    def test_order_and_shipping_zones_have_no_target(self):
        order_zone = coupon_zone_payload(self.zone(cp_method=2))
        shipping_zone = coupon_zone_payload(self.zone(cp_method=3))
        self.assertEqual((order_zone["target_label"], order_zone["target_name"]), ("Order discount", ""))
        self.assertEqual((shipping_zone["target_label"], shipping_zone["target_href"]), ("Shipping discount", ""))

    def test_downloaded_flag_follows_the_member_and_ignores_strangers(self):
        zone = self.zone()
        self.assertFalse(coupon_zone_payload(zone, user=self.member)["downloaded"])
        self.coupon(coupon_zone=zone)
        self.assertTrue(coupon_zone_payload(zone, user=self.member)["downloaded"])
        self.assertFalse(coupon_zone_payload(zone, user=self.other)["downloaded"])
        self.assertFalse(coupon_zone_payload(zone)["downloaded"])

    def test_dates_are_empty_when_the_zone_has_no_end(self):
        payload = coupon_zone_payload(self.zone(cz_end=None))
        self.assertEqual(payload["cz_end"], "")
        self.assertEqual(payload["cz_start"], (today() - timedelta(days=1)).isoformat())


class CouponListTests(CouponTestBase):
    def test_zone_list_shows_only_zones_open_today_and_marks_downloads(self):
        open_zone = self.zone(cz_subject="Open")
        self.zone(cz_subject="Ended", cz_end=today() - timedelta(days=1))
        self.zone(cz_subject="Future", cz_start=today() + timedelta(days=1), cz_end=today() + timedelta(days=9))
        self.coupon(coupon_zone=open_zone)
        data = self.client.get(f"{API}/coupons/zone").json()["data"]
        self.assertEqual([(row["cz_subject"], row["downloaded"]) for row in data], [("Open", True)])

    def test_zone_list_is_public(self):
        self.zone()
        data = APIClient().get(f"{API}/coupons/zone").json()["data"]
        self.assertEqual((len(data), data[0]["downloaded"]), (1, False))

    def test_mine_lists_only_the_members_coupons(self):
        mine = self.coupon()
        self.coupon(user=self.other)
        data = self.client.get(f"{API}/coupons/mine").json()["data"]
        self.assertEqual([row["cp_id"] for row in data], [mine.cp_id])

    def test_mine_is_empty_for_a_visitor(self):
        self.coupon()
        response = APIClient().get(f"{API}/coupons/mine?per_page=5")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"], [])

    def test_mine_can_be_narrowed_to_one_method(self):
        self.coupon(cp_method=2)
        shipping = self.coupon(cp_method=3)
        data = self.client.get(f"{API}/coupons?method=3").json()["data"]
        self.assertEqual([row["cp_id"] for row in data], [shipping.cp_id])

    def test_mine_is_paged(self):
        for _ in range(3):
            self.coupon()
        response = self.client.get(f"{API}/coupons/mine?per_page=2")
        self.assertEqual(len(response.json()["data"]), 2)


class CouponDownloadTests(CouponTestBase):
    def download(self, zone, client=None):
        return (client or self.client).post(f"{API}/coupons/download", {"cz_id": zone.pk}, format="json")

    def test_download_issues_a_coupon_with_the_zone_terms_and_counts_it(self):
        zone = self.zone(cp_type=1, cp_price=15, cp_minimum=20000, cp_maximum=4000, cp_trunc=10, cz_subject="Spring", cz_period=10)
        response = self.download(zone)
        self.assertEqual(response.status_code, 201, response.content[:300])
        coupon = ShopCoupon.objects.get(user=self.member, coupon_zone=zone)
        self.assertEqual(response.json()["data"]["cp_id"], coupon.cp_id)
        self.assertEqual(
            (coupon.cp_subject, coupon.cp_method, coupon.cp_type, coupon.cp_price, coupon.cp_minimum, coupon.cp_maximum, coupon.cp_trunc, coupon.cp_used),
            ("Spring", 2, 1, 15, 20000, 4000, 10, ""),
        )
        self.assertEqual(coupon.cp_start, today())
        zone.refresh_from_db()
        self.assertEqual(zone.cz_download, 1)

    def test_download_needs_a_login(self):
        response = self.download(self.zone(), client=APIClient())
        self.assertEqual(response.status_code, 401)
        self.assertFalse(ShopCoupon.objects.exists())

    def test_unknown_zone_is_refused(self):
        response = self.client.post(f"{API}/coupons/download", {"cz_id": 99999}, format="json")
        self.assertEqual((response.status_code, response.json()["code"]), (404, "coupon_zone_not_found"))

    def test_a_second_download_of_the_same_zone_is_refused_and_issues_nothing(self):
        zone = self.zone()
        self.download(zone)
        response = self.download(zone)
        self.assertEqual((response.status_code, response.json()["code"]), (400, "already_downloaded"))
        self.assertEqual(ShopCoupon.objects.filter(user=self.member, coupon_zone=zone).count(), 1)
        zone.refresh_from_db()
        self.assertEqual(zone.cz_download, 1)

    def test_two_members_can_each_download_a_zone_once(self):
        zone = self.zone()
        other_client = APIClient()
        other_client.force_authenticate(user=self.other)
        self.assertEqual(self.download(zone).status_code, 201)
        self.assertEqual(self.download(zone, client=other_client).status_code, 201)
        zone.refresh_from_db()
        self.assertEqual(zone.cz_download, 2)

    def test_point_zone_takes_the_points(self):
        self.profile.user_point = 5000
        self.profile.save(update_fields=["user_point"])
        zone = self.zone(cz_type=1, cz_point=2000)
        self.assertEqual(self.download(zone).status_code, 201)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.user_point, 3000)

    def test_point_zone_is_refused_when_the_balance_is_short_and_nothing_changes(self):
        self.profile.user_point = 1500
        self.profile.save(update_fields=["user_point"])
        zone = self.zone(cz_type=1, cz_point=2000)
        response = self.download(zone)
        self.assertEqual((response.status_code, response.json()["code"]), (422, "not_enough_points"))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.user_point, 1500)
        self.assertFalse(ShopCoupon.objects.exists())

    def test_the_whole_balance_can_pay_a_point_zone(self):
        self.profile.user_point = 2000
        self.profile.save(update_fields=["user_point"])
        self.assertEqual(self.download(self.zone(cz_type=1, cz_point=2000)).status_code, 201)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.user_point, 0)

    def test_downloaded_coupon_is_usable_at_checkout(self):
        zone = self.zone(cp_price=3000)
        cp_id = self.download(zone).json()["data"]["cp_id"]
        self.add(self.big)
        order = self.placed(cp_id=cp_id)
        self.assertEqual(order.od_coupon, 3000)

    # Defect (api/v1_shop.py coupon_download_view): the points are taken before the duplicate check,
    # so a member who presses download again on a point zone loses the points and gets no coupon.
    # YoungCart ajax.coupondownload.php refuses a duplicate before it looks at the points.
    def test_a_repeated_download_of_a_point_zone_costs_no_points(self):
        self.profile.user_point = 5000
        self.profile.save(update_fields=["user_point"])
        zone = self.zone(cz_type=1, cz_point=2000)
        self.download(zone)
        self.download(zone)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.user_point, 3000)

    # Defect (coupon_download_view, no zone date check): an ended or not yet started zone can still
    # be downloaded by id. YoungCart: "다운로드할 수 없는 쿠폰입니다." unless cz_start <= today <= cz_end.
    def test_an_ended_zone_cannot_be_downloaded(self):
        zone = self.zone(cz_end=today() - timedelta(days=1))
        self.assertEqual(self.download(zone).status_code, 400)
        self.assertFalse(ShopCoupon.objects.exists())

    def test_a_zone_that_has_not_started_cannot_be_downloaded(self):
        zone = self.zone(cz_start=today() + timedelta(days=1), cz_end=today() + timedelta(days=9))
        self.assertEqual(self.download(zone).status_code, 400)
        self.assertFalse(ShopCoupon.objects.exists())

    # Defect (issue_coupon_from_zone / coupon_zone_payload filter cp_used=""): once the downloaded
    # coupon is used the member can download the zone again, so a one-per-member coupon can be
    # reused without limit. YoungCart is_coupon_downloaded counts used coupons too.
    def test_a_zone_coupon_that_was_used_cannot_be_downloaded_again(self):
        zone = self.zone()
        first = self.download(zone).json()["data"]["cp_id"]
        ShopCoupon.objects.filter(pk=first).update(cp_used="1")
        self.assertEqual(self.download(zone).status_code, 400)
        self.assertEqual(ShopCoupon.objects.filter(user=self.member, coupon_zone=zone).count(), 1)

    def test_the_zone_list_still_shows_a_used_zone_coupon_as_downloaded(self):
        zone = self.zone()
        self.coupon(coupon_zone=zone, cp_used="1")
        self.assertTrue(coupon_zone_payload(zone, user=self.member)["downloaded"])

    # Defect (issue_coupon_from_zone: end_date = today + max(1, cz_period)): the coupon lives one day
    # longer than the zone period. YoungCart sets cp_end = today + (cz_period - 1) days.
    def test_a_one_day_zone_coupon_ends_today(self):
        zone = self.zone(cz_period=1)
        self.download(zone)
        self.assertEqual(ShopCoupon.objects.get(user=self.member).cp_end, today())

    def test_a_ten_day_zone_coupon_ends_on_the_tenth_day(self):
        zone = self.zone(cz_period=10)
        self.download(zone)
        self.assertEqual(ShopCoupon.objects.get(user=self.member).cp_end, today() + timedelta(days=9))

    # Defect (coupon_download_view: `if zone.cz_point > 0`): points are charged for any zone that has
    # a cz_point value; YoungCart charges only zones of the point type (cz_type = 1).
    def test_a_free_zone_with_a_leftover_point_value_costs_nothing(self):
        self.profile.user_point = 5000
        self.profile.save(update_fields=["user_point"])
        self.download(self.zone(cz_type=0, cz_point=2000))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.user_point, 5000)

    # Defect (coupon_download_view edits Profile.user_point directly): the charge leaves no row in
    # the member's point history, so the balance no longer matches the ledger.
    # YoungCart writes insert_point(..., "쿠폰 {cp_id} 발급").
    def test_the_point_charge_is_written_to_the_point_history(self):
        self.profile.user_point = 5000
        self.profile.save(update_fields=["user_point"])
        self.download(self.zone(cz_type=1, cz_point=2000))
        self.assertEqual(User_Point.objects.filter(user=self.member, po_point=-2000).count(), 1)


class ApplicableCouponTests(CouponTestBase):
    def applicable(self, ct_id=None):
        suffix = f"?ct_id={ct_id}" if ct_id else ""
        return self.client.get(f"{API}/coupons/applicable{suffix}")

    def test_applicable_needs_a_login(self):
        self.assertEqual(APIClient().get(f"{API}/coupons/applicable").status_code, 401)

    def test_for_a_line_only_matching_valid_coupons_are_listed_with_their_discount(self):
        ct_id = self.add(self.big)
        match = self.coupon(cp_method=0, cp_target="BIG01", cp_type=1, cp_price=10)
        self.coupon(cp_method=0, cp_target="SML01")
        self.coupon(cp_method=0, cp_target="BIG01", cp_end=today() - timedelta(days=1))
        self.coupon(cp_method=0, cp_target="BIG01", user=self.other)
        data = self.applicable(ct_id).json()["data"]
        self.assertEqual([(row["cp_id"], row["discount"]) for row in data], [(match.cp_id, 10000)])

    def test_without_a_line_every_valid_coupon_is_priced_against_the_cart_total(self):
        self.add(self.big)
        self.add(self.small)
        coupon = self.coupon(cp_type=1, cp_price=10)
        data = self.applicable().json()["data"]
        self.assertEqual([(row["cp_id"], row["discount"]) for row in data], [(coupon.cp_id, 11000)])

    def test_coupon_below_its_minimum_is_listed_with_zero_discount(self):
        ct_id = self.add(self.small)
        self.coupon(cp_method=1, cp_target="40", cp_minimum=50000)
        self.assertEqual(self.applicable(ct_id).json()["data"][0]["discount"], 0)

    # Defect (coupon_applicable_view + coupon_matches_cart_item): the item coupon picker also offers
    # order and shipping coupons for a line. YoungCart orderitemcoupon.php lists only cp_method 0 and 1.
    def test_the_item_coupon_list_does_not_offer_order_or_shipping_coupons(self):
        ct_id = self.add(self.big)
        item_coupon = self.coupon(cp_method=0, cp_target="BIG01")
        self.coupon(cp_method=2)
        self.coupon(cp_method=3)
        data = self.applicable(ct_id).json()["data"]
        self.assertEqual([row["cp_id"] for row in data], [item_coupon.cp_id])

    def test_legacy_order_list_has_every_valid_coupon_priced_on_the_cart(self):
        self.add(self.big)
        coupon = self.coupon(cp_price=2500)
        data = self.client.get(f"{API}/coupons/legacy-order").json()["data"]["coupons"]
        self.assertEqual([(row["cp_id"], row["discount"]) for row in data], [(coupon.cp_id, 2500)])

    def test_legacy_item_list_keeps_only_coupons_that_match_the_line(self):
        ct_id = self.add(self.big)
        match = self.coupon(cp_method=0, cp_target="BIG01")
        self.coupon(cp_method=0, cp_target="SML01")
        data = self.client.get(f"{API}/coupons/legacy-item?ct_id={ct_id}").json()["data"]["coupons"]
        self.assertEqual([row["cp_id"] for row in data], [match.cp_id])

    def test_legacy_lists_need_a_login(self):
        self.assertEqual(APIClient().get(f"{API}/coupons/legacy-item").status_code, 401)


class ApplyToCartTests(CouponTestBase):
    def cart_line(self):
        return self.client.get(f"{API}/cart").json()["data"]["items"][0]

    def test_applying_a_matching_coupon_stores_the_choice_and_the_discount(self):
        ct_id = self.add(self.big)
        coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_type=1, cp_price=10, cp_maximum=4000)
        response = self.apply(ct_id, coupon.cp_id)
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual((response.json()["data"]["discount"], response.json()["data"]["ct_id"]), (4000, ct_id))
        line = self.cart_line()
        self.assertEqual((line["cp_id"], line["cp_price"]), (coupon.cp_id, 4000))
        self.assertEqual(self.client.get(f"{API}/cart").json()["data"]["cart_coupon"], 4000)

    def test_an_empty_coupon_clears_the_choice(self):
        ct_id = self.add(self.big)
        coupon = self.coupon(cp_method=0, cp_target="BIG01")
        self.apply(ct_id, coupon.cp_id)
        response = self.apply(ct_id, "")
        self.assertEqual(response.status_code, 200)
        line = self.cart_line()
        self.assertEqual((line["cp_id"], line["cp_price"]), ("", 0))

    def test_a_coupon_for_another_product_is_refused(self):
        ct_id = self.add(self.big)
        coupon = self.coupon(cp_method=0, cp_target="SML01")
        response = self.apply(ct_id, coupon.cp_id)
        self.assertEqual((response.status_code, response.json()["code"]), (400, "coupon_not_applicable"))
        self.assertEqual(self.cart_line()["cp_id"], "")

    def test_a_category_coupon_of_another_category_is_refused(self):
        ct_id = self.add(self.big)
        coupon = self.coupon(cp_method=1, cp_target="40")
        self.assertEqual(self.apply(ct_id, coupon.cp_id).status_code, 400)

    def test_a_category_coupon_applies_to_a_product_of_that_category(self):
        ct_id = self.add(self.small)
        coupon = self.coupon(cp_method=1, cp_target="40", cp_price=1500)
        self.assertEqual(self.apply(ct_id, coupon.cp_id).json()["data"]["discount"], 1500)

    def test_an_unknown_expired_used_or_foreign_coupon_is_not_found(self):
        ct_id = self.add(self.big)
        cases = [
            "NOPE",
            self.coupon(cp_method=0, cp_target="BIG01", cp_end=today() - timedelta(days=1)).cp_id,
            self.coupon(cp_method=0, cp_target="BIG01", cp_used="1").cp_id,
            self.coupon(cp_method=0, cp_target="BIG01", user=self.other).cp_id,
        ]
        for cp_id in cases:
            with self.subTest(cp_id=cp_id):
                response = self.apply(ct_id, cp_id)
                self.assertEqual((response.status_code, response.json()["code"]), (404, "coupon_not_found"))

    def test_an_unknown_cart_line_is_not_found(self):
        coupon = self.coupon()
        response = self.apply("999", coupon.cp_id)
        self.assertEqual((response.status_code, response.json()["code"]), (404, "cart_item_not_found"))

    def test_applying_needs_a_login(self):
        self.assertEqual(APIClient().post(f"{API}/coupons/apply-to-cart", {"ct_id": "1"}, format="json").status_code, 401)

    # Defect (coupon_apply_cart_view): an order or shipping coupon can be attached to a cart line, and
    # the cart then shows its discount as an item discount. YoungCart item coupons are cp_method 0/1.
    def test_an_order_coupon_cannot_be_attached_to_a_cart_line(self):
        ct_id = self.add(self.big)
        coupon = self.coupon(cp_method=2, cp_price=7000)
        self.assertEqual(self.apply(ct_id, coupon.cp_id).status_code, 400)
        self.assertEqual(self.client.get(f"{API}/cart").json()["data"]["cart_coupon"], 0)


class ItemCouponOrderTests(CouponTestBase):
    """Product and category coupons at order time."""

    def test_percent_item_coupon_is_capped_by_its_maximum_and_logged(self):
        coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_type=1, cp_price=20, cp_maximum=12000)
        ct_id = self.add(self.big)
        self.apply(ct_id, coupon.cp_id)
        order = self.placed()
        self.assertEqual(order.coupon_logs.get().cp_price, 12000)
        self.assertEqual(self.payable(order), 100000 - 12000)
        self.assertEqual(self.used(coupon), "1")

    def test_item_coupon_discounts_the_whole_line_quantity(self):
        coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_type=1, cp_price=10)
        ct_id = self.add(self.big, qty=3)
        self.apply(ct_id, coupon.cp_id)
        order = self.placed()
        self.assertEqual(order.coupon_logs.get().cp_price, 30000)
        self.assertEqual(self.payable(order), 300000 - 30000)

    def test_item_coupon_below_its_minimum_gives_no_discount_and_stays_unused(self):
        coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_minimum=150000)
        ct_id = self.add(self.big)
        self.apply(ct_id, coupon.cp_id)
        order = self.placed()
        self.assertFalse(order.coupon_logs.exists())
        self.assertEqual(self.payable(order), 100000)
        self.assertEqual(self.used(coupon), "")

    def test_item_coupon_is_judged_on_the_line_after_the_quantity_is_raised(self):
        coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_minimum=150000, cp_price=9000)
        ct_id = self.add(self.big, qty=2)
        self.apply(ct_id, coupon.cp_id)
        order = self.placed()
        self.assertEqual(order.coupon_logs.get().cp_price, 9000)

    def test_item_coupon_never_discounts_more_than_its_line(self):
        coupon = self.coupon(cp_method=0, cp_target="SML01", cp_price=50000)
        ct_id = self.add(self.small)
        self.apply(ct_id, coupon.cp_id)
        order = self.placed()
        discount = sum(log.cp_price for log in order.coupon_logs.all())
        self.assertLessEqual(discount, 10000)
        self.assertGreaterEqual(self.payable(order), order.od_send_cost + order.od_send_cost2)

    def test_item_coupon_only_discounts_its_own_line(self):
        coupon = self.coupon(cp_method=0, cp_target="SML01", cp_price=4000)
        self.add(self.big)
        small_line = self.add(self.small)
        self.apply(small_line, coupon.cp_id)
        order = self.placed()
        self.assertEqual(order.coupon_logs.get().cp_price, 4000)
        self.assertEqual(self.payable(order), 110000 - 4000 + order.od_send_cost + order.od_send_cost2)

    def test_category_coupon_applies_to_a_product_of_the_category_slot(self):
        self.small.category3 = self.cat_a
        self.small.save()
        coupon = self.coupon(cp_method=1, cp_target="30", cp_price=2000)
        ct_id = self.add(self.small)
        self.assertEqual(self.apply(ct_id, coupon.cp_id).status_code, 200)
        order = self.placed()
        self.assertEqual(order.coupon_logs.get().cp_price, 2000)

    def test_an_item_coupon_taken_to_another_product_by_a_stale_cart_is_ignored_at_order_time(self):
        # the cart remembers the coupon id; the checkout must re-check that it still matches the line
        coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_price=5000)
        ct_id = self.add(self.big)
        self.apply(ct_id, coupon.cp_id)
        coupon.cp_target = "SML01"
        coupon.save(update_fields=["cp_target"])
        order = self.placed()
        self.assertFalse(order.coupon_logs.exists())
        self.assertEqual(self.used(coupon), "")

    def test_an_item_coupon_that_has_not_started_gives_no_discount(self):
        coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_price=5000)
        ct_id = self.add(self.big)
        self.apply(ct_id, coupon.cp_id)
        coupon.cp_start = today() + timedelta(days=1)
        coupon.save(update_fields=["cp_start"])
        self.assertFalse(self.placed().coupon_logs.exists())

    def test_an_item_coupon_of_another_member_in_the_cart_gives_no_discount(self):
        coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_price=5000)
        ct_id = self.add(self.big)
        self.apply(ct_id, coupon.cp_id)
        coupon.user = self.other
        coupon.save(update_fields=["user"])
        order = self.placed()
        self.assertFalse(order.coupon_logs.exists())
        self.assertEqual(self.payable(order), 100000)

    def test_an_item_coupon_used_elsewhere_after_it_was_picked_gives_no_discount(self):
        coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_price=5000)
        ct_id = self.add(self.big)
        self.apply(ct_id, coupon.cp_id)
        ShopCoupon.objects.filter(pk=coupon.pk).update(cp_used="1")
        self.assertFalse(self.placed().coupon_logs.exists())

    def test_a_coupon_is_used_by_one_order_only(self):
        coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_price=5000)
        ct_id = self.add(self.big)
        self.apply(ct_id, coupon.cp_id)
        first = self.placed()
        # a second cart that still remembers the same coupon
        ct_id = self.add(self.big)
        self.apply(ct_id, coupon.cp_id)
        second = self.placed()
        self.assertFalse(second.coupon_logs.exists())
        self.assertEqual(self.payable(second), 100000)
        self.assertEqual(ShopCouponLog.objects.filter(cp_id=coupon.cp_id).count(), 1)
        self.assertEqual(first.coupon_logs.count(), 1)

    def test_two_lines_of_different_products_with_the_same_coupon_id_count_it_once(self):
        coupon = self.coupon(cp_method=1, cp_target="30", cp_price=2000)
        first = self.add(self.big)
        second = self.add_options(self.shirt, "Red")[0]
        self.apply(first, coupon.cp_id)
        self.apply(second, coupon.cp_id)
        order = self.placed()
        self.assertEqual(order.coupon_logs.count(), 1)
        self.assertEqual(order.coupon_logs.get().cp_price, 2000)

    def test_cancelling_gives_an_item_coupon_back_and_clears_its_log(self):
        coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_price=5000)
        ct_id = self.add(self.big)
        self.apply(ct_id, coupon.cp_id)
        order = self.placed()
        response = self.client.post(f"{API}/payment/cancel", {"order_id": order.od_id}, format="json")
        self.assertIn(response.status_code, (200, 201), response.content[:300])
        self.assertEqual(self.used(coupon), "")
        self.assertFalse(ShopCouponLog.objects.filter(od_id=order.od_id).exists())

    def test_a_cancelled_coupon_discounts_the_next_order_again(self):
        coupon = self.coupon(cp_price=7000)
        self.add(self.big)
        order = self.placed(cp_id=coupon.cp_id)
        self.client.post(f"{API}/payment/cancel", {"order_id": order.od_id}, format="json")
        self.add(self.big)
        again = self.placed(cp_id=coupon.cp_id)
        self.assertEqual(again.od_coupon, 7000)
        self.assertEqual(self.used(coupon), "1")

    # Defect (v1_shop.create_order_from_request / validated_item_coupons): item coupons are chosen per
    # cart line, so one product added with two options can use two coupons, one per line.
    # YoungCart orderformupdate.php allows one item coupon per product (it sums the product's lines
    # and ignores a second coupon for the same it_id).
    def test_one_product_with_two_option_lines_takes_only_one_item_coupon(self):
        first_coupon = self.coupon(cp_method=0, cp_target="OPT01", cp_price=3000)
        second_coupon = self.coupon(cp_method=0, cp_target="OPT01", cp_price=3000)
        red, blue = self.add_options(self.shirt, "Red", "Blue")
        self.apply(red, first_coupon.cp_id)
        self.apply(blue, second_coupon.cp_id)
        order = self.placed()
        self.assertEqual(sum(log.cp_price for log in order.coupon_logs.all()), 3000)


class OrderCouponOrderTests(CouponTestBase):
    def test_percent_order_coupon_rounds_to_trunc_and_respects_the_maximum(self):
        coupon = self.coupon(cp_type=1, cp_price=7, cp_trunc=1000, cp_maximum=6000)
        self.add(self.big)
        order = self.placed(cp_id=coupon.cp_id)
        # 7 percent of 100000 is 7000, below the cap only after the cap: 6000
        self.assertEqual(order.od_coupon, 6000)
        self.assertEqual(self.payable(order), 100000 - 6000 + order.od_send_cost + order.od_send_cost2)

    def test_percent_order_coupon_rounds_down_to_the_unit(self):
        coupon = self.coupon(cp_type=1, cp_price=3, cp_trunc=100)
        self.add(self.big, qty=1)
        self.add(self.small)
        order = self.placed(cp_id=coupon.cp_id)
        self.assertEqual(order.od_coupon, 3300)

    def test_order_coupon_minimum_is_checked_after_item_coupons(self):
        item_coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_price=30000)
        order_coupon = self.coupon(cp_minimum=80000, cp_price=5000)
        ct_id = self.add(self.big)
        self.apply(ct_id, item_coupon.cp_id)
        order = self.placed(cp_id=order_coupon.cp_id)
        # 100000 - 30000 = 70000 is below the 80000 minimum
        self.assertEqual(order.od_coupon, 0)
        self.assertEqual(self.used(order_coupon), "")
        self.assertEqual(self.used(item_coupon), "1")

    def test_order_coupon_with_the_exact_minimum_applies(self):
        coupon = self.coupon(cp_minimum=100000, cp_price=5000)
        self.add(self.big)
        self.assertEqual(self.placed(cp_id=coupon.cp_id).od_coupon, 5000)

    def test_order_coupon_is_percent_of_the_amount_after_item_coupons(self):
        item_coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_price=20000)
        order_coupon = self.coupon(cp_type=1, cp_price=10)
        ct_id = self.add(self.big)
        self.apply(ct_id, item_coupon.cp_id)
        order = self.placed(cp_id=order_coupon.cp_id)
        self.assertEqual(order.od_coupon, 8000)
        self.assertEqual(self.payable(order), 100000 - 20000 - 8000)

    def test_order_coupon_larger_than_the_order_never_makes_the_total_negative(self):
        coupon = self.coupon(cp_price=500000)
        self.add(self.big)
        order = self.placed(cp_id=coupon.cp_id)
        self.assertLessEqual(order.od_coupon, 100000)
        self.assertGreaterEqual(self.payable(order), 0)
        self.assertEqual(self.payable(order), 100000 - order.od_coupon + order.od_send_cost + order.od_send_cost2)

    def test_the_order_coupon_id_is_also_read_from_cp_id_order(self):
        coupon = self.coupon(cp_price=4000)
        self.add(self.big)
        self.assertEqual(self.placed(cp_id_order=coupon.cp_id).od_coupon, 4000)

    def test_an_item_coupon_id_sent_as_the_order_coupon_is_ignored(self):
        coupon = self.coupon(cp_method=0, cp_target="BIG01", cp_price=4000)
        self.add(self.big)
        order = self.placed(cp_id=coupon.cp_id)
        self.assertEqual(order.od_coupon, 0)
        self.assertEqual(self.used(coupon), "")

    def test_a_shipping_coupon_id_sent_as_the_order_coupon_is_ignored(self):
        coupon = self.coupon(cp_method=3, cp_price=2000)
        self.add(self.small)
        self.assertEqual(self.placed(cp_id=coupon.cp_id).od_coupon, 0)

    def test_two_orders_cannot_share_one_order_coupon_even_while_unpaid(self):
        coupon = self.coupon(cp_price=7000)
        self.add(self.big)
        first = self.placed(cp_id=coupon.cp_id)
        self.add(self.big)
        second = self.placed(cp_id=coupon.cp_id)
        self.assertEqual((first.od_coupon, second.od_coupon), (7000, 0))
        self.assertEqual(ShopCouponLog.objects.filter(cp_id=coupon.cp_id).count(), 1)

    def test_a_guest_order_ignores_a_coupon_id(self):
        coupon = self.coupon(cp_price=7000)
        guest = APIClient()
        guest.post(f"{API}/cart", {"it_id": "BIG01", "ct_qty": 1}, format="json")
        response = guest.post(
            f"{API}/orders",
            {
                "od_name": "Guest", "od_tel": "010", "od_hp": "010-1111-2222", "od_email": "g@example.test", "od_pwd": "secret-pass",
                "od_zip": "06236", "od_addr1": "Seoul", "od_addr2": "1", "od_b_name": "Guest", "od_b_hp": "010-1111-2222",
                "od_b_zip": "06236", "od_b_addr1": "Seoul", "od_b_addr2": "1",
                "od_settle_case": "bank", "od_bank_account": "Test Bank 000-00 Holder", "od_deposit_name": "Guest",
                "cp_id": coupon.cp_id,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertEqual(ShopOrder.objects.get(pk=response.json()["data"]["od_id"]).od_coupon, 0)
        self.assertEqual(self.used(coupon), "")

    def test_cancelling_gives_the_order_coupon_back_for_good(self):
        coupon = self.coupon(cp_price=7000)
        self.add(self.big)
        order = self.placed(cp_id=coupon.cp_id)
        for _ in range(2):
            self.client.post(f"{API}/payment/cancel", {"order_id": order.od_id}, format="json")
        self.assertEqual(self.used(coupon), "")
        self.assertEqual(ShopCouponLog.objects.filter(od_id=order.od_id).count(), 0)

    def test_the_price_change_stop_leaves_the_coupon_unused_and_the_next_try_uses_the_new_price(self):
        coupon = self.coupon(cp_type=1, cp_price=10)
        self.add(self.big)
        self.big.it_price = 80000
        self.big.save(update_fields=["it_price"])
        stopped = self.place(cp_id=coupon.cp_id)
        self.assertEqual(stopped.json()["code"], "cart_price_changed")
        self.assertGreaterEqual(stopped.status_code, 400)
        self.assertEqual(self.used(coupon), "")
        self.assertFalse(ShopOrder.objects.exists())
        order = self.placed(cp_id=coupon.cp_id)
        self.assertEqual(order.od_coupon, 8000)


class ShippingCouponOrderTests(CouponTestBase):
    """Shipping of 3000 applies below the free threshold (default policy)."""

    def test_fixed_shipping_coupon_is_capped_at_the_shipping_cost(self):
        coupon = self.coupon(cp_method=3, cp_price=5000)
        self.add(self.small)
        order = self.placed(cp_id_send=coupon.cp_id)
        self.assertEqual((order.od_send_cost, order.od_send_coupon), (3000, 3000))
        self.assertEqual(self.payable(order), 10000 + 3000 - 3000)
        self.assertEqual(self.used(coupon), "1")

    def test_percent_shipping_coupon_takes_a_share_of_the_shipping(self):
        coupon = self.coupon(cp_method=3, cp_type=1, cp_price=50)
        self.add(self.small)
        order = self.placed(cp_id_send=coupon.cp_id)
        self.assertEqual(order.od_send_coupon, 1500)
        self.assertEqual(self.payable(order), 10000 + 3000 - 1500)

    def test_shipping_coupon_gives_nothing_when_shipping_is_free(self):
        coupon = self.coupon(cp_method=3, cp_price=2000)
        self.add(self.big)
        order = self.placed(cp_id_send=coupon.cp_id)
        self.assertEqual((order.od_send_cost, order.od_send_coupon), (0, 0))
        self.assertEqual(self.used(coupon), "")

    def test_an_order_coupon_id_sent_as_the_shipping_coupon_is_ignored(self):
        coupon = self.coupon(cp_method=2, cp_price=2000)
        self.add(self.small)
        order = self.placed(cp_id_send=coupon.cp_id)
        self.assertEqual((order.od_send_coupon, order.od_coupon), (0, 0))

    def test_an_expired_shipping_coupon_is_ignored(self):
        coupon = self.coupon(cp_method=3, cp_price=2000, cp_end=today() - timedelta(days=1))
        self.add(self.small)
        self.assertEqual(self.placed(cp_id_send=coupon.cp_id).od_send_coupon, 0)

    def test_order_and_shipping_coupons_can_be_used_together_and_both_come_back_on_cancel(self):
        order_coupon = self.coupon(cp_price=2000)
        shipping_coupon = self.coupon(cp_method=3, cp_price=3000)
        self.add(self.small)
        order = self.placed(cp_id=order_coupon.cp_id, cp_id_send=shipping_coupon.cp_id)
        self.assertEqual((order.od_coupon, order.od_send_coupon), (2000, 3000))
        self.assertEqual(self.payable(order), 10000 + 3000 - 2000 - 3000)
        self.client.post(f"{API}/payment/cancel", {"order_id": order.od_id}, format="json")
        self.assertEqual((self.used(order_coupon), self.used(shipping_coupon)), ("", ""))

    def test_a_shipping_coupon_used_once_cannot_discount_a_second_order(self):
        coupon = self.coupon(cp_method=3, cp_price=3000)
        self.add(self.small)
        first = self.placed(cp_id_send=coupon.cp_id)
        self.add(self.small)
        second = self.placed(cp_id_send=coupon.cp_id)
        self.assertEqual((first.od_send_coupon, second.od_send_coupon), (3000, 0))

    # Defect (v1_shop.py create_order_from_request, coupon_discount(coupon, shipping_total)): the
    # coupon minimum is compared with the shipping fee instead of the order amount, so a shipping
    # coupon "for orders of 5000 or more" never works. YoungCart ordersendcostcoupon.php and
    # orderformupdate.php compare cp_minimum with the order amount.
    def test_shipping_coupon_minimum_is_checked_against_the_order_amount(self):
        coupon = self.coupon(cp_method=3, cp_price=3000, cp_minimum=8000)
        self.add(self.small)
        order = self.placed(cp_id_send=coupon.cp_id)
        self.assertEqual(order.od_send_coupon, 3000)

    def test_shipping_coupon_is_refused_when_the_order_amount_is_below_its_minimum(self):
        coupon = self.coupon(cp_method=3, cp_price=3000, cp_minimum=20000)
        self.add(self.small)
        order = self.placed(cp_id_send=coupon.cp_id)
        self.assertEqual(order.od_send_coupon, 0)

    # Defect (same place): the shipping coupon is applied to base shipping plus the extra
    # remote-area fee (send_cost + send_cost2). YoungCart discounts only the base shipping
    # ($send_cost) and caps the coupon there; the extra fee is always paid.
    def test_shipping_coupon_does_not_cover_the_remote_area_fee(self):
        ShopShippingCost.objects.create(sc_id=1, sc_zip1="06000", sc_zip2="06999", sc_price=2000)
        coupon = self.coupon(cp_method=3, cp_price=5000)
        self.add(self.small)
        order = self.placed(cp_id_send=coupon.cp_id)
        self.assertEqual((order.od_send_cost, order.od_send_cost2), (3000, 2000))
        self.assertEqual(order.od_send_coupon, 3000)
        self.assertEqual(self.payable(order), 10000 + 3000 + 2000 - 3000)


class AllMemberCouponTests(CouponTestBase):
    """YoungCart '전체회원' coupons: one row, usable once by each member (is_used_coupon per member)."""

    def shared(self, **extra):
        return self.coupon(user=None, cp_all_members=True, cp_subject="For everyone", **extra)

    def other_client(self):
        client = APIClient()
        client.force_authenticate(user=self.other)
        return client

    def test_every_member_sees_it_as_usable(self):
        coupon = self.shared()

        self.assertIn(coupon.cp_id, {c.cp_id for c in valid_coupons_queryset(self.member)})
        self.assertIn(coupon.cp_id, {c.cp_id for c in valid_coupons_queryset(self.other)})

    def test_a_coupon_of_a_member_who_no_longer_exists_is_not_shared(self):
        orphan = self.coupon(user=None)

        self.assertNotIn(orphan.cp_id, {c.cp_id for c in valid_coupons_queryset(self.member)})

    def test_one_member_using_it_leaves_it_open_for_the_others(self):
        coupon = self.shared()
        self.add(self.big)

        order = self.placed(cp_id=coupon.cp_id)

        self.assertEqual(order.od_coupon, 7000)
        self.assertEqual(self.used(coupon), "")
        self.assertNotIn(coupon.cp_id, {c.cp_id for c in valid_coupons_queryset(self.member)})
        self.assertIn(coupon.cp_id, {c.cp_id for c in valid_coupons_queryset(self.other)})

    def test_the_same_member_cannot_use_it_twice(self):
        coupon = self.shared()
        self.add(self.big)
        self.placed(cp_id=coupon.cp_id)
        self.add(self.big)

        second = self.placed(cp_id=coupon.cp_id)

        self.assertEqual(second.od_coupon, 0)

    def test_the_coupon_list_shows_it_used_only_for_the_member_who_used_it(self):
        coupon = self.shared()
        self.add(self.big)
        self.placed(cp_id=coupon.cp_id)

        mine = {row["cp_id"]: row for row in self.client.get(f"{API}/coupons").json()["data"]}
        theirs = {row["cp_id"]: row for row in self.other_client().get(f"{API}/coupons").json()["data"]}

        self.assertEqual(mine[coupon.cp_id]["cp_used"], "1")
        self.assertEqual(theirs[coupon.cp_id]["cp_used"], "")
        self.assertTrue(theirs[coupon.cp_id]["cp_all_members"])

    def test_cancelling_gives_it_back_to_the_member(self):
        coupon = self.shared()
        self.add(self.big)
        order = self.placed(cp_id=coupon.cp_id)

        self.client.post(f"{API}/payment/cancel", {"order_id": order.od_id}, format="json")

        self.assertIn(coupon.cp_id, {c.cp_id for c in valid_coupons_queryset(self.member)})
