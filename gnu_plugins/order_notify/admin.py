from django.contrib import admin, messages
from unfold.admin import ModelAdmin

from . import services
from .models import OrderNotice

# The action sends inside the admin's request, a few seconds per channel at worst.
ADMIN_SEND_LIMIT = 20

@admin.register(OrderNotice)
class OrderNoticeAdmin(ModelAdmin):
    """The send log: read-only, with an action that sends the selected unsent messages again."""

    list_display = ("created_at", "od_id", "event", "channel", "status", "attempts", "last_error")
    list_filter = ("status", "channel", "event")
    search_fields = ("od_id",)
    date_hierarchy = "created_at"
    readonly_fields = (
        "od_id", "event", "key", "channel", "text", "status", "attempts", "last_error", "created_at", "sent_at"
    )
    actions = ("send_again",)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # A deleted row no longer stops the same message from being posted again.
        return request.user.is_superuser

    @admin.action(description="선택한 알림 다시 보내기", permissions=["change"])
    def send_again(self, request, queryset):
        # Only the failed and waiting ones: a sent message is not posted twice, a sending one is busy.
        ids = list(queryset.filter(status__in=(OrderNotice.FAILED, OrderNotice.PENDING)).values_list("pk", flat=True))
        if len(ids) > ADMIN_SEND_LIMIT:
            self.message_user(
                request, f"한 번에 {ADMIN_SEND_LIMIT}건까지 다시 보낼 수 있습니다. ({len(ids)}건 선택)", messages.ERROR
            )
            return
        OrderNotice.objects.filter(pk__in=ids).update(status=OrderNotice.PENDING, attempts=0, last_error="")
        report = services.send_pending(ids)
        level = messages.SUCCESS if not report["failed"] else messages.WARNING
        self.message_user(
            request, f"{report['sent']}건을 보냈고 {report['failed']}건은 보내지 못했습니다. (이미 보낸 알림은 건너뜁니다)", level
        )
