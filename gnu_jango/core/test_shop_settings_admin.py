"""Regression coverage for the unified shop settings page and PG status checks."""

import io
from unittest.mock import patch
from urllib import error as urllib_error

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from gnu_jango.api.shop_payments import check_toss_connection, toss_payment_config
from gnu_jango.config.models import Config
from gnu_jango.shop.admin_settings import ShopSettingsForm
from gnu_jango.shop.models import ShopShippingPolicy
from gnu_jango.shop.settings_sync import sync_shop_phone_from_config, sync_shop_phone_from_policy


class TossKeyStatusTests(TestCase):
    @override_settings(SHOP_TOSS_CLIENT_KEY="", SHOP_TOSS_SECRET_KEY="")
    def test_missing_keys_are_not_enabled(self):
        config = toss_payment_config()
        self.assertEqual(config["key_status"], "missing")
        self.assertFalse(config["enabled"])

    @override_settings(SHOP_TOSS_CLIENT_KEY="test_ck_client", SHOP_TOSS_SECRET_KEY="")
    def test_incomplete_key_pair_is_not_enabled(self):
        config = toss_payment_config()
        self.assertEqual(config["key_status"], "incomplete")
        self.assertFalse(config["enabled"])

    @override_settings(SHOP_TOSS_CLIENT_KEY="test_ck_client", SHOP_TOSS_SECRET_KEY="live_sk_secret")
    def test_mixed_test_and_live_keys_are_rejected(self):
        config = toss_payment_config()
        self.assertEqual(config["key_status"], "mode_mismatch")
        self.assertFalse(config["enabled"])
        self.assertFalse(config["is_test_mode"])

    @override_settings(SHOP_TOSS_CLIENT_KEY="test_ck_client", SHOP_TOSS_SECRET_KEY="test_sk_secret")
    def test_matching_test_keys_are_enabled_as_test_mode(self):
        config = toss_payment_config()
        self.assertEqual(config["key_status"], "test")
        self.assertTrue(config["enabled"])
        self.assertTrue(config["is_test_mode"])

    @override_settings(SHOP_TOSS_CLIENT_KEY="client", SHOP_TOSS_SECRET_KEY="secret")
    def test_unrecognized_key_prefix_is_rejected(self):
        config = toss_payment_config()
        self.assertEqual(config["key_status"], "invalid_prefix")
        self.assertFalse(config["enabled"])


class TossReadOnlyConnectionTests(TestCase):
    @override_settings(SHOP_TOSS_CLIENT_KEY="", SHOP_TOSS_SECRET_KEY="")
    def test_missing_keys_do_not_make_a_network_request(self):
        with patch("gnu_jango.api.shop_payments.urllib_request.urlopen") as urlopen:
            result = check_toss_connection()
        self.assertEqual(result, {"status": "missing", "connected": False})
        urlopen.assert_not_called()

    @override_settings(SHOP_TOSS_CLIENT_KEY="test_ck_fake", SHOP_TOSS_SECRET_KEY="test_sk_fake")
    def test_not_found_order_response_confirms_auth_without_charging(self):
        error = urllib_error.HTTPError(
            "https://api.tosspayments.com", 404, "Not Found", {}, io.BytesIO(b'{"code":"NOT_FOUND_PAYMENT"}')
        )
        with patch("gnu_jango.api.shop_payments.urllib_request.urlopen", side_effect=error) as urlopen:
            result = check_toss_connection()

        request = urlopen.call_args.args[0]
        self.assertEqual(result, {"status": "connected", "connected": True})
        self.assertEqual(request.get_method(), "GET")
        self.assertIsNone(request.data)
        self.assertIn("/v1/payments/orders/codex-health-", request.full_url)

    @override_settings(SHOP_TOSS_CLIENT_KEY="test_ck_fake", SHOP_TOSS_SECRET_KEY="test_sk_fake")
    def test_invalid_api_key_is_reported_without_echoing_provider_body(self):
        error = urllib_error.HTTPError(
            "https://api.tosspayments.com", 401, "Unauthorized", {}, io.BytesIO(b'{"code":"UNAUTHORIZED_KEY"}')
        )
        with patch("gnu_jango.api.shop_payments.urllib_request.urlopen", side_effect=error):
            result = check_toss_connection()
        self.assertEqual(result, {"status": "invalid_credentials", "connected": False})


class ShopSettingsAdminTests(TestCase):
    minimal_form = {
        "de_admin_company_name": "Demo Shop",
        "de_admin_company_tel": "",
        "de_delivery_company": "Courier",
        "de_send_cost_case": "",
        "de_send_cost_limit": "",
        "de_send_cost_list": "",
        "de_baesong_content": "",
        "de_change_content": "",
        "de_item_use_write": "0",
        "de_item_use_use": "0",
        "de_settle_min_point": "0",
        "de_settle_max_point": "0",
        "de_settle_point_unit": "1",
    }

    def setUp(self):
        self.url = reverse("admin-shop-settings")
        self.admin = get_user_model().objects.create_superuser(
            username="shop-settings-admin", email="shop-settings@example.test", password="password"
        )

    def test_admin_page_requires_superuser(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)

        staff = get_user_model().objects.create_user(
            username="shop-settings-staff", password="password", is_staff=True
        )
        self.client.force_login(staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    @override_settings(SHOP_TOSS_CLIENT_KEY="test_ck_private_client", SHOP_TOSS_SECRET_KEY="test_sk_private_secret")
    def test_page_shows_only_key_presence_and_never_secret(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("테스트 키 쌍", body)
        self.assertIn("등록됨", body)
        self.assertNotIn("test_sk_private_secret", body)
        self.assertIn("data-shipping-preview", body)
        self.assertIn("토스 서버 인증 확인", body)

    def test_saving_settings_keeps_support_phone_in_both_sources(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            self.url,
            {
                "de_admin_company_name": "Demo Shop",
                "de_admin_company_tel": "02-1234-5678",
                "de_delivery_company": "Courier",
                "de_send_cost_case": "차등",
                "de_send_cost_limit": "30000;50000",
                "de_send_cost_list": "4000;0",
                "de_baesong_content": "Delivery details",
                "de_change_content": "Returns details",
                "de_item_use_write": "1",
                "de_item_use_use": "0",
                "de_settle_min_point": "0",
                "de_settle_max_point": "0",
                "de_settle_point_unit": "1",
                "de_bank_use": "on",
                "de_bank_account": "Demo Bank 123-456 Account Holder",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ShopShippingPolicy.objects.get(pk=1).de_admin_company_tel, "02-1234-5678")
        self.assertEqual(Config.objects.get(name="de_admin_company_tel").value, "02-1234-5678")
        self.assertEqual(Config.objects.get(name="de_card_use").value, "")

    def test_business_info_is_saved_to_site_config_and_published(self):
        Config.objects.create(name="cf_company_owner", value="Before")
        self.client.force_login(self.admin)
        page = self.client.get(self.url).content.decode()
        self.assertIn('value="Before"', page)
        self.assertIn("부가통신 사업자번호", page)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(self.url, {
                **self.minimal_form,
                "cf_company_owner": "Owner",
                "cf_company_biz_no": "123-45-67890",
                "cf_company_fax": "02-000-0000",
                "cf_company_zip": "04524",
                "cf_company_buga_no": "VAN-1",
                "cf_company_email": "privacy@example.test",
            })
        self.assertEqual(response.status_code, 302)
        saved = dict(Config.objects.filter(name__startswith="cf_company_").values_list("name", "value"))
        self.assertEqual(saved["cf_company_owner"], "Owner")
        self.assertEqual(saved["cf_company_fax"], "02-000-0000")
        self.assertEqual(saved["cf_company_zip"], "04524")
        self.assertEqual(saved["cf_company_buga_no"], "VAN-1")

        public = self.client.get("/api/v1/settings").json()["data"]
        self.assertEqual(public["cf_company_fax"], "02-000-0000")
        self.assertEqual(public["cf_company_buga_no"], "VAN-1")

    def test_business_email_must_be_valid(self):
        form = ShopSettingsForm(data={**self.minimal_form, "cf_company_email": "not-an-email"},
                                instance=ShopShippingPolicy(pk=1))
        self.assertFalse(form.is_valid())
        self.assertIn("cf_company_email", form.errors)

    @override_settings(SHOP_TOSS_CLIENT_KEY="test_ck_private_client", SHOP_TOSS_SECRET_KEY="test_sk_private_secret")
    def test_pg_check_post_does_not_save_the_settings_form(self):
        ShopShippingPolicy.objects.create(pk=1, de_admin_company_name="Before check")
        self.client.force_login(self.admin)
        with patch(
            "gnu_jango.shop.admin_settings.check_toss_connection",
            return_value={"status": "connected", "connected": True},
        ) as check_connection:
            response = self.client.post(
                self.url,
                {"action": "check_pg", "de_admin_company_name": "Must not be saved"},
            )

        self.assertEqual(response.status_code, 302)
        check_connection.assert_called_once_with()
        self.assertEqual(ShopShippingPolicy.objects.get(pk=1).de_admin_company_name, "Before check")
        self.assertFalse(Config.objects.filter(name="de_admin_company_name").exists())

    def test_tiered_shipping_requires_matching_sorted_bands(self):
        form = ShopSettingsForm(
            data={
                "de_admin_company_name": "Demo Shop",
                "de_admin_company_tel": "",
                "de_delivery_company": "Courier",
                "de_send_cost_case": "차등",
                "de_send_cost_limit": "50000;30000",
                "de_send_cost_list": "3000",
                "de_baesong_content": "",
                "de_change_content": "",
                "de_item_use_write": "0",
                "de_item_use_use": "0",
                "de_settle_min_point": "0",
                "de_settle_max_point": "0",
                "de_settle_point_unit": "1",
            },
            instance=ShopShippingPolicy(pk=1),
        )
        self.assertFalse(form.is_valid())
        self.assertIn("de_send_cost_limit", form.errors)
        self.assertIn("de_send_cost_list", form.errors)

    def test_phone_sync_helpers_cover_both_legacy_admin_paths(self):
        ShopShippingPolicy.objects.create(pk=1, de_admin_company_tel="old")
        sync_shop_phone_from_config("010-1111-2222")
        self.assertEqual(ShopShippingPolicy.objects.get(pk=1).de_admin_company_tel, "010-1111-2222")

        sync_shop_phone_from_policy("010-3333-4444")
        self.assertEqual(Config.objects.get(name="de_admin_company_tel").value, "010-3333-4444")
