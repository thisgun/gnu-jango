import logging

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from gnu_jango.bbs.models import Board, Post
from gnu_jango.config import config as site_config

from .service import _revision_key, clear_memory_cache

logger = logging.getLogger(__name__)


def _configured_group_id():
    try:
        group_id = site_config.get_all().get("cf_docs_group")
    except Exception:
        group_id = ""
    return str(group_id or getattr(settings, "G5_DEFAULT_DOCS_GROUP", "") or "").strip()


def _post_group_id(instance):
    if not instance.board_id:
        return ""
    return str(
        Board.objects.filter(pk=instance.board_id).values_list("group__gr_id", flat=True).first() or ""
    ).strip()


def _bump_shared_revision(group_id):
    key = _revision_key(group_id)
    try:
        if not cache.add(key, 1, timeout=None):
            cache.incr(key)
    except Exception:
        logger.warning("Could not invalidate the shared handbook search index.", exc_info=True)


@receiver(post_save, sender=Post, dispatch_uid="docs_search_post_saved")
@receiver(post_delete, sender=Post, dispatch_uid="docs_search_post_deleted")
def invalidate_handbook_search(sender, instance, **kwargs):
    group_id = _post_group_id(instance)
    if not group_id or group_id != _configured_group_id():
        return
    clear_memory_cache()
    # Clear this process immediately; publish the shared revision only after the DB transaction commits.
    transaction.on_commit(lambda: _bump_shared_revision(group_id), robust=True)
