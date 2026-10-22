from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, override_settings

from gnu_jango.core.models import Notification, NotificationAnnouncement, NotificationWork
from gnu_jango.notifications.announcements import publish_announcement
from gnu_jango.notifications.outbox import process_one


@skipUnless(connection.vendor == "postgresql", "Requires PostgreSQL row locking")
@override_settings(NOTIFICATION_WS_ENABLED=False)
class NotificationConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username="concurrent-actor")
        self.recipient = get_user_model().objects.create_user(username="concurrent-recipient")

    def run_concurrently(self, task):
        barrier = Barrier(2)

        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                return task()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs = [pool.submit(run) for _ in range(2)]
            return [job.result(timeout=15) for job in jobs]

    def test_same_announcement_request_commits_only_once(self):
        values = {"title": "Concurrent", "body": "Hello", "href": "/", "recipient_ids": [self.recipient.pk]}
        result = self.run_concurrently(lambda: publish_announcement(self.actor, values, request_id="same-request"))
        self.assertEqual(result, [1, 1])
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(NotificationAnnouncement.objects.count(), 1)

    def test_two_workers_cannot_create_duplicate_inbox_rows(self):
        work = NotificationWork.objects.create(user=self.recipient, event_key="concurrent-event", kind="create", payload={"nt_title": "Hello"})
        result = self.run_concurrently(lambda: process_one(work.pk))
        self.assertEqual(result.count("completed"), 1)
        self.assertEqual(Notification.objects.count(), 1)
