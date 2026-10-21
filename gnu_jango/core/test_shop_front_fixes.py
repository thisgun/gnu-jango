"""Customer-facing YoungCart parity fixes: product search columns, coupon periods, courier
tracking links, 상품정보제공고시, the member contact the order form prefills, local-time order
numbers and the review write rule."""

import importlib
from datetime import date, datetime, timezone as dt_timezone
from unittest import mock

from django import forms
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.api.shop_common import generate_numeric_order_id
from gnu_jango.api.shop_search import literal_product_search_q, selected_product_search_fields
from gnu_jango.shop.admin.catalog import ShopProductAdminForm
from gnu_jango.shop.admin.item_info_form import ItemInfoTextField, clean_item_info
from gnu_jango.shop.admin_settings import ShopSettingsForm
from gnu_jango.shop.coupon_dates import coupon_end_date
from gnu_jango.shop.delivery import delivery_company_choices, delivery_inquiry
from gnu_jango.shop.item_info import (
    item_info_from_text,
    item_info_rows,
    item_info_to_text,
    parse_item_info_value,
    parse_php_array,
)
from gnu_jango.shop.models import (
    ShopCoupon,
    ShopCouponZone,
    ShopOrder,
    ShopOrderItem,
    ShopProduct,
    ShopShippingPolicy,
)
from gnu_jango.users.models import Profile

API = "/api/v1"
WEAR_NOTICE = 'a:3:{s:8:"material";s:8:"면 100%";s:5:"color";s:6:"검정";s:4:"size";s:1:"M";}'


def php_serialize(pairs):
    body = "".join(
        f's:{len(key.encode())}:"{key}";s:{len(value.encode())}:"{value}";' for key, value in pairs
    )
    return f"a:{len(pairs)}:{{{body}}}"


class ProductSearchColumnsTests(TestCase):
    """shop/search.php: qname / qexplan / qid / qbasic pick the columns, none picked means all,
    and every word has to match."""

    @classmethod
    def setUpTestData(cls):
        cls.by_name = ShopProduct.objects.create(it_id="S-NAME", it_name="Linen shirt", it_use="1")
        cls.by_explan = ShopProduct.objects.create(
            it_id="S-EXPL", it_name="Plain", it_explan="<p>Soft <b>linen</b> weave</p>", it_use="1"
        )
        cls.by_basic = ShopProduct.objects.create(it_id="S-BASE", it_name="Basic", it_basic="linen blend", it_use="1")
        cls.by_code = ShopProduct.objects.create(it_id="LINEN-01", it_name="Code only", it_use="1")
        cls.other = ShopProduct.objects.create(it_id="S-OTHER", it_name="Wool coat", it_use="1")

    def ids(self, **params):
        response = APIClient().get(f"{API}/shop/products", params)
        self.assertEqual(response.status_code, 200, response.content[:500])
        return {row["it_id"] for row in response.json()["data"]}

    def test_no_selector_searches_name_description_code_and_summary(self):
        self.assertEqual(self.ids(q="linen"), {"S-NAME", "S-EXPL", "S-BASE", "LINEN-01"})

    def test_each_selector_limits_the_columns(self):
        self.assertEqual(self.ids(q="linen", qname="1"), {"S-NAME"})
        self.assertEqual(self.ids(q="linen", qexplan="1"), {"S-EXPL"})
        self.assertEqual(self.ids(q="linen", qid="1"), {"LINEN-01"})
        self.assertEqual(self.ids(q="linen", qbasic="1"), {"S-BASE"})
        self.assertEqual(self.ids(q="linen", qname="1", qbasic="1"), {"S-NAME", "S-BASE"})

    def test_every_word_must_match(self):
        self.assertEqual(self.ids(q="linen shirt"), {"S-NAME"})
        self.assertEqual(self.ids(q="linen coat"), set())

    def test_selector_helpers(self):
        self.assertEqual(selected_product_search_fields({}), ["it_name", "it_explan", "it_id", "it_basic"])
        self.assertEqual(selected_product_search_fields({"qid": "1", "qname": "0"}), ["it_id"])
        self.assertEqual(str(literal_product_search_q("", ["it_name"])), "(AND: )")


class CouponPeriodTests(TestCase):
    def test_end_date_is_clamped_instead_of_overflowing(self):
        today = date(2026, 10, 21)
        self.assertEqual(coupon_end_date(today, 30), date(2026, 11, 19))
        self.assertEqual(coupon_end_date(today, 1), today)
        self.assertEqual(coupon_end_date(today, 0), today)
        self.assertEqual(coupon_end_date(today, 2147483647), date.max)
        self.assertEqual(coupon_end_date(date.max, 5), date.max)

    def test_couponzone_download_with_an_imported_huge_period(self):
        user = get_user_model().objects.create(username="zone-member")
        Profile.objects.update_or_create(user=user, defaults={"user_point": 5000})
        zone = ShopCouponZone.objects.create(
            cz_type=1, cz_point=1000, cz_subject="Point coupon", cz_period=2147483647, cp_price=1000
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        response = client.post(f"{API}/shop/coupons/download", {"cz_id": zone.pk}, format="json")
        self.assertEqual(response.status_code, 201, response.content[:500])
        coupon = ShopCoupon.objects.get(user=user, coupon_zone=zone)
        self.assertEqual(coupon.cp_end, date.max)
        self.assertEqual(response.json()["data"]["cp_end"], "9999-12-31")
        listing = client.get(f"{API}/shop/coupons/zone")
        self.assertEqual(listing.status_code, 200, listing.content[:300])


class DeliveryInquiryTests(TestCase):
    def test_links_follow_the_courier(self):
        self.assertEqual(
            delivery_inquiry("로젠택배", "123 45"),
            {"url": "https://www.ilogen.com/m/personal/trace.pop/123%2045", "tel": "1588-9988"},
        )
        self.assertEqual(delivery_inquiry("CJ대한통운", "555")["url"], "https://trace.cjlogistics.com/next/tracking.html?wblNo=555")
        # get_delivery_inquiry matches a part of the name too
        self.assertEqual(delivery_inquiry("한진", "9")["tel"], "1588-0011")

    def test_unknown_or_self_delivery_or_no_invoice_has_no_link(self):
        for company, invoice in (("자체배송", "1"), ("동네택배", "1"), ("로젠택배", ""), ("", "1")):
            self.assertEqual(delivery_inquiry(company, invoice), {"url": "", "tel": ""})

    def test_choices_keep_an_unlisted_value(self):
        values = [value for value, _ in delivery_company_choices("동네택배")]
        self.assertEqual(values[:3], ["", "자체배송", "경동택배"])
        self.assertEqual(values[-1], "동네택배")
        self.assertEqual(values.count("CJ대한통운"), 1)

    def test_order_detail_uses_the_order_courier(self):
        user = get_user_model().objects.create(username="tracker")
        order = ShopOrder.objects.create(
            od_id="TRACK1", user=user, od_name="b", od_status="배송",
            od_delivery_company="롯데택배", od_invoice="777",
        )
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        data = client.get(f"{API}/shop/orders/{order.od_id}").json()["data"]
        self.assertEqual(data["delivery_inquiry_url"], "https://www.lotteglogis.com/open/tracking?invno=777")
        self.assertEqual(data["delivery_inquiry_tel"], "1588-2121")
        ShopOrder.objects.filter(pk=order.pk).update(od_delivery_company="자체배송")
        data = client.get(f"{API}/shop/orders/{order.od_id}").json()["data"]
        self.assertEqual((data["delivery_inquiry_url"], data["delivery_inquiry_tel"]), ("", ""))
        self.assertEqual((data["od_delivery_company"], data["od_invoice"]), ("자체배송", "777"))

    def test_admin_forms_offer_the_courier_list(self):
        policy = ShopShippingPolicy.objects.create(de_delivery_company="옛택배")
        field = ShopSettingsForm(instance=policy).fields["de_delivery_company"]
        values = [value for value, _ in field.choices]
        self.assertIn("우체국", values)
        self.assertIn("옛택배", values)


class PhpSerializedParserTests(SimpleTestCase):
    def test_reads_utf8_byte_lengths(self):
        pairs, complete = parse_php_array(WEAR_NOTICE)
        self.assertTrue(complete)
        self.assertEqual(pairs, [("material", "면 100%"), ("color", "검정"), ("size", "M")])

    def test_scalars_and_integer_keys(self):
        pairs, complete = parse_php_array('a:4:{i:0;i:5;s:1:"b";b:1;s:1:"d";d:1.5;s:1:"n";N;}')
        self.assertTrue(complete)
        self.assertEqual(pairs, [("0", 5), ("b", True), ("d", 1.5), ("n", None)])

    def test_truncated_value_keeps_the_complete_rows(self):
        pairs, complete = parse_php_array(WEAR_NOTICE[:60])
        self.assertFalse(complete)
        self.assertEqual(pairs, [("material", "면 100%"), ("color", "검정")])

    def test_objects_and_garbage_are_refused(self):
        self.assertEqual(parse_php_array('O:8:"stdClass":0:{}'), (None, False))
        self.assertEqual(parse_php_array('a:1:{s:1:"x";O:8:"stdClass":0:{}}'), ([], False))
        self.assertEqual(parse_php_array('a:1:{s:99:"x";s:1:"y";}'), ([], False))
        self.assertIsNone(parse_item_info_value("plain text"))

    def test_slashed_values_are_read_like_stripslashes(self):
        slashed = php_serialize([("material", 'say "hi"')]).replace('"hi"', '\\"hi\\"')
        self.assertEqual(parse_item_info_value(slashed, "wear")[0]["value"], 'say "hi"')

    def test_rows_get_the_article_titles_of_the_kind(self):
        rows = parse_item_info_value(WEAR_NOTICE, "wear")
        self.assertEqual([row["title"] for row in rows], ["제품소재", "색상", "치수"])
        self.assertEqual(parse_item_info_value(WEAR_NOTICE, "unknown")[0]["title"], "material")

    def test_json_copies(self):
        self.assertEqual(
            parse_item_info_value('{"gubun":"wear","key":"material","value":"x"}'),
            [{"key": "material", "title": "제품소재", "value": "x"}],
        )
        self.assertEqual(parse_item_info_value('{"color":"red"}', "wear"), [{"key": "color", "title": "색상", "value": "red"}])
        self.assertEqual(parse_item_info_value("[]"), [])


class ItemInfoPayloadTests(TestCase):
    def test_every_row_is_returned_with_title_value_and_hint(self):
        rows = parse_item_info_value(php_serialize([(f"k{i}", f"v{i}") for i in range(3)]), "")
        rows += parse_item_info_value(WEAR_NOTICE, "wear")
        ShopProduct.objects.create(it_id="INFO-1", it_name="Shirt", it_use="1", it_info_gubun="wear", it_info_value=rows)
        data = APIClient().get(f"{API}/shop/products/INFO-1").json()["data"]
        self.assertEqual(data["it_info_title"], "상품 정보 고시")
        self.assertEqual(data["it_info_gubun_title"], "의류")
        self.assertEqual(len(data["it_info_items"]), 6)
        material = data["it_info_items"][3]
        self.assertEqual((material["key"], material["title"], material["value"]), ("material", "제품소재", "면 100%"))
        self.assertIn("혼용률", material["example"])

    def test_item_info_rows_falls_back_to_the_key(self):
        product = ShopProduct(it_info_gubun="", it_info_value=[{"key": "origin", "value": "KR"}])
        self.assertEqual(item_info_rows(product), [{"key": "origin", "title": "origin", "value": "KR", "example": ""}])


class ItemInfoMigrationTests(TestCase):
    def test_existing_text_moves_into_rows(self):
        migration = importlib.import_module("gnu_jango.shop.migrations.0031_shopproduct_it_info_value")
        ShopProduct.objects.create(it_id="M-1", it_name="a", it_info_gubun="wear", it_info_title=WEAR_NOTICE)
        ShopProduct.objects.create(it_id="M-2", it_name="b", it_info_gubun="wear", it_info_title=WEAR_NOTICE[:60])
        ShopProduct.objects.create(it_id="M-3", it_name="c", it_info_title="plain notice text")
        ShopProduct.objects.create(it_id="M-4", it_name="d", it_info_title='a:1:{s:9')
        from django.apps import apps

        migration.move_info_rows(apps, None)
        rows = {p.it_id: (p.it_info_title, p.it_info_value) for p in ShopProduct.objects.filter(it_id__startswith="M-")}
        self.assertEqual(rows["M-1"][0], "")
        self.assertEqual([row["value"] for row in rows["M-1"][1]], ["면 100%", "검정", "M"])
        self.assertEqual(len(rows["M-2"][1]), 2)
        self.assertEqual(rows["M-3"], ("plain notice text", []))
        self.assertEqual(rows["M-4"], ("", []))

    def test_importer_parses_the_serialized_value(self):
        from gnu_jango.core.management.commands.migrate_gnuboard5 import Command

        fields = Command().product_info_fields({"it_info_gubun": "wear", "it_info_value": WEAR_NOTICE})
        self.assertEqual(fields["it_info_title"], "")
        self.assertEqual(fields["it_info_value"][0], {"key": "material", "title": "제품소재", "value": "면 100%"})
        fields = Command().product_info_fields({"it_info_gubun": "", "it_info_value": "free text"})
        self.assertEqual(fields, {"it_info_title": "free text", "it_info_value": []})


class ItemInfoAdminTests(TestCase):
    class Form(forms.Form):
        it_info_gubun = forms.CharField(required=False)
        it_info_value = ItemInfoTextField()

        def clean(self):
            return clean_item_info(self, super().clean())

    def test_text_round_trip_keeps_article_keys(self):
        rows = item_info_from_text("제품소재: 면 100%\n\n세탁: 손세탁: 찬물", "wear")
        self.assertEqual(rows, [
            {"key": "material", "title": "제품소재", "value": "면 100%"},
            {"key": "세탁", "title": "세탁", "value": "손세탁: 찬물"},
        ])
        self.assertEqual(item_info_to_text(rows), "제품소재: 면 100%\n세탁: 손세탁: 찬물")

    def test_form_validates_each_line(self):
        form = self.Form(data={"it_info_gubun": "wear", "it_info_value": "색상: 검정"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["it_info_value"], [{"key": "color", "title": "색상", "value": "검정"}])
        form = self.Form(data={"it_info_gubun": "wear", "it_info_value": "색상: 검정\n콜론 없음"})
        self.assertFalse(form.is_valid())
        self.assertIn("2번째 줄", str(form.errors["it_info_value"]))

    def test_product_form_shows_rows_as_text_and_offers_the_kinds(self):
        product = ShopProduct.objects.create(
            it_id="ADM-1", it_name="a", it_info_gubun="wear",
            it_info_value=[{"key": "material", "title": "제품소재", "value": "면"}],
        )
        form = ShopProductAdminForm(instance=product)
        self.assertEqual(form["it_info_value"].value(), "제품소재: 면")
        self.assertFalse(form.fields["it_info_value"].has_changed(product.it_info_value, "제품소재: 면\n"))
        self.assertIn(("wear", "의류"), form.fields["it_info_gubun"].choices)


class MemberContactTests(TestCase):
    def test_auth_me_returns_the_members_own_phone_and_address(self):
        user = get_user_model().objects.create(username="orderer")
        Profile.objects.update_or_create(user=user, defaults={
            "user_hp": "010-1234-5678", "user_zip": "06236", "user_addr1": "서울 강남구",
            "user_addr2": "101호", "user_addr_jibeon": "R",
        })
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        member = client.get(f"{API}/auth/me").json()["data"]["member"]
        self.assertEqual(
            {key: member[key] for key in ("mb_hp", "mb_tel", "mb_zip1", "mb_zip2", "mb_addr1", "mb_addr2", "mb_addr3", "mb_addr_jibeon")},
            {"mb_hp": "010-1234-5678", "mb_tel": "", "mb_zip1": "062", "mb_zip2": "36", "mb_addr1": "서울 강남구",
             "mb_addr2": "101호", "mb_addr3": "", "mb_addr_jibeon": "R"},
        )

    def test_anonymous_gets_nothing(self):
        self.assertEqual(APIClient().get(f"{API}/auth/me").status_code, 401)


class OrderNumberTests(SimpleTestCase):
    def test_order_number_uses_shop_local_time(self):
        utc = datetime(2026, 10, 20, 16, 30, 5, tzinfo=dt_timezone.utc)
        with mock.patch("django.utils.timezone.now", return_value=utc):
            od_id = generate_numeric_order_id()
        self.assertEqual(od_id[:14], "20261021013005")
        self.assertEqual(len(od_id), 20)


class ReviewWriteRuleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ShopProduct.objects.create(it_id="RV-1", it_name="Reviewed", it_use="1")
        cls.user = get_user_model().objects.create(username="reviewer")
        ShopShippingPolicy.objects.update_or_create(pk=1, defaults={"de_item_use_write": 1})

    def post(self, user):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
        return client.post(f"{API}/shop/reviews", {"it_id": "RV-1", "is_subject": "s", "is_content": "c"}, format="json")

    def line(self, status):
        order = ShopOrder.objects.create(od_id=f"RV-{status}", user=self.user, od_name="b", od_status=status)
        ShopOrderItem.objects.create(
            order=order, product=self.product, ct_id=f"ct-{status}", it_id="RV-1", it_name="Reviewed",
            ct_price=1000, ct_qty=1, ct_status=status,
        )

    def test_only_a_completed_line_allows_a_review(self):
        self.line("배송")
        refused = self.post(self.user)
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.json()["message"], "사용후기는 주문이 완료된 경우에만 작성하실 수 있습니다.")
        self.line("완료")
        self.assertEqual(self.post(self.user).status_code, 201)

    def test_super_admin_is_exempt(self):
        admin = get_user_model().objects.create(username="root", is_superuser=True, is_staff=True)
        self.assertEqual(self.post(admin).status_code, 201)

    def test_without_the_rule_any_member_may_review(self):
        ShopShippingPolicy.objects.filter(pk=1).update(de_item_use_write=0)
        self.assertEqual(self.post(self.user).status_code, 201)


class OrderDateTests(SimpleTestCase):
    def test_order_datetime_is_local_iso(self):
        from gnu_jango.api.shop_common import datetime_value

        value = datetime_value(timezone.make_aware(datetime(2026, 10, 20, 9, 5), timezone.get_current_timezone()))
        self.assertTrue(value.startswith("2026-10-20T09:05:00"))
        self.assertEqual(datetime_value(None), "")
