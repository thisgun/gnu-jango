"""Hosts without a Celery worker (Vercel, PythonAnywhere, runserver) keep the direct paths.

BACKGROUND_JOBS_ENABLED defaults to False. In that mode no request may write an outbox row,
because nothing would ever process it: texts and mails go out on commit, and the cron
endpoint runs the scheduled commands inline. Transports are always replaced.
"""
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from gnu_jango.config.models import Config
from gnu_jango.core.admin.background import STALE_PENDING_MINUTES
from gnu_jango.shop.notifications import queue_order_placed_mails
from gnu_jango.shop.order_flow import move_order_status
from gnu_jango.shop.sms import notifications, service

from . import scheduled_jobs
from .background_models import BackgroundJob
from .models import MailCampaign
from .tasks import send_mail_campaign_task
from .test_deploy_profiles import CRON_URL, fake_runner
from .test_shop_sms import TRANSPORT, ShopSmsFixture, accepted

DIRECT_MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
CRON_SECRET = "s" * 32


class DefaultSettingsTests(SimpleTestCase):
    def test_background_jobs_are_off_unless_explicitly_enabled(self):
        self.assertFalse(settings.BACKGROUND_JOBS_ENABLED)
        self.assertEqual(settings.CELERY_BEAT_SCHEDULE, {})
        self.assertNotIn("delivery", settings.MAILERS)
        self.assertNotEqual(settings.MAILERS["default"]["BACKEND"], "gnu_jango.core.queued_mail.EmailBackend")
        self.assertNotIn("background_media_source", settings.STORAGES)
        self.assertNotIn("Queued", settings.STORAGES["default"]["BACKEND"])


@override_settings(BACKGROUND_JOBS_ENABLED=False)
class DirectSmsTests(ShopSmsFixture, TestCase):
    def test_order_placed_text_is_sent_on_commit_without_an_outbox_row(self):
        self.configure(de_sms_use2="1")
        order = self.make_order()
        with patch(TRANSPORT, side_effect=accepted) as send:
            with self.captureOnCommitCallbacks(execute=True):
                notifications.queue_order_placed_sms(order)

        self.assertEqual(send.call_count, 2)  # the order notice and the bank account text
        self.assertFalse(BackgroundJob.objects.exists())
        self.assertIn("접수", order.__class__.objects.get(pk=order.pk).od_shop_memo)

    def test_status_move_text_is_sent_on_commit_without_an_outbox_row(self):
        self.configure(de_sms_use4="1")
        order = self.make_order()
        with patch(TRANSPORT, side_effect=accepted) as send:
            with self.captureOnCommitCallbacks(execute=True):
                self.assertTrue(move_order_status(order, "입금").ok)

        send.assert_called_once()
        self.assertFalse(BackgroundJob.objects.exists())

    @override_settings(G5_SMS_RECIPIENT_HOURLY_LIMIT=2)
    def test_send_message_keeps_the_per_number_cap(self):
        self.configure()
        with patch(TRANSPORT, side_effect=accepted) as send:
            results = [service.send_message("010-3333-4444", "x") for _ in range(3)]

        self.assertEqual([result.status for result in results], ["accepted", "accepted", "rejected"])
        self.assertEqual(results[2].provider_code, "recipient_limit")
        self.assertEqual(send.call_count, 2)
        self.assertFalse(BackgroundJob.objects.exists())


@override_settings(BACKGROUND_JOBS_ENABLED=False, MAILERS=DIRECT_MAILERS)
class DirectMailTests(ShopSmsFixture, TestCase):
    def test_order_mails_are_sent_on_commit_without_an_outbox_row(self):
        for name, value in {"cf_email_use": "1", "cf_admin_email": "shop@example.com"}.items():
            Config.objects.update_or_create(name=name, defaults={"value": value})
        order = self.make_order(od_email="buyer@example.com")
        with self.captureOnCommitCallbacks(execute=True):
            queue_order_placed_mails(order)

        self.assertEqual(sorted(message.to[0] for message in mail.outbox), ["buyer@example.com", "shop@example.com"])
        self.assertFalse(BackgroundJob.objects.exists())

    def test_mail_campaign_task_delivers_directly(self):
        campaign = MailCampaign.objects.create(subject="Synthetic", body="Hello", recipient_count=1)
        result = send_mail_campaign_task(campaign.pk, [{"user_id": None, "email": "member@example.com"}])

        self.assertEqual(result["sent"], 1)
        self.assertEqual([message.to for message in mail.outbox], [["member@example.com"]])
        self.assertFalse(BackgroundJob.objects.exists())


class StaleBacklogWarningTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("jobs_admin", "jobs@example.com", "pw")
        self.client.force_login(self.admin)
        self.url = reverse("admin:core_backgroundjob_changelist")

    def make_job(self, minutes_ago):
        return BackgroundJob.objects.create(kind="sms", operation="sms", queue="communications", payload={"x": 1},
                                            available_at=timezone.now() - timedelta(minutes=minutes_ago))

    def warnings(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        return [str(message) for message in response.context["messages"]]

    @override_settings(BACKGROUND_JOBS_ENABLED=True)
    def test_fresh_jobs_do_not_warn(self):
        self.make_job(minutes_ago=1)
        self.assertEqual(self.warnings(), [])

    @override_settings(BACKGROUND_JOBS_ENABLED=True)
    def test_undrained_backlog_names_the_missing_worker(self):
        self.make_job(minutes_ago=STALE_PENDING_MINUTES + 1)
        self.assertTrue(any("Beat" in text and "1개" in text for text in self.warnings()))

    @override_settings(BACKGROUND_JOBS_ENABLED=False)
    def test_rows_left_after_switching_off_point_at_the_operator_command(self):
        self.make_job(minutes_ago=STALE_PENDING_MINUTES + 1)
        self.assertTrue(any("process_background_jobs --apply" in text for text in self.warnings()))


@override_settings(BACKGROUND_JOBS_ENABLED=False, CRON_SECRET=CRON_SECRET)
class DirectCronTests(TestCase):
    def test_cron_endpoint_runs_every_scheduled_job_inline(self):
        runner = fake_runner()
        with patch.object(scheduled_jobs, "default_runner", runner):
            response = APIClient().get(CRON_URL, HTTP_AUTHORIZATION=f"Bearer {CRON_SECRET}")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("queued", response.json()["data"])
        self.assertEqual([name for name, _ in runner.calls], list(scheduled_jobs.JOB_NAMES))
        self.assertFalse(BackgroundJob.objects.exists())
