"""Shop admin reports (youngcart adm/shop_admin): 보관함 현황 (wishlist.php), 매출현황 (sale1*.php)
and 가격비교사이트 (price.php). Wired into the product and order admins by bulk.py."""

from calendar import monthrange
from datetime import date
from urllib.parse import urlencode

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Q
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from gnu_jango.shop import price_feed, sales_report
from gnu_jango.shop.admin.bulk import product_tool_links, require_perms, tool_context
from gnu_jango.shop.models import ShopProduct, ShopWishlist
from gnu_jango.shop.spreadsheet import csv_download

WISHLIST_LIMIT = 200
FEED_PREVIEW_LINES = 20


def _date_param(request, name):
    """A date from the query string; None when it is missing or not a real date (2024-13-45)."""
    try:
        return parse_date(str(request.GET.get(name) or "").strip()[:10]) if request.GET.get(name) else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------- 보관함 현황


def wishlist_report_view(model_admin, request):
    """youngcart wishlist.php: products ranked by how many wishlists hold them."""
    require_perms(request, "view_shopwishlist")
    start = _date_param(request, "date_from")
    end = _date_param(request, "date_to")
    query = str(request.GET.get("q") or "").strip()[:120]
    entries = ShopWishlist.objects.all()
    if start:
        entries = entries.filter(wi_time__date__gte=start)
    if end:
        entries = entries.filter(wi_time__date__lte=end)
    if query:
        entries = entries.filter(Q(it_id__icontains=query) | Q(product__it_name__icontains=query))
    grouped = list(
        entries.values("it_id")
        .annotate(count=Count("pk"), members=Count("user", distinct=True), last=Max("wi_time"))
        .order_by("-count", "it_id")[:WISHLIST_LIMIT]
    )
    products = ShopProduct.objects.only("it_id", "it_name", "it_price", "it_stock_qty", "it_use", "it_soldout").in_bulk(
        [row["it_id"] for row in grouped]
    )
    rows = []
    for rank, row in enumerate(grouped, 1):
        product = products.get(row["it_id"])
        rows.append(
            {
                "rank": rank,
                "it_id": row["it_id"],
                "name": product.it_name if product else "(삭제된 상품)",
                "price": f"{product.it_price:,}" if product else "-",
                "stock": product.it_stock_qty if product else "-",
                "on_sale": bool(product and product.it_use == "1" and product.it_soldout != "1"),
                "count": row["count"],
                "members": row["members"],
                "guests": row["count"] - row["members"],
                "last": timezone.localtime(row["last"]).strftime("%Y-%m-%d %H:%M") if row["last"] else "-",
                "change_url": reverse("admin:shop_shopproduct_change", args=[product.pk]) if product else "",
                "public_url": f"/shop/{product.it_id}" if product else "",
            }
        )
    if request.GET.get("export") == "csv":
        return csv_download(
            "shop-wishlist-report.csv",
            [["순위", "상품코드", "상품명", "판매가", "재고", "보관 수", "회원 수", "비회원 수", "최근 보관"]],
            [[row["rank"], row["it_id"], row["name"], row["price"], row["stock"], row["count"], row["members"], row["guests"], row["last"]] for row in rows],
        )
    filters = {"date_from": start.isoformat() if start else "", "date_to": end.isoformat() if end else "", "q": query}
    context = tool_context(
        model_admin,
        request,
        title="보관함 현황",
        subtitle="고객이 보관함(위시리스트)에 많이 담은 상품 순위입니다. 기간은 보관한 날짜 기준입니다.",
        parent_url=reverse("admin:shop_shopproduct_changelist"),
        parent_label="상품",
        tool_links=product_tool_links(request),
        filters=filters,
        rows=rows,
        total=f"{entries.count():,}",
        export_query=urlencode({**{key: value for key, value in filters.items() if value}, "export": "csv"}),
        limit=WISHLIST_LIMIT,
    )
    return TemplateResponse(request, "admin/shop/tools/wishlist_report.html", context)


# ---------------------------------------------------------------------------- 매출현황


def _drill_url(path, period, row):
    """The next finer table for a row: a year → its months, a month → its days, a day → its orders."""
    value = row.get("date")
    if not value:
        return ""
    if period == sales_report.PERIOD_DAY:
        params = {"period": sales_report.PERIOD_TODAY, "date_from": value.isoformat()}
    elif period == sales_report.PERIOD_MONTH:
        last = monthrange(value.year, value.month)[1]
        params = {"period": sales_report.PERIOD_DAY, "date_from": value.replace(day=1).isoformat(), "date_to": value.replace(day=last).isoformat()}
    elif period == sales_report.PERIOD_YEAR:
        params = {"period": sales_report.PERIOD_MONTH, "date_from": date(value.year, 1, 1).isoformat(), "date_to": date(value.year, 12, 31).isoformat()}
    else:
        return ""
    return f"{path}?{urlencode(params)}"


def sales_view(model_admin, request):
    """youngcart sale1today / sale1date / sale1month / sale1year with the payment-method split."""
    period = request.GET.get("period")
    if period not in dict(sales_report.PERIODS):
        period = sales_report.PERIOD_DAY
    today = timezone.localdate()
    start, end, cut = sales_report.clamp_range(period, _date_param(request, "date_from"), _date_param(request, "date_to"), today)
    table = sales_report.sales_table(period, start, end)
    columns = [label for _key, label in table["columns"]]
    if request.GET.get("export") == "csv":
        first = "주문번호" if period == sales_report.PERIOD_TODAY else "기간"
        header = [first, "주문수", "주문합계", "쿠폰", *columns, "포인트", "입금합계", "주문취소", "환불", "미수금"]

        def line(row):
            return [
                row["label"], row["order_count"], row["order_price"], row["coupon"],
                *(cell["amount"] for cell in row["method_cells"]),
                row["point"], row["receipt"], row["cancel"], row["refund"], row["misu"],
            ]

        return csv_download(
            f"shop-sales-{period}-{start.isoformat()}-{end.isoformat()}.csv",
            [header],
            [*(line(row) for row in table["rows"]), line(table["total"])],
        )
    for row in table["rows"]:
        row["drill_url"] = _drill_url(request.path, period, row)
        if period == sales_report.PERIOD_TODAY:
            row["order_url"] = reverse("admin:shop_shoporder_change", args=[row["od_id"]])
    if cut:
        messages.info(request, f"일별 매출은 {sales_report.MAX_DAY_SPAN}일까지 보여 줍니다. 시작일을 {start.isoformat()}(으)로 맞췄습니다.")
    filters = {"period": period, "date_from": start.isoformat(), "date_to": end.isoformat()}
    context = tool_context(
        model_admin,
        request,
        title="매출현황",
        subtitle="일일·일별·월별·연도별 주문 합계와 결제수단별 입금액입니다. 입금액은 환불을 뺀 금액입니다.",
        parent_url=reverse("admin:shop_shoporder_changelist"),
        parent_label="주문",
        tool_links=[
            {"url": reverse("admin:shop_shoporder_reports"), "label": "정산 리포트"},
            {"url": reverse("admin:shop_shoporder_sales_rank"), "label": "상품 판매 순위"},
        ],
        periods=sales_report.PERIODS,
        filters=filters,
        table=table,
        method_labels=columns,
        is_today=period == sales_report.PERIOD_TODAY,
        today_limit=sales_report.MAX_TODAY_ROWS,
        export_query=urlencode({**filters, "export": "csv"}),
    )
    return TemplateResponse(request, "admin/shop/tools/sales.html", context)


# ---------------------------------------------------------------------------- 가격비교사이트


def price_compare_view(model_admin, request):
    """youngcart price.php: where the comparison-site feed is and whether it is served."""
    require_perms(request, "view_shopproduct")
    can_change = request.user.has_perm("shop.change_shopproduct")
    if request.method == "POST":
        if not can_change:
            raise PermissionDenied
        action = request.POST.get("action")
        if action in {"enable", "disable"}:
            price_feed.set_feed_enabled(action == "enable")
            price_feed.clear_feed_cache(request)
            messages.success(request, "가격비교 상품목록을 공개했습니다." if action == "enable" else "가격비교 상품목록 공개를 껐습니다.")
        elif action == "refresh":
            price_feed.clear_feed_cache(request)
            messages.success(request, "상품목록 캐시를 비웠습니다. 다음 요청 때 새로 만듭니다.")
        return HttpResponseRedirect(request.path)
    base = price_feed.site_base(request)
    feed_path = reverse("api_v1:shop-price-naver")
    preview = price_feed.feed_text(request).splitlines()
    context = tool_context(
        model_admin,
        request,
        title="가격비교사이트",
        subtitle="네이버쇼핑 등 가격비교사이트에 알려 줄 상품목록(EP) 주소입니다.",
        parent_url=reverse("admin:shop_shopproduct_changelist"),
        parent_label="상품",
        tool_links=product_tool_links(request),
        enabled=price_feed.feed_enabled(),
        can_change=can_change,
        feed_url=f"{base}{feed_path}",
        legacy_url=f"{base}/shop/price/naver.php",
        product_count=f"{max(0, len(preview) - 1):,}",
        preview_header=preview[0].split("\t") if preview else [],
        preview_rows=[line.split("\t") for line in preview[1 : FEED_PREVIEW_LINES + 1]],
        cache_minutes=price_feed.CACHE_SECONDS // 60,
    )
    return TemplateResponse(request, "admin/shop/tools/price_compare.html", context)
