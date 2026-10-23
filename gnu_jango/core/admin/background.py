from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, LogEntry
from unfold.admin import ModelAdmin

from gnu_jango.core.background import replay
from gnu_jango.core.background_models import BackgroundJob


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
