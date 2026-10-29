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
