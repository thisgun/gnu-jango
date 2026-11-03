import json

from django.core.management.base import BaseCommand

from gnu_plugins.order_notify import services


class Command(BaseCommand):
    help = (
        "주문 알림: send again the messages a channel refused or did not take in time "
        f"(up to {services.MAX_ATTEMPTS} tries within {services.RETRY_WITHIN.total_seconds() / 3600:.0f} hours)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="send; without it, only count")
        parser.add_argument("--json", action="store_true", help="print the report as JSON")

    def handle(self, *args, **options):
        report = services.retry(apply=options["apply"])
        if options["json"]:
            self.stdout.write(json.dumps(report))
            return
        self.stdout.write(
            f"due {report['due']}, expired {report['expired']}, sent {report['sent']}, failed {report['failed']}"
            + (" (dry run)" if report["dry_run"] else "")
        )
