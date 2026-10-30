"""정기구독 admin: subscriptions and their charges (shop/subscriptions.py).

The sealed billing key, the customerKey and the registration token are never shown. A charge's
order is an ordinary shop order, so a refund goes through the order's own cancel / partial cancel
(Toss cancel API with the order's key pair) like any card order.
"""

from django.contrib import admin, messages
from django.contrib.admin import ActionLocation
from django.core.exceptions import PermissionDenied
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from gnu_jango.shop import subscriptions as service
from gnu_jango.shop.models import ShopSubscription, ShopSubscriptionCharge
from gnu_jango.utils.admin_display import badge, money_html

STATUS_TONES = {
    ShopSubscription.STATUS_ACTIVE: "success",
    ShopSubscription.STATUS_PAUSED: "warning",
    ShopSubscription.STATUS_CANCELLED: "neutral",
    ShopSubscription.STATUS_PENDING: "info",
}
CHARGE_TONES = {
    ShopSubscriptionCharge.STATUS_DONE: "success",
    ShopSubscriptionCharge.STATUS_PENDING: "info",
    ShopSubscriptionCharge.STATUS_FAILED: "danger",
    ShopSubscriptionCharge.STATUS_SKIPPED: "neutral",
    ShopSubscriptionCharge.STATUS_REVIEW: "danger",
}
HIDDEN_FIELDS = ("billing_key_sealed", "customer_key", "auth_token_hash", "auth_expires_at", "auth_mode")


def order_link(charge):
    if not charge.order_id:
        return charge.od_id or "-"
    return format_html('<a href="{}">{}</a>', reverse("admin:shop_shoporder_change", args=[charge.od_id]), charge.od_id)


def retry_message(result):
    labels = {
        "charged": "결제 완료",
        "failed": f"결제 실패 ({result.message})" if result.message else "결제 실패",
        "skipped": f"건너뜀 ({result.message})" if result.message else "건너뜀",
        "pending": "결제 결과 확인 중",
        "review": "확인 필요",
        "already": "이미 결제했거나 결제 중",
        "inactive": "재시도할 수 없는 상태 (구독 중이거나 결제 실패로 일시정지된 구독만)",
        "paused": "카드가 없어 일시정지",
        "cancelled": "회원 계정을 사용할 수 없어 해지",
    }
    return labels.get(result.status, result.status)


class ShopSubscriptionChargeInline(TabularInline):
    model = ShopSubscriptionCharge
    extra = 0
    max_num = 0
    can_delete = False
    tab = True
    show_count = True
    fields = ("cycle_no", "attempt", "scheduled_date", "status", "source", "amount", "order_display", "failure_message", "created_at")
    readonly_fields = fields

    @admin.display(description="주문")
    def order_display(self, obj):
        return order_link(obj)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class SubscriptionActionsMixin:
    """Admin actions need the change permission of the subscription model."""

    def can_operate(self, request):
        return bool(request.user and request.user.is_active and request.user.has_perm("shop.change_shopsubscription"))

    def get_actions(self, request, action_location=ActionLocation.CHANGE_LIST):
        if not self.can_operate(request):
            return {}
        return super().get_actions(request, action_location)

    def report_retries(self, request, subscription_ids):
        results = {}
        for pk in subscription_ids:
            try:
                result = service.admin_retry(pk)
            except Exception as exc:  # noqa: BLE001 - one row must not stop the admin action
                results.setdefault(f"오류 ({type(exc).__name__})", []).append(pk)
                continue
            results.setdefault(retry_message(result), []).append(pk)
        summary = ", ".join(f"{label} {len(ids)}건" for label, ids in results.items()) or "대상 없음"
        all_charged = set(results) == {"결제 완료"}
        self.message_user(request, f"정기구독 결제 재시도: {summary}", messages.SUCCESS if all_charged else messages.WARNING)


@admin.register(ShopSubscription)
class ShopSubscriptionAdmin(SubscriptionActionsMixin, ModelAdmin):
    list_display = (
        "id", "user", "it_name", "qty", "cycle", "status_display", "next_charge_display", "card_display",
        "failure_count", "created_at",
    )
    list_display_links = ("id", "it_name")
    list_filter = ("status", "cycle", "pause_reason", "toss_mode")
    search_fields = ("=id", "it_id", "it_name", "user__username", "user__email", "od_b_name", "od_email")
    list_select_related = ("user",)
    ordering = ("-created_at",)
    inlines = (ShopSubscriptionChargeInline,)
    exclude = HIDDEN_FIELDS
    readonly_fields = (
        "user", "product", "it_id", "it_name", "io_id", "qty", "cycle", "billing_day", "status", "pause_reason",
        "next_charge_date", "retry_date", "cycle_no", "failure_count", "notice_cycle_no", "toss_mode",
        "card_company", "card_number", "card_type", "card_registered_at", "od_name", "od_email", "od_hp",
        "last_error", "started_at", "cancelled_at", "created_at", "updated_at",
    )
    fieldsets = (
        ("구독", {"fields": (
            ("user", "status", "pause_reason"),
            ("product", "it_id", "it_name"),
            ("io_id", "qty"),
            ("cycle", "billing_day", "cycle_no"),
            ("next_charge_date", "retry_date", "failure_count"),
            "last_error",
            ("started_at", "cancelled_at"),
            ("created_at", "updated_at", "notice_cycle_no"),
        )}),
        ("결제 카드", {"fields": (("card_company", "card_number", "card_type"), ("card_registered_at", "toss_mode"))}),
        ("주문자·배송지", {"fields": (
            ("od_name", "od_email", "od_hp"),
            ("od_b_name", "od_b_tel", "od_b_hp"),
            ("od_b_zip", "od_b_addr1"),
            ("od_b_addr2", "od_b_addr3", "od_b_addr_jibeon"),
            "od_memo",
        )}),
    )
    actions = ("pause_selected", "cancel_selected", "retry_selected")

    @admin.display(description="상태", ordering="status")
    def status_display(self, obj):
        label = obj.get_status_display()
        if obj.pause_reason:
            label = f"{label} ({obj.get_pause_reason_display()})"
        return badge(label, STATUS_TONES.get(obj.status, "neutral"))

    @admin.display(description="다음 결제일")
    def next_charge_display(self, obj):
        if obj.status in {ShopSubscription.STATUS_CANCELLED, ShopSubscription.STATUS_PENDING}:
            return "-"
        due = service.due_date(obj)
        return f"{due:%Y-%m-%d}{' (재시도)' if obj.retry_date else ''}" if due else "-"

    @admin.display(description="카드")
    def card_display(self, obj):
        return f"{obj.card_company} {obj.card_number}".strip() or "-"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # cancelling drops the billing key at Toss too; a deleted row would leave it there
        return False

    @admin.action(description="선택한 정기구독 일시정지")
    def pause_selected(self, request, queryset):
        if not self.can_operate(request):
            raise PermissionDenied
        done = sum(1 for pk in queryset.values_list("pk", flat=True) if service.admin_pause(pk))
        self.message_user(request, f"정기구독 {done}건을 일시정지했습니다. 구독 중이 아니거나 결제 중인 구독은 건너뜁니다.")

    @admin.action(description="선택한 정기구독 해지")
    def cancel_selected(self, request, queryset):
        if not self.can_operate(request):
            raise PermissionDenied
        done = sum(1 for pk in queryset.values_list("pk", flat=True) if service.admin_cancel(pk))
        self.message_user(request, f"정기구독 {done}건을 해지하고 등록된 카드를 삭제했습니다. 결제 중인 구독은 건너뜁니다.")

    @admin.action(description="지금 결제 재시도 (구독 중·결제 실패로 일시정지)")
    def retry_selected(self, request, queryset):
        if not self.can_operate(request):
            raise PermissionDenied
        self.report_retries(request, list(queryset.values_list("pk", flat=True)))


@admin.register(ShopSubscriptionCharge)
class ShopSubscriptionChargeAdmin(SubscriptionActionsMixin, ModelAdmin):
    list_display = (
        "id", "subscription", "cycle_no", "attempt", "scheduled_date", "status_display", "source", "amount_display",
        "order_display", "failure_message", "created_at",
    )
    list_filter = ("status", "source", "scheduled_date")
    search_fields = ("od_id", "payment_key", "subscription__it_name", "subscription__user__username")
    list_select_related = ("subscription",)
    ordering = ("-created_at",)
    exclude = ("idempotency_key",)
    readonly_fields = (
        "subscription", "cycle_no", "attempt", "scheduled_date", "status", "source", "order", "od_id", "amount",
        "payment_key", "failure_code", "failure_message", "created_at", "updated_at",
    )
    actions = ("retry_failed_charges",)

    @admin.display(description="상태", ordering="status")
    def status_display(self, obj):
        return badge(obj.get_status_display(), CHARGE_TONES.get(obj.status, "neutral"))

    @admin.display(description="금액", ordering="amount")
    def amount_display(self, obj):
        return money_html(obj.amount)

    @admin.display(description="주문")
    def order_display(self, obj):
        return order_link(obj)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="실패한 결제를 지금 다시 시도")
    def retry_failed_charges(self, request, queryset):
        if not self.can_operate(request):
            raise PermissionDenied
        # only the latest cycle of a subscription can be charged; an older failure is history
        subscription_ids = {
            charge.subscription_id
            for charge in queryset.filter(status=ShopSubscriptionCharge.STATUS_FAILED).select_related("subscription")
            if charge.cycle_no == charge.subscription.cycle_no
        }
        self.report_retries(request, sorted(subscription_ids))
