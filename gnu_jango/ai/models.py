from django.db import models

from .fields import EmbeddingVectorField


class Embedding(models.Model):
    """One embedding per (kind, object id).

    ``text_hash`` covers the model, the dimensions and the embedded text, so ``build_embeddings``
    skips unchanged rows and re-embeds everything after a model change. Vectors are stored
    L2-normalised; cosine similarity is then a dot product on the portable path.
    """

    KIND_DOCS = "docs"
    KIND_PRODUCT = "product"
    KIND_CHOICES = ((KIND_DOCS, "Handbook chapter"), (KIND_PRODUCT, "Shop product"))

    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    object_id = models.CharField(max_length=64)
    # The board of a handbook chapter, for operators only. Read permission is checked
    # at query time against the live board settings, never from this copy.
    board_id = models.BigIntegerField(null=True, blank=True)
    model = models.CharField(max_length=128)
    dimensions = models.PositiveIntegerField()
    text_hash = models.CharField(max_length=64)
    embedding = EmbeddingVectorField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("kind", "object_id"), name="ai_embedding_one_per_object")]
        indexes = [models.Index(fields=("kind", "model", "dimensions"), name="ai_embedding_lookup")]
        verbose_name = "AI embedding"
        verbose_name_plural = "AI embeddings"

    def __str__(self):
        return f"{self.kind}:{self.object_id}"


class ReviewSummary(models.Model):
    """The chat model's summary of one product's published reviews (``summarize_reviews``).

    ``source_hash`` covers the chat model, the prompt version and the summarised reviews, so
    unchanged products are skipped and a model or prompt change rewrites every summary. Pages
    only read this row; they never call the model. An operator can hide a bad summary; a rewrite
    after new reviews keeps it hidden.
    """

    # ShopProduct.it_id; a plain id like Embedding.object_id, so deleting a product never cascades here.
    product_id = models.CharField(max_length=64, unique=True)
    model = models.CharField(max_length=128)
    review_count = models.PositiveIntegerField()
    source_hash = models.CharField(max_length=64)
    summary = models.TextField()
    is_hidden = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI review summary"
        verbose_name_plural = "AI review summaries"

    def __str__(self):
        return self.product_id
