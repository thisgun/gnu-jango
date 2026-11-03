"""The core's write and sign-up hooks: bbs.post.created, bbs.comment.created and member.joined."""

from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APIClient

from gnu_jango.bbs.models import Board, Group
from gnu_jango.plugins import hooks
from gnu_jango.users.models import Profile


class WriteAndJoinHookTests(TestCase):
    def setUp(self):
        patcher = mock.patch.object(hooks, "_listeners", {})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.seen = []
        for name in ("bbs.post.created", "bbs.comment.created", "member.joined"):
            hooks.on(name)(self.recorder(name))

        self.author = get_user_model().objects.create_user(username="hk-author", email="hk@example.test", password="x")
        profile, _ = Profile.objects.get_or_create(user=self.author)
        profile.user_level = 2
        profile.save()
        group = Group.objects.create(gr_id="hk-group", gr_subject="Hooks")
        self.board = Board.objects.create(
            group=group, bo_subject="훅", bo_table="hk-board", bo_skin="basic", bo_mobile_skin="basic",
            bo_write_level=1, bo_comment_level=1, bo_read_level=1, bo_reply_level=1,
        )
        self.client_api = APIClient()
        self.client_api.force_authenticate(user=self.author)

    def recorder(self, name):
        def listener(user, request, **kwargs):
            self.seen.append((name, user.pk if user else None, kwargs))

        listener.__qualname__ = f"listener_{name}"
        return listener

    def write(self):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            response = self.client_api.post(
                f"/api/v1/boards/{self.board.bo_table}/posts",
                {"wr_subject": "Subject", "wr_content": "Body text"},
                format="json",
            )
        self.assertEqual(response.status_code, 201, response.content[:300])
        return response.json()["data"]["wr_id"], callbacks

    def test_writing_a_post_sends_bbs_post_created_after_commit(self):
        wr_id, callbacks = self.write()

        self.assertTrue(callbacks)
        self.assertEqual([(name, user) for name, user, _ in self.seen], [("bbs.post.created", self.author.pk)])
        self.assertEqual(self.seen[0][2]["post"].board_id, self.board.pk)

    def test_writing_a_comment_sends_bbs_comment_created(self):
        wr_id, _ = self.write()
        self.seen.clear()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client_api.post(
                f"/api/v1/comments/{self.board.bo_table}/{wr_id}", {"wr_content": "Nice"}, format="json"
            )

        self.assertIn(response.status_code, (200, 201), response.content[:300])
        self.assertEqual([(name, user) for name, user, _ in self.seen], [("bbs.comment.created", self.author.pk)])
        self.assertEqual(self.seen[0][2]["comment"].wr_content, "Nice")

    def test_a_refused_write_sends_nothing(self):
        Board.objects.filter(pk=self.board.pk).update(bo_write_level=9)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client_api.post(
                f"/api/v1/boards/{self.board.bo_table}/posts",
                {"wr_subject": "Subject", "wr_content": "Body text"},
                format="json",
            )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.seen, [])

    def test_signing_up_sends_member_joined(self):
        with mock.patch("gnu_jango.api.v1_auth._captcha_matches", return_value=True):
            with self.captureOnCommitCallbacks(execute=True):
                response = APIClient().post(
                    "/api/v1/auth/register",
                    {
                        "mb_id": "hk_newbie", "mb_password": "Str0ng-pass-99", "mb_password_re": "Str0ng-pass-99",
                        "mb_email": "hk-newbie@example.test", "mb_name": "New", "mb_nick": "newbie-hk",
                    },
                    format="json",
                )

        self.assertIn(response.status_code, (200, 201), response.content[:300])
        user = get_user_model().objects.get(username="hk_newbie")
        self.assertEqual([(name, uid) for name, uid, _ in self.seen], [("member.joined", user.pk)])
