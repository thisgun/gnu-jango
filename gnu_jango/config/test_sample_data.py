"""Admin sample data: what it creates, what it removes and what it leaves alone."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gnu_jango.api.v1_shop import category_tree_products
from gnu_jango.bbs.models import Board, Comment, Group, Post
from gnu_jango.config import sample_data
from gnu_jango.config.models import Config
from gnu_jango.shop.models import ShopCategory, ShopProduct

SAMPLE_POST_COUNT = sum(len(board["posts"]) for board in sample_data.BOARD_CONTENT.values())


def public_board(group, table, subject):
    return Board.objects.create(
        group=group, bo_table=table, bo_subject=subject, bo_skin="basic", bo_mobile_skin="basic",
        bo_list_level=1, bo_read_level=1,
    )


class SampleDataTests(TestCase):
    def test_create_then_remove_leaves_nothing_behind(self):
        boards_before = set(Board.objects.values_list("bo_table", flat=True))
        groups_before = set(Group.objects.values_list("gr_id", flat=True))

        manifest = sample_data.create_sample_data()
        counts = sample_data.managed_counts(manifest)
        self.assertEqual(counts["posts"], SAMPLE_POST_COUNT)
        self.assertEqual(counts["products"], len(sample_data.PRODUCTS))
        self.assertEqual(counts["faqs"], len(sample_data.FAQS))

        result = sample_data.remove_sample_data()

        self.assertEqual(result["retained"], 0)
        self.assertEqual(result["deleted"], sum(counts.values()))
        self.assertFalse(Config.objects.filter(name=sample_data.MANIFEST_NAME).exists())
        self.assertEqual(set(Board.objects.values_list("bo_table", flat=True)), boards_before)
        self.assertEqual(set(Group.objects.values_list("gr_id", flat=True)), groups_before)
        self.assertFalse(Post.objects.filter(pk__in=manifest["posts"]).exists())
        self.assertFalse(ShopProduct.objects.filter(pk__in=manifest["products"]).exists())
        self.assertFalse(ShopCategory.objects.filter(pk__in=manifest["categories"]).exists())

    def test_a_second_batch_is_refused_until_the_first_is_removed(self):
        sample_data.create_sample_data()

        with self.assertRaises(sample_data.SampleDataError):
            sample_data.create_sample_data()

        sample_data.remove_sample_data()
        sample_data.create_sample_data()

    def test_a_post_that_gained_a_real_comment_is_kept(self):
        manifest = sample_data.create_sample_data()
        sample_comment_posts = set(Comment.objects.filter(pk__in=manifest["comments"]).values_list("post_id", flat=True))
        post = Post.objects.filter(pk__in=manifest["posts"]).exclude(pk__in=sample_comment_posts).first()
        now = timezone.now()
        real = Comment.objects.create(
            board=post.board, post=post, wr_content="실제 댓글", wr_name="회원", wr_datetime=now, wr_last=now,
        )

        result = sample_data.remove_sample_data()

        self.assertTrue(Comment.objects.filter(pk=real.pk).exists())
        self.assertEqual(list(Post.objects.filter(pk__in=manifest["posts"]).values_list("pk", flat=True)), [post.pk])
        self.assertIn(post.pk, result["manifest"]["posts"])
        self.assertGreater(result["retained"], 0)
        post.refresh_from_db()
        self.assertEqual(post.wr_comment, 1)

    def test_boards_with_korean_table_names_are_reused_by_subject(self):
        # Sites converted from Gnuboard often name tables in Korean, e.g. /bbs/자유게시판.
        self.assertFalse(Board.objects.filter(bo_table="free").exists())
        community = Group.objects.create(gr_id="community", gr_subject="커뮤니티")
        free = public_board(community, "자유게시판", "자유게시판")
        now = timezone.now()
        real = Post.objects.create(
            board=free, wr_num=-1, wr_subject="실제 글", wr_content="본문", wr_name="회원", wr_datetime=now, wr_last=now,
        )

        manifest = sample_data.create_sample_data()

        self.assertFalse(Board.objects.filter(bo_table="free").exists())
        self.assertEqual(Post.objects.filter(board=free).count(), len(sample_data.BOARD_CONTENT["free"]["posts"]) + 1)
        self.assertNotIn(free.pk, manifest["boards"])
        self.assertIn(free.pk, manifest["boards_used"])

        sample_data.remove_sample_data()

        self.assertEqual(list(Post.objects.filter(board=free).values_list("pk", flat=True)), [real.pk])
        free.refresh_from_db()
        self.assertEqual(free.bo_count_write, 1)

    def test_no_sample_group_is_left_when_every_board_is_reused(self):
        community = Group.objects.create(gr_id="community", gr_subject="커뮤니티")
        for definition in sample_data.BOARD_CONTENT.values():
            public_board(community, f"ko-{definition['subject']}", definition["subject"])

        manifest = sample_data.create_sample_data()

        self.assertEqual(manifest["boards"], [])
        self.assertEqual(manifest["groups"], [])
        self.assertFalse(Group.objects.filter(gr_id="sample").exists())

    def test_a_board_in_a_members_only_group_is_not_used(self):
        members = Group.objects.create(gr_id="members", gr_subject="회원 전용", gr_use_access=1)
        locked = public_board(members, "자유게시판", "자유게시판")

        sample_data.create_sample_data()

        self.assertFalse(Post.objects.filter(board=locked).exists())

    def test_a_private_board_with_the_same_subject_is_not_used(self):
        community = Group.objects.create(gr_id="community", gr_subject="커뮤니티")
        private = public_board(community, "자유게시판", "자유게시판")
        Board.objects.filter(pk=private.pk).update(bo_read_level=2)

        sample_data.create_sample_data()

        self.assertFalse(Post.objects.filter(board=private).exists())
        self.assertTrue(Board.objects.filter(bo_table="free").exists())

    def test_the_sample_category_takes_a_free_two_character_root_code(self):
        # Product listings match categories by ca_id prefix, so a longer code could land inside a real one.
        real = ShopCategory.objects.create(ca_id="10", ca_name="실제 분류", ca_use=True)

        manifest = sample_data.create_sample_data()

        category = ShopCategory.objects.get(pk=manifest["categories"][0])
        self.assertEqual(len(category.ca_id), 2)
        self.assertNotEqual(category.ca_id, real.ca_id)
        self.assertFalse(category_tree_products(real.ca_id).filter(pk__in=manifest["products"]).exists())
        self.assertEqual(category_tree_products(category.ca_id).count(), len(sample_data.PRODUCTS))

    def test_the_root_code_avoids_existing_codes_in_any_case_and_short_prefixes(self):
        # The search starts at "z0"; prefix matching ignores case on SQLite and most MySQL collations.
        for ca_id in ("Z0", "z101", "y"):
            ShopCategory.objects.create(ca_id=ca_id, ca_name=ca_id, ca_use=True)

        code = sample_data._free_root_category_id()

        self.assertEqual(code, "z2")
        ShopCategory.objects.create(ca_id="z", ca_name="z", ca_use=True)
        code = sample_data._free_root_category_id()
        self.assertEqual(code, "x0")


class SampleDataAdminViewTests(TestCase):
    def setUp(self):
        self.url = reverse("admin-sample-data")
        self.superuser = get_user_model().objects.create_superuser(username="root", email="root@example.test", password="pw")

    def test_staff_who_are_not_superusers_are_refused(self):
        staff = get_user_model().objects.create_user(username="staff", email="staff@example.test", password="pw", is_staff=True)
        self.client.force_login(staff)

        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {"action": "add"}).status_code, 403)
        self.assertFalse(Config.objects.filter(name=sample_data.MANIFEST_NAME).exists())

    def test_superuser_adds_and_removes_with_confirmation(self):
        self.client.force_login(self.superuser)
        self.assertEqual(self.client.get(self.url).status_code, 200)

        self.assertRedirects(self.client.post(self.url, {"action": "add"}), self.url)
        self.assertEqual(Post.objects.count(), SAMPLE_POST_COUNT)

        self.client.post(self.url, {"action": "delete", "confirmation": "아니오"})
        self.assertEqual(Post.objects.count(), SAMPLE_POST_COUNT)

        self.client.post(self.url, {"action": "delete", "confirmation": "삭제"})
        self.assertEqual(Post.objects.count(), 0)
        self.assertFalse(Config.objects.filter(name=sample_data.MANIFEST_NAME).exists())
