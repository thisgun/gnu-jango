"""The admin's cash receipt page of an order (/admin/shop/shoporder/<id>/cash-receipt/): issue a
receipt (youngcart orderform.php's 현금영수증 발급 opens taxsave.php for the admin too), record one
issued by hand, turn a request down, or cancel an issued receipt."""

from django.contrib import messages
from django.contrib.admin.utils import unquote
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import reverse

from gnu_jango.shop.cash_receipts import (
    CASH_RECEIPT_TYPE_LABELS,
    CashReceiptError,
    admin_summary,
    cancel_receipt,
    mark_issued,
    request_cash_receipt,
    withdraw_request,
)

def _run(order, data, actor):
    action = str(data.get("action") or "")
    reason = str(data.get("reason") or "").strip()[:200]
    if action == "issue":
        return request_cash_receipt(
            order, data.get("cash_type"), data.get("identity"), actor=actor, by_admin=True
        )
    if action == "mark_issued":
        return mark_issued(order, data.get("cash_no"), data.get("receipt_url"), actor=actor)
    if action == "withdraw":
        return withdraw_request(order, actor=actor, reason=reason)
    if action == "cancel":
        return cancel_receipt(order, actor=actor, reason=reason)
    raise CashReceiptError("처리할 작업을 고르세요.")


def order_cash_receipt_page(model_admin, request, object_id):
    order = model_admin.get_object(request, unquote(object_id))
    if order is None:
        raise Http404
    if not model_admin.has_change_permission(request, order):
        raise PermissionDenied
    page_url = reverse("admin:shop_shoporder_cash_receipt", args=[order.pk])
    error = ""
    if request.method == "POST":
        try:
            result = _run(order, request.POST, request.user.get_username())
        except CashReceiptError as exc:
            error = str(exc)
        else:
            model_admin.log_change(request, order, f"현금영수증: {result.message}")
            model_admin.message_user(request, result.message, messages.SUCCESS)
            return redirect(page_url)
        order.refresh_from_db()
    summary = admin_summary(order)
    context = {
        **model_admin.admin_site.each_context(request),
        "opts": model_admin.model._meta,
        "title": f"현금영수증 - {order.od_id}",
        "order": order,
        "summary": summary,
        "error": error,
        "types": list(CASH_RECEIPT_TYPE_LABELS.items()),
        "posted": request.POST if request.method == "POST" else {},
        "change_url": reverse("admin:shop_shoporder_change", args=[order.pk]),
        "history": [line for line in (order.od_mod_history or "").splitlines() if "현금영수증" in line][-10:],
    }
    return TemplateResponse(request, "admin/shop/order_cash_receipt.html", context)
