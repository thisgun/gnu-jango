"""The Expo app opens the social login at the site root (/social/start.php), as the PHP site served it."""

from django.test import TestCase
from django.urls import resolve

from gnu_jango.api import v1_auth


class SocialRootAliasTests(TestCase):
    def test_the_root_paths_use_the_same_views_as_the_api_paths(self):
        self.assertIs(resolve("/social/start.php").func, resolve("/api/social/start.php").func)
        self.assertIs(resolve("/social/finish.php").func, resolve("/api/social/finish.php").func)
        self.assertIs(resolve("/social/start.php").func, v1_auth.social_start_view)

    def test_the_root_start_answers_like_the_api_start(self):
        root = self.client.get("/social/start.php", {"provider": "naver"})
        api = self.client.get("/api/social/start.php", {"provider": "naver"})

        self.assertEqual(root.status_code, api.status_code)
        self.assertNotEqual(root.status_code, 404)
        self.assertEqual(root.get("Location", ""), api.get("Location", ""))
