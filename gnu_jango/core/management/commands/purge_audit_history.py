"""Delete audit history older than the configured retention window.

This is a deliberate, explicit operation: history tables contain personal data (order contacts,
addresses) and are not immutable at the database level. Schedule this command only after the
privacy/retention policy has been agreed, and keep database backups for the remaining window.
"""

from datetime import timedelta

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Delete audit history rows older than --days (default: 365)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=365)
        parser.add_argument("--models", nargs="*", default=None, metavar="app.Model")
        parser.add_argument("--batch-size", type=int, default=5000)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        days = int(options["days"])
        if days < 0:
            raise CommandError("--days must be zero or a positive integer.")
        batch_size = int(options["batch_size"])
        if batch_size < 1:
            raise CommandError("--batch-size must be a positive integer.")
        cutoff = timezone.now() - timedelta(days=days)
        dry_run = options["dry_run"]

        total = 0
        for model in self._models(options["models"]):
            history = model.history
            queryset = history.filter(history_date__lt=cutoff)
            if dry_run:
                count = queryset.count()
            else:
                count = 0
                while True:
                    ids = list(queryset.values_list("history_id", flat=True)[:batch_size])
                    if not ids:
                        break
                    deleted, _ = history.filter(history_id__in=ids).delete()
                    count += deleted
            total += count
            suffix = " (dry run)" if dry_run else ""
            self.stdout.write(f"{model._meta.label}: {count} row(s) older than {cutoff.isoformat()}{suffix}")

        self.stdout.write(f"Total: {total} row(s){' (dry run)' if dry_run else ''}")

    def _models(self, names):
        if names:
            models = []
            for name in names:
                try:
                    model = apps.get_model(name)
                except (LookupError, ValueError) as exc:
                    raise CommandError(f"Unknown model: {name}") from exc
                if not hasattr(model, "history"):
                    raise CommandError(f"{name} is not history-tracked")
                models.append(model)
            return models

        from gnu_jango.core.audit import audit_model_specs

        return [spec["model"] for spec in audit_model_specs()]
