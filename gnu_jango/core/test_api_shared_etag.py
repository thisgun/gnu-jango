"""ETag revalidation for API responses that are the same for every requester (api/caching.py)."""

from django.core.cache import cache
from django.test import TestCase

from gnu_jango.config.models import Config


class SharedResponseEtagTests(TestCase):
    url = "/api/v1/settings"

    def setUp(self):
        cache.clear()
        # a browser almost always sends cookies; that alone used to force no-store
        self.client.cookies["csrftoken"] = "x" * 32

    def test_a_shared_response_gets_an_etag_and_revalidation_cache_control(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response["ETag"].startswith('"'))
        self.assertEqual(response["Cache-Control"], "private, no-cache")
        self.assertIn("Cookie", response["Vary"])

    def test_the_etag_is_stable_while_the_content_is_unchanged(self):
        first = self.client.get(self.url)
        second = self.client.get(self.url)

        self.assertEqual(first["ETag"], second["ETag"])

    def test_a_matching_if_none_match_returns_an_empty_304(self):
        etag = self.client.get(self.url)["ETag"]

        response = self.client.get(self.url, HTTP_IF_NONE_MATCH=etag)

        self.assertEqual(response.status_code, 304)
        self.assertEqual(response.content, b"")
        self.assertEqual(response["ETag"], etag)
        self.assertEqual(response["Cache-Control"], "private, no-cache")

    def test_changed_content_gets_a_new_etag_and_a_full_response(self):
        etag = self.client.get(self.url)["ETag"]
        Config.objects.update_or_create(name="cf_title", defaults={"value": "Renamed site"})
        cache.clear()

        response = self.client.get(self.url, HTTP_IF_NONE_MATCH=etag)

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response["ETag"], etag)
        self.assertEqual(response.json()["data"]["cf_title"], "Renamed site")

    def test_the_public_catalogue_lists_are_revalidated_by_etag(self):
        from gnu_jango.shop.models import ShopCategory

        ShopCategory.objects.create(ca_id="10", ca_name="Clothes", ca_order=1)
        for url in ("/api/v1/boards", "/api/v1/shop/categories", "/api/v1/shop/categories/10", "/api/v1/shop/products"):
            with self.subTest(url=url):
                first = self.client.get(url)
                self.assertEqual(first.status_code, 200)
                self.assertEqual(first["Cache-Control"], "private, no-cache")

                again = self.client.get(url, HTTP_IF_NONE_MATCH=first["ETag"])
                self.assertEqual(again.status_code, 304)

    def test_a_missing_category_is_not_tagged(self):
        response = self.client.get("/api/v1/shop/categories/does-not-exist")

        self.assertEqual(response.status_code, 404)
        self.assertNotIn("ETag", response)
        self.assertEqual(response["Cache-Control"], "no-store, private")

    def test_requester_specific_endpoints_keep_no_store(self):
        response = self.client.get("/api/v1/menus")

        self.assertNotIn("ETag", response)
        self.assertEqual(response["Cache-Control"], "no-store, private")
