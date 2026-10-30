"""가격 인하 알림 and 장바구니 알림 메일: what the scheduled shop alerts did, for the operator to look up.
Both are written by gnu_jango/shop/price_alerts.py and cart_reminders.py, so they are read-only here."""

from datetime import datetime

from django.contrib import admin
from django.utils import timezone
from unfold.admin import ModelAdmin

from gnu_jango.shop.models import ShopCartReminder, ShopPriceAlert


class ReadOnlyAdmin(ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ShopPriceAlert)
class ShopPriceAlertAdmin(ReadOnlyAdmin):
    list_display = ("id", "product", "user", "pa_price", "current_price", "created_at", "notified_at", "notified_price")
    list_display_links = ("id",)
    list_filter = (("notified_at", admin.EmptyFieldListFilter), "created_at")
    search_fields = ("product__it_id", "product__it_name", "user__username")
    list_select_related = ("product", "user")
    ordering = ("-created_at", "-pk")
    list_per_page = 50
    fields = readonly_fields = ("user", "product", "pa_price", "created_at", "notified_at", "notified_price")

    @admin.display(description="현재 가격")
    def current_price(self, obj):
        return obj.product.it_price


@admin.register(ShopCartReminder)
class ShopCartReminderAdmin(ReadOnlyAdmin):
    list_display = ("id", "user", "cart_put_at", "line_count", "coupon", "sent", "created_at")
    list_display_links = ("id",)
    list_filter = ("sent", "created_at")
    search_fields = ("user__username", "user__email")
    list_select_related = ("user", "coupon")
    ordering = ("-created_at", "-pk")
    list_per_page = 50
    fields = readonly_fields = ("user", "cart_put_at", "line_count", "coupon", "sent", "created_at")

    @admin.display(description="마지막으로 담은 시각")
    def cart_put_at(self, obj):
        return timezone.localtime(datetime.fromtimestamp(obj.cart_time, tz=timezone.get_current_timezone()))
