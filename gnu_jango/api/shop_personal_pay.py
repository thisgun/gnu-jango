"""Personal pay API (youngcart shop/personalpay.php, personalpayform.php, personalpayformupdate.php).

The checkout offers what an order checkout offers (checkout_payment_methods): 무통장입금 when bank
accounts are configured, and the Toss methods while the Toss keys are set. Virtual accounts are not
offered: their deposit webhook belongs to shop orders.

Toss flow: POST .../toss/prepare gives the widget the server's amount and the request's own Toss
orderId; the widget returns to the pay page, which POSTs .../toss/confirm. The confirm checks the
amount against the request, asks Toss to approve exactly that amount, checks what Toss approved and
records it (record_receipt). Should the request have been paid or closed in the meantime, the Toss
payment is cancelled again, as personalpayformupdate.php does.
"""

import logging
from types import SimpleNamespace

from django.db.models import F
from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny

from gnu_jango.shop import personal_pay as pp_service
from gnu_jango.shop.models import ShopPersonalPay

from . import shop_payments
from .authentication import SessionJWTAuthentication as JWTAuthentication
from .response import api_error, api_response
from .shop_common import (
    configured_bank_accounts,
    current_user,
    datetime_value,
    paginate_queryset,
    request_data,
)

logger = logging.getLogger(__name__)

TOSS_METHODS = ("card", "iche", "hp", "easy_pay")
DEPOSIT_NAME_MAX = 100


def personalpay_payload(item):
    state = pp_service.payment_state(item)
    paid = state == pp_service.STATE_PAID
    receipt_url = (
        f"https://dashboard.tosspayments.com/receipt/redirection?transactionId={item.pp_tno}"
        if item.pp_tno and paid
        else ""
    )
    cash_receipt_url = (
        f"https://dashboard.tosspayments.com/receipt/cash-receipt/{item.pp_cash_no}"
        if item.pp_cash and item.pp_cash_no
        else ""
    )
    block_reason = pp_service.checkout_block_reason(item, "online")
    can_pay = not block_reason
    return {
        "pp_id": item.pp_id,
        "od_id": item.order_id or "",
        "pp_name": item.pp_name,
        "pp_email": item.pp_email,
        "pp_hp": item.pp_hp,
        "pp_content": item.pp_content,
        "pp_price": item.pp_price,
        "pp_pg": item.pp_pg,
        "pp_tno": item.pp_tno,
        "pp_app_no": item.pp_app_no,
        "pp_settle_case": item.pp_settle_case,
        "pp_bank_account": item.pp_bank_account,
        "pp_deposit_name": item.pp_deposit_name,
        "pp_receipt_price": item.pp_receipt_price,
        "pp_misu_price": pp_service.amount_due(item),
        "already_paid": paid,
        "has_payment_transaction": pp_service.has_transaction(item),
        "payment_in_progress": state == pp_service.STATE_PROCESSING,
        "awaiting_deposit": state == pp_service.STATE_AWAITING_DEPOSIT,
        "payment_state": state,
        "payment_state_label": pp_service.STATE_LABELS[state],
        "pp_receipt_time": item.pp_receipt_time or None,
        "pp_time": datetime_value(item.pp_time),
        "pp_cash": item.pp_cash,
        "pp_cash_no": item.pp_cash_no,
        "pp_payment_app_label": "Approval no." if item.pp_app_no else "Transaction no." if item.pp_tno else "",
        "pp_payment_app_value": item.pp_app_no or item.pp_tno,
        "receipt_url": receipt_url,
        "pp_payment_receipt_url": receipt_url,
        "cash_receipt_url": cash_receipt_url,
        "pp_cash_receipt_url": cash_receipt_url,
        "cash_receipt_issue_url": "",
        "pp_cash_receipt_issue_url": "",
        "payment_path": f"/shop/personalpayform.php?pp_id={item.pp_id}",
        "checkout_path": f"/shop/personalpay/{item.pp_id}/pay",
        "can_pay": can_pay,
        "can_change_deposit": state == pp_service.STATE_AWAITING_DEPOSIT and item.active,
        "payment_block_reason": block_reason,
    }


def accessible_personal_pay(request, pp_id):
    """The active request ``pp_id`` when the caller may see it: its member, staff, or anyone for a
    request issued without a member (youngcart hands those out by link)."""
    user = current_user(request)
    item = ShopPersonalPay.objects.filter(pk=pp_id, active=True).first()
    if not item:
        return None, api_error("Personal pay not found.", status=drf_status.HTTP_404_NOT_FOUND, code="personalpay_not_found")
    if item.user_id and not (user and (user.is_staff or user.is_superuser or item.user_id == user.id)):
        return None, api_error("Permission denied.", status=drf_status.HTTP_403_FORBIDDEN, code="permission_denied")
    return item, None


def not_payable(reason):
    return api_error(reason, status=drf_status.HTTP_409_CONFLICT, code="personalpay_not_payable")


def agreed(data):
    value = data.get("agree")
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return bool(value)


def agreement_required():
    return api_error(
        "Agree to the payment terms to continue.",
        status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="validation_error",
        details={"agree": "Agree to the payment terms to continue."},
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def personalpay_view(request, pp_id=None):
    if pp_id is not None:
        item, error = accessible_personal_pay(request, pp_id)
        if error:
            return error
        return api_response(data=personalpay_payload(item))

    user = current_user(request)
    if not user or not user.is_authenticated:
        return api_error(
            "Authentication credentials were not provided.",
            status=drf_status.HTTP_401_UNAUTHORIZED,
            code="not_authenticated",
        )

    queryset = ShopPersonalPay.objects.filter(active=True, pp_receipt_price__lt=F("pp_price"), pp_tno="", pp_app_no="")
    if not (user.is_staff or user.is_superuser):
        queryset = queryset.filter(user=user)
    page, meta = paginate_queryset(request, queryset, default_per_page=20)
    return api_response(data=[personalpay_payload(item) for item in page], meta=meta)


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def personalpay_start_view(request, pp_id):
    """Kept for older clients: it answers where the checkout is (the legacy personalpayform.php
    address, which redirects to the Next.js pay page)."""
    item, error = accessible_personal_pay(request, pp_id)
    if error:
        return error
    payload = personalpay_payload(item)
    if not payload["can_pay"]:
        return not_payable(payload["payment_block_reason"])
    payment_path = payload["payment_path"]
    return api_response(
        data={
            "pp_id": item.pp_id,
            "payment_path": payment_path,
            "payment_url": payment_path,
            "legacy_payment_url": payment_path,
            "checkout_path": payload["checkout_path"],
            "can_pay": True,
            "payment_state": payload["payment_state"],
            "payment_state_label": payload["payment_state_label"],
            "payment_block_reason": "",
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def personalpay_bank_view(request, pp_id):
    """무통장입금: the customer picks one of the shop's accounts and names the depositor. The request
    then waits for the shop to confirm the deposit (admin action)."""
    item, error = accessible_personal_pay(request, pp_id)
    if error:
        return error
    data = request_data(request)
    accounts = configured_bank_accounts()
    if not accounts:
        return api_error(
            "Bank transfer is not configured.",
            status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
            code="bank_deposit_unavailable",
        )
    bank_account = str(data.get("bank_account") or data.get("pp_bank_account") or "").strip()
    if bank_account not in accounts:
        return api_error(
            "Select a configured bank account.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details={"bank_account": "Select a configured bank account."},
        )
    deposit_name = " ".join(str(data.get("deposit_name") or data.get("pp_deposit_name") or "").split())
    if not deposit_name:
        return api_error(
            "Enter the depositor name.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details={"deposit_name": "Enter the depositor name."},
        )
    if len(deposit_name) > DEPOSIT_NAME_MAX:
        return api_error(
            "Depositor name is too long.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details={"deposit_name": "Depositor name is too long."},
        )
    if not agreed(data):
        return agreement_required()
    item, reason = pp_service.choose_bank_deposit(item.pp_id, bank_account=bank_account, deposit_name=deposit_name)
    if reason:
        return not_payable(reason)
    return api_response(data=personalpay_payload(item))


def toss_ready_error():
    config = shop_payments.toss_payment_config()
    if shop_payments.configured_payment_provider() != "toss" or not config["enabled"]:
        return api_error(
            "Toss Payments is not configured.",
            status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
            code="toss_payment_unconfigured",
        )
    return None


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def personalpay_toss_prepare_view(request, pp_id):
    item, error = accessible_personal_pay(request, pp_id)
    if error:
        return error
    error = toss_ready_error()
    if error:
        return error
    data = request_data(request)
    method = str(data.get("method") or data.get("payment_method") or "card").strip()
    if method not in TOSS_METHODS or not shop_payments.checkout_payment_methods().get(method):
        return api_error(
            "The selected payment method is not available.",
            status=drf_status.HTTP_400_BAD_REQUEST,
            code="payment_method_disabled",
        )
    if not agreed(data):
        return agreement_required()
    reason = pp_service.checkout_block_reason(item, "online")
    if reason:
        return not_payable(reason)
    order_id = pp_service.toss_order_id(item)
    if not order_id:
        return api_error(
            "This personal pay cannot be paid online.",
            status=drf_status.HTTP_409_CONFLICT,
            code="personalpay_online_unavailable",
        )
    return api_response(
        data={
            "pp_id": item.pp_id,
            "order_id": order_id,
            "order_name": f"개인결제 {item.pp_name}"[:100],
            "amount": pp_service.amount_due(item),
            "buyer_name": item.pp_name,
            "buyer_email": item.pp_email or "",
            "buyer_tel": item.pp_hp or "",
            "method": method,
            "pg_service": "toss",
            "client_key": shop_payments.toss_payment_config()["client_key"],
        }
    )


def refund_toss_payment(order_id, payment_key_value, reason):
    """Give back a Toss payment we could not record (personalpayformupdate.php toss_cancel.php)."""
    try:
        shop_payments.toss_api_cancel_payment(SimpleNamespace(od_id=order_id, od_tno=payment_key_value), reason)
    except shop_payments.PaymentCancelError:
        logger.exception("Toss payment %s for personal pay %s could not be cancelled", payment_key_value, order_id)
        return False
    return True


def toss_payment_mismatch(item, order_id, payment_key_value, toss_payment):
    """Why the approved Toss payment does not belong to ``item`` ("" when it does)."""
    if not isinstance(toss_payment, dict) or str(toss_payment.get("orderId") or "") != order_id:
        return "Toss payment order does not match the local order."
    if str(toss_payment.get("paymentKey") or "") != payment_key_value:
        return "Toss payment key does not match the confirmation request."
    approved = shop_payments.safe_amount_int(toss_payment.get("totalAmount", toss_payment.get("amount")), -1)
    if approved != pp_service.amount_due(item):
        return "Toss approved amount does not match the order amount."
    return ""


def toss_receipt(toss_payment, item):
    card = toss_payment.get("card") if isinstance(toss_payment.get("card"), dict) else {}
    cash_receipt = shop_payments.toss_cash_receipt_from_payment(toss_payment) or {}
    approved_at = str(toss_payment.get("approvedAt") or "")
    return pp_service.Receipt(
        amount=pp_service.amount_due(item),
        settle_case=pp_service.toss_settle_case(toss_payment.get("method")),
        receipt_time=approved_at[:19].replace("T", " ") if approved_at else pp_service.receipt_time_label(),
        pg="toss",
        tno=str(toss_payment.get("paymentKey") or ""),
        app_no=str(card.get("approveNo") or ""),
        bank_account="",
        deposit_name=item.pp_name,
        cash_no=str(cash_receipt.get("issueNumber") or ""),
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def personalpay_toss_confirm_view(request, pp_id):
    item, error = accessible_personal_pay(request, pp_id)
    if error:
        return error
    data = request_data(request)
    payment_key_value = shop_payments.payment_key(data)
    order_id = shop_payments.payment_order_id(data)
    if not payment_key_value:
        return api_error("Toss payment key is required.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, code="toss_payment_key_required")
    expected_order_id = pp_service.toss_order_id(item)
    if not expected_order_id or order_id != expected_order_id:
        return api_error("Toss payment order does not match the local order.", status=drf_status.HTTP_409_CONFLICT, code="toss_order_mismatch")
    if item.pp_tno == payment_key_value and pp_service.is_paid(item):
        # the success page was reloaded: the payment is already recorded
        return api_response(data=personalpay_payload(item))
    reason = pp_service.checkout_block_reason(item, "online")
    if reason:
        return not_payable(reason)
    amount = shop_payments.payment_amount(data)
    due = pp_service.amount_due(item)
    if amount != due:
        shop_payments.record_payment_raw_log(None, order_id, "toss", payment_key_value, data, prefix="pp-reject")
        return api_error(
            "Payment amount does not match the order amount.",
            status=drf_status.HTTP_409_CONFLICT,
            code="payment_amount_mismatch",
            details={"expected_amount": due, "received_amount": amount},
        )
    toss_payment, error = shop_payments.toss_api_confirm(payment_key_value, order_id, due)
    if error:
        shop_payments.record_payment_raw_log(None, order_id, "toss", payment_key_value, data, prefix="pp-reject")
        return error
    raw_data = {**data, "toss_payment": toss_payment}
    mismatch = toss_payment_mismatch(item, order_id, payment_key_value, toss_payment)
    status_value = str(toss_payment.get("status") or "").upper() if isinstance(toss_payment, dict) else ""
    if mismatch or status_value != "DONE":
        shop_payments.record_payment_raw_log(None, order_id, "toss", payment_key_value, raw_data, prefix="pp-reject")
        if status_value in {"DONE", "WAITING_FOR_DEPOSIT"}:
            refund_toss_payment(order_id, payment_key_value, "결제금액 불일치")
        return api_error(
            mismatch or "Toss payment is not completed.",
            status=drf_status.HTTP_409_CONFLICT,
            code="toss_payment_mismatch" if mismatch else "toss_payment_not_done",
        )
    recorded, reason = pp_service.record_receipt(item.pp_id, toss_receipt(toss_payment, item), method="online")
    shop_payments.record_payment_raw_log(None, order_id, "toss", payment_key_value, raw_data, prefix="pp")
    if reason:
        refund_toss_payment(order_id, payment_key_value, "개인결제 정보 처리 오류")
        return not_payable(reason)
    return api_response(data=personalpay_payload(recorded))
