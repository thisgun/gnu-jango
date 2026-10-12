"""Payment providers for shop orders: Toss Payments, signed adapters and callback checks."""

import base64
import hashlib
import hmac
import json
import logging
import socket
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status as drf_status

from gnu_jango.shop.models import (
    ShopCoupon,
    ShopOrder,
    ShopOrderData,
)

from .response import api_error

from .shop_common import (
    ORDERED_STATUSES,
    CANCELLED_STATUSES,
    ORDER_STATUS_PAID,
    PAYMENT_ADAPTER_PROVIDERS,
    first_value,
    safe_int,
    split_setting_list,
)

logger = logging.getLogger(__name__)


def payment_transaction_id(data):
    for key in ("transaction_id", "transactionId", "paymentKey", "tno", "TID", "tid", "P_TID", "LGD_TID", "authToken"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    return ""


def payment_key(data):
    return str(first_value(data, "paymentKey", "payment_key", "payment_key_id") or "").strip()


def configured_payment_provider():
    configured_provider = str(getattr(settings, "SHOP_PAYMENT_PROVIDER", "") or "").strip().lower()
    toss_client_key = str(getattr(settings, "SHOP_TOSS_CLIENT_KEY", "") or "").strip()
    toss_secret_key = str(getattr(settings, "SHOP_TOSS_SECRET_KEY", "") or "").strip()
    if configured_provider in PAYMENT_ADAPTER_PROVIDERS and payment_adapter_enabled(configured_provider):
        return configured_provider
    if toss_client_key and toss_secret_key:
        return "toss"
    return "bank"


def toss_payment_config():
    client_key = str(getattr(settings, "SHOP_TOSS_CLIENT_KEY", "") or "").strip()
    secret_key = str(getattr(settings, "SHOP_TOSS_SECRET_KEY", "") or "").strip()
    return {
        "enabled": bool(client_key and secret_key),
        "vbank_enabled": bool(getattr(settings, "SHOP_TOSS_VBANK_ENABLED", False) and client_key and secret_key),
        "client_key": client_key,
        "has_secret_key": bool(secret_key),
        "api_base_url": str(getattr(settings, "SHOP_TOSS_API_BASE_URL", "") or "https://api.tosspayments.com").rstrip("/"),
        "is_test_mode": client_key.startswith("test_") or secret_key.startswith("test_"),
    }


def payment_adapter_config():
    provider_setting = str(getattr(settings, "SHOP_PAYMENT_ADAPTER_PROVIDERS", "") or "").strip()
    providers = split_setting_list(provider_setting) if provider_setting else set(PAYMENT_ADAPTER_PROVIDERS)
    providers = providers & PAYMENT_ADAPTER_PROVIDERS
    base_url = str(getattr(settings, "SHOP_PAYMENT_ADAPTER_BASE_URL", "") or "").strip().rstrip("/")
    secret = str(getattr(settings, "SHOP_PAYMENT_ADAPTER_SECRET", "") or "").strip()
    timeout = safe_int(getattr(settings, "SHOP_PAYMENT_ADAPTER_TIMEOUT", 10), 10)
    return {
        "enabled": bool(base_url and secret),
        "base_url": base_url,
        "has_secret": bool(secret),
        "secret": secret,
        "providers": sorted(providers),
        "timeout": max(1, min(timeout, 30)),
    }


def payment_adapter_enabled(provider):
    provider = str(provider or "").strip().lower()
    config = payment_adapter_config()
    return bool(config["enabled"] and provider in set(config["providers"]))


def payment_adapter_signature(secret, timestamp, body):
    payload = f"{timestamp}.{body}".encode("utf-8")
    return hmac.new(str(secret).encode("utf-8"), payload, hashlib.sha256).hexdigest()


def payment_adapter_request(action, provider, data):
    provider = str(provider or "").strip().lower()
    config = payment_adapter_config()
    if not config["enabled"] or provider not in set(config["providers"]):
        return None, api_error(
            "Payment verification adapter is not configured for this provider.",
            status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
            code="payment_adapter_unconfigured",
            details={"provider": provider},
        )

    payload = {"action": str(action or "").strip(), "provider": provider, "payload": data}
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    timestamp = str(int(timezone.now().timestamp()))
    request = urllib_request.Request(
        config["base_url"],
        data=body.encode("utf-8"),
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Gnujango-Adapter-Timestamp": timestamp,
            "X-Gnujango-Adapter-Signature": f"sha256={payment_adapter_signature(config['secret'], timestamp, body)}",
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=config["timeout"]) as response:
            raw = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:1000]
        try:
            payload = json.loads(raw or "{}")
        except ValueError:
            payload = {"message": raw}
        return None, api_error(
            str(payload.get("message") or payload.get("error") or "Payment adapter rejected the request."),
            status=drf_status.HTTP_400_BAD_REQUEST if 400 <= exc.code < 500 else drf_status.HTTP_502_BAD_GATEWAY,
            code="payment_adapter_rejected",
            details={"provider": provider, "adapter_status": exc.code},
        )
    except (urllib_error.URLError, TimeoutError, socket.timeout) as exc:
        # The exception text can name internal hosts; it goes to the log, not to the client.
        logger.warning("Payment adapter request for %s failed: %s", provider, exc)
        return None, api_error(
            "Payment adapter request failed.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="payment_adapter_unavailable",
            details={"provider": provider},
        )

    try:
        return json.loads(raw or "{}"), None
    except ValueError:
        return None, api_error(
            "Payment adapter returned an invalid response.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="payment_adapter_invalid_response",
            details={"provider": provider},
        )


def settle_case_is_bank(value):
    return str(value or "").strip() in {"", "bank", "무통장", "무통장입금"}


def settle_case_supports_cash_receipt(value):
    normalized = str(value or "").strip().lower().replace(" ", "")
    return normalized in {
        "bank",
        "무통장",
        "무통장입금",
        "vbank",
        "가상계좌",
        "iche",
        "계좌이체",
        "실시간계좌이체",
    }


def settle_case_is_vbank(value):
    normalized = str(value or "").strip().lower().replace("_", "").replace("-", "")
    return normalized in {"vbank", "virtualaccount", "가상계좌"}


def payment_log_id(order_id, transaction_id):
    suffix = transaction_id or uuid.uuid4().hex
    return ("pay-%s-%s" % (order_id, suffix))[:40]


def safe_amount_int(value, default=-1):
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    return safe_int(value, default)


def payment_order_id(data):
    return str(
        first_value(
            data,
            "order_id",
            "orderId",
            "od_id",
            "ordr_idxx",
            "MOID",
            "Moid",
            "moid",
            "oid",
            "P_OID",
            "P_NOTI",
            "orderNumber",
        )
        or ""
    ).strip()


def payment_amount(data):
    return safe_amount_int(
        first_value(
            data,
            "amount",
            "approved_amount",
            "paid_amount",
            "totalAmount",
            "TotPrice",
            "Amt",
            "good_mny",
            "price",
            "P_AMT",
            "LGD_AMOUNT",
        ),
        -1,
    )


def payment_callback_success(data):
    success_value = str(first_value(data, "success", "is_success", "paid", "ok") or "").strip().lower()
    if success_value in ("1", "true", "yes", "y", "ok", "success"):
        return True

    status_value = str(
        first_value(
            data,
            "status",
            "paymentStatus",
            "pay_status",
            "P_STATUS",
            "resultStatus",
            "trade_state",
            "state",
        )
        or ""
    ).strip().lower()
    if status_value in ("done", "paid", "success", "approved", "completed", "complete", "00", "0"):
        return True

    result_code = str(
        first_value(
            data,
            "res_cd",
            "resultCode",
            "ResultCode",
            "result_code",
            "P_STATUS",
            "LGD_RESPCODE",
        )
        or ""
    ).strip()
    return result_code in ("0000", "00", "0", "3001")


def payment_adapter_success(data):
    if not isinstance(data, dict):
        return False
    if data.get("verified") is True or data.get("approved") is True:
        return True
    if data.get("success") is True or data.get("ok") is True:
        return True
    return payment_callback_success(data)


def payment_callback_secret(request, data):
    header_value = first_value(
        request.META,
        "HTTP_X_GNUJANGO_PAYMENT_CALLBACK_SECRET",
        "HTTP_X_PAYMENT_CALLBACK_SECRET",
        "HTTP_X_WEBHOOK_SECRET",
    )
    if header_value:
        return str(header_value).strip()
    # Only the request body: a secret in the query string would end up in access logs.
    body = request.data if hasattr(request.data, "get") else {}
    return str(first_value(body, "callback_secret", "webhook_secret", "secret") or "").strip()


def payment_callback_signature(request, data):
    header_value = first_value(
        request.META,
        "HTTP_X_GNUJANGO_PAYMENT_SIGNATURE",
        "HTTP_X_PAYMENT_SIGNATURE",
        "HTTP_X_HUB_SIGNATURE_256",
    )
    if header_value:
        return str(header_value).strip()
    return str(first_value(data, "payment_signature", "callback_signature", "signature") or "").strip()


def normalize_payment_signature(value):
    signature = str(value or "").strip().lower()
    if signature.startswith("sha256="):
        signature = signature[7:]
    return signature


def payment_callback_signature_payload(provider, data):
    payload = {
        "amount": payment_amount(data),
        "order_id": payment_order_id(data),
        "provider": str(provider or "").strip().lower(),
        "success": payment_callback_success(data),
        "transaction_id": payment_transaction_id(data),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def payment_callback_expected_signature(provider, data, secret):
    payload = payment_callback_signature_payload(provider, data)
    return hmac.new(str(secret).encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def payment_callback_signature_error(request, provider, data):
    configured_secret = str(getattr(settings, "SHOP_PAYMENT_CALLBACK_SIGNATURE_SECRET", "") or "").strip()
    if not configured_secret:
        return None

    received = normalize_payment_signature(payment_callback_signature(request, data))
    if not received:
        return api_error(
            "Payment callback signature is required.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="payment_callback_signature_required",
        )

    expected = payment_callback_expected_signature(provider, data, configured_secret)
    if not hmac.compare_digest(received, expected):
        return api_error(
            "Invalid payment callback signature.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="payment_callback_signature_invalid",
        )

    return None


def redact_payment_data(data):
    if isinstance(data, dict):
        redacted = {}
        for key, value in data.items():
            normalized = str(key).lower().replace("-", "_")
            if "secret" in normalized or "signature" in normalized or "authorization" in normalized or "access_token" in normalized:
                redacted[key] = "***redacted***"
            else:
                redacted[key] = redact_payment_data(value)
        return redacted
    if isinstance(data, list):
        return [redact_payment_data(value) for value in data]
    if isinstance(data, tuple):
        return [redact_payment_data(value) for value in data]
    return data


def record_payment_raw_log(order, order_id, pg_service, transaction_id, data, *, prefix="pay"):
    log_id = payment_log_id(order_id or "unknown", transaction_id)
    if prefix and prefix != "pay":
        log_id = ("%s-%s" % (prefix, log_id))[:40]
    ShopOrderData.objects.update_or_create(
        log_id=log_id,
        defaults={
            "order": order,
            "od_id": order.od_id if order else str(order_id or ""),
            "cart_id": "",
            "user": order.user if order and order.user_id else None,
            "mb_id": order.user.get_username() if order and order.user_id else "",
            "dt_pg": str(pg_service or "")[:50],
            "dt_data": json.dumps(redact_payment_data(data), ensure_ascii=False, default=str),
            "dt_time": timezone.now(),
        },
    )


def toss_api_confirm(payment_key_value, order_id, amount):
    config = toss_payment_config()
    secret_key = str(getattr(settings, "SHOP_TOSS_SECRET_KEY", "") or "").strip()
    if not config["enabled"] or not secret_key:
        return None, api_error(
            "Toss Payments is not configured.",
            status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
            code="toss_payment_unconfigured",
        )

    credentials = base64.b64encode(f"{secret_key}:".encode("utf-8")).decode("ascii")
    body = json.dumps(
        {
            "paymentKey": payment_key_value,
            "orderId": order_id,
            "amount": amount,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib_request.Request(
        f"{config['api_base_url']}/v1/payments/confirm",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Idempotency-Key": f"confirm-{order_id}-{payment_key_value}"[:300],
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw or "{}"), None
    except urllib_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except ValueError:
            payload = {"message": raw}
        return None, api_error(
            str(payload.get("message") or payload.get("code") or "Toss payment authorization failed."),
            status=drf_status.HTTP_400_BAD_REQUEST if 400 <= exc.code < 500 else drf_status.HTTP_502_BAD_GATEWAY,
            code="toss_payment_rejected",
            details={
                "provider": "toss",
                "provider_status": exc.code,
                "provider_code": payload.get("code", ""),
            },
        )
    except (urllib_error.URLError, TimeoutError, socket.timeout) as exc:
        logger.warning("Toss payment authorization request failed: %s", exc)
        return None, api_error(
            "Toss payment authorization request failed.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="toss_payment_unavailable",
            details={"provider": "toss"},
        )
    except ValueError:
        return None, api_error(
            "Toss payment authorization returned an invalid response.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="toss_payment_invalid_response",
        )


def toss_api_get_payment_by_order(order_id):
    config = toss_payment_config()
    secret_key = str(getattr(settings, "SHOP_TOSS_SECRET_KEY", "") or "").strip()
    if not config["enabled"] or not secret_key:
        return None, api_error(
            "Toss Payments is not configured.",
            status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
            code="toss_payment_unconfigured",
        )
    credentials = base64.b64encode(f"{secret_key}:".encode("utf-8")).decode("ascii")
    request = urllib_request.Request(
        f"{config['api_base_url']}/v1/payments/orders/{quote(str(order_id), safe='')}",
        method="GET",
        headers={"Authorization": f"Basic {credentials}", "Accept": "application/json"},
    )
    try:
        with urllib_request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("Toss response must be a JSON object.")
            return payload, None
    except urllib_error.HTTPError as exc:
        return None, api_error(
            "Toss payment status could not be retrieved.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="toss_payment_status_unavailable",
            details={"provider_status": exc.code},
        )
    except (urllib_error.URLError, TimeoutError, socket.timeout):
        return None, api_error(
            "Toss payment status could not be retrieved.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="toss_payment_status_unavailable",
        )
    except ValueError:
        return None, api_error(
            "Toss payment status returned an invalid response.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="toss_payment_invalid_response",
        )


def cancel_pending_toss_vbank(order, reason):
    if not settle_case_is_vbank(order.od_settle_case) or not order.od_tno:
        return None
    payment, error = toss_api_get_payment_by_order(order.od_id)
    if error:
        return error
    if (
        str(payment.get("orderId") or "") != str(order.od_id)
        or safe_amount_int(payment.get("totalAmount"), -1) != order.od_receipt_price
        or str(payment.get("paymentKey") or "") != str(order.od_tno)
        or not toss_method_is_vbank(payment.get("method"))
    ):
        return api_error(
            "Toss payment does not match this virtual account order.",
            status=drf_status.HTTP_409_CONFLICT,
            code="toss_vbank_cancel_mismatch",
        )
    provider_status = str(payment.get("status") or "").upper()
    if provider_status in {"CANCELED", "EXPIRED"}:
        return None
    if provider_status != "WAITING_FOR_DEPOSIT":
        return api_error(
            "This virtual account is no longer waiting for a deposit. Contact support to reconcile the payment.",
            status=drf_status.HTTP_409_CONFLICT,
            code="toss_vbank_cancel_requires_review",
        )

    config = toss_payment_config()
    secret_key = str(getattr(settings, "SHOP_TOSS_SECRET_KEY", "") or "").strip()
    credentials = base64.b64encode(f"{secret_key}:".encode("utf-8")).decode("ascii")
    payload = json.dumps({"cancelReason": str(reason or "Customer requested cancellation")[:200]}).encode("utf-8")
    request = urllib_request.Request(
        f"{config['api_base_url']}/v1/payments/{quote(str(order.od_tno), safe='')}/cancel",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Idempotency-Key": f"vbank-cancel-{order.od_id}"[:300],
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=10) as response:
            canceled = json.loads(response.read().decode("utf-8") or "{}")
            if not isinstance(canceled, dict):
                raise ValueError("Toss response must be a JSON object.")
    except urllib_error.HTTPError as exc:
        return api_error(
            "Toss could not cancel the virtual account. The order was left unchanged.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="toss_vbank_cancel_failed",
            details={"provider_status": exc.code},
        )
    except (urllib_error.URLError, TimeoutError, socket.timeout, ValueError):
        return api_error(
            "Toss could not confirm virtual account cancellation. The order was left unchanged.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="toss_vbank_cancel_unavailable",
        )
    if str(canceled.get("orderId") or "") != str(order.od_id) or str(canceled.get("status") or "").upper() != "CANCELED":
        return api_error(
            "Toss did not confirm virtual account cancellation. The order was left unchanged.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="toss_vbank_cancel_unconfirmed",
        )
    return None


def toss_method_is_vbank(value):
    normalized = str(value or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    return normalized in {"virtualaccount", "가상계좌", "vbank"}


def save_toss_vbank_authorization(order, toss_payment):
    virtual_account = toss_payment.get("virtualAccount")
    secret = str(toss_payment.get("secret") or "")
    if not isinstance(virtual_account, dict) or not secret:
        return None, api_error(
            "Toss did not return the virtual account details required for deposit verification.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="toss_vbank_details_missing",
        )
    account_number = str(virtual_account.get("accountNumber") or "").strip()
    bank_code = str(virtual_account.get("bankCode") or "").strip()
    if not account_number or not bank_code:
        return None, api_error(
            "Toss returned incomplete virtual account details.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="toss_vbank_details_invalid",
        )
    secret_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    with transaction.atomic():
        locked = ShopOrder.objects.select_for_update().filter(pk=order.pk).first()
        if not locked or str(locked.od_status or "") in CANCELLED_STATUSES:
            return None, api_error(
                "Order cannot accept a virtual account payment.",
                status=drf_status.HTTP_409_CONFLICT,
                code="order_cancelled",
            )
        locked.od_pg = "toss"
        locked.od_tno = str(toss_payment.get("paymentKey") or "")[:255]
        locked.od_vbank_bank_code = bank_code[:10]
        locked.od_vbank_account = account_number[:20]
        locked.od_vbank_customer_name = str(virtual_account.get("customerName") or "")[:100]
        locked.od_vbank_due_date = str(virtual_account.get("dueDate") or "")[:40]
        locked.od_vbank_secret_hash = secret_hash
        locked.od_vbank_status = str(toss_payment.get("status") or "WAITING_FOR_DEPOSIT")[:32]
        locked.od_misu = locked.od_receipt_price
        locked.save(update_fields=[
            "od_pg", "od_tno", "od_vbank_bank_code", "od_vbank_account",
            "od_vbank_customer_name", "od_vbank_due_date", "od_vbank_secret_hash",
            "od_vbank_status", "od_misu",
        ])
        return locked, None


def confirm_toss_payment(data):
    order_id = payment_order_id(data)
    amount = payment_amount(data)
    payment_key_value = payment_key(data)
    if not payment_key_value:
        return None, api_error(
            "Toss payment key is required.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="toss_payment_key_required",
        )

    order = ShopOrder.objects.filter(pk=order_id).first()
    if not order:
        record_payment_raw_log(None, order_id, "toss", payment_key_value, data, prefix="toss-reject")
        return None, api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
    if str(order.od_status or "") in CANCELLED_STATUSES:
        record_payment_raw_log(order, order_id, "toss", payment_key_value, data, prefix="toss-reject")
        return None, api_error("Cancelled orders cannot be confirmed.", status=drf_status.HTTP_409_CONFLICT, code="order_cancelled")
    if amount != order.od_receipt_price:
        record_payment_raw_log(order, order_id, "toss", payment_key_value, data, prefix="toss-reject")
        return None, api_error(
            "Payment amount does not match the order amount.",
            status=drf_status.HTTP_409_CONFLICT,
            code="payment_amount_mismatch",
            details={"expected_amount": order.od_receipt_price, "received_amount": amount},
        )

    toss_payment, error = toss_api_confirm(payment_key_value, order_id, amount)
    if error:
        record_payment_raw_log(order, order_id, "toss", payment_key_value, data, prefix="toss-reject")
        return None, error

    if not isinstance(toss_payment, dict) or not toss_payment.get("orderId"):
        raw_data = {**data, "toss_payment": toss_payment}
        record_payment_raw_log(order, order_id, "toss", payment_key_value, raw_data, prefix="toss-reject")
        return None, api_error(
            "Toss payment authorization returned an invalid response.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="toss_payment_invalid_response",
        )

    if str(toss_payment.get("orderId")) != str(order.od_id):
        raw_data = {**data, "toss_payment": toss_payment}
        record_payment_raw_log(order, order_id, "toss", payment_key_value, raw_data, prefix="toss-reject")
        return None, api_error(
            "Toss payment order does not match the local order.",
            status=drf_status.HTTP_409_CONFLICT,
            code="toss_order_mismatch",
        )

    if str(toss_payment.get("paymentKey") or "") != payment_key_value:
        raw_data = {**data, "toss_payment": toss_payment}
        record_payment_raw_log(order, order_id, "toss", payment_key_value, raw_data, prefix="toss-reject")
        return None, api_error(
            "Toss payment key does not match the confirmation request.",
            status=drf_status.HTTP_409_CONFLICT,
            code="toss_payment_key_mismatch",
        )

    approved_amount = safe_amount_int(toss_payment.get("totalAmount", toss_payment.get("amount")), -1)
    approved_status = str(toss_payment.get("status") or "").upper()
    is_vbank_order = settle_case_is_vbank(order.od_settle_case)
    is_vbank_payment = toss_method_is_vbank(toss_payment.get("method"))
    if approved_amount != order.od_receipt_price:
        raw_data = {**data, "toss_payment": toss_payment}
        record_payment_raw_log(order, order_id, "toss", payment_key_value, raw_data, prefix="toss-reject")
        return None, api_error(
            "Toss approved amount does not match the order amount.",
            status=drf_status.HTTP_409_CONFLICT,
            code="toss_amount_mismatch",
            details={"expected_amount": order.od_receipt_price, "approved_amount": approved_amount},
        )
    if is_vbank_order != is_vbank_payment:
        raw_data = {**data, "toss_payment": toss_payment}
        record_payment_raw_log(order, order_id, "toss", payment_key_value, raw_data, prefix="toss-reject")
        return None, api_error(
            "Toss payment method does not match the order payment method.",
            status=drf_status.HTTP_409_CONFLICT,
            code="toss_payment_method_mismatch",
        )
    if approved_status == "WAITING_FOR_DEPOSIT":
        if not is_vbank_order:
            return None, api_error(
                "Only virtual account orders can wait for a deposit.",
                status=drf_status.HTTP_409_CONFLICT,
                code="toss_vbank_order_required",
            )
        pending_order, error = save_toss_vbank_authorization(order, toss_payment)
        raw_data = {**data, "toss_payment": toss_payment}
        record_payment_raw_log(pending_order or order, order_id, "toss", payment_key_value, raw_data, prefix="toss-pending")
        if error:
            return None, error
        return toss_payment, None
    if approved_status != "DONE":
        raw_data = {**data, "toss_payment": toss_payment}
        record_payment_raw_log(order, order_id, "toss", payment_key_value, raw_data, prefix="toss-pending")
        return None, api_error(
            "Toss payment is not completed.",
            status=drf_status.HTTP_409_CONFLICT,
            code="toss_payment_not_done",
            details={"provider_status": approved_status},
        )

    return toss_payment, None


def confirm_adapter_payment(provider, data):
    adapter_result, error = payment_adapter_request("confirm", provider, data)
    if error:
        record_payment_raw_log(
            None,
            payment_order_id(data),
            provider,
            payment_transaction_id(data),
            data,
            prefix="adapter-reject",
        )
        return None, None, None, None, error

    if not payment_adapter_success(adapter_result):
        raw_data = {**data, "payment_adapter": adapter_result}
        record_payment_raw_log(
            None,
            payment_order_id(data),
            provider,
            payment_transaction_id(data),
            raw_data,
            prefix="adapter-reject",
        )
        return None, None, None, None, api_error(
            "Payment adapter did not verify the payment.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="payment_adapter_not_verified",
            details={"provider": provider},
        )

    order_id = payment_order_id(adapter_result) or payment_order_id(data)
    # The verified amount has to come from the adapter; the client's figure proves nothing.
    amount = payment_amount(adapter_result)
    transaction_id = payment_transaction_id(adapter_result) or payment_transaction_id(data)
    raw_data = {**data, "payment_adapter": adapter_result}
    return order_id, amount, transaction_id, raw_data, None


def confirm_order_payment(order_id, amount, pg_service, transaction_id, raw_data, *, log_prefix="pay"):
    if not order_id:
        return None, api_error("Order id is required.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, code="order_id_required")
    with transaction.atomic():
        order = ShopOrder.objects.select_for_update().filter(pk=order_id).first()
        if not order:
            record_payment_raw_log(None, order_id, pg_service, transaction_id, raw_data, prefix=log_prefix)
            return None, api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
        if str(order.od_status or "") in CANCELLED_STATUSES:
            record_payment_raw_log(order, order_id, pg_service, transaction_id, raw_data, prefix=log_prefix)
            return None, api_error("Cancelled orders cannot be confirmed.", status=drf_status.HTTP_409_CONFLICT, code="order_cancelled")
        if amount != order.od_receipt_price:
            record_payment_raw_log(order, order_id, pg_service, transaction_id, raw_data, prefix=log_prefix)
            return None, api_error(
                "Payment amount does not match the order amount.",
                status=drf_status.HTTP_409_CONFLICT,
                code="payment_amount_mismatch",
                details={"expected_amount": order.od_receipt_price, "received_amount": amount},
            )
        if str(order.od_status or "") not in ORDERED_STATUSES:
            # Already paid, shipping or done: a repeated confirmation, webhook or callback must not
            # move the order (or its items) back to "paid".
            record_payment_raw_log(order, order_id, pg_service, transaction_id, raw_data, prefix=log_prefix)
            return order, None
        pg_service = str(pg_service or order.od_pg or "")
        order.od_status = ORDER_STATUS_PAID
        order.od_misu = 0
        order.od_pg = pg_service
        order.od_receipt_time = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S")
        update_fields = ["od_status", "od_misu", "od_pg", "od_tno", "od_receipt_time"]
        if settle_case_is_vbank(order.od_settle_case):
            order.od_vbank_status = "DONE"
            update_fields.append("od_vbank_status")
        if transaction_id:
            order.od_tno = transaction_id
        order.save(update_fields=update_fields)
        order.items.exclude(ct_status__in=CANCELLED_STATUSES).update(ct_status=ORDER_STATUS_PAID)
        for log in order.coupon_logs.select_related("coupon").all():
            if log.coupon_id:
                # an all-member coupon stays open for the other members (use is in the log)
                ShopCoupon.objects.filter(pk=log.cp_id, cp_all_members=False).update(cp_used="1")
        record_payment_raw_log(order, order_id, pg_service, transaction_id, raw_data, prefix=log_prefix)
    return order, None
