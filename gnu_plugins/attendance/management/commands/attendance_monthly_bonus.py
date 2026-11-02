import json

from django.core.management.base import BaseCommand, CommandError

from gnu_plugins.attendance import services


class Command(BaseCommand):
    help = (
        "출석체크: give the monthly bonus to members who checked in every day of a month "
        f"(default: each of the last {services.CATCH_UP_MONTHS} finished months; each bonus is paid once)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--month", help="only this month, YYYY-MM")
        parser.add_argument("--apply", action="store_true", help="give the points; without it, only count")
        parser.add_argument("--json", action="store_true", help="print the report as JSON")

    def handle(self, *args, **options):
        if options["month"]:
            month = services.parse_month(options["month"])
            if month is None:
                raise CommandError("--month must look like 2026-10.")
            report = services.award_monthly_bonus(month, apply=options["apply"])
            reports = [report]
        else:
            reports = [services.award_monthly_bonus(month, apply=options["apply"]) for month in services.recent_months()]
            report = {
                "months": reports,
                "members": sum(item["members"] for item in reports),
                "awarded": sum(item["awarded"] for item in reports),
                "dry_run": not options["apply"],
            }

        if options["json"]:
            self.stdout.write(json.dumps(report))
            return
        for item in reports:
            self.stdout.write(
                f"{item['month']}: {item['members']} member(s) attended every day, {item['awarded']} awarded"
            )
