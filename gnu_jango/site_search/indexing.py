"""Synchronous DB indexing; no worker, local files, or external search service."""
import hashlib
import html
import re
from collections import Counter

from django.db import connections, transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.html import strip_tags

from gnu_jango.docs_search import tokenizer

from .models import SearchDocument, SearchIndexState, SearchPosting, SearchSnapshot, SearchSnapshotPosting

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


def prefix_terms(query_terms):
    """ASCII words/codes support prefixes; Korean bigrams remain exact lexemes."""
    return {term for term in query_terms if re.fullmatch(r"[a-z0-9][a-z0-9_.+\-]{1,63}", term)}


def posting_match(query_terms):
    result = Q(term__in=set(query_terms))
    for term in prefix_terms(query_terms):
        result |= Q(term__gte=term, term__lt=term + "\uffff")
    return result


def postgres_query(query_terms):
    from functools import reduce
    from operator import or_
    from django.contrib.postgres.search import SearchQuery
    prefixes = prefix_terms(query_terms)
    return reduce(or_, [SearchQuery(encoded(term) + (":*" if term in prefixes else ""),
                                   config="simple", search_type="raw") for term in sorted(set(query_terms))])


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


def locked_state(kind, using):
    states = SearchIndexState.objects.using(using)
    states.get_or_create(kind=kind)
    if connections[using].vendor == "postgresql":
        # Writers to different source rows may coexist. FOR UPDATE here would
        # deadlock a multi-save transaction against another source's post_save.
        # Rebuild claim/publish use FOR UPDATE and wait for these shared locks.
        table = connections[using].ops.quote_name(SearchIndexState._meta.db_table)
        return next(iter(states.raw(f"SELECT * FROM {table} WHERE kind=%s FOR SHARE", [kind])))
    return states.select_for_update().get(kind=kind)


def index_instance(instance, kind, *, using="default", build_generation=None):
    version = tokenizer_version()
    lookup = {f"{kind}_id": instance.pk}
    with transaction.atomic(using=using):
        # Locking the source serializes a rebuild against an ordinary save.
        source = type(instance).objects.using(using).select_for_update().filter(pk=instance.pk).first()
        if source is None:
            return
        state = locked_state(kind, using)
        if build_generation is not None and state.building_generation != build_generation:
            raise RuntimeError("Search index build ownership changed; stopping this rebuild")
        # Always use the latest committed source, rather than a stale iterator snapshot.
        title, body = source_text(source, kind)
        digest = hashlib.sha256(f"{version}\0{title}\0{body}".encode()).hexdigest()
        doc = SearchDocument.objects.using(using).filter(**lookup).first()
        generations = ({build_generation} if build_generation else {
            state.active_generation, state.building_generation,
        }) - {"", None}
        if doc and doc.fingerprint == digest:
            present = set(SearchSnapshot.objects.using(using).filter(
                document=doc, generation__in=generations, fingerprint=digest,
            ).values_list("generation", flat=True)) if generations else set()
            if present == generations:
                return
        title_terms, body_terms = terms(title, MAX_TITLE_TERMS), terms(body, MAX_BODY_TERMS)
        values = {"title_tokens": " ".join(map(encoded, title_terms)),
                  "body_tokens": " ".join(map(encoded, body_terms)), "fingerprint": digest, "tokenizer": version}
        if not doc or doc.fingerprint != digest:
            doc, _ = SearchDocument.objects.using(using).update_or_create(
                **lookup, defaults={"kind": kind, "title": title[:255], **values, "indexed_at": timezone.now()},
            )
            _write_postings(doc, title_terms, body_terms, using=using)
        for generation in generations:
            snapshot = SearchSnapshot.objects.using(using).filter(document=doc, generation=generation).first()
            if snapshot and snapshot.fingerprint == digest:
                continue
            snapshot, _ = SearchSnapshot.objects.using(using).update_or_create(
                document=doc, generation=generation, defaults=values,
            )
            _write_postings(snapshot, title_terms, body_terms, using=using)


def _write_postings(instance, title_terms, body_terms, *, using):
    model, key = (SearchPosting, "document") if isinstance(instance, SearchDocument) else (SearchSnapshotPosting, "snapshot")
    model.objects.using(using).filter(**{key: instance}).delete()
    if connections[using].vendor != "postgresql":
        model.objects.using(using).bulk_create([
            model(**{key: instance}, field=field, term=term, frequency=count)
            for field, terms_list in (("title", title_terms), ("body", body_terms))
            for term, count in Counter(terms_list).items()
        ], batch_size=500)


def unready_kinds(kinds):
    version = tokenizer_version()
    ready = set(SearchIndexState.objects.filter(ready=True, tokenizer=version).values_list("kind", flat=True))
    return sorted(set(kinds) - ready)
