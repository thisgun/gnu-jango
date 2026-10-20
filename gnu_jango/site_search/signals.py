from django.db.models.signals import post_save
from django.dispatch import receiver

from gnu_jango.bbs.models import Post
from gnu_jango.core.models import ContentPage
from gnu_jango.shop.models import ShopProduct

from .indexing import SOURCE_FIELDS, index_instance


@receiver(post_save, sender=Post, dispatch_uid="site_search:post")
@receiver(post_save, sender=ShopProduct, dispatch_uid="site_search:product")
@receiver(post_save, sender=ContentPage, dispatch_uid="site_search:page")
def source_saved(sender, instance, raw=False, using="default", update_fields=None, **kwargs):
    if raw:
        return
    kind = {Post: "post", ShopProduct: "product", ContentPage: "page"}[sender]
    if update_fields is not None and not SOURCE_FIELDS[kind].intersection(update_fields):
        return
    index_instance(instance, kind, using=using)
