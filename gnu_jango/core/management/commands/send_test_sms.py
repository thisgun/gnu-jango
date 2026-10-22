"""Send one iCode test text, the command-line twin of the shop settings "테스트 발송" button.

    python manage.py send_test_sms 010-1234-5678 --confirm

Without --confirm nothing is sent: the command only reports what it would do. The iCode
credentials come from the environment (G5_ICODE_TOKEN_KEY, or G5_ICODE_ID / G5_ICODE_PASSWORD)
and are never printed.
"""

from django.core.management.base import BaseCommand, CommandError

from gnu_jango.shop.sms import icode
from gnu_jango.shop.sms.service import mask_phone, operator_test_text, send_message, sms_settings


class Command(BaseCommand):
    help = "Send one iCode test SMS to the given mobile number (requires --confirm)."

    def add_arguments(self, parser):
        parser.add_argument("phone", help="Recipient mobile number, e.g. 010-1234-5678.")
        parser.add_argument("--confirm", action="store_true", help="Actually send the (billed) text.")

    def handle(self, *args, **options):
        phone = icode.normalize_mobile(options["phone"])
        if not phone:
            raise CommandError("Give a valid Korean mobile number (01X-XXXX-XXXX).")
        status = icode.credential_status()
        if not status["provider_enabled"]:
            raise CommandError("G5_SMS_PROVIDER disables SMS on this server.")
        if status["mode"] == "missing":
            raise CommandError("Set G5_ICODE_TOKEN_KEY (or G5_ICODE_ID and G5_ICODE_PASSWORD) in the environment.")
        current = sms_settings()
        if not current.callback:
            raise CommandError("Save the shop customer-service phone number (the callback number) first.")
        text = operator_test_text(current)
        self.stdout.write(f"Mode: {status['mode']}. Recipient: {mask_phone(phone)}. Text: {text}")
        if not options["confirm"]:
            raise CommandError("Nothing was sent. Re-run with --confirm to send this billed test text.")
        result = send_message(phone, text, current=current, purpose="test (command)")
        line = f"{result.message_type} {result.status} ({result.provider_code})"
        if result.status != "accepted":
            raise CommandError(f"iCode did not accept the text: {line} {result.error_text}".strip())
        self.stdout.write(self.style.SUCCESS(f"Sent: {line}"))
