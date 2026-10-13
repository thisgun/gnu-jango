from django.test import TestCase
from django.utils import timezone

from gnu_jango.bbs.models import Board, Group, Post
from gnu_jango.shop.models import ShopCategory, ShopProduct


class DynamicThemeFallbackTests(TestCase):
    def setUp(self):
        group = Group.objects.create(gr_id="runtime", gr_subject="Runtime records")
        self.board = Board.objects.create(
            group=group,
            bo_subject="Runtime board",
            bo_table="runtime-created-board",
            bo_skin="basic",
            bo_mobile_skin="basic",
        )
        self.post = Post.objects.create(
            board=self.board,
            wr_subject="Created after static export",
            wr_content="This post was not present when the theme was exported.",
            wr_name="runtime-test",
            wr_slug="created-after-static-export",
            wr_datetime=timezone.now(),
        )
        category = ShopCategory.objects.create(ca_id="runtime", ca_name="Runtime")
        self.product = ShopProduct.objects.create(
            it_id="runtime-created-product",
            category=category,
            it_name="Created after static export",
            it_price=12345,
        )

    def test_post_created_after_export_resolves_through_theme_fallback_and_api(self):
        page = self.client.get(f"/bbs/{self.board.bo_table}/{self.post.pk}")
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page["Content-Type"].startswith("text/html"))

        canonical_page = self.client.get(
            f"/boards/{self.board.bo_table}/{self.post.pk}",
            follow=True,
        )
        self.assertEqual(canonical_page.status_code, 200)

        detail = self.client.get(f"/api/v1/posts/{self.board.bo_table}/{self.post.pk}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["data"]["wr_subject"], self.post.wr_subject)

    def test_product_created_after_export_resolves_through_theme_fallback_and_api(self):
        page = self.client.get(f"/shop/{self.product.it_id}")
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page["Content-Type"].startswith("text/html"))

        canonical_page = self.client.get(
            f"/shop/products/{self.product.it_id}",
            follow=True,
        )
        self.assertEqual(canonical_page.status_code, 200)

        detail = self.client.get(f"/api/v1/shop/products/{self.product.it_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["data"]["it_name"], self.product.it_name)
