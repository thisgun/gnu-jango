"""Synchronous DB indexing; no worker, local files, or external search service."""
import hashlib
import html
from collections import Counter

from django.db import connections, transaction
from django.utils import timezone
from django.utils.html import strip_tags

from gnu_jango.docs_search import tokenizer

from .models import SearchDocument, SearchIndexState, SearchPosting

MAX_TITLE_TERMS = 256
MAX_BODY_TERMS = 4096
MAX_TEXT_CHARS = 65536
SOURCE_FIELDS = {
    "post": {"wr_subject", "wr_content", "ca_name", "wr_option"},
    "product": {"it_name", "it_id", "it_basic", "it_content", "it_explan", "it_brand", "it_model", "it_maker"},
    "page": {"co_subject", "co_content", "co_mobile_content"},
}


def tokenizer_version():
    return "kiwi-v1" if tokenizer._get_kiwi() is not None else "bigram-v1"


def plain_text(text):
    return " ".join(html.unescape(strip_tags(str(text or ""))).split())


def terms(text, limit):
    return [term for term in tokenizer.tokenize(str(text or "")[:MAX_TEXT_CHARS]) if 0 < len(term) <= 128][:limit]


def encoded(term):
    return "t" + term.encode("utf-8").hex()


def source_text(instance, kind):
    if kind == "post":
        # Even a secret post's owner searches only its title. Its body is never indexed.
        body = "" if "secret" in (instance.wr_option or "") else instance.wr_content
        return instance.wr_subject or "", plain_text(body)
    if kind == "product":
        title = instance.it_name
        body = " ".join(str(getattr(instance, field) or "") for field in (
            "it_id", "it_basic", "it_content", "it_explan", "it_brand", "it_model", "it_maker",
        ))
        return title, plain_text(body)
    return instance.co_subject, plain_text(f"{instance.co_content} {instance.co_mobile_content}")


def index_instance(instance, kind, *, using="default"):
    version = tokenizer_version()
    lookup = {f"{kind}_id": instance.pk}
    with transaction.atomic(using=using):
        # Locking the source serializes a rebuild against an ordinary save.
        source = type(instance).objects.using(using).select_for_update().filter(pk=instance.pk).first()
        if source is None:
            return
        # Always use the latest committed source, rather than a stale iterator snapshot.
        title, body = source_text(source, kind)
        digest = hashlib.sha256(f"{version}\0{title}\0{body}".encode()).hexdigest()
        doc = SearchDocument.objects.using(using).filter(**lookup).first()
        if doc and doc.fingerprint == digest:
            return
        title_terms, body_terms = terms(title, MAX_TITLE_TERMS), terms(body, MAX_BODY_TERMS)
        doc, _ = SearchDocument.objects.using(using).update_or_create(
            **lookup,
            defaults={"kind": kind, "title": title[:255], "title_tokens": " ".join(map(encoded, title_terms)),
                      "body_tokens": " ".join(map(encoded, body_terms)), "fingerprint": digest,
                      "tokenizer": version, "indexed_at": timezone.now()},
        )
        SearchPosting.objects.using(using).filter(document=doc).delete()
        if connections[using].vendor != "postgresql":
            SearchPosting.objects.using(using).bulk_create([
                SearchPosting(document=doc, field=field, term=term, frequency=count)
                for field, values in (("title", title_terms), ("body", body_terms))
                for term, count in Counter(values).items()
            ], batch_size=500)


def unready_kinds(kinds):
    version = tokenizer_version()
    ready = set(SearchIndexState.objects.filter(ready=True, tokenizer=version).values_list("kind", flat=True))
    return sorted(set(kinds) - ready)
