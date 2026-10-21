from datetime import timedelta
import time
import uuid

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, OperationalError, transaction
from django.utils import timezone

from gnu_jango.bbs.models import Post
from gnu_jango.core.models import ContentPage
from gnu_jango.shop.models import ShopProduct
from gnu_jango.site_search.indexing import index_instance, tokenizer_version
from gnu_jango.site_search.models import SearchIndexState, SearchSnapshot


class Command(BaseCommand):
    help = "Build a replacement search index in bounded batches and activate it on success."

    def add_arguments(self, parser):
        parser.add_argument("--kind", choices=["all", "post", "product", "page"], default="all")
        parser.add_argument("--database", default="default")
        parser.add_argument("--batch-size", type=int, default=25)

    def handle(self, *args, **options):
        if not 1 <= options["batch_size"] <= 200:
            raise CommandError("--batch-size must be between 1 and 200")
        for kind, model in (("post", Post), ("product", ShopProduct), ("page", ContentPage)):
            if options["kind"] in ("all", kind):
                self.rebuild(kind, model, options["database"], options["batch_size"])

    def rebuild(self, kind, model, database, batch_size):
        version, generation = tokenizer_version(), uuid.uuid4().hex
        def heartbeat(state):
            if state.building_generation != generation:
                raise CommandError(f"{kind}: rebuild ownership changed")
            state.build_updated_at = timezone.now()
            state.save(update_fields=["build_updated_at"], using=database)

        def release(state):
            if state.building_generation == generation:
                state.building_generation, state.build_updated_at = "", None
                state.save(update_fields=["building_generation", "build_updated_at"], using=database)

        def claim(state):
            if (state.building_generation and state.build_updated_at
                    and state.build_updated_at > timezone.now() - timedelta(minutes=30)):
                raise CommandError(f"{kind}: another rebuild is running")
            state.building_generation, state.build_updated_at = generation, timezone.now()
            state.save(update_fields=["building_generation", "build_updated_at"], using=database)
            return model.objects.using(database).order_by("-pk").values_list("pk", flat=True).first()
        last = self.change_state(kind, database, claim)
        count, cursor = 0, None
        try:
            while last is not None:
                rows = model.objects.using(database).filter(pk__lte=last).order_by("pk")
                if cursor is not None:
                    rows = rows.filter(pk__gt=cursor)
                ids = list(rows.values_list("pk", flat=True)[:batch_size])
                if not ids:
                    break
                # Release source/state locks after each document. Holding the state
                # lock while acquiring the next source row can deadlock live saves.
                for source_id in ids:
                    index_instance(model(pk=source_id), kind, using=database, build_generation=generation)
                self.change_state(kind, database, heartbeat)
                cursor, count = ids[-1], count + len(ids)
            def activate(state):
                if state.building_generation != generation:
                    raise CommandError(f"{kind}: rebuild ownership changed")
                if tokenizer_version() != version:
                    raise CommandError("Tokenizer changed during rebuild")
                state.active_generation, state.building_generation = generation, ""
                state.ready, state.tokenizer, state.build_updated_at = True, version, None
                state.save(using=database)
            self.change_state(kind, database, activate)
        except BaseException:
            try:
                self.change_state(kind, database, release)
                self.prune(kind, database, batch_size)
            except Exception:
                self.stderr.write(f"{kind}: cleanup deferred; the build lease expires after 30 minutes")
            raise
        self.prune(kind, database, batch_size)
        self.stdout.write(self.style.SUCCESS(f"{kind}: {count} documents indexed ({version})"))

    def change_state(self, kind, database, operation):
        # Never queue an exclusive lock ahead of a live multi-save transaction's
        # next shared lock: that transaction may need a source row held by a
        # writer behind us. Retry outside the transaction instead.
        deadline = time.monotonic() + 30
        states = SearchIndexState.objects.using(database)
        while True:
            try:
                with transaction.atomic(using=database):
                    states.get_or_create(kind=kind)
                    state = states.select_for_update(nowait=connections[database].vendor == "postgresql").get(kind=kind)
                    return operation(state)
            except OperationalError as exc:
                cause = exc.__cause__
                code = getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)
                if code != "55P03":
                    raise
                if time.monotonic() >= deadline:
                    raise CommandError(f"{kind}: index state is busy; retry the rebuild later") from exc
                time.sleep(0.05)

    def prune(self, kind, database, batch_size):
        states = SearchIndexState.objects.using(database)
        while True:
            stale = SearchSnapshot.objects.using(database).filter(document__kind=kind).exclude(
                generation__in=states.exclude(active_generation="").values("active_generation"),
            ).exclude(generation__in=states.exclude(building_generation="").values("building_generation"))
            ids = list(stale.order_by("pk").values_list("pk", flat=True)[:batch_size])
            if not ids:
                return
            SearchSnapshot.objects.using(database).filter(pk__in=ids).delete()
