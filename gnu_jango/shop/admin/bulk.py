"""Bulk shop admin tools (youngcart adm/shop_admin): 상품 엑셀 일괄등록 (itemexcel), 재고 일괄수정
(itemstocklist), 옵션 재고 (optionstocklist), 송장 일괄등록 (orderdelivery), 후기 일괄 승인·숨김
(itemuselist), 개인결제 복사 (personalpaycopy) and 미수금 개인결제 (personalpayform from an order).

The views hang off the product and order admins (``product_tool_urls`` / ``order_tool_urls``) and
check the model permission each one needs; the domain work lives in shop/product_import.py,
stock_bulk.py and delivery_import.py.
"""

import re
from urllib.parse import quote, unquote, urlencode

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse

from gnu_jango.shop import delivery_import, product_import
from gnu_jango.shop.models import ShopCategory, ShopOrder, ShopPersonalPay, ShopProduct, ShopReview
from gnu_jango.shop.product_counters import recount_product_reviews
from gnu_jango.shop.shipping import current_shipping_policy
from gnu_jango.shop.spreadsheet import MAX_UPLOAD_BYTES, SpreadsheetError, csv_download, xlsx_download
from gnu_jango.shop.stock_bulk import apply_option_rows, apply_product_rows, option_label, option_rows

PAGE_SIZE = 50
OPTION_PAGE_SIZE = 100
OPTION_SCAN_LIMIT = 3000
MAX_QUERY = 120


def require_perms(request, *codenames):
    if not all(request.user.has_perm(f"shop.{codename}") for codename in codenames):
        raise PermissionDenied


def tool_context(model_admin, request, *, title, subtitle, parent_url="", parent_label="", **extra):
    request.current_app = model_admin.admin_site.name
    return {
        **model_admin.admin_site.each_context(request),
        "opts": model_admin.model._meta,
        "title": title,
        "subtitle": subtitle,
        "parent_url": parent_url,
        "parent_label": parent_label,
        "report_path": request.path,
        **extra,
    }


def _product_parent():
    return reverse("admin:shop_shopproduct_changelist"), "상품"


def _order_parent():
    return reverse("admin:shop_shoporder_changelist"), "주문"


def product_tool_links(request):
    links = [
        ("view_shopproduct", "admin:shop_shopproduct_stock_list", "재고 일괄수정"),
        ("view_shopproduct", "admin:shop_shopproduct_option_stock_list", "옵션 재고"),
        ("add_shopproduct", "admin:shop_shopproduct_bulk_upload", "상품 일괄등록"),
        ("view_shopproduct", "admin:shop_shopproduct_stock_adjustments", "재고 이력"),
    ]
    return [
        {"url": reverse(name), "label": label}
        for codename, name, label in links
        if request.user.has_perm(f"shop.{codename}") and name != request.resolver_match.view_name
    ]


def _template_download(request, basename, header_rows, rows, *, text_columns):
    """The upload template as .xlsx (``?format=xlsx``) or CSV; a server without openpyxl falls
    back to the page with the reason."""
    if request.GET.get("format") != "xlsx":
        return csv_download(f"{basename}.csv", header_rows, rows)
    try:
        return xlsx_download(f"{basename}.xlsx", header_rows, rows, text_columns=text_columns)
    except SpreadsheetError as exc:
        messages.error(request, str(exc))
        return HttpResponseRedirect(request.path)


def _report_rows(report, columns):
    return [
        {
            "line": row.line,
            "ok": row.ok,
            "saved": row.saved,
            "errors": row.errors,
            "notes": row.notes,
            "cells": [getattr(row, column) for column in columns],
        }
        for row in report.rows
    ]


# ---------------------------------------------------------------------------- 상품 엑셀 일괄등록


def product_upload_view(model_admin, request):
    require_perms(request, "add_shopproduct")
    can_update = request.user.has_perm("shop.change_shopproduct")
    if request.GET.get("download") == "template":
        headers, rows = product_import.template_rows()
        return _template_download(
            request, "shop-product-upload-template", headers, rows, text_columns=product_import.TEXT_COLUMNS
        )
    mode = request.POST.get("mode") if request.POST.get("mode") in {product_import.MODE_CREATE, product_import.MODE_UPDATE} else product_import.MODE_CREATE
    report = None
    error = ""
    if request.method == "POST":
        if mode == product_import.MODE_UPDATE and not can_update:
            raise PermissionDenied
        try:
            report = product_import.parse_products(request.FILES.get("file"), mode=mode)
        except SpreadsheetError as exc:
            error = str(exc)
        if report is not None and request.POST.get("step") == "apply":

            def logged(product, item):
                if item.action == "update":
                    model_admin.log_change(request, product, "상품 엑셀 일괄수정")
                else:
                    model_admin.log_addition(request, product, "상품 엑셀 일괄등록")

            product_import.apply_products(report, actor=request.user, on_saved=logged)
            if report.saved_count:
                messages.success(request, f"상품 {report.saved_count}개를 저장했습니다.")
            if report.error_count:
                messages.warning(request, f"{report.error_count}개 행은 저장하지 않았습니다. 아래 결과를 확인하세요.")
    parent_url, parent_label = _product_parent()
    context = tool_context(
        model_admin,
        request,
        title="상품 일괄등록",
        subtitle="영카트 상품 일괄등록 양식의 엑셀(.xlsx) 또는 CSV 파일로 상품을 한 번에 등록하거나 고칩니다.",
        parent_url=parent_url,
        parent_label=parent_label,
        tool_links=product_tool_links(request),
        report=report,
        report_columns=("상품코드", "상품명", "처리"),
        report_rows=_report_rows(report, ("it_id", "it_name", "action_label")) if report else [],
        error=error,
        mode=mode,
        can_update=can_update,
        max_rows=f"{product_import.MAX_ROWS:,}",
        max_mb=MAX_UPLOAD_BYTES // (1024 * 1024),
    )
    return TemplateResponse(request, "admin/shop/tools/product_upload.html", context)


# ---------------------------------------------------------------------------- 재고 일괄수정


def _category_choices():
    choices = []
    for category in ShopCategory.objects.order_by("ca_id").only("ca_id", "ca_name"):
        depth = max(0, len(category.ca_id) // 2 - 1)
        choices.append({"ca_id": category.ca_id, "ca_name": category.ca_name, "indent": "　" * depth})
    return choices


def _stock_filters(request, *, options=False):
    query = str(request.GET.get("q") or "").strip()[:MAX_QUERY]
    category = str(request.GET.get("ca") or "").strip()[:20]
    low_text = str(request.GET.get("low") or "").strip()
    low = int(low_text) if re.fullmatch(r"[0-9]{1,10}", low_text) else None
    filters = {"q": query, "ca": category, "low": "" if low is None else low}
    if options:
        filters["below_noti"] = request.GET.get("below_noti") == "1"
    params = {key: value for key, value in filters.items() if value not in ("", None, False)}
    if options and filters["below_noti"]:
        params["below_noti"] = "1"
    return filters, low, urlencode(params)


def _redirect_back(request):
    query = request.GET.urlencode()
    return HttpResponseRedirect(f"{request.path}?{query}" if query else request.path)


def _report_bulk_result(request, result, noun):
    if result.changed:
        messages.success(request, f"{noun} {len(result.changed)}건을 저장했습니다.")
    elif not result.errors:
        messages.info(request, "바뀐 내용이 없습니다.")
    for label, message in result.errors[:20]:
        messages.warning(request, f"{label}: {message}")
    if len(result.errors) > 20:
        messages.warning(request, f"그 밖에 {len(result.errors) - 20}건을 저장하지 못했습니다.")


def _posted_rows(request, fields, limit):
    try:
        count = min(int(request.POST.get("row_count") or 0), limit)
    except (TypeError, ValueError):
        count = 0
    rows = []
    for index in range(count):
        row = {name: request.POST.get(f"{name}_{index}") for name in fields}
        if row.get("it_id"):
            rows.append(row)
    return rows


def stock_list_view(model_admin, request):
    require_perms(request, "view_shopproduct")
    can_change = request.user.has_perm("shop.change_shopproduct")
    if request.method == "POST":
        if not can_change:
            raise PermissionDenied
        posted = _posted_rows(request, ("it_id", "stock", "stock_was", "use", "soldout", "sms"), PAGE_SIZE)
        rows = [
            {
                "it_id": row["it_id"],
                "stock": row["stock"],
                "stock_was": row["stock_was"],
                "it_use": bool(row["use"]),
                "it_soldout": bool(row["soldout"]),
                "it_stock_sms": bool(row["sms"]),
            }
            for row in posted
        ]
        result = apply_product_rows(rows, actor=request.user, reason=request.POST.get("reason"))
        for product in ShopProduct.objects.filter(pk__in=result.changed).only("pk", "it_name"):
            model_admin.log_change(request, product, "재고 일괄수정")
        _report_bulk_result(request, result, "상품")
        return _redirect_back(request)

    filters, low, page_query = _stock_filters(request)
    products = ShopProduct.objects.select_related("category").only(
        "it_id", "it_name", "it_stock_qty", "it_use", "it_soldout", "it_stock_sms", "options",
        "category__ca_name", "category__ca_id",
    )
    if filters["q"]:
        products = products.filter(Q(it_id__icontains=filters["q"]) | Q(it_name__icontains=filters["q"]))
    if filters["ca"]:
        products = products.filter(category__ca_id__startswith=filters["ca"])
    if low is not None:
        products = products.filter(it_stock_qty__lte=low)
    products = products.order_by("it_stock_qty", "it_id") if low is not None else products.order_by("-created_at", "it_id")
    page_obj = Paginator(products, PAGE_SIZE).get_page(request.GET.get("page"))
    history = reverse("admin:shop_shopproduct_stock_adjustments")
    rows = [
        {
            "product": product,
            "option_count": len(option_rows(product)),
            "category_name": product.category.ca_name if product.category_id and product.category else "",
            "history_url": f"{history}?{urlencode({'it_id': product.it_id})}",
            "change_url": reverse("admin:shop_shopproduct_change", args=[product.pk]),
        }
        for product in page_obj
    ]
    parent_url, parent_label = _product_parent()
    post_query = request.GET.urlencode()
    context = tool_context(
        model_admin,
        request,
        title="재고 일괄수정",
        subtitle="상품 재고, 판매·품절·재입고 알림 여부를 목록에서 한 번에 고칩니다.",
        parent_url=parent_url,
        parent_label=parent_label,
        tool_links=product_tool_links(request),
        filters=filters,
        categories=_category_choices(),
        page_obj=page_obj,
        page_query=page_query,
        post_url=f"{request.path}?{post_query}" if post_query else request.path,
        rows=rows,
        can_change=can_change,
    )
    return TemplateResponse(request, "admin/shop/tools/stock_list.html", context)


def option_stock_list_view(model_admin, request):
    require_perms(request, "view_shopproduct")
    can_change = request.user.has_perm("shop.change_shopproduct")
    if request.method == "POST":
        if not can_change:
            raise PermissionDenied
        rows = _posted_rows(request, ("it_id", "io_type", "io_key", "stock", "stock_was", "noti", "use"), OPTION_PAGE_SIZE)
        # the option id travels percent-encoded: a choice id holds chr(30) between its values
        rows = [{**row, "io_id": unquote(str(row.get("io_key") or ""))} for row in rows]
        result = apply_option_rows(rows, actor=request.user, reason=request.POST.get("reason") or "옵션 재고 일괄수정")
        changed_products = {label.split(" ", 1)[0] for label in result.changed}
        for product in ShopProduct.objects.filter(pk__in=changed_products).only("pk", "it_name"):
            model_admin.log_change(request, product, "옵션 재고 일괄수정")
        _report_bulk_result(request, result, "옵션")
        return _redirect_back(request)

    filters, low, page_query = _stock_filters(request, options=True)
    products = ShopProduct.objects.exclude(options=[]).only("it_id", "it_name", "options", "category_id").order_by("it_id")
    if filters["ca"]:
        products = products.filter(category__ca_id__startswith=filters["ca"])
    query = filters["q"].lower()
    rows = []
    scanned = 0
    for product in products.iterator(chunk_size=200):
        scanned += 1
        if scanned > OPTION_SCAN_LIMIT:
            break
        product_match = not query or query in product.it_id.lower() or query in product.it_name.lower()
        for option_type, option_id, record in option_rows(product):
            if not product_match and query not in option_id.lower():
                continue
            stock = _safe_int(record.get("io_stock_qty"))
            noti = _safe_int(record.get("io_noti_qty"))
            is_low = (noti > 0 and stock <= noti)
            if low is not None and stock > low:
                continue
            if filters["below_noti"] and not is_low:
                continue
            rows.append(
                {
                    "it_id": product.it_id,
                    "it_name": product.it_name,
                    "io_type": option_type,
                    "io_key": quote(option_id, safe=""),
                    "label": option_label(option_id),
                    "type_label": "추가옵션" if option_type else "선택옵션",
                    "stock": stock,
                    "noti": noti,
                    "use": _safe_int(record.get("io_use", 1), 1) != 0,
                    "low": is_low or stock <= 0,
                    "change_url": reverse("admin:shop_shopproduct_change", args=[product.pk]),
                }
            )
    page_obj = Paginator(rows, OPTION_PAGE_SIZE).get_page(request.GET.get("page"))
    parent_url, parent_label = _product_parent()
    post_query = request.GET.urlencode()
    context = tool_context(
        model_admin,
        request,
        title="옵션 재고 관리",
        subtitle="모든 상품의 선택옵션·추가옵션 재고를 한 목록에서 고칩니다.",
        parent_url=parent_url,
        parent_label=parent_label,
        tool_links=product_tool_links(request),
        filters=filters,
        option_list=True,
        categories=_category_choices(),
        page_obj=page_obj,
        page_query=page_query,
        post_url=f"{request.path}?{post_query}" if post_query else request.path,
        rows=list(page_obj),
        can_change=can_change,
        scan_limited=scanned > OPTION_SCAN_LIMIT,
        scan_limit=f"{OPTION_SCAN_LIMIT:,}",
    )
    return TemplateResponse(request, "admin/shop/tools/option_stock_list.html", context)


def _safe_int(value, default=0):
    try:
        return int(value if value not in (None, "") else default)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------- 송장 일괄등록


def delivery_upload_view(model_admin, request):
    require_perms(request, "view_shoporder", "change_shoporder")
    if request.GET.get("download") == "template":
        policy = current_shipping_policy()
        headers, rows = delivery_import.template_rows(str(policy.de_delivery_company or "").strip())
        return _template_download(request, "shop-delivery-upload", headers, rows, text_columns=delivery_import.TEXT_COLUMNS)
    report = None
    error = ""
    if request.method == "POST":
        try:
            report = delivery_import.parse_deliveries(request.FILES.get("file"))
        except SpreadsheetError as exc:
            error = str(exc)
        if report is not None and request.POST.get("step") == "apply":

            def logged(order, item):
                model_admin.log_change(request, order, f"송장 일괄등록: {item.company} {item.invoice}")

            delivery_import.apply_deliveries(
                report,
                actor=request.user.get_username(),
                on_saved=logged,
                send_sms=request.POST.get("send_sms") == "1",
            )
            if report.saved_count:
                messages.success(request, f"주문 {report.saved_count}건에 운송장을 등록하고 배송으로 바꿨습니다.")
            if report.error_count:
                messages.warning(request, f"{report.error_count}개 행은 처리하지 않았습니다. 아래 결과를 확인하세요.")
    parent_url, parent_label = _order_parent()
    context = tool_context(
        model_admin,
        request,
        title="송장 일괄등록",
        subtitle="준비 상태 주문의 배송회사·운송장번호를 엑셀(.xlsx) 또는 CSV 파일로 한 번에 등록하고 배송으로 바꿉니다.",
        parent_url=parent_url,
        parent_label=parent_label,
        report=report,
        report_columns=("주문번호", "받는분", "배송회사", "운송장번호"),
        report_rows=_report_rows(report, ("od_id", "customer", "company", "invoice")) if report else [],
        error=error,
        ready_count=f"{ShopOrder.objects.filter(od_status__in=delivery_import.READY_SPELLINGS).count():,}",
        max_rows=f"{delivery_import.MAX_ROWS:,}",
    )
    return TemplateResponse(request, "admin/shop/tools/delivery_upload.html", context)


# ---------------------------------------------------------------------------- URLs


def _bind(model_admin, view, guard=None):
    def bound(request, *args, **kwargs):
        return view(model_admin, request, *args, **kwargs)

    bound.__name__ = view.__name__
    bound.__doc__ = view.__doc__
    if guard is not None:
        return guard(bound)
    return model_admin.admin_site.admin_view(bound)


def product_tool_urls(model_admin):
    from gnu_jango.shop.admin import reports

    return [
        path("bulk-upload/", _bind(model_admin, product_upload_view), name="shop_shopproduct_bulk_upload"),
        path("stock-list/", _bind(model_admin, stock_list_view), name="shop_shopproduct_stock_list"),
        path("option-stock-list/", _bind(model_admin, option_stock_list_view), name="shop_shopproduct_option_stock_list"),
        path("price-compare/", _bind(model_admin, reports.price_compare_view), name="shop_shopproduct_price_compare"),
        path("wishlist-report/", _bind(model_admin, reports.wishlist_report_view), name="shop_shopproduct_wishlist_report"),
    ]


def order_tool_urls(model_admin):
    from gnu_jango.shop.admin import reports

    return [
        path("delivery-upload/", _bind(model_admin, delivery_upload_view), name="shop_shoporder_delivery_upload"),
        # the sales tables show order amounts per order: the order view permission, as the reports
        path("sales/", _bind(model_admin, reports.sales_view, guard=model_admin.order_report_view), name="shop_shoporder_sales"),
        path(
            "sales-anomalies/",
            _bind(model_admin, reports.sales_anomalies_view, guard=model_admin.order_report_view),
            name="shop_shoporder_sales_anomalies",
        ),
    ]


# ---------------------------------------------------------------------------- admin actions


def _set_review_visibility(modeladmin, request, queryset, value, verb):
    # the rows to change, taken before the update (a changelist filtered on visibility would be
    # empty afterwards)
    reviews = list(queryset.select_related(None).exclude(is_confirm=value).only("pk", "is_subject", "product_id"))
    changed = ShopReview.objects.filter(pk__in=[review.pk for review in reviews]).update(is_confirm=value)
    recount_product_reviews({review.product_id for review in reviews})
    for review in reviews:
        modeladmin.log_change(request, review, f"후기 {verb}")
    modeladmin.message_user(request, f"후기 {changed}건을 {verb}했습니다.", messages.SUCCESS)


@admin.action(description="선택한 후기 승인 (쇼핑몰에 표시)", permissions=["change"])
def approve_selected_reviews(modeladmin, request, queryset):
    """youngcart itemuselistupdate.php 선택수정 with 확인: publish and recount the products."""
    _set_review_visibility(modeladmin, request, queryset, "1", "승인")


@admin.action(description="선택한 후기 숨김", permissions=["change"])
def hide_selected_reviews(modeladmin, request, queryset):
    _set_review_visibility(modeladmin, request, queryset, "0", "숨김")


def _new_personal_pay_id():
    from gnu_jango.shop.personal_pay import new_personal_pay_id

    return new_personal_pay_id()


def _finish_personal_pay_action(modeladmin, request, created, verb):
    for pay in created:
        modeladmin.log_addition(request, pay, verb)
    if len(created) == 1:
        modeladmin.message_user(
            request, f"개인결제 {created[0].pp_id}을(를) 만들었습니다. 이름·금액을 확인하고 저장하세요.", messages.SUCCESS
        )
        return HttpResponseRedirect(reverse("admin:shop_shoppersonalpay_change", args=[created[0].pk]))
    if created:
        modeladmin.message_user(request, f"개인결제 {len(created)}건을 만들었습니다.", messages.SUCCESS)
    return None


@admin.action(description="선택한 개인결제 복사", permissions=["add"])
def copy_selected_personal_pays(modeladmin, request, queryset):
    """youngcart personalpaycopyupdate.php: a new request with the same customer, content and
    amount; nothing of the original payment is carried over."""
    created = []
    for source in queryset[:50]:
        created.append(
            ShopPersonalPay.objects.create(
                pp_id=_new_personal_pay_id(),
                user=source.user,
                # not linked to the source's order: a payment of the copy would be credited to that
                # order a second time (youngcart personalpaycopy asks for the order number anew)
                pp_name=source.pp_name,
                pp_email=source.pp_email,
                pp_hp=source.pp_hp,
                pp_content=source.pp_content,
                pp_price=source.pp_price,
                active=source.active,
            )
        )
    return _finish_personal_pay_action(modeladmin, request, created, "개인결제 복사")


@admin.action(description="미수금으로 개인결제 만들기", permissions=["view"])
def create_personal_pay_for_balance(modeladmin, request, queryset):
    """youngcart personalpayform.php?od_id=: a request for what the order still owes, linked to
    the order so the payment is credited to it (shop/personal_pay.py apply_receipt_to_order)."""
    from gnu_jango.shop.order_flow import canonical_status, order_misu
    from gnu_jango.shop.order_statuses import INACTIVE_LINE_STATUSES
    from gnu_jango.shop.personal_pay import is_paid

    if not request.user.has_perm("shop.add_shoppersonalpay"):
        modeladmin.message_user(request, "개인결제를 추가할 권한이 없습니다.", messages.ERROR)
        return None
    created = []
    skipped = []
    pending = []
    pay_admin = modeladmin.admin_site.get_model_admin(ShopPersonalPay)
    for order_id in list(queryset.values_list("pk", flat=True)[:50]):
        # the order row stays locked while its requests are checked, so two admins (or a double
        # submit) cannot both create a request for the same balance
        with transaction.atomic():
            order = ShopOrder.objects.select_for_update().filter(pk=order_id).first()
            if order is None:
                continue
            owed = order_misu(order)
            if owed <= 0 or canonical_status(order.od_status) in INACTIVE_LINE_STATUSES:
                skipped.append(order.od_id)
                continue
            if any(pay.active and not is_paid(pay) for pay in ShopPersonalPay.objects.filter(order=order)):
                pending.append(order.od_id)
                continue
            created.append(
                ShopPersonalPay.objects.create(
                    pp_id=_new_personal_pay_id(),
                    user_id=order.user_id,
                    order=order,
                    pp_name=order.od_name or order.od_b_name or order.od_id,
                    pp_email=order.od_email,
                    pp_hp=order.od_hp,
                    pp_content=f"주문번호 {order.od_id} 미수금",
                    pp_price=owed,
                )
            )
    if pending:
        shown = ", ".join(pending[:5]) + (f" 외 {len(pending) - 5}건" if len(pending) > 5 else "")
        modeladmin.message_user(request, f"결제 전인 개인결제가 이미 있는 주문은 건너뛰었습니다 ({shown}).", messages.WARNING)
    if skipped:
        shown = ", ".join(skipped[:5]) + (f" 외 {len(skipped) - 5}건" if len(skipped) > 5 else "")
        modeladmin.message_user(request, f"미수금이 없거나 취소된 주문은 건너뛰었습니다 ({shown}).", messages.WARNING)
    return _finish_personal_pay_action(pay_admin, request, created, "주문 미수금 개인결제 생성")
