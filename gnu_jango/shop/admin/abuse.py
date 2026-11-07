"""The 이상 활동 점검 admin report: a thin view over gnu_jango.shop.abuse_signals."""

from django.template.response import TemplateResponse
from django.urls import reverse

from gnu_jango.shop import abuse_signals
from gnu_jango.shop.admin.bulk import tool_context


def abuse_signals_view(model_admin, request):
    report = abuse_signals.build_report(request.GET.get("days"))
    context = tool_context(
        model_admin,
        request,
        title="이상 활동 점검",
        subtitle="후기 조작과 쿠폰 악용이 의심되는 기록을 정해진 규칙으로 찾습니다. 자동으로 처리하지 않으며, "
                 "후기 숨김은 후기 관리의 선택 동작을 쓰십시오.",
        parent_url=reverse("admin:shop_shoporder_changelist"),
        parent_label="주문",
        tool_links=[
            {"url": reverse("admin:shop_shopreview_changelist"), "label": "상품 후기"},
            {"url": reverse("admin:shop_shoporder_sales_anomalies"), "label": "매출 이상 징후"},
        ],
        report=report,
        window_choices=abuse_signals.WINDOW_CHOICES,
    )
    return TemplateResponse(request, "admin/shop/tools/abuse_signals.html", context)
