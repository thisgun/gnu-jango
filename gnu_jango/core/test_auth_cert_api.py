"""Identity verification (cert) bridge: gnu_jango/api/auth_cert.py.

The Django port has no provider SDK. The start pages either hand the browser to a configured
adapter host or report "not implemented", and the result pages never accept a verification. These
tests pin that fail-closed behaviour (a forged or replayed provider callback never yields a success
payload or a session flag), the allow-listing of the postMessage target origin, the adapter redirect
and the config parsing. No provider is called; nothing here touches the network.
"""

import json
import re
from unittest import mock

from django.core.cache import cache
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings

from gnu_jango.api import auth_cert, auth_common, v1_auth
from gnu_jango.config.models import Config

SESSION_KEY = auth_cert.CERT_RETURN_ORIGIN_SESSION_KEY
EVIL_ORIGINS = (
    "https://evil.example",
    "http://evil.example:8000",
    "null",
    "javascript:alert(1)",
    "//evil.example",
    "http://testserver.evil.example",
    "http://testserver@evil.example",
    "http://evil.example#testserver",
    "ftp://testserver",
)
PROVIDERS = (
    # (config name, provider, start path, result path, adapter endpoint)
    ("cf_cert_hp", "kcp", "/api/cert/kcp_start.php", "/api/cert/kcp_result.php", "kcp_start.php"),
    ("cf_cert_hp", "kcp_v2", "/api/cert/kcp_v2_start.php", "/api/cert/kcp_v2_result.php", "kcp_v2_start.php"),
    ("cf_cert_simple", "inicis", "/api/cert/inicis_start.php", "/api/cert/inicis_result.php", "inicis_start.php"),
)
FORGED_RESULT = {
    "res_cd": "0000",
    "result": "success",
    "status": "success",
    "cert_no": "FORGED-CERT-NO",
    "dn_hash": "deadbeef",
    "ci": "forged-ci",
    "di": "forged-di",
    "mb_certify": "hp",
    "mb_adult": "1",
    "adult": "Y",
    "mb_dupinfo": "x" * 64,
    "user_name": "FORGED Name",
    "birth_day": "19000101",
    "ss_cert_no": "FORGED",
    "returnOrigin": "https://evil.example",
}
NO_ORIGINS = {
    "CORS_ALLOWED_ORIGINS": [],
    "SOCIAL_APP_BASE_URL": "",
    "GNUBOARD_CERT_APP_BASE_URL": "",
    "SOCIAL_ALLOWED_REDIRECT_ORIGINS": [],
    "GNUBOARD_CERT_ALLOWED_ORIGINS": [],
}
SESSION_FLAGS = {"ss_cert_no", "ss_cert_hash", "ss_cert_adult", "ss_cert_dupinfo", "ss_cert_type", "ss_cert_mb_id"}


class FakeSession(dict):
    modified = False


def target_origin(response):
    match = re.search(r"var targetOrigin = (.*);", response.content.decode())
    return json.loads(match.group(1))


def bridge_payload(response):
    match = re.search(r"var payload = (.*);", response.content.decode())
    return json.loads(match.group(1).replace("<\\/", "</"))


def set_config(**values):
    for name, value in values.items():
        Config.objects.update_or_create(name=name, defaults={"value": value})


def request_with_session(query=None, session=None):
    request = RequestFactory().get("/x", query or {})
    request.session = FakeSession(session or {})
    return request


class CertTestBase(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def enable(self, name, provider, mode="1"):
        set_config(cf_cert_use=mode, **{name: provider})


class CertConfigValueTests(CertTestBase):
    def test_setting_wins_over_the_site_config(self):
        set_config(cf_cert_hp="kcp")
        with override_settings(GNUBOARD_CERT_HP="kcp_v2"):
            self.assertEqual(auth_cert._cert_value("cf_cert_hp", "GNUBOARD_CERT_HP"), "kcp_v2")

    def test_blank_setting_falls_back_to_the_site_config(self):
        set_config(cf_cert_hp="kcp")
        with override_settings(GNUBOARD_CERT_HP="   "):
            self.assertEqual(auth_cert._cert_value("cf_cert_hp", "GNUBOARD_CERT_HP"), "kcp")

    def test_without_a_setting_name_only_the_site_config_is_read(self):
        set_config(cf_cert_hp="kcp")
        self.assertEqual(auth_cert._cert_value("cf_cert_hp"), "kcp")
        self.assertEqual(auth_cert._cert_value("cf_missing", default="d"), "d")

    def test_a_database_failure_yields_the_default_instead_of_an_error(self):
        with mock.patch.object(auth_common.Config.objects, "filter", side_effect=RuntimeError("db down")):
            self.assertEqual(auth_cert._cert_value("cf_cert_hp", default="fallback"), "fallback")
            payload = auth_cert._cert_config_payload()
        self.assertFalse(payload["enabled"])
        self.assertEqual(payload["hp"], "")

    def test_int_value_parses_whitespace_and_defaults_on_garbage(self):
        set_config(cf_cert_use=" 2 ")
        self.assertEqual(auth_cert._cert_int_value("cf_cert_use"), 2)
        set_config(cf_cert_use="two")
        self.assertEqual(auth_cert._cert_int_value("cf_cert_use", default=7), 7)
        set_config(cf_cert_use="")
        self.assertEqual(auth_cert._cert_int_value("cf_cert_use", default=5), 5)
        set_config(cf_cert_use="1.5")
        self.assertEqual(auth_cert._cert_int_value("cf_cert_use", default=3), 3)

    def test_provider_value_is_lowercased_trimmed_and_allow_listed(self):
        set_config(cf_cert_hp="  KCP ")
        self.assertEqual(auth_cert._cert_provider_value("cf_cert_hp", allowed={"kcp"}), "kcp")
        set_config(cf_cert_hp="kcp'; drop table--")
        self.assertEqual(auth_cert._cert_provider_value("cf_cert_hp", allowed={"kcp"}), "")

    def test_provider_value_without_an_allow_list_is_returned_normalised(self):
        set_config(cf_cert_hp="Anything")
        self.assertEqual(auth_cert._cert_provider_value("cf_cert_hp"), "anything")

    def test_config_payload_rejects_a_provider_from_the_wrong_family(self):
        set_config(cf_cert_use="1", cf_cert_simple="kcp", cf_cert_ipin="inicis", cf_cert_hp="inicis")
        payload = auth_cert._cert_config_payload()
        self.assertEqual((payload["simple"], payload["ipin"], payload["hp"]), ("", "", ""))

    def test_config_payload_reads_the_flag_options(self):
        set_config(cf_use_hp="1", cf_req_hp="yes", cf_cert_req="0", cf_cert_find="on")
        payload = auth_cert._cert_config_payload()
        self.assertTrue(payload["use_hp"])
        self.assertTrue(payload["require_hp"])
        self.assertFalse(payload["required"])
        self.assertTrue(payload["find_enabled"])

    def test_config_endpoint_is_public_and_exposes_only_the_public_fields(self):
        set_config(cf_cert_use="1", cf_cert_hp="kcp")
        with override_settings(GNUBOARD_CERT_SITE_CD="SECRET-SITE-CD", GNUBOARD_CERT_KEY="SECRET-KEY-MATERIAL"):
            response = self.client.get("/api/v1/auth/cert/config")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("SECRET", response.content.decode())
        self.assertEqual(
            set(response.json()["data"]),
            {"enabled", "mode", "required", "find_enabled", "simple", "hp", "ipin", "use_hp", "require_hp"},
        )

    def test_config_endpoint_rejects_writes(self):
        for method in ("post", "put", "patch", "delete"):
            response = getattr(self.client, method)("/api/v1/auth/cert/config", {"cf_cert_use": "1"})
            self.assertEqual(response.status_code, 405, method)
        self.assertFalse(auth_cert._cert_config_payload()["enabled"])

    def test_v1_auth_reexports_the_moved_names(self):
        for name in ("_cert_config_payload", "_cert_bridge_html", "cert_kcp_result_view", "_cert_origin_allowed"):
            self.assertIs(getattr(v1_auth, name), getattr(auth_cert, name))


class CertMethodEnabledTests(CertTestBase):
    def test_nothing_is_enabled_when_the_master_switch_is_off(self):
        set_config(cf_cert_use="0", cf_cert_hp="kcp", cf_cert_simple="inicis", cf_cert_ipin="kcb")
        for kind, provider in (("hp", "kcp"), ("simple", "inicis"), ("ipin", "kcb")):
            self.assertFalse(auth_cert._cert_method_enabled(kind, provider))

    def test_only_the_configured_provider_of_each_kind_is_enabled(self):
        set_config(cf_cert_use="1", cf_cert_hp="kcp", cf_cert_simple="inicis", cf_cert_ipin="kcb")
        self.assertTrue(auth_cert._cert_method_enabled("hp", "kcp"))
        self.assertFalse(auth_cert._cert_method_enabled("hp", "kcp_v2"))
        self.assertTrue(auth_cert._cert_method_enabled("simple", "inicis"))
        self.assertTrue(auth_cert._cert_method_enabled("ipin", "kcb"))
        self.assertFalse(auth_cert._cert_method_enabled("ipin", "kcp"))

    def test_an_unknown_kind_is_never_enabled(self):
        set_config(cf_cert_use="1", cf_cert_hp="kcp")
        self.assertFalse(auth_cert._cert_method_enabled("admin", "kcp"))
        self.assertFalse(auth_cert._cert_method_enabled("", ""))

    def test_an_empty_provider_name_never_matches_an_unconfigured_family(self):
        # Fixed latent defect: an unconfigured family is "" and "" == "" enables an
        # empty provider name. Unreachable today because every view passes a non-empty provider.
        set_config(cf_cert_use="1")
        self.assertFalse(auth_cert._cert_method_enabled("hp", ""))


class CertPageTypeTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_defaults_to_register(self):
        self.assertEqual(auth_cert._cert_page_type(self.factory.get("/x")), "register")

    def test_is_case_and_whitespace_insensitive(self):
        self.assertEqual(auth_cert._cert_page_type(self.factory.get("/x", {"pageType": " FIND "})), "find")

    def test_can_come_from_the_post_body(self):
        self.assertEqual(auth_cert._cert_page_type(self.factory.post("/x", {"pageType": "find"})), "find")

    def test_anything_else_is_refused(self):
        for value in ("../x", "admin", "register;find", "<script>", "reg\x00ister"):
            self.assertEqual(auth_cert._cert_page_type(self.factory.get("/x", {"pageType": value})), "", value)


class CertOriginAllowListTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get("/x")  # origin http://testserver

    def test_the_current_origin_is_always_allowed(self):
        self.assertIn("http://testserver", auth_cert._cert_allowed_post_message_origins(self.request))
        self.assertTrue(auth_cert._cert_origin_allowed(self.request, "http://testserver"))

    @override_settings(
        SOCIAL_APP_BASE_URL="https://app.example/path/ignored",
        GNUBOARD_CERT_APP_BASE_URL="https://cert-app.example:8443",
        SOCIAL_ALLOWED_REDIRECT_ORIGINS="https://a.example|https://b.example, notanorigin",
        GNUBOARD_CERT_ALLOWED_ORIGINS=["https://c.example"],
        CORS_ALLOWED_ORIGINS=["https://cors.example", "ws://bad.example"],
    )
    def test_configured_origins_are_collected_and_normalised(self):
        self.assertEqual(
            auth_cert._cert_allowed_post_message_origins(self.request),
            {
                "http://testserver",
                "https://app.example",
                "https://cert-app.example:8443",
                "https://a.example",
                "https://b.example",
                "https://c.example",
                "https://cors.example",
            },
        )

    @override_settings(SOCIAL_APP_BASE_URL="", GNUBOARD_CERT_APP_BASE_URL=None)
    def test_blank_settings_add_nothing(self):
        self.assertNotIn("", auth_cert._cert_allowed_post_message_origins(self.request))

    def test_unlisted_origins_are_refused(self):
        for origin in EVIL_ORIGINS:
            self.assertFalse(auth_cert._cert_origin_allowed(self.request, origin), origin)

    @override_settings(DEBUG=False, **NO_ORIGINS)
    def test_loopback_is_not_allowed_outside_debug(self):
        self.assertFalse(auth_cert._cert_origin_allowed(self.request, "http://localhost:3000"))
        self.assertFalse(auth_cert._cert_origin_allowed(self.request, "http://127.0.0.1:3000"))

    @override_settings(DEBUG=True, **NO_ORIGINS)
    def test_loopback_is_allowed_in_debug_only(self):
        self.assertTrue(auth_cert._cert_origin_allowed(self.request, "http://localhost:3000"))
        self.assertTrue(auth_cert._cert_origin_allowed(self.request, "http://127.0.0.1:3000"))
        self.assertFalse(auth_cert._cert_origin_allowed(self.request, "https://evil.example"))

    @override_settings(DEBUG=True)
    def test_debug_loopback_check_survives_a_malformed_origin(self):
        with mock.patch.object(auth_cert.urllib.parse, "urlparse", side_effect=ValueError("bad")):
            self.assertFalse(auth_cert._cert_origin_allowed(self.request, "http://x"))

    @override_settings(DEBUG=True, **NO_ORIGINS)
    def test_debug_loopback_check_does_not_trust_a_public_host_starting_with_127(self):
        # Fixed: auth_common._is_loopback_host used hostname.startswith("127."), so a public DNS name
        # such as 127.evil.example is treated as loopback and becomes a valid postMessage target.
        self.assertFalse(auth_cert._cert_origin_allowed(self.request, "http://127.evil.example"))


class CertPostMessageOriginTests(CertTestBase):
    def test_a_listed_origin_is_used_and_remembered_in_the_session(self):
        request = request_with_session({"returnOrigin": "http://testserver"})
        self.assertEqual(auth_cert._cert_post_message_origin(request), "http://testserver")
        self.assertEqual(request.session[SESSION_KEY], "http://testserver")
        self.assertTrue(request.session.modified)

    def test_a_foreign_origin_falls_back_to_the_current_one_and_is_not_stored(self):
        for origin in EVIL_ORIGINS:
            request = request_with_session({"returnOrigin": origin})
            self.assertEqual(auth_cert._cert_post_message_origin(request), "http://testserver", origin)
            self.assertNotIn(SESSION_KEY, request.session, origin)

    @override_settings(CORS_ALLOWED_ORIGINS=["https://app.example"])
    def test_a_stored_origin_is_reused_when_the_request_names_none(self):
        request = request_with_session(session={SESSION_KEY: "https://app.example"})
        self.assertEqual(auth_cert._cert_post_message_origin(request), "https://app.example")

    def test_a_stored_origin_that_is_no_longer_allowed_is_ignored(self):
        request = request_with_session(session={SESSION_KEY: "https://revoked.example"})
        self.assertEqual(auth_cert._cert_post_message_origin(request), "http://testserver")

    @override_settings(CORS_ALLOWED_ORIGINS=["https://app.example"])
    def test_a_bad_request_origin_does_not_displace_a_good_stored_one(self):
        request = request_with_session(
            {"returnOrigin": "https://evil.example"}, {SESSION_KEY: "https://app.example"}
        )
        self.assertEqual(auth_cert._cert_post_message_origin(request), "https://app.example")
        self.assertEqual(request.session[SESSION_KEY], "https://app.example")

    def test_the_result_is_not_the_wildcard_when_the_host_is_known(self):
        self.assertNotEqual(auth_cert._cert_post_message_origin(request_with_session()), "*")

    def test_never_broadcasts_a_verification_result_to_any_origin(self):
        # Fixed: the last-resort target origin used to be "*". With a real verification
        # payload this hands the result (name, CI/DI, adult flag) to whichever page opened the popup.
        # A bridge that cannot name a trusted origin should refuse to post rather than broadcast.
        with mock.patch.object(auth_cert, "_current_origin", return_value=""):
            self.assertNotEqual(auth_cert._cert_post_message_origin(request_with_session()), "*")


class CertAdapterUrlTests(CertTestBase):
    def url(self, query="", base="https://adapter.example", endpoint="kcp_start.php"):
        request = RequestFactory().get("/api/cert/kcp_start.php" + (f"?{query}" if query else ""))
        with override_settings(GNUBOARD_CERT_ADAPTER_BASE_URL=base):
            return auth_cert._cert_adapter_url(request, endpoint)

    def test_no_adapter_configured_gives_an_empty_url(self):
        self.assertEqual(self.url(base=""), "")

    def test_the_endpoint_is_appended_to_the_api_cert_root(self):
        expected = "https://adapter.example/api/cert/kcp_start.php"
        self.assertEqual(self.url(), expected)
        self.assertEqual(self.url(base="https://adapter.example/"), expected)
        self.assertEqual(self.url(base="https://adapter.example/api/cert/"), expected)

    def test_a_leading_slash_on_the_endpoint_cannot_escape_the_root(self):
        self.assertEqual(self.url(endpoint="/kcp_start.php"), "https://adapter.example/api/cert/kcp_start.php")

    def test_an_adapter_on_the_same_origin_is_ignored_to_avoid_a_redirect_loop(self):
        self.assertEqual(self.url(base="http://testserver"), "")
        self.assertEqual(self.url(base="http://testserver/api/cert"), "")

    def test_the_query_string_is_forwarded(self):
        self.assertEqual(self.url("pageType=find"), "https://adapter.example/api/cert/kcp_start.php?pageType=find")

    def test_a_foreign_return_origin_is_dropped_from_the_forwarded_query(self):
        url = self.url("pageType=register&returnOrigin=https%3A%2F%2Fevil.example")
        self.assertNotIn("evil.example", url)
        self.assertNotIn("returnOrigin", url)
        self.assertIn("pageType=register", url)

    def test_an_allowed_return_origin_is_forwarded_normalised(self):
        url = self.url("returnOrigin=HTTP%3A%2F%2FTestServer%2Fsome%2Fpath")
        self.assertIn("returnOrigin=http%3A%2F%2Ftestserver", url)
        self.assertNotIn("some", url)

    def test_repeated_return_origin_parameters_cannot_smuggle_a_foreign_one(self):
        good = "returnOrigin=http%3A%2F%2Ftestserver"
        evil = "returnOrigin=https%3A%2F%2Fevil.example"
        self.assertNotIn("evil.example", self.url(f"{good}&{evil}"))
        self.assertNotIn("evil.example", self.url(f"{evil}&{good}"))


class CertBridgeHtmlTests(CertTestBase):
    def render(self, payload, **kwargs):
        request = request_with_session()
        return request, auth_cert._cert_bridge_html(request, payload, **kwargs)

    def test_the_payload_defaults_to_an_error_result(self):
        _, response = self.render({})
        self.assertEqual(bridge_payload(response), {"type": "identity-verification-result", "status": "error"})
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")

    def test_a_script_closing_sequence_in_the_payload_cannot_break_out_of_the_script_block(self):
        _, response = self.render({"message": "</script><script>alert(1)</script>"})
        self.assertEqual(response.content.decode().count("</script>"), 1)
        self.assertEqual(bridge_payload(response)["message"], "</script><script>alert(1)</script>")

    def test_no_markup_character_from_the_payload_reaches_the_script_block(self):
        # "<!--" and an unclosed "<script" can change how the browser parses a script block.
        _, response = self.render({"message": "<!--<script>&x"})
        script_line = re.search(r"var payload = (.*);", response.content.decode()).group(1)
        self.assertNotRegex(script_line, r"[<>&]")
        self.assertEqual(bridge_payload(response)["message"], "<!--<script>&x")

    def test_non_ascii_text_is_preserved(self):
        _, response = self.render({"message": "본인확인 실패"})
        self.assertEqual(bridge_payload(response)["message"], "본인확인 실패")

    def test_an_explicit_payload_type_and_status_are_kept(self):
        _, response = self.render({"type": "custom", "status": "success"})
        self.assertEqual((bridge_payload(response)["type"], bridge_payload(response)["status"]), ("custom", "success"))

    def test_the_stored_return_origin_is_cleared_after_rendering(self):
        request = request_with_session(session={SESSION_KEY: "http://testserver"})
        auth_cert._cert_bridge_html(request, {})
        self.assertEqual(request.session[SESSION_KEY], "")

    def test_the_stored_return_origin_can_be_kept(self):
        request = request_with_session(session={SESSION_KEY: "http://testserver"})
        auth_cert._cert_bridge_html(request, {}, clear_return_origin=False)
        self.assertEqual(request.session[SESSION_KEY], "http://testserver")

    def test_the_message_is_posted_only_to_the_resolved_origin(self):
        _, response = self.render({"status": "success"})
        self.assertEqual(target_origin(response), "http://testserver")
        self.assertIn("postMessage(payload, targetOrigin)", response.content.decode())

    def test_error_helper_wraps_the_message_and_code(self):
        payload = bridge_payload(auth_cert._cert_error_and_close(request_with_session(), ValueError("boom"), code="c1"))
        self.assertEqual((payload["status"], payload["code"], payload["message"]), ("error", "c1", "boom"))


class CertStartViewTests(CertTestBase):
    def test_every_start_page_is_disabled_by_default(self):
        for _, provider, start, _, _ in PROVIDERS:
            response = self.client.get(start)
            self.assertEqual(response.status_code, 200, provider)
            self.assertEqual(bridge_payload(response)["code"], "cert_provider_disabled", provider)

    def test_disabled_message_names_the_provider(self):
        self.assertIn("KG", bridge_payload(self.client.get("/api/cert/inicis_start.php"))["message"])
        self.assertIn("api_v2", bridge_payload(self.client.get("/api/cert/kcp_v2_start.php"))["message"])
        self.assertIn("KCP", bridge_payload(self.client.get("/api/cert/kcp_start.php"))["message"])

    def test_an_enabled_provider_without_an_adapter_reports_not_implemented(self):
        for name, provider, start, _, _ in PROVIDERS:
            self.enable(name, provider)
            payload = bridge_payload(self.client.get(start))
            self.assertEqual(payload["code"], "cert_provider_unimplemented", provider)
            self.assertEqual(payload["status"], "error")

    def test_only_the_configured_provider_starts(self):
        self.enable("cf_cert_hp", "kcp")
        for path in ("/api/cert/kcp_v2_start.php", "/api/cert/inicis_start.php"):
            self.assertEqual(bridge_payload(self.client.get(path))["code"], "cert_provider_disabled", path)

    def test_an_invalid_page_type_is_refused_before_the_provider_is_considered(self):
        self.enable("cf_cert_hp", "kcp")
        for page_type in ("admin", "../x"):
            response = self.client.get("/api/cert/kcp_start.php", {"pageType": page_type})
            self.assertEqual(bridge_payload(response)["code"], "invalid_cert_page_type", page_type)

    def test_find_requires_the_find_option_for_every_provider(self):
        for name, provider, start, _, _ in PROVIDERS:
            self.enable(name, provider)
            payload = bridge_payload(self.client.get(start, {"pageType": "find"}))
            self.assertEqual(payload["code"], "cert_find_disabled", provider)

    def test_find_proceeds_to_the_provider_check_when_the_option_is_on(self):
        self.enable("cf_cert_hp", "kcp")
        set_config(cf_cert_find="1")
        payload = bridge_payload(self.client.get("/api/cert/kcp_start.php", {"pageType": "find"}))
        self.assertEqual(payload["code"], "cert_provider_unimplemented")

    @override_settings(GNUBOARD_CERT_ADAPTER_BASE_URL="https://adapter.example")
    def test_with_an_adapter_the_browser_is_redirected_there(self):
        for name, provider, start, _, endpoint in PROVIDERS:
            self.enable(name, provider)
            response = self.client.get(start, {"pageType": "register"})
            self.assertEqual(response.status_code, 302, provider)
            self.assertEqual(response["Location"], f"https://adapter.example/api/cert/{endpoint}?pageType=register")

    @override_settings(GNUBOARD_CERT_ADAPTER_BASE_URL="https://adapter.example")
    def test_the_redirect_never_goes_to_a_client_chosen_host(self):
        self.enable("cf_cert_hp", "kcp")
        response = self.client.get(
            "/api/cert/kcp_start.php",
            {"returnOrigin": "https://evil.example", "next": "https://evil.example", "adapter": "https://evil.example"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("https://adapter.example/api/cert/kcp_start.php?"))
        self.assertNotIn("returnOrigin", response["Location"])

    @override_settings(GNUBOARD_CERT_ADAPTER_BASE_URL="https://adapter.example")
    def test_a_disabled_provider_is_not_redirected_to_the_adapter(self):
        self.assertEqual(self.client.get("/api/cert/kcp_start.php").status_code, 200)

    @override_settings(GNUBOARD_CERT_ADAPTER_BASE_URL="http://testserver")
    def test_an_adapter_pointing_back_at_this_host_does_not_loop(self):
        self.enable("cf_cert_hp", "kcp")
        response = self.client.get("/api/cert/kcp_start.php")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(bridge_payload(response)["code"], "cert_provider_unimplemented")

    def test_a_start_page_reads_its_page_type_from_a_post_body_too(self):
        self.enable("cf_cert_hp", "kcp")
        response = self.client.post("/api/cert/kcp_start.php", {"pageType": "find"})
        self.assertEqual(bridge_payload(response)["code"], "cert_find_disabled")

    def test_start_responses_are_not_cacheable(self):
        for _, _, start, _, _ in PROVIDERS:
            cache_control = self.client.get(start)["Cache-Control"]
            self.assertIn("no-store", cache_control)
            self.assertIn("private", cache_control)

    def test_the_start_page_posts_to_the_requested_allowed_origin_only(self):
        self.enable("cf_cert_hp", "kcp")
        with override_settings(CORS_ALLOWED_ORIGINS=["https://app.example"]):
            good = self.client.get("/api/cert/kcp_start.php", {"returnOrigin": "https://app.example"})
            bad = self.client.get("/api/cert/kcp_start.php", {"returnOrigin": "https://evil.example"})
        self.assertEqual(target_origin(good), "https://app.example")
        self.assertEqual(target_origin(bad), "http://testserver")

    def test_a_remembered_origin_is_used_once_then_cleared(self):
        with override_settings(CORS_ALLOWED_ORIGINS=["https://app.example"]):
            first = self.client.get("/api/cert/kcp_start.php", {"returnOrigin": "https://app.example"})
            self.assertEqual(target_origin(first), "https://app.example")
            self.assertEqual(self.client.session[SESSION_KEY], "")
            second = self.client.get("/api/cert/kcp_start.php")
        self.assertEqual(target_origin(second), "http://testserver")


class CertResultViewTests(CertTestBase):
    """A provider callback is never accepted: the port has no SDK to verify its signature."""

    def assert_not_verified(self, response, provider):
        self.assertEqual(response.status_code, 200, provider)
        payload = bridge_payload(response)
        self.assertEqual(payload["status"], "error", provider)
        for key in ("cert_no", "ci", "di", "mb_dupinfo", "mb_adult", "adult", "user_name", "birth_day"):
            self.assertNotIn(key, payload, provider)
        self.assertNotIn("FORGED", response.content.decode(), provider)

    def test_a_disabled_provider_rejects_a_result(self):
        for _, provider, _, result, _ in PROVIDERS:
            response = self.client.post(result, FORGED_RESULT)
            self.assertEqual(bridge_payload(response)["code"], "cert_provider_disabled", provider)
            self.assert_not_verified(response, provider)

    def test_an_enabled_provider_still_rejects_a_forged_result(self):
        for name, provider, _, result, _ in PROVIDERS:
            self.enable(name, provider)
            response = self.client.post(result, FORGED_RESULT)
            self.assertEqual(bridge_payload(response)["code"], "cert_result_unimplemented", provider)
            self.assert_not_verified(response, provider)

    def test_a_result_for_a_provider_other_than_the_configured_one_is_refused(self):
        self.enable("cf_cert_hp", "kcp")
        response = self.client.post("/api/cert/kcp_v2_result.php", FORGED_RESULT)
        self.assertEqual(bridge_payload(response)["code"], "cert_provider_disabled")

    def test_a_forged_result_sets_no_certification_flags_in_the_session(self):
        for name, provider, _, result, _ in PROVIDERS:
            self.enable(name, provider)
            self.client.post(result, FORGED_RESULT)
        self.assertFalse(SESSION_FLAGS & set(self.client.session.keys()))
        self.assertFalse([key for key in self.client.session.keys() if key.startswith("ss_cert")])

    def test_a_replayed_result_is_rejected_every_time(self):
        self.enable("cf_cert_hp", "kcp")
        codes = {bridge_payload(self.client.post("/api/cert/kcp_result.php", FORGED_RESULT))["code"] for _ in range(3)}
        self.assertEqual(codes, {"cert_result_unimplemented"})

    def test_get_callbacks_with_a_query_string_are_rejected_too(self):
        self.enable("cf_cert_hp", "kcp")
        response = self.client.get("/api/cert/kcp_result.php", FORGED_RESULT)
        self.assertEqual(bridge_payload(response)["code"], "cert_result_unimplemented")

    def test_result_endpoints_accept_provider_posts_without_a_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        for _, _, _, result, _ in PROVIDERS:
            self.assertEqual(client.post(result, FORGED_RESULT).status_code, 200)

    def test_start_endpoints_are_not_csrf_exempt(self):
        client = Client(enforce_csrf_checks=True)
        for _, _, start, _, _ in PROVIDERS:
            self.assertEqual(client.post(start, {"pageType": "register"}).status_code, 403)

    def test_a_forged_return_origin_in_a_result_callback_is_not_used_as_the_target(self):
        self.enable("cf_cert_hp", "kcp")
        response = self.client.post("/api/cert/kcp_result.php", FORGED_RESULT)
        self.assertEqual(target_origin(response), "http://testserver")
        response = self.client.get("/api/cert/kcp_result.php", {"returnOrigin": "https://evil.example"})
        self.assertEqual(target_origin(response), "http://testserver")

    def test_malformed_and_oversized_bodies_do_not_cause_a_server_error(self):
        self.enable("cf_cert_hp", "kcp")
        cases = (
            {"data": b"\x00\xff", "content_type": "application/octet-stream"},
            {"data": "{not json", "content_type": "application/json"},
            {"data": "a=" + "b" * 200_000, "content_type": "application/x-www-form-urlencoded"},
        )
        for case in cases:
            response = self.client.post("/api/cert/kcp_result.php", **case)
            self.assertEqual(response.status_code, 200, case["content_type"])
            self.assertEqual(bridge_payload(response)["code"], "cert_result_unimplemented")

    def test_unicode_and_sql_characters_in_fields_are_inert(self):
        self.enable("cf_cert_hp", "kcp")
        nasty = {"cert_no": "' OR 1=1 --", "user_name": "홍길동😀<script>alert(1)</script>", "pageType": "'; --"}
        response = self.client.post("/api/cert/kcp_result.php", nasty)
        self.assertNotIn("<script>alert(1)</script>", response.content.decode())
        self.assertEqual(bridge_payload(response)["code"], "cert_result_unimplemented")

    def test_pages_do_not_leak_configured_provider_secrets(self):
        self.enable("cf_cert_hp", "kcp")
        with override_settings(GNUBOARD_CERT_SITE_CD="SITECD-SECRET-123", GNUBOARD_CERT_KEY="KEY-SECRET-456"):
            for path in ("/api/cert/kcp_start.php", "/api/cert/kcp_result.php", "/api/cert/inicis_result.php"):
                self.assertNotIn("SECRET", self.client.post(path, FORGED_RESULT).content.decode(), path)

    def test_result_responses_are_not_cacheable(self):
        for _, _, _, result, _ in PROVIDERS:
            self.assertIn("no-store", self.client.post(result, FORGED_RESULT)["Cache-Control"])

    def test_a_database_outage_still_returns_a_closed_page_rather_than_a_500(self):
        with mock.patch.object(auth_common.Config.objects, "filter", side_effect=RuntimeError("db down")):
            for _, _, start, result, _ in PROVIDERS:
                self.assertEqual(bridge_payload(self.client.get(start))["code"], "cert_provider_disabled")
                self.assertEqual(
                    bridge_payload(self.client.post(result, FORGED_RESULT))["code"], "cert_provider_disabled"
                )

    def test_the_public_config_ignores_client_supplied_verification_fields(self):
        response = self.client.get("/api/v1/auth/cert/config", FORGED_RESULT)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("mb_adult", response.json()["data"])
