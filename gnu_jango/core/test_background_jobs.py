"""Outbox regression tests. External delivery is replaced; use a disposable test DB."""
import base64
import hashlib
import io
import json
import smtplib
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import Mock, patch

from django.core import mail
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.mail import EmailMultiAlternatives
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone
from PIL import Image

from . import background as jobs
from .background_models import BackgroundJob
from .queued_mail import StoredEmail, queue_message


MAILERS = {
    "default": {"BACKEND": "gnu_jango.core.queued_mail.EmailBackend"},
    "delivery": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"},
}
STORAGES = {
    "default": {"BACKEND": "gnu_jango.core.queued_storage.QueuedFileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    "background_media_source": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "background_media_writer": {
        "BACKEND": "django.core.files.storage.FileSystemStorage", "OPTIONS": {"allow_overwrite": True},
    },
}


@override_settings(BACKGROUND_JOBS_ENABLED=True)
class OutboxTests(TestCase):
    def test_enqueue_does_not_publish(self):
        with patch("example.celery.app.send_task") as publish:
            job = jobs.enqueue("mail", {"private": "message"})
        publish.assert_not_called()
        self.assertEqual(job.status, "pending")

    def test_transaction_rollback_discards_job(self):
        with self.assertRaises(RuntimeError), transaction.atomic():
            jobs.enqueue("mail", {"private": "message"})
            raise RuntimeError("rollback")
        self.assertFalse(BackgroundJob.objects.exists())

    def test_dedupe_and_active_keys(self):
        first = jobs.enqueue("scheduled", {"name": "save_order_points"}, dedupe_key="one", active_key="active")
        self.assertEqual(jobs.enqueue("scheduled", {}, dedupe_key="one").pk, first.pk)
        self.assertEqual(jobs.enqueue("scheduled", {}, active_key="active").pk, first.pk)

    def test_invalid_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            jobs.enqueue("arbitrary_callable", {})

    def test_health_check_command_flags_dead_letters(self):
        job = jobs.enqueue("mail", {"private": "message"})
        BackgroundJob.objects.filter(pk=job.pk).update(status="dead", error_code="smtp_550")
        output = io.StringIO()
        with self.assertRaises(CommandError):
            call_command("process_background_jobs", "--check", stdout=output)
        report = json.loads(output.getvalue())
        self.assertFalse(report["ok"])
        self.assertEqual(report["dead"], 1)

    def test_health_check_command_flags_stale_pending_jobs(self):
        job = jobs.enqueue("scheduled", {"name": "save_order_points"})
        BackgroundJob.objects.filter(pk=job.pk).update(
            available_at=timezone.now() - timedelta(minutes=20)
        )
        output = io.StringIO()
        with self.assertRaises(CommandError):
            call_command("process_background_jobs", "--check", stdout=output)
        report = json.loads(output.getvalue())
        self.assertFalse(report["ok"])
        self.assertEqual(report["stale_pending"], 1)

    def test_health_check_command_passes_when_queue_is_clear(self):
        output = io.StringIO()
        call_command("process_background_jobs", "--check", stdout=output)
        report = json.loads(output.getvalue())
        self.assertTrue(report["ok"])
        self.assertEqual(report["dead"], 0)
        self.assertEqual(report["stale_pending"], 0)

    def test_recurring_job_is_deduplicated(self):
        self.assertEqual(jobs.enqueue_scheduled("save_order_points").pk,
                         jobs.enqueue_scheduled("save_order_points").pk)

    def test_success_scrubs_payload_and_duplicate_skips(self):
        job = jobs.enqueue("scheduled", {"name": "save_order_points"}, active_key="one")
        with patch("gnu_jango.core.background_handlers.handle") as handler:
            self.assertEqual(jobs.execute_job(job.pk)["status"], "succeeded")
            self.assertEqual(jobs.execute_job(job.pk)["status"], "skipped")
        handler.assert_called_once()
        job.refresh_from_db()
        self.assertEqual(job.payload, {})
        self.assertIsNone(job.active_key)
        self.assertIsNone(job.claim_token)
        self.assertEqual(job.attempts, 1)

    def test_transient_failure_is_delayed_and_bounded(self):
        job = jobs.enqueue("scheduled", {"name": "save_order_points"}, max_attempts=2)
        with patch("gnu_jango.core.background_handlers.handle", side_effect=RuntimeError("private details")):
            result = jobs.execute_job(job.pk)
            self.assertEqual(result["status"], "pending")
            self.assertTrue(15 <= result["retry_in"] <= 25)
            self.assertEqual(jobs.execute_job(job.pk)["status"], "skipped")
            BackgroundJob.objects.filter(pk=job.pk).update(available_at=timezone.now())
            self.assertEqual(jobs.execute_job(job.pk)["status"], "dead")
        job.refresh_from_db()
        self.assertEqual(job.error_code, "RuntimeError")
        self.assertEqual(job.attempts, 2)

    def test_permanent_failure_stops_immediately(self):
        job = jobs.enqueue("scheduled", {})
        with patch("gnu_jango.core.background_handlers.handle", side_effect=jobs.PermanentJobError(code="rejected")):
            self.assertEqual(jobs.execute_job(job.pk)["status"], "dead")
        job.refresh_from_db()
        self.assertEqual(job.error_code, "rejected")

    def test_unknown_delivery_outcome_requires_explicit_replay(self):
        for kind in ("mail", "sms"):
            with self.subTest(kind=kind):
                job = jobs.enqueue(kind, {"private": "payload"})
                with patch("gnu_jango.core.background_handlers.handle", side_effect=OSError("connection lost")):
                    self.assertEqual(jobs.execute_job(job.pk)["status"], "dead")
                job.refresh_from_db()
                self.assertEqual(job.error_code, "delivery_uncertain")
                self.assertFalse(jobs.replay(job))
                self.assertTrue(jobs.replay(job, allow_uncertain=True))

    def test_known_non_delivery_can_retry(self):
        job = jobs.enqueue("mail", {"private": "payload"})
        with patch("gnu_jango.core.background_handlers.handle", side_effect=jobs.RetryableJobError()):
            self.assertEqual(jobs.execute_job(job.pk)["status"], "pending")

    def test_expired_leases_retry_safe_jobs_but_quarantine_deliveries(self):
        for kind, status in (("scheduled", "pending"), ("mail", "dead"), ("sms", "dead")):
            job = jobs.enqueue(kind, {"name": "save_order_points"})
            BackgroundJob.objects.filter(pk=job.pk).update(status="running", attempts=1,
                claim_token=uuid.uuid4(), lease_until=timezone.now() - timedelta(seconds=1))
            jobs.recover_expired()
            job.refresh_from_db()
            self.assertEqual(job.status, status)

    def test_broker_failure_keeps_pending_row(self):
        job = jobs.enqueue("mail", {"private": "payload"})
        with patch("example.celery.app.send_task", side_effect=ConnectionError("offline")):
            self.assertEqual(jobs.dispatch_due(), {"published": 0})
        job.refresh_from_db()
        self.assertIsNone(job.dispatched_at)
        self.assertEqual(job.status, "pending")

    def test_broker_receives_uuid_only_and_stale_delivery_is_republished(self):
        job = jobs.enqueue("mail", {"private": "payload"})
        with patch("example.celery.app.send_task") as publish:
            self.assertEqual(jobs.dispatch_due()["published"], 1)
            self.assertEqual(publish.call_args.kwargs["args"], [str(job.pk)])
            self.assertNotIn("payload", str(publish.call_args))
            self.assertEqual(jobs.dispatch_due()["published"], 0)
            BackgroundJob.objects.filter(pk=job.pk).update(dispatched_at=timezone.now() - timedelta(minutes=2))
            self.assertEqual(jobs.dispatch_due()["published"], 1)

    def test_stale_worker_cannot_complete_new_claim(self):
        job = jobs.enqueue("scheduled", {})
        replacement = uuid.uuid4()
        def steal_claim(row):
            BackgroundJob.objects.filter(pk=row.pk).update(claim_token=replacement)
        with patch("gnu_jango.core.background_handlers.handle", side_effect=steal_claim):
            self.assertEqual(jobs.execute_job(job.pk)["status"], "lease_lost")
        job.refresh_from_db()
        self.assertEqual(job.status, "running")
        self.assertEqual(job.claim_token, replacement)

    def test_replay_respects_active_resource_owner(self):
        old = jobs.enqueue("scheduled", {"name": "save_order_points"})
        BackgroundJob.objects.filter(pk=old.pk).update(status="dead")
        old.refresh_from_db()
        jobs.enqueue("scheduled", old.payload, active_key="scheduled:save_order_points")
        self.assertFalse(jobs.replay(old))

    def test_replay_rechecks_delivery_outcome_after_stale_admin_read(self):
        job = jobs.enqueue("mail", {"private": "message"})
        BackgroundJob.objects.filter(pk=job.pk).update(status="dead", error_code="smtp_550")
        job.refresh_from_db()
        # Another operator already retried this row and the outcome is now unknown.
        BackgroundJob.objects.filter(pk=job.pk).update(error_code="delivery_uncertain")
        self.assertFalse(jobs.replay(job))

    def test_replay_rechecks_payload_after_retention_scrub(self):
        job = jobs.enqueue("mail", {"private": "message"})
        BackgroundJob.objects.filter(pk=job.pk).update(status="dead")
        job.refresh_from_db()
        BackgroundJob.objects.filter(pk=job.pk).update(payload={})
        self.assertFalse(jobs.replay(job, allow_uncertain=True))

    def test_retention_scrubs_private_data_before_metadata_deletion(self):
        job = jobs.enqueue("mail", {"private": "message"})
        BackgroundJob.objects.filter(pk=job.pk).update(status="dead", finished_at=timezone.now() - timedelta(days=8))
        self.assertEqual(jobs.purge_finished(), {"scrubbed": 1, "deleted": 0})
        job.refresh_from_db()
        self.assertEqual(job.payload, {})
        self.assertFalse(jobs.replay(job, allow_uncertain=True))
        BackgroundJob.objects.filter(pk=job.pk).update(finished_at=timezone.now() - timedelta(days=31))
        self.assertEqual(jobs.purge_finished()["deleted"], 1)

    def test_expired_message_is_never_sent(self):
        job = jobs.enqueue("mail", {"private": "message"})
        BackgroundJob.objects.filter(pk=job.pk).update(created_at=timezone.now() - timedelta(days=2))
        with patch("gnu_jango.core.background_handlers._mail") as send:
            self.assertEqual(jobs.execute_job(job.pk)["status"], "dead")
        send.assert_not_called()
        job.refresh_from_db()
        self.assertEqual(job.error_code, "payload_expired")


@override_settings(BACKGROUND_JOBS_ENABLED=True, MAILERS=MAILERS)
class QueuedMailTests(TestCase):
    def message(self):
        message = EmailMultiAlternatives("Synthetic subject", "plain body", "sender@example.invalid",
            ["to@example.invalid"], bcc=["hidden@example.invalid"])
        message.attach_alternative("<p>HTML body</p>", "text/html")
        message.attach("sample.txt", b"attachment", "text/plain")
        return message

    def test_mime_and_private_bcc_envelope_survive_queue(self):
        message = self.message()
        with patch("gnu_jango.core.background_handlers._mail") as deliver:
            self.assertEqual(message.send(), 1)
        deliver.assert_not_called()
        job = BackgroundJob.objects.get()
        stored = StoredEmail(job.payload)
        parsed = stored.message()
        self.assertEqual(stored.recipients(), message.recipients())
        self.assertIsNone(parsed["Bcc"])
        self.assertEqual(len(list(parsed.iter_attachments())), 1)
        self.assertIn("HTML body", parsed.get_body(preferencelist=("html",)).get_content())

    def test_worker_delivers_and_scrubs(self):
        job = queue_message(self.message())
        self.assertEqual(jobs.execute_job(job.pk)["status"], "succeeded")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("hidden@example.invalid", mail.outbox[0].recipients())
        job.refresh_from_db()
        self.assertEqual(job.payload, {})

    def test_delivery_failures_are_classified(self):
        from .background_handlers import _mail
        for phase, error, expected in (
            ("open", OSError(), jobs.RetryableJobError),
            ("send_messages", OSError(), jobs.DeliveryUncertain),
            ("send_messages", smtplib.SMTPDataError(451, b"temporary"), jobs.RetryableJobError),
            ("send_messages", smtplib.SMTPDataError(550, b"rejected"), jobs.PermanentJobError),
            ("send_messages", smtplib.SMTPRecipientsRefused({"to": (450, b"retry")}), jobs.RetryableJobError),
        ):
            with self.subTest(phase=phase, error=type(error).__name__):
                backend = Mock()
                getattr(backend, phase).side_effect = error
                with patch("gnu_jango.core.background_handlers.mailers", {"delivery": backend}):
                    with self.assertRaises(expected):
                        _mail(queue_message(self.message()))

    def test_quit_failure_does_not_resend_accepted_mail(self):
        backend = Mock()
        backend.send_messages.return_value = 1
        backend.close.side_effect = OSError("QUIT disconnected")
        with patch("gnu_jango.core.background_handlers.mailers", {"delivery": backend}):
            self.assertEqual(jobs.execute_job(queue_message(self.message()).pk)["status"], "succeeded")

    def test_campaign_deduplicates_recipients_and_counts_completion(self):
        from .models import MailCampaign
        from .queued_mail import queue_campaign
        campaign = MailCampaign.objects.create(subject="Synthetic", body="body", status="sending")
        self.assertEqual(queue_campaign(campaign.pk, [{"email": "one@example.invalid"},
            {"email": "ONE@example.invalid"}, {"email": "two@example.invalid"}]), 2)
        for job in BackgroundJob.objects.all():
            self.assertEqual(jobs.execute_job(job.pk)["status"], "succeeded")
        campaign.refresh_from_db()
        self.assertEqual((campaign.status, campaign.sent_count, campaign.failed_count), ("sent", 2, 0))
        self.assertEqual(campaign.logs.count(), 2)


@override_settings(BACKGROUND_JOBS_ENABLED=True)
class QueuedSmsTests(TestCase):
    def test_request_queues_without_calling_transport(self):
        from gnu_jango.shop.sms import service
        with patch("gnu_jango.shop.sms.service.icode.send_message") as transport:
            result = service.send_message("01012345678", "Synthetic", current=service.SmsSettings(callback="0212345678"))
        transport.assert_not_called()
        self.assertEqual(result.status, "queued")
        self.assertTrue(BackgroundJob.objects.filter(pk=result.provider_code, kind="sms").exists())

    def test_parent_fanout_deduplicates_children(self):
        from gnu_jango.shop.sms import service
        for _ in range(2):
            service.send_message("01012345678", "Synthetic", current=service.SmsSettings(), background_parent="same-parent")
        self.assertEqual(BackgroundJob.objects.filter(kind="sms").count(), 1)

    def test_known_non_delivery_retries_and_unknown_quarantines(self):
        from gnu_jango.shop.sms import service
        from gnu_jango.shop.sms.icode import ICodeSendResult
        for result, expected in ((ICodeSendResult("rejected", "connect_timeout"), "pending"),
                                 (ICodeSendResult("rejected", "guard_unavailable"), "pending"),
                                 (ICodeSendResult("unknown", "timeout"), "dead")):
            queued = service.send_message("01012345678", "Synthetic", current=service.SmsSettings())
            with patch("gnu_jango.shop.sms.service._send_message_now", return_value=result):
                self.assertEqual(jobs.execute_job(queued.provider_code)["status"], expected)


@override_settings(BACKGROUND_JOBS_ENABLED=True, SHOP_TOSS_CLIENT_KEY="test_client_key",
                   SHOP_TOSS_SECRET_KEY="test_secret_key", SHOP_TOSS_VBANK_ENABLED=True)
class QueuedWebhookTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        from gnu_jango.shop.models import ShopOrder
        user = get_user_model().objects.create_user(username="background-validation")
        self.order = ShopOrder.objects.create(od_id="BACKGROUND-ORDER", user=user, od_name="Synthetic buyer",
            od_receipt_price=1000, od_misu=1000, od_status="order", od_pg="toss", od_settle_case="가상계좌",
            od_tno="synthetic-payment", od_vbank_status="WAITING_FOR_DEPOSIT",
            od_vbank_secret_hash=hashlib.sha256(b"synthetic-secret").hexdigest())

    def callback(self, secret="synthetic-secret"):
        return self.client.post("/api/v1/shop/payment/toss/vbank/webhook", data=json.dumps({
            "eventType": "DEPOSIT_CALLBACK", "data": {"orderId": self.order.pk, "secret": secret}}),
            content_type="application/json")

    def test_authentication_precedes_enqueue(self):
        with patch("gnu_jango.api.v1_shop.toss_api_get_payment_by_order") as provider:
            self.assertEqual(self.callback("wrong").status_code, 403)
        provider.assert_not_called()
        self.assertFalse(BackgroundJob.objects.exists())

    def test_request_is_db_only_and_worker_checks_provider_amount(self):
        with patch("gnu_jango.api.v1_shop.toss_api_get_payment_by_order") as provider:
            response = self.callback()
        provider.assert_not_called()
        self.assertEqual(response.status_code, 200)
        job = BackgroundJob.objects.get(pk=response.json()["data"]["job_id"])
        self.assertNotIn("synthetic-secret", json.dumps(job.payload))
        provider_state = {"orderId": self.order.pk, "paymentKey": self.order.od_tno,
                          "method": "가상계좌", "status": "DONE", "totalAmount": 999}
        with patch("gnu_jango.api.v1_shop.toss_api_get_payment_by_order", return_value=(provider_state, None)):
            self.assertEqual(jobs.execute_job(job.pk)["status"], "dead")
        self.order.refresh_from_db()
        self.assertEqual(self.order.od_misu, 1000)
        job.refresh_from_db()
        self.assertEqual(job.error_code, "payment_manual_review")

    def test_worker_confirmation_is_idempotent(self):
        job = BackgroundJob.objects.get(pk=self.callback().json()["data"]["job_id"])
        provider_state = {"orderId": self.order.pk, "paymentKey": self.order.od_tno,
                          "method": "가상계좌", "status": "DONE", "totalAmount": 1000}
        with patch("gnu_jango.api.v1_shop.toss_api_get_payment_by_order", return_value=(provider_state, None)) as provider:
            self.assertEqual(jobs.execute_job(job.pk)["status"], "succeeded")
            self.assertEqual(jobs.execute_job(job.pk)["status"], "skipped")
        provider.assert_called_once()
        self.order.refresh_from_db()
        self.assertEqual(self.order.od_misu, 0)


@override_settings(BACKGROUND_JOBS_ENABLED=True, STORAGES=STORAGES, MEDIA_URL="/media/")
class QueuedMediaTests(TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        override = override_settings(MEDIA_ROOT=directory.name)
        override.enable()
        self.addCleanup(override.disable)

    def upload(self):
        from .test_image_privacy import _jpeg_with_exif
        return default_storage.save("private/photo.jpg", ContentFile(_jpeg_with_exif()))

    def test_only_placeholder_is_public_until_worker_sanitizes(self):
        name = self.upload()
        job = BackgroundJob.objects.get(kind="image")
        with default_storage.open(name) as source:
            placeholder = source.read()
        self.assertNotIn(b"PrivacyTestCam", placeholder)
        self.assertIn(b"PrivacyTestCam", base64.b64decode(job.payload["data"]))
        with patch("sorl.thumbnail.delete"):
            self.assertEqual(jobs.execute_job(job.pk)["status"], "succeeded")
        with default_storage.open(name) as source, Image.open(source) as image:
            self.assertEqual(image.size, (20, 40))
            self.assertEqual(dict(image.getexif()), {})

    def test_user_deletion_wins_over_delayed_conversion(self):
        name = self.upload()
        job = BackgroundJob.objects.get()
        default_storage.delete(name)
        self.assertEqual(jobs.execute_job(job.pk)["status"], "skipped")
        job.refresh_from_db()
        self.assertEqual(job.error_code, "source_deleted")
        self.assertEqual(job.payload, {})
        self.assertFalse(default_storage.exists(name))
        self.assertFalse(jobs.replay(job, allow_uncertain=True))

    def test_invalid_jpeg_is_not_published(self):
        with self.assertRaises(ValidationError):
            default_storage.save("broken.jpg", ContentFile(b"not an image"))
        self.assertFalse(BackgroundJob.objects.exists())
        self.assertFalse(default_storage.exists("broken.jpg"))

    def test_thumbnail_waits_for_sanitization(self):
        name = self.upload()
        job = jobs.enqueue("thumbnail", {"kind": "media", "path": name, "width": 240, "image_format": "WEBP"})
        self.assertEqual(jobs.execute_job(job.pk)["status"], "pending")
        image_job = BackgroundJob.objects.get(kind="image")
        with patch("sorl.thumbnail.delete"):
            jobs.execute_job(image_job.pk)
        BackgroundJob.objects.filter(pk=job.pk).update(available_at=timezone.now())
        self.assertEqual(jobs.execute_job(job.pk)["status"], "succeeded")
        from .thumbnails import thumbnail_artifact_name
        with default_storage.open(thumbnail_artifact_name(**job.payload)) as source, Image.open(source) as image:
            self.assertEqual(image.format, "WEBP")
            self.assertEqual(dict(image.getexif()), {})


@override_settings(BACKGROUND_JOBS_ENABLED=True)
class ConcurrentClaimTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_duplicate_delivery_is_claimed_once(self):
        job = jobs.enqueue("scheduled", {})
        entered = threading.Event()
        release = threading.Event()
        def handler(row):
            entered.set()
            if not release.wait(10):
                raise RuntimeError("test synchronization timed out")
        def execute():
            close_old_connections()
            try:
                return jobs.execute_job(job.pk)
            finally:
                close_old_connections()
        with patch("gnu_jango.core.background_handlers.handle", side_effect=handler) as run:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(execute)
                try:
                    self.assertTrue(entered.wait(10))
                    self.assertEqual(pool.submit(execute).result(timeout=10)["status"], "skipped")
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=10)["status"], "succeeded")
        run.assert_called_once()

    def test_postgres_outbox_is_private_to_backend_role(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL RLS check")
        with connection.cursor() as cursor:
            cursor.execute("SELECT relrowsecurity FROM pg_class WHERE oid = 'gnu_jango_background_job'::regclass")
            self.assertTrue(cursor.fetchone()[0])
            for role in ("anon", "authenticated"):
                cursor.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", [role])
                if cursor.fetchone():
                    cursor.execute("SELECT has_table_privilege(%s, 'gnu_jango_background_job', 'SELECT')", [role])
                    self.assertFalse(cursor.fetchone()[0])
