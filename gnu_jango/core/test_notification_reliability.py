"""Regressions for source isolation, retries, administrator idempotency and imports."""

import uuid
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from gnu_jango.bbs.models import Board, Comment, Group, Post
from gnu_jango.core.management.commands.migrate_gnuboard5 import Command as ImportCommand
from gnu_jango.core.models import Notification, NotificationAnnouncement, NotificationWork
from gnu_jango.notifications.announcements import AnnouncementForm, publish_announcement
from gnu_jango.notifications.context import events_suppressed, suppress_notification_events
from gnu_jango.notifications.delivery import invalidate_on_commit
from gnu_jango.notifications.outbox import event_on_commit, process_pending
from gnu_jango.shop.models import ShopOrder
from gnu_jango.users.models import User_Memo


class Fixtures:
    def make_fixtures(self):
        users = get_user_model().objects
        self.alice = users.create_user(username="nr-alice")
        self.bob = users.create_user(username="nr-bob")
        self.carol = users.create_user(username="nr-carol")
        self.group = Group.objects.create(gr_id="nr", gr_subject="Notifications")
        self.board = Board.objects.create(group=self.group, bo_table="nr", bo_subject="Notifications")
        self.post = Post.objects.create(board=self.board, user=self.alice, wr_datetime=timezone.now(), legacy_wr_id=12345)

    def comment(self, **values):
        return Comment.objects.create(board=self.board, post=self.post, wr_datetime=timezone.now(), **values)


@override_settings(NOTIFICATION_WS_ENABLED=False)
class NotificationEventsTests(Fixtures, TestCase):
    def setUp(self):
        self.make_fixtures()

    def test_comment_uses_public_id_and_does_not_copy_private_content(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.comment(user=self.bob, wr_content="private content", wr_option="secret")
        note = Notification.objects.get(user=self.alice)
        self.assertEqual(note.nt_data["post_id"], 12345)
        self.assertNotIn("private content", str(note.nt_data) + note.nt_body)

    def test_parent_and_post_owner_receive_one_each(self):
        with suppress_notification_events():
            parent = self.comment(user=self.bob)
        with self.captureOnCommitCallbacks(execute=True):
            self.comment(user=self.carol, parent=parent.pk)
        self.assertEqual(set(Notification.objects.values_list("user_id", flat=True)), {self.alice.pk, self.bob.pk})

    def test_same_parent_and_post_owner_is_deduplicated(self):
        with suppress_notification_events():
            parent = self.comment(user=self.alice)
        with self.captureOnCommitCallbacks(execute=True):
            self.comment(user=self.bob, parent=parent.pk)
        self.assertEqual(Notification.objects.count(), 1)

    def test_self_comment_has_no_notification(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.comment(user=self.alice)
        self.assertFalse(NotificationWork.objects.exists())

    def test_guest_comment_notifies_owner(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.comment()
        self.assertEqual(Notification.objects.get().user_id, self.alice.pk)

    def test_comment_update_does_not_notify_again(self):
        with self.captureOnCommitCallbacks(execute=True):
            comment = self.comment(user=self.bob)
            comment.wr_content = "updated"
            comment.save()
        self.assertEqual(Notification.objects.count(), 1)

    def test_rolled_back_comment_has_no_work(self):
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(ValueError), transaction.atomic():
                self.comment(user=self.bob)
                raise ValueError("rollback")
        self.assertFalse(NotificationWork.objects.exists())

    def test_received_memo_only(self):
        with self.captureOnCommitCallbacks(execute=True):
            User_Memo.objects.create(user=self.alice, me_send_id=self.bob.pk, me_type="recv")
            User_Memo.objects.create(user=self.bob, me_send_id=99, me_type="send")
        self.assertEqual(Notification.objects.get().user_id, self.alice.pk)

    def test_self_memo_has_no_notification(self):
        with self.captureOnCommitCallbacks(execute=True):
            User_Memo.objects.create(user=self.alice, me_send_id=self.alice.pk, me_type="recv")
        self.assertFalse(NotificationWork.objects.exists())

    def test_order_status_alias_is_not_a_change(self):
        order = ShopOrder.objects.create(od_id="nr", user=self.alice, od_status="paid")
        with self.captureOnCommitCallbacks(execute=True):
            order.od_status = "입금"
            order.save(update_fields=["od_status"])
        self.assertFalse(NotificationWork.objects.exists())

    def test_order_status_cycle_creates_distinct_events(self):
        order = ShopOrder.objects.create(od_id="nr", user=self.alice)
        with self.captureOnCommitCallbacks(execute=True):
            for status in ("입금", "준비", "입금"):
                order.od_status = status
                order.save(update_fields=["od_status"])
        self.assertEqual(Notification.objects.count(), 3)

    def test_order_unrelated_field_update_does_not_notify(self):
        order = ShopOrder.objects.create(od_id="nr", user=self.alice)
        with self.captureOnCommitCallbacks(execute=True):
            order.od_status = "입금"
            order.od_name = "Alice"
            order.save(update_fields=["od_name"])
        self.assertFalse(NotificationWork.objects.exists())

    def test_event_retry_is_idempotent(self):
        with self.captureOnCommitCallbacks(execute=True):
            for _ in range(2):
                event_on_commit(self.alice.pk, "test-event", {"nt_title": "Hello"})
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(NotificationWork.objects.count(), 1)

    @override_settings(NOTIFICATION_WS_ENABLED=True)
    def test_request_only_queues_hint_and_never_contacts_redis(self):
        with patch("gnu_jango.notifications.outbox._send_hint", side_effect=AssertionError("network")):
            with self.captureOnCommitCallbacks(execute=True):
                invalidate_on_commit(self.alice.pk)
        self.assertEqual(NotificationWork.objects.get().kind, "hint")

    def test_suppression_is_nested_and_restored_after_exception(self):
        with self.assertRaises(ValueError), suppress_notification_events():
            with suppress_notification_events():
                self.assertTrue(events_suppressed())
            self.assertTrue(events_suppressed())
            raise ValueError
        self.assertFalse(events_suppressed())

    def test_imported_comment_cannot_emit_events(self):
        importer = ImportCommand()
        importer.legacy_user = lambda value: self.bob
        importer.write_option = lambda value: "both"
        with self.captureOnCommitCallbacks(execute=True):
            importer.upsert_comment(self.board, self.post, {"wr_id": "7", "wr_datetime": "2026-01-01 12:00:00", "wr_content": "old"})
        self.assertTrue(Comment.objects.exists())
        self.assertFalse(NotificationWork.objects.exists())

    def test_imported_memo_cannot_emit_events(self):
        importer = ImportCommand()
        importer.legacy_user = lambda name: self.alice if name == "alice" else self.bob
        with self.captureOnCommitCallbacks(execute=True):
            importer.import_memos([{"me_id": "700", "me_recv_mb_id": "alice", "me_send_mb_id": "bob", "me_type": "recv"}])
        self.assertTrue(User_Memo.objects.exists())
        self.assertFalse(NotificationWork.objects.exists())


@override_settings(NOTIFICATION_WS_ENABLED=False)
class NotificationPaymentIsolationTests(Fixtures, TransactionTestCase):
    def setUp(self):
        self.make_fixtures()

    def test_inbox_error_does_not_rollback_confirmed_payment_and_retries(self):
        from gnu_jango.api.shop_payments import confirm_order_payment

        order = ShopOrder.objects.create(od_id="nr-payment", user=self.alice, od_cart_price=1000, od_receipt_price=1000)
        with patch("gnu_jango.notifications.outbox.Notification") as inbox:
            inbox.objects.using.return_value.get_or_create.side_effect = IntegrityError("inbox unavailable")
            paid, error = confirm_order_payment(order.pk, 1000, "test", "test-transaction", {})
        self.assertIsNone(error)
        self.assertIsNotNone(paid)
        order.refresh_from_db()
        self.assertIn(order.od_status, ("입금", "paid"))
        work = NotificationWork.objects.get(kind="create")
        self.assertEqual(work.attempts, 1)
        self.assertIsNone(work.completed_at)
        NotificationWork.objects.filter(pk=work.pk).update(available_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(process_pending()["completed"], 1)
        self.assertEqual(Notification.objects.get().user_id, self.alice.pk)

    def test_outbox_enqueue_error_cannot_rollback_source(self):
        order = ShopOrder.objects.create(od_id="nr-outbox", user=self.alice)
        with patch("gnu_jango.notifications.outbox.NotificationWork") as work:
            work.objects.using.return_value.get_or_create.side_effect = IntegrityError("outbox unavailable")
            with transaction.atomic():
                order.od_status = "입금"
                order.save(update_fields=["od_status"])
        order.refresh_from_db()
        self.assertEqual(order.od_status, "입금")


@override_settings(NOTIFICATION_WS_ENABLED=False)
class AnnouncementReliabilityTests(Fixtures, TestCase):
    def setUp(self):
        self.make_fixtures()
        self.values = {"title": "Notice", "body": "Hello", "href": "/", "recipient_ids": [self.alice.pk, self.bob.pk]}
        self.request_id = uuid.uuid4().hex

    def test_cache_eviction_does_not_resend(self):
        publish_announcement(self.carol, self.values, request_id=self.request_id)
        cache.clear()
        publish_announcement(self.carol, self.values, request_id=self.request_id)
        self.assertEqual(Notification.objects.count(), 2)
        self.assertEqual(NotificationAnnouncement.objects.get().status, "sent")

    def test_changed_request_body_is_rejected(self):
        publish_announcement(self.carol, self.values, request_id=self.request_id)
        with self.assertRaisesMessage(Exception, "이미 처리한"):
            publish_announcement(self.carol, {**self.values, "title": "Changed"}, request_id=self.request_id)
        self.assertEqual(Notification.objects.count(), 2)

    def test_failed_batch_rolls_back_request_id_and_can_be_retried(self):
        with patch("gnu_jango.notifications.announcements.Notification") as inbox:
            inbox.objects.bulk_create.side_effect = IntegrityError("inbox unavailable")
            with self.assertRaises(IntegrityError):
                publish_announcement(self.carol, self.values, request_id=self.request_id)
        self.assertFalse(NotificationAnnouncement.objects.exists())
        publish_announcement(self.carol, self.values, request_id=self.request_id)
        self.assertEqual(Notification.objects.count(), 2)

    def test_external_link_is_rejected(self):
        form = AnnouncementForm({"send_token": "x", "title": "Notice", "body": "Hello", "audience": "active", "confirm": True, "href": "//evil.test"})
        self.assertFalse(form.is_valid())
        self.assertIn("href", form.errors)

    def test_staff_without_add_permission_is_rejected(self):
        self.carol.is_staff = True
        self.carol.save(update_fields=["is_staff"])
        self.client.force_login(self.carol)
        self.assertEqual(self.client.get("/admin/core/notification/announce/").status_code, 403)

    def test_admin_page_repeated_post_has_one_batch(self):
        self.carol.is_staff = self.carol.is_superuser = True
        self.carol.save(update_fields=["is_staff", "is_superuser"])
        self.client.force_login(self.carol)
        url = "/admin/core/notification/announce/"
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        values = {"title": "Notice", "body": "Hello", "href": "/", "audience": "selected", "usernames": self.alice.username, "confirm": True,
                  "send_token": response.context["form"].initial["send_token"]}
        for _ in range(2):
            self.assertEqual(self.client.post(url, values).status_code, 302)
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(NotificationAnnouncement.objects.count(), 1)
