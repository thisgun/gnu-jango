"""The board's "secret posts" setting is enforced on the server, as Gnuboard5 does.

PHP bbs/write_update.php rejects a secret post from a non-admin on a board that has
secret posts disabled (bo_use_secret = 0). The API used to trust the request flag, so
any member could create (or switch an existing post to) a secret post on such a board.
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from gnu_jango.bbs.models import Board, Group, Post


class BoardSecretPostTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.member = user_model.objects.create_user(username="secret-member", email="secret-member@example.test", password="password")
        self.admin = user_model.objects.create_superuser(username="secret-admin", email="secret-admin@example.test", password="password")
        group = Group.objects.create(gr_id="secret-group", gr_subject="Secret posts")
        self.closed = Board.objects.create(group=group, bo_subject="No secrets", bo_table="no-secret", bo_skin="basic", bo_mobile_skin="basic", bo_write_level=1, bo_use_secret=False)
        self.open = Board.objects.create(group=group, bo_subject="Secrets ok", bo_table="with-secret", bo_skin="basic", bo_mobile_skin="basic", bo_write_level=1, bo_use_secret=True)
        self.member_client = APIClient()
        self.member_client.force_authenticate(user=self.member)
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

    def create(self, client, board, **extra):
        return client.post(f"/api/v1/boards/{board.bo_table}/posts", {"wr_subject": "Subject", "wr_content": "Content", **extra}, format="json")

    def test_member_cannot_create_a_secret_post_on_a_board_without_secret_posts(self):
        response = self.create(self.member_client, self.closed, secret="secret")
        self.assertEqual(response.status_code, 403, response.content[:300])
        self.assertEqual(Post.objects.filter(board=self.closed).count(), 0)

    def test_member_can_still_create_a_normal_post_on_that_board(self):
        response = self.create(self.member_client, self.closed)
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertFalse(response.json()["data"]["is_secret"])

    def test_html_field_cannot_smuggle_the_secret_option(self):
        # PHP also checks the html and mail fields for the word "secret".
        response = self.create(self.member_client, self.closed, html="secret")
        self.assertEqual(response.status_code, 403, response.content[:300])

    def test_other_truthy_secret_values_are_refused_too(self):
        # The post option treats these as "secret" as well, so the guard must not miss them.
        for value in (1, True, "1", "true", "on", "yes"):
            response = self.create(self.member_client, self.closed, secret=value)
            self.assertEqual(response.status_code, 403, f"{value!r}: {response.content[:200]}")
        self.assertEqual(Post.objects.filter(board=self.closed).count(), 0)

    def test_member_can_create_a_secret_post_on_a_board_that_allows_it(self):
        response = self.create(self.member_client, self.open, secret="secret")
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertTrue(response.json()["data"]["is_secret"])

    def test_administrator_may_create_a_secret_post_anywhere(self):
        response = self.create(self.admin_client, self.closed, secret="secret")
        self.assertEqual(response.status_code, 201, response.content[:300])
        self.assertTrue(response.json()["data"]["is_secret"])

    def test_member_cannot_turn_an_existing_post_secret_on_a_board_without_secret_posts(self):
        created = self.create(self.member_client, self.closed).json()["data"]
        response = self.member_client.patch(
            f"/api/v1/posts/{self.closed.bo_table}/{created['wr_id']}",
            {"wr_subject": "Subject", "wr_content": "Content", "secret": "secret"},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.content[:300])
        self.assertFalse(Post.objects.get(board=self.closed).wr_option.startswith("secret"))


class BoardSecretPostVisibilityTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.author = user_model.objects.create_user(username="secret-author", email="secret-author@example.test", password="password")
        self.other = user_model.objects.create_user(username="secret-other", email="secret-other@example.test", password="password")
        self.admin = user_model.objects.create_superuser(username="secret-boss", email="secret-boss@example.test", password="password")
        group = Group.objects.create(gr_id="secret-view-group", gr_subject="Secret view")
        self.board = Board.objects.create(group=group, bo_subject="Secrets ok", bo_table="view-secret", bo_skin="basic", bo_mobile_skin="basic", bo_write_level=1, bo_use_secret=True)
        client = APIClient()
        client.force_authenticate(user=self.author)
        created = client.post(f"/api/v1/boards/{self.board.bo_table}/posts", {"wr_subject": "Hidden subject", "wr_content": "Hidden body text", "secret": "secret"}, format="json")
        self.wr_id = created.json()["data"]["wr_id"]

    def detail(self, user=None):
        client = APIClient()
        if user is not None:
            client.force_authenticate(user=user)
        return client.get(f"/api/v1/posts/{self.board.bo_table}/{self.wr_id}")

    def test_author_and_administrator_can_read_the_secret_post(self):
        for user in (self.author, self.admin):
            response = self.detail(user)
            self.assertEqual(response.status_code, 200, response.content[:300])
            self.assertIn("Hidden body text", response.content.decode())

    def test_other_member_and_visitor_cannot_read_the_secret_post_body(self):
        for user in (self.other, None):
            response = self.detail(user)
            self.assertNotIn("Hidden body text", response.content.decode(), f"leaked to {user}")
            self.assertIn(response.status_code, (401, 403, 404), response.content[:300])

    def test_secret_post_content_is_not_leaked_by_the_list(self):
        client = APIClient()
        client.force_authenticate(user=self.other)
        response = client.get(f"/api/v1/boards/{self.board.bo_table}/posts")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Hidden body text", response.content.decode())
