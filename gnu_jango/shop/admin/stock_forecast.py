"""재고 소진 예측 admin page: the rules live in gnu_jango.shop.stock_forecast."""

from urllib.parse import urlencode

from django.core.paginator import Paginator
from django.template.response import TemplateResponse
from django.utils import timezone

from gnu_jango.shop import stock_forecast
from gnu_jango.shop.admin.bulk import _product_parent, product_tool_links, require_perms, tool_context

PAGE_SIZE = 50


def stock_forecast_view(model_admin, request):
    require_perms(request, "view_shopproduct")
    settings = stock_forecast.parse_settings(request.GET)
    forecasts = stock_forecast.forecast_all(timezone.localdate(), settings)
    counts = stock_forecast.status_counts(forecasts)
    status = request.GET.get("status") if request.GET.get("status") in counts else ""
    shown = [forecast for forecast in forecasts if not status or forecast.status == status]
    query = {"window": settings.window, "lead": settings.lead_days, "cover": settings.cover_days}
    parent_url, parent_label = _product_parent()
    context = tool_context(
        model_admin,
        request,
        title="재고 소진 예측",
        subtitle=f"최근 {settings.window}일(어제까지) 판매량으로 상품별 소진 시점과 발주 수량을 계산합니다. 이 결과는 AI 없이 계산합니다.",
        parent_url=parent_url,
        parent_label=parent_label,
        tool_links=product_tool_links(request),
        settings=settings,
        windows=stock_forecast.WINDOWS,
        status=status,
        status_counts=[
            {
                "label": label,
                "count": count,
                "badge": stock_forecast.STATUS_BADGES[label],
                "query": urlencode({**query, "status": label}),
            }
            for label, count in counts.items()
        ],
        page_obj=Paginator(shown, PAGE_SIZE).get_page(request.GET.get("page")),
        page_query=urlencode({**query, **({"status": status} if status else {})}),
        recent_days=stock_forecast.RECENT_DAYS,
    )
    return TemplateResponse(request, "admin/shop/tools/stock_forecast.html", context)
