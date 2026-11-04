from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Attendance


@admin.register(Attendance)
class AttendanceAdmin(ModelAdmin):
    """Read-only: a row records points already given, so it is not edited here."""

    list_display = ("day", "user", "streak", "point", "created_at")
    list_select_related = ("user",)
    search_fields = ("user__username",)
    date_hierarchy = "day"
    readonly_fields = ("user", "day", "streak", "point", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
