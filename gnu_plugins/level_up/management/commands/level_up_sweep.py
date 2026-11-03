import json

from django.core.management.base import BaseCommand

from gnu_plugins.level_up import services


class Command(BaseCommand):
    help = "자동 등업: check every member against the level rules and raise the levels they have reached."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="raise the levels; without it, only count")
        parser.add_argument("--json", action="store_true", help="print the report as JSON")
        parser.add_argument(
            "--limit", type=int, default=services.MAX_PROMOTIONS_PER_RUN, help="raise at most this many members"
        )

    def handle(self, *args, **options):
        report = services.sweep(apply=options["apply"], limit=max(1, options["limit"]))
        if options["json"]:
            self.stdout.write(json.dumps(report))
            return
        levels = ", ".join(f"level {level}: {count}" for level, count in sorted(report["levels"].items())) or "none"
        self.stdout.write(
            f"checked {report['checked']}, promoted {report['promoted']} ({levels})"
            + (" (dry run)" if report["dry_run"] else "")
        )
