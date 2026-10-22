"""The coupon admin form after youngcart couponform.php: labelled kinds, the target picker per kind,
전체회원 issuance and its use once per member on the storefront."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gnu_jango.api.shop_coupons import valid_coupons_queryset
from gnu_jango.shop.models import ShopCategory, ShopCoupon, ShopCouponLog, ShopProduct


class CouponAdminTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="coupon-admin", password="password")
        self.member = User.objects.create_user(username="member-a", password="pw")
        self.other = User.objects.create_user(username="member-b", password="pw")
        self.product = ShopProduct.objects.create(it_id="CP-SHIRT", it_name="쿠폰 셔츠", it_price=10000)
        self.category = ShopCategory.objects.create(ca_id="10", ca_name="의류")
        self.client.force_login(self.admin)
        self.add_url = reverse("admin:shop_shopcoupon_add")
        today = timezone.localdate()
        self.dates = {"cp_start": today.isoformat(), "cp_end": (today + timedelta(days=30)).isoformat()}

    def post_coupon(self, **values):
        data = {
            "cp_id": values.pop("cp_id", "ADMINCOUPON01"),
            "cp_subject": "가을 할인",
            "cp_used": "",
            "cp_method": "2",
            "cp_type": "0",
            "cp_price": "3000",
            "cp_minimum": "0",
            "cp_maximum": "0",
            "cp_trunc": "1",
            "created_at_0": timezone.localdate().isoformat(),
            "created_at_1": "10:00:00",
            **self.dates,
            **values,
        }
        return self.client.post(self.add_url, data)

    def test_add_form_has_labelled_kinds_target_pickers_and_all_members(self):
        page = self.client.get(self.add_url).content.decode()
        for text in ("개별상품할인", "카테고리할인", "주문금액할인", "배송비할인", "정률할인(%)", "1,000원단위", "전체회원"):
            self.assertIn(text, page)
        self.assertIn(reverse("admin:shop_shopcoupon_target_products"), page)
        self.assertIn(reverse("admin:shop_shopcoupon_target_categories"), page)
        self.assertIn('x-show="cp_method == ', page)
        self.assertNotIn('name="cp_target"', page)

    def test_all_member_coupon_is_issued_without_a_member(self):
        response = self.post_coupon(cp_all_members="on", user=str(self.member.pk))
        self.assertEqual(response.status_code, 302, response.content.decode()[:2000])
        coupon = ShopCoupon.objects.get(pk="ADMINCOUPON01")
        self.assertTrue(coupon.cp_all_members)
        self.assertIsNone(coupon.user)
        self.assertEqual((coupon.cp_method, coupon.cp_target), (2, ""))

    def test_product_and_category_targets_come_from_the_picker(self):
        response = self.post_coupon(cp_method="0", target_product=self.product.pk, user=str(self.member.pk))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ShopCoupon.objects.get(pk="ADMINCOUPON01").cp_target, "CP-SHIRT")

        response = self.post_coupon(
            cp_id="ADMINCOUPON02", cp_method="1", target_category=self.category.pk,
            target_product=self.product.pk, user=str(self.member.pk),
        )
        self.assertEqual(response.status_code, 302)
        coupon = ShopCoupon.objects.get(pk="ADMINCOUPON02")
        self.assertEqual((coupon.cp_method, coupon.cp_target), (1, "10"))

    def test_youngcart_validation_messages(self):
        cases = (
            ({}, "회원을 선택하거나 전체회원을 켜 주십시오."),
            ({"cp_method": "0", "cp_all_members": "on"}, "적용상품을 선택해 주십시오."),
            ({"cp_method": "1", "cp_all_members": "on"}, "적용분류를 선택해 주십시오."),
            ({"cp_type": "1", "cp_price": "120", "cp_all_members": "on"}, "할인비율을 1과 99사이 값으로 입력해 주십시오."),
            ({"cp_price": "0", "cp_all_members": "on"}, "할인금액을 입력해 주십시오."),
            ({"cp_end": (timezone.localdate() - timedelta(days=1)).isoformat(), "cp_start": (timezone.localdate() - timedelta(days=5)).isoformat(), "cp_all_members": "on"}, "이후로 입력해 주십시오."),
        )
        for values, message in cases:
            with self.subTest(message=message):
                response = self.post_coupon(**values)
                self.assertEqual(response.status_code, 200)
                self.assertIn(message, response.content.decode())
        self.assertFalse(ShopCoupon.objects.exists())

    def test_change_form_shows_the_saved_target_without_listing_the_catalog(self):
        for index in range(5):
            ShopProduct.objects.create(it_id=f"OTHER{index}", it_name=f"다른 상품 {index}")
        coupon = ShopCoupon.objects.create(
            cp_id="EXISTING01", user=self.member, cp_subject="상품 쿠폰", cp_method=0, cp_target="CP-SHIRT",
            cp_price=1000, cp_end=timezone.localdate() + timedelta(days=3),
        )
        page = self.client.get(reverse("admin:shop_shopcoupon_change", args=[coupon.pk])).content.decode()
        self.assertIn("CP-SHIRT: 쿠폰 셔츠", page)
        self.assertNotIn("OTHER1", page)
        self.assertNotIn('name="cp_id"', page)  # the primary key is read-only once saved

        response = self.client.get(reverse("admin:shop_shopcoupon_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("개별상품할인", response.content.decode())

    def test_target_search_returns_matching_products_and_categories(self):
        products = self.client.get(reverse("admin:shop_shopcoupon_target_products"), {"term": "셔츠"}).json()
        self.assertEqual(products["results"], [{"id": "CP-SHIRT", "text": "CP-SHIRT: 쿠폰 셔츠"}])
        categories = self.client.get(reverse("admin:shop_shopcoupon_target_categories"), {"term": "의류"}).json()
        self.assertEqual(categories["results"], [{"id": "10", "text": "10: 의류"}])

    def test_target_search_is_closed_to_visitors_and_staff_without_coupon_rights(self):
        url = reverse("admin:shop_shopcoupon_target_products")
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)
        staff = get_user_model().objects.create_user(username="plain-staff", password="pw", is_staff=True)
        self.client.force_login(staff)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_issued_all_member_coupon_is_usable_once_per_member_on_the_storefront(self):
        self.assertEqual(self.post_coupon(cp_all_members="on").status_code, 302)
        coupon = ShopCoupon.objects.get(pk="ADMINCOUPON01")
        self.assertIn(coupon.pk, {c.pk for c in valid_coupons_queryset(self.member)})
        self.assertIn(coupon.pk, {c.pk for c in valid_coupons_queryset(self.other)})

        ShopCouponLog.objects.create(
            cl_id=1, coupon=coupon, cp_id=coupon.pk, user=self.member, mb_id=self.member.username,
            od_id="ORDER1", cp_price=3000,
        )
        self.assertNotIn(coupon.pk, {c.pk for c in valid_coupons_queryset(self.member)})
        self.assertIn(coupon.pk, {c.pk for c in valid_coupons_queryset(self.other)})
        coupon.refresh_from_db()
        self.assertEqual(coupon.cp_used, "")
