"""Create the first audit snapshot for data that predates django-simple-history.

Run this once after the history migrations. It only inserts a snapshot for objects that do not
have any history yet, so it can be re-run safely after a partial failure.

The optional ``--import-order-history`` pass reads the legacy ``ShopOrder.od_mod_history`` text
and adds the status transitions it can parse as historical rows. Those rows carry the original
timestamp and a clear change reason; fields other than status are the current snapshot because
the legacy text never stored a full row.
"""

import copy
import re
from datetime import datetime

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

SNAPSHOT_REASON = "initial snapshot (audit rollout)"
ORDER_HISTORY_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) "
    r"(?P<actor>\S+) "
    r"주문상태 (?P<from>.+?)→(?P<to>.+?) 처리$"
)


class Command(BaseCommand):
    help = "Backfill initial history snapshots (and legacy order status events) for audited models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--models",
            nargs="*",
            default=None,
            metavar="app.Model",
            help="Only these models (default: every model on the audit screen).",
        )
        parser.add_argument("--batch-size", type=int, default=500)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--import-order-history",
            action="store_true",
            help="Also import parseable ShopOrder.od_mod_history status transitions.",
        )

    def handle(self, *args, **options):
        models = self._models(options["models"])
        batch_size = max(1, int(options["batch_size"]))
        dry_run = options["dry_run"]

        total = 0
        for model in models:
            count = self._backfill_model(
                model,
                batch_size=batch_size,
                dry_run=dry_run,
                import_order_history=options["import_order_history"],
            )
            total += count
            suffix = " (dry run)" if dry_run else ""
            self.stdout.write(f"{model._meta.label}: {count} snapshot(s){suffix}")

        self.stdout.write(f"Total: {total} snapshot(s){' (dry run)' if dry_run else ''}")

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

    def _backfill_model(self, model, *, batch_size, dry_run, import_order_history):
        queryset = self._missing_history_queryset(model)
        if model._meta.label_lower == "shop.shoporder" and import_order_history:
            return self._backfill_orders_with_legacy_events(queryset, batch_size, dry_run)

        if dry_run:
            return queryset.count()

        count = 0
        history = model.history
        batch = []
        for obj in queryset.iterator(chunk_size=batch_size):
            batch.append(obj)
            if len(batch) >= batch_size:
                history.bulk_history_create(
                    batch,
                    batch_size=batch_size,
                    default_change_reason=SNAPSHOT_REASON,
                )
                count += len(batch)
                batch = []
        if batch:
            history.bulk_history_create(
                batch,
                batch_size=batch_size,
                default_change_reason=SNAPSHOT_REASON,
            )
            count += len(batch)
        return count

    def _backfill_orders_with_legacy_events(self, queryset, batch_size, dry_run):
        """Snapshot each order and, when possible, insert its old status transitions.

        Imported rows are marked with a reason because only od_status is known from the legacy
        text; every other field is the current value.
        """

        from django.contrib.auth import get_user_model

        user_model = get_user_model()
        users = {}
        count = 0
        for order in queryset.iterator(chunk_size=batch_size):
            events = self._order_events(order)
            if dry_run:
                count += 1 + len(events)
                continue

            order.history.bulk_history_create(
                [order],
                batch_size=1,
                default_change_reason=SNAPSHOT_REASON,
            )
            count += 1

            for event in events:
                snapshot = copy.copy(order)
                snapshot.od_status = event["to"]
                # Keep the legacy text so the diff is about status, not the current log text.
                snapshot.od_mod_history = order.od_mod_history
                snapshot._history_date = event["date"]
                snapshot._change_reason = (
                    f"od_mod_history import: {event['from']}→{event['to']}"
                )[:100]
                actor = event["actor"]
                if actor and actor != "-":
                    if actor not in users:
                        users[actor] = user_model.objects.filter(username=actor).first()
                    snapshot._history_user = users[actor]
                order.history.bulk_history_create(
                    [snapshot],
                    batch_size=1,
                    update=True,
                    default_change_reason="od_mod_history import",
                )
                count += 1
        return count

    def _order_events(self, order):
        events = []
        for line in (order.od_mod_history or "").splitlines():
            match = ORDER_HISTORY_RE.match(line.strip())
            if not match:
                continue
            try:
                event_date = timezone.make_aware(
                    datetime.strptime(match.group("date"), "%Y-%m-%d %H:%M:%S"),
                    timezone.get_current_timezone(),
                )
            except ValueError:
                continue
            events.append(
                {
                    "date": event_date,
                    "actor": match.group("actor"),
                    "from": match.group("from").strip(),
                    "to": match.group("to").strip(),
                }
            )
        return events

    def _missing_history_queryset(self, model):
        history_model = model.history.model
        pk_name = model._meta.pk.attname
        has_history = history_model.objects.filter(**{pk_name: OuterRef(pk_name)})
        queryset = model.objects.annotate(
            _audit_has_history=Exists(has_history)
        ).filter(_audit_has_history=False)

        if model._meta.label_lower == "config.config":
            from gnu_jango.config.models import TRACKED_CONFIG_PREFIXES

            tracked = Q()
            for prefix in TRACKED_CONFIG_PREFIXES:
                tracked |= Q(name__startswith=prefix)
            queryset = queryset.filter(tracked)

        return queryset
