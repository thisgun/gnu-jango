"""Closed handler registry; untrusted jobs cannot select arbitrary Python callables or URLs."""
import base64
import smtplib

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.mail import mailers
from django.db import transaction
from django.utils import timezone

from .background import DeliveryUncertain, PermanentJobError, RetryableJobError


def mail_campaign_finished(job, *, success, error_code=""):
    payload = job.payload
    if job.kind != "mail" or not payload.get("campaign_id"):
        return
    from .models import MailCampaign, MailSendLog
    from django.contrib.auth import get_user_model
    with transaction.atomic():
        campaign = MailCampaign.objects.select_for_update().filter(pk=payload["campaign_id"]).first()
        if campaign is None:
            return
        user_id = payload.get("user_id")
        if user_id and not get_user_model().objects.filter(pk=user_id).exists():
            user_id = None
        MailSendLog.objects.update_or_create(campaign=campaign, recipient_email=payload["recipients"][0],
                                            defaults={"recipient_user_id": user_id, "status": "success" if success else "failed",
                                                      "error_message": error_code, "sent_at": timezone.now()})
        campaign.sent_count = campaign.logs.filter(status="success").count()
        campaign.failed_count = campaign.logs.filter(status="failed").count()
        finished = campaign.sent_count + campaign.failed_count >= campaign.recipient_count
        campaign.status = ("partial" if campaign.sent_count and campaign.failed_count else "failed" if campaign.failed_count else "sent") if finished else "sending"
        campaign.sent_at = timezone.now() if finished else None
        campaign.save(update_fields=["sent_count", "failed_count", "status", "sent_at"])


def _mail(job):
    from .queued_mail import StoredEmail
    # Only the configured delivery alias is allowed. Credentials never enter job payloads.
    mailer = mailers["delivery"]
    sending = False
    try:
        mailer.open()
        sending = True
        if mailer.send_messages([StoredEmail(job.payload)]) != 1:
            raise DeliveryUncertain("Mailer did not confirm delivery")
    except smtplib.SMTPResponseException as exc:
        if 400 <= exc.smtp_code < 500:
            raise RetryableJobError("SMTP temporary rejection") from None
        raise PermanentJobError("SMTP permanent rejection", code=f"smtp_{exc.smtp_code}") from None
    except smtplib.SMTPRecipientsRefused as exc:
        if all(400 <= result[0] < 500 for result in exc.recipients.values()):
            raise RetryableJobError("SMTP recipient temporarily rejected") from None
        raise PermanentJobError("SMTP recipient rejected", code="smtp_recipient_rejected") from None
    except (OSError, smtplib.SMTPServerDisconnected):
        if not sending:
            raise RetryableJobError("SMTP connection unavailable before delivery") from None
        raise DeliveryUncertain("SMTP delivery outcome unknown") from None
    finally:
        try:
            mailer.close()
        except Exception:
            # A failed QUIT does not invalidate a successful SMTP DATA acknowledgement.
            pass


def _sms(job):
    from gnu_jango.shop.sms.service import SmsSettings, _send_message_now
    payload = job.payload
    current = SmsSettings(**payload["settings"])
    result = _send_message_now(payload["recipient"], payload["message"], current=current,
                               subject=payload["subject"], purpose=payload["purpose"])
    if result.provider_code == "connect_timeout":
        raise RetryableJobError("SMS connection unavailable before delivery")
    if result.status == "unknown":
        raise DeliveryUncertain("SMS outcome unknown")
    if result.status != "accepted":
        if result.provider_code in {"connect_timeout", "circuit_open", "guard_unavailable"}:
            raise RetryableJobError("SMS temporarily unavailable")
        import re
        code = re.sub(r"[^a-zA-Z0-9_-]", "", result.provider_code)[:50] or "rejected"
        raise PermanentJobError("SMS rejected", code=f"sms_{code}")


def _sms_event(job):
    from gnu_jango.shop.sms import notifications
    payload = job.payload
    handlers = {"order_placed": notifications.send_order_placed_sms,
                "order_status": notifications.send_order_status_sms,
                "member_join": notifications.send_member_join_sms}
    callback = handlers.get(payload["event"])
    if callback is None:
        raise PermanentJobError("Unknown SMS event")
    # All children are committed together; they never send on this staging handler.
    with transaction.atomic():
        callback(*payload["args"], background_parent=str(job.pk))


def _scheduled(job):
    from .scheduled_jobs import default_runner, run_job, select_jobs
    name = job.payload["name"]
    if name == "purge_background_jobs":
        from .background import purge_finished
        purge_finished()
        return
    result = run_job(select_jobs([name])[0], dry_run=False, runner=default_runner)
    if result["status"] == "failed":
        raise RuntimeError("Scheduled command failed")


def _payment(job):
    from gnu_jango.api.v1_shop import process_toss_vbank_notification, process_payment_callback
    payload = job.payload
    if payload["provider"] == "toss-vbank":
        response = process_toss_vbank_notification(payload["order_id"], payload.get("transaction_key", ""))
    else:
        response = process_payment_callback(payload["provider"], payload["data"])
    if response.status_code >= 500 or response.status_code == 429:
        raise RuntimeError("Payment provider temporarily unavailable")
    if response.status_code >= 400:
        raise PermanentJobError("Payment notification requires review", code=f"payment_http_{response.status_code}")
    data = response.data.get("data", {})
    if isinstance(data, dict) and data.get("manual_review"):
        raise PermanentJobError("Payment notification requires review", code="payment_manual_review")


def _image(job):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.core.files.storage import storages
    from .image_privacy import strip_image_metadata, _has_metadata
    payload = job.payload
    storage = storages["background_media_source"]
    # Deletion by the user wins over a queued conversion.
    source = SimpleUploadedFile(payload["name"], base64.b64decode(payload["data"]), content_type=payload["content_type"])
    from PIL import Image
    with Image.open(source) as image:
        image.load()  # Fail closed; corrupt images must never be published unchanged.
        had_metadata = _has_metadata(image)
    source.seek(0)
    cleaned = strip_image_metadata(source)
    if had_metadata and cleaned is source:
        raise PermanentJobError("Image metadata removal failed", code="image_privacy_failed")
    # The target name is unique to this upload. Retrying is safe; never writes original bytes.
    writer = storages["background_media_writer"]
    from .background_models import BackgroundJob
    with transaction.atomic():
        locked = BackgroundJob.objects.select_for_update().get(pk=job.pk)
        if locked.status != "running" or locked.claim_token != job.claim_token or not storage.exists(payload["name"]):
            return
        saved = writer.save(payload["name"], cleaned)
        if saved != payload["name"]:
            storage.delete(saved)
            raise PermanentJobError("Image target was concurrently replaced")
    from sorl.thumbnail import delete
    delete(payload["name"], delete_file=False)
    from .thumbnails import THUMBNAIL_WIDTHS, thumbnail_artifact_name
    for width in THUMBNAIL_WIDTHS:
        for image_format in ("JPEG", "PNG", "WEBP"):
            artifact = thumbnail_artifact_name("media", payload["name"], width, image_format)
            if storage.exists(artifact):
                storage.delete(artifact)


def _thumbnail(job):
    from .thumbnails import _source, _make_copy, thumbnail_artifact_name
    payload = job.payload
    from .background_models import BackgroundJob
    from .background import resource_digest
    if payload["kind"] == "media" and BackgroundJob.objects.filter(
        kind="image", status__in=["pending", "running"], resource_key=resource_digest(payload["path"]),
    ).exists():
        raise RuntimeError("Source image is still being sanitized")
    source = _source(payload["kind"], payload["path"])
    if source is None:
        return
    name = thumbnail_artifact_name(**payload)
    if default_storage.exists(name):
        return
    content = _make_copy(*source, payload["width"], payload["image_format"])
    saved = default_storage.save(name, ContentFile(content))
    if saved != name:
        default_storage.delete(saved)


def handle(job):
    from datetime import timedelta
    ttl_days = {"mail": 1, "sms": 1, "sms_event": 1, "image": 7}
    if job.kind in ttl_days and job.created_at < timezone.now() - timedelta(days=ttl_days[job.kind]):
        raise PermanentJobError("Queued payload expired", code="payload_expired")
    handlers = {"scheduled": _scheduled, "mail": _mail, "sms": _sms, "sms_event": _sms_event,
                "payment_webhook": _payment, "thumbnail": _thumbnail, "image": _image}
    handler = handlers.get(job.kind)
    if handler is None:
        raise PermanentJobError("Unknown job kind")
    handler(job)
