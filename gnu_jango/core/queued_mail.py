"""Request-side mailer: durable DB insertion, never SMTP or Celery eager execution."""
import base64
import hashlib
from email import policy
from email.parser import BytesParser

from django.core.mail import EmailMessage
from django.core.mail.backends.base import BaseEmailBackend
from django.db import transaction

from .background import enqueue


def queue_message(message, *, dedupe_key=None, campaign_id=None, user_id=None):
    raw = message.message().as_bytes()
    if len(raw) > 16 * 1024 * 1024:
        raise ValueError("Queued email exceeds 16 MiB")
    return enqueue("mail", {"mime": base64.b64encode(raw).decode("ascii"),
                            "from_email": message.from_email, "recipients": message.recipients(),
                            "campaign_id": campaign_id, "user_id": user_id}, dedupe_key=dedupe_key)


class EmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        count = 0
        with transaction.atomic():
            for message in email_messages or []:
                if message.recipients():
                    queue_message(message)
                    count += 1
        return count  # Accepted into the outbox, not delivered to the recipient.


class StoredEmail(EmailMessage):
    def __init__(self, payload):
        super().__init__(from_email=payload["from_email"], to=payload["recipients"])
        self.raw = base64.b64decode(payload["mime"])

    def message(self, *, policy=policy.default):
        return BytesParser(policy=policy).parsebytes(self.raw)


def queue_campaign(campaign_id, recipient_rows):
    from .models import MailCampaign
    with transaction.atomic():
        campaign = MailCampaign.objects.select_for_update().get(pk=campaign_id)
        count = 0
        seen = set()
        for row in recipient_rows:
            email = str(row.get("email") or "").strip()
            if not email or email.casefold() in seen:
                continue
            seen.add(email.casefold())
            digest = hashlib.sha256(email.casefold().encode()).hexdigest()
            message = EmailMessage(subject=campaign.subject, body=campaign.body,
                                   from_email=campaign.from_email or None, to=[email])
            queue_message(message, dedupe_key=f"campaign:{campaign.pk}:{digest}", campaign_id=campaign.pk,
                          user_id=row.get("user_id") or row.get("pk") or row.get("id"))
            count += 1
        campaign.recipient_count = count
        if not count:
            campaign.status = "failed"
        campaign.save(update_fields=["recipient_count", "status"])
        return count
