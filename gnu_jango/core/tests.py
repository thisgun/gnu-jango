import datetime
from io import BytesIO, StringIO
import shutil
import tempfile
from types import SimpleNamespace
from unittest import skip
from unittest.mock import PropertyMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from gnu_jango import defaults
from gnu_jango.bbs.forms import WriteFileForm
from gnu_jango.bbs.bbs_libs import Board_Move_update
from gnu_jango.bbs.models import Board, Comment, Group, Post, Post_file
from gnu_jango.bbs.utils import get_board
from gnu_jango.config.Configforms import ConfigsForm
from gnu_jango.core.models import Editor_attachments
from gnu_jango.templatetags.bleach_tags import bleach_value
from gnu_jango.templatetags.gfm import gfm
from gnu_jango.templatetags.widgets import latest
from gnu_jango.utils.lib import get_encrypt_string


AUTH_THROTTLE_TEST_RATES = {
    **settings.REST_FRAMEWORK.get("DEFAULT_THROTTLE_RATES", {}),
    "auth-register": "1/min",
    "auth-login": "1/min",
    "auth-token": "1/min",
}

AUTH_THROTTLE_TEST_REST_FRAMEWORK = {
    **settings.REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": AUTH_THROTTLE_TEST_RATES,
}


class HtmlSanitizerTests(SimpleTestCase):
    def test_gfm_filter_sanitizes_links_and_preserves_tables(self):
        rendered = str(
            gfm(
                "| a | b |\n"
                "| - | - |\n"
                "| 1 | 2 |\n\n"
                "[bad](javascript:alert(1))"
            )
        )

        self.assertIn("<table>", rendered)
        self.assertIn("<td>1</td>", rendered)
        self.assertIn('<a href="">bad</a>', rendered)
        self.assertNotIn("javascript:", rendered)
        self.assertNotIn("<script", rendered)

    def test_bleach_filter_removes_unsafe_html(self):
        rendered = str(
            bleach_value(
                '<p onclick="alert(1)">hello<script>alert(1)</script></p>'
                '<a href="javascript:alert(1)">bad</a>'
            )
        )

        self.assertIn("<p>helloalert(1)</p>", rendered)
        self.assertIn('<a>bad</a>', rendered)
        self.assertNotIn("onclick", rendered)
        self.assertNotIn("javascript:", rendered)
        self.assertNotIn("<script", rendered)

    def test_config_help_escapes_description_html(self):
        rendered = str(
            ConfigsForm.format_help(
                None,
                '<script>alert(1)</script> *bold*\nhttps://example.com',
            )
        )

        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertIn("<b>bold</b>", rendered)
        self.assertIn("<br>", rendered)
        self.assertIn('href="https://example.com"', rendered)
        self.assertNotIn("<script", rendered)


class DevelopmentSettingsTests(SimpleTestCase):
    def test_development_cors_does_not_allow_wildcard_credentials(self):
        self.assertFalse(
            settings.CORS_ALLOW_ALL_ORIGINS and settings.CORS_ALLOW_CREDENTIALS
        )

    def test_development_cors_has_explicit_local_origins(self):
        self.assertIn("http://localhost:3000", settings.CORS_ALLOWED_ORIGINS)


class ProjectSmokeTests(TestCase):
    def test_homepage_renders(self):
        response = self.client.get(reverse("index"))

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<html", response.content.lower())

    def test_admin_requires_login(self):
        response = self.client.get(reverse("admin:index"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/admin/login/", response["Location"])


class MainApiLatestTests(TestCase):
    def setUp(self):
        cache.clear()
        self.group = Group.objects.create(gr_id="latest", gr_subject="Latest")
        self.board = Board.objects.create(
            group=self.group,
            bo_subject="First board",
            bo_table="first-board",
            bo_skin="basic",
            bo_mobile_skin="basic",
        )
        self.second_board = Board.objects.create(
            group=self.group,
            bo_subject="Second board",
            bo_table="second-board",
            bo_skin="basic",
            bo_mobile_skin="basic",
        )
        self._create_posts(self.board, "First")
        self._create_posts(self.second_board, "Second")

    def _create_posts(self, board, prefix):
        base_time = timezone.now()
        for index in range(6):
            Post.objects.create(
                board=board,
                wr_subject=f"{prefix} post {index}",
                wr_content=f"{prefix} content {index}",
                wr_name="writer",
                wr_num=0,
                wr_datetime=base_time + datetime.timedelta(minutes=index),
            )

    def test_latest_tag_returns_requested_rows(self):
        posts = latest(
            {"request": None},
            "",
            self.board,
            rows=5,
            subject_len=40,
            cache_time=1,
            options={"get_api": 1},
        )

        self.assertEqual(len(posts), 5)
        self.assertEqual(posts[0].wr_subject, "First post 5")


class PostSlugTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(gr_id="slug", gr_subject="Slug")
        self.first_board = Board.objects.create(
            group=self.group,
            bo_subject="First slug board",
            bo_table="first-slug-board",
            bo_skin="basic",
            bo_mobile_skin="basic",
        )
        self.second_board = Board.objects.create(
            group=self.group,
            bo_subject="Second slug board",
            bo_table="second-slug-board",
            bo_skin="basic",
            bo_mobile_skin="basic",
        )

    def create_post(self, board, subject):
        return Post.objects.create(
            board=board,
            wr_subject=subject,
            wr_content="content",
            wr_name="writer",
            wr_datetime=timezone.now(),
        )

    def test_same_subject_can_use_same_slug_on_different_boards(self):
        first_post = self.create_post(self.first_board, "Shared title")
        second_post = self.create_post(self.second_board, "Shared title")

        self.assertEqual(first_post.wr_slug, "shared-title")
        self.assertEqual(second_post.wr_slug, "shared-title")

    def test_same_subject_gets_suffix_on_same_board(self):
        first_post = self.create_post(self.first_board, "Shared title")
        second_post = self.create_post(self.first_board, "Shared title")

        self.assertEqual(first_post.wr_slug, "shared-title")
        self.assertEqual(second_post.wr_slug, "shared-title-1")


class BoardLookupTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(gr_id="lookup", gr_subject="Lookup")
        self.board = Board.objects.create(
            group=self.group,
            bo_subject="Original board",
            bo_table="lookup-board",
            bo_skin="basic",
            bo_mobile_skin="basic",
        )

    def test_get_board_returns_fresh_values_after_update(self):
        first_board = get_board(pk=self.board.pk)
        self.assertEqual(first_board.bo_subject, "Original board")

        Board.objects.filter(pk=self.board.pk).update(bo_subject="Updated board")
        second_board = get_board(pk=self.board.pk)

        self.assertEqual(second_board.bo_subject, "Updated board")
        self.assertEqual(second_board.board_skin_path, "board/basic/")

    def test_get_board_does_not_store_function_row_cache(self):
        if hasattr(get_board, "row"):
            delattr(get_board, "row")

        get_board(pk=self.board.pk)

        self.assertFalse(hasattr(get_board, "row"))


class WriteFileFormUploadLimitTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(gr_id="upload", gr_subject="Upload")
        self.board = Board.objects.create(
            group=self.group,
            bo_subject="Upload board",
            bo_table="upload-board",
            bo_upload_size=4,
        )

    def test_uploaded_file_larger_than_board_limit_is_rejected(self):
        upload = SimpleUploadedFile(
            "too-large.pdf",
            b"12345",
            content_type="application/pdf",
        )

        form = WriteFileForm(data={}, files={"bf_file": upload}, board=self.board)

        self.assertFalse(form.is_valid())
        error = form.errors.as_data()["bf_file"][0]
        self.assertEqual(error.code, "file_too_large")
        self.assertIn("max_size", error.params)

    def test_zero_board_upload_limit_allows_file(self):
        self.board.bo_upload_size = 0
        upload = SimpleUploadedFile(
            "allowed.pdf",
            b"%PDF-1.7\n%%EOF",
            content_type="application/pdf",
        )

        form = WriteFileForm(data={}, files={"bf_file": upload}, board=self.board)

        self.assertTrue(form.is_valid(), form.errors)


class WriteFileFormContentValidationTests(TestCase):
    def setUp(self):
        self.group = Group.objects.create(gr_id="content", gr_subject="Content")
        self.board = Board.objects.create(
            group=self.group,
            bo_subject="Content board",
            bo_table="content-board",
            bo_upload_size=0,
        )

    def make_png_upload(self, name="image.png", content_type="image/png"):
        image_buffer = BytesIO()
        Image.new("RGB", (1, 1), color="white").save(image_buffer, format="PNG")
        return SimpleUploadedFile(
            name,
            image_buffer.getvalue(),
            content_type=content_type,
        )

    def test_valid_png_upload_is_allowed(self):
        form = WriteFileForm(
            data={},
            files={"bf_file": self.make_png_upload()},
            board=self.board,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_fake_image_upload_is_rejected(self):
        upload = SimpleUploadedFile(
            "fake.jpg",
            b"not really an image",
            content_type="image/jpeg",
        )

        form = WriteFileForm(data={}, files={"bf_file": upload}, board=self.board)

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors.as_data()["bf_file"][0].code,
            "invalid_file_content",
        )

    def test_image_content_must_match_extension(self):
        form = WriteFileForm(
            data={},
            files={"bf_file": self.make_png_upload("mismatch.jpg")},
            board=self.board,
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors.as_data()["bf_file"][0].code,
            "invalid_file_content",
        )

    def test_declared_mime_type_must_match_extension(self):
        form = WriteFileForm(
            data={},
            files={
                "bf_file": self.make_png_upload(
                    name="image.png",
                    content_type="text/plain",
                )
            },
            board=self.board,
        )

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors.as_data()["bf_file"][0].code,
            "invalid_file_content_type",
        )

    def test_fake_pdf_upload_is_rejected(self):
        upload = SimpleUploadedFile(
            "fake.pdf",
            b"not really a pdf",
            content_type="application/pdf",
        )

        form = WriteFileForm(data={}, files={"bf_file": upload}, board=self.board)

        self.assertFalse(form.is_valid())
        self.assertEqual(
            form.errors.as_data()["bf_file"][0].code,
            "invalid_file_content",
        )


class BbsDownloadSecurityTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.mkdtemp()
        self.override = override_settings(MEDIA_ROOT=self.media_root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, ignore_errors=True)

        self.group = Group.objects.create(gr_id="download", gr_subject="Download")
        self.board = Board.objects.create(
            group=self.group,
            bo_subject="Download board",
            bo_table="download-board",
        )
        self.post = Post.objects.create(
            board=self.board,
            wr_subject="Download post",
            wr_content="content",
            wr_name="writer",
            wr_datetime=timezone.now(),
        )
        self.other_board = Board.objects.create(
            group=self.group,
            bo_subject="Other download board",
            bo_table="other-download-board",
        )
        self.other_post = Post.objects.create(
            board=self.other_board,
            wr_subject="Other download post",
            wr_content="content",
            wr_name="writer",
            wr_datetime=timezone.now(),
        )
        self.post_file = Post_file.objects.create(
            board=self.board,
            post=self.post,
            bf_no=0,
            bf_file=SimpleUploadedFile(
                "report.pdf",
                b"%PDF-1.7\n%%EOF",
                content_type="application/pdf",
            ),
            bf_source="../reports/original report.pdf",
            bf_datetime=timezone.now(),
        )
        self.allow_download_from_post_view()

    def allow_download_from_post_view(self):
        session = self.client.session
        session[f"ss_view_{self.board.pk}_{self.post.pk}"] = True
        session.save()


    def test_bulk_delete_removes_stored_file_via_storage_api(self):
        stored_name = self.post_file.bf_file.name
        storage = self.post_file.bf_file.storage
        self.assertTrue(storage.exists(stored_name))

        with patch.object(storage, "delete", wraps=storage.delete) as delete_mock:
            Post_file.objects.filter(pk=self.post_file.pk).delete()

        delete_mock.assert_called_once_with(stored_name)
        self.assertFalse(storage.exists(stored_name))

    def test_replacing_post_file_removes_old_file_via_storage_api(self):
        old_name = self.post_file.bf_file.name
        storage = self.post_file.bf_file.storage
        self.assertTrue(storage.exists(old_name))

        with patch.object(storage, "delete", wraps=storage.delete) as delete_mock:
            self.post_file.bf_file = SimpleUploadedFile(
                "replacement.pdf",
                b"%PDF-1.7\n%%EOF",
                content_type="application/pdf",
            )
            self.post_file.save()

        delete_mock.assert_called_once_with(old_name)
        self.assertFalse(storage.exists(old_name))
        self.assertTrue(storage.exists(self.post_file.bf_file.name))

    def test_cleanup_post_files_reports_orphans_without_deleting(self):
        storage = self.post_file.bf_file.storage
        orphaned_name = f"{defaults.BBS_FILE_DIR}/{self.board.pk}/orphaned.pdf"
        storage.save(orphaned_name, ContentFile(b"%PDF-1.7\n%%EOF"))

        out = StringIO()
        call_command("cleanup_post_files", stdout=out)

        self.assertIn("Found 1 orphaned post file(s)", out.getvalue())
        self.assertTrue(storage.exists(orphaned_name))
        self.assertTrue(storage.exists(self.post_file.bf_file.name))

    def test_cleanup_post_files_deletes_orphans_when_requested(self):
        storage = self.post_file.bf_file.storage
        orphaned_name = f"{defaults.BBS_FILE_DIR}/{self.board.pk}/delete-me.pdf"
        storage.save(orphaned_name, ContentFile(b"%PDF-1.7\n%%EOF"))

        out = StringIO()
        call_command("cleanup_post_files", "--delete", stdout=out)

        self.assertIn("Deleted 1 orphaned post file(s)", out.getvalue())
        self.assertFalse(storage.exists(orphaned_name))
        self.assertTrue(storage.exists(self.post_file.bf_file.name))

    def test_cleanup_post_files_reports_missing_referenced_files(self):
        storage = self.post_file.bf_file.storage
        missing_name = self.post_file.bf_file.name
        storage.delete(missing_name)

        out = StringIO()
        call_command("cleanup_post_files", "--include-missing", stdout=out)

        self.assertIn("Found 1 missing referenced post file(s)", out.getvalue())
        self.assertIn("Found 0 orphaned post file(s)", out.getvalue())

    def test_clearing_post_file_uses_storage_api_without_field_path(self):
        stored_name = self.post_file.bf_file.name
        storage = self.post_file.bf_file.storage
        field_file_class = type(self.post_file.bf_file)

        with patch.object(
            field_file_class,
            "path",
            new_callable=PropertyMock,
            side_effect=AssertionError("FieldFile.path should not be used"),
        ):
            form = WriteFileForm(
                data={"bf_file-clear": "on"},
                files={},
                instance=self.post_file,
                board=self.board,
            )

            self.assertTrue(form.is_valid(), form.errors)

        self.assertFalse(storage.exists(stored_name))

    def test_copy_post_file_uses_storage_api_without_field_path(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="copy-admin",
            email="copy-admin@example.com",
            password="password",
        )
        field_file_class = type(self.post_file.bf_file)

        with patch.object(
            field_file_class,
            "path",
            new_callable=PropertyMock,
            side_effect=AssertionError("FieldFile.path should not be used"),
        ):
            mover = Board_Move_update(user, self.board, "copy")
            move_result = mover.check_move_update(
                self.post,
                self.board.pk,
                self.other_board.pk,
            )

        copied_post_id = move_result["insert_ids"][0]["post_id"]
        copied_file = Post_file.objects.get(
            board=self.other_board,
            post_id=copied_post_id,
        )

        self.assertTrue(
            self.post_file.bf_file.storage.exists(self.post_file.bf_file.name)
        )
        self.assertTrue(
            copied_file.bf_file.storage.exists(copied_file.bf_file.name)
        )
        copied_file.bf_file.open("rb")
        try:
            self.assertEqual(copied_file.bf_file.read(), b"%PDF-1.7\n%%EOF")
        finally:
            copied_file.bf_file.close()

    def test_copy_post_does_not_mutate_source_instance(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="copy-source-admin",
            email="copy-source-admin@example.com",
            password="password",
        )
        Post.objects.filter(pk=self.post.pk).update(wr_good=7, wr_nogood=3)
        self.post.refresh_from_db()
        original_state = {
            "pk": self.post.pk,
            "board_id": self.post.board_id,
            "wr_content": self.post.wr_content,
            "wr_good": self.post.wr_good,
            "wr_nogood": self.post.wr_nogood,
        }

        mover = Board_Move_update(user, self.board, "copy")
        move_result = mover.check_move_update(
            self.post,
            self.board.pk,
            self.other_board.pk,
        )

        self.assertEqual(self.post.pk, original_state["pk"])
        self.assertEqual(self.post.board_id, original_state["board_id"])
        self.assertEqual(self.post.wr_content, original_state["wr_content"])
        self.assertEqual(self.post.wr_good, original_state["wr_good"])
        self.assertEqual(self.post.wr_nogood, original_state["wr_nogood"])

        copied_post = Post.objects.get(pk=move_result["insert_ids"][0]["post_id"])
        self.assertEqual(copied_post.board_id, self.other_board.pk)
        self.assertEqual(copied_post.wr_good, 0)
        self.assertEqual(copied_post.wr_nogood, 0)
        self.assertTrue(
            copied_post.wr_content.startswith(original_state["wr_content"])
        )

    def test_copy_reply_chain_remaps_parent_ids(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="copy-reply-admin",
            email="copy-reply-admin@example.com",
            password="password",
        )
        reply = Post.objects.create(
            board=self.board,
            wr_subject="Reply post",
            wr_content="reply content",
            wr_name="writer",
            wr_parent=self.post.pk,
            wr_datetime=timezone.now(),
        )
        Post.objects.create(
            board=self.board,
            wr_subject="Nested reply post",
            wr_content="nested reply content",
            wr_name="writer",
            wr_parent=reply.pk,
            wr_datetime=timezone.now(),
        )

        mover = Board_Move_update(user, self.board, "copy")
        move_result = mover.check_move_update(
            self.post,
            self.board.pk,
            self.other_board.pk,
        )

        copied_root_id = move_result["insert_ids"][0]["post_id"]
        copied_reply = Post.objects.get(
            board=self.other_board,
            wr_subject="Reply post",
        )
        copied_nested_reply = Post.objects.get(
            board=self.other_board,
            wr_subject="Nested reply post",
        )

        self.assertEqual(copied_reply.wr_parent, copied_root_id)
        self.assertEqual(copied_nested_reply.wr_parent, copied_reply.pk)

    def test_copy_comments_remaps_parent_ids_and_keeps_sources(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="copy-comment-admin",
            email="copy-comment-admin@example.com",
            password="password",
        )
        parent_comment = Comment.objects.create(
            board=self.board,
            post=self.post,
            wr_content="parent comment",
            wr_name="commenter",
            wr_datetime=timezone.now(),
        )
        child_comment = Comment.objects.create(
            board=self.board,
            post=self.post,
            parent=parent_comment.pk,
            wr_content="child comment",
            wr_name="commenter",
            wr_datetime=timezone.now(),
        )
        grandchild_comment = Comment.objects.create(
            board=self.board,
            post=self.post,
            parent=child_comment.pk,
            wr_content="grandchild comment",
            wr_name="commenter",
            wr_datetime=timezone.now(),
        )
        source_comment_ids = {
            parent_comment.pk,
            child_comment.pk,
            grandchild_comment.pk,
        }

        mover = Board_Move_update(user, self.board, "copy")
        move_result = mover.check_move_update(
            self.post,
            self.board.pk,
            self.other_board.pk,
        )

        copied_post_id = move_result["insert_ids"][0]["post_id"]
        copied_parent_comment = Comment.objects.get(
            board=self.other_board,
            post_id=copied_post_id,
            wr_content="parent comment",
        )
        copied_child_comment = Comment.objects.get(
            board=self.other_board,
            post_id=copied_post_id,
            wr_content="child comment",
        )
        copied_grandchild_comment = Comment.objects.get(
            board=self.other_board,
            post_id=copied_post_id,
            wr_content="grandchild comment",
        )

        self.assertEqual(copied_parent_comment.parent, 0)
        self.assertEqual(copied_child_comment.parent, copied_parent_comment.pk)
        self.assertEqual(copied_grandchild_comment.parent, copied_child_comment.pk)
        self.assertEqual(
            set(
                Comment.objects.filter(
                    board=self.board,
                    post=self.post,
                ).values_list("pk", flat=True)
            ),
            source_comment_ids,
        )

    def test_copy_post_rolls_back_when_related_copy_fails(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="copy-rollback-admin",
            email="copy-rollback-admin@example.com",
            password="password",
        )
        existing_post_ids = set(
            Post.objects.filter(board=self.other_board).values_list("pk", flat=True)
        )
        existing_file_ids = set(
            Post_file.objects.filter(board=self.other_board).values_list(
                "pk",
                flat=True,
            )
        )

        with patch(
            "gnu_jango.bbs.bbs_libs.comment_copy",
            side_effect=RuntimeError("related copy failed"),
        ):
            mover = Board_Move_update(user, self.board, "copy")
            with self.assertRaises(RuntimeError):
                mover.check_move_update(
                    self.post,
                    self.board.pk,
                    self.other_board.pk,
                )

        self.assertEqual(
            set(
                Post.objects.filter(board=self.other_board).values_list(
                    "pk",
                    flat=True,
                )
            ),
            existing_post_ids,
        )
        self.assertEqual(
            set(
                Post_file.objects.filter(board=self.other_board).values_list(
                    "pk", flat=True
                )
            ),
            existing_file_ids,
        )

    def test_copy_state_is_isolated_between_move_instances(self):
        User = get_user_model()
        user = User.objects.create_user(
            username="copy-isolated-admin",
            email="copy-isolated-admin@example.com",
            password="password",
        )
        Post.objects.create(
            board=self.board,
            wr_subject="State reply",
            wr_content="state reply content",
            wr_name="writer",
            wr_parent=self.post.pk,
            wr_datetime=timezone.now(),
        )
        first_mover = Board_Move_update(user, self.board, "copy")
        first_result = first_mover.check_move_update(
            self.post,
            self.board.pk,
            self.other_board.pk,
        )
        self.assertEqual(sorted(first_result["insert_ids"].keys()), [0, 1])

        second_source = Post.objects.create(
            board=self.board,
            wr_subject="Independent source",
            wr_content="independent content",
            wr_name="writer",
            wr_datetime=timezone.now(),
        )
        second_mover = Board_Move_update(user, self.board, "copy")
        second_result = second_mover.check_move_update(
            second_source,
            self.board.pk,
            self.other_board.pk,
        )

        self.assertEqual(second_result["count_write"], 1)
        self.assertEqual(sorted(second_result["insert_ids"].keys()), [0])


#: Board/post/comment detail rendering moved from server-rendered Django views
#: to the Next.js SPA (core.views.nextjs25_short_board_theme serves the static
#: shell). Secret / read-level / cross-board access is now enforced by the API
#: (api.access.readable_post_queryset) and covered by
#: MainApiLatestTests.test_article_detail_hides_secret_post_without_session.
#: These Django-rendered-board assertions are therefore obsolete.
_BOARD_RENDER_MOVED_TO_SPA = (
    "Board detail rendering moved to the Next.js SPA; secret/level/cross-board "
    "access is now enforced by the API (api.access.readable_post_queryset)."
)


class BoardViewAccessTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(
            username="view-owner",
            email="view-owner@example.com",
            password="password",
        )
        self.group = Group.objects.create(gr_id="view", gr_subject="View")
        self.public_board = Board.objects.create(
            group=self.group,
            bo_subject="Public board",
            bo_table="public-view-board",
            bo_skin="basic",
            bo_mobile_skin="basic",
        )
        self.other_board = Board.objects.create(
            group=self.group,
            bo_subject="Other board",
            bo_table="other-view-board",
            bo_skin="basic",
            bo_mobile_skin="basic",
        )
        self.restricted_board = Board.objects.create(
            group=self.group,
            bo_subject="Restricted board",
            bo_table="restricted-view-board",
            bo_skin="basic",
            bo_mobile_skin="basic",
            bo_list_level=2,
            bo_read_level=2,
        )
        self.public_post = Post.objects.create(
            board=self.public_board,
            wr_subject="Public post",
            wr_content="Public content",
            wr_name="writer",
            wr_datetime=timezone.now(),
        )
        self.other_post = Post.objects.create(
            board=self.other_board,
            user=self.owner,
            wr_subject="Other post",
            wr_content="Other content",
            wr_name="writer",
            wr_datetime=timezone.now(),
        )
        self.secret_post = Post.objects.create(
            board=self.public_board,
            wr_subject="Secret post",
            wr_content="Secret content",
            wr_name="writer",
            wr_option="secret",
            wr_password=get_encrypt_string("open-sesame"),
            wr_datetime=timezone.now(),
        )
        self.secret_comment = Comment.objects.create(
            board=self.public_board,
            post=self.public_post,
            wr_content="Secret comment content",
            wr_name="commenter",
            wr_option="secret",
            wr_password=get_encrypt_string("comment-pass"),
            wr_datetime=timezone.now(),
        )
        self.guest_comment = Comment.objects.create(
            board=self.public_board,
            post=self.public_post,
            wr_content="Guest original content",
            wr_name="guest",
            wr_password=get_encrypt_string("guest-pass"),
            wr_datetime=timezone.now(),
        )
        self.other_comment = Comment.objects.create(
            board=self.other_board,
            post=self.other_post,
            user=self.owner,
            wr_content="Other comment content",
            wr_name="owner",
            wr_datetime=timezone.now(),
        )
        self.restricted_post = Post.objects.create(
            board=self.restricted_board,
            user=self.owner,
            wr_subject="Restricted post",
            wr_content="Protected content",
            wr_name="writer",
            wr_datetime=timezone.now(),
        )


    @skip(_BOARD_RENDER_MOVED_TO_SPA)
    def test_post_detail_cannot_be_loaded_through_another_board_url(self):
        response = self.client.get(
            reverse(
                "post_detail",
                kwargs={
                    "bo_table": self.public_board.bo_table,
                    "post_id": self.restricted_post.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"Protected content", response.content)


    @skip(_BOARD_RENDER_MOVED_TO_SPA)
    def test_secret_post_redirects_to_password_check_before_incrementing_hits(self):
        response = self.client.get(
            reverse(
                "post_detail",
                kwargs={
                    "bo_table": self.public_board.bo_table,
                    "post_id": self.secret_post.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn(
            reverse(
                "pwd_post",
                kwargs={
                    "bo_table": self.public_board.bo_table,
                    "post_id": self.secret_post.pk,
                },
            ),
            response["Location"],
        )
        self.assertIn("w=s", response["Location"])
        self.secret_post.refresh_from_db()
        self.assertEqual(self.secret_post.wr_hit, 0)


    @skip(_BOARD_RENDER_MOVED_TO_SPA)
    def test_secret_post_password_grants_read_session(self):
        password_response = self.client.post(
            reverse(
                "pwd_post",
                kwargs={
                    "bo_table": self.public_board.bo_table,
                    "post_id": self.secret_post.pk,
                },
            ),
            {"w": "s", "wr_password": "open-sesame"},
        )

        self.assertRedirects(
            password_response,
            reverse(
                "post_detail",
                kwargs={
                    "bo_table": self.public_board.bo_table,
                    "post_id": self.secret_post.pk,
                },
            ),
            fetch_redirect_response=False,
        )
        session_key = f"ss_secret_{self.public_board.pk}_{self.secret_post.wr_num}"
        self.assertTrue(self.client.session[session_key])

        detail_response = self.client.get(
            reverse(
                "post_detail",
                kwargs={
                    "bo_table": self.public_board.bo_table,
                    "post_id": self.secret_post.pk,
                },
            )
        )

        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Secret content")


    @skip(_BOARD_RENDER_MOVED_TO_SPA)
    def test_secret_comment_body_is_hidden_until_password_check(self):
        response = self.client.get(
            reverse(
                "post_detail",
                kwargs={
                    "bo_table": self.public_board.bo_table,
                    "post_id": self.public_post.pk,
                },
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Secret comment content")
        self.assertContains(response, "w=sc")
        self.assertContains(response, f"comment_id={self.secret_comment.pk}")


    @skip(_BOARD_RENDER_MOVED_TO_SPA)
    def test_secret_comment_password_grants_read_session(self):
        response = self.client.post(
            reverse(
                "pwd_post",
                kwargs={
                    "bo_table": self.public_board.bo_table,
                    "post_id": self.public_post.pk,
                },
            ),
            {
                "w": "sc",
                "comment_id": self.secret_comment.pk,
                "wr_password": "comment-pass",
            },
        )

        post_url = reverse(
            "post_detail",
            kwargs={
                "bo_table": self.public_board.bo_table,
                "post_id": self.public_post.pk,
            },
        )
        self.assertRedirects(
            response,
            f"{post_url}#c_{self.secret_comment.pk}",
            fetch_redirect_response=False,
        )
        session_key = f"ss_secret_comment_{self.public_board.pk}_{self.secret_comment.pk}"
        self.assertTrue(self.client.session[session_key])

        detail_response = self.client.get(post_url)

        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, "Secret comment content")


    @skip(_BOARD_RENDER_MOVED_TO_SPA)
    def test_guest_comment_update_rejects_wrong_password(self):
        with patch(
            "captcha.client.submit",
            return_value=SimpleNamespace(is_valid=True, error_codes=[], extra_data={}),
        ):
            response = self.client.post(
                reverse(
                    "write_comment",
                    kwargs={
                        "bo_table": self.public_board.bo_table,
                        "post_id": self.public_post.pk,
                    },
                ),
                {
                    "w": "cu",
                    "comment_id": self.guest_comment.pk,
                    "wr_content": "Wrong password content",
                    "wr_name": "guest",
                    "wr_password": "wrong-password",
                    "g-recaptcha-response": "PASSED",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.guest_comment.refresh_from_db()
        self.assertEqual(self.guest_comment.wr_content, "Guest original content")


class LegacyCKEditorEndpointTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff_user = User.objects.create_user(
            username="staff",
            email="staff@example.com",
            password="password",
            is_staff=True,
        )

    def test_staff_upload_requires_csrf_token(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.staff_user)
        upload = SimpleUploadedFile(
            "note.txt",
            b"not an image",
            content_type="text/plain",
        )

        response = csrf_client.post(reverse("ckeditor_upload"), {"upload": upload})

        self.assertEqual(response.status_code, 403)

    def test_ckeditor_upload_endpoint_is_retired(self):
        self.client.force_login(self.staff_user)
        upload = SimpleUploadedFile(
            "note.txt",
            b"not an image",
            content_type="text/plain",
        )

        response = self.client.post(reverse("ckeditor_upload"), {"upload": upload})

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["uploaded"], "0")
        self.assertIn("retired", response.json()["error"]["message"])
        self.assertEqual(Editor_attachments.objects.count(), 0)

    def test_ckeditor_browse_endpoint_is_retired(self):
        self.client.force_login(self.staff_user)

        response = self.client.get(reverse("ckeditor_browse"))

        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["uploaded"], "0")
        self.assertIn("retired", response.json()["error"]["message"])


