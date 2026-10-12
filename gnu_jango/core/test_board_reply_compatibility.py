from importlib import import_module
from types import SimpleNamespace

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.sessions.backends.db import SessionStore
from django.db import connection
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.bbs.models import Board, Group, Post
from gnu_jango.api.v1_board import _public_post_id
from gnu_jango.api.v1_auth import (
    CAPTCHA_ATTEMPT_SESSION_KEY,
    CAPTCHA_MAX_FAILURES,
    CAPTCHA_SESSION_KEY,
    _captcha_matches,
    _consume_captcha,
    _store_captcha,
)
from gnu_jango.core.management.commands.migrate_gnuboard5 import (
    Command as GnuboardImportCommand,
    post_reply_marker,
)

reply_migration = import_module(
    "gnu_jango.bbs.migrations.0044_post_wr_reply_character_path"
)


class BoardReplyCompatibilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="reply-compat-admin",
            email="reply-compat-admin@example.com",
            password="password",
        )
        self.user.is_superuser = True
        self.user.save(update_fields=["is_superuser"])

        self.group = Group.objects.create(gr_id="reply-compat", gr_subject="Reply compatibility")
        self.board = Board.objects.create(
            group=self.group,
            bo_subject="Reply compatibility",
            bo_table="reply-compat",
            bo_skin="basic",
            bo_mobile_skin="basic",
            bo_write_level=1,
            bo_reply_level=1,
            bo_page_rows=100,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
        self.url = f"/api/v1/boards/{self.board.bo_table}/posts"

    def create_post(self, subject, reply_to=None):
        data = {"wr_subject": subject, "wr_content": f"Content for {subject}"}
        if reply_to is not None:
            data["reply_to"] = reply_to
        response = self.client.post(self.url, data, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["data"]

    def test_reply_markers_follow_gnuboard_parent_path_and_order_setting(self):
        self.board.bo_reply_order = True
        self.board.save(update_fields=["bo_reply_order"])
        root = self.create_post("Root")
        first = self.create_post("First reply", reply_to=root["wr_id"])
        second = self.create_post("Second reply", reply_to=root["wr_id"])
        nested = self.create_post("Nested reply", reply_to=first["wr_id"])

        self.assertEqual(first["wr_reply"], "A")
        self.assertEqual(second["wr_reply"], "B")
        self.assertEqual(nested["wr_reply"], "AA")
        self.assertEqual(nested["wr_parent"], root["wr_id"])

        listing = self.client.get(self.url)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(
            [row["wr_reply"] for row in listing.data["data"]],
            ["", "A", "AA", "B"],
        )

    def test_default_reply_order_allocates_z_downward_and_lists_ascending(self):
        root = self.create_post("Root")
        first = self.create_post("First reply", reply_to=root["wr_id"])
        second = self.create_post("Second reply", reply_to=root["wr_id"])
        nested = self.create_post("Nested reply", reply_to=first["wr_id"])

        self.assertEqual(first["wr_reply"], "Z")
        self.assertEqual(second["wr_reply"], "Y")
        self.assertEqual(nested["wr_reply"], "ZZ")

        listing = self.client.get(self.url)
        self.assertEqual(
            [row["wr_reply"] for row in listing.data["data"]],
            ["", "Y", "Z", "ZZ"],
        )

    def test_imported_reply_keeps_its_source_id_and_root_relationship(self):
        root = Post.objects.create(
            board=self.board,
            legacy_wr_id=9001,
            wr_num=-9001,
            wr_reply="",
            wr_parent=9001,
            wr_subject="Imported root",
            wr_content="Root content",
            wr_name="writer",
            wr_datetime=timezone.now(),
        )
        reply = Post.objects.create(
            board=self.board,
            legacy_wr_id=9002,
            wr_num=root.wr_num,
            wr_reply="A",
            wr_parent=9001,
            wr_subject="Imported reply",
            wr_content="Reply content",
            wr_name="writer",
            wr_datetime=timezone.now(),
        )

        self.assertEqual(_public_post_id(reply), 9002)
        detail = self.client.get(f"/api/v1/posts/{self.board.bo_table}/9002")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.data["data"]["wr_id"], 9002)
        self.assertEqual(detail.data["data"]["wr_parent"], 9001)

        nested = self.create_post("Nested imported reply", reply_to=9002)
        self.assertEqual(nested["wr_reply"], "AZ")
        self.assertEqual(nested["wr_parent"], 9001)

    def test_sibling_and_depth_limits_match_gnuboard(self):
        root = self.create_post("Root")
        parent_id = root["wr_id"]
        for index in range(26):
            reply = self.create_post(f"Reply {index + 1}", reply_to=parent_id)
            if index == 0:
                first_reply_id = reply["wr_id"]

        overflow = self.client.post(
            self.url,
            {"wr_subject": "Reply 27", "wr_content": "Overflow", "reply_to": parent_id},
            format="json",
        )
        self.assertEqual(overflow.status_code, 422)
        self.assertEqual(overflow.data["errors"].get("reply_limit_reached"),
                         "답글 단계당 최대 26개, 최대 깊이 10단계까지만 작성할 수 있습니다.")

        parent_id = first_reply_id
        for index in range(9):
            nested = self.create_post(f"Nested {index + 1}", reply_to=parent_id)
            parent_id = nested["wr_id"]
        too_deep = self.client.post(
            self.url,
            {"wr_subject": "Too deep", "wr_content": "Overflow", "reply_to": parent_id},
            format="json",
        )
        self.assertEqual(too_deep.status_code, 422)
        self.assertEqual(Post.objects.filter(board=self.board).count(), 1 + 26 + 9)

    def test_guest_post_and_reply_require_captcha_and_store_hashed_password(self):
        self.board.bo_use_captcha = True
        self.board.save(update_fields=["bo_use_captcha"])
        root = self.create_post("Root")
        guest_client = APIClient()
        session = guest_client.session
        session[CAPTCHA_SESSION_KEY] = "234567"
        session.save()
        guest_payload = {
            "wr_name": "guest writer",
            "wr_password": "guest-secret",
            "wr_subject": "Guest post",
            "wr_content": "Created without signing in",
            "captcha_key": "222222",
        }

        invalid = guest_client.post(self.url, guest_payload, format="json")
        self.assertEqual(invalid.status_code, 422)
        self.assertEqual(Post.objects.filter(board=self.board).count(), 1)

        guest_payload["captcha_key"] = "234567"
        created = guest_client.post(self.url, guest_payload, format="json")
        self.assertEqual(created.status_code, 201, created.data)
        post = Post.objects.get(pk=created.data["data"]["id"])
        self.assertIsNone(post.user)
        self.assertEqual(post.wr_name, "guest writer")
        self.assertTrue(check_password("guest-secret", post.wr_password))
        self.assertNotIn(CAPTCHA_SESSION_KEY, guest_client.session)
        self.assertNotIn(CAPTCHA_ATTEMPT_SESSION_KEY, guest_client.session)

        reply_session = guest_client.session
        reply_session[CAPTCHA_SESSION_KEY] = "876543"
        reply_session.save()
        guest_reply = guest_client.post(
            self.url,
            {
                "wr_name": "guest replier",
                "wr_password": "reply-secret",
                "wr_subject": "Guest reply",
                "wr_content": "Reply created without signing in",
                "reply_to": root["wr_id"],
                "captcha_key": "876543",
            },
            format="json",
        )
        self.assertEqual(guest_reply.status_code, 201, guest_reply.data)
        reply = Post.objects.get(pk=guest_reply.data["data"]["id"])
        self.assertEqual(reply.wr_reply, "Z")
        self.assertTrue(check_password("reply-secret", reply.wr_password))
        self.assertEqual(reply.wr_parent, root["wr_id"])

    def test_guest_write_and_reply_levels_are_enforced(self):
        guest_client = APIClient()
        payload = {
            "wr_name": "guest writer",
            "wr_password": "guest-secret",
            "wr_subject": "Guest post",
            "wr_content": "Created without signing in",
        }
        self.board.bo_write_level = 2
        self.board.save(update_fields=["bo_write_level"])
        denied_write = guest_client.post(self.url, payload, format="json")
        self.assertEqual(denied_write.status_code, 403)
        self.assertEqual(Post.objects.filter(board=self.board).count(), 0)

        self.board.bo_write_level = 1
        self.board.bo_reply_level = 2
        self.board.save(update_fields=["bo_write_level", "bo_reply_level"])
        root = self.create_post("Root")
        denied_reply = guest_client.post(
            self.url,
            {**payload, "reply_to": root["wr_id"]},
            format="json",
        )
        self.assertEqual(denied_reply.status_code, 403)
        self.assertEqual(Post.objects.filter(board=self.board).count(), 1)


class GnuboardImportReplyMarkerTests(TestCase):
    def test_import_preserves_alphabetic_markers_and_normalizes_root(self):
        self.assertEqual(post_reply_marker({"wr_reply": ""}), "")
        self.assertEqual(post_reply_marker({"wr_reply": 0}), "")
        self.assertEqual(post_reply_marker({"wr_reply": "A"}), "A")
        self.assertEqual(post_reply_marker({"wr_reply": "AZ"}), "AZ")
        with self.assertRaisesRegex(ValueError, "cannot exceed 10 characters"):
            post_reply_marker({"wr_reply": "ABCDEFGHIJK"})

    def test_importer_keeps_source_post_id_parent_and_is_idempotent(self):
        group = Group.objects.create(gr_id="reply-import", gr_subject="Reply import")
        board = Board.objects.create(
            group=group,
            bo_subject="Imported replies",
            bo_table="reply-import",
            bo_skin="basic",
            bo_mobile_skin="basic",
        )
        row = {
            "wr_id": 9002,
            "wr_parent": 9001,
            "wr_num": -9001,
            "wr_reply": "AZ",
            "wr_subject": "Imported reply",
            "wr_content": "Original content",
            "wr_name": "writer",
            "wr_datetime": "2026-10-09 07:00:00",
        }

        command = GnuboardImportCommand()
        imported = command.upsert_post(board, row)
        self.assertEqual(imported.legacy_wr_id, 9002)
        self.assertEqual(imported.wr_parent, 9001)
        self.assertEqual(imported.wr_reply, "AZ")

        row["wr_content"] = "Updated content"
        refreshed = command.upsert_post(board, row)
        self.assertEqual(refreshed.pk, imported.pk)
        self.assertEqual(refreshed.wr_content, "Updated content")
        self.assertEqual(Post.objects.filter(board=board).count(), 1)

    def test_schema_migration_converts_numeric_replies_and_can_reverse(self):
        group = Group.objects.create(gr_id="reply-migration", gr_subject="Reply migration")
        default_board = Board.objects.create(
            group=group,
            bo_subject="Default reply order",
            bo_table="reply-migration-default",
            bo_skin="basic",
            bo_mobile_skin="basic",
            bo_reply_order=False,
        )
        forward_board = Board.objects.create(
            group=group,
            bo_subject="Forward reply order",
            bo_table="reply-migration-forward",
            bo_skin="basic",
            bo_mobile_skin="basic",
            bo_reply_order=True,
        )
        def make_post(board, wr_num, wr_reply, wr_parent, subject):
            return Post.objects.create(
                board=board,
                wr_num=wr_num,
                wr_reply=wr_reply,
                wr_parent=wr_parent,
                wr_subject=subject,
                wr_name="writer",
                wr_datetime=timezone.now(),
            )

        root_default = make_post(default_board, -1, "0", 1001, "Root")
        old_default_first = make_post(default_board, -1, "1", 1001, "First")
        old_default_second = make_post(default_board, -1, "2", 1001, "Second")
        root_forward = make_post(forward_board, -2, "0", 2001, "Root")
        old_forward_first = make_post(forward_board, -2, "1", 2001, "First")
        old_forward_second = make_post(forward_board, -2, "2", 2001, "Second")
        schema_editor = SimpleNamespace(connection=connection)

        reply_migration.forwards(django_apps, schema_editor)

        root_default.refresh_from_db()
        old_default_first.refresh_from_db()
        old_default_second.refresh_from_db()
        root_forward.refresh_from_db()
        old_forward_first.refresh_from_db()
        old_forward_second.refresh_from_db()
        self.assertEqual(root_default.wr_reply, "")
        self.assertEqual((old_default_first.wr_reply, old_default_second.wr_reply), ("Z", "Y"))
        self.assertEqual(root_default.legacy_wr_id, 1001)
        self.assertEqual(root_forward.wr_reply, "")
        self.assertEqual((old_forward_first.wr_reply, old_forward_second.wr_reply), ("A", "B"))

        reply_migration.backwards(django_apps, schema_editor)

        root_default.refresh_from_db()
        old_default_first.refresh_from_db()
        old_default_second.refresh_from_db()
        root_forward.refresh_from_db()
        old_forward_first.refresh_from_db()
        old_forward_second.refresh_from_db()
        self.assertEqual(root_default.wr_reply, "0")
        self.assertEqual((old_default_first.wr_reply, old_default_second.wr_reply), ("1", "2"))
        self.assertEqual(root_default.legacy_wr_id, None)
        self.assertEqual(root_forward.wr_reply, "0")
        self.assertEqual((old_forward_first.wr_reply, old_forward_second.wr_reply), ("1", "2"))

    def test_captcha_failure_limit_resets_on_refresh_and_clears_after_use(self):
        request = SimpleNamespace(session=SessionStore())
        _store_captcha(request, "234567")

        for _ in range(CAPTCHA_MAX_FAILURES):
            self.assertFalse(_captcha_matches(request, "222222"))
        self.assertEqual(
            request.session[CAPTCHA_ATTEMPT_SESSION_KEY], CAPTCHA_MAX_FAILURES
        )
        self.assertFalse(_captcha_matches(request, "234567"))

        _store_captcha(request, "765432")
        self.assertEqual(request.session[CAPTCHA_ATTEMPT_SESSION_KEY], 0)
        self.assertTrue(_captcha_matches(request, "765432"))
        _consume_captcha(request)
        self.assertNotIn(CAPTCHA_SESSION_KEY, request.session)
        self.assertNotIn(CAPTCHA_ATTEMPT_SESSION_KEY, request.session)
