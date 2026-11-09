"""고객 세그먼트 (RFM) report: the scoring lives in gnu_jango.shop.customer_segments."""

from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone

from gnu_jango.core.audit import log_admin_export
from gnu_jango.shop import customer_segments
from gnu_jango.shop.admin.bulk import tool_context
from gnu_jango.shop.models import ShopOrder
from gnu_jango.shop.spreadsheet import SpreadsheetError, xlsx_download

PAGE_SIZE = 50
EXPORT_HEADER = ("아이디", "닉네임", "이메일(메일 수신 동의자만)", "최근 주문일", "주문 수", "결제 금액", "R", "F", "M", "세그먼트")


def _window_param(request):
    try:
        window = int(request.GET.get("window") or customer_segments.DEFAULT_WINDOW)
    except ValueError:
        return customer_segments.DEFAULT_WINDOW
    return window if window in customer_segments.WINDOW_CHOICES else customer_segments.DEFAULT_WINDOW


def _export_row(customer):
    return (
        customer.username,
        customer.nickname,
        customer.email if customer.accepts_mail else "",
        customer.last_order,
        customer.orders,
        customer.amount,
        customer.r_score,
        customer.f_score,
        customer.m_score,
        customer.segment_label,
    )


def _export(model_admin, request, customers, window, segment):
    if not model_admin.has_export_permission(request):
        raise PermissionDenied
    rows = [_export_row(customer) for customer in customers]
    try:
        response = xlsx_download(
            f"customer-segments-{timezone.localdate():%Y%m%d}-{window}d{f'-{segment}' if segment else ''}.xlsx",
            [EXPORT_HEADER],
            rows,
            text_columns=(0,),
        )
    except SpreadsheetError as exc:
        messages.error(request, str(exc))
        return HttpResponseRedirect(request.path)
    log_admin_export(request, ShopOrder, len(rows), label="customer segments (RFM)")
    return response


def customer_segments_view(model_admin, request):
    """Members ranked by recency, frequency and monetary value, grouped into named segments."""
    window = _window_param(request)
    report = customer_segments.segment_report(window)
    segment = request.GET.get("segment") or ""
    if segment not in customer_segments.SEGMENT_BY_KEY:
        segment = ""
    customers = [c for c in report.customers if not segment or c.segment == segment]
    customers.sort(key=lambda c: (-c.amount, c.recency_days, c.user_id))
    if request.GET.get("export") == "xlsx":
        return _export(model_admin, request, customers, window, segment)

    filters = {"window": window, **({"segment": segment} if segment else {})}
    page = Paginator(customers, PAGE_SIZE).get_page(request.GET.get("page"))
    context = tool_context(
        model_admin,
        request,
        title="고객 세그먼트 (RFM)",
        subtitle=f"{report.start:%Y-%m-%d} ~ {report.end:%Y-%m-%d}에 결제한 회원을 최근 구매(R)·구매 횟수(F)로 나누고 "
                 "결제 금액(M)은 참고로 보여줍니다. 비회원과 결제 전·취소·반품·전액 환불 주문은 제외하며 AI 없이 계산합니다.",
        parent_url=reverse("admin:shop_shoporder_changelist"),
        parent_label="주문",
        tool_links=[{"url": reverse("admin:shop_shoporder_sales"), "label": "매출현황"}],
        report=report,
        window=window,
        window_choices=customer_segments.WINDOW_CHOICES,
        lapsed_days=customer_segments.LAPSED_DAYS,
        segment=segment,
        segment_label=customer_segments.SEGMENT_BY_KEY[segment].label if segment else "",
        segment_rows=[
            {"row": row, "url": f"{request.path}?{urlencode({'window': window, 'segment': row.segment.key})}"}
            for row in report.rows
        ],
        all_url=f"{request.path}?{urlencode({'window': window})}",
        page_obj=page,
        page_query=urlencode(filters),
        can_export=model_admin.has_export_permission(request),
        export_url=f"{request.path}?{urlencode({**filters, 'export': 'xlsx'})}",
        filtered_count=len(customers),
    )
    return TemplateResponse(request, "admin/shop/tools/customer_segments.html", context)
