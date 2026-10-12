"""Board and member points follow Gnuboard5.

Writing, replying and commenting add the board's points; deleting takes them back; reading and
downloading charge the board's (usually negative) points once per post and are refused when the
balance cannot cover them; registration and the first login of the day add the site's points.
The v1 API used to show these settings without applying any of them.
"""

import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.bbs.models import Board, Group, Post, Post_file
from gnu_jango.config.models import Config
from gnu_jango.users.models import Profile, User_Point


class BoardPointTestBase(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.author = user_model.objects.create_user(username="pt-author", email="pt-author@example.test", password="password-1234")
        self.reader = user_model.objects.create_user(username="pt-reader", email="pt-reader@example.test", password="password-1234")
        for user in (self.author, self.reader):
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.user_level = 2
            profile.user_point = 100
            profile.save()
        group = Group.objects.create(gr_id="pt-group", gr_subject="Points")
        self.board = Board.objects.create(
            group=group, bo_subject="포인트", bo_table="pt-board", bo_skin="basic", bo_mobile_skin="basic",
            bo_write_level=1, bo_comment_level=1, bo_read_level=1, bo_download_level=1, bo_reply_level=1,
            bo_write_point=5, bo_comment_point=1, bo_read_point=-1, bo_download_point=-20,
        )
        self.author_client = self.client_for(self.author)
        self.reader_client = self.client_for(self.reader)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def balance(self, user):
        return Profile.objects.get(user=user).user_point

    def write(self, client=None, **extra):
        client = client or self.author_client
        response = client.post(
            f"/api/v1/boards/{self.board.bo_table}/posts",
            {"wr_subject": "Subject", "wr_content": "Body text", **extra},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content[:300])
        return response.json()["data"]["wr_id"]


class WritePointTests(BoardPointTestBase):
    def test_writing_a_post_adds_the_write_points(self):
        wr_id = self.write()
        self.assertEqual(self.balance(self.author), 105)
        row = User_Point.objects.get(user=self.author, po_rel_table="pt-board", po_rel_id=wr_id, po_rel_action="쓰기")
        self.assertEqual(row.po_point, 5)
        self.assertEqual(row.po_mb_point, 105)

    def test_a_reply_adds_the_comment_points(self):
        parent = self.write()
        self.write(client=self.reader_client, reply_to=parent)
        self.assertEqual(self.balance(self.reader), 101)

    def test_a_comment_adds_the_comment_points_and_deleting_it_takes_them_back(self):
        wr_id = self.write()
        response = self.reader_client.post(f"/api/v1/comments/{self.board.bo_table}/{wr_id}", {"wr_content": "Nice"}, format="json")
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertEqual(self.balance(self.reader), 101)
        comment_id = response.json()["data"]["id"]
        deleted = self.reader_client.delete(f"/api/v1/comments/{self.board.bo_table}/{comment_id}")
        self.assertEqual(deleted.status_code, 200, deleted.content[:300])
        self.assertEqual(self.balance(self.reader), 100)

    def test_deleting_a_post_takes_the_write_points_back(self):
        wr_id = self.write()
        response = self.author_client.delete(f"/api/v1/posts/{self.board.bo_table}/{wr_id}")
        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(self.balance(self.author), 100)
        self.assertFalse(User_Point.objects.filter(user=self.author, po_rel_action="쓰기").exists())

    def test_no_points_move_when_the_site_turns_points_off(self):
        Config.objects.update_or_create(name="cf_use_point", defaults={"value": "0"})
        self.write()
        self.assertEqual(self.balance(self.author), 100)


class ReadPointTests(BoardPointTestBase):
    def read(self, client, wr_id):
        return client.get(f"/api/v1/posts/{self.board.bo_table}/{wr_id}")

    def test_reading_someone_elses_post_charges_once(self):
        wr_id = self.write()
        self.assertEqual(self.read(self.reader_client, wr_id).status_code, 200)
        self.assertEqual(self.read(self.reader_client, wr_id).status_code, 200)
        self.assertEqual(self.balance(self.reader), 99)
        self.assertEqual(User_Point.objects.filter(user=self.reader, po_rel_action="읽기").count(), 1)

    def test_reading_your_own_post_is_free(self):
        wr_id = self.write()
        self.read(self.author_client, wr_id)
        self.assertEqual(self.balance(self.author), 105)

    def test_a_member_without_enough_points_cannot_read(self):
        wr_id = self.write()
        Profile.objects.filter(user=self.reader).update(user_point=0)
        response = self.read(self.reader_client, wr_id)
        self.assertEqual(response.status_code, 403, response.content[:300])
        self.assertNotIn("Body text", response.content.decode())
        self.assertIn("포인트", response.json()["message"])

    def test_a_visitor_cannot_read_where_reading_costs_points(self):
        wr_id = self.write()
        response = self.read(APIClient(), wr_id)
        self.assertEqual(response.status_code, 403, response.content[:300])
        self.assertNotIn("Body text", response.content.decode())

    def test_a_visitor_can_read_where_reading_is_free(self):
        Board.objects.filter(pk=self.board.pk).update(bo_read_point=0)
        wr_id = self.write()
        self.assertEqual(self.read(APIClient(), wr_id).status_code, 200)

    def test_a_member_who_already_paid_can_reread_with_an_empty_balance(self):
        wr_id = self.write()
        self.read(self.reader_client, wr_id)
        Profile.objects.filter(user=self.reader).update(user_point=0)
        self.assertEqual(self.read(self.reader_client, wr_id).status_code, 200)


class DownloadPointTests(BoardPointTestBase):
    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp(prefix="pt-media-")
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)
        media = override_settings(MEDIA_ROOT=self.media_root)
        media.enable()
        self.addCleanup(media.disable)
        self.wr_id = self.write()
        post = Post.objects.get(pk=self.wr_id)
        post_file = Post_file(board=self.board, post=post, bf_no=0, bf_source="hello.zip")
        post_file.bf_file.save("hello.zip", ContentFile(b"PK-test-bytes"), save=False)
        post_file.save()
        self.url = f"/api/v1/boards/{self.board.bo_table}/{self.wr_id}/files/0/download"

    def test_download_charges_once_counts_and_returns_the_file(self):
        first = self.reader_client.get(self.url)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(b"".join(first.streaming_content), b"PK-test-bytes")
        self.reader_client.get(self.url)
        self.assertEqual(self.balance(self.reader), 80)
        self.assertEqual(Post_file.objects.get(post_id=self.wr_id).bf_download, 1)

    def test_the_payload_points_downloads_at_the_checked_endpoint(self):
        data = self.reader_client.get(f"/api/v1/boards/{self.board.bo_table}/{self.wr_id}/files").json()["data"]
        self.assertTrue(data[0]["bf_download_url"].endswith(self.url), data[0]["bf_download_url"])

    def test_not_enough_points_refuses_the_download(self):
        Profile.objects.filter(user=self.reader).update(user_point=10)
        self.assertEqual(self.reader_client.get(self.url).status_code, 403)
        self.assertEqual(self.balance(self.reader), 10)

    def test_a_visitor_cannot_download_where_downloads_cost_points(self):
        self.assertIn(APIClient().get(self.url).status_code, (401, 403))

    def test_the_download_level_is_enforced(self):
        Board.objects.filter(pk=self.board.pk).update(bo_download_level=5, bo_download_point=0)
        self.assertEqual(self.reader_client.get(self.url).status_code, 403)

    def test_the_author_downloads_for_free(self):
        self.assertEqual(self.author_client.get(self.url).status_code, 200)
        self.assertEqual(self.balance(self.author), 105)


class MemberPointTests(TestCase):
    def setUp(self):
        Config.objects.update_or_create(name="cf_register_point", defaults={"value": "1000"})
        Config.objects.update_or_create(name="cf_login_point", defaults={"value": "100"})

    def test_registration_adds_the_welcome_points(self):
        with mock.patch("gnu_jango.api.v1_auth._captcha_matches", return_value=True):
            response = APIClient().post(
                "/api/v1/auth/register",
                {
                    "mb_id": "pt_newbie", "mb_password": "Str0ng-pass-99", "mb_password_re": "Str0ng-pass-99",
                    "mb_email": "pt-newbie@example.test", "mb_name": "New", "mb_nick": "newbie-pt",
                },
                format="json",
            )
        self.assertIn(response.status_code, (200, 201), response.content[:300])
        user = get_user_model().objects.get(username="pt_newbie")
        self.assertEqual(Profile.objects.get(user=user).user_point, 1000)
        self.assertTrue(User_Point.objects.filter(user=user, po_rel_table="@member", po_rel_action="회원가입").exists())

    def test_the_first_login_of_the_day_adds_points_once(self):
        get_user_model().objects.create_user(username="pt_login", email="pt-login@example.test", password="password-1234")
        for _ in range(2):
            response = APIClient().post("/api/v1/auth/login", {"mb_id": "pt_login", "password": "password-1234"}, format="json")
            self.assertEqual(response.status_code, 200, response.content[:300])
        user = get_user_model().objects.get(username="pt_login")
        self.assertEqual(Profile.objects.get(user=user).user_point, 100)
        self.assertEqual(User_Point.objects.filter(user=user, po_rel_table="@login").count(), 1)


class PointReviewEdgeTests(BoardPointTestBase):
    """Cases a review found: other read routes, direct file URLs, imported ids, costs, admins."""

    def test_reading_by_the_seo_address_charges_too(self):
        wr_id = self.write()
        Post.objects.filter(pk=wr_id).update(wr_slug="seo-points")
        response = self.reader_client.get(f"/api/v1/posts/{self.board.bo_table}/seo/seo-points")
        self.assertEqual(response.status_code, 200, response.content[:200])
        self.assertEqual(self.balance(self.reader), 99)
        self.assertEqual(APIClient().get(f"/api/v1/posts/{self.board.bo_table}/seo/seo-points").status_code, 403)

    def test_imported_posts_use_their_original_id_for_points(self):
        wr_id = self.write()
        Post.objects.filter(pk=wr_id).update(legacy_wr_id=777)
        User_Point.objects.create(
            user=self.reader, po_datetime=timezone.now(), po_content="imported read", po_point=-1,
            po_mb_point=99, po_rel_table=self.board.bo_table, po_rel_id=777, po_rel_action="읽기",
        )
        self.assertEqual(self.reader_client.get(f"/api/v1/posts/{self.board.bo_table}/777").status_code, 200)
        self.assertEqual(self.balance(self.reader), 100)

    def test_a_negative_write_cost_the_member_cannot_pay_is_refused(self):
        Board.objects.filter(pk=self.board.pk).update(bo_write_point=-500)
        response = self.author_client.post(f"/api/v1/boards/{self.board.bo_table}/posts", {"wr_subject": "S", "wr_content": "B"}, format="json")
        self.assertEqual(response.status_code, 403, response.content[:200])
        self.assertEqual(self.balance(self.author), 100)

    def test_a_board_admin_pays_read_points_but_not_download_points(self):
        wr_id = self.write()
        Board.objects.filter(pk=self.board.pk).update(bo_admin=self.reader.username)
        self.reader_client.get(f"/api/v1/posts/{self.board.bo_table}/{wr_id}")
        self.assertEqual(self.balance(self.reader), 99)


class DownloadUrlTests(DownloadPointTests):
    def test_non_image_files_have_no_direct_url_that_skips_the_checks(self):
        data = self.reader_client.get(f"/api/v1/boards/{self.board.bo_table}/{self.wr_id}/files").json()["data"][0]
        self.assertTrue(data["bf_url"].endswith(self.url), data["bf_url"])
        self.assertTrue(data["bf_download_url"].startswith("/api/v1/"), data["bf_download_url"])

    def test_a_missing_file_is_not_charged(self):
        Post_file.objects.filter(post_id=self.wr_id).update(bf_file="file/missing/nothing.zip")
        self.assertEqual(self.reader_client.get(self.url).status_code, 404)
        self.assertFalse(User_Point.objects.filter(user=self.reader, po_rel_action="다운로드").exists())


class DailyVisitPointTests(TestCase):
    def test_a_signed_in_member_gets_the_login_points_on_the_first_visit_of_the_day(self):
        Config.objects.update_or_create(name="cf_login_point", defaults={"value": "100"})
        user = get_user_model().objects.create_user(username="pt_stay", email="pt-stay@example.test", password="password-1234")
        client = APIClient()
        client.force_authenticate(user=user)
        for _ in range(3):
            self.assertEqual(client.get("/api/v1/auth/me").status_code, 200)
        self.assertEqual(Profile.objects.get(user=user).user_point, 100)
        self.assertEqual(User_Point.objects.filter(user=user, po_rel_table="@login").count(), 1)
