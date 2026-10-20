"""Pay youngcart purchase points (save_order_point) for order lines that are due."""

import json

from django.core.management.base import BaseCommand, CommandError

from gnu_jango.shop.order_points import DEFAULT_BATCH_LIMIT, save_order_points


class Command(BaseCommand):
    help = (
        "Pay the purchase points of order lines that have been 완료 for de_point_days days. "
        "Without --apply, count the due lines without changing data."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=DEFAULT_BATCH_LIMIT,
            help=f"Maximum lines to pay in one run (default {DEFAULT_BATCH_LIMIT}).",
        )
        parser.add_argument("--apply", action="store_true", help="Pay the points. Without this, dry-run only.")
        parser.add_argument("--json", action="store_true", help="Print a machine-readable summary.")

    def handle(self, *args, **options):
        limit = int(options["limit"])
        if limit < 1:
            raise CommandError("--limit must be positive.")
        summary = save_order_points(limit=limit, dry_run=not options["apply"])
        if options["json"]:
            self.stdout.write(json.dumps(summary, ensure_ascii=False))
            return
        self.stdout.write(
            "due={due} awarded={awarded} points={points} marked={marked} applied={applied}".format(**summary)
        )
