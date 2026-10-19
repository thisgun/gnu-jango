"""The social login provider list is fetched on every page (login buttons), so it must stay cheap.

It used to read each provider's settings with one query per key (24 queries); on Vercel every query is
a round trip to Supabase. The settings are now read in one query.
"""

from django.test import TestCase
from rest_framework.test import APIClient

from gnu_jango.config.models import Config

URL = "/api/v1/auth/social/providers"


class SocialProvidersQueryTests(TestCase):
    def test_the_provider_list_reads_its_settings_in_one_query(self):
        with self.assertNumQueries(1):
            response = APIClient().get(URL)
        self.assertEqual(response.status_code, 200)

    def test_settings_saved_in_admin_still_decide_what_is_enabled(self):
        Config.objects.update_or_create(name="cf_social_login_use", defaults={"value": "1"})
        Config.objects.update_or_create(name="cf_social_servicelist", defaults={"value": "naver"})
        Config.objects.update_or_create(name="cf_naver_clientid", defaults={"value": "naver-client"})
        Config.objects.update_or_create(name="cf_naver_secret", defaults={"value": "naver-secret"})

        data = APIClient().get(URL).json()["data"]

        naver = next(provider for provider in data["providers"] if provider["name"] == "naver")
        self.assertTrue(naver["has_api_key"])
        self.assertTrue(naver["enabled"])
        self.assertTrue(data["enabled"])
