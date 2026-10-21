from django.db import models
from django.db.models import Q
from django.utils import timezone


class SearchDocument(models.Model):
    KIND_CHOICES = (("post", "Post"), ("product", "Product"), ("page", "Page"))
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, db_index=True)
    post = models.OneToOneField("bbs.Post", null=True, blank=True, on_delete=models.CASCADE)
    product = models.OneToOneField("shop.ShopProduct", null=True, blank=True, on_delete=models.CASCADE)
    page = models.OneToOneField("core.ContentPage", null=True, blank=True, on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    # Hex-encoded tokens give PostgreSQL and SQLite identical lexeme boundaries,
    # including product codes and Korean morphemes. No raw body is duplicated.
    title_tokens = models.TextField(blank=True)
    body_tokens = models.TextField(blank=True)
    fingerprint = models.CharField(max_length=64)
    tokenizer = models.CharField(max_length=40)
    indexed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="post", post__isnull=False, product__isnull=True, page__isnull=True)
                    | Q(kind="product", product__isnull=False, post__isnull=True, page__isnull=True)
                    | Q(kind="page", page__isnull=False, post__isnull=True, product__isnull=True)
                ),
                name="search_doc_one_source",
            ),
        ]


class SearchPosting(models.Model):
    document = models.ForeignKey(SearchDocument, on_delete=models.CASCADE, related_name="postings")
    field = models.CharField(max_length=5, choices=(("title", "Title"), ("body", "Body")))
    term = models.CharField(max_length=128)
    frequency = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["document", "field", "term"], name="search_posting_unique")]
        indexes = [models.Index(fields=["term", "field", "document"], name="search_term_field_doc")]


class SearchIndexState(models.Model):
    kind = models.CharField(primary_key=True, max_length=10, choices=SearchDocument.KIND_CHOICES)
    ready = models.BooleanField(default=False)
    tokenizer = models.CharField(max_length=40, blank=True)
    active_generation = models.CharField(max_length=32, blank=True, default="")
    building_generation = models.CharField(max_length=32, blank=True, default="")
    build_updated_at = models.DateTimeField(null=True, blank=True)


class SearchSnapshot(models.Model):
    """A replaceable index generation; source identities and click FKs stay stable."""
    document = models.ForeignKey(SearchDocument, on_delete=models.CASCADE, related_name="snapshots")
    generation = models.CharField(max_length=32, db_index=True)
    title_tokens = models.TextField(blank=True)
    body_tokens = models.TextField(blank=True)
    fingerprint = models.CharField(max_length=64)
    tokenizer = models.CharField(max_length=40)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["document", "generation"], name="search_snapshot_unique")]


class SearchSnapshotPosting(models.Model):
    snapshot = models.ForeignKey(SearchSnapshot, on_delete=models.CASCADE, related_name="postings")
    field = models.CharField(max_length=5)
    term = models.CharField(max_length=128)
    frequency = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["snapshot", "field", "term"], name="search_snap_posting_unique")]
        indexes = [models.Index(fields=["term", "field", "snapshot"], name="search_snap_term_field")]


class SearchClickDaily(models.Model):
    query_hash = models.CharField(max_length=64)
    document = models.ForeignKey(SearchDocument, on_delete=models.CASCADE, related_name="daily_clicks")
    day = models.DateField(default=timezone.localdate, db_index=True)
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["query_hash", "document", "day"], name="search_click_day_unique")]
        indexes = [models.Index(fields=["query_hash", "day"], name="search_click_query_day")]
