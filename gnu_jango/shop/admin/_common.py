import csv
from datetime import timedelta

from django.contrib import admin
from django.db.models import Count, ExpressionWrapper, F, IntegerField, Q, Sum
from django.http import HttpResponse
from django.template.response import TemplateResponse
from django.urls import path
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import DropdownFilter

from gnu_jango.shop.models import (
    ShopAddress,
    ShopCategory,
    ShopCoupon,
    ShopCouponLog,
    ShopCouponZone,
    ShopEvent,
    ShopEventItem,
    ShopOrder,
    ShopOrderData,
    ShopOrderItem,
    ShopPersonalPay,
    ShopProduct,
    ShopQA,
    ShopReview,
    ShopStockNotification,
    ShopStockNotificationSendLog,
    ShopShippingCost,
    ShopShippingPolicy,
    ShopWishlist,
)
from gnu_jango.utils.admin_display import (
    badge,
    compact_text,
    format_number,
    money_html,
    money_sum,
    snapshot_panel,
)


def report_date_range(request):
    start = parse_date(str(request.GET.get("date_from") or request.GET.get("start") or ""))
    end = parse_date(str(request.GET.get("date_to") or request.GET.get("end") or ""))
    return start, end


def filter_datetime_range(queryset, field, start, end):
    if start:
        queryset = queryset.filter(**{f"{field}__date__gte": start})
    if end:
        queryset = queryset.filter(**{f"{field}__date__lte": end})
    return queryset


def excerpt_text(value, limit=160):
    text = " ".join(str(value or "").split())
    if not text:
        return "-"
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def grouped_money(queryset, group_field, money_field, limit=12):
    rows = (
        queryset.values(group_field)
        .annotate(count=Count("pk"), amount=Sum(money_field))
        .order_by("-amount", group_field)[:limit]
    )
    return [
        {
            "key": row[group_field] or _("Unspecified"),
            "count": row["count"],
            "count_display": format_number(row["count"]),
            "amount": row["amount"] or 0,
            "amount_display": format_number(row["amount"]),
        }
        for row in rows
    ]


def sales_series(queryset, period):
    from django.db.models.functions import TruncDate, TruncMonth

    trunc = TruncMonth("od_datetime") if period == "month" else TruncDate("od_datetime")
    rows = list(
        queryset.annotate(period_value=trunc)
        .values("period_value")
        .annotate(
            order_count=Count("pk"),
            receipt_price=Sum("od_receipt_price"),
            cancel_price=Sum("od_cancel_price"),
            coupon_price=Sum("od_coupon"),
            tax_base=Sum("od_tax_mny"),
            vat_amount=Sum("od_vat_mny"),
            exempt_amount=Sum("od_free_mny"),
        )
        .order_by("period_value")
    )
    max_receipt = max([row["receipt_price"] or 0 for row in rows] or [0])
    result = []
    for row in rows:
        period_value = row["period_value"]
        label = ""
        if period_value:
            label = period_value.strftime("%Y-%m") if period == "month" else period_value.strftime("%Y-%m-%d")
        receipt_price = row["receipt_price"] or 0
        result.append(
            {
                "period": label,
                "order_count": row["order_count"],
                "order_count_display": format_number(row["order_count"]),
                "receipt_price": receipt_price,
                "receipt_price_display": format_number(receipt_price),
                "cancel_price_display": format_number(row["cancel_price"]),
                "coupon_price_display": format_number(row["coupon_price"]),
                "tax_base": row["tax_base"] or 0,
                "tax_base_display": format_number(row["tax_base"]),
                "vat_amount": row["vat_amount"] or 0,
                "vat_amount_display": format_number(row["vat_amount"]),
                "exempt_amount": row["exempt_amount"] or 0,
                "exempt_amount_display": format_number(row["exempt_amount"]),
                "share": round((receipt_price / max_receipt) * 100) if max_receipt else 0,
            }
        )
    return result


def csv_cell(value):
    if value is None:
        return ""
    text = str(value)
    if text[:1] in ("=", "+", "-", "@"):
        return "'" + text
    return text


def datetime_value(value):
    if not value:
        return ""
    try:
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value.strftime("%Y-%m-%d %H:%M:%S")


def date_value(value):
    return value.strftime("%Y-%m-%d") if value else "-"


def flag_enabled(value):
    return str(value or "").strip().lower() in {"1", "y", "yes", "true", "on"}


def csv_response(filename, headers, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")
    writer = csv.writer(response)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([csv_cell(value) for value in row])
    return response


def raw_preview(value, limit=2200):
    return format_html('<pre class="g5-admin-raw-log">{}</pre>', excerpt_text(value, limit))


def report_row(label, queryset, amount_field):
    count = queryset.count()
    amount = money_sum(queryset, amount_field)
    return {
        "key": label,
        "count": count,
        "count_display": format_number(count),
        "amount": amount,
        "amount_display": format_number(amount),
    }


def flow_step(label, value, hint, url, tone, icon):
    return {
        "label": label,
        "value": format_number(value),
        "hint": hint,
        "url": url,
        "tone": tone,
        "icon": icon,
    }


def brief_order_rows(queryset):
    return [
        {
            "id": order.od_id,
            "name": order.od_name or "-",
            "status": order.od_status or "-",
            "settle_case": order.od_settle_case or "-",
            "pg": order.od_pg or "-",
            "receipt": format_number(order.od_receipt_price),
            "misu": format_number(order.od_misu),
            "time": datetime_value(order.od_datetime),
        }
        for order in queryset
    ]


def brief_raw_log_rows(queryset):
    return [
        {
            "id": log.log_id,
            "order_id": log.od_id or "-",
            "cart_id": log.cart_id or "-",
            "pg": log.dt_pg or "-",
            "time": datetime_value(log.dt_time),
        }
        for log in queryset
    ]


def brief_personal_pay_rows(queryset):
    return [
        {
            "id": pay.pp_id,
            "name": pay.pp_name or "-",
            "settle_case": pay.pp_settle_case or "-",
            "pg": pay.pp_pg or "-",
            "price": format_number(pay.pp_price),
            "receipt": format_number(pay.pp_receipt_price),
            "cash_no": pay.pp_cash_no or "-",
            "time": datetime_value(pay.pp_time),
        }
        for pay in queryset
    ]


def order_line_sales_expression():
    return ExpressionWrapper((F("ct_price") + F("io_price")) * F("ct_qty"), output_field=IntegerField())


def order_line_point_expression():
    return ExpressionWrapper(F("ct_point") * F("ct_qty"), output_field=IntegerField())


class DistinctValueDropdownFilter(DropdownFilter):
    field_name = ""
    empty_label = _("Unspecified")

    #: Cap on distinct values fetched, to avoid a full-table DISTINCT scan on
    #: large tables every time the changelist renders.
    max_values = 100

    def lookups(self, request, model_admin):
        values = (
            model_admin.model.objects.exclude(**{self.field_name: ""})
            .values_list(self.field_name, flat=True)
            .distinct()
            .order_by(self.field_name)[: self.max_values]
        )
        return [(value, value or self.empty_label) for value in values]

    def queryset(self, request, queryset):
        value = self.value()
        if value:
            return queryset.filter(**{self.field_name: value})
        return queryset


class DatePeriodFilter(DropdownFilter):
    title = _("Date")
    parameter_name = "date_period"
    field_name = ""

    def lookups(self, request, model_admin):
        return (
            ("today", _("Today")),
            ("7d", _("Last 7 days")),
            ("month", _("This month")),
            ("year", _("This year")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        today = timezone.localdate()
        if value == "today":
            return queryset.filter(**{f"{self.field_name}__date": today})
        if value == "7d":
            return queryset.filter(**{f"{self.field_name}__date__gte": today - timedelta(days=6)})
        if value == "month":
            return queryset.filter(**{f"{self.field_name}__date__year": today.year, f"{self.field_name}__date__month": today.month})
        if value == "year":
            return queryset.filter(**{f"{self.field_name}__date__year": today.year})
        return queryset


class OrderStatusFilter(DistinctValueDropdownFilter):
    title = _("Order status")
    parameter_name = "od_status"
    field_name = "od_status"


class SettleCaseFilter(DistinctValueDropdownFilter):
    title = _("Settle case")
    parameter_name = "od_settle_case"
    field_name = "od_settle_case"


class PaymentGatewayFilter(DistinctValueDropdownFilter):
    title = _("Payment gateway")
    parameter_name = "od_pg"
    field_name = "od_pg"


class PaymentLogGatewayFilter(DistinctValueDropdownFilter):
    title = _("Gateway")
    parameter_name = "dt_pg"
    field_name = "dt_pg"


class PaymentLogDateFilter(DatePeriodFilter):
    title = _("Imported at")
    parameter_name = "payment_log_date"
    field_name = "dt_time"


class OrderDateFilter(DatePeriodFilter):
    title = _("Order date")
    parameter_name = "order_date"
    field_name = "od_datetime"


class ReceiptStateFilter(DropdownFilter):
    title = _("Receipt state")
    parameter_name = "receipt_state"

    def lookups(self, request, model_admin):
        return (
            ("paid", _("Paid")),
            ("outstanding", _("Outstanding")),
            ("cancelled", _("Cancelled")),
            ("cash", _("Cash receipt")),
            ("requested", _("Receipt requests")),
            ("proof_needed", _("Receipt proof needed")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "paid":
            return queryset.filter(od_receipt_price__gt=0, od_misu__lte=0)
        if value == "outstanding":
            return queryset.filter(od_misu__gt=0)
        if value == "cancelled":
            return queryset.filter(od_cancel_price__gt=0)
        if value == "cash":
            return queryset.exclude(od_cash_no="")
        if value == "requested":
            return queryset.filter(Q(od_tax_invoice_request=True) | Q(od_cash_request=True))
        if value == "proof_needed":
            return queryset.filter(od_receipt_price__gt=0, od_cash_no="", od_tno="", od_app_no="")
        return queryset


class ShippingStateFilter(DropdownFilter):
    title = _("Shipping state")
    parameter_name = "shipping_state"

    def lookups(self, request, model_admin):
        return (
            ("waiting_invoice", _("Waiting invoice")),
            ("carrier_only", _("Carrier only")),
            ("invoiced", _("Invoiced")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "waiting_invoice":
            return queryset.filter(od_receipt_price__gt=0, od_cancel_price__lte=0, od_invoice="")
        if value == "carrier_only":
            return queryset.exclude(od_delivery_company="").filter(od_invoice="")
        if value == "invoiced":
            return queryset.exclude(od_invoice="")
        return queryset


class PersonalPayStateFilter(DropdownFilter):
    title = _("Personal pay state")
    parameter_name = "personal_pay_state"

    def lookups(self, request, model_admin):
        return (
            ("due", _("Payment due")),
            ("partial", _("Partial payment")),
            ("paid", _("Paid")),
            ("inactive", _("Inactive")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "due":
            return queryset.filter(active=True, pp_price__gt=0, pp_receipt_price__lte=0)
        if value == "partial":
            return queryset.filter(active=True, pp_receipt_price__gt=0, pp_receipt_price__lt=F("pp_price"))
        if value == "paid":
            return queryset.filter(active=True, pp_price__gt=0, pp_receipt_price__gte=F("pp_price"))
        if value == "inactive":
            return queryset.filter(active=False)
        return queryset


class PersonalPaySettleCaseFilter(DistinctValueDropdownFilter):
    title = _("Settle case")
    parameter_name = "pp_settle_case"
    field_name = "pp_settle_case"


class PersonalPayActiveFilter(DropdownFilter):
    title = _("Activation")
    parameter_name = "active_state"

    def lookups(self, request, model_admin):
        return (
            ("active", _("Active")),
            ("inactive", _("Inactive")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "active":
            return queryset.filter(active=True)
        if value == "inactive":
            return queryset.filter(active=False)
        return queryset


class PersonalPayDateFilter(DatePeriodFilter):
    title = _("Request date")
    parameter_name = "personal_pay_date"
    field_name = "pp_time"



class ShopOrderItemInline(TabularInline):
    model = ShopOrderItem
    extra = 0
    tab = True
    show_count = True
    readonly_fields = ("ct_notax", "line_total")
    fields = ("ct_id", "it_id", "it_name", "ct_status", "ct_price", "ct_qty", "ct_notax", "line_total", "stock_adjusted")

    @admin.display(description=_("Line total"))
    def line_total(self, obj):
        unit_price = obj.io_price if obj.io_type == 1 else obj.ct_price + obj.io_price
        return money_html(max(0, unit_price) * obj.ct_qty)


class ShopOrderDataInline(TabularInline):
    model = ShopOrderData
    extra = 0
    tab = True
    show_count = True
    readonly_fields = ("log_id", "dt_pg", "cart_id", "dt_time", "dt_data_excerpt")
    fields = ("log_id", "dt_pg", "cart_id", "dt_time", "dt_data_excerpt")
    can_delete = False

    @admin.display(description=_("Raw data"))
    def dt_data_excerpt(self, obj):
        text = obj.dt_data or ""
        return text[:180] + ("..." if len(text) > 180 else "")

