"""반품·교환 신청 (shop/returns.py) in the shop admin: the list with its filters, the request page with
the lines asked for, and the approve / reject / complete steps, each confirmed on its own page
(complete shows the refund it would make first, the way the order's line change previews it)."""

from django.contrib import admin, messages
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline

from gnu_jango.shop import returns
from gnu_jango.shop.admin._common import DatePeriodFilter
from gnu_jango.shop.delivery import delivery_company_choices
from gnu_jango.shop.models import ShopReturnRequest, ShopReturnRequestLine
from gnu_jango.shop.order_flow import canonical_status
from gnu_jango.shop.order_lines import line_label
from gnu_jango.shop.shipping import current_shipping_policy
from gnu_jango.utils.admin_display import badge, format_number

STATUS_TONES = {
    ShopReturnRequest.STATUS_REQUESTED: "warning",
    ShopReturnRequest.STATUS_APPROVED: "info",
    ShopReturnRequest.STATUS_COMPLETED: "success",
    ShopReturnRequest.STATUS_REJECTED: "danger",
    ShopReturnRequest.STATUS_WITHDRAWN: "neutral",
}
# step -> (title, button label, the statuses it starts from)
STEPS = {
    "approve": ("신청 승인", "승인", {ShopReturnRequest.STATUS_REQUESTED}),
    "reject": ("신청 거절", "거절", ShopReturnRequest.OPEN_STATUSES),
    "complete": ("처리 완료", "완료", {ShopReturnRequest.STATUS_APPROVED}),
}


class ReturnRequestDateFilter(DatePeriodFilter):
    title = "신청일"
    parameter_name = "requested_date"
    field_name = "created_at"


class ShopReturnRequestLineInline(TabularInline):
    model = ShopReturnRequestLine
    extra = 0
    can_delete = False
    fields = ("line_display", "qty", "amount_display", "line_status", "is_open")
    readonly_fields = fields
    verbose_name = "신청 상품"
    verbose_name_plural = "신청 상품"

    def has_add_permission(self, request, obj=None):
        return False

    @admin.display(description="상품")
    def line_display(self, obj):
        return line_label(obj.item) if obj.item_id else obj.it_name

    @admin.display(description="신청 금액")
    def amount_display(self, obj):
        return format_number(obj.amount)

    @admin.display(description="현재 상품 상태")
    def line_status(self, obj):
        return f"{obj.item.ct_status} · 수량 {obj.item.ct_qty}" if obj.item_id else "-"


@admin.register(ShopReturnRequest)
class ShopReturnRequestAdmin(ModelAdmin):
    list_display = (
        "request_id_display",
        "order_link",
        "customer_display",
        "kind_badge",
        "status_badge",
        "reason_display",
        "lines_display",
        "refund_display",
        "created_at",
    )
    list_display_links = ("request_id_display",)
    list_filter = ("status", "kind", "reason", ReturnRequestDateFilter)
    list_filter_submit = True
    search_fields = ("order__od_id", "order__od_name", "order__od_email", "order__od_hp", "user__username", "detail")
    list_select_related = ("order", "user")
    list_per_page = 50
    change_form_before_template = "admin/shop/return_request_change_before.html"
    inlines = [ShopReturnRequestLineInline]
    readonly_fields = (
        "order_link",
        "user",
        "kind",
        "status",
        "reason",
        "detail",
        "reject_reason",
        "return_fee",
        "refund_amount",
        "exchange_delivery_company",
        "exchange_invoice",
        "processed_by",
        "created_at",
        "approved_at",
        "closed_at",
    )
    fieldsets = (
        ("신청", {"fields": (("order_link", "user"), ("kind", "status", "reason"), "detail")}),
        (
            "처리",
            {
                "fields": (
                    ("processed_by", "approved_at", "closed_at"),
                    "reject_reason",
                    ("return_fee", "refund_amount"),
                    ("exchange_delivery_company", "exchange_invoice"),
                    "admin_memo",
                )
            },
        ),
        ("일시", {"fields": ("created_at",)}),
    )

    def has_add_permission(self, request):
        # requests come from customers (the order page)
        return False

    def has_delete_permission(self, request, obj=None):
        # a request is the record of a refund or a refusal: it is closed, never deleted
        return False

    @admin.display(description="신청번호", ordering="pk")
    def request_id_display(self, obj):
        return f"#{obj.pk}"

    @admin.display(description="주문", ordering="order__od_id")
    def order_link(self, obj):
        return format_html('<a href="{}">{}</a>', reverse("admin:shop_shoporder_change", args=[obj.order_id]), obj.order_id)

    @admin.display(description="주문자")
    def customer_display(self, obj):
        return obj.order.od_name or (obj.user.get_username() if obj.user_id else "비회원")

    @admin.display(description="구분", ordering="kind")
    def kind_badge(self, obj):
        return badge(obj.get_kind_display(), "info" if obj.kind == ShopReturnRequest.KIND_EXCHANGE else "warning")

    @admin.display(description="상태", ordering="status")
    def status_badge(self, obj):
        return badge(obj.get_status_display(), STATUS_TONES.get(obj.status, "neutral"))

    @admin.display(description="사유", ordering="reason")
    def reason_display(self, obj):
        return obj.get_reason_display()

    @admin.display(description="상품")
    def lines_display(self, obj):
        lines = list(obj.lines.all())
        if not lines:
            return "-"
        head = f"{lines[0].it_name} x {lines[0].qty}"
        return f"{head} 외 {len(lines) - 1}건" if len(lines) > 1 else head

    @admin.display(description="환불", ordering="refund_amount")
    def refund_display(self, obj):
        if obj.status != ShopReturnRequest.STATUS_COMPLETED or obj.kind != ShopReturnRequest.KIND_RETURN:
            return "-"
        return format_number(obj.refund_amount)

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("lines")

    def get_urls(self):
        return [
            path(
                "<path:object_id>/process/<str:step>/",
                self.admin_site.admin_view(self.process_view),
                name="shop_shopreturnrequest_process",
            ),
            *super().get_urls(),
        ]

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, unquote(object_id))
        if obj is not None:
            extra_context["return_request_ops"] = self.request_ops(request, obj)
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def can_change_orders(self, request):
        return request.user.has_perm("shop.change_shoporder")

    def request_ops(self, request, obj):
        can_change = self.has_change_permission(request, obj)
        return {
            "request": obj,
            "status_tone": STATUS_TONES.get(obj.status, "neutral"),
            "order_url": reverse("admin:shop_shoporder_change", args=[obj.order_id]),
            "steps": [
                {
                    "label": label,
                    "url": reverse("admin:shop_shopreturnrequest_process", args=[obj.pk, step]),
                    "danger": step == "reject",
                }
                for step, (_title, label, sources) in STEPS.items()
                if can_change and obj.status in sources and (step != "complete" or self.can_change_orders(request))
            ],
        }

    def process_view(self, request, object_id, step):
        if step not in STEPS:
            raise Http404
        obj = self.get_object(request, unquote(object_id))
        if obj is None:
            raise Http404
        if not self.has_change_permission(request, obj):
            raise PermissionDenied
        if step == "complete" and not self.can_change_orders(request):
            # completing refunds and returns order lines, as the order's own line change does
            raise PermissionDenied
        change_url = reverse("admin:shop_shopreturnrequest_change", args=[obj.pk])
        title, label, sources = STEPS[step]
        values = self.posted_values(request, obj)
        error = ""
        if request.method == "POST" and request.POST.get("confirm") and obj.status in sources:
            result = self.apply_step(request, obj, step, values)
            if result:
                self.log_change(request, obj, f"반품·교환 신청 {label}")
                self.message_user(
                    request, result.message, messages.WARNING if result.manual_refund or result.warning else messages.SUCCESS
                )
                return redirect(change_url)
            error = result.message
            obj.refresh_from_db()
        # what keeps the step from being offered at all (the form is left out)
        blocked = "" if obj.status in sources else f"'{obj.get_status_display()}' 상태의 신청은 {label}할 수 없습니다."
        plan = None
        if not blocked and step == "complete" and obj.kind == ShopReturnRequest.KIND_RETURN:
            plan, blocked = returns.preview_return(obj, values["return_fee"])
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": f"{title} - {obj.get_kind_display()} 신청 #{obj.pk}",
            "step": step,
            "step_title": title,
            "step_label": label,
            "request_obj": obj,
            "order": obj.order,
            "lines": [
                {
                    "label": line_label(line.item) if line.item_id else line.it_name,
                    "qty": line.qty,
                    "current_qty": line.item.ct_qty if line.item_id else 0,
                    "status": canonical_status(line.item.ct_status) if line.item_id else "-",
                    "amount": line.amount,
                }
                for line in obj.lines.select_related("item").order_by("pk")
            ],
            "values": values,
            "plan": plan,
            "error": error or blocked,
            "can_apply": not blocked,
            "delivery_companies": delivery_company_choices(values["delivery_company"]),
            "change_url": change_url,
        }
        return TemplateResponse(request, "admin/shop/return_request_process.html", context)

    def posted_values(self, request, obj):
        data = request.POST if request.method == "POST" else request.GET
        raw_fee = str(data.get("return_fee") or "").strip()
        try:
            fee = max(0, int(raw_fee)) if raw_fee else returns.default_return_fee(obj)
        except ValueError:
            fee = returns.default_return_fee(obj)
        return {
            "return_fee": fee,
            "reject_reason": str(data.get("reject_reason") or "").strip(),
            "delivery_company": str(data.get("delivery_company") or "").strip() or current_shipping_policy().de_delivery_company,
            "invoice": str(data.get("invoice") or "").strip(),
        }

    def apply_step(self, request, obj, step, values):
        actor = request.user.get_username()
        if step == "approve":
            return returns.approve_request(obj.pk, actor=actor)
        if step == "reject":
            return returns.reject_request(obj.pk, values["reject_reason"], actor=actor)
        return returns.complete_request(
            obj.pk,
            actor=actor,
            return_fee=values["return_fee"],
            delivery_company=values["delivery_company"],
            invoice=values["invoice"],
        )
