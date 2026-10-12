from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.bbs.models import Board, Comment, Group, Post, Post_file


class BoardThreadDeletionTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.author = user_model.objects.create_user(
            username="thread-delete-author",
            email="thread-delete-author@example.com",
            password="password",
        )
        self.reply_author = user_model.objects.create_user(
            username="thread-delete-reply-author",
            email="thread-delete-reply-author@example.com",
            password="password",
        )
        self.board_admin = user_model.objects.create_user(
            username="thread-delete-board-admin",
            email="thread-delete-board-admin@example.com",
            password="password",
        )
        self.admin = user_model.objects.create_superuser(
            username="thread-delete-admin",
            email="thread-delete-admin@example.com",
            password="password",
        )

        self.group = Group.objects.create(
            gr_id="thread-delete-group",
            gr_subject="Thread deletion",
        )
        self.board = Board.objects.create(
            group=self.group,
            bo_subject="Thread deletion fixture",
            bo_table="thread-delete-fixture",
            bo_skin="basic",
            bo_mobile_skin="basic",
            bo_write_level=1,
            bo_reply_level=1,
        )

        self.author_client = APIClient()
        self.author_client.force_authenticate(user=self.author)
        self.reply_author_client = APIClient()
        self.reply_author_client.force_authenticate(user=self.reply_author)
        self.board_admin_client = APIClient()
        self.board_admin_client.force_authenticate(user=self.board_admin)
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self.posts_url = f"/api/v1/boards/{self.board.bo_table}/posts"

    def create_post(self, client, subject, reply_to=None):
        payload = {"wr_subject": subject, "wr_content": f"Content for {subject}"}
        if reply_to is not None:
            payload["reply_to"] = reply_to

        response = client.post(self.posts_url, payload, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        return response.data["data"]

    def delete_url(self, post):
        return f"/api/v1/posts/{self.board.bo_table}/{post['wr_id']}"

    def test_author_cannot_delete_thread_but_admin_deletes_all_thread_data(self):
        now = timezone.now()
        root_post = Post.objects.create(
            board=self.board,
            legacy_wr_id=9001,
            wr_num=-9001,
            wr_reply="",
            wr_parent=9001,
            wr_subject="Root",
            wr_content="Root content",
            wr_name="author",
            user=self.author,
            wr_datetime=now,
        )
        reply_post = Post.objects.create(
            board=self.board,
            legacy_wr_id=9002,
            wr_num=root_post.wr_num,
            wr_reply="A",
            wr_parent=9001,
            wr_subject="Reply",
            wr_content="Reply content",
            wr_name="author",
            user=self.author,
            wr_datetime=now,
        )
        nested_reply_post = Post.objects.create(
            board=self.board,
            legacy_wr_id=9003,
            wr_num=root_post.wr_num,
            wr_reply="AA",
            wr_parent=9001,
            wr_subject="Nested reply",
            wr_content="Nested reply content",
            wr_name="author",
            user=self.author,
            wr_datetime=now,
        )
        root = {"id": root_post.pk, "wr_id": root_post.legacy_wr_id}
        reply = {"id": reply_post.pk, "wr_id": reply_post.legacy_wr_id}
        nested_reply = {
            "id": nested_reply_post.pk,
            "wr_id": nested_reply_post.legacy_wr_id,
        }
        comment = Comment.objects.create(
            board=self.board,
            post_id=nested_reply["id"],
            wr_content="Comment on nested reply",
            wr_name="commenter",
            wr_datetime=timezone.now(),
        )
        post_file = Post_file.objects.create(
            board=self.board,
            post_id=nested_reply["id"],
            bf_source="attachment.txt",
            bf_datetime=timezone.now(),
        )
        other_board = Board.objects.create(
            group=self.group,
            bo_subject="Other board",
            bo_table="thread-delete-other",
            bo_skin="basic",
            bo_mobile_skin="basic",
        )
        cross_board_post = Post.objects.create(
            board=other_board,
            wr_parent=root_post.legacy_wr_id,
            wr_subject="Unrelated post with a colliding parent reference",
            wr_name="other writer",
            wr_datetime=timezone.now(),
        )

        owner_response = self.author_client.delete(self.delete_url(root))
        self.assertEqual(owner_response.status_code, 409, owner_response.data)
        self.assertTrue(Post.objects.filter(pk=root["id"]).exists())
        self.assertTrue(Post.objects.filter(pk=reply["id"]).exists())
        self.assertTrue(Post.objects.filter(pk=nested_reply["id"]).exists())

        admin_response = self.admin_client.delete(self.delete_url(root))
        self.assertEqual(admin_response.status_code, 200, admin_response.data)
        self.assertEqual(
            set(admin_response.data["data"]["deleted_ids"]),
            {root["wr_id"], reply["wr_id"], nested_reply["wr_id"]},
        )
        self.assertFalse(Post.objects.filter(pk__in=[root["id"], reply["id"], nested_reply["id"]]).exists())
        self.assertFalse(Comment.objects.filter(pk=comment.pk).exists())
        self.assertFalse(Post_file.objects.filter(pk=post_file.pk).exists())
        self.assertTrue(Post.objects.filter(pk=cross_board_post.pk, board=other_board).exists())

        self.board.refresh_from_db()
        self.assertEqual(self.board.bo_count_write, 0)
        self.assertEqual(self.board.bo_count_comment, 0)

    def test_board_admin_cannot_delete_descendant_above_their_member_level(self):
        self.board_admin.profile.user_level = 2
        self.board_admin.profile.save(update_fields=["user_level"])
        self.reply_author.profile.user_level = 5
        self.reply_author.profile.save(update_fields=["user_level"])
        self.board.bo_admin = self.board_admin.username
        self.board.save(update_fields=["bo_admin"])

        root = self.create_post(self.author_client, "Root")
        reply = self.create_post(
            self.reply_author_client, "High-level reply", reply_to=root["wr_id"]
        )

        response = self.board_admin_client.delete(self.delete_url(root))

        self.assertEqual(response.status_code, 403, response.data)
        self.assertTrue(Post.objects.filter(pk=root["id"]).exists())
        self.assertTrue(Post.objects.filter(pk=reply["id"]).exists())

    def test_admin_deleting_reply_removes_only_its_nested_branch(self):
        root = self.create_post(self.author_client, "Root")
        first_reply = self.create_post(
            self.author_client, "First reply", reply_to=root["wr_id"]
        )
        nested_reply = self.create_post(
            self.author_client, "Nested reply", reply_to=first_reply["wr_id"]
        )
        sibling_reply = self.create_post(
            self.author_client, "Sibling reply", reply_to=root["wr_id"]
        )

        response = self.admin_client.delete(self.delete_url(first_reply))

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            set(response.data["data"]["deleted_ids"]),
            {first_reply["wr_id"], nested_reply["wr_id"]},
        )
        self.assertTrue(Post.objects.filter(pk=root["id"]).exists())
        self.assertFalse(
            Post.objects.filter(pk__in=[first_reply["id"], nested_reply["id"]]).exists()
        )
        self.assertTrue(Post.objects.filter(pk=sibling_reply["id"]).exists())
