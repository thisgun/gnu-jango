"""Rate limits (login 10/min, question search, ...) must not reset when a client forges X-Forwarded-For.

DRF identifies anonymous clients with get_ident(), which trusts the whole X-Forwarded-For header
unless REST_FRAMEWORK["NUM_PROXIES"] is set. The project already knows how many proxies it trusts
(TRUSTED_PROXY_COUNT, used by get_client_ip), so DRF is given the same number.
"""

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import SimpleRateThrottle

from gnu_jango.utils.lib import get_client_ip


def _ident(forwarded_for, remote_addr="198.51.100.7"):
    request = APIRequestFactory().get("/", HTTP_X_FORWARDED_FOR=forwarded_for, REMOTE_ADDR=remote_addr)
    return SimpleRateThrottle.get_ident(SimpleRateThrottle.__new__(SimpleRateThrottle), request)


class ThrottleIdentityTests(SimpleTestCase):
    def test_drf_trusts_as_many_proxies_as_the_project(self):
        self.assertEqual(settings.REST_FRAMEWORK.get("NUM_PROXIES"), settings.TRUSTED_PROXY_COUNT)

    def test_without_proxies_a_forged_header_is_ignored(self):
        with override_settings(REST_FRAMEWORK={**settings.REST_FRAMEWORK, "NUM_PROXIES": 0}):
            self.assertEqual(_ident("203.0.113.1"), "198.51.100.7")
            self.assertEqual(_ident("203.0.113.2"), "198.51.100.7")

    def test_behind_one_proxy_drf_and_get_client_ip_pick_the_same_address(self):
        with override_settings(
            TRUSTED_PROXY_COUNT=1, REST_FRAMEWORK={**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
        ):
            request = APIRequestFactory().get("/", HTTP_X_FORWARDED_FOR="203.0.113.9, 192.0.2.4")
            self.assertEqual(_ident("203.0.113.9, 192.0.2.4"), "192.0.2.4")
            self.assertEqual(get_client_ip(request), "192.0.2.4")
