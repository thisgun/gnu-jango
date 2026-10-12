from __future__ import annotations

from typing import Any

from celery import shared_task
from django.conf import settings
from django.core.management import call_command
from django.core.mail import EmailMessage, mailers
from django.utils import timezone
from django.utils.encoding import force_str

from gnu_jango.core.models import MailCampaign, MailSendLog


ALLOWED_BACKGROUND_COMMANDS = {
    "admin_smoke_check",
    "audit_external_integrations",
    "audit_gnuboard_assets",
    "audit_legacy_data_quality",
    "check_release_readiness",
    "cleanup_admin_privacy",
    "cleanup_post_files",
    "nextjs_smoke",
    "reconcile_payment_adapter",
    "sync_gnuboard_assets",
}


def _normalise_recipients(recipient_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recipients: list[dict[str, Any]] = []
    for row in recipient_rows:
        email = str(row.get("email") or "").strip()
        if not email:
            continue
        recipients.append(
            {
                "user_id": row.get("user_id") or row.get("pk") or row.get("id"),
                "email": email,
            }
        )
    return recipients


@shared_task(name="core.send_mail_campaign")
def send_mail_campaign_task(campaign_id: int, recipient_rows: list[dict[str, Any]]) -> dict[str, int | str]:
    campaign = MailCampaign.objects.get(pk=campaign_id)
    recipients = _normalise_recipients(recipient_rows)

    if not recipients:
        campaign.status = "failed"
        campaign.failed_count = 0
        campaign.sent_at = timezone.now()
        campaign.note = "No recipients were available for this campaign."
        campaign.save(update_fields=["status", "failed_count", "sent_at", "note"])
        return {"status": "failed", "sent": 0, "failed": 0}

    from_email = campaign.from_email or getattr(settings, "DEFAULT_FROM_EMAIL", "webmaster@localhost")
    sent_count = 0
    failed_count = 0
    logs: list[MailSendLog] = []

    # A single mailer instance is reused for the whole campaign so the SMTP
    # connection is opened once rather than per recipient.
    mailer = mailers["default"]
    for row in recipients:
        try:
            mailer.send_messages(
                [
                    EmailMessage(
                        subject=campaign.subject,
                        body=campaign.body,
                        from_email=from_email,
                        to=[row["email"]],
                    )
                ]
            )
        except Exception as exc:
            failed_count += 1
            logs.append(
                MailSendLog(
                    campaign=campaign,
                    recipient_user_id=row["user_id"],
                    recipient_email=row["email"],
                    status="failed",
                    error_message=force_str(exc),
                )
            )
            continue

        sent_count += 1
        logs.append(
            MailSendLog(
                campaign=campaign,
                recipient_user_id=row["user_id"],
                recipient_email=row["email"],
                status="success",
            )
        )

    if logs:
        MailSendLog.objects.bulk_create(logs, batch_size=500)

    campaign.sent_count = sent_count
    campaign.failed_count = failed_count
    campaign.sent_at = timezone.now()
    if failed_count and sent_count:
        campaign.status = "partial"
        campaign.note = f"{failed_count} recipient(s) failed."
    elif failed_count:
        campaign.status = "failed"
        campaign.note = f"{failed_count} recipient(s) failed."
    else:
        campaign.status = "sent"
        campaign.note = ""
    campaign.save(update_fields=["status", "sent_count", "failed_count", "sent_at", "note"])

    return {"status": campaign.status, "sent": sent_count, "failed": failed_count}


@shared_task(name="core.run_management_command")
def run_management_command_task(
    command_name: str,
    args: list[Any] | None = None,
    kwargs: dict[str, Any] | None = None,
) -> dict[str, str]:
    if command_name not in ALLOWED_BACKGROUND_COMMANDS:
        raise ValueError(f"{command_name} is not allowed as a background command.")

    call_command(command_name, *(args or []), **(kwargs or {}))
    return {"status": "completed", "command": command_name}
