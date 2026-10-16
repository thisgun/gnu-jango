"""Broader behaviour tests for the board API (gnu_jango/api/v1_board.py, gnu_jango/api/access.py).

Everything goes through the public /api/v1 routes. Rules are checked against the Gnuboard5
originals (bbs/write_update.php, delete.php, delete_comment.php, write_comment_update.php, good.php,
board.php, search.php). Where the port deviates from Gnuboard5, the correct behaviour is pinned
with @unittest.expectedFailure and a comment naming the defect and the PHP reference, so the
decorator can be dropped once the code is fixed.
"""

import io
import shutil
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from gnu_jango.api import v1_board
from gnu_jango.api.v1_auth import CAPTCHA_SESSION_KEY
from gnu_jango.bbs.models import Board, Comment, Group, Post, Post_file, Post_scrap
from gnu_jango.users.models import Profile
from gnu_jango.utils.lib import get_encrypt_string

API = "/api/v1"


def zip_upload(name="doc.zip", payload=b"hello"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("a.txt", payload)
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="application/zip")


def png_upload(name="pic.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (4, 3), "red").save(buffer, format="PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), content_type="image/png")


class BoardApiTestCase(TestCase):
    """Shared users, boards and request helpers."""

    @classmethod
    def make_user(cls, username, level, **fields):
        user = get_user_model().objects.create(username=username, email=f"{username}@example.test", **fields)
        profile, _ = Profile.objects.get_or_create(user=user)
        profile.user_level = level
        profile.save()
        return user

    @classmethod
    def make_board(cls, table, **fields):
        defaults = {
            "group": cls.group,
            "bo_subject": table,
            "bo_table": table,
            "bo_skin": "basic",
            "bo_mobile_skin": "basic",
            "bo_list_level": 1,
            "bo_use_search": True,
            "bo_read_level": 1,
            "bo_write_level": 1,
            "bo_reply_level": 1,
            "bo_comment_level": 1,
            "bo_upload_level": 1,
            "bo_download_level": 1,
        }
        defaults.update(fields)
        return Board.objects.create(**defaults)

    @classmethod
    def make_post(cls, board, user=None, **fields):
        now = timezone.now()
        number = fields.pop("wr_num", -(Post.objects.count() + 1))
        defaults = {
            "board": board,
            "wr_num": number,
            "wr_subject": f"Subject {abs(number)}",
            "wr_content": f"Body {abs(number)}",
            "user": user,
            "wr_name": user.username if user else "guest",
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
            "wr_datetime": timezone.now(),
        }
        defaults.update(fields)
        return Comment.objects.create(**defaults)

    @classmethod
    def setUpTestData(cls):
        cls.owner = cls.make_user("more-owner", 2)
        cls.other = cls.make_user("more-other", 2)
        cls.rookie = cls.make_user("more-rookie", 1)
        cls.boss = cls.make_user("more-boss", 10, is_superuser=True)
        cls.board_admin = cls.make_user("more-boardadmin", 5)
        cls.group_admin = cls.make_user("more-groupadmin", 6)
        cls.group = Group.objects.create(gr_id="more-group", gr_subject="More", gr_admin=cls.group_admin.username)
        cls.board = cls.make_board("more-board", bo_admin=cls.board_admin.username, bo_use_good=True, bo_use_nogood=True)
        cls.post = cls.make_post(cls.board, cls.owner)

    def api(self, user=None):
        client = APIClient()
        if user is not None:
            token = RefreshToken.for_user(user).access_token
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        return client

    def posts_url(self, board=None):
        return f"{API}/boards/{(board or self.board).bo_table}/posts"

    def post_url(self, post=None, board=None):
        post = post or self.post
        return f"{API}/posts/{(board or post.board).bo_table}/{post.pk}"

    def comment_url(self, item, board=None):
        return f"{API}/comments/{(board or item.board).bo_table}/{item.pk}"

    def write(self, user=None, board=None, **fields):
        payload = {"wr_subject": "New subject", "wr_content": "New body", **fields}
        return self.api(user).post(self.posts_url(board), payload, format="json")

    def comment(self, user=None, post=None, **fields):
        post = post or self.post
        payload = {"wr_content": "Nice", **fields}
        return self.api(user).post(self.comment_url(post), payload, format="json")


class BoardCatalogueTests(BoardApiTestCase):
    def test_the_board_list_counts_posts_and_comments_per_board(self):
        self.make_comment(self.post, self.other)
        self.make_comment(self.post, self.owner)
        empty = self.make_board("more-empty")

        rows = {row["bo_table"]: row for row in self.api().get(f"{API}/boards").json()["data"]}

        self.assertEqual((rows["more-board"]["post_count"], rows["more-board"]["comment_count"]), (1, 2))
        self.assertEqual((rows[empty.bo_table]["post_count"], rows[empty.bo_table]["comment_count"]), (0, 0))
        self.assertEqual(rows["more-board"]["gr_admin"], self.group_admin.username)

    def test_the_board_list_can_be_narrowed_to_a_group_by_id_or_number(self):
        other_group = Group.objects.create(gr_id="more-elsewhere", gr_subject="Elsewhere")
        elsewhere = self.make_board("more-elsewhere-board", group=other_group)

        by_id = self.api().get(f"{API}/boards", {"group": "more-elsewhere"}).json()["data"]
        by_number = self.api().get(f"{API}/boards", {"group": str(other_group.pk)}).json()["data"]
        nothing = self.api().get(f"{API}/boards", {"group": "no-such-group"}).json()["data"]

        self.assertEqual([row["bo_table"] for row in by_id], [elsewhere.bo_table])
        self.assertEqual([row["bo_table"] for row in by_number], [elsewhere.bo_table])
        self.assertEqual(nothing, [])

    def test_an_oversized_group_id_does_not_overflow_the_database_integer(self):
        response = self.api().get(f"{API}/boards", {"group": "9" * 100})

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"], [])

    def test_a_board_is_found_by_table_number_or_legacy_alias(self):
        free = self.make_board("free")

        by_table = self.api().get(f"{API}/boards/more-board").json()["data"]
        by_number = self.api().get(f"{API}/boards/{self.board.pk}").json()["data"]
        by_alias = self.api().get(f"{API}/boards/cm_free").json()["data"]

        self.assertEqual(by_table["id"], self.board.pk)
        self.assertEqual(by_number["bo_table"], "more-board")
        self.assertEqual(by_alias["id"], free.pk)

    def test_an_unknown_board_is_a_404_everywhere(self):
        for response in (
            self.api().get(f"{API}/boards/nope"),
            self.api().get(f"{API}/boards/nope/posts"),
            self.api(self.owner).post(f"{API}/boards/nope/posts", {"wr_subject": "x", "wr_content": "y"}, format="json"),
            self.api().get(f"{API}/posts/nope/1"),
            self.api().get(f"{API}/posts/nope/seo/some-slug"),
            self.api().get(f"{API}/boards/nope/1/files"),
        ):
            self.assertEqual(response.status_code, 404, response.content[:200])


class BoardListTests(BoardApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.list_board = cls.make_board("more-list", bo_page_rows=3, bo_use_category=True, bo_category_list="Q&A|News")
        cls.alpha = cls.make_post(cls.list_board, cls.owner, wr_subject="Alpha topic", wr_content="red apple", ca_name="News")
        cls.beta = cls.make_post(cls.list_board, cls.other, wr_subject="Beta topic", wr_content="green pear", ca_name="Q&A")
        cls.gamma = cls.make_post(cls.list_board, cls.owner, wr_subject="Gamma", wr_content="topic body", ca_name="News", wr_name="Zed")

    def listing(self, user=None, **query):
        response = self.api(user).get(self.posts_url(self.list_board), query)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    def subjects(self, body):
        return [row["wr_subject"] for row in body["data"]]

    def test_the_list_lists_newest_first_and_pages_by_the_boards_row_count(self):
        body = self.listing()

        self.assertEqual(self.subjects(body), ["Gamma", "Beta topic", "Alpha topic"])
        self.assertEqual(body["meta"]["per_page"], 3)
        self.assertEqual(body["meta"]["total"], 3)

    def test_per_page_and_page_slice_the_list(self):
        body = self.listing(per_page=2, page=2)

        self.assertEqual(self.subjects(body), ["Alpha topic"])
        self.assertEqual(body["meta"]["last_page"], 2)
        self.assertEqual(body["meta"]["current_page"], 2)
        self.assertEqual(body["meta"]["from"], 3)

    def test_per_page_is_capped_and_never_below_one(self):
        self.assertEqual(self.listing(per_page=100000)["meta"]["per_page"], 100)
        self.assertEqual(self.listing(per_page=0)["meta"]["per_page"], 1)
        self.assertEqual(self.listing(per_page=-5)["meta"]["per_page"], 1)
        self.assertEqual(self.listing(page_size=2)["meta"]["per_page"], 2)

    def test_garbage_paging_values_fall_back_to_the_defaults(self):
        body = self.listing(per_page="many", page="first")

        self.assertEqual(body["meta"]["per_page"], 3)
        self.assertEqual(body["meta"]["current_page"], 1)
        self.assertEqual(len(body["data"]), 3)

    def test_a_page_past_the_end_is_empty(self):
        self.assertEqual(self.listing(page=99)["data"], [])

    def test_a_page_offset_beyond_the_database_integer_range_is_empty(self):
        body = self.listing(page="9000000000000000000")

        self.assertEqual(body["data"], [])

    def test_an_empty_board_lists_nothing_with_a_single_page(self):
        empty = self.make_board("more-nothing")
        body = self.api().get(self.posts_url(empty)).json()

        self.assertEqual(body["data"], [])
        self.assertEqual(body["meta"]["total"], 0)
        self.assertEqual(body["meta"]["last_page"], 1)
        self.assertIsNone(body["meta"]["from"])

    def test_notices_lead_the_list_in_the_boards_notice_order(self):
        Post.objects.filter(pk__in=[self.alpha.pk, self.beta.pk]).update(is_notice=1)
        Board.objects.filter(pk=self.list_board.pk).update(bo_notice=f"{self.beta.pk},{self.alpha.pk}")

        body = self.listing()

        self.assertEqual(self.subjects(body), ["Beta topic", "Alpha topic", "Gamma"])
        self.assertEqual([row["is_notice"] for row in body["data"]], [True, True, False])
        self.assertEqual(body["meta"]["total_notice_count"], 2)

    def test_malformed_notice_ids_are_ignored(self):
        Post.objects.filter(pk=self.alpha.pk).update(is_notice=1)
        Board.objects.filter(pk=self.list_board.pk).update(bo_notice=f"{self.alpha.pk},²,{'9' * 100}")

        body = self.listing()

        self.assertEqual(self.subjects(body), ["Alpha topic", "Gamma", "Beta topic"])

    def test_a_search_or_category_filter_hides_the_notices(self):
        Post.objects.filter(pk=self.alpha.pk).update(is_notice=1)

        self.assertEqual(self.subjects(self.listing(stx="topic")), ["Gamma", "Beta topic"])
        self.assertEqual(self.subjects(self.listing(sca="News")), ["Gamma"])

    def test_a_category_filter_keeps_only_that_category(self):
        self.assertEqual(self.subjects(self.listing(sca="Q&A")), ["Beta topic"])
        self.assertEqual(self.subjects(self.listing(sca="Nothing")), [])

    def test_the_search_covers_subject_content_name_and_member_id(self):
        self.assertEqual(self.subjects(self.listing(stx="apple")), ["Alpha topic"])
        self.assertEqual(self.subjects(self.listing(stx="apple", sfl="wr_subject")), [])
        self.assertEqual(self.subjects(self.listing(stx="Zed", sfl="wr_name")), ["Gamma"])
        self.assertEqual(self.subjects(self.listing(stx="more-other", sfl="mb_id")), ["Beta topic"])
        self.assertEqual(self.subjects(self.listing(stx="News", sfl="ca_name")), ["Gamma", "Alpha topic"])
        self.assertEqual(self.subjects(self.listing(stx="Alpha", sfl="wr_subject||wr_name")), ["Alpha topic"])

    def test_an_unknown_search_field_falls_back_to_subject_and_content(self):
        self.assertEqual(self.subjects(self.listing(stx="pear", sfl="wr_password")), ["Beta topic"])

    def test_a_search_term_is_not_run_as_sql_or_a_pattern(self):
        for term in ("'; DROP TABLE bbs_post; --", "%", "_", "\\", "‮\U0001f4a5", "a" * 5000):
            self.assertEqual(self.subjects(self.listing(stx=term)), [], term[:20])
        self.assertEqual(Post.objects.filter(board=self.list_board).count(), 3)

    def test_a_secret_posts_body_and_author_details_are_withheld_in_the_list(self):
        Post.objects.filter(pk=self.beta.pk).update(wr_option="secret", wr_homepage="https://secret.example/", wr_link1="https://link.example/")

        row = next(r for r in self.listing(self.owner)["data"] if r["wr_subject"] == "Beta topic")

        self.assertTrue(row["is_secret"])
        self.assertEqual(row["wr_content"], "")
        self.assertEqual(row["wr_homepage"], "")
        self.assertEqual(row["wr_link1"], "")
        self.assertEqual(row["thumbnail"], "")

    def test_a_member_below_the_list_level_sees_only_their_own_posts(self):
        Board.objects.filter(pk=self.list_board.pk).update(bo_list_level=5)

        self.assertEqual(self.subjects(self.listing(self.owner)), ["Gamma", "Alpha topic"])
        self.assertEqual(self.subjects(self.listing(self.board_admin)), ["Gamma", "Beta topic", "Alpha topic"])
        self.assertEqual(self.listing()["data"], [])
        self.assertEqual(len(self.listing(self.boss)["data"]), 3)

    def test_the_list_marks_hot_posts_and_what_the_viewer_may_manage(self):
        Board.objects.filter(pk=self.list_board.pk).update(bo_hot=5)
        Post.objects.filter(pk=self.alpha.pk).update(wr_hit=5)
        Post_scrap.objects.create(user=self.owner, board=self.list_board, post=self.alpha, ms_datetime=timezone.now())

        rows = {row["wr_subject"]: row for row in self.listing(self.owner)["data"]}

        self.assertTrue(rows["Alpha topic"]["is_hot"])
        self.assertFalse(rows["Beta topic"]["is_hot"])
        self.assertTrue(rows["Alpha topic"]["is_scrapped"])
        self.assertFalse(rows["Beta topic"]["is_scrapped"])
        self.assertTrue(rows["Alpha topic"]["can_manage"])
        self.assertFalse(rows["Beta topic"]["can_manage"])

    def test_the_search_does_not_reveal_secret_content_of_other_members(self):
        Post.objects.filter(pk=self.beta.pk).update(wr_option="secret", wr_content="the hidden pear plan")

        body = self.api(self.other).get(f"{API}/search", {"q": "hidden pear"}).content.decode()
        guest = self.api().get(f"{API}/search", {"q": "hidden pear"}).content.decode()

        self.assertIn("Beta topic", body)  # the author finds their own post
        self.assertNotIn("Beta topic", guest)
        self.assertNotIn("hidden pear plan", guest)

    def test_the_search_skips_posts_of_boards_the_visitor_may_not_read(self):
        Board.objects.filter(pk=self.list_board.pk).update(bo_read_level=5)

        guest = self.api().get(f"{API}/search", {"q": "topic"}).json()["data"]
        admin = self.api(self.boss).get(f"{API}/search", {"q": "topic"}).json()["data"]

        self.assertEqual(guest["total_count"], 0)
        self.assertEqual(admin["total_count"], 3)

    # Gnuboard5 rule (search.php:25): only boards with bo_use_search = 1 and bo_list_level <= the
    # member's level are searched.
    def test_the_search_leaves_out_boards_excluded_from_the_site_search(self):
        Board.objects.filter(pk=self.list_board.pk).update(bo_use_search=False)

        data = self.api().get(f"{API}/search", {"q": "topic"}).json()["data"]

        self.assertNotIn("more-list", [group["bo_table"] for group in data["results"]])

    def test_the_search_leaves_out_boards_the_visitor_may_not_list(self):
        Board.objects.filter(pk=self.list_board.pk).update(bo_use_search=True, bo_list_level=5, bo_read_level=1)

        data = self.api().get(f"{API}/search", {"q": "topic"}).json()["data"]

        self.assertNotIn("more-list", [group["bo_table"] for group in data["results"]])


class PostWriteTests(BoardApiTestCase):
    def test_the_server_decides_the_posts_owner_name_and_counters(self):
        response = self.api(self.owner).post(
            self.posts_url(),
            {
                "wr_subject": "Honest", "wr_content": "Body", "wr_name": "Spoofed", "wr_hit": 99, "wr_good": 50,
                "wr_num": 7, "wr_parent": 1, "is_notice": 1, "notice": 1, "mb_id": "more-other", "wr_email": "x@x.test",
                "wr_ip": "203.0.113.9", "wr_datetime": "2001-01-01T00:00:00Z", "legacy_wr_id": 5,
            },
            format="json",
            REMOTE_ADDR="198.51.100.24",
        )

        self.assertEqual(response.status_code, 201, response.content[:300])
        post = Post.objects.get(pk=response.json()["data"]["id"])
        self.assertEqual(post.user, self.owner)
        self.assertEqual((post.wr_hit, post.wr_good, post.is_notice), (0, 0, 0))
        self.assertEqual(post.wr_parent, post.pk)
        self.assertEqual(post.wr_ip, "198.51.100.24")
        self.assertEqual(post.wr_email, self.owner.email)
        self.assertNotEqual(post.wr_name, "Spoofed")
        self.assertIsNone(post.legacy_wr_id)
        self.assertGreater(post.wr_datetime.year, 2020)
        self.assertEqual(Board.objects.get(pk=self.board.pk).bo_count_write, Post.objects.filter(board=self.board).count())

    def test_a_visitor_below_the_write_level_is_refused_but_a_board_admin_is_not(self):
        board = self.make_board("more-high-write", bo_write_level=3, bo_admin=self.board_admin.username)

        self.assertEqual(self.write(None, board).status_code, 403)
        self.assertEqual(self.write(self.rookie, board).status_code, 403)
        self.assertEqual(self.write(self.owner, board).status_code, 403)
        self.assertEqual(self.write(self.board_admin, board).status_code, 201)
        self.assertEqual(Post.objects.filter(board=board).count(), 1)

    def test_a_blank_subject_or_content_is_refused(self):
        for fields in ({"wr_subject": "   "}, {"wr_content": ""}, {"wr_content": " \n\t"}, {"wr_subject": None}):
            response = self.write(self.owner, **fields)
            self.assertEqual(response.status_code, 422, f"{fields}: {response.content[:200]}")
        self.assertEqual(self.api(self.owner).post(self.posts_url(), {}, format="json").status_code, 422)
        self.assertEqual(self.api(self.owner).post(self.posts_url(), ["not", "an", "object"], format="json").status_code, 422)

    def test_a_visitor_must_give_a_name_and_a_password_of_sane_length(self):
        cases = (
            ({}, "wr_name"),
            ({"wr_name": "  "}, "wr_name"),
            ({"wr_name": "n" * 256, "wr_password": "pw"}, "wr_name"),
            ({"wr_name": "Guest"}, "wr_password"),
            ({"wr_name": "Guest", "wr_password": "p" * 129}, "wr_password"),
        )
        for fields, field in cases:
            response = self.write(None, **fields)
            self.assertEqual(response.status_code, 422, f"{fields}: {response.content[:200]}")
            self.assertIn(field, response.json()["errors"])
        self.assertFalse(Post.objects.filter(board=self.board).exclude(pk=self.post.pk).exists())

    def test_a_visitors_post_stores_their_name_and_a_hashed_password(self):
        response = self.write(None, wr_name="  Visitor  ", wr_password="visitor-pass")

        self.assertEqual(response.status_code, 201, response.content[:300])
        post = Post.objects.get(pk=response.json()["data"]["id"])
        self.assertIsNone(post.user)
        self.assertEqual(post.wr_name, "Visitor")
        self.assertTrue(post.wr_password)
        self.assertNotIn("visitor-pass", post.wr_password)
        self.assertNotIn(post.wr_password, response.content.decode())

    def test_a_visitor_needs_the_anti_spam_code_where_the_board_asks_for_it(self):
        board = self.make_board("more-captcha", bo_use_captcha=True)
        guest = {"wr_name": "Visitor", "wr_password": "pw"}
        client = self.api()
        session = client.session
        session[CAPTCHA_SESSION_KEY] = "234567"
        session.save()

        missing = client.post(self.posts_url(board), {"wr_subject": "S", "wr_content": "C", **guest}, format="json")
        wrong = client.post(self.posts_url(board), {"wr_subject": "S", "wr_content": "C", "captcha_key": "000000", **guest}, format="json")
        member = self.write(self.owner, board)

        self.assertEqual(missing.status_code, 422)
        self.assertEqual(missing.json()["code"], "captcha_invalid")
        self.assertEqual(wrong.status_code, 422)
        self.assertEqual(member.status_code, 201)

    def test_html_and_secret_options_are_stored_as_gnuboard_does(self):
        board = self.make_board("more-options", bo_use_secret=True)
        cases = (({}, "both"), ({"html": "1"}, "html1"), ({"html": "2"}, "html2"), ({"html": "bogus"}, "both"), ({"secret": "secret"}, "secret"))
        for fields, expected in cases:
            response = self.write(self.owner, board, **fields)
            self.assertEqual(response.status_code, 201, f"{fields}: {response.content[:200]}")
            self.assertEqual(response.json()["data"]["wr_option"], expected, fields)

    def test_a_member_cannot_publish_a_notice(self):
        # Gnuboard5 answers "관리자만 공지할 수 있습니다." (write_update.php:189); the API never creates notices.
        response = self.write(self.owner, notice="1", is_notice=True)

        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.json()["data"]["is_notice"])
        self.assertEqual(Board.objects.get(pk=self.board.pk).bo_notice or "", "")

    def test_the_category_a_member_picks_is_stored_when_it_is_in_the_list(self):
        board = self.make_board("more-category-ok", bo_use_category=True, bo_category_list="News|Q&A")

        response = self.write(self.owner, board, ca_name=" News ")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["ca_name"], "News")

    # Gnuboard5 rule (write_update.php:14-28): with bo_use_category on, a category from
    # bo_category_list is required; a board without categories drops it.
    def test_a_category_outside_the_boards_list_is_refused(self):
        board = self.make_board("more-category-bad", bo_use_category=True, bo_category_list="News|Q&A")

        response = self.write(self.owner, board, ca_name="Invented")

        self.assertGreaterEqual(response.status_code, 400)
        self.assertFalse(Post.objects.filter(board=board).exists())

    def test_a_category_is_required_when_the_board_uses_categories(self):
        board = self.make_board("more-category-req", bo_use_category=True, bo_category_list="News|Q&A")

        response = self.write(self.owner, board)

        self.assertGreaterEqual(response.status_code, 400)

    def test_a_category_is_dropped_on_a_board_without_categories(self):
        # write_update.php:26-28 sets ca_name = '' when bo_use_category is off.
        response = self.write(self.owner, self.board, ca_name="Injected")

        self.assertEqual(Post.objects.get(pk=response.json()["data"]["id"]).ca_name, "")

    # Gnuboard5 rule (write_update.php:54-65): links are trim(strip_tags(substr(..., 0, 1000))).
    def test_links_are_stripped_of_tags_and_capped_at_a_thousand_characters(self):
        response = self.write(self.owner, wr_link1="<script>alert(1)</script>https://ok.example/", wr_link2="https://x.example/" + "a" * 2000)

        post = Post.objects.get(pk=response.json()["data"]["id"])
        self.assertNotIn("<", post.wr_link1)
        self.assertLessEqual(len(post.wr_link2), 1000)

    # Gnuboard5 rule (write_update.php:29-37): the subject is cut to 255 characters.
    def test_an_overlong_subject_is_cut_or_refused(self):
        response = self.write(self.owner, wr_subject="s" * 400)

        if response.status_code == 201:
            self.assertLessEqual(len(Post.objects.get(pk=response.json()["data"]["id"]).wr_subject), 255)
        else:
            self.assertEqual(response.status_code, 422)

    # A JSON number is taken as text; a list or object is a 422, never a 500.
    def test_non_text_fields_are_a_client_error_not_a_server_error(self):
        client = self.api(self.owner)
        client.raise_request_exception = False

        for fields in ({"wr_subject": 123}, {"wr_subject": ["a"]}, {"wr_link1": 5}, {"ca_name": ["x"]}):
            response = client.post(self.posts_url(), {"wr_subject": "S", "wr_content": "C", **fields}, format="json")
            self.assertLess(response.status_code, 500, f"{fields}: {response.status_code}")

    def test_a_form_encoded_post_works_like_a_json_post(self):
        response = self.api(self.owner).post(self.posts_url(), {"wr_subject": "Form", "wr_content": "Posted as a form"})

        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertEqual(response.json()["data"]["wr_subject"], "Form")

    def test_unicode_and_markup_text_survives_a_round_trip(self):
        subject = "한글 제목 \U0001f600 <b>bold</b> ' \" %s"
        response = self.write(self.owner, wr_subject=subject, wr_content="내용\n‮x")

        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertEqual(Post.objects.get(pk=response.json()["data"]["id"]).wr_subject, subject)


class PostReplyTests(BoardApiTestCase):
    def reply(self, user, parent=None, board=None, **fields):
        parent = parent or self.post
        return self.write(user, board or parent.board, reply_to=parent.pk, **fields)

    def test_a_member_below_the_reply_level_cannot_reply_but_the_board_admin_can(self):
        board = self.make_board("more-reply-level", bo_reply_level=3, bo_admin=self.board_admin.username)
        parent = self.make_post(board, self.owner)

        self.assertEqual(self.reply(self.other, parent).status_code, 403)
        self.assertEqual(self.reply(None, parent, wr_name="g", wr_password="p").status_code, 403)
        self.assertEqual(self.reply(self.board_admin, parent).status_code, 201)

    def test_a_reply_to_a_missing_post_or_another_boards_post_is_a_404(self):
        elsewhere = self.make_board("more-reply-elsewhere")
        foreign = self.make_post(elsewhere, self.owner)

        missing = self.write(self.owner, reply_to=999999)
        crossed = self.write(self.owner, self.board, reply_to=foreign.pk)

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(crossed.status_code, 404)
        self.assertEqual(Post.objects.filter(board=self.board).count(), 1)

    def test_a_notice_cannot_be_answered(self):
        Post.objects.filter(pk=self.post.pk).update(is_notice=1)

        response = self.reply(self.other)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "reply_to_notice_forbidden")

    def test_a_reply_joins_the_thread_of_its_parent(self):
        response = self.reply(self.other)

        self.assertEqual(response.status_code, 201, response.content[:300])
        reply = Post.objects.get(pk=response.json()["data"]["id"])
        self.assertEqual((reply.wr_num, reply.wr_parent), (self.post.wr_num, self.post.pk))
        self.assertNotEqual(reply.wr_reply, "")

    def test_a_reply_to_a_secret_post_stays_secret(self):
        board = self.make_board("more-reply-secret", bo_use_secret=True)
        parent = self.make_post(board, self.owner, wr_option="secret")

        response = self.reply(self.owner, parent)

        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertTrue(response.json()["data"]["is_secret"])

    def test_a_non_numeric_reply_target_is_treated_as_a_new_post(self):
        response = self.write(self.owner, reply_to="abc")

        self.assertEqual(response.status_code, 201)
        self.assertEqual(Post.objects.get(pk=response.json()["data"]["id"]).wr_reply, "")

    def test_reply_markers_run_out_after_twenty_six_siblings(self):
        board = self.make_board("more-reply-limit")
        parent = self.make_post(board, self.owner)
        for _ in range(26):
            self.assertEqual(self.reply(self.other, parent).status_code, 201)

        response = self.reply(self.other, parent)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "reply_limit_reached")

    # Gnuboard5 rule (board.php:84-95): the author of a secret thread's original post reads the
    # secret replies in it.
    def test_the_author_of_a_secret_thread_can_read_the_administrators_answer(self):
        board = self.make_board("more-secret-thread", bo_use_secret=True, bo_admin=self.board_admin.username)
        parent = self.make_post(board, self.owner, wr_option="secret")
        answer = self.reply(self.boss, parent, wr_subject="Answer", wr_content="Private answer")
        self.assertEqual(answer.status_code, 201, answer.content[:300])

        response = self.api(self.owner).get(self.post_url(Post.objects.get(pk=answer.json()["data"]["id"])))

        self.assertEqual(response.status_code, 200)
        self.assertIn("Private answer", response.content.decode())


class SecretPostAccessTests(BoardApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.secret_board = cls.make_board("more-secret", bo_use_secret=True, bo_admin=cls.board_admin.username)
        cls.secret = cls.make_post(cls.secret_board, cls.owner, wr_option="secret", wr_content="Classified text")

    def test_an_unlock_remembered_in_the_session_opens_a_secret_post(self):
        client = self.api()
        session = client.session
        session[f"ss_secret_{self.secret_board.pk}_{self.secret.wr_num}"] = True
        session.save()

        response = client.get(self.post_url(self.secret))

        self.assertEqual(response.status_code, 200)
        self.assertIn("Classified text", response.content.decode())

    def test_malformed_or_empty_unlock_keys_open_nothing(self):
        client = self.api()
        session = client.session
        session[f"ss_secret_{self.secret_board.pk}_{self.secret.wr_num}"] = False
        session["ss_secret_oops"] = True
        session["ss_secret_a_b"] = True
        session["ss_secret_1_2_3"] = True
        session["unrelated"] = True
        session.save()

        response = client.get(self.post_url(self.secret))

        self.assertEqual(response.status_code, 404)

    def test_an_unlock_for_another_thread_does_not_open_this_one(self):
        client = self.api()
        session = client.session
        session[f"ss_secret_{self.secret_board.pk}_{self.secret.wr_num - 50}"] = True
        session.save()

        self.assertEqual(client.get(self.post_url(self.secret)).status_code, 404)

    def test_a_secret_post_does_not_appear_as_the_previous_or_next_post(self):
        self.make_post(self.secret_board, self.other, wr_subject="Before")
        middle = self.make_post(self.secret_board, self.other, wr_subject="Middle")
        self.make_post(self.secret_board, self.other, wr_subject="After", wr_option="secret")

        data = self.api(self.rookie).get(self.post_url(middle)).json()["data"]
        owner_view = self.api(self.other).get(self.post_url(middle)).json()["data"]

        self.assertEqual(data["prev_post"]["wr_subject"], "Before")
        self.assertIsNone(data["next_post"])
        self.assertEqual(owner_view["next_post"]["wr_subject"], "After")

    # Gnuboard5 rule (board.php:78 `|| $is_admin`): the board or group administrator reads any secret
    # post of the board.
    def test_a_board_admin_can_read_a_members_secret_post(self):
        response = self.api(self.board_admin).get(self.post_url(self.secret))

        self.assertEqual(response.status_code, 200)

    def test_a_group_admin_can_read_a_members_secret_post(self):
        response = self.api(self.group_admin).get(self.post_url(self.secret))

        self.assertEqual(response.status_code, 200)

    # Gnuboard5 rule (write_update.php:705-712): writing a secret post stores ss_secret_<board>_<wr_num>
    # in the session, so the writer is not asked for the password again.
    def test_a_visitor_can_reopen_the_secret_post_they_just_wrote(self):
        client = self.api()
        created = client.post(
            self.posts_url(self.secret_board),
            {"wr_subject": "Mine", "wr_content": "Visitor secret", "secret": "secret", "wr_name": "Visitor", "wr_password": "pw"},
            format="json",
        )
        self.assertEqual(created.status_code, 201, created.content[:300])

        response = client.get(self.post_url(Post.objects.get(pk=created.json()["data"]["id"])))

        self.assertEqual(response.status_code, 200)


class PostDetailTests(BoardApiTestCase):
    def test_the_hit_counter_counts_once_per_browser_session(self):
        first = self.api()
        second = self.api()

        first.get(self.post_url())
        first.get(self.post_url())
        second.get(self.post_url())

        self.assertEqual(Post.objects.get(pk=self.post.pk).wr_hit, 2)

    def test_the_detail_shows_the_previous_and_next_readable_posts(self):
        board = self.make_board("more-nav")
        first = self.make_post(board, self.owner, wr_subject="First")
        middle = self.make_post(board, self.owner, wr_subject="Middle")
        last = self.make_post(board, self.owner, wr_subject="Last")

        data = self.api().get(self.post_url(middle)).json()["data"]
        edge = self.api().get(self.post_url(first)).json()["data"]

        self.assertEqual(data["prev_post"]["wr_subject"], "First")
        self.assertEqual(data["next_post"]["wr_subject"], "Last")
        self.assertIsNone(edge["prev_post"])
        self.assertEqual(self.api().get(self.post_url(last)).json()["data"]["prev_post"]["wr_id"], middle.pk)

    def test_the_detail_resolves_an_imported_posts_original_number(self):
        imported = self.make_post(self.board, self.owner, legacy_wr_id=900, wr_subject="Imported")

        response = self.api().get(f"{API}/posts/{self.board.bo_table}/900")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["wr_id"], 900)
        self.assertEqual(response.json()["data"]["id"], imported.pk)

    def test_the_detail_resolves_a_thread_root_by_its_parent_number(self):
        self.make_post(self.board, self.owner, wr_parent=777, wr_subject="Old root")

        response = self.api().get(f"{API}/posts/{self.board.bo_table}/777")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["data"]["wr_subject"], "Old root")

    def test_an_unknown_post_number_is_a_404(self):
        self.assertEqual(self.api().get(f"{API}/posts/{self.board.bo_table}/424242").status_code, 404)

    def test_the_post_is_found_by_its_slug_in_any_case_or_by_a_unique_prefix(self):
        post = self.make_post(self.board, self.owner, wr_subject="Hello Slug World")
        post.refresh_from_db()
        base = f"{API}/posts/{self.board.bo_table}/seo/"

        exact = self.api().get(base + post.wr_slug)
        upper = self.api().get(base + post.wr_slug.upper())
        prefix = self.api().get(base + post.wr_slug[:8])
        missing = self.api().get(base + "no-such-slug-at-all")

        self.assertEqual(exact.status_code, 200, exact.content[:200])
        self.assertEqual(exact.json()["data"]["id"], post.pk)
        self.assertEqual(upper.json()["data"]["id"], post.pk)
        self.assertEqual(prefix.json()["data"]["id"], post.pk)
        self.assertEqual(missing.status_code, 404)

    def test_a_unicode_slug_works_percent_encoded(self):
        post = self.make_post(self.board, self.owner, wr_subject="한글 제목입니다")
        post.refresh_from_db()

        response = self.api().get(f"{API}/posts/{self.board.bo_table}/seo/{quote(post.wr_slug)}")

        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertEqual(response.json()["data"]["id"], post.pk)

    def test_the_slug_lookup_cannot_reach_a_secret_post(self):
        post = self.make_post(self.board, self.owner, wr_subject="Secret slug topic", wr_option="secret")
        post.refresh_from_db()

        response = self.api(self.other).get(f"{API}/posts/{self.board.bo_table}/seo/{post.wr_slug}")

        self.assertEqual(response.status_code, 404)

    def test_the_detail_tells_the_viewer_what_they_may_manage(self):
        as_owner = self.api(self.owner).get(self.post_url()).json()["data"]
        as_group_admin = self.api(self.group_admin).get(self.post_url()).json()["data"]
        as_rookie = self.api(self.rookie).get(self.post_url()).json()["data"]
        as_guest = self.api().get(self.post_url()).json()["data"]

        self.assertEqual((as_owner["can_manage"], as_owner["admin_role"]), (True, ""))
        self.assertEqual((as_group_admin["can_manage"], as_group_admin["admin_role"]), (True, "group"))
        self.assertEqual((as_rookie["can_manage"], as_rookie["admin_role"]), (False, ""))
        self.assertEqual((as_guest["can_manage"], as_guest["is_scrapped"]), (False, False))

    def test_the_detail_flags_a_scrapped_post_for_the_member_who_scrapped_it(self):
        scrap = Post_scrap.objects.create(user=self.other, board=self.board, post=self.post, ms_datetime=timezone.now())

        mine = self.api(self.other).get(self.post_url()).json()["data"]
        theirs = self.api(self.owner).get(self.post_url()).json()["data"]

        self.assertEqual((mine["is_scrapped"], mine["scrap_id"]), (True, scrap.pk))
        self.assertEqual((theirs["is_scrapped"], theirs["scrap_id"]), (False, 0))

    def test_comments_of_a_reply_thread_are_grouped_under_their_parent(self):
        top = self.make_comment(self.post, self.owner, wr_content="Top", wr_comment=1, order_num=1)
        self.make_comment(self.post, self.other, wr_content="Second", wr_comment=2, order_num=2)
        self.make_comment(self.post, self.other, wr_content="Child", wr_comment=1, order_num=3, parent=top.pk, wr_comment_reply="A")

        comments = self.api().get(self.post_url()).json()["data"]["comments"]

        self.assertEqual([c["wr_content"] for c in comments], ["Top", "Child", "Second"])

    # Gnuboard5 rule (write_comment_update.php:155-160): a new comment takes the post's highest
    # wr_comment + 1 and comments list by wr_comment, wr_comment_reply, i.e. oldest first and after
    # imported comments.
    def test_new_comments_are_listed_oldest_first(self):
        self.assertEqual(self.comment(self.other, wr_content="first").status_code, 201)
        self.assertEqual(self.comment(self.owner, wr_content="second").status_code, 201)

        comments = self.api().get(self.post_url()).json()["data"]["comments"]

        self.assertEqual([c["wr_content"] for c in comments], ["first", "second"])

    def test_a_new_comment_is_listed_after_the_imported_ones(self):
        self.make_comment(self.post, self.owner, wr_content="imported", wr_comment=3, order_num=3)
        self.assertEqual(self.comment(self.other, wr_content="fresh").status_code, 201)

        comments = self.api().get(self.post_url()).json()["data"]["comments"]

        self.assertEqual([c["wr_content"] for c in comments], ["imported", "fresh"])


class PostEditAndDeleteTests(BoardApiTestCase):
    def edit(self, actor, post=None, **fields):
        payload = {"wr_subject": "Edited", "wr_content": "Edited body", **fields}
        return self.api(actor).patch(self.post_url(post), payload, format="json")

    def test_editing_needs_a_login_and_an_existing_post(self):
        self.assertEqual(self.edit(None).status_code, 401)
        self.assertEqual(self.api(self.owner).patch(f"{API}/posts/{self.board.bo_table}/99999", {"wr_subject": "x", "wr_content": "y"}, format="json").status_code, 404)

    def test_the_author_edits_text_and_links_but_not_ownership_or_counters(self):
        response = self.edit(self.owner, wr_link1="https://link.example/", wr_hit=500, user=self.other.pk, wr_num=5, is_notice=1, wr_good=9)

        self.assertEqual(response.status_code, 200, response.content[:300])
        post = Post.objects.get(pk=self.post.pk)
        self.assertEqual((post.wr_subject, post.wr_content, post.wr_link1), ("Edited", "Edited body", "https://link.example/"))
        self.assertEqual((post.user, post.wr_num, post.wr_hit, post.wr_good, post.is_notice), (self.owner, self.post.wr_num, 0, 0, 0))

    def test_an_edit_with_a_blank_subject_or_body_changes_nothing(self):
        self.assertEqual(self.edit(self.owner, wr_subject=" ").status_code, 422)
        self.assertEqual(self.edit(self.owner, wr_content="").status_code, 422)
        self.assertEqual(Post.objects.get(pk=self.post.pk).wr_subject, self.post.wr_subject)

    def test_a_super_administrator_may_edit_any_post(self):
        self.assertEqual(self.edit(self.boss).status_code, 200)
        self.assertEqual(Post.objects.get(pk=self.post.pk).user, self.owner)

    # Gnuboard5 rule (write.php:76-88): a post with replies can only be edited by an administrator.
    def test_a_post_with_replies_cannot_be_edited_by_its_author(self):
        self.make_post(self.board, self.other, wr_num=self.post.wr_num, wr_reply="A", wr_parent=self.post.pk)

        response = self.edit(self.owner)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(Post.objects.get(pk=self.post.pk).wr_subject, self.post.wr_subject)

    # Gnuboard5 rule (write.php:90-97): bo_count_modify or more comments by others block an edit
    # (administrators excepted).
    def test_a_post_with_enough_comments_by_others_cannot_be_edited(self):
        Board.objects.filter(pk=self.board.pk).update(bo_count_modify=1)
        self.make_comment(self.post, self.other)

        response = self.edit(self.owner)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Post.objects.get(pk=self.post.pk).wr_subject, self.post.wr_subject)

    # Gnuboard5 rule (delete.php:55-61): bo_count_delete or more comments by others block a delete
    # (administrators excepted).
    def test_a_post_with_enough_comments_by_others_cannot_be_deleted(self):
        Board.objects.filter(pk=self.board.pk).update(bo_count_delete=1)
        self.make_comment(self.post, self.other)

        response = self.api(self.owner).delete(self.post_url())

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Post.objects.filter(pk=self.post.pk).exists())

    # Gnuboard5 rule (delete.php:33-37): a visitor deletes their own guest post with its password.
    def test_a_visitor_deletes_their_own_post_with_its_password(self):
        post = self.make_post(self.board, None, wr_name="Visitor", wr_password=get_encrypt_string("visitor-pass"))

        response = self.api().delete(self.post_url(post), {"wr_password": "visitor-pass"}, format="json")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Post.objects.filter(pk=post.pk).exists())

    def test_guessing_a_guest_post_password_is_rate_limited(self):
        from django.core.cache import cache

        cache.clear()
        self.addCleanup(cache.clear)
        post = self.make_post(self.board, None, wr_name="Visitor", wr_password=get_encrypt_string("visitor-pass"))
        client = self.api()
        statuses = [client.delete(self.post_url(post), {"wr_password": f"guess{n}"}, format="json").status_code for n in range(11)]

        self.assertEqual(set(statuses[:10]), {403})
        self.assertEqual(statuses[10], 429)
        self.assertTrue(Post.objects.filter(pk=post.pk).exists())

    def test_deleting_needs_a_login_and_an_existing_post(self):
        self.assertEqual(self.api().delete(self.post_url()).status_code, 401)
        self.assertEqual(self.api(self.owner).delete(f"{API}/posts/{self.board.bo_table}/99999").status_code, 404)
        self.assertTrue(Post.objects.filter(pk=self.post.pk).exists())

    def test_deleting_a_post_removes_its_comments_and_refreshes_the_counters(self):
        self.make_comment(self.post, self.other)
        self.make_comment(self.post, self.owner)

        response = self.api(self.owner).delete(self.post_url())

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(response.json()["data"]["deleted_ids"], [self.post.pk])
        self.assertFalse(Comment.objects.filter(post_id=self.post.pk).exists())
        board = Board.objects.get(pk=self.board.pk)
        self.assertEqual((board.bo_count_write, board.bo_count_comment), (0, 0))

    def test_a_super_administrator_deletes_the_whole_thread(self):
        reply = self.make_post(self.board, self.other, wr_num=self.post.wr_num, wr_reply="A", wr_parent=self.post.pk)

        response = self.api(self.boss).delete(self.post_url())

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertCountEqual(response.json()["data"]["deleted_ids"], [self.post.pk, reply.pk])
        self.assertFalse(Post.objects.filter(board=self.board).exists())


class PostVoteTests(BoardApiTestCase):
    def vote(self, user, kind="good", post=None):
        post = post or self.post
        return self.api(user).post(f"{API}/posts/{post.board.bo_table}/{post.pk}/{kind}")

    def test_a_vote_adds_one_and_reports_both_counters(self):
        good = self.vote(self.other, "good")
        nogood = self.vote(self.rookie, "nogood")

        self.assertEqual(good.status_code, 200, good.content[:200])
        self.assertEqual(good.json()["data"], {"flag": "good", "wr_good": 1, "wr_nogood": 0})
        self.assertEqual(nogood.json()["data"], {"flag": "nogood", "wr_good": 1, "wr_nogood": 1})

    def test_votes_are_refused_where_the_board_turns_them_off(self):
        board = self.make_board("more-no-votes")
        post = self.make_post(board, self.owner)

        self.assertEqual(self.vote(self.other, "good", post).status_code, 403)
        self.assertEqual(self.vote(self.other, "nogood", post).status_code, 403)
        self.assertEqual(Post.objects.get(pk=post.pk).wr_good, 0)

    def test_an_unknown_vote_type_or_post_is_a_404(self):
        self.assertEqual(self.vote(self.other, "love").status_code, 404)
        self.assertEqual(self.api(self.other).post(f"{API}/posts/{self.board.bo_table}/99999/good").status_code, 404)

    def test_a_post_the_voter_cannot_read_cannot_be_voted_on(self):
        post = self.make_post(self.board, self.owner, wr_option="secret")

        self.assertEqual(self.vote(self.other, "good", post).status_code, 404)
        self.assertEqual(Post.objects.get(pk=post.pk).wr_good, 0)

    # Gnuboard5 rule (good.php:21-24, 45-48): only members vote, and never on their own post.
    def test_a_visitor_cannot_vote(self):
        response = self.vote(None, "good")

        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(Post.objects.get(pk=self.post.pk).wr_good, 0)

    def test_a_member_cannot_vote_on_their_own_post(self):
        response = self.vote(self.owner, "good")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(Post.objects.get(pk=self.post.pk).wr_good, 0)

    # Gnuboard5 rule (good.php:56-70): one vote per member and post, recorded in Post_good.
    def test_a_member_votes_once_per_post(self):
        self.assertEqual(self.vote(self.other, "good").status_code, 200)
        second = self.vote(self.other, "good")
        switched = self.vote(self.other, "nogood")

        self.assertEqual(second.status_code, 403)
        self.assertEqual(switched.status_code, 403)
        post = Post.objects.get(pk=self.post.pk)
        self.assertEqual((post.wr_good, post.wr_nogood), (1, 0))


class CommentWriteTests(BoardApiTestCase):
    def reply_to(self, parent, user=None, **fields):
        return self.comment(user or self.other, wr_content="Reply", comment_id=parent.pk, **fields)

    def test_a_comment_on_a_missing_post_or_another_boards_post_is_a_404(self):
        elsewhere = self.make_board("more-comment-elsewhere")
        foreign = self.make_post(elsewhere, self.owner)

        missing = self.api(self.other).post(f"{API}/comments/{self.board.bo_table}/99999", {"wr_content": "x"}, format="json")
        crossed = self.api(self.other).post(f"{API}/comments/{self.board.bo_table}/{foreign.pk}", {"wr_content": "x"}, format="json")

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(crossed.status_code, 404)
        self.assertFalse(Comment.objects.exists())

    def test_the_board_admin_may_comment_below_the_comment_level(self):
        Board.objects.filter(pk=self.board.pk).update(bo_comment_level=9)

        self.assertEqual(self.comment(self.board_admin).status_code, 201)
        self.assertEqual(self.comment(self.other).status_code, 403)
        self.assertEqual(self.comment(None, wr_name="G", wr_password="p").status_code, 403)

    def test_a_visitors_comment_needs_a_name_and_password_and_stores_them_safely(self):
        client = self.api()
        session = client.session
        session[CAPTCHA_SESSION_KEY] = "345678"
        session.save()
        url = self.comment_url(self.post)
        no_name = client.post(url, {"wr_content": "Nice", "wr_password": "pw"}, format="json")
        no_password = client.post(url, {"wr_content": "Nice", "wr_name": "Guest"}, format="json")
        ok = client.post(
            url,
            {
                "wr_name": "Guest",
                "wr_password": "guest-pass",
                "wr_content": "  hi there  ",
                "captcha_key": "345678",
            },
            format="json",
        )

        self.assertEqual(no_name.status_code, 422)
        self.assertEqual(no_password.status_code, 422)
        self.assertEqual(ok.status_code, 201, ok.content[:300])
        comment = Comment.objects.get()
        self.assertEqual((comment.wr_name, comment.wr_content, comment.user), ("Guest", "hi there", None))
        self.assertNotIn("guest-pass", comment.wr_password)
        self.assertNotIn(comment.wr_password, ok.content.decode())

    def test_a_visitors_comment_always_needs_the_anti_spam_code(self):
        board = self.make_board("more-comment-captcha", bo_use_captcha=False)
        post = self.make_post(board, self.owner)
        client = self.api()
        session = client.session
        session[CAPTCHA_SESSION_KEY] = "345678"
        session.save()
        url = self.comment_url(post)
        guest = {"wr_content": "Hello", "wr_name": "Guest", "wr_password": "pw"}

        wrong = client.post(url, {**guest, "captcha_key": "111111"}, format="json")
        right = client.post(url, {**guest, "captcha_key": "345678"}, format="json")
        member = self.api(self.other).post(url, {"wr_content": "Member"}, format="json")

        self.assertEqual(wrong.status_code, 422)
        self.assertEqual(right.status_code, 201, right.content[:300])
        self.assertEqual(member.status_code, 201)
        self.assertNotIn(CAPTCHA_SESSION_KEY, client.session)

    def test_the_post_author_can_comment_on_their_own_secret_post(self):
        Post.objects.filter(pk=self.post.pk).update(wr_option="secret")

        self.assertEqual(self.comment(self.owner).status_code, 201)

    def test_commenting_updates_the_post_and_board_counters(self):
        self.comment(self.other)
        self.comment(self.owner)

        self.assertEqual(Post.objects.get(pk=self.post.pk).wr_comment, 2)
        self.assertEqual(Board.objects.get(pk=self.board.pk).bo_count_comment, 2)
        self.assertEqual(self.api().get(self.post_url()).json()["data"]["wr_comment"], 2)

    def test_a_reply_to_a_comment_of_another_post_is_refused(self):
        other_post = self.make_post(self.board, self.owner, wr_subject="Elsewhere")
        stray = self.make_comment(other_post, self.owner)

        response = self.reply_to(stray)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(Comment.objects.filter(post=self.post).count(), 0)

    def test_a_reply_to_a_missing_comment_is_a_404(self):
        response = self.comment(self.other, comment_id=424242)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "comment_not_found")

    def test_a_reply_joins_the_group_of_its_parent_comment(self):
        parent = self.comment(self.other).json()["data"]
        child = self.comment(self.owner, comment_id=parent["id"]).json()["data"]

        self.assertEqual(child["wr_comment"], parent["wr_comment"])
        self.assertNotEqual(child["wr_comment_reply"], "")

    # Gnuboard5 rule (write_comment_update.php:118-150): each reply to a comment takes the next free
    # letter, so siblings keep distinct markers.
    def test_sibling_replies_to_one_comment_get_distinct_markers(self):
        parent = self.comment(self.other).json()["data"]

        first = self.comment(self.owner, comment_id=parent["id"], wr_content="one").json()["data"]
        second = self.comment(self.rookie, comment_id=parent["id"], wr_content="two").json()["data"]

        self.assertNotEqual(first["wr_comment_reply"], second["wr_comment_reply"])

    # Gnuboard5 rule (write_comment_update.php:115-116): "답변은 5단계 까지만 가능합니다".
    def test_comment_replies_stop_at_five_levels(self):
        current = self.comment(self.other).json()["data"]
        for _ in range(5):
            response = self.comment(self.other, comment_id=current["id"])
            if response.status_code != 201:
                break
            current = response.json()["data"]

        too_deep = self.comment(self.other, comment_id=current["id"])

        self.assertEqual(too_deep.status_code, 422, too_deep.content[:200])

    def test_comment_text_is_kept_as_typed_apart_from_surrounding_blanks(self):
        response = self.comment(self.other, wr_content="  line one\nline two \U0001f600 <i>x</i>  ")

        self.assertEqual(Comment.objects.get(pk=response.json()["data"]["id"]).wr_content, "line one\nline two \U0001f600 <i>x</i>")

    def test_a_comment_body_that_is_not_text_is_not_a_server_error(self):
        client = self.api(self.other)
        client.raise_request_exception = False

        for body in ({"wr_content": 12345}, {"wr_content": ["a"]}, {"wr_content": None}, {}):
            response = client.post(self.comment_url(self.post), body, format="json")
            self.assertLess(response.status_code, 500, body)


class CommentDeleteTests(BoardApiTestCase):
    def delete(self, user, comment):
        return self.api(user).delete(self.comment_url(comment))

    def test_deleting_a_comment_needs_a_login_and_an_existing_comment(self):
        comment = self.make_comment(self.post, self.owner)

        self.assertEqual(self.delete(None, comment).status_code, 401)
        self.assertEqual(self.api(self.owner).delete(f"{API}/comments/{self.board.bo_table}/99999").status_code, 404)
        self.assertEqual(self.api(self.owner).delete(f"{API}/comments/nope/{comment.pk}").status_code, 404)
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())

    def test_the_author_a_board_admin_and_a_super_administrator_may_delete(self):
        for deleter in (self.other, self.board_admin, self.boss):
            comment = self.make_comment(self.post, self.other)

            response = self.delete(deleter, comment)

            self.assertEqual(response.status_code, 200, f"{deleter}: {response.content[:200]}")
            self.assertFalse(Comment.objects.filter(pk=comment.pk).exists())

    def test_deleting_a_comment_refreshes_the_counters(self):
        self.comment(self.other)
        kept = self.comment(self.owner).json()["data"]
        gone = Comment.objects.exclude(pk=kept["id"]).get()

        self.assertEqual(self.delete(self.other, gone).status_code, 200)

        self.assertEqual(Post.objects.get(pk=self.post.pk).wr_comment, 1)
        self.assertEqual(Board.objects.get(pk=self.board.pk).bo_count_comment, 1)

    def test_a_visitors_comment_is_deleted_by_an_administrator(self):
        comment = self.make_comment(self.post, None, wr_name="Visitor")

        self.assertEqual(self.delete(self.rookie, comment).status_code, 403)
        self.assertEqual(self.delete(self.board_admin, comment).status_code, 200)

    # Gnuboard5 rule (delete_comment.php:22-40): a board or group administrator cannot delete the
    # comment of a member above their level.
    def test_a_board_admin_cannot_delete_a_comment_of_a_higher_level_member(self):
        comment = self.make_comment(self.post, self.boss)

        response = self.delete(self.board_admin, comment)

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Comment.objects.filter(pk=comment.pk).exists())

    # Gnuboard5 rule (delete_comment.php:49-62): without administrator rights a comment with reply
    # comments cannot be deleted.
    def test_a_comment_with_replies_cannot_be_deleted_by_its_author(self):
        parent = self.make_comment(self.post, self.other, wr_comment=1, order_num=1)
        self.make_comment(self.post, self.owner, wr_comment=1, order_num=2, parent=parent.pk, wr_comment_reply="A")

        response = self.delete(self.other, parent)

        self.assertEqual(response.status_code, 409)
        self.assertTrue(Comment.objects.filter(pk=parent.pk).exists())


class PostFilesTests(BoardApiTestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="more-media-")
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        media = override_settings(MEDIA_ROOT=self.media_root)
        media.enable()
        self.addCleanup(media.disable)

    @property
    def url(self):
        return f"{API}/boards/{self.board.bo_table}/{self.post.pk}/files"

    def upload(self, user, files, order=None, post=None, url=None):
        data = {"files[]": files}
        if order is not None:
            data["order[]"] = order
        return self.api(user).post(url or self.url, data, format="multipart")

    def attach(self, name="old.zip", bf_no=0, post=None):
        post = post or self.post
        post_file = Post_file(board=post.board, post=post, bf_no=bf_no, bf_source=name)
        post_file.bf_file.save(name, ContentFile(b"PK\x03\x04data"), save=False)
        post_file.save()
        return post_file

    def test_uploading_stores_the_files_in_order_and_counts_them_on_the_post(self):
        response = self.upload(self.owner, [zip_upload("a.zip"), png_upload("b.png")])

        self.assertEqual(response.status_code, 200, response.content[:300])
        rows = response.json()["data"]
        self.assertEqual([row["bf_source"] for row in rows], ["a.zip", "b.png"])
        self.assertEqual([row["bf_no"] for row in rows], [0, 1])
        self.assertEqual(rows[0]["bf_type"], 0)
        self.assertGreater(rows[1]["bf_type"], 0)
        self.assertEqual(rows[0]["bf_url"], rows[0]["bf_download_url"])
        self.assertTrue(rows[0]["bf_download_url"].endswith("/files/0/download"))
        self.assertTrue(rows[1]["bf_url"].startswith("http"))

    def test_the_order_list_reorders_keeps_and_drops_attachments(self):
        self.upload(self.owner, [zip_upload("a.zip"), png_upload("b.png")])

        swapped = self.upload(self.owner, [], order=["1", "0"])
        kept = self.upload(self.owner, [], order=["0"])

        self.assertEqual([row["bf_source"] for row in swapped.json()["data"]], ["b.png", "a.zip"])
        self.assertEqual([row["bf_source"] for row in kept.json()["data"]], ["b.png"])
        self.assertEqual(Post_file.objects.filter(post=self.post).count(), 1)

    def test_malformed_order_payloads_are_rejected_without_a_server_error(self):
        self.attach("old.zip")
        client = self.api(self.owner)
        client.raise_request_exception = False

        for payload in ([], "text", 12, {"order[]": {"unexpected": "value"}}, {"order[]": True}):
            response = client.post(self.url, payload, format="json")
            self.assertEqual(response.status_code, 422, f"{payload!r}: {response.status_code}")
            self.assertEqual(Post_file.objects.filter(post=self.post).count(), 1)

    # Gnuboard5 rule (write_update.php): Post.wr_file holds the real attachment count after an upload.
    def test_the_posts_attachment_count_follows_the_uploads(self):
        self.upload(self.owner, [zip_upload("a.zip"), png_upload("b.png")])
        self.assertEqual(Post.objects.get(pk=self.post.pk).wr_file, 2)

        self.upload(self.owner, [], order=["0"])
        self.assertEqual(Post.objects.get(pk=self.post.pk).wr_file, 1)

    def test_new_files_can_be_placed_among_the_kept_ones(self):
        self.attach("old.zip")

        response = self.upload(self.owner, [zip_upload("new.zip")], order=["new:0", "0"])

        self.assertEqual([row["bf_source"] for row in response.json()["data"]], ["new.zip", "old.zip"])

    def test_only_the_posts_manager_with_the_upload_level_can_attach_files(self):
        Board.objects.filter(pk=self.board.pk).update(bo_upload_level=9)

        self.assertEqual(self.upload(None, [zip_upload()]).status_code, 401)
        self.assertEqual(self.upload(self.other, [zip_upload()]).status_code, 403)
        self.assertEqual(self.upload(self.owner, [zip_upload()]).status_code, 403)
        self.assertEqual(self.upload(self.board_admin, [zip_upload()]).status_code, 200)
        self.assertEqual(Post_file.objects.filter(post=self.post).count(), 1)

    def test_a_file_over_the_boards_size_limit_is_refused(self):
        Board.objects.filter(pk=self.board.pk).update(bo_upload_size=10)

        response = self.upload(self.owner, [zip_upload()])

        self.assertEqual(response.status_code, 422)
        self.assertFalse(Post_file.objects.exists())

    def test_too_many_entries_in_the_order_list_are_refused(self):
        Board.objects.filter(pk=self.board.pk).update(bo_upload_count=1)

        response = self.upload(self.owner, [zip_upload("a.zip"), zip_upload("b.zip")], order=["new:0", "new:1"])

        self.assertEqual(response.status_code, 422)
        self.assertFalse(Post_file.objects.exists())

    # Gnuboard5 rule (write_update.php:476-490): bo_upload_count limits the uploaded files themselves,
    # with or without an order list.
    def test_too_many_files_are_refused_even_without_an_order_list(self):
        Board.objects.filter(pk=self.board.pk).update(bo_upload_count=1)

        response = self.upload(self.owner, [zip_upload("a.zip"), zip_upload("b.zip"), zip_upload("c.zip")])

        self.assertEqual(response.status_code, 422)
        self.assertLessEqual(Post_file.objects.count(), 1)

    def test_a_bad_extension_or_fake_content_is_refused_and_nothing_is_kept(self):
        bad_ext = SimpleUploadedFile("run.exe", b"MZ\x90", content_type="application/octet-stream")
        fake_png = SimpleUploadedFile("pic.png", b"this is not a png", content_type="image/png")

        for bad in (bad_ext, fake_png):
            response = self.upload(self.owner, [zip_upload("fine.zip"), bad])
            self.assertEqual(response.status_code, 422, response.content[:300])
            self.assertEqual(response.json()["code"], "validation_error")
        self.assertFalse(Post_file.objects.exists())
        self.assertEqual(Post.objects.get(pk=self.post.pk).wr_file, 0)

    def test_the_file_list_is_public_for_a_readable_post_and_hidden_for_a_secret_one(self):
        self.attach("seen.zip")

        public = self.api().get(self.url)
        Post.objects.filter(pk=self.post.pk).update(wr_option="secret")
        hidden = self.api(self.other).get(self.url)

        self.assertEqual([row["bf_source"] for row in public.json()["data"]], ["seen.zip"])
        self.assertEqual(hidden.status_code, 404)

    def test_a_stored_files_checked_download_link_hides_the_media_path(self):
        self.attach("report.zip")

        row = self.api().get(self.url).json()["data"][0]

        self.assertEqual(row["bf_download_url"], f"/api/v1/boards/{self.board.bo_table}/{self.post.pk}/files/0/download")
        self.assertTrue(row["bf_download_available"])

    def test_a_file_missing_from_the_disk_is_not_offered(self):
        stored = self.attach("lost.zip")
        Post_file.objects.filter(pk=stored.pk).update(bf_file="file/1/not-on-disk.zip")

        row = self.api().get(self.url).json()["data"][0]

        self.assertFalse(row["bf_download_available"])

    def test_legacy_file_addresses_are_only_trusted_when_safe(self):
        legacy_dir = Path(self.media_root, "data", "file", self.board.bo_table)
        legacy_dir.mkdir(parents=True)
        (legacy_dir / "kept.zip").write_bytes(b"PK")
        cases = (
            ("/data/file/more-board/kept.zip", "", True),
            ("http://testserver/data/file/more-board/kept.zip", "", True),
            ("/data/file/more-board/gone.zip", "", False),
            ("/data/file/%2e%2e/%2e%2e/settings.py", "", False),
            ("/data/file/more-board/../../x.zip", "", False),
            ("https://cdn.example.test/a.zip", "", True),
            ("ftp://files.example.test/a.zip", "", False),
            ("javascript:alert(1)", "", False),
            ("/uploads/old.zip", "legacy_missing", False),
            ("/uploads/old.zip", "", True),
            ("", "", False),
        )
        for number, (address, storage, available) in enumerate(cases):
            Post_file.objects.create(
                board=self.board, post=self.post, bf_no=number, bf_source=f"f{number}", bf_fileurl=address,
                bf_storage=storage, bf_datetime=timezone.now(),
            )

        rows = self.api().get(self.url).json()["data"]

        for row, (address, _, available) in zip(rows, cases):
            self.assertEqual(row["bf_download_available"], available, address)

    def test_a_download_of_an_unknown_file_or_post_is_a_404(self):
        self.attach("one.zip")
        base = f"{API}/boards/{self.board.bo_table}"

        self.assertEqual(self.api().get(f"{base}/{self.post.pk}/files/7/download").status_code, 404)
        self.assertEqual(self.api().get(f"{base}/99999/files/0/download").status_code, 404)

    def test_a_download_from_a_secret_post_is_not_available_to_others(self):
        self.attach("one.zip")
        Post.objects.filter(pk=self.post.pk).update(wr_option="secret")

        response = self.api(self.other).get(f"{API}/boards/{self.board.bo_table}/{self.post.pk}/files/0/download")

        self.assertEqual(response.status_code, 404)


class EditorUploadTests(BoardApiTestCase):
    url = f"{API}/upload"

    def setUp(self):
        self.media_root = tempfile.mkdtemp(prefix="more-editor-")
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        media = override_settings(MEDIA_ROOT=self.media_root)
        media.enable()
        self.addCleanup(media.disable)

    def send(self, user, upload, field="file"):
        return self.api(user).post(self.url, {field: upload}, format="multipart")

    def test_an_editor_image_is_stored_under_a_random_name(self):
        response = self.send(self.owner, png_upload("holiday photo.png"))

        self.assertEqual(response.status_code, 201, response.content[:300])
        data = response.json()["data"]
        self.assertEqual(data["file_name"], "holiday_photo.png")
        self.assertEqual(data["uploaded_by"], self.owner.username)
        self.assertNotIn("holiday", data["url"])
        stored = list(Path(self.media_root, "uploads", "editor").iterdir())
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].suffix, ".png")

    def test_the_upload_field_may_be_called_upload_or_anything_else(self):
        self.assertEqual(self.send(self.owner, png_upload(), field="upload").status_code, 201)
        self.assertEqual(self.send(self.owner, png_upload(), field="whatever").status_code, 201)

    def test_an_upload_needs_a_login(self):
        self.assertEqual(self.send(None, png_upload()).status_code, 401)
        self.assertFalse(Path(self.media_root, "uploads").exists())

    def test_a_request_without_a_file_is_refused(self):
        response = self.api(self.owner).post(self.url, {"note": "no file"}, format="multipart")

        self.assertEqual(response.status_code, 422)

    def test_a_file_over_the_size_limit_is_refused(self):
        with mock.patch.object(v1_board, "MAX_EDITOR_UPLOAD_SIZE", 10):
            response = self.send(self.owner, png_upload())

        self.assertEqual(response.status_code, 422)
        self.assertFalse(Path(self.media_root, "uploads").exists())

    def test_script_and_markup_extensions_are_refused(self):
        for name in ("shell.php", "page.html", "image.svg", "run.exe", "noextension", "x.PHP", "x.png.php"):
            upload = SimpleUploadedFile(name, b"<?php echo 1;", content_type="text/plain")
            self.assertEqual(self.send(self.owner, upload).status_code, 422, name)
        self.assertFalse(Path(self.media_root, "uploads").exists())

    def test_an_upper_case_extension_is_accepted_and_stored_lower_case(self):
        response = self.send(self.owner, png_upload("PHOTO.PNG"))

        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["data"]["url"].endswith(".png"))

    def test_a_path_in_the_file_name_is_reduced_to_the_base_name(self):
        # A real ZIP signature: editor uploads now get the same content check as board attachments.
        upload = SimpleUploadedFile("..\\..\\evil.zip", b"PK\x03\x04" + b"\x00" * 26, content_type="application/zip")

        response = self.send(self.owner, upload)

        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertNotIn("..", response.json()["data"]["url"])
        self.assertEqual(len(list(Path(self.media_root, "uploads", "editor").iterdir())), 1)
