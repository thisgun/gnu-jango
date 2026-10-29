import json

from django.core.management.base import BaseCommand, CommandError

from gnu_jango.ai.client import ChatError, get_chat_provider
from gnu_jango.ai.review_summaries import summarize


class Command(BaseCommand):
    help = (
        "Summarise the published reviews of on-sale products with the chat model (G5_AI_CHAT_MODEL), "
        "skip unchanged ones, and delete summaries of products that no longer qualify."
    )

    def add_arguments(self, parser):
        parser.add_argument("--rebuild", action="store_true", help="Rewrite every summary, changed or not.")
        parser.add_argument("--limit", type=int, default=None, help="Call the model at most N times this run.")
        parser.add_argument("--dry-run", action="store_true", help="Count the work without calling the model.")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        limit = options["limit"]
        if limit is not None and limit < 0:
            raise CommandError("--limit must be zero or positive")
        provider = get_chat_provider()
        if provider is None:
            if options["json"]:
                self.stdout.write(json.dumps({"configured": False}))
                return
            raise CommandError("No chat model is configured (set G5_AI_BASE_URL and G5_AI_CHAT_MODEL).")
        try:
            report = summarize(provider, rebuild=options["rebuild"], limit=limit, dry_run=options["dry_run"])
        except ChatError as exc:
            raise CommandError(f"Chat endpoint failed ({exc.reason}): {exc}") from None
        if options["json"]:
            self.stdout.write(json.dumps({"configured": True, "dry_run": options["dry_run"], "model": provider.model,
                                          **report}))
            return
        verb = "would summarise" if options["dry_run"] else "summarised"
        count = report.get("would_summarize", report["summarized"])
        self.stdout.write(
            f"{verb} {count}, nothing to summarise {report['insufficient']}, "
            f"unchanged {report['unchanged']}, pruned {report['pruned']}, "
            f"deferred {report['deferred']}, failed {report['failed']} "
            f"(eligible {report['eligible']} with {report['min_reviews']}+ reviews)"
        )
