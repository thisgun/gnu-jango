"""Board rules pinned on the v1 API.

These rules were tested against the pre-v1 API (/api/post/..., /api/articles, /api/user/...), which
was removed because no client used it. The same rules are tested here on the endpoints the site
and the mobile app call.
"""

import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.bbs.models import Board, Comment, Group, Post, Post_scrap
from gnu_jango.users.models import Profile
from gnu_jango.utils.lib import get_encrypt_string


class BoardRulesV1Tests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="rule-owner", email="rule-owner@example.test", password="password-1234")
        self.other = user_model.objects.create_user(username="rule-other", email="rule-other@example.test", password="password-1234")
        for user in (self.owner, self.other):
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.user_level = 2
            profile.save()
        self.owner = user_model.objects.get(pk=self.owner.pk)
        self.other = user_model.objects.get(pk=self.other.pk)
        group = Group.objects.create(gr_id="rule-group", gr_subject="Rules")
        self.board = Board.objects.create(
            group=group, bo_subject="Rules", bo_table="rule-board", bo_skin="basic", bo_mobile_skin="basic",
            bo_comment_level=1, bo_write_level=1,
        )
        now = timezone.now()
        self.post = Post.objects.create(
            board=self.board, wr_num=-1, wr_subject="Rule post", wr_content="Rule body", user=self.owner,
            wr_name="owner", wr_password=get_encrypt_string("post-pass"), wr_datetime=now, wr_last=now,
        )
        self.post.wr_parent = self.post.pk
        self.post.save(update_fields=["wr_parent"])
        self.owner_client = self.client_for(self.owner)
        self.other_client = self.client_for(self.other)

    def client_for(self, user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user=user)
        return client

    def comment(self, client, post=None, extra=None, **data):
        post = post or self.post
        return client.post(f"/api/v1/comments/{self.board.bo_table}/{post.pk}", data, format="json", **(extra or {}))

    def test_a_comment_below_the_boards_comment_level_is_refused(self):
        Board.objects.filter(pk=self.board.pk).update(bo_comment_level=5)
        response = self.comment(self.other_client, wr_content="Too low")
        self.assertEqual(response.status_code, 403, response.content[:200])
        self.assertFalse(Comment.objects.exists())

    def test_a_comment_at_the_comment_level_is_accepted(self):
        Board.objects.filter(pk=self.board.pk).update(bo_comment_level=2)
        self.assertEqual(self.comment(self.other_client, wr_content="Just right").status_code, 201)

    def test_a_blank_comment_is_refused(self):
        self.assertEqual(self.comment(self.other_client, wr_content="   ").status_code, 422)
        self.assertFalse(Comment.objects.exists())

    def test_the_server_decides_the_comment_metadata(self):
        response = self.comment(
            self.other_client, extra={"REMOTE_ADDR": "198.51.100.24"},
            wr_content="Hello", wr_name="Spoofed", wr_ip="203.0.113.77",
        )
        self.assertEqual(response.status_code, 201, response.content[:200])
        comment = Comment.objects.get(post=self.post)
        self.assertEqual(comment.board, self.board)
        self.assertEqual(comment.wr_ip, "198.51.100.24")
        self.assertNotEqual(comment.wr_name, "Spoofed")
        self.assertEqual(comment.user, self.other)
        self.assertIsNotNone(comment.wr_datetime)

    def test_nobody_without_access_can_comment_on_a_secret_post(self):
        Post.objects.filter(pk=self.post.pk).update(wr_option="secret")
        self.assertEqual(self.comment(self.other_client, wr_content="No access").status_code, 404)
        guest = self.comment(self.client_for(), wr_content="No access", wr_name="Guest", wr_password="guest-pass-1")
        self.assertEqual(guest.status_code, 404)
        self.assertFalse(Comment.objects.exists())

    def test_only_the_author_can_edit_a_post(self):
        payload = {"wr_subject": "Edited", "wr_content": "Edited body"}
        url = f"/api/v1/posts/{self.board.bo_table}/{self.post.pk}"
        self.assertEqual(self.other_client.patch(url, payload, format="json").status_code, 403)
        self.post.refresh_from_db()
        self.assertEqual(self.post.wr_subject, "Rule post")
        self.assertEqual(self.owner_client.patch(url, payload, format="json").status_code, 200)
        self.post.refresh_from_db()
        self.assertEqual(self.post.wr_subject, "Edited")

    def test_a_secret_comment_is_masked_for_other_readers(self):
        Comment.objects.create(
            board=self.board, post=self.post, wr_content="Hidden comment text", wr_name="commenter",
            wr_option="secret", wr_password=get_encrypt_string("comment-pass"), wr_datetime=timezone.now(),
        )
        body = self.other_client.get(f"/api/v1/posts/{self.board.bo_table}/{self.post.pk}").content.decode()
        self.assertNotIn("Hidden comment text", body)

    def test_post_passwords_never_leave_the_server(self):
        for path in (f"/api/v1/boards/{self.board.bo_table}/posts", f"/api/v1/posts/{self.board.bo_table}/{self.post.pk}"):
            body = self.owner_client.get(path).content.decode()
            self.assertNotIn(self.post.wr_password, body, path)

    def test_the_scrap_list_shows_only_my_readable_scraps(self):
        Post_scrap.objects.create(user=self.owner, board=self.board, post=self.post, ms_datetime=timezone.now())
        hidden_board = Board.objects.create(
            group=self.board.group, bo_subject="Hidden", bo_table="rule-hidden", bo_skin="basic", bo_mobile_skin="basic", bo_read_level=9,
        )
        hidden = Post.objects.create(
            board=hidden_board, wr_num=-2, wr_subject="Hidden scrap", wr_content="x", user=self.other, wr_name="o",
            wr_datetime=timezone.now(), wr_last=timezone.now(),
        )
        Post_scrap.objects.create(user=self.owner, board=hidden_board, post=hidden, ms_datetime=timezone.now())
        Post_scrap.objects.create(user=self.other, board=self.board, post=self.post, ms_datetime=timezone.now())
        data = self.owner_client.get("/api/v1/scraps").json()["data"]
        body = json.dumps(data, ensure_ascii=False)
        self.assertIn("Rule post", body)
        self.assertNotIn("Hidden scrap", body)
        self.assertEqual(len(data), 1)

    def test_a_secret_comment_is_shown_to_its_author_and_the_post_author(self):
        Comment.objects.create(
            board=self.board, post=self.post, user=self.other, wr_content="Whispered text", wr_name="other",
            wr_option="secret", wr_datetime=timezone.now(),
        )
        url = f"/api/v1/posts/{self.board.bo_table}/{self.post.pk}"
        self.assertIn("Whispered text", self.other_client.get(url).content.decode())
        self.assertIn("Whispered text", self.owner_client.get(url).content.decode())
        self.assertNotIn("Whispered text", self.client_for().get(url).content.decode())
