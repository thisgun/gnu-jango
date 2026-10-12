from django.apps import AppConfig
from django.dispatch import receiver
from django.utils.translation import gettext_lazy as _

from . import signals
from gnu_jango import defaults
from gnu_jango.utils.cache import gnu_delete_cache


class BbsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gnu_jango.bbs"
    verbose_name = _("BBS")


# signal 을 받아서 config 값을 초기화 합니다.
@receiver(signals.bbs_post_update_done)
@receiver(signals.bbs_comment_update_done)
def post_write_created_or_update(sender, **kwargs):
    board = kwargs.get("board")

    gnu_delete_cache("latest-%s-%s" % (str(board.id), defaults.BBS_CACHE_ROWS))
