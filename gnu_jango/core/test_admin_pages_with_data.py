"""Admin pages that only render their preview columns when rows exist.

The earlier smoke check ran against empty tables, so a preview helper that called
``compact_text(..., limit=...)`` (an argument the helper did not accept) returned
HTTP 500 for the shop review and Q&A lists, the stock adjustment list and the
board activity report as soon as real rows were present.
"""

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase
from django.utils import timezone

from gnu_jango.bbs.models import Board, Comment, Group, Post
from gnu_jango.shop.models import ShopProduct, ShopQA, ShopReview, ShopStockAdjustment, ShopStockNotification
from gnu_jango.utils.admin_display import compact_text

LONG_TEXT = "".join(f"w{index:03d} " for index in range(120))


class CompactTextTests(SimpleTestCase):
    def test_joins_non_empty_values_and_falls_back_to_a_dash(self):
        self.assertEqual(compact_text("a", " ", None, "b"), "a b")
        self.assertEqual(compact_text("", None), "-")

    def test_limit_shortens_long_text_with_an_ellipsis(self):
        result = compact_text(LONG_TEXT, limit=40)
        self.assertLessEqual(len(result), 40)
        self.assertTrue(result.endswith("…"))
        self.assertTrue(result.startswith("w000"))

    def test_limit_leaves_short_text_and_the_no_limit_default_alone(self):
        self.assertEqual(compact_text("short", limit=40), "short")
        self.assertEqual(compact_text(LONG_TEXT).strip(), LONG_TEXT.strip())

    def test_limit_never_returns_more_characters_than_the_limit(self):
        for limit in (1, 2, 5):
            self.assertLessEqual(len(compact_text(LONG_TEXT, limit=limit)), limit)
        self.assertEqual(compact_text(LONG_TEXT, limit=0), "-")
        self.assertEqual(compact_text(LONG_TEXT, limit=1), "…")
        self.assertEqual(compact_text("abcde", limit=5), "abcde")

    def test_limit_applies_to_the_joined_text(self):
        result = compact_text("subject", LONG_TEXT, limit=30)
        self.assertLessEqual(len(result), 30)
        self.assertTrue(result.startswith("subject w000"))


class AdminRegistryTests(SimpleTestCase):
    def test_every_registered_admin_is_an_unfold_model_admin(self):
        # A plain Django ModelAdmin renders Unfold's bulk-action bar without the Alpine binding,
        # so its Run button never appears; every admin must therefore be an Unfold ModelAdmin.
        from django.contrib import admin
        from unfold.admin import ModelAdmin as UnfoldModelAdmin

        plain = sorted(
            model._meta.label
            for model, model_admin in admin.site._registry.items()
            if not isinstance(model_admin, UnfoldModelAdmin)
        )
        self.assertEqual(plain, [])

    def test_every_admin_action_form_binds_the_action_select(self):
        # Custom action forms must extend unfold.forms.ActionForm (x-model="action"), not Django's.
        from django.contrib import admin
        from unfold.forms import ActionForm as UnfoldActionForm

        wrong = sorted(
            model._meta.label
            for model, model_admin in admin.site._registry.items()
            if not issubclass(model_admin.action_form, UnfoldActionForm)
        )
        self.assertEqual(wrong, [])


class AdminPagesWithDataTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            username="admin-rows", email="admin-rows@example.test", password="password123"
        )
        now = timezone.now()
        ShopReview.objects.create(is_subject="Review", is_content=f"<p>{LONG_TEXT}</p>", is_name="buyer")
        ShopQA.objects.create(iq_subject="Question", iq_question=f"<p>{LONG_TEXT}</p>", iq_name="asker")
        ShopStockAdjustment.objects.create(
            it_id="ADJ001",
            scope="product",
            before_qty=5,
            delta=-2,
            after_qty=3,
            reason=LONG_TEXT[:255],
        )
        group = Group.objects.create(gr_id="rows-group", gr_subject="Rows group")
        board = Board.objects.create(group=group, bo_subject="Rows board", bo_table="rows-board", bo_skin="basic", bo_mobile_skin="basic")
        post = Post.objects.create(
            board=board, legacy_wr_id=1, wr_num=-1, wr_reply="", wr_parent=1,
            wr_subject="Rows post", wr_content="body", wr_name="writer", wr_datetime=now,
        )
        Comment.objects.create(board=board, post=post, wr_content=LONG_TEXT, wr_name="commenter", wr_datetime=now)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.admin)

    def assert_page_ok(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, path)
        return response.content.decode("utf-8")

    def test_shop_review_list_renders_a_shortened_preview(self):
        html = self.assert_page_ok("/admin/shop/shopreview/")
        self.assertIn("w000", html)
        self.assertNotIn("w119", html)

    def test_shop_qa_list_renders_a_shortened_preview(self):
        html = self.assert_page_ok("/admin/shop/shopqa/")
        self.assertIn("w000", html)
        self.assertNotIn("w119", html)

    def test_stock_adjustment_list_renders(self):
        self.assert_page_ok("/admin/shop/shopstockadjustment/")

    def test_product_list_bulk_action_select_is_bound_so_the_run_button_can_appear(self):
        # Unfold shows the "Run" button with x-show="action"; without x-model on the select
        # the button stays hidden and no bulk action can be executed on any device.
        ShopProduct.objects.create(it_id="ACT001", it_name="Bulk action product")
        html = self.assert_page_ok("/admin/shop/shopproduct/")
        self.assertIn('x-model="action"', html)

    def test_stock_notification_list_bulk_action_select_is_bound(self):
        ShopStockNotification.objects.create(it_id="ACT001", ss_hp="01012345678")
        html = self.assert_page_ok("/admin/shop/shopstocknotification/")
        self.assertIn('x-model="action"', html)

    def test_board_activity_report_renders_recent_comments(self):
        html = self.assert_page_ok("/admin/bbs/post/activity/")
        self.assertIn("Rows board", html)
