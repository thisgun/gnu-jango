import logging

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils import timezone

from gnu_jango.bbs.models import Post
from gnu_jango.core.models import ContentPage
from gnu_jango.shop.models import ShopProduct

from .indexing import SOURCE_FIELDS, index_instance
from .models import SearchIndexRetry

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Post, dispatch_uid="site_search:post")
@receiver(post_save, sender=ShopProduct, dispatch_uid="site_search:product")
@receiver(post_save, sender=ContentPage, dispatch_uid="site_search:page")
def source_saved(sender, instance, raw=False, using="default", update_fields=None, **kwargs):
    if raw:
        return
    kind = {Post: "post", ShopProduct: "product", ContentPage: "page"}[sender]
    if update_fields is not None and not SOURCE_FIELDS[kind].intersection(update_fields):
        return
    try:
        index_instance(instance, kind, using=using)
    except Exception as exc:
        # index_instance owns a savepoint. Source.save owns the outer transaction:
        # either the source plus retry identity commit, or both roll back. If the
        # DB cannot store this record, propagate and roll back the source write.
        SearchIndexRetry.objects.using(using).update_or_create(
            kind=kind, source_id=str(instance.pk),
            defaults={"error_type": type(exc).__name__[:80], "available_at": timezone.now(), "attempts": 0},
        )
        logger.error("Search indexing deferred: kind=%s error_type=%s", kind, type(exc).__name__)
    else:
        SearchIndexRetry.objects.using(using).filter(kind=kind, source_id=str(instance.pk)).delete()


@receiver(post_delete, sender=Post, dispatch_uid="site_search:post_delete")
@receiver(post_delete, sender=ShopProduct, dispatch_uid="site_search:product_delete")
@receiver(post_delete, sender=ContentPage, dispatch_uid="site_search:page_delete")
def source_deleted(sender, instance, using="default", **kwargs):
    kind = {Post: "post", ShopProduct: "product", ContentPage: "page"}[sender]
    SearchIndexRetry.objects.using(using).filter(kind=kind, source_id=str(instance.pk)).delete()
