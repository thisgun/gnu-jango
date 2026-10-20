"""youngcart 신규회원 쿠폰: signing up gives the member an order coupon when the shop offers one,
and a coupon that cannot be issued never stops the signup."""

from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.config.models import Config
from gnu_jango.shop.models import ShopCoupon

REGISTER_URL = "/api/v1/auth/register"


def set_config(name, value):
    Config.objects.update_or_create(name=name, defaults={"value": str(value)})


class SignupCouponTests(TestCase):
    def offer_coupon(self, *, use="1", price="5000", minimum="30000", term="10"):
        set_config("de_member_reg_coupon_use", use)
        set_config("de_member_reg_coupon_price", price)
        set_config("de_member_reg_coupon_minimum", minimum)
        set_config("de_member_reg_coupon_term", term)

    def register(self, mb_id="cp_newbie"):
        client = APIClient()
        with mock.patch("gnu_jango.api.v1_auth._captcha_matches", return_value=True):
            response = client.post(
                REGISTER_URL,
                {
                    "mb_id": mb_id, "mb_password": "Str0ng-pass-99", "mb_password_re": "Str0ng-pass-99",
                    "mb_email": f"{mb_id}@example.test", "mb_name": "New", "mb_nick": f"nick-{mb_id}",
                },
                format="json",
            )
        self.assertIn(response.status_code, (200, 201), response.content[:300])
        return get_user_model().objects.get(username=mb_id)

    def test_signup_issues_the_new_member_coupon(self):
        self.offer_coupon()
        user = self.register()
        coupon = ShopCoupon.objects.get(user=user)
        today = timezone.localdate()
        self.assertEqual(coupon.cp_subject, "신규 회원가입 축하 쿠폰")
        self.assertEqual(
            (coupon.cp_method, coupon.cp_target, coupon.cp_type, coupon.cp_price, coupon.cp_trunc),
            (2, "", 0, 5000, 1),
        )
        self.assertEqual((coupon.cp_minimum, coupon.cp_maximum), (30000, 0))
        self.assertEqual((coupon.cp_start, coupon.cp_end), (today, today + timedelta(days=9)))
        self.assertEqual(coupon.cp_used, "")

        client = APIClient()
        client.force_authenticate(user=user)
        listed = client.get("/api/v1/shop/coupons/mine").json()["data"]
        self.assertIn(coupon.cp_id, [row["cp_id"] for row in listed])

    def test_no_coupon_when_the_shop_does_not_offer_one(self):
        self.offer_coupon(use="0")
        self.assertFalse(ShopCoupon.objects.filter(user=self.register("cp_off")).exists())

    def test_no_coupon_without_a_price_or_a_term(self):
        self.offer_coupon(price="0")
        self.assertFalse(ShopCoupon.objects.filter(user=self.register("cp_noprice")).exists())
        self.offer_coupon(term="0")
        self.assertFalse(ShopCoupon.objects.filter(user=self.register("cp_noterm")).exists())

    def test_a_coupon_failure_does_not_block_signup(self):
        self.offer_coupon()
        with mock.patch("gnu_jango.shop.signup_coupon.ShopCoupon.objects.create", side_effect=RuntimeError("boom")):
            with self.assertLogs("gnu_jango.shop.signup_coupon", "ERROR"):
                user = self.register("cp_fail")
        self.assertTrue(user.is_active)
        self.assertFalse(ShopCoupon.objects.filter(user=user).exists())
