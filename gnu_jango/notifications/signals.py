"""Notification creation shared by legacy views, REST, admin and payment callbacks.

bulk_create/update deliberately bypass signals; imports should disable events explicitly.
"""

import uuid

from django.conf import settings
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from gnu_jango.bbs.models import Comment
from gnu_jango.core.models import Notification
from gnu_jango.shop.models import ShopOrder
from gnu_jango.users.models import User_Memo

from .delivery import invalidate_on_commit
from .context import events_suppressed
from .outbox import event_on_commit


def events_enabled(raw):
    return not raw and not events_suppressed() and getattr(settings, "NOTIFICATION_EVENTS_ENABLED", True)


@receiver(post_save, sender=Notification, dispatch_uid="notification.publish")
def publish_notification(sender, instance, raw=False, using="default", **kwargs):
    if not raw:
        invalidate_on_commit(instance.user_id, using=using, notification_id=instance.pk)


@receiver(post_save, sender=Comment, dispatch_uid="notification.comment")
def comment_created(sender, instance, created, raw=False, using="default", **kwargs):
    if not created or not events_enabled(raw):
        return
    post = instance.post
    if post.board_id != instance.board_id:
        return
    recipients = {post.user_id}
    if instance.parent:
        parent_user = Comment.objects.using(using).filter(
            pk=instance.parent, post_id=instance.post_id,
        ).values_list("user_id", flat=True).first()
        recipients.add(parent_user)
    recipients.difference_update({None, instance.user_id})
    # Never store comment bodies or post titles: permissions may change after delivery.
    for user_id in recipients:
        event_on_commit(user_id, f"comment:{instance.pk}:{user_id}", {
            "nt_type": "comment", "nt_title": "새 댓글이 등록되었습니다.",
            "nt_data": {"bo_table": post.board.bo_table, "post_id": post.legacy_wr_id or post.pk, "comment_id": instance.pk},
        }, using=using)


@receiver(post_save, sender=User_Memo, dispatch_uid="notification.memo")
def memo_created(sender, instance, created, raw=False, using="default", **kwargs):
    if not created or not events_enabled(raw) or instance.me_type != "recv":
        return
    if instance.user_id == instance.me_send_id:
        return
    event_on_commit(instance.user_id, f"memo:{instance.pk}", {
        "nt_type": "memo", "nt_title": "새 쪽지가 도착했습니다.",
        "nt_data": {"href": f"/mypage/memos/{instance.pk}", "memo_id": instance.pk},
    }, using=using)


@receiver(pre_save, sender=ShopOrder, dispatch_uid="notification.order_before")
def order_before_save(sender, instance, raw=False, using="default", update_fields=None, **kwargs):
    instance._notification_previous_status = None
    if not events_enabled(raw) or not instance.pk or (update_fields is not None and "od_status" not in update_fields):
        return
    instance._notification_previous_status = sender.objects.using(using).filter(pk=instance.pk).values_list(
        "od_status", flat=True,
    ).first()


@receiver(post_save, sender=ShopOrder, dispatch_uid="notification.order_after")
def order_after_save(sender, instance, created, raw=False, using="default", **kwargs):
    from gnu_jango.shop.order_flow import canonical_status

    previous = getattr(instance, "_notification_previous_status", None)
    if created or not events_enabled(raw) or previous is None or not instance.user_id:
        return
    current = canonical_status(instance.od_status)
    if canonical_status(previous) == current:
        return
    event_on_commit(instance.user_id, f"order:{instance.pk}:{uuid.uuid4().hex}", {
        "nt_type": "order", "nt_title": "주문 상태가 변경되었습니다.", "nt_body": f"주문 상태: {current}",
        "nt_data": {"href": f"/shop/orders/{instance.pk}", "order_id": instance.pk, "status": current},
    }, using=using)
