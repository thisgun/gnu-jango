"""First-screen snapshots preserve read rules and invalidate only committed content."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import transaction
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.api import page_bootstrap
from gnu_jango.bbs.models import Board, Group, Post
from gnu_jango.config import sample_data
from gnu_jango.core.models import Poll, PollChoice, PollVote
from gnu_jango.shop.models import ShopProduct


@override_settings(DEBUG=True, CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "page-bootstrap-tests"}})
class PageBootstrapTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def data(self, path, client=None, **headers):
        response = (client or self.client).get(path, **headers)
        self.assertEqual(response.status_code, 200, response.content[:500])
        return response.json()["data"]

    def test_community_matches_individual_read_endpoints(self):
        sample_data.create_sample_data()
        home = self.data("/api/v1/home")
        self.assertEqual(len(home["boardPanels"]), 3)
        for panel in home["boardPanels"]:
            posts = self.data(f'/api/v1/boards/{panel["board"]["bo_table"]}/posts?per_page=5')
            self.assertEqual(panel["posts"], posts[:5])
        self.assertTrue(home["gallery"]["posts"])
        self.assertEqual(home["faqs"], self.data("/api/v1/faqs?per_page=4")["items"][:4])

    def test_shop_matches_product_filters_and_does_not_show_disabled_products(self):
        manifest = sample_data.create_sample_data()
        disabled = ShopProduct.objects.get(pk=manifest["products"][0])
        disabled.it_use = "0"
        disabled.save(update_fields=["it_use"])
        home = self.data("/api/v1/shop/home")
        self.assertTrue(home["banners"])
        self.assertEqual(home["categories"], self.data("/api/v1/shop/categories"))
        for number in range(1, 6):
            expected = self.data(f"/api/v1/shop/products?it_type{number}=1&per_page=12")
            self.assertEqual(home["products"][f"type{number}"], expected)
            self.assertNotIn(disabled.pk, [row["it_id"] for row in expected])

    def test_only_cookieless_anonymous_requests_share_snapshots(self):
        with patch.object(page_bootstrap, "_shop_data", return_value={"settings": {}}) as build:
            self.data("/api/v1/shop/home")
            self.data("/api/v1/shop/home")
            self.assertEqual(build.call_count, 1)
            cookie_client = APIClient()
            cookie_client.cookies["sessionid"] = "unknown-guest-session"
            self.data("/api/v1/shop/home", cookie_client)
            self.data("/api/v1/shop/home", cookie_client)
            self.assertEqual(build.call_count, 3)
            member = get_user_model().objects.create_user(username="bootstrap-member")
            member_client = APIClient()
            member_client.force_authenticate(member)
            self.data("/api/v1/shop/home", member_client)
            self.data("/api/v1/shop/home", member_client)
            self.assertEqual(build.call_count, 5)

    @override_settings(DEBUG=False)
    def test_production_does_not_share_a_worker_local_cache(self):
        with patch.object(page_bootstrap, "_shop_data", return_value={}) as build:
            self.data("/api/v1/shop/home")
            self.data("/api/v1/shop/home")
            self.assertEqual(build.call_count, 2)

    def test_an_admin_snapshot_cannot_expose_private_posts_to_guests(self):
        sample_data.create_sample_data()
        group = Group.objects.create(gr_id="bootstrap-private", gr_subject="Private")
        private = Board.objects.create(
            group=group, bo_table="private", bo_subject="Hidden board",
            bo_list_level=10, bo_read_level=10,
        )
        post = Post.objects.create(
            board=private, wr_subject="Private post", wr_content="Private body", wr_num=-1,
            wr_datetime=timezone.now(), wr_last=timezone.now(),
        )
        # Explicitly select the private board to make it the first panel for an administrator.
        from gnu_jango.config.models import Config

        Config.objects.update_or_create(name="cf_home_boards", defaults={"value": private.bo_table})
        admin = get_user_model().objects.create_superuser(username="bootstrap-admin", email="admin@example.test", password="unused")
        admin_client = APIClient()
        admin_client.force_authenticate(admin)
        admin_panels = self.data("/api/v1/home", admin_client)["boardPanels"]
        self.assertIn(post.pk, [row["wr_id"] for panel in admin_panels for row in panel["posts"]])
        guest = self.data("/api/v1/home")
        # The existing board directory exposes board names; post visibility still follows list access.
        self.assertEqual(guest["boardPanels"][0]["posts"], [])
        self.assertEqual(self.data("/api/v1/boards/private/posts"), [])

    def test_poll_vote_state_is_read_per_visitor_even_when_common_data_is_cached(self):
        poll = Poll.objects.create(po_subject="Choose")
        choice = PollChoice.objects.create(poll=poll, content="Yes")
        with patch.object(page_bootstrap, "_community_data", return_value={}) as build:
            before = self.data("/api/v1/home", REMOTE_ADDR="203.0.113.1")
            self.assertFalse(before["poll"]["has_voted"])
            PollVote.objects.create(poll=poll, choice=choice, ip="203.0.113.1")
            self.assertTrue(self.data("/api/v1/home", REMOTE_ADDR="203.0.113.1")["poll"]["has_voted"])
            self.assertFalse(self.data("/api/v1/home", REMOTE_ADDR="203.0.113.2")["poll"]["has_voted"])
            self.assertEqual(build.call_count, 1)

    def test_sample_add_remove_and_bulk_type_repair_invalidate_after_commit(self):
        self.assertFalse(self.data("/api/v1/shop/home")["products"]["type1"])
        with self.captureOnCommitCallbacks(execute=True):
            manifest = sample_data.create_sample_data()
        home = self.data("/api/v1/shop/home")
        self.assertTrue(home["products"]["type1"])
        ShopProduct.objects.filter(pk__in=manifest["products"]).update(it_type1="0", it_type2="0", it_type3="0", it_type4="0", it_type5="0")
        version = cache.get(page_bootstrap.BOOTSTRAP_VERSION_KEY)
        with self.captureOnCommitCallbacks(execute=True):
            sample_data.repair_sample_product_types()
        self.assertNotEqual(cache.get(page_bootstrap.BOOTSTRAP_VERSION_KEY), version)
        self.assertTrue(self.data("/api/v1/shop/home")["products"]["type1"])
        with self.captureOnCommitCallbacks(execute=True):
            sample_data.remove_sample_data()
        self.assertFalse(self.data("/api/v1/shop/home")["products"]["type1"])

    def test_sample_batch_uses_one_generation_write(self):
        with patch.object(cache, "set", wraps=cache.set) as write:
            with self.captureOnCommitCallbacks(execute=True):
                sample_data.create_sample_data()
        generation_writes = [call for call in write.call_args_list if call.args[0] == page_bootstrap.BOOTSTRAP_VERSION_KEY]
        self.assertEqual(len(generation_writes), 1)

    def test_rollback_does_not_invalidate_and_committed_change_does(self):
        manifest = sample_data.create_sample_data()
        product = ShopProduct.objects.get(pk=manifest["products"][0])
        self.data("/api/v1/shop/home")
        version = cache.get(page_bootstrap.BOOTSTRAP_VERSION_KEY)
        try:
            with self.captureOnCommitCallbacks(execute=True), transaction.atomic():
                product.it_name = "Rolled back"
                product.save(update_fields=["it_name"])
                raise ValueError("rollback")
        except ValueError:
            pass
        self.assertEqual(cache.get(page_bootstrap.BOOTSTRAP_VERSION_KEY), version)
        with self.captureOnCommitCallbacks(execute=True):
            product.it_name = "Committed name"
            product.save(update_fields=["it_name"])
        self.assertNotEqual(cache.get(page_bootstrap.BOOTSTRAP_VERSION_KEY), version)
        rows = [row for section in self.data("/api/v1/shop/home")["products"].values() for row in section]
        self.assertTrue(any(row["it_name"] == "Committed name" for row in rows))

    def test_responses_are_private_and_static_sample_images_are_cdn_cacheable(self):
        for path in ("/api/v1/home", "/api/v1/shop/home"):
            self.assertEqual(self.client.get(path)["Cache-Control"], "no-store, private")
        self.client.cookies["sessionid"] = "unknown-guest-session"
        image = self.client.get("/sample-data/product-01.webp")
        self.assertEqual(image.status_code, 200)
        self.assertIn("s-maxage=86400", image["Cache-Control"])
        self.assertNotIn("Cookie", image.get("Vary", ""))
        self.assertFalse(image.cookies)
        for path in ("/sw.js", "/manifest.json"):
            self.assertNotIn("immutable", self.client.get(path).get("Cache-Control", ""))
