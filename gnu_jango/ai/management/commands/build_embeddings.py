import json

from django.core.management.base import BaseCommand, CommandError

from gnu_jango.ai.client import EmbeddingError, get_provider
from gnu_jango.ai.indexing import KINDS, build


class Command(BaseCommand):
    help = (
        "Embed new or changed handbook chapters and on-sale products for semantic search, "
        "and delete embeddings of deleted, secret or hidden sources."
    )

    def add_arguments(self, parser):
        parser.add_argument("--kind", choices=("docs", "products", "all"), default="all")
        parser.add_argument("--rebuild", action="store_true", help="Re-embed every row, changed or not.")
        parser.add_argument("--limit", type=int, default=None, help="Embed at most N texts per kind this run.")
        parser.add_argument("--dry-run", action="store_true", help="Count the work without calling the endpoint.")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit is not None and limit < 0:
            raise CommandError("--limit must be zero or positive")
        provider = get_provider()
        if provider is None:
            message = "No embedding endpoint is configured (set G5_AI_BASE_URL and G5_AI_EMBEDDING_MODEL)."
            if options["json"]:
                self.stdout.write(json.dumps({"configured": False}))
                return
            raise CommandError(message)
        kinds = KINDS if options["kind"] == "all" else ({"docs": "docs", "products": "product"}[options["kind"]],)
        reports = []
        try:
            for kind in kinds:
                reports.append(build(kind, provider, rebuild=options["rebuild"], limit=limit, dry_run=options["dry_run"]))
        except EmbeddingError as exc:
            raise CommandError(f"Embedding endpoint failed ({exc.reason}): {exc}") from None
        if options["json"]:
            totals = {key: sum(report[key] for report in reports) for key in ("embedded", "unchanged", "pruned", "deferred")}
            self.stdout.write(json.dumps({"configured": True, "dry_run": options["dry_run"], "model": provider.model,
                                          **totals, "kinds": reports}))
            return
        for report in reports:
            verb = "would embed" if options["dry_run"] else "embedded"
            count = report.get("would_embed", report["embedded"])
            self.stdout.write(
                f"{report['kind']}: {verb} {count}, unchanged {report['unchanged']}, "
                f"pruned {report['pruned']}, deferred {report['deferred']} (eligible {report['eligible']})"
            )
