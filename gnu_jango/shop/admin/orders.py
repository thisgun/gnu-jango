from gnu_jango.shop.admin._common import *  # noqa: F401,F403
from django import forms
from django.db import transaction
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.utils.translation import gettext_lazy as _
from unfold.forms import ActionForm

from gnu_jango.api.shop_common import CANCELLED_STATUSES
from gnu_jango.shop.models import ORDER_ITEM_STATUS_COMPLETED
from gnu_jango.shop.order_points import item_status_update, run_save_order_points_safely, take_back_order_points

# YoungCart order states an operator moves an order through (adm/shop_admin/orderlist.php).
ADMIN_ORDER_STATUSES = ("주문", "입금", "준비", "배송", "완료", "취소")

HOPE_DATE_LABEL = "희망배송일"
KOREAN_WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")


def hope_date_label(value):
    """2026-10-25 (일), as youngcart's order view shows the hoped-for delivery date."""
    return f"{value.isoformat()} ({KOREAN_WEEKDAYS[value.weekday()]})" if value else "-"


def set_order_status(order, status, reason, *, pay_due_points=True):
    """Move an order to ``status``: its items follow, and a cancellation goes through the shared
    cancel path (stock back, coupons and points refunded once).

    Returns False for an order that is already cancelled: reopening it would not take back the
    stock, coupons and points the cancellation returned."""
    current = ShopOrder.objects.filter(pk=order.pk).values_list("od_status", flat=True).first()
    if str(current or "") in CANCELLED_STATUSES:
        return False
    if status in CANCELLED_STATUSES:
        from gnu_jango.api.v1_shop import cancel_order_and_refund_benefits

        cancel_order_and_refund_benefits(order, reason)
        return True
    with transaction.atomic():
        ShopOrder.objects.filter(pk=order.pk).update(od_status=status)
        order.items.exclude(ct_status__in=CANCELLED_STATUSES).update(**item_status_update(status))
        # youngcart orderformcartupdate.php: a paid line that leaves 완료 gives its point back
        take_back_order_points(order)
    # 완료 runs save_order_point at once, so a 0-day wait pays immediately
    if pay_due_points and status == ORDER_ITEM_STATUS_COMPLETED:
        run_save_order_points_safely()
    return True


class OrderStatusActionForm(ActionForm):
    od_status = forms.ChoiceField(
        label="변경할 주문 상태",
        required=False,
        choices=[("", "상태 선택")] + [(status, status) for status in ADMIN_ORDER_STATUSES],
    )


@admin.register(ShopOrder)
class ShopOrderAdmin(ModelAdmin):
    list_before_template = "admin/shop/order_list_before.html"
    change_form_before_template = "admin/shop/order_change_before.html"
    list_display = (
        "order_id_display",
        "customer_display",
        "order_status",
        "settlement_status",
        "receipt_status",
        "shipping_status",
        "receipt_price_display",
        "outstanding_price_display",
        "ordered_at_display",
    )
    list_display_links = ("order_id_display", "customer_display")
    search_fields = ("od_id", "od_name", "od_email", "od_hp", "od_tno", "od_app_no", "od_cash_no", "od_invoice")
    list_filter = (
        OrderStatusFilter,
        SettleCaseFilter,
        PaymentGatewayFilter,
        ReceiptStateFilter,
        ShippingStateFilter,
        OrderDateFilter,
    )
    list_select_related = ("user",)
    list_per_page = 50
    list_fullwidth = True
    list_horizontal_scrollbar_top = True
    list_filter_submit = True
    actions = ("change_selected_order_status", "export_selected_orders_csv", "export_selected_receipts_csv")
    action_form = OrderStatusActionForm
    inlines = [ShopOrderItemInline, ShopOrderDataInline]

    @admin.action(description="선택 주문 상태 변경", permissions=["change"])
    def change_selected_order_status(self, request, queryset):
        status = str(request.POST.get("od_status") or "").strip()
        if status not in ADMIN_ORDER_STATUSES:
            self.message_user(request, "변경할 주문 상태를 고르세요.", messages.WARNING)
            return
        reason = f"관리자 취소 ({request.user.get_username()})"
        changed = skipped = 0
        for order in queryset:
            if set_order_status(order, status, reason, pay_due_points=False):
                self.log_change(request, order, f"주문 상태를 '{status}'(으)로 변경")
                changed += 1
            else:
                skipped += 1
        if changed and status == ORDER_ITEM_STATUS_COMPLETED:
            run_save_order_points_safely()  # once for the whole selection
        if changed:
            self.message_user(request, f"주문 {changed}건을 '{status}' 상태로 바꿨습니다.", messages.SUCCESS)
        if skipped:
            self.message_user(request, f"이미 취소된 주문 {skipped}건은 바꾸지 않았습니다.", messages.WARNING)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "od_hope_date" and field is not None:
            field.label = HOPE_DATE_LABEL
            field.help_text = "주문서에서 고객이 고른 희망배송일입니다. 희망배송일을 쓰지 않으면 비어 있습니다."
        return field

    def save_model(self, request, obj, form, change):
        changed = set(getattr(form, "changed_data", ()) or ())
        if obj.od_invoice and not obj.od_invoice_time:
            obj.od_invoice_time = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
        if change and "od_status" in changed:
            # The new status is applied in save_related, after the item inlines are saved (an item row
            # saved later would overwrite a cancellation). The other edits are saved under the old
            # status, because the cancel path refunds only an order that is not cancelled yet.
            request._pending_order_status = obj.od_status
            obj.od_status = form.initial.get("od_status", obj.od_status)
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # item rows edited in the inline: a paid line moved off 완료 gives its point back
        take_back_order_points(form.instance)
        status = getattr(request, "_pending_order_status", None)
        if status is None:
            run_save_order_points_safely()
            return
        request._pending_order_status = None
        order = form.instance
        if set_order_status(order, status, f"관리자 취소 ({request.user.get_username()})"):
            order.refresh_from_db()
        else:
            self.message_user(request, "취소된 주문은 다른 상태로 되돌릴 수 없습니다.", messages.WARNING)
    readonly_fields = (
        "operations_snapshot",
        "settlement_snapshot",
        "shipping_snapshot",
        "receipt_snapshot",
        "memo_snapshot",
        "od_tax_invoice_request",
        "od_cash_request",
    )
    fieldsets = (
        (
            _("Operations snapshot"),
            {
                "classes": ("tab",),
                "fields": (
                    "operations_snapshot",
                    "settlement_snapshot",
                    "shipping_snapshot",
                    "receipt_snapshot",
                    "memo_snapshot",
                ),
            },
        ),
        (
            _("Order identity"),
            {
                "classes": ("tab",),
                "fields": (
                    ("od_id", "uid"),
                    ("user", "od_name"),
                    ("od_email", "od_hp", "od_tel"),
                    ("od_datetime", "od_ip"),
                ),
            },
        ),
        (
            _("Payment and settlement"),
            {
                "classes": ("tab",),
                "fields": (
                    ("od_status", "od_settle_case", "od_pg"),
                    ("od_cart_price", "od_send_cost", "od_send_cost2"),
                    ("od_receipt_price", "od_cancel_price", "od_misu"),
                    ("od_receipt_point", "od_coupon", "od_send_coupon", "od_point"),
                    ("od_tax_flag", "od_tax_mny", "od_vat_mny", "od_free_mny"),
                    ("od_tno", "od_app_no"),
                    ("od_bank_account", "od_deposit_name"),
                    ("od_receipt_time", "od_test"),
                ),
            },
        ),
        (
            _("Receipt requests"),
            {
                "classes": ("tab",),
                "fields": (
                    ("od_tax_invoice_request", "od_cash_request", "od_cash_type"),
                    ("od_tax_company", "od_tax_business_no", "od_tax_email"),
                ),
            },
        ),
        (
            _("Cash receipt"),
            {
                "classes": ("tab",),
                "fields": (
                    ("od_cash_no", "od_cash_res"),
                ),
            },
        ),
        (
            _("Shipping"),
            {
                "classes": ("tab",),
                "fields": (
                    ("od_delivery_company", "od_invoice", "od_invoice_time"),
                    ("od_hope_date",),
                ),
            },
        ),
        (
            _("Orderer address"),
            {
                "classes": ("tab",),
                "fields": (
                    ("od_zip", "od_addr1"),
                    ("od_addr2", "od_addr3"),
                ),
            },
        ),
        (
            _("Recipient address"),
            {
                "classes": ("tab",),
                "fields": (
                    ("od_b_name", "od_b_tel", "od_b_hp"),
                    ("od_b_zip", "od_b_addr1"),
                    ("od_b_addr2", "od_b_addr3"),
                ),
            },
        ),
        (
            _("Memo"),
            {
                "classes": ("tab",),
                "fields": ("od_memo",),
            },
        ),
    )

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["order_ops"] = self.order_ops_context(request)
        return super().changelist_view(request, extra_context=extra_context)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        if request.method == "GET":
            # youngcart orderform.php runs save_order_point("완료") when the order is opened
            run_save_order_points_safely()
        order = self.get_object(request, object_id)
        if order:
            extra_context["order_detail_ops"] = self.order_detail_context(request, order)
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    def order_ops_context(self, request):
        orders = ShopOrder.objects.all()
        today = timezone.localdate()
        today_orders = orders.filter(od_datetime__date=today)
        paid_orders = orders.filter(od_receipt_price__gt=0, od_misu__lte=0, od_cancel_price__lte=0)
        outstanding_orders = orders.filter(od_misu__gt=0)
        shipping_queue = paid_orders.filter(od_invoice="")
        cancelled_orders = orders.filter(od_cancel_price__gt=0)
        cash_receipt_orders = orders.exclude(od_cash_no="")
        receipt_requests = orders.filter(Q(od_tax_invoice_request=True) | Q(od_cash_request=True))
        receipt_request_count = receipt_requests.count()
        receipt_proof_needed = orders.filter(od_receipt_price__gt=0, od_cash_no="", od_tno="", od_app_no="")
        personal_pay_due = ShopPersonalPay.objects.filter(active=True, pp_price__gt=0, pp_receipt_price__lte=0)

        return {
            "metrics": [
                {
                    "label": _("Today orders"),
                    "value": format_number(today_orders.count()),
                    "hint": _("%(amount)s received") % {"amount": format_number(money_sum(today_orders, "od_receipt_price"))},
                    "tone": "info",
                    "url": self.order_list_url(request, receipt_state=None, shipping_state=None),
                },
                {
                    "label": _("Payment due"),
                    "value": format_number(outstanding_orders.count()),
                    "hint": _("%(amount)s unpaid") % {"amount": format_number(money_sum(outstanding_orders, "od_misu"))},
                    "tone": "warning",
                    "url": "/admin/shop/shoporder/unresolved/",
                },
                {
                    "label": _("Delivery queue"),
                    "value": format_number(shipping_queue.count()),
                    "hint": _("Paid orders without invoice"),
                    "tone": "neutral",
                    "url": self.order_list_url(request, receipt_state=None, shipping_state="waiting_invoice"),
                },
                {
                    "label": _("Cash receipts"),
                    "value": format_number(cash_receipt_orders.count()),
                    "hint": _("%(amount)s issued") % {"amount": format_number(money_sum(cash_receipt_orders, "od_receipt_price"))},
                    "tone": "success",
                    "url": self.order_list_url(request, receipt_state="cash", shipping_state=None),
                },
                {
                    "label": _("Receipt requests"),
                    "value": format_number(receipt_request_count),
                    "hint": _("Customer-requested tax invoices or cash receipts"),
                    "tone": "warning",
                    "url": self.order_list_url(request, receipt_state="requested", shipping_state=None),
                },
            ],
            "quick_filters": [
                self.order_quick_filter(request, _("All orders"), orders.count()),
                self.order_quick_filter(
                    request,
                    _("Payment due"),
                    outstanding_orders.count(),
                    receipt_state="outstanding",
                    tone="warning",
                ),
                self.order_quick_filter(
                    request,
                    _("Paid"),
                    paid_orders.count(),
                    receipt_state="paid",
                    tone="success",
                ),
                self.order_quick_filter(
                    request,
                    _("Delivery queue"),
                    shipping_queue.count(),
                    shipping_state="waiting_invoice",
                    tone="neutral",
                ),
                self.order_quick_filter(
                    request,
                    _("Cancelled"),
                    cancelled_orders.count(),
                    receipt_state="cancelled",
                    tone="danger",
                ),
                self.order_quick_filter(
                    request,
                    _("Cash receipt"),
                    cash_receipt_orders.count(),
                    receipt_state="cash",
                    tone="info",
                ),
                self.order_quick_filter(
                    request,
                    _("Receipt requests"),
                    receipt_request_count,
                    receipt_state="requested",
                    tone="warning",
                ),
                self.order_quick_filter(
                    request,
                    _("Receipt proof needed"),
                    receipt_proof_needed.count(),
                    receipt_state="proof_needed",
                    tone="warning" if receipt_proof_needed.exists() else "success",
                ),
            ],
            "flow_steps": [
                flow_step(
                    _("Payment due"),
                    outstanding_orders.count(),
                    _("%(amount)s unpaid") % {"amount": format_number(money_sum(outstanding_orders, "od_misu"))},
                    self.order_list_url(request, receipt_state="outstanding", shipping_state=None),
                    "warning" if outstanding_orders.exists() else "success",
                    "priority_high",
                ),
                flow_step(
                    _("Receipt requests"),
                    receipt_request_count,
                    _("Customer-requested tax invoices or cash receipts"),
                    self.order_list_url(request, receipt_state="requested", shipping_state=None),
                    "warning" if receipt_request_count else "success",
                    "receipt_long",
                ),
                flow_step(
                    _("Receipt proof"),
                    receipt_proof_needed.count(),
                    _("Paid orders without PG or cash receipt evidence"),
                    self.order_list_url(request, receipt_state="proof_needed", shipping_state=None),
                    "warning" if receipt_proof_needed.exists() else "success",
                    "fact_check",
                ),
                flow_step(
                    _("Delivery queue"),
                    shipping_queue.count(),
                    _("Paid orders without invoice"),
                    self.order_list_url(request, receipt_state=None, shipping_state="waiting_invoice"),
                    "warning" if shipping_queue.exists() else "success",
                    "local_shipping",
                ),
                flow_step(
                    _("Personal pay due"),
                    personal_pay_due.count(),
                    _("%(amount)s requested") % {"amount": format_number(money_sum(personal_pay_due, "pp_price"))},
                    "/admin/shop/shoppersonalpay/?personal_pay_state=due",
                    "warning" if personal_pay_due.exists() else "success",
                    "payments",
                ),
                flow_step(
                    _("Settlement report"),
                    paid_orders.count(),
                    _("%(amount)s received") % {"amount": format_number(money_sum(paid_orders, "od_receipt_price"))},
                    "/admin/shop/shoporder/reports/",
                    "info",
                    "monitoring",
                ),
            ],
            "shortcuts": [
                {"label": _("Settlement report"), "url": "/admin/shop/shoporder/reports/", "icon": "monitoring"},
                {"label": _("Unresolved orders"), "url": "/admin/shop/shoporder/unresolved/", "icon": "priority_high"},
                {"label": _("Product sales rank"), "url": "/admin/shop/shoporder/sales-rank/", "icon": "leaderboard"},
                {"label": _("Order print"), "url": "/admin/shop/shoporder/order-print/", "icon": "print"},
                {"label": _("Payment logs"), "url": "/admin/shop/shoporderdata/", "icon": "fact_check"},
                {"label": _("Personal pay"), "url": "/admin/shop/shoppersonalpay/", "icon": "payments"},
            ],
        }

    def order_quick_filter(self, request, label, count, receipt_state=None, shipping_state=None, tone="info"):
        active = (
            request.GET.get("receipt_state") == receipt_state
            and request.GET.get("shipping_state") == shipping_state
        )
        return {
            "label": label,
            "count": format_number(count),
            "url": self.order_list_url(request, receipt_state=receipt_state, shipping_state=shipping_state),
            "active": active,
            "tone": tone,
        }

    def order_list_url(self, request, receipt_state=None, shipping_state=None):
        params = request.GET.copy()
        for key in ("p", "all", "e", "o"):
            params.pop(key, None)
        for key, value in (("receipt_state", receipt_state), ("shipping_state", shipping_state)):
            params.pop(key, None)
            if value:
                params[key] = value
        query = params.urlencode()
        return f"{request.path}?{query}" if query else request.path

    def order_detail_context(self, request, order):
        item_count = order.items.count()
        raw_log_count = order.raw_logs.count()
        coupon_count = order.coupon_logs.count()
        personal_pay_count = order.personal_pays.count()
        paid = order.od_receipt_price and order.od_misu <= 0
        cancelled = order.od_cancel_price and order.od_cancel_price > 0
        waiting_invoice = bool(order.od_receipt_price and not order.od_invoice and not cancelled)
        cash_receipt = bool(order.od_cash_no)

        risks = []
        if order.od_misu and order.od_misu > 0:
            risks.append(
                {
                    "label": _("Payment due"),
                    "value": format_number(order.od_misu),
                    "tone": "warning",
                    "hint": _("Outstanding balance remains."),
                }
            )
        if waiting_invoice:
            risks.append(
                {
                    "label": _("Waiting invoice"),
                    "value": order.od_delivery_company or "-",
                    "tone": "warning",
                    "hint": _("Paid order has no invoice number."),
                }
            )
        if cancelled:
            risks.append(
                {
                    "label": _("Cancelled"),
                    "value": format_number(order.od_cancel_price),
                    "tone": "danger",
                    "hint": _("Cancellation amount exists."),
                }
            )
        if cash_receipt:
            risks.append(
                {
                    "label": _("Cash receipt"),
                    "value": order.od_cash_no,
                    "tone": "info",
                    "hint": _("Cash receipt number is registered."),
                }
            )
        if not risks:
            risks.append(
                {
                    "label": _("No urgent risks"),
                    "value": _("Normal"),
                    "tone": "success",
                    "hint": _("Payment and delivery signals look stable."),
                }
            )

        return {
            "order_id": order.od_id,
            "customer": order.od_name or "-",
            "email": order.od_email or "-",
            "phone": order.od_hp or order.od_tel or "-",
            "created": datetime_value(order.od_datetime),
            "status": order.od_status or "-",
            "status_tone": "danger" if cancelled else "success" if paid else "warning" if order.od_misu > 0 else "neutral",
            "settle_case": order.od_settle_case or "-",
            "pg": order.od_pg or "-",
            "receipt": format_number(order.od_receipt_price),
            "outstanding": format_number(order.od_misu),
            "cancel": format_number(order.od_cancel_price),
            "delivery_company": order.od_delivery_company or "-",
            "invoice": order.od_invoice or "-",
            "invoice_time": order.od_invoice_time or "-",
            "cash_no": order.od_cash_no or "-",
            "transaction_no": order.od_tno or "-",
            "approval_no": order.od_app_no or "-",
            "recipient": order.od_b_name or "-",
            "recipient_phone": order.od_b_hp or order.od_b_tel or "-",
            "recipient_address": " ".join(
                item for item in (order.od_b_zip, order.od_b_addr1, order.od_b_addr2, order.od_b_addr3) if item
            )
            or "-",
            "metrics": [
                {"label": _("Items"), "value": format_number(item_count), "hint": _("Order line count")},
                {"label": _("PG logs"), "value": format_number(raw_log_count), "hint": _("Imported gateway records")},
                {"label": _("Coupons"), "value": format_number(coupon_count), "hint": _("Applied coupon logs")},
                {"label": _("Personal pay"), "value": format_number(personal_pay_count), "hint": _("Linked personal payments")},
            ],
            "risks": risks,
            "links": [
                {"label": _("Back to orders"), "url": "../../", "icon": "arrow_back"},
                {"label": _("Settlement report"), "url": "../../reports/", "icon": "monitoring"},
                {"label": _("Order print"), "url": "../../order-print/?q=%s" % order.od_id, "icon": "print"},
                {"label": _("Payment logs"), "url": "/admin/shop/shoporderdata/?q=%s" % order.od_id, "icon": "fact_check"},
            ],
        }

    @admin.display(description=_("Order ID"), ordering="od_id")
    def order_id_display(self, obj):
        return obj.od_id

    @admin.display(description=_("Customer"), ordering="od_name")
    def customer_display(self, obj):
        return obj.od_name or "-"

    @admin.display(description=_("Ordered at"), ordering="od_datetime")
    def ordered_at_display(self, obj):
        return datetime_value(obj.od_datetime)

    @admin.display(description=_("Status"), ordering="od_status")
    def order_status(self, obj):
        tone = {
            "done": "success",
            "delivery": "info",
            "paid": "success",
            "cancel": "danger",
            "refund": "danger",
        }.get(str(obj.od_status).lower(), "neutral")
        return badge(obj.od_status or "-", tone)

    @admin.display(description=_("Settlement"), ordering="od_settle_case")
    def settlement_status(self, obj):
        tone = "success" if obj.od_receipt_price and obj.od_misu <= 0 else "warning"
        return badge(obj.od_settle_case or "-", tone)

    @admin.display(description=_("Receipt"))
    def receipt_status(self, obj):
        if obj.od_tax_invoice_request:
            return badge(_("Tax invoice requested"), "warning")
        if obj.od_cash_no:
            return badge(_("Cash receipt"), "info")
        if obj.od_cancel_price:
            return badge(_("Cancelled"), "danger")
        if obj.od_cash_request:
            return badge(_("Cash receipt requested"), "warning")
        if obj.od_receipt_price and obj.od_misu <= 0:
            return badge(_("Paid"), "success")
        if obj.od_misu > 0:
            return badge(_("Outstanding"), "warning")
        return badge(_("Unpaid"), "neutral")

    @admin.display(description=_("Shipping"))
    def shipping_status(self, obj):
        if obj.od_invoice:
            return badge(_("Invoiced"), "success")
        if obj.od_delivery_company:
            return badge(_("Carrier set"), "info")
        return badge(_("Pending"), "neutral")

    @admin.display(description=_("Receipt"), ordering="od_receipt_price")
    def receipt_price_display(self, obj):
        return money_html(obj.od_receipt_price)

    @admin.display(description=_("Outstanding"), ordering="od_misu")
    def outstanding_price_display(self, obj):
        return money_html(obj.od_misu, danger=obj.od_misu > 0)

    @admin.display(description=_("Operations snapshot"))
    def operations_snapshot(self, obj):
        if not obj:
            return _("Save the order before reviewing operations status.")
        cancelled = obj.od_cancel_price and obj.od_cancel_price > 0
        if cancelled:
            state, tone, next_action = _("Cancelled"), "danger", _("Check cancellation and refund trail.")
        elif obj.od_misu and obj.od_misu > 0:
            state, tone, next_action = _("Payment due"), "warning", _("Contact customer or confirm bank transfer.")
        elif obj.od_receipt_price and not obj.od_invoice:
            state, tone, next_action = _("Waiting invoice"), "warning", _("Register carrier and invoice number.")
        elif obj.od_memo:
            state, tone, next_action = _("Memo review"), "info", _("Review customer memo before shipping.")
        else:
            state, tone, next_action = _("Routine monitoring"), "success", _("No urgent operations signal.")

        return self._snapshot_panel(
            _("Operations snapshot"),
            state,
            tone,
            _("Review identity, payment, shipping, and memo before saving changes."),
            (
                (_("Order status"), obj.od_status or "-", obj.od_id),
                (_("Customer signal"), obj.od_name or "-", compact_text(obj.od_email, obj.od_hp, obj.od_tel)),
                (_("Created from"), datetime_value(obj.od_datetime), obj.od_ip or "-"),
                (_("Next action"), next_action, _("Use the tabs below for direct edits.")),
            ),
        )

    @admin.display(description=_("Settlement snapshot"))
    def settlement_snapshot(self, obj):
        if not obj:
            return "-"
        cancelled = obj.od_cancel_price and obj.od_cancel_price > 0
        if cancelled:
            state, tone = _("Cancelled"), "danger"
        elif obj.od_misu and obj.od_misu > 0:
            state, tone = _("Payment due"), "warning"
        elif obj.od_receipt_price and obj.od_misu <= 0:
            state, tone = _("Paid"), "success"
        else:
            state, tone = _("Unpaid"), "neutral"

        order_total = obj.od_cart_price + obj.od_send_cost + obj.od_send_cost2
        coupon_total = obj.od_coupon + obj.od_send_coupon
        return self._snapshot_panel(
            _("Payment and settlement"),
            state,
            tone,
            _("Receipt %(receipt)s / outstanding %(outstanding)s / cancel %(cancel)s")
            % {
                "receipt": format_number(obj.od_receipt_price),
                "outstanding": format_number(obj.od_misu),
                "cancel": format_number(obj.od_cancel_price),
            },
            (
                (_("Order amount"), format_number(order_total), _("Items %(items)s / shipping %(shipping)s") % {"items": format_number(obj.od_cart_price), "shipping": format_number(obj.od_send_cost + obj.od_send_cost2)}),
                (_("Receipt amount"), format_number(obj.od_receipt_price), compact_text(obj.od_settle_case, obj.od_pg)),
                (_("Outstanding"), format_number(obj.od_misu), compact_text(obj.od_deposit_name, obj.od_receipt_time)),
                (_("Bank account"), obj.od_bank_account or "-", ""),
                (_("Discount and point"), format_number(coupon_total + obj.od_point), _("Coupon %(coupon)s / point %(point)s") % {"coupon": format_number(coupon_total), "point": format_number(obj.od_point)}),
            ),
        )

    @admin.display(description=_("Receipt snapshot"))
    def receipt_snapshot(self, obj):
        if not obj:
            return "-"
        if obj.od_tax_invoice_request:
            state, tone = _("Tax invoice request received"), "warning"
        elif obj.od_cash_no:
            state, tone = _("Cash receipt issued"), "info"
        elif obj.od_cash_request:
            state, tone = _("Cash receipt request received"), "warning"
        elif obj.od_tno or obj.od_app_no:
            state, tone = _("Gateway evidence"), "success"
        elif obj.od_receipt_price:
            state, tone = _("Receipt proof needed"), "warning"
        else:
            state, tone = _("No receipt proof"), "neutral"

        return self._snapshot_panel(
            _("Receipt proof"),
            state,
            tone,
            _("Keep PG identifiers, cash receipt, and tax base aligned."),
            (
                (
                    _("Tax invoice request"),
                    _("Requested") if obj.od_tax_invoice_request else _("Not requested"),
                    "-",
                ),
                (
                    _("Cash receipt request"),
                    _("Requested") if obj.od_cash_request else _("Not requested"),
                    obj.get_od_cash_type_display() if obj.od_cash_request else "-",
                ),
                (
                    _("Tax invoice recipient"),
                    obj.od_tax_company or "-",
                    compact_text(obj.od_tax_business_no, obj.od_tax_email),
                ),
                (_("Cash receipt no"), obj.od_cash_no or "-", obj.od_cash_res or "-"),
                (_("TID"), obj.od_tno or "-", obj.od_app_no or "-"),
                (_("Approval no"), obj.od_app_no or "-", obj.od_receipt_time or "-"),
                (_("Tax/VAT/Free"), f"{format_number(obj.od_tax_mny)} / {format_number(obj.od_vat_mny)} / {format_number(obj.od_free_mny)}", "-"),
            ),
        )

    @admin.display(description=_("Shipping snapshot"))
    def shipping_snapshot(self, obj):
        if not obj:
            return "-"
        cancelled = obj.od_cancel_price and obj.od_cancel_price > 0
        if obj.od_invoice:
            state, tone = _("Invoiced"), "success"
        elif obj.od_receipt_price and not cancelled:
            state, tone = _("Waiting invoice"), "warning"
        elif obj.od_delivery_company:
            state, tone = _("Carrier only"), "info"
        else:
            state, tone = _("Shipping pending"), "neutral"

        recipient_address = compact_text(obj.od_b_zip, obj.od_b_addr1, obj.od_b_addr2, obj.od_b_addr3)
        return self._snapshot_panel(
            _("Shipping"),
            state,
            tone,
            _("Confirm carrier, invoice, contact, and recipient address together."),
            (
                (_("Carrier and invoice"), compact_text(obj.od_delivery_company, obj.od_invoice), obj.od_invoice_time or "-"),
                (_("Recipient"), obj.od_b_name or "-", compact_text(obj.od_b_hp, obj.od_b_tel)),
                (_("Recipient address"), recipient_address, _("Copy this into shipping tools when needed.")),
                *(((HOPE_DATE_LABEL, hope_date_label(obj.od_hope_date), ""),) if obj.od_hope_date else ()),
                (_("Shipping edit target"), _("Shipping tab"), _("Carrier, invoice, and invoice time fields.")),
            ),
        )

    @admin.display(description=_("Memo snapshot"))
    def memo_snapshot(self, obj):
        if not obj:
            return "-"
        has_memo = bool(str(obj.od_memo or "").strip())
        state = _("Memo registered") if has_memo else _("No memo")
        tone = "info" if has_memo else "neutral"
        memo = excerpt_text(obj.od_memo, 220)
        return self._snapshot_panel(
            _("Memo"),
            state,
            tone,
            _("Review customer request text before settlement or delivery changes."),
            (
                (_("Customer memo"), memo, _("Full memo is editable in the Memo tab.")),
                (_("Memo length"), format_number(len(str(obj.od_memo or ""))), _("Characters")),
                (_("Orderer address"), compact_text(obj.od_zip, obj.od_addr1, obj.od_addr2, obj.od_addr3), obj.od_name or "-"),
                (_("Recipient address"), compact_text(obj.od_b_zip, obj.od_b_addr1, obj.od_b_addr2, obj.od_b_addr3), obj.od_b_name or "-"),
            ),
        )

    def _snapshot_panel(self, title, state, tone, description, cards):
        return snapshot_panel(title, state, tone, description, cards)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "reports/",
                self.admin_site.admin_view(self.reports_view),
                name="shop_shoporder_reports",
            ),
            path(
                "sales-rank/",
                self.admin_site.admin_view(self.sales_rank_view),
                name="shop_shoporder_sales_rank",
            ),
            path(
                "order-print/",
                self.admin_site.admin_view(self.order_print_view),
                name="shop_shoporder_print",
            ),
            path(
                "unresolved/",
                self.admin_site.admin_view(self.unresolved_orders_view),
                name="shop_shoporder_unresolved",
            ),
        ]
        return custom_urls + urls

    @admin.action(description=_("Export selected orders CSV"))
    def export_selected_orders_csv(self, request, queryset):
        return self.orders_csv(queryset)

    @admin.action(description=_("Export selected receipts CSV"))
    def export_selected_receipts_csv(self, request, queryset):
        return self.receipts_csv(queryset, ShopPersonalPay.objects.none())

    def sales_rank_view(self, request):
        start, end = report_date_range(request)
        export_type = request.GET.get("export")
        orders = filter_datetime_range(ShopOrder.objects.all(), "od_datetime", start, end)
        order_items = ShopOrderItem.objects.filter(order__in=orders)
        rows = self.product_sales_rank_rows(order_items, limit=500 if export_type == "csv" else 100)

        if export_type == "csv":
            return self.sales_rank_csv(rows)

        total_sales = order_items.aggregate(value=Sum(order_line_sales_expression()))["value"] or 0
        total_points = order_items.aggregate(value=Sum(order_line_point_expression()))["value"] or 0
        metrics = [
            {
                "label": _("Ranked products"),
                "value": format_number(len(rows)),
                "hint": _("Top selling products in the selected period"),
            },
            {
                "label": _("Sold quantity"),
                "value": format_number(order_items.aggregate(value=Sum("ct_qty"))["value"]),
                "hint": _("%(count)s order lines") % {"count": format_number(order_items.count())},
            },
            {
                "label": _("Product sales"),
                "value": format_number(total_sales),
                "hint": _("%(count)s orders") % {"count": format_number(orders.count())},
            },
            {
                "label": _("Reward points"),
                "value": format_number(total_points),
                "hint": _("Calculated from order item points"),
            },
        ]

        context = {
            **self.admin_site.each_context(request),
            "title": _("Product sales rank"),
            "subtitle": _("Compare product quantity, revenue, and order contribution."),
            "opts": self.model._meta,
            "report_path": request.path,
            "filters": {
                "date_from": start.isoformat() if start else "",
                "date_to": end.isoformat() if end else "",
            },
            "metrics": metrics,
            "rank_rows": rows,
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/shop/sales_rank.html", context)

    def product_sales_rank_rows(self, order_items, limit=100):
        ranked_queryset = (
            order_items.values("product_id", "it_id", "it_name")
            .annotate(
                line_count=Count("pk"),
                order_count=Count("order_id", distinct=True),
                quantity=Sum("ct_qty"),
                gross_sales=Sum(order_line_sales_expression()),
                reward_points=Sum(order_line_point_expression()),
            )
            .order_by("-gross_sales", "-quantity", "it_name")
        )
        raw_rows = list(ranked_queryset[:limit])
        product_keys = {row["product_id"] or row["it_id"] for row in raw_rows if row.get("product_id") or row.get("it_id")}
        existing_products = set(ShopProduct.objects.filter(it_id__in=product_keys).values_list("it_id", flat=True))
        max_sales = max([row["gross_sales"] or 0 for row in raw_rows] or [0])

        rows = []
        for index, row in enumerate(raw_rows, start=1):
            lookup_key = row["product_id"] or row["it_id"] or ""
            gross_sales = row["gross_sales"] or 0
            rows.append(
                {
                    "rank": index,
                    "product_id": lookup_key or "-",
                    "product_lookup": lookup_key if lookup_key in existing_products else "",
                    "name": row["it_name"] or _("Unnamed product"),
                    "line_count": format_number(row["line_count"]),
                    "order_count": format_number(row["order_count"]),
                    "quantity": format_number(row["quantity"]),
                    "gross_sales": format_number(gross_sales),
                    "reward_points": format_number(row["reward_points"]),
                    "share": round((gross_sales / max_sales) * 100) if max_sales else 0,
                }
            )
        return rows

    def order_print_view(self, request):
        start, end = report_date_range(request)
        receipt_state = request.GET.get("receipt_state") or ""
        shipping_state = request.GET.get("shipping_state") or ""
        query = str(request.GET.get("q") or "").strip()
        limit = self.order_print_limit(request)
        export_type = request.GET.get("export")

        orders = filter_datetime_range(ShopOrder.objects.all(), "od_datetime", start, end)
        orders = self.apply_order_print_filters(orders, receipt_state, shipping_state)
        if query:
            orders = orders.filter(
                Q(od_id__icontains=query)
                | Q(od_name__icontains=query)
                | Q(od_email__icontains=query)
                | Q(od_hp__icontains=query)
                | Q(od_invoice__icontains=query)
            )
        orders = orders.select_related("user").prefetch_related("items").order_by("-od_datetime", "-od_id")

        if export_type == "csv":
            return self.order_print_csv(orders)

        order_count = orders.count()
        rows = self.order_print_rows(orders[:limit])
        metrics = [
            {"label": _("Orders"), "value": format_number(order_count), "hint": _("Matched printable orders")},
            {"label": _("Print rows"), "value": format_number(len(rows)), "hint": _("Limited for browser print stability")},
            {"label": _("Receipt total"), "value": format_number(money_sum(orders, "od_receipt_price")), "hint": _("Collected amount")},
            {"label": _("Outstanding"), "value": format_number(money_sum(orders, "od_misu")), "hint": _("Remaining balance")},
        ]

        context = {
            **self.admin_site.each_context(request),
            "title": _("Order print"),
            "subtitle": _("Print order, payment, receipt, and delivery handoff sheets."),
            "opts": self.model._meta,
            "report_path": request.path,
            "filters": {
                "date_from": start.isoformat() if start else "",
                "date_to": end.isoformat() if end else "",
                "receipt_state": receipt_state,
                "shipping_state": shipping_state,
                "q": query,
                "limit": str(limit),
            },
            "metrics": metrics,
            "print_rows": rows,
            "receipt_state_choices": [
                ("", _("All receipt states")),
                ("paid", _("Paid")),
                ("outstanding", _("Payment due")),
                ("cancelled", _("Cancelled")),
                ("cash", _("Cash receipt")),
                ("requested", _("Receipt requests")),
                ("proof_needed", _("Receipt proof needed")),
            ],
            "shipping_state_choices": [
                ("", _("All shipping states")),
                ("waiting_invoice", _("Delivery queue")),
                ("shipped", _("Invoice registered")),
            ],
            "limit_choices": [50, 100, 200],
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/shop/order_print.html", context)

    def order_print_limit(self, request):
        try:
            limit = int(request.GET.get("limit") or 100)
        except (TypeError, ValueError):
            limit = 100
        return min(max(limit, 20), 200)

    def apply_order_print_filters(self, orders, receipt_state, shipping_state):
        if receipt_state == "paid":
            orders = orders.filter(od_receipt_price__gt=0, od_misu__lte=0, od_cancel_price__lte=0)
        elif receipt_state == "outstanding":
            orders = orders.filter(od_misu__gt=0)
        elif receipt_state == "cancelled":
            orders = orders.filter(od_cancel_price__gt=0)
        elif receipt_state == "cash":
            orders = orders.exclude(od_cash_no="")
        elif receipt_state == "requested":
            orders = orders.filter(Q(od_tax_invoice_request=True) | Q(od_cash_request=True))
        elif receipt_state == "proof_needed":
            orders = orders.filter(od_receipt_price__gt=0, od_cash_no="", od_tno="", od_app_no="")

        if shipping_state == "waiting_invoice":
            orders = orders.filter(od_receipt_price__gt=0, od_cancel_price__lte=0, od_invoice="")
        elif shipping_state == "shipped":
            orders = orders.exclude(od_invoice="")
        return orders

    def order_print_rows(self, orders):
        rows = []
        for order in orders:
            items = list(order.items.all())
            item_labels = [f"{item.it_name or item.it_id} x {format_number(item.ct_qty)}" for item in items[:3]]
            more_count = max(len(items) - 3, 0)
            if more_count:
                item_labels.append(_("+%(count)s more") % {"count": format_number(more_count)})
            rows.append(
                {
                    "id": order.od_id,
                    "name": order.od_name or "-",
                    "phone": order.od_hp or order.od_tel or "-",
                    "email": order.od_email or "-",
                    "time": datetime_value(order.od_datetime),
                    "status": order.od_status or "-",
                    "settle_case": order.od_settle_case or "-",
                    "pg": order.od_pg or "-",
                    "receipt": format_number(order.od_receipt_price),
                    "outstanding": format_number(order.od_misu),
                    "cash_no": order.od_cash_no or "-",
                    "transaction_no": order.od_tno or "-",
                    "approval_no": order.od_app_no or "-",
                    "recipient": order.od_b_name or "-",
                    "recipient_phone": order.od_b_hp or order.od_b_tel or "-",
                    "recipient_address": compact_text(order.od_b_zip, order.od_b_addr1, order.od_b_addr2, order.od_b_addr3),
                    "delivery_company": order.od_delivery_company or "-",
                    "invoice": order.od_invoice or "-",
                    "invoice_time": order.od_invoice_time or "-",
                    "items": ", ".join(str(label) for label in item_labels) or "-",
                    "item_count": format_number(len(items)),
                    "memo": excerpt_text(order.od_memo, 90),
                }
            )
        return rows

    def unresolved_orders_view(self, request):
        start, end = report_date_range(request)
        query = str(request.GET.get("q") or "").strip()[:120]
        settle_case = str(request.GET.get("settle_case") or "").strip()
        ordering = str(request.GET.get("ordering") or "oldest").strip()

        orders = filter_datetime_range(
            ShopOrder.objects.filter(od_misu__gt=0),
            "od_datetime",
            start,
            end,
        )
        settle_case_choices = list(
            orders.exclude(od_settle_case="")
            .values_list("od_settle_case", flat=True)
            .distinct()
            .order_by("od_settle_case")
        )
        if settle_case not in settle_case_choices:
            settle_case = ""
        if settle_case:
            orders = orders.filter(od_settle_case=settle_case)
        if query:
            orders = orders.filter(
                Q(od_id__icontains=query)
                | Q(od_name__icontains=query)
                | Q(od_b_name__icontains=query)
                | Q(od_email__icontains=query)
                | Q(od_hp__icontains=query)
                | Q(od_tel__icontains=query)
                | Q(od_deposit_name__icontains=query)
                | Q(od_bank_account__icontains=query)
            )

        ordering_choices = {
            "oldest": ("od_datetime", "od_id"),
            "newest": ("-od_datetime", "-od_id"),
            "largest": ("-od_misu", "od_datetime", "od_id"),
        }
        if ordering not in ordering_choices:
            ordering = "oldest"
        orders = orders.select_related("user").order_by(*ordering_choices[ordering])

        if request.GET.get("export") == "csv":
            return self.orders_csv(orders)

        total_count = orders.count()
        total_due = money_sum(orders, "od_misu")
        bank_orders = orders.filter(od_settle_case__in=("bank", "무통장", "무통장입금"))
        oldest_order = orders.order_by("od_datetime", "od_id").first()
        page_obj = Paginator(orders, 50).get_page(request.GET.get("page"))
        rows = [
            {
                "id": order.od_id,
                "name": order.od_name or "-",
                "status": order.od_status or "-",
                "settle_case": order.od_settle_case or "-",
                "bank_account": order.od_bank_account or "-",
                "deposit_name": order.od_deposit_name or "-",
                "receipt": format_number(order.od_receipt_price),
                "outstanding": format_number(order.od_misu),
                "time": datetime_value(order.od_datetime),
            }
            for order in page_obj.object_list
        ]
        export_params = request.GET.copy()
        export_params["export"] = "csv"
        page_params = request.GET.copy()
        page_params.pop("page", None)
        page_params.pop("export", None)
        context = {
            **self.admin_site.each_context(request),
            "title": _("Unresolved orders"),
            "subtitle": _("Orders with an outstanding balance, with filters and export."),
            "opts": self.model._meta,
            "report_path": request.path,
            "filters": {
                "date_from": start.isoformat() if start else "",
                "date_to": end.isoformat() if end else "",
                "q": query,
                "settle_case": settle_case,
                "ordering": ordering,
            },
            "settle_case_choices": settle_case_choices,
            "ordering_choices": [
                ("oldest", _("Oldest first")),
                ("newest", _("Newest first")),
                ("largest", _("Largest balance first")),
            ],
            "metrics": [
                {"label": _("Matching orders"), "value": format_number(total_count), "hint": _("Orders with an outstanding balance")},
                {"label": _("Total outstanding"), "value": format_number(total_due), "hint": _("Amount requiring settlement")},
                {"label": _("Bank transfer orders"), "value": format_number(bank_orders.count()), "hint": _("Orders requiring a depositor match")},
                {"label": _("Oldest order"), "value": datetime_value(oldest_order.od_datetime) if oldest_order else "-", "hint": _("Oldest matching outstanding order")},
            ],
            "orders_page": page_obj,
            "rows": rows,
            "page_query": page_params.urlencode(),
            "export_url": f"{request.path}?{export_params.urlencode()}",
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/shop/unresolved_orders.html", context)

    def reports_view(self, request):
        start, end = report_date_range(request)
        period = request.GET.get("period") if request.GET.get("period") in {"day", "month"} else "month"
        export_type = request.GET.get("export")

        orders = filter_datetime_range(ShopOrder.objects.all(), "od_datetime", start, end)
        order_items = ShopOrderItem.objects.filter(order__in=orders)
        coupon_logs = filter_datetime_range(ShopCouponLog.objects.all(), "cl_datetime", start, end)
        raw_logs = filter_datetime_range(ShopOrderData.objects.all(), "dt_time", start, end)
        personal_pays = filter_datetime_range(ShopPersonalPay.objects.all(), "pp_time", start, end)
        issued_coupons = ShopCoupon.objects.all()
        if start:
            issued_coupons = issued_coupons.filter(created_at__date__gte=start)
        if end:
            issued_coupons = issued_coupons.filter(created_at__date__lte=end)

        if export_type == "orders":
            return self.orders_csv(orders)
        if export_type == "sales":
            return self.sales_csv(orders, period)
        if export_type == "coupons":
            return self.coupons_csv(coupon_logs)
        if export_type == "receipts":
            return self.receipts_csv(orders, personal_pays)

        paid_orders = orders.filter(od_receipt_price__gt=0, od_misu__lte=0)
        outstanding_orders = orders.filter(od_misu__gt=0)
        cancelled_orders = orders.filter(od_cancel_price__gt=0)
        cash_receipt_orders = orders.exclude(od_cash_no="")
        receipt_proof_needed = orders.filter(od_receipt_price__gt=0, od_cash_no="", od_tno="", od_app_no="")
        shipping_queue = paid_orders.filter(od_cancel_price__lte=0, od_invoice="")
        personal_pay_due = personal_pays.filter(active=True, pp_price__gt=0, pp_receipt_price__lte=0)

        metrics = [
            {"label": _("Orders"), "value": format_number(orders.count()), "hint": _("%(count)s items") % {"count": format_number(order_items.count())}},
            {"label": _("Receipt total"), "value": format_number(money_sum(orders, "od_receipt_price")), "hint": _("Paid and confirmed")},
            {"label": _("Tax base"), "value": format_number(money_sum(orders, "od_tax_mny")), "hint": _("Order amount excluding VAT")},
            {"label": _("VAT"), "value": format_number(money_sum(orders, "od_vat_mny")), "hint": _("Calculated order VAT")},
            {"label": _("Tax exempt"), "value": format_number(money_sum(orders, "od_free_mny")), "hint": _("Tax-exempt product amount")},
            {"label": _("Outstanding"), "value": format_number(money_sum(orders, "od_misu")), "hint": _("Unpaid balance")},
            {"label": _("Cancelled"), "value": format_number(money_sum(orders, "od_cancel_price")), "hint": _("%(count)s orders") % {"count": format_number(cancelled_orders.count())}},
            {"label": _("Cash receipts"), "value": format_number(cash_receipt_orders.count()), "hint": format_number(money_sum(cash_receipt_orders, "od_receipt_price"))},
            {"label": _("Coupon discount"), "value": format_number(money_sum(coupon_logs, "cp_price")), "hint": _("%(count)s usage logs") % {"count": format_number(coupon_logs.count())}},
            {"label": _("Personal pay"), "value": format_number(money_sum(personal_pays, "pp_receipt_price")), "hint": _("%(count)s requests") % {"count": format_number(personal_pays.count())}},
            {"label": _("Raw PG logs"), "value": format_number(raw_logs.count()), "hint": _("Imported order data")},
        ]

        receipt_command_queue = [
            {
                "label": _("Payment due"),
                "value": format_number(outstanding_orders.count()),
                "hint": _("%(amount)s unpaid") % {"amount": format_number(money_sum(outstanding_orders, "od_misu"))},
                "url": "/admin/shop/shoporder/unresolved/",
                "tone": "warning" if outstanding_orders.exists() else "success",
                "icon": "priority_high",
            },
            {
                "label": _("Receipt proof needed"),
                "value": format_number(receipt_proof_needed.count()),
                "hint": _("Paid orders without PG or cash receipt evidence"),
                "url": "/admin/shop/shoporder/?receipt_state=proof_needed",
                "tone": "warning" if receipt_proof_needed.exists() else "success",
                "icon": "fact_check",
            },
            {
                "label": _("Delivery queue"),
                "value": format_number(shipping_queue.count()),
                "hint": _("Paid orders without invoice"),
                "url": "/admin/shop/shoporder/?shipping_state=waiting_invoice",
                "tone": "warning" if shipping_queue.exists() else "success",
                "icon": "local_shipping",
            },
            {
                "label": _("Personal pay due"),
                "value": format_number(personal_pay_due.count()),
                "hint": _("%(amount)s requested") % {"amount": format_number(money_sum(personal_pay_due, "pp_price"))},
                "url": "/admin/shop/shoppersonalpay/?personal_pay_state=due",
                "tone": "warning" if personal_pay_due.exists() else "success",
                "icon": "payments",
            },
            {
                "label": _("Raw PG logs"),
                "value": format_number(raw_logs.count()),
                "hint": _("Imported order data"),
                "url": "/admin/shop/shoporderdata/",
                "tone": "info" if raw_logs.exists() else "neutral",
                "icon": "fact_check",
            },
        ]

        settlement_pipeline = [
            flow_step(
                _("Payment due"),
                outstanding_orders.count(),
                _("%(amount)s unpaid") % {"amount": format_number(money_sum(outstanding_orders, "od_misu"))},
                "/admin/shop/shoporder/unresolved/",
                "warning" if outstanding_orders.exists() else "success",
                "priority_high",
            ),
            flow_step(
                _("Receipt proof"),
                receipt_proof_needed.count(),
                _("Paid orders without PG or cash receipt evidence"),
                "/admin/shop/shoporder/?receipt_state=proof_needed",
                "warning" if receipt_proof_needed.exists() else "success",
                "fact_check",
            ),
            flow_step(
                _("Delivery queue"),
                shipping_queue.count(),
                _("Paid orders without invoice"),
                "/admin/shop/shoporder/?shipping_state=waiting_invoice",
                "warning" if shipping_queue.exists() else "success",
                "local_shipping",
            ),
            flow_step(
                _("Personal pay due"),
                personal_pay_due.count(),
                _("%(amount)s requested") % {"amount": format_number(money_sum(personal_pay_due, "pp_price"))},
                "/admin/shop/shoppersonalpay/?personal_pay_state=due",
                "warning" if personal_pay_due.exists() else "success",
                "payments",
            ),
            flow_step(
                _("Export receipts"),
                cash_receipt_orders.count(),
                _("Download receipt evidence CSV for handoff."),
                "%s?period=%s&date_from=%s&date_to=%s&export=receipts"
                % (
                    request.path,
                    period,
                    start.isoformat() if start else "",
                    end.isoformat() if end else "",
                ),
                "info",
                "download",
            ),
        ]

        top_coupons = [
            {
                "key": row["cp_id"] or _("Unspecified"),
                "count": row["count"],
                "count_display": format_number(row["count"]),
                "amount": row["discount"] or 0,
                "amount_display": format_number(row["discount"]),
            }
            for row in coupon_logs.values("cp_id")
            .annotate(count=Count("cl_id"), discount=Sum("cp_price"))
            .order_by("-discount", "cp_id")[:12]
        ]

        context = {
            **self.admin_site.each_context(request),
            "title": _("Shop settlement report"),
            "subtitle": _("Sales, payment logs, coupons, receipts, and personal pay"),
            "opts": self.model._meta,
            "report_path": request.path,
            "filters": {
                "date_from": start.isoformat() if start else "",
                "date_to": end.isoformat() if end else "",
                "period": period,
            },
            "metrics": metrics,
            "receipt_command_queue": receipt_command_queue,
            "settlement_pipeline": settlement_pipeline,
            "sales_series": sales_series(orders, period),
            "status_rows": grouped_money(orders, "od_status", "od_receipt_price"),
            "settle_rows": grouped_money(orders, "od_settle_case", "od_receipt_price"),
            "pg_rows": grouped_money(orders, "od_pg", "od_receipt_price"),
            "receipt_rows": [
                report_row(_("Paid"), paid_orders, "od_receipt_price"),
                report_row(_("Outstanding"), outstanding_orders, "od_misu"),
                report_row(_("Cancelled"), cancelled_orders, "od_cancel_price"),
                report_row(_("Cash receipt"), cash_receipt_orders, "od_receipt_price"),
            ],
            "top_coupons": top_coupons,
            "coupon_summary": {
                "issued": format_number(issued_coupons.count()),
                "unused": format_number(issued_coupons.filter(cp_used="").count()),
                "used_logs": format_number(coupon_logs.count()),
                "used_discount": format_number(money_sum(coupon_logs, "cp_price")),
            },
            "outstanding_orders": brief_order_rows(outstanding_orders.order_by("-od_datetime")[:10]),
            "cash_receipt_orders": brief_order_rows(cash_receipt_orders.order_by("-od_datetime")[:10]),
            "recent_raw_logs": brief_raw_log_rows(raw_logs.order_by("-dt_time")[:10]),
            "personal_pay_rows": brief_personal_pay_rows(personal_pays.order_by("-pp_time")[:10]),
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/shop/reports.html", context)

    def orders_csv(self, orders):
        queryset = orders.prefetch_related("items", "raw_logs", "coupon_logs").order_by("-od_datetime", "-od_id")
        return csv_response(
            "shop-orders-report.csv",
            [
                "od_id",
                "od_datetime",
                "od_name",
                "od_status",
                "od_settle_case",
                "od_bank_account",
                "od_deposit_name",
                "od_pg",
                "od_cart_price",
                "od_receipt_price",
                "od_cancel_price",
                "od_misu",
                "od_coupon",
                "od_send_coupon",
                "od_tax_flag",
                "od_tax_mny",
                "od_vat_mny",
                "od_free_mny",
                "item_count",
                "raw_log_count",
                "coupon_log_count",
            ],
            (
                [
                    order.od_id,
                    datetime_value(order.od_datetime),
                    order.od_name,
                    order.od_status,
                    order.od_settle_case,
                    order.od_bank_account,
                    order.od_deposit_name,
                    order.od_pg,
                    order.od_cart_price,
                    order.od_receipt_price,
                    order.od_cancel_price,
                    order.od_misu,
                    order.od_coupon,
                    order.od_send_coupon,
                    order.od_tax_flag,
                    order.od_tax_mny,
                    order.od_vat_mny,
                    order.od_free_mny,
                    # len(...all()) reuses the prefetched cache; .count() would
                    # issue a fresh query per order per relation (3N extra).
                    len(order.items.all()),
                    len(order.raw_logs.all()),
                    len(order.coupon_logs.all()),
                ]
                for order in queryset
            ),
        )

    def sales_csv(self, orders, period):
        return csv_response(
            "shop-sales-series-report.csv",
            [
                "period",
                "order_count",
                "receipt_price",
                "cancel_price",
                "coupon_price",
                "tax_base",
                "vat_amount",
                "exempt_amount",
            ],
            (
                [
                    row["period"],
                    row["order_count"],
                    row["receipt_price"],
                    row["cancel_price_display"].replace(",", ""),
                    row["coupon_price_display"].replace(",", ""),
                    row["tax_base"],
                    row["vat_amount"],
                    row["exempt_amount"],
                ]
                for row in sales_series(orders, period)
            ),
        )

    def sales_rank_csv(self, rows):
        return csv_response(
            "shop-product-sales-rank.csv",
            [
                "rank",
                "product_id",
                "product_name",
                "line_count",
                "order_count",
                "quantity",
                "gross_sales",
                "reward_points",
                "share_percent",
            ],
            (
                [
                    row["rank"],
                    row["product_id"],
                    row["name"],
                    str(row["line_count"]).replace(",", ""),
                    str(row["order_count"]).replace(",", ""),
                    str(row["quantity"]).replace(",", ""),
                    str(row["gross_sales"]).replace(",", ""),
                    str(row["reward_points"]).replace(",", ""),
                    row["share"],
                ]
                for row in rows
            ),
        )

    def coupons_csv(self, coupon_logs):
        queryset = coupon_logs.select_related("coupon", "order", "user").order_by("-cl_datetime", "-cl_id")
        return csv_response(
            "shop-coupon-usage-report.csv",
            ["cl_id", "cl_datetime", "cp_id", "cp_subject", "mb_id", "od_id", "cp_price"],
            (
                [
                    log.cl_id,
                    datetime_value(log.cl_datetime),
                    log.cp_id,
                    log.coupon.cp_subject if log.coupon_id else "",
                    log.mb_id,
                    log.od_id,
                    log.cp_price,
                ]
                for log in queryset
            ),
        )

    def receipts_csv(self, orders, personal_pays):
        rows = []
        for order in orders.order_by("-od_datetime", "-od_id"):
            rows.append(
                [
                    "order",
                    order.od_id,
                    datetime_value(order.od_datetime),
                    order.od_name,
                    order.od_settle_case,
                    order.od_pg,
                    order.od_receipt_price,
                    order.od_misu,
                    order.od_cash_no,
                    order.od_cash_res,
                    order.od_receipt_time,
                    order.od_tno,
                    order.od_app_no,
                    order.od_tax_flag,
                    order.od_tax_mny,
                    order.od_vat_mny,
                    order.od_free_mny,
                ]
            )
        for pay in personal_pays.order_by("-pp_time", "-pp_id"):
            rows.append(
                [
                    "personal_pay",
                    pay.pp_id,
                    datetime_value(pay.pp_time),
                    pay.pp_name,
                    pay.pp_settle_case,
                    pay.pp_pg,
                    pay.pp_receipt_price,
                    max((pay.pp_price or 0) - (pay.pp_receipt_price or 0), 0),
                    pay.pp_cash_no,
                    "",
                    pay.pp_receipt_time,
                    pay.pp_tno,
                    pay.pp_app_no,
                    "",
                    "",
                    "",
                    "",
                ]
            )
        return csv_response(
            "shop-receipts-report.csv",
            [
                "type",
                "id",
                "time",
                "name",
                "settle_case",
                "pg",
                "receipt_price",
                "outstanding",
                "cash_no",
                "cash_response",
                "receipt_time",
                "transaction_no",
                "approval_no",
                "tax_flag",
                "tax_base",
                "vat_amount",
                "exempt_amount",
            ],
            rows,
        )

    def order_print_csv(self, orders):
        rows = self.order_print_rows(orders[:1000])
        return csv_response(
            "shop-order-print.csv",
            [
                "od_id",
                "od_datetime",
                "od_name",
                "od_phone",
                "od_email",
                "status",
                "settle_case",
                "pg",
                "receipt_price",
                "outstanding",
                "cash_no",
                "transaction_no",
                "approval_no",
                "recipient",
                "recipient_phone",
                "recipient_address",
                "delivery_company",
                "invoice",
                "invoice_time",
                "item_count",
                "items",
                "memo",
            ],
            (
                [
                    row["id"],
                    row["time"],
                    row["name"],
                    row["phone"],
                    row["email"],
                    row["status"],
                    row["settle_case"],
                    row["pg"],
                    str(row["receipt"]).replace(",", ""),
                    str(row["outstanding"]).replace(",", ""),
                    row["cash_no"],
                    row["transaction_no"],
                    row["approval_no"],
                    row["recipient"],
                    row["recipient_phone"],
                    row["recipient_address"],
                    row["delivery_company"],
                    row["invoice"],
                    row["invoice_time"],
                    str(row["item_count"]).replace(",", ""),
                    row["items"],
                    row["memo"],
                ]
                for row in rows
            ),
        )



@admin.register(ShopOrderData)
class ShopOrderDataAdmin(ModelAdmin):
    list_display = (
        "log_id_display",
        "order_signal",
        "cart_id_display",
        "member_signal",
        "gateway_badge",
        "payload_signal",
        "imported_at_display",
    )
    search_fields = ("log_id", "od_id", "cart_id", "mb_id", "dt_pg", "dt_data")
    list_filter = (PaymentLogGatewayFilter, PaymentLogDateFilter)
    readonly_fields = ("log_snapshot", "log_id", "dt_data_preview")
    fieldsets = (
        (
            _("Payment log snapshot"),
            {
                "classes": ("tab",),
                "fields": ("log_snapshot",),
            },
        ),
        (
            _("Log identity"),
            {
                "classes": ("tab",),
                "fields": (
                    ("log_id", "dt_pg"),
                    ("order", "od_id"),
                    ("cart_id", "user", "mb_id"),
                    "dt_time",
                ),
            },
        ),
        (
            _("Raw payload"),
            {
                "classes": ("tab",),
                "fields": ("dt_data_preview", "dt_data"),
            },
        ),
    )
    list_fullwidth = True

    @admin.display(description=_("Log ID"), ordering="log_id")
    def log_id_display(self, obj):
        return obj.log_id

    @admin.display(description=_("Order"), ordering="od_id")
    def order_signal(self, obj):
        if obj.order_id:
            return badge(obj.od_id or obj.order_id, "success")
        if obj.od_id:
            return badge(obj.od_id, "warning")
        return badge(_("Unlinked"), "neutral")

    @admin.display(description=_("Cart ID"), ordering="cart_id")
    def cart_id_display(self, obj):
        return obj.cart_id or "-"

    @admin.display(description=_("Member"), ordering="mb_id")
    def member_signal(self, obj):
        return obj.mb_id or getattr(obj.user, "username", "") or "-"

    @admin.display(description=_("Gateway"), ordering="dt_pg")
    def gateway_badge(self, obj):
        return badge(obj.dt_pg or _("Unspecified"), "info" if obj.dt_pg else "neutral")

    @admin.display(description=_("Payload"))
    def payload_signal(self, obj):
        length = len(obj.dt_data or "")
        return badge(_("%(count)s chars") % {"count": format_number(length)}, "success" if length else "neutral")

    @admin.display(description=_("Imported at"), ordering="dt_time")
    def imported_at_display(self, obj):
        return datetime_value(obj.dt_time) or "-"

    @admin.display(description=_("Payment log snapshot"))
    def log_snapshot(self, obj):
        if not obj:
            return "-"
        if obj.order_id:
            state, tone = _("Linked to order"), "success"
        elif obj.od_id:
            state, tone = _("Order ID only"), "warning"
        else:
            state, tone = _("Unlinked payment log"), "neutral"

        return snapshot_panel(
            _("Payment log snapshot"),
            state,
            tone,
            _("Review gateway, order key, member key, and raw payload together."),
            (
                (_("Gateway"), obj.dt_pg or "-", obj.log_id),
                (_("Order reference"), obj.od_id or "-", obj.order_id or "-"),
                (_("Cart and member"), compact_text(obj.cart_id, obj.mb_id), getattr(obj.user, "username", "") or "-"),
                (_("Payload size"), _("%(count)s chars") % {"count": format_number(len(obj.dt_data or ""))}, datetime_value(obj.dt_time)),
            ),
        )

    @admin.display(description=_("Payload preview"))
    def dt_data_preview(self, obj):
        if not obj:
            return "-"
        return raw_preview(obj.dt_data)


@admin.register(ShopPersonalPay)
class ShopPersonalPayAdmin(ModelAdmin):
    change_form_before_template = "admin/shop/personal_pay_change_before.html"
    list_display = (
        "personal_pay_id_display",
        "customer_display",
        "request_price_display",
        "personal_pay_status",
        "settlement_badge",
        "receipt_proof",
        "linked_order",
        "active_status",
        "requested_at_display",
    )
    list_display_links = ("personal_pay_id_display", "customer_display")
    search_fields = ("pp_id", "pp_name", "pp_email", "pp_hp", "user__username", "pp_tno", "pp_app_no", "pp_cash_no")
    list_filter = (PersonalPayStateFilter, PersonalPaySettleCaseFilter, PersonalPayActiveFilter, PersonalPayDateFilter)
    readonly_fields = ("personal_pay_snapshot",)
    fieldsets = (
        (
            _("Personal pay snapshot"),
            {
                "classes": ("tab",),
                "fields": ("personal_pay_snapshot",),
            },
        ),
        (
            _("Customer"),
            {
                "classes": ("tab",),
                "fields": (
                    ("user", "order"),
                    ("pp_name", "pp_email", "pp_hp"),
                    "active",
                ),
            },
        ),
        (
            _("Payment request"),
            {
                "classes": ("tab",),
                "fields": (
                    ("pp_price", "pp_receipt_price"),
                    ("pp_settle_case", "pp_pg"),
                    ("pp_bank_account", "pp_deposit_name"),
                    "pp_time",
                ),
            },
        ),
        (
            _("Receipt proof"),
            {
                "classes": ("tab",),
                "fields": (
                    ("pp_tno", "pp_app_no"),
                    ("pp_cash", "pp_cash_no"),
                    "pp_receipt_time",
                ),
            },
        ),
        (
            _("Content"),
            {
                "classes": ("tab",),
                "fields": ("pp_content",),
            },
        ),
    )
    list_fullwidth = True

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        personal_pay = self.get_object(request, object_id)
        if personal_pay:
            extra_context["personal_pay_detail_ops"] = self.personal_pay_detail_context(personal_pay)
        return super().change_view(request, object_id, form_url, extra_context=extra_context)

    @admin.display(description=_("Personal pay ID"), ordering="pp_id")
    def personal_pay_id_display(self, obj):
        return obj.pp_id

    @admin.display(description=_("Customer"), ordering="pp_name")
    def customer_display(self, obj):
        return obj.pp_name or getattr(obj.user, "username", "") or "-"

    @admin.display(description=_("Request"), ordering="pp_price")
    def request_price_display(self, obj):
        return money_html(obj.pp_price)

    @admin.display(description=_("Status"))
    def personal_pay_status(self, obj):
        due = max(0, int(obj.pp_price or 0) - int(obj.pp_receipt_price or 0))
        if not obj.active:
            return badge(_("Inactive"), "neutral")
        if obj.pp_price and obj.pp_receipt_price >= obj.pp_price:
            return badge(_("Paid"), "success")
        if obj.pp_receipt_price:
            return badge(_("Partial"), "warning")
        if due:
            return badge(_("Payment due"), "warning")
        return badge(_("Unpaid"), "neutral")

    @admin.display(description=_("Settlement"), ordering="pp_settle_case")
    def settlement_badge(self, obj):
        return badge(obj.pp_settle_case or "-", "info" if obj.pp_settle_case else "neutral")

    @admin.display(description=_("Receipt proof"))
    def receipt_proof(self, obj):
        if obj.pp_cash_no:
            return badge(_("Cash receipt"), "info")
        if obj.pp_tno or obj.pp_app_no:
            return badge(_("Gateway evidence"), "success")
        if obj.pp_receipt_price:
            return badge(_("Receipt proof needed"), "warning")
        return badge(_("No receipt proof"), "neutral")

    @admin.display(description=_("Linked order"), ordering="order")
    def linked_order(self, obj):
        return obj.order_id or "-"

    @admin.display(description=_("Activation"))
    def active_status(self, obj):
        return badge(_("Active") if obj.active else _("Inactive"), "success" if obj.active else "neutral")

    @admin.display(description=_("Requested at"), ordering="pp_time")
    def requested_at_display(self, obj):
        return datetime_value(obj.pp_time)

    @admin.display(description=_("Receipt"), ordering="pp_receipt_price")
    def personal_pay_receipt(self, obj):
        if obj.pp_cash_no:
            return badge(_("Cash receipt"), "info")
        if obj.pp_receipt_price:
            return badge(format_number(obj.pp_receipt_price), "success")
        return badge(_("Unpaid"), "neutral")

    @admin.display(description=_("Personal pay snapshot"))
    def personal_pay_snapshot(self, obj):
        if not obj:
            return "-"
        due = max(0, int(obj.pp_price or 0) - int(obj.pp_receipt_price or 0))
        if not obj.active:
            state, tone = _("Inactive"), "neutral"
        elif obj.pp_price and obj.pp_receipt_price >= obj.pp_price:
            state, tone = _("Paid"), "success"
        elif obj.pp_receipt_price:
            state, tone = _("Partial payment"), "warning"
        elif due:
            state, tone = _("Payment due"), "warning"
        else:
            state, tone = _("Unpaid"), "neutral"

        return snapshot_panel(
            _("Personal pay snapshot"),
            state,
            tone,
            _("Review request amount, receipt proof, linked order, and customer contact together."),
            (
                (_("Request amount"), format_number(obj.pp_price), compact_text(obj.pp_settle_case, obj.pp_pg)),
                (_("Receipt amount"), format_number(obj.pp_receipt_price), _("Outstanding %(amount)s") % {"amount": format_number(due)}),
                (_("Receipt proof"), compact_text(obj.pp_tno, obj.pp_app_no, obj.pp_cash_no), obj.pp_receipt_time or "-"),
                (_("Customer contact"), obj.pp_name or "-", compact_text(obj.pp_email, obj.pp_hp)),
            ),
        )

    def personal_pay_detail_context(self, pay):
        due = max(0, int(pay.pp_price or 0) - int(pay.pp_receipt_price or 0))
        if not pay.active:
            status, tone = _("Inactive"), "neutral"
        elif pay.pp_price and pay.pp_receipt_price >= pay.pp_price:
            status, tone = _("Paid"), "success"
        elif pay.pp_receipt_price:
            status, tone = _("Partial payment"), "warning"
        elif due:
            status, tone = _("Payment due"), "warning"
        else:
            status, tone = _("Unpaid"), "neutral"

        payment_log_query = pay.order_id or pay.pp_id
        links = [
            {"label": _("Back to personal pay"), "url": "/admin/shop/shoppersonalpay/", "icon": "arrow_back"},
            {"label": _("Settlement report"), "url": "/admin/shop/shoporder/reports/", "icon": "monitoring"},
            {"label": _("Payment logs"), "url": "/admin/shop/shoporderdata/?q=%s" % payment_log_query, "icon": "fact_check"},
        ]
        if pay.order_id:
            links.insert(
                1,
                {"label": _("Linked order"), "url": "/admin/shop/shoporder/%s/change/" % pay.order_id, "icon": "receipt_long"},
            )

        return {
            "pay_id": pay.pp_id,
            "customer": pay.pp_name or getattr(pay.user, "username", "") or "-",
            "email": pay.pp_email or "-",
            "phone": pay.pp_hp or "-",
            "created": datetime_value(pay.pp_time),
            "status": status,
            "status_tone": tone,
            "settle_case": pay.pp_settle_case or "-",
            "pg": pay.pp_pg or "-",
            "request": format_number(pay.pp_price),
            "receipt": format_number(pay.pp_receipt_price),
            "outstanding": format_number(due),
            "cash_no": pay.pp_cash_no or "-",
            "transaction_no": pay.pp_tno or "-",
            "approval_no": pay.pp_app_no or "-",
            "receipt_time": pay.pp_receipt_time or "-",
            "linked_order": pay.order_id or "-",
            "links": links,
            "metrics": [
                {"label": _("Request amount"), "value": format_number(pay.pp_price), "hint": compact_text(pay.pp_settle_case, pay.pp_pg)},
                {"label": _("Receipt amount"), "value": format_number(pay.pp_receipt_price), "hint": _("Outstanding %(amount)s") % {"amount": format_number(due)}},
                {"label": _("Receipt proof"), "value": compact_text(pay.pp_tno, pay.pp_app_no, pay.pp_cash_no), "hint": pay.pp_receipt_time or "-"},
                {"label": _("Linked order"), "value": pay.order_id or "-", "hint": _("Related order record")},
            ],
        }

