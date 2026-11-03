from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import LevelChange, LevelRule, LevelUpHold


@admin.register(LevelRule)
class LevelRuleAdmin(ModelAdmin):
    """Staff with the view permission see the rules; only superusers change them, because a rule
    hands out levels (and so board rights) to many members at once."""

    list_display = ("level", "min_points", "min_posts", "min_comments", "min_days", "min_attendance", "is_active")
    list_display_links = ("level",)
    list_filter = ("is_active",)
    fields = ("level", "min_points", "min_posts", "min_comments", "min_days", "min_attendance", "is_active")

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(LevelChange)
class LevelChangeAdmin(ModelAdmin):
    """Read-only: a row records a level already given."""

    list_display = ("created_at", "user", "old_level", "new_level", "reason")
    list_select_related = ("user",)
    list_filter = ("new_level",)
    search_fields = ("user__username",)
    date_hierarchy = "created_at"
    readonly_fields = ("user", "old_level", "new_level", "reason", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        # The row is also what keeps an admin's later demotion from being undone (services._candidates).
        return request.user.is_superuser


@admin.register(LevelUpHold)
class LevelUpHoldAdmin(ModelAdmin):
    """Members the plugin never raises; deleting the row lets the rules apply again."""

    list_display = ("user", "reason", "created_at")
    list_select_related = ("user",)
    search_fields = ("user__username", "reason")
    raw_id_fields = ("user",)
    fields = ("user", "reason")
