from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase

from gnu_jango.bbs.models import Board, Group
from gnu_jango.bbs.utils import get_board_admin_role, is_board_admin
from gnu_jango.api.v1_board import _admin_role, _can_manage_post, _is_board_admin


class BoardAdminRoleTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.group_admin = user_model.objects.create_user(
            username="board-role-group-admin", password="password"
        )
        self.board_admin = user_model.objects.create_user(
            username="board-role-board-admin", password="password"
        )
        self.member = user_model.objects.create_user(
            username="board-role-member", password="password"
        )
        self.superuser = user_model.objects.create_superuser(
            username="board-role-superuser",
            email="board-role-superuser@example.com",
            password="password",
        )

        self.group = Group.objects.create(
            gr_id="board-role-group",
            gr_subject="Board role group",
            gr_admin=self.group_admin.username,
        )
        self.board = Board.objects.create(
            group=self.group,
            bo_subject="Board role fixture",
            bo_table="board-role-fixture",
            bo_skin="basic",
            bo_mobile_skin="basic",
            bo_admin=self.board_admin.username,
            bo_list_level=2,
            bo_page_rows=10,
        )

    def test_role_resolution_matches_gnuboard_priority_and_board_scope(self):
        self.assertEqual(get_board_admin_role(self.superuser, self.board), "super")
        self.assertEqual(get_board_admin_role(self.group_admin, self.board), "group")
        self.assertEqual(get_board_admin_role(self.board_admin, self.board), "board")
        self.assertEqual(get_board_admin_role(self.member, self.board), "")
        self.assertTrue(is_board_admin(self.board, SimpleNamespace(user=self.group_admin)))
        self.assertTrue(_is_board_admin(self.group_admin, self.board))
        self.assertEqual(_admin_role(self.group_admin, self.board), "group")
        self.assertTrue(_is_board_admin(self.board_admin, self.board))
        self.assertEqual(_admin_role(self.board_admin, self.board), "board")

        other_group = Group.objects.create(gr_id="other-board-role", gr_subject="Other")
        other_board = Board.objects.create(
            group=other_group,
            bo_subject="Other board",
            bo_table="other-board-role-fixture",
            bo_skin="basic",
            bo_mobile_skin="basic",
        )
        self.assertEqual(get_board_admin_role(self.group_admin, other_board), "")
        self.assertFalse(_is_board_admin(self.group_admin, other_board))

    def test_group_and_board_admin_post_management_respects_member_level(self):
        user_model = get_user_model()
        author = user_model.objects.create_user(username="board-role-author", password="password")
        managers = (self.group_admin, self.board_admin)
        for manager in managers:
            manager.profile.user_level = 2
            manager.profile.save(update_fields=["user_level"])
        author.profile.user_level = 3
        author.profile.save(update_fields=["user_level"])

        post = SimpleNamespace(user_id=author.pk, user=author, board=self.board)
        for manager in managers:
            with self.subTest(username=manager.username, author_level=3):
                self.assertFalse(_can_manage_post(manager, post))

        author.profile.user_level = 2
        author.profile.save(update_fields=["user_level"])
        for manager in managers:
            with self.subTest(username=manager.username, author_level=2):
                self.assertTrue(_can_manage_post(manager, post))
        self.assertTrue(_can_manage_post(self.superuser, post))
