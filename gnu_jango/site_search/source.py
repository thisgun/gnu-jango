"""Keep a source write and its index/retry record in one transaction."""
from django.db import models, router, transaction


class SearchIndexedSource(models.Model):
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        using = kwargs.get("using") or router.db_for_write(type(self), instance=self)
        kwargs["using"] = using
        with transaction.atomic(using=using):
            return super().save(*args, **kwargs)
