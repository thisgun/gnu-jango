from datetime import timedelta

from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.utils import timezone
from unfold.admin import ModelAdmin

from gnu_jango.core.background import enabled, replay
from gnu_jango.core.background_models import BackgroundJob

# Beat dispatches every 10 seconds; a due job still pending after this long means nothing runs it.
STALE_PENDING_MINUTES = 15


def stale_pending_warning():
    """Name a backlog that no worker is draining, so it is not discovered by missing texts."""
    cutoff = timezone.now() - timedelta(minutes=STALE_PENDING_MINUTES)
    stale = BackgroundJob.objects.filter(status="pending", available_at__lte=cutoff).count()
    if not stale:
        return ""
    if not enabled():
        return (f"백그라운드 작업이 꺼져 있어 대기 작업 {stale}개를 처리할 작업자가 없습니다. "
                "운영자 명령 process_background_jobs --apply 로 남은 작업을 처리하세요.")
    return (f"{STALE_PENDING_MINUTES}분 넘게 대기 중인 작업이 {stale}개 있습니다. "
            "Celery 작업자와 Beat가 같은 DB·브로커로 실행 중인지 확인하세요.")


@admin.register(BackgroundJob)
class BackgroundJobAdmin(ModelAdmin):
    list_display = ("id", "kind", "operation", "queue", "status", "attempts", "error_code", "created_at", "updated_at")
    list_filter = ("status", "kind", "queue")
    search_fields = ("=id", "operation", "error_code")
    fields = ("id", "kind", "operation", "queue", "status", "attempts", "max_attempts", "error_code",
              "created_at", "updated_at", "available_at", "dispatched_at", "lease_until", "finished_at")
    readonly_fields = fields
    actions = ("requeue_failed",)

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        warning = stale_pending_warning()
        if warning:
            self.message_user(request, warning, messages.WARNING)
        return super().changelist_view(request, extra_context)

    @admin.action(description="선택한 최종 실패 작업을 재처리 대기열로 이동", permissions=["view"])
    def requeue_failed(self, request, queryset):
        count = 0
        for job in queryset.filter(status="dead"):
            if replay(job):
                count += 1
                LogEntry.objects.log_actions(user_id=request.user.pk, queryset=BackgroundJob.objects.filter(pk=job.pk),
                                            action_flag=CHANGE, change_message="Background job replay requested")
        self.message_user(request, f"{count}개 작업을 재처리 대기열에 등록했습니다.", messages.SUCCESS)
        self.message_user(request, "발송 결과 불명·보관 기간 만료 작업은 자동 재처리하지 않습니다. 발송 여부 확인 후 운영 명령을 사용하세요.", messages.INFO)
