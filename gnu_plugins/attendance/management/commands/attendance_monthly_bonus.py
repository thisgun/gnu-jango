import json

from django.core.management.base import BaseCommand, CommandError

from gnu_plugins.attendance import services


class Command(BaseCommand):
    help = "출석체크: give the monthly bonus to members who checked in every day of a month (default: last month)."

    def add_arguments(self, parser):
        parser.add_argument("--month", help="YYYY-MM (default: last month)")
        parser.add_argument("--apply", action="store_true", help="give the points; without it, only count")
        parser.add_argument("--json", action="store_true", help="print the report as JSON")

    def handle(self, *args, **options):
        month = services.last_month()
        if options["month"]:
            month = services.parse_month(options["month"])
            if month is None:
                raise CommandError("--month must look like 2026-10.")
        report = services.award_monthly_bonus(month, apply=options["apply"])
        if options["json"]:
            self.stdout.write(json.dumps(report))
        else:
            self.stdout.write(
                f"{report['month']}: {report['members']} member(s) attended every day, {report['awarded']} awarded"
            )
