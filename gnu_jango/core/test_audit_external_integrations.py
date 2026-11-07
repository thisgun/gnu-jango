"""audit_external_integrations only gates on the PG, social logins and certification a site uses.

A bank-transfer shop without social login or certification is production-ready; a provider the site
chose but has not keyed is still a gap. Providers nobody picked are reported as "unused".
"""

import json
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from gnu_jango.api import v1_auth
from gnu_jango.config.models import Config
from gnu_jango.core.test_shop_nicepay import FAKE_NICEPAY


def blank_social_settings():
    names = set()
    for spec in v1_auth.SOCIAL_PROVIDER_SPECS.values():
        for key in ("setting_client_id", "setting_secret", "setting_service_provider_code"):
            if spec.get(key):
                names.add(spec[key])
    return {name: "" for name in names}


# Every integration switched off, so a developer's .env cannot leak into the expectations.
CLEAN = {
    "SHOP_PAYMENT_PROVIDER": "",
    "SHOP_TOSS_CLIENT_KEY": "",
    "SHOP_TOSS_SECRET_KEY": "",
    "SHOP_NICEPAY_MID": "",
    "SHOP_NICEPAY_MERCHANT_KEY": "",
    "SHOP_NICEPAY_TEST_MID": "",
    "SHOP_NICEPAY_TEST_MERCHANT_KEY": "",
    "SHOP_PAYMENT_ADAPTER_BASE_URL": "",
    "SHOP_PAYMENT_ADAPTER_SECRET": "",
    "SHOP_PAYMENT_ADAPTER_PROVIDERS": "",
    "SHOP_PAYMENT_CALLBACK_SECRET": "",
    "SHOP_PAYMENT_CALLBACK_SIGNATURE_SECRET": "",
    "SOCIAL_APP_BASE_URL": "",
    "SOCIAL_ALLOWED_REDIRECT_ORIGINS": "",
    "GNUBOARD_CERT_USE": "",
    "GNUBOARD_CERT_ADAPTER_BASE_URL": "",
    "GNUBOARD_CERT_APP_BASE_URL": "",
    "GNUBOARD_CERT_ALLOWED_ORIGINS": "",
    **blank_social_settings(),
}
ADAPTER = {
    "SHOP_PAYMENT_ADAPTER_BASE_URL": "https://pg-adapter.example.test",
    "SHOP_PAYMENT_ADAPTER_SECRET": "adapter-secret",
}


def run_audit():
    out = StringIO()
    call_command("audit_external_integrations", json=True, stdout=out)
    return json.loads(out.getvalue())


def by_name(items):
    return {item["name"]: item for item in items}


def set_config(**values):
    for name, value in values.items():
        Config.objects.update_or_create(name=name, defaults={"value": value})


@override_settings(**CLEAN)
class UnusedIntegrationsTests(TestCase):
    def test_a_bank_transfer_site_without_social_or_certification_is_ready(self):
        audit = run_audit()

        self.assertTrue(audit["summary"]["production_ready"], audit["summary"])
        self.assertEqual(audit["summary"]["missing_settings"], 0)
        self.assertGreater(audit["summary"]["unused"], 0)
        payment = audit["payment"]
        self.assertEqual(payment["active_provider"], "bank")
        for key in ("callback_secret", "callback_hmac_signature", "toss", "nicepay", "adapter_delegation"):
            self.assertEqual(payment[key]["status"], "unused", key)
        self.assertEqual({item["status"] for item in payment["legacy_pg_parity"]}, {"unused"})
        self.assertEqual({item["status"] for item in payment["operations"]}, {"unused"})
        social = audit["social_oauth"]
        self.assertEqual(social["frontend_origin"]["status"], "unused")
        self.assertEqual({item["status"] for item in social["providers"].values()}, {"unused"})
        self.assertEqual(
            {item["status"] for item in audit["identity_verification"].values()}, {"unused"}
        )

    def test_fail_on_missing_passes_when_nothing_is_in_use(self):
        call_command("audit_external_integrations", fail_on_missing=True, stdout=StringIO())

    def test_text_output_lists_unused_checks_without_actions(self):
        out = StringIO()
        call_command("audit_external_integrations", stdout=out)
        text = out.getvalue()

        self.assertIn("- KG Inicis: unused", text)
        self.assertIn("unused checks:", text)
        self.assertIn("production ready: yes", text)
        self.assertNotIn("action:", text)


@override_settings(**{**CLEAN, **FAKE_NICEPAY})
class NativeNicepayTests(TestCase):
    def test_native_nicepay_counts_as_ready_without_an_adapter(self):
        audit = run_audit()

        payment = audit["payment"]
        self.assertEqual(payment["active_provider"], "nicepay")
        self.assertEqual(payment["nicepay"]["status"], "ready")
        self.assertTrue(payment["nicepay"]["details"]["is_test_mode"])
        legacy = by_name(payment["legacy_pg_parity"])
        self.assertEqual(legacy["nicepay"]["status"], "ready")
        self.assertTrue(legacy["nicepay"]["details"]["native_signature_verification"])
        self.assertEqual(legacy["inicis"]["status"], "unused")
        self.assertEqual(payment["adapter_delegation"]["status"], "unused")
        self.assertEqual(payment["callback_secret"]["status"], "unused")
        self.assertTrue(audit["summary"]["production_ready"], audit["summary"])

    @override_settings(SHOP_NICEPAY_TEST_MID="", SHOP_NICEPAY_TEST_MERCHANT_KEY="")
    def test_a_chosen_nicepay_without_keys_is_missing(self):
        audit = run_audit()

        payment = audit["payment"]
        self.assertEqual(payment["active_provider"], "bank")
        self.assertEqual(payment["nicepay"]["status"], "missing")
        self.assertEqual(by_name(payment["legacy_pg_parity"])["nicepay"]["status"], "missing")
        self.assertFalse(audit["summary"]["production_ready"])
        with self.assertRaises(CommandError):
            call_command("audit_external_integrations", fail_on_missing=True, stdout=StringIO())


@override_settings(**CLEAN)
class AdminChosenPgTests(TestCase):
    def test_toss_saved_in_admin_without_keys_is_missing(self):
        set_config(de_pg_service="toss")

        audit = run_audit()

        self.assertEqual(audit["payment"]["toss"]["status"], "missing")
        self.assertIn("SHOP_TOSS_CLIENT_KEY", audit["payment"]["toss"]["missing"])
        self.assertFalse(audit["summary"]["production_ready"])

    def test_no_pg_saved_in_admin_keeps_toss_unused(self):
        set_config(de_pg_service="none")

        self.assertEqual(run_audit()["payment"]["toss"]["status"], "unused")


@override_settings(**{**CLEAN, **ADAPTER, "SHOP_PAYMENT_PROVIDER": "kcp", "SHOP_PAYMENT_ADAPTER_PROVIDERS": "kcp"})
class AdapterTests(TestCase):
    def test_the_adapter_delegates_its_providers_and_needs_the_callback_secrets(self):
        audit = run_audit()

        payment = audit["payment"]
        self.assertEqual(payment["active_provider"], "kcp")
        self.assertEqual(payment["adapter_delegation"]["status"], "ready")
        legacy = by_name(payment["legacy_pg_parity"])
        self.assertEqual(legacy["kcp"]["status"], "delegated")
        self.assertEqual(legacy["inicis"]["status"], "unused")
        self.assertEqual({item["status"] for item in payment["operations"]}, {"delegated"})
        self.assertEqual(payment["callback_secret"]["status"], "missing")
        self.assertEqual(payment["callback_hmac_signature"]["status"], "missing")
        self.assertFalse(audit["summary"]["production_ready"])

    @override_settings(SHOP_PAYMENT_ADAPTER_SECRET="")
    def test_an_adapter_provider_without_the_adapter_secret_is_missing(self):
        payment = run_audit()["payment"]

        self.assertEqual(payment["adapter_delegation"]["status"], "missing")
        self.assertEqual(by_name(payment["legacy_pg_parity"])["kcp"]["status"], "missing")


@override_settings(**CLEAN)
class SocialLoginTests(TestCase):
    def test_only_the_providers_turned_on_in_admin_are_required(self):
        set_config(cf_social_login_use="1", cf_social_servicelist="kakao")

        social = run_audit()["social_oauth"]

        self.assertEqual(social["providers"]["kakao"]["status"], "missing")
        self.assertEqual(social["providers"]["naver"]["status"], "unused")
        self.assertEqual(social["frontend_origin"]["status"], "missing")

    @override_settings(SOCIAL_KAKAO_REST_KEY="kakao-rest", SOCIAL_APP_BASE_URL="https://site.example.test")
    def test_a_keyed_provider_is_ready(self):
        audit = run_audit()

        self.assertEqual(audit["social_oauth"]["providers"]["kakao"]["status"], "ready")
        self.assertEqual(audit["social_oauth"]["frontend_origin"]["status"], "ready")
        self.assertTrue(audit["summary"]["production_ready"], audit["summary"])


@override_settings(**CLEAN)
class CertificationTests(TestCase):
    @override_settings(GNUBOARD_CERT_USE="2")
    def test_enabled_certification_still_needs_a_verified_adapter(self):
        cert = run_audit()["identity_verification"]

        self.assertEqual(cert["adapter_delegation"]["status"], "missing")
        self.assertEqual(cert["provider_verification"]["status"], "blocked")
