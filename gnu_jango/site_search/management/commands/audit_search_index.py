import json

from django.core.management.base import BaseCommand, CommandError

from gnu_jango.site_search.maintenance import SOURCES, audit_sources


class Command(BaseCommand):
    help = "Read-only bounded source/index fingerprint audit; --enqueue records repairs for bulk updates."

    def add_arguments(self, parser):
        parser.add_argument("--kind", choices=tuple(SOURCES), required=True)
        parser.add_argument("--limit", type=int, default=200)
        parser.add_argument("--after", default="")
        parser.add_argument("--database", default="default")
        parser.add_argument("--enqueue", action="store_true")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        if not 1 <= options["limit"] <= 10000:
            raise CommandError("limit must be 1..10000; resume with --after")
        if options["kind"] == "post" and options["after"] and not options["after"].isdigit():
            raise CommandError("post cursor must be numeric")
        result = audit_sources(kind=options["kind"], using=options["database"], limit=options["limit"],
                               after=options["after"], enqueue=options["enqueue"])
        self.stdout.write(json.dumps(result))
        if result["mismatches"] and not options["enqueue"]:
            raise CommandError("Search source/index mismatch detected; review then use --enqueue")
