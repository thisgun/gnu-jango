from django.core.management.base import BaseCommand
from django.db import transaction

from gnu_jango.bbs.models import Post
from gnu_jango.core.models import ContentPage
from gnu_jango.shop.models import ShopProduct
from gnu_jango.site_search.indexing import index_instance, tokenizer_version
from gnu_jango.site_search.models import SearchIndexState


class Command(BaseCommand):
    help = "Rebuild unified search after deployment, bulk imports, or a tokenizer change."

    def add_arguments(self, parser):
        parser.add_argument("--kind", choices=["all", "post", "product", "page"], default="all")
        parser.add_argument("--database", default="default")

    def handle(self, *args, **options):
        database = options["database"]
        version = tokenizer_version()
        for kind, model in (("post", Post), ("product", ShopProduct), ("page", ContentPage)):
            if options["kind"] not in ("all", kind):
                continue
            SearchIndexState.objects.using(database).update_or_create(kind=kind, defaults={"ready": False})
            count = 0
            # One transaction per kind keeps readers on the legacy fallback until a
            # complete corpus has committed, and preserves the prior index on failure.
            with transaction.atomic(using=database):
                state = SearchIndexState.objects.using(database).select_for_update().get(kind=kind)
                for instance in model.objects.using(database).order_by("pk").iterator(chunk_size=200):
                    index_instance(instance, kind, using=database)
                    count += 1
                state.ready, state.tokenizer = True, version
                state.save(using=database, update_fields=["ready", "tokenizer"])
            self.stdout.write(self.style.SUCCESS(f"{kind}: {count} documents indexed ({version})"))
