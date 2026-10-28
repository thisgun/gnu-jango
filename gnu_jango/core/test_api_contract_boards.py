"""OpenAPI contract tests for the board read endpoints (gnu_jango/api/contracts/boards.py).

Each test calls a real /api/v1 route and validates the whole JSON against the generated schema,
covering the shapes that add or blank keys: notices, replies, secret posts and comments, guest and
member authors, attachments, anonymous and signed-in viewers, a later page and list excerpts.
"""

import io
import shutil
import tempfile

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.bbs.models import Board, Comment, Group, Post, Post_file, Post_scrap
from gnu_jango.core.contract_testing import ContractAssertions
from gnu_jango.users.models import Profile

BOARDS = "/api/v1/boards"
BOARD = "/api/v1/boards/{bo_table}"
BOARD_POSTS = "/api/v1/boards/{bo_table}/posts"
POST = "/api/v1/posts/{bo_table}/{wr_id}"

CONTRACT_OPERATIONS = {
    ("GET", BOARDS),
    ("GET", BOARD),
    ("GET", BOARD_POSTS),
    ("GET", POST),
}


def png_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (4, 3), "red").save(buffer, format="PNG")
    return buffer.getvalue()


class BoardContractTestCase(ContractAssertions, TestCase):
    @classmethod
    def make_user(cls, username, level, **fields):
        user = get_user_model().objects.create(username=username, email=f"{username}@example.test", **fields)
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.user_level = level
        profile.save()
        return user

    @classmethod
    def make_post(cls, user=None, **fields):
        now = timezone.now()
        number = fields.pop("wr_num", -(Post.objects.count() + 1))
        defaults = {
            "board": cls.board,
            "wr_num": number,
            "wr_subject": f"Subject {abs(number)}",
            "wr_content": f"<p>Body {abs(number)}</p>",
            "wr_slug": f"subject-{abs(number)}",
            "user": user,
            "wr_name": user.username if user else "guest",
            "wr_ip": "203.0.113.7",
            "wr_datetime": now,
            "wr_last": now,
        }
        defaults.update(fields)
        post = Post.objects.create(**defaults)
        if not post.wr_parent:
            post.wr_parent = post.pk
            post.save(update_fields=["wr_parent"])
        return post

    @classmethod
    def make_comment(cls, post, user=None, **fields):
        defaults = {
            "board": post.board,
            "post": post,
            "user": user,
            "wr_content": "A comment",
            "wr_name": user.username if user else "guest",
            "wr_ip": "203.0.113.8",
            "wr_datetime": timezone.now(),
        }
        defaults.update(fields)
        return Comment.objects.create(**defaults)

    @classmethod
    def setUpTestData(cls):
        cls.member = cls.make_user("contract-member", 2)
        cls.reader = cls.make_user("contract-reader", 2)
        cls.group = Group.objects.create(gr_id="contract-group", gr_subject="Contract", gr_admin="")
        cls.board = Board.objects.create(
            group=cls.group,
            bo_subject="Contract board",
            bo_table="contract-board",
            bo_skin="basic",
            bo_mobile_skin="basic",
            bo_list_level=1,
            bo_read_level=1,
            bo_write_level=1,
            bo_reply_level=1,
            bo_comment_level=1,
            bo_upload_level=1,
            bo_download_level=1,
            bo_use_good=True,
            bo_use_ip_view=True,
            bo_use_category=True,
            bo_category_list="news|talk",
            bo_page_rows=2,
            bo_hot=1,
        )
        cls.member_post = cls.make_post(cls.member, ca_name="news", wr_hit=5, wr_email="member@example.test")
        cls.guest_post = cls.make_post(None, wr_homepage="https://example.test")
        cls.secret_post = cls.make_post(cls.member, wr_option="secret")
        cls.reply = cls.make_post(
            cls.reader,
            wr_num=cls.member_post.wr_num,
            wr_reply="A",
            wr_parent=cls.member_post.pk,
            wr_subject="Re: member post",
        )
        cls.notice = cls.make_post(cls.member, is_notice=1, wr_subject="Notice")
        Board.objects.filter(pk=cls.board.pk).update(bo_notice=str(cls.notice.pk))

    def setUp(self):
        cache.clear()

    def get(self, url, user=None, **params):
        headers = {}
        if user is not None:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {RefreshToken.for_user(user).access_token}"
        return self.client.get(url, params, **headers)


class BoardCatalogueContractTests(BoardContractTestCase):
    def test_board_list_matches_its_contract(self):
        Group.objects.filter(pk=self.group.pk).update(gr_admin=None)
        empty_group = Group.objects.create(gr_id="contract-empty", gr_subject="Empty", gr_admin="admin")
        Board.objects.create(group=empty_group, bo_subject="Empty", bo_table="contract-empty", bo_skin="basic")

        response = self.get(BOARDS)

        rows = {row["bo_table"]: row for row in response.json()["data"]}
        self.assertIsNone(rows["contract-board"]["gr_admin"])
        self.assertEqual(rows["contract-empty"]["post_count"], 0)
        self.assertMatchesContract(response, BOARDS)

    def test_board_detail_matches_its_contract(self):
        response = self.get(f"{BOARDS}/{self.board.bo_table}")

        self.assertEqual(response.json()["data"]["bo_use_good"], 1)
        self.assertMatchesContract(response, BOARD)


class BoardPostsContractTests(BoardContractTestCase):
    def posts_url(self):
        return f"{BOARDS}/{self.board.bo_table}/posts"

    def test_first_page_with_notice_guest_secret_and_reply_rows_matches_its_contract(self):
        response = self.get(self.posts_url(), per_page=10)

        body = response.json()
        self.assertEqual(body["meta"]["total_notice_count"], 1)
        rows = body["data"]
        self.assertTrue(rows[0]["is_notice"])
        self.assertIn(True, [row["is_secret"] for row in rows])
        self.assertIn("", [row["mb_id"] for row in rows])
        self.assertIn("A", [row["wr_reply"] for row in rows])
        self.assertMatchesContract(response, BOARD_POSTS)

    def test_page_two_for_a_signed_in_member_matches_its_contract(self):
        Post_scrap.objects.create(user=self.member, board=self.board, post=self.guest_post, ms_datetime=timezone.now())

        response = self.get(self.posts_url(), user=self.member, page=2, per_page=1)

        body = response.json()
        self.assertEqual(body["meta"]["current_page"], 2)
        self.assertEqual(body["meta"]["notice_count"], 0)
        self.assertEqual(len(body["data"]), 1)
        self.assertMatchesContract(response, BOARD_POSTS)

    def test_a_page_past_the_end_has_no_rows_and_matches_its_contract(self):
        response = self.get(self.posts_url(), page=99)

        self.assertEqual(response.json()["data"], [])
        self.assertMatchesContract(response, BOARD_POSTS)

    def test_an_empty_board_has_null_from_and_to_and_matches_its_contract(self):
        Board.objects.create(group=self.group, bo_subject="Empty", bo_table="contract-empty", bo_skin="basic")

        response = self.get(f"{BOARDS}/contract-empty/posts")

        self.assertIsNone(response.json()["meta"]["from"])
        self.assertMatchesContract(response, BOARD_POSTS)

    def test_excerpts_match_their_contract(self):
        response = self.get(self.posts_url(), user=self.member, per_page=10, **{"with": "excerpt"})

        rows = response.json()["data"]
        self.assertIn("Body", next(row for row in rows if not row["is_secret"])["wr_excerpt"])
        self.assertNotIn("wr_excerpt", next(row for row in rows if row["is_secret"]))
        self.assertMatchesContract(response, BOARD_POSTS)


class PostDetailContractTests(BoardContractTestCase):
    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp(prefix="contract-media-")
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        media = override_settings(MEDIA_ROOT=self.media_root)
        media.enable()
        self.addCleanup(media.disable)

    def post_url(self, post):
        return f"/api/v1/posts/{self.board.bo_table}/{post.pk}"

    def attach_files(self, post):
        picture = Post_file(board=self.board, post=post, bf_no=0, bf_source="pic.png", bf_type=3)
        picture.bf_file.save("pic.png", ContentFile(png_bytes()), save=False)
        picture.save()
        Post_file.objects.create(
            board=self.board,
            post=post,
            bf_no=1,
            bf_source="old.zip",
            bf_fileurl="/data/file/contract-board/missing.zip",
            bf_datetime=timezone.now(),
        )

    def test_member_post_with_files_and_comments_read_by_a_guest_matches_its_contract(self):
        self.attach_files(self.member_post)
        self.make_comment(self.member_post, self.reader)
        self.make_comment(self.member_post, None, wr_option="secret", wr_content="hidden")

        response = self.get(self.post_url(self.member_post))

        data = response.json()["data"]
        self.assertEqual(len(data["files"]), 2)
        self.assertEqual(len(data["comments"]), 2)
        self.assertEqual(data["wr_email"], "")
        self.assertFalse(data["can_manage"])
        self.assertMatchesContract(response, POST)

    def test_first_post_read_by_another_member_has_a_null_prev_post_and_matches_its_contract(self):
        response = self.get(self.post_url(self.member_post), user=self.reader)

        data = response.json()["data"]
        self.assertIsNone(data["prev_post"])
        self.assertIsNotNone(data["next_post"])
        self.assertMatchesContract(response, POST)

    def test_guest_post_matches_its_contract(self):
        response = self.get(self.post_url(self.guest_post))

        data = response.json()["data"]
        self.assertEqual(data["member"], {"mb_id": "", "mb_nick": "", "mb_icon_path": ""})
        self.assertMatchesContract(response, POST)

    def test_secret_post_read_by_its_scrapping_author_matches_its_contract(self):
        Post_scrap.objects.create(user=self.member, board=self.board, post=self.secret_post, ms_datetime=timezone.now())

        response = self.get(self.post_url(self.secret_post), user=self.member)

        data = response.json()["data"]
        self.assertTrue(data["is_secret"])
        self.assertTrue(data["can_manage"])
        self.assertTrue(data["is_scrapped"])
        self.assertMatchesContract(response, POST)

    def test_last_post_has_a_null_next_post_and_matches_its_contract(self):
        response = self.get(self.post_url(self.notice))

        self.assertIsNone(response.json()["data"]["next_post"])
        self.assertMatchesContract(response, POST)
