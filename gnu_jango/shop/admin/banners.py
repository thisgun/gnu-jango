from django.contrib import admin
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from gnu_jango.shop.models import ShopBanner


@admin.register(ShopBanner)
class ShopBannerAdmin(ModelAdmin):
    list_display = (
        "banner_preview",
        "bn_alt",
        "bn_position",
        "bn_device",
        "bn_order",
        "is_active",
        "hit_count",
        "begin_at",
        "end_at",
    )
    list_filter = ("is_active", "bn_position", "bn_device")
    list_editable = ("bn_order", "is_active")
    search_fields = ("bn_alt", "bn_url", "image_url")
    readonly_fields = ("banner_preview", "hit_count", "created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("bn_alt", "image_file", "banner_preview", "image_url", "bn_url")}),
        (
            "노출 설정",
            {"fields": ("bn_position", "bn_device", "bn_order", "is_active", "begin_at", "end_at")},
        ),
        ("링크 및 통계", {"fields": ("bn_border", "bn_new_win", "hit_count")}),
        ("관리 정보", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    @admin.display(description="이미지")
    def banner_preview(self, obj):
        if not obj:
            return "-"
        image_url = ""
        if obj.image_file:
            try:
                image_url = obj.image_file.url
            except ValueError:
                image_url = ""
        image_url = image_url or obj.image_url
        if not image_url:
            return "-"
        return format_html(
            '<img src="{}" alt="" style="max-width:180px; max-height:64px; object-fit:contain;" />',
            image_url,
        )
