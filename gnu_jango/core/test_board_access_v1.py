"""Board access rules on the v1 API.

These were tested against the legacy template views, which were removed because the Next.js
site only uses the v1 API. The same rules are pinned here on the endpoints the site calls.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.bbs.models import Board, Comment, Group, Post, Post_scrap
from gnu_jango.users.models import Profile


class BoardAccessV1Tests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(username="acc-owner", email="acc-owner@example.test", password="password-1234")
        self.other = user_model.objects.create_user(username="acc-other", email="acc-other@example.test", password="password-1234")
        for user in (self.owner, self.other):
            profile, _ = Profile.objects.get_or_create(user=user)
            profile.user_level = 2
            profile.save()
        group = Group.objects.create(gr_id="acc-group", gr_subject="Access")
        self.board = Board.objects.create(group=group, bo_subject="Open", bo_table="acc-open", bo_skin="basic", bo_mobile_skin="basic")
        self.other_board = Board.objects.create(group=group, bo_subject="Other", bo_table="acc-other", bo_skin="basic", bo_mobile_skin="basic")
        self.post = Post.objects.create(board=self.board, wr_num=-1, wr_subject="Owned", wr_content="Owned body", user=self.owner, wr_name="owner", wr_datetime=timezone.now(), wr_last=timezone.now())
        self.post.wr_parent = self.post.pk
        self.post.save(update_fields=["wr_parent"])
        self.comment = Comment.objects.create(board=self.board, post=self.post, user=self.owner, wr_content="Owned comment", wr_name="owner", wr_datetime=timezone.now(), wr_last=timezone.now())
        self.owner_client = self.client_for(self.owner)
        self.other_client = self.client_for(self.other)

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_a_post_cannot_be_deleted_through_another_boards_address(self):
        response = self.owner_client.delete(f"/api/v1/posts/{self.other_board.bo_table}/{self.post.pk}")
        self.assertEqual(response.status_code, 404, response.content[:200])
        self.assertTrue(Post.objects.filter(pk=self.post.pk).exists())

    def test_a_comment_cannot_be_deleted_through_another_boards_address(self):
        response = self.owner_client.delete(f"/api/v1/comments/{self.other_board.bo_table}/{self.comment.pk}")
        self.assertEqual(response.status_code, 404, response.content[:200])
        self.assertTrue(Comment.objects.filter(pk=self.comment.pk).exists())

    def test_another_member_cannot_delete_someones_post_or_comment(self):
        self.assertEqual(self.other_client.delete(f"/api/v1/posts/{self.board.bo_table}/{self.post.pk}").status_code, 403)
        self.assertEqual(self.other_client.delete(f"/api/v1/comments/{self.board.bo_table}/{self.comment.pk}").status_code, 403)
        self.assertTrue(Post.objects.filter(pk=self.post.pk).exists())
        self.assertTrue(Comment.objects.filter(pk=self.comment.pk).exists())

    def test_a_post_is_not_readable_through_another_boards_address(self):
        response = self.other_client.get(f"/api/v1/posts/{self.other_board.bo_table}/{self.post.pk}")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("Owned body", response.content.decode())

    def test_the_read_level_hides_the_post_and_does_not_count_a_hit(self):
        Board.objects.filter(pk=self.board.pk).update(bo_read_level=5)
        response = self.other_client.get(f"/api/v1/posts/{self.board.bo_table}/{self.post.pk}")
        self.assertIn(response.status_code, (403, 404))
        self.assertNotIn("Owned body", response.content.decode())
        self.post.refresh_from_db()
        self.assertEqual(self.post.wr_hit, 0)

    def test_the_list_level_hides_the_board_list(self):
        Board.objects.filter(pk=self.board.pk).update(bo_list_level=5)
        response = self.other_client.get(f"/api/v1/boards/{self.board.bo_table}/posts")
        # The API answers with an empty list rather than an error; nothing of the board leaks.
        self.assertNotIn("Owned", response.content.decode())
        if response.status_code == 200:
            self.assertEqual(response.json()["data"], [])

    def test_a_member_cannot_delete_another_members_scrap(self):
        scrap = Post_scrap.objects.create(user=self.other, board=self.board, post=self.post, ms_datetime=timezone.now())
        response = self.owner_client.delete(f"/api/v1/scraps/{scrap.pk}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["data"]["deleted"])
        self.assertTrue(Post_scrap.objects.filter(pk=scrap.pk).exists())


class AuthorPrivacyV1Tests(BoardAccessV1Tests):
    """The author's e-mail and IP are not handed to other readers (search, list, detail, comments)."""

    def setUp(self):
        super().setUp()
        Post.objects.filter(pk=self.post.pk).update(wr_ip="203.0.113.77", wr_email="secret@example.test")
        Comment.objects.filter(pk=self.comment.pk).update(wr_ip="203.0.113.78")

    def assert_private_hidden(self, response):
        body = response.content.decode()
        self.assertNotIn("secret@example.test", body)
        self.assertNotIn("acc-owner@example.test", body)
        self.assertNotIn("203.0.113.77", body)
        self.assertNotIn("203.0.113.78", body)

    def test_search_list_and_detail_hide_the_authors_email_and_ip_from_others(self):
        for client in (APIClient(), self.other_client):
            self.assert_private_hidden(client.get("/api/v1/search", {"q": "Owned"}))
            self.assert_private_hidden(client.get(f"/api/v1/boards/{self.board.bo_table}/posts"))
            self.assert_private_hidden(client.get(f"/api/v1/posts/{self.board.bo_table}/{self.post.pk}"))

    def test_the_ip_is_masked_when_the_board_shows_ips(self):
        Board.objects.filter(pk=self.board.pk).update(bo_use_ip_view=True)
        data = self.other_client.get(f"/api/v1/posts/{self.board.bo_table}/{self.post.pk}").json()["data"]
        self.assertEqual(data["wr_ip"], "203.♡.113.77")

    def test_the_author_sees_their_own_email_and_ip(self):
        data = self.owner_client.get(f"/api/v1/posts/{self.board.bo_table}/{self.post.pk}").json()["data"]
        self.assertEqual(data["wr_email"], "secret@example.test")
        self.assertEqual(data["wr_ip"], "203.0.113.77")
