"""NICEPAY PG 인증결제 (MID / MerchantKey / AuthToken) server integration.

This module deliberately stays on the authentication-payment product described at
https://developers.nicepay.co.kr/docs/pg/auth/authorization.  It does not use the separate
NICEPAY clientId/secretKey API product.

The browser only receives an order amount, MID, EdiDate, SignData and a one-time attempt token.
The MerchantKey, AuthToken and approval/cancellation decisions stay server-side.  Authentication
success is never treated as payment success: the approval response signature, amount, MID, order
number, transaction id and method success code are all verified before an order becomes paid.
"""

import hashlib
import hmac
import http.client
import json
import logging
import secrets
import socket
import ssl
from datetime import timedelta
from http.client import HTTPSConnection
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, HttpResponseRedirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_http_methods
from rest_framework import status as drf_status

from gnu_jango.shop.models import ShopOrder, ShopPaymentAttempt
from gnu_jango.shop.notifications import (
    STATUS_PAID as MAIL_STATUS_PAID,
    queue_order_placed_mails,
    queue_order_status_mail,
)
from gnu_jango.shop.pg_settings import MODE_LABELS, effective_nicepay_keys, order_key_mode
from gnu_jango.shop.sms.notifications import (
    STATUS_PAID as SMS_STATUS_PAID,
    queue_order_placed_sms,
    queue_order_status_sms,
)
from gnu_jango.utils.lib import get_client_ip

from .response import api_error
from .shop_common import CANCELLED_STATUSES, ORDER_STATUS_PAID, ORDERED_STATUSES, PAID_STATUSES, safe_int
from .shop_payments import (
    PaymentCancelError,
    confirm_order_payment,
    payment_order_id,
    record_payment_raw_log,
    settle_case_is_bank,
    settle_case_is_vbank,
)

logger = logging.getLogger(__name__)

NICEPAY_SCRIPT_URL = "https://pg-web.nicepay.co.kr/v3/common/js/nicepay-pgweb.js"
NICEPAY_APPROVAL_URLS = {
    "dc1-api.nicepay.co.kr": "/webapi/pay_process.jsp",
    "dc2-api.nicepay.co.kr": "/webapi/pay_process.jsp",
    # The PAYU sample and older merchant guides use this host for the same authentication flow.
    "webapi.nicepay.co.kr": "/webapi/pay_process.jsp",
}
NICEPAY_NET_CANCEL_URLS = {
    "dc1-api.nicepay.co.kr": "/webapi/cancel_process.jsp",
    "dc2-api.nicepay.co.kr": "/webapi/cancel_process.jsp",
    "webapi.nicepay.co.kr": "/webapi/cancel_process.jsp",
}
# Fixed endpoints: the provider response only selects one of these constants. The request URL
# itself is never built from a host or path supplied by the response (CodeQL SSRF guard).
NICEPAY_APPROVAL_ENDPOINTS = {
    host: f"https://{host}{path}" for host, path in NICEPAY_APPROVAL_URLS.items()
}
NICEPAY_NET_CANCEL_ENDPOINTS = {
    host: f"https://{host}{path}" for host, path in NICEPAY_NET_CANCEL_URLS.items()
}
NICEPAY_CANCEL_URL = "https://pg-api.nicepay.co.kr/webapi/cancel_process.jsp"
NICEPAY_LOOKUP_URL = "https://webapi.nicepay.co.kr/webapi/inquery/trans_status.jsp"
NICEPAY_SUCCESS_CODES = {"CARD": "3001", "BANK": "4000", "VBANK": "4100", "CELLPHONE": "A000"}
NICEPAY_VBANK_DEPOSIT_CODE = "4110"
NICEPAY_CANCEL_SUCCESS_CODES = {"2001", "2211"}
NICEPAY_NET_CANCEL_SUCCESS_CODE = "2001"
NICEPAY_MAX_AMOUNT = 999_999_999_999
NICEPAY_ATTEMPT_TOKEN_PREFIX = "gnu-nicepay:"
NICEPAY_ATTEMPT_TOKEN_RE = 32
# libcurl/urllib must not follow a redirect from a provider URL; every redirect is treated as an
# invalid provider response instead of being resolved against an untrusted Location header.
NETWORK_ERRORS = (urllib_error.URLError, TimeoutError, socket.timeout, http.client.HTTPException, OSError)


class NicepayConfigError(Exception):
    """The shop has no usable NICEPAY credential pair for this payment."""


class NicepayTransportError(Exception):
    """The approval/lookup/cancel request did not produce a trustworthy response."""

    def __init__(self, message, *, kind="unavailable"):
        super().__init__(message)
        self.kind = kind


class NicepayKeyRotationError(PaymentCancelError):
    """The attempt was made with a credential pair that is no longer configured."""


def _now_edidate():
    return timezone.localtime().strftime("%Y%m%d%H%M%S")


def _amount_text(value):
    return str(max(0, safe_int(value, 0)))


def _amount_int(value):
    if isinstance(value, str):
        value = value.replace(",", "").strip()
    return safe_int(value, -1)


def nicepay_sign_data(*parts, merchant_key):
    """hex(sha256(concatenated parts + MerchantKey)); the caller supplies document order."""
    payload = "".join(str(part) for part in parts) + str(merchant_key or "")
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def nicepay_auth_signature(auth_token, mid, amt, merchant_key):
    return nicepay_sign_data(auth_token, mid, amt, merchant_key=merchant_key)


def nicepay_approval_signature(auth_token, mid, amt, edi_date, merchant_key):
    return nicepay_sign_data(auth_token, mid, amt, edi_date, merchant_key=merchant_key)


def nicepay_response_signature(tid, mid, amt, merchant_key):
    return nicepay_sign_data(tid, mid, amt, merchant_key=merchant_key)


def nicepay_cancel_signature(mid, cancel_amt, edi_date, merchant_key):
    return nicepay_sign_data(mid, cancel_amt, edi_date, merchant_key=merchant_key)


def nicepay_lookup_signature(tid, mid, edi_date, merchant_key):
    return nicepay_sign_data(tid, mid, edi_date, merchant_key=merchant_key)


def _signature_matches(received, expected):
    return bool(received) and hmac.compare_digest(
        str(received).strip().lower(), str(expected).strip().lower()
    )


def _allowed_url(value, allowed):
    if not value:
        return False
    try:
        parsed = urlsplit(str(value))
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    try:
        port = parsed.port
    except ValueError:
        return False
    if port not in (None, 443):
        return False
    if parsed.query or parsed.fragment:
        return False
    host = (parsed.hostname or "").lower()
    expected_path = allowed.get(host)
    return bool(expected_path and parsed.path == expected_path)


def nicepay_approval_url_allowed(value):
    return _allowed_url(value, NICEPAY_APPROVAL_URLS)


def nicepay_net_cancel_url_allowed(value):
    return _allowed_url(value, NICEPAY_NET_CANCEL_URLS)


def _canonical_endpoint(value, allowed_urls, endpoints):
    """Map a provider URL to one of our fixed endpoint constants, or "".

    The response may choose dc1/dc2/legacy webapi, but the actual request URL never contains a
    host or path copied from it.
    """
    if not _allowed_url(value, allowed_urls):
        return ""
    host = (urlsplit(str(value)).hostname or "").lower()
    return endpoints.get(host, "")


def _decode_response(raw):
    for encoding in ("utf-8-sig", "euc-kr", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _parse_provider_response(raw):
    text = _decode_response(raw).strip()
    if not text:
        return {}
    if text.startswith("{"):
        try:
            payload = json.loads(text)
            return payload if isinstance(payload, dict) else {}
        except ValueError:
            return {}
    # EdiType=JSON is the default, but tolerate the documented KV form without trusting it.
    payload = {}
    for key, value in urllib_parse.parse_qsl(text, keep_blank_values=True):
        payload[key] = value
    return payload


@sensitive_variables("payload", "body")
def _nicepay_post(url, payload, *, allowed_urls):
    if not _allowed_url(url, allowed_urls):
        raise NicepayTransportError("NICEPAY endpoint is not in the approved allow-list.", kind="url")
    try:
        body = urlencode({key: str(value) for key, value in payload.items()}, encoding="euc-kr").encode("ascii")
    except UnicodeEncodeError as exc:
        raise NicepayTransportError("NICEPAY request could not be encoded.", kind="encoding") from exc
    connect_timeout = max(
        1,
        min(safe_int(getattr(settings, "SHOP_NICEPAY_CONNECT_TIMEOUT", 10), 10), 60),
    )
    read_timeout = max(
        1,
        min(safe_int(getattr(settings, "SHOP_NICEPAY_READ_TIMEOUT", 20), 20), 60),
    )
    parsed_url = urlsplit(url)
    connection = HTTPSConnection(
        parsed_url.hostname,
        443,
        timeout=connect_timeout,
        context=ssl.create_default_context(),
    )
    try:
        connection.request(
            "POST",
            parsed_url.path,
            body=body,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=euc-kr",
                "Accept": "application/json",
                "User-Agent": "gnu-jango-nicepay/1.0",
            },
        )
        if connection.sock is not None:
            connection.sock.settimeout(read_timeout)
        response = connection.getresponse()
        raw = response.read()
        status = response.status
        if 300 <= status < 400:
            raise NicepayTransportError("NICEPAY returned a redirect.", kind="redirect")
        parsed = _parse_provider_response(raw)
        if parsed:
            return parsed, status
        if status >= 500:
            raise NicepayTransportError("NICEPAY returned an empty server error.", kind="server")
        raise NicepayTransportError("NICEPAY rejected the request without a response body.", kind="http")
    except NicepayTransportError:
        raise
    except NETWORK_ERRORS as exc:
        kind = "timeout" if isinstance(exc, (TimeoutError, socket.timeout)) else "network"
        logger.warning("NICEPAY request failed (%s): %s", kind, exc)
        raise NicepayTransportError("NICEPAY request failed.", kind=kind) from exc
    finally:
        connection.close()


def _keys_for_attempt(attempt):
    keys = effective_nicepay_keys(mode=attempt.mode)
    if not keys.enabled:
        raise NicepayKeyRotationError(
            f"NICEPAY {MODE_LABELS.get(attempt.mode, attempt.mode)} MID/MerchantKey가 설정되지 않았습니다."
        )
    if attempt.key_fingerprint and keys.key_fingerprint != attempt.key_fingerprint:
        raise NicepayKeyRotationError(
            "이 결제를 시작할 때 사용한 NICEPAY 키와 현재 키가 다릅니다. "
            "기존 키를 복원하거나 NICEPAY 상점관리자에서 거래 상태를 확인한 뒤 수동으로 처리하세요."
        )
    return keys


def _keys_for_order(order):
    keys = effective_nicepay_keys(mode=order_key_mode(order))
    if not keys.enabled:
        raise PaymentCancelError(
            f"NICEPAY {MODE_LABELS.get(keys.selected_mode, keys.selected_mode)} MID/MerchantKey가 설정되지 않았습니다."
        )
    attempt = order.payment_attempts.filter(provider="nicepay").order_by("-pk").first()
    if attempt and attempt.key_fingerprint and attempt.key_fingerprint != keys.key_fingerprint:
        raise PaymentCancelError(
            "이 결제를 시작할 때 사용한 NICEPAY 설정과 현재 MID/MerchantKey가 다릅니다. "
            "기존 키를 복원하거나 NICEPAY 상점관리자에서 취소하세요."
        )
    return keys


def _provider_data(payload):
    """A small, non-secret response snapshot for the attempt/admin screen."""
    if not isinstance(payload, dict):
        return ""
    keep = (
        "ResultCode",
        "ResultMsg",
        "TID",
        "Moid",
        "MID",
        "Amt",
        "PayMethod",
        "AuthCode",
        "AuthDate",
        "VbankBankCode",
        "VbankBankName",
        "VbankNum",
        "VbankExpDate",
        "VbankExpTime",
        "CancelAmt",
        "RemainAmt",
        "CancelNum",
        "CancelDate",
        "CancelTime",
        "Status",
    )
    return json.dumps({key: payload[key] for key in keep if key in payload}, ensure_ascii=False, default=str)


def _record_attempt_log(attempt, data, *, prefix="nicepay"):
    try:
        record_payment_raw_log(
            attempt.order,
            attempt.od_id,
            "nicepay",
            attempt.tid,
            data,
            prefix=prefix,
        )
    except Exception:  # noqa: BLE001 - a log write must not undo a provider answer
        logger.exception("order %s: could not record NICEPAY payment log", attempt.od_id)


def _mark_attempt(attempt, state, *, error="", provider_data=None, tid=None, next_app_url=None, net_cancel_url=None):
    fields = ["state", "last_error", "updated_at"]
    attempt.state = state
    attempt.last_error = str(error or "")[:4000]
    if provider_data is not None:
        attempt.provider_data = _provider_data(provider_data)
        fields.append("provider_data")
    if tid is not None:
        attempt.tid = str(tid or "")[:30]
        fields.append("tid")
    if next_app_url is not None:
        attempt.next_app_url = str(next_app_url or "")[:255]
        fields.append("next_app_url")
    if net_cancel_url is not None:
        attempt.net_cancel_url = str(net_cancel_url or "")[:255]
        fields.append("net_cancel_url")
    attempt.save(update_fields=fields)


def _attempt_token():
    token = secrets.token_urlsafe(NICEPAY_ATTEMPT_TOKEN_RE)
    return token, hashlib.sha256(token.encode("utf-8")).hexdigest()


def _attempt_context(attempt):
    return f"nicepay-attempt-{attempt.pk}"


@sensitive_variables("token")
def _seal_attempt_token(attempt, token):
    from gnu_jango.shop.sealed_values import seal

    return seal(token, salt="shop-nicepay-attempt", context=_attempt_context(attempt))


@sensitive_variables("token")
def _unseal_attempt_token(attempt):
    from gnu_jango.shop.sealed_values import unseal

    return unseal(attempt.auth_token_sealed, salt="shop-nicepay-attempt", context=_attempt_context(attempt))


def _attempt_token_from_data(data):
    explicit = str(data.get("attempt_token") or data.get("nicepay_attempt_token") or "").strip()
    if explicit:
        return explicit, ""
    reserved = str(data.get("ReqReserved") or data.get("req_reserved") or "").strip()
    if reserved.startswith(NICEPAY_ATTEMPT_TOKEN_PREFIX):
        parts = reserved.split(":", 2)
        if len(parts) == 3:
            return parts[2], parts[1]
    return "", ""


def _find_attempt(data):
    order_id = payment_order_id(data)
    token, attempt_id = _attempt_token_from_data(data)
    if not order_id:
        return None, "주문번호가 없습니다."
    queryset = ShopPaymentAttempt.objects.select_related("order").filter(
        od_id=str(order_id), provider="nicepay"
    )
    if attempt_id.isdigit():
        queryset = queryset.filter(pk=int(attempt_id))
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""
    for attempt in queryset.order_by("-pk")[:20]:
        if token_hash and hmac.compare_digest(attempt.attempt_token_hash, token_hash):
            return attempt, ""
    return None, "결제 시도 정보를 확인할 수 없습니다."


def _return_url(request=None):
    configured = str(getattr(settings, "SHOP_NICEPAY_RETURN_URL", "") or "").strip()
    if configured:
        return configured
    if request is not None:
        try:
            from django.urls import reverse

            return request.build_absolute_uri(reverse("api_v1:shop-payment-nicepay-return"))
        except Exception:  # noqa: BLE001 - the admin warning covers a missing configured URL
            pass
    return "/api/v1/shop/payment/nicepay/return"


def nicepay_success_url():
    configured = str(getattr(settings, "SHOP_NICEPAY_SUCCESS_URL", "") or "").strip()
    if configured:
        return configured
    frontend = str(getattr(settings, "SHOP_NICEPAY_FRONTEND_URL", "") or "").strip().rstrip("/")
    return f"{frontend}/shop/payment/success" if frontend else ""


def _timeout():
    return max(1, min(safe_int(getattr(settings, "SHOP_NICEPAY_READ_TIMEOUT", 20), 20), 60))


@sensitive_variables("keys", "token", "sign_data")
def create_nicepay_attempt(order, pay_method, *, request=None):
    """Create the server-side attempt and return the browser-safe payment-window fields."""
    keys = effective_nicepay_keys(mode=order_key_mode(order))
    if not keys.enabled:
        raise NicepayConfigError("NICEPAY MID/MerchantKey가 설정되지 않았습니다.")
    amount = safe_int(order.od_receipt_price, 0)
    if amount <= 0 or amount > NICEPAY_MAX_AMOUNT:
        raise NicepayConfigError("NICEPAY 결제금액이 올바르지 않습니다.")
    edi_date = _now_edidate()
    sign_data = nicepay_sign_data(edi_date, keys.mid, _amount_text(amount), merchant_key=keys.merchant_key)
    token, token_hash = _attempt_token()
    attempt = ShopPaymentAttempt.objects.create(
        order=order,
        od_id=order.od_id,
        provider="nicepay",
        mode=keys.selected_mode,
        mid=keys.mid,
        key_fingerprint=keys.key_fingerprint,
        amount=amount,
        pay_method=str(pay_method or "")[:10],
        attempt_token_hash=token_hash,
        state="prepared",
    )
    reserved = f"{NICEPAY_ATTEMPT_TOKEN_PREFIX}{attempt.pk}:{token}"
    extra = {
        "mid": keys.mid,
        "edi_date": edi_date,
        "sign_data": sign_data,
        "return_url": _return_url(request),
        "script_url": NICEPAY_SCRIPT_URL,
        "module_type": "mobile" if _is_mobile_request(request) else "pc",
        "attempt_token": token,
        "req_reserved": reserved,
        "pay_method": attempt.pay_method,
    }
    if settle_case_is_vbank(order.od_settle_case):
        # The official request accepts YYYYMMDD or YYYYMMDDHHMI. Two days is a safe default;
        # merchants that need another limit can set it in the checkout request after contract review.
        extra["vbank_exp_date"] = (timezone.localdate() + timedelta(days=2)).strftime("%Y%m%d")
    return attempt, extra


def _is_mobile_request(request):
    if request is None:
        return False
    ua = str(request.META.get("HTTP_USER_AGENT") or "")
    return any(value in ua.lower() for value in ("android", "iphone", "ipad", "ipod", "mobile"))


def _auth_error(attempt, message, *, code, status=drf_status.HTTP_400_BAD_REQUEST):
    _mark_attempt(attempt, "failed", error=message)
    _record_attempt_log(attempt, {"error": message, "failure_code": code}, prefix="nicepay-reject")
    return api_error(message, status=status, code=code)


def _validate_auth_response(attempt, data, keys):
    """Return an API error for invalid authentication data, or None."""
    auth_code = str(data.get("AuthResultCode") or "").strip()
    if auth_code != "0000":
        message = str(data.get("AuthResultMsg") or "NICEPAY 인증에 실패했습니다.")[:300]
        return _auth_error(attempt, message, code="nicepay_auth_failed")
    auth_token = str(data.get("AuthToken") or "").strip()
    tid = str(data.get("TxTid") or data.get("TID") or "").strip()
    mid = str(data.get("MID") or "").strip()
    moid = str(data.get("Moid") or data.get("MOID") or "").strip()
    amt = str(data.get("Amt") or "").strip()
    method = str(data.get("PayMethod") or "").strip().upper()
    next_url = str(data.get("NextAppURL") or "").strip()
    net_url = str(data.get("NetCancelURL") or "").strip()
    if not auth_token or not tid or not mid or not moid or not amt:
        return _auth_error(attempt, "NICEPAY 인증 응답의 필수값이 누락되었습니다.", code="nicepay_auth_incomplete")
    if mid != attempt.mid:
        return _auth_error(attempt, "NICEPAY MID가 결제 시도와 일치하지 않습니다.", code="nicepay_mid_mismatch")
    if moid != str(attempt.od_id):
        return _auth_error(attempt, "NICEPAY 주문번호가 일치하지 않습니다.", code="nicepay_order_mismatch")
    if _amount_int(amt) != attempt.amount:
        return _auth_error(
            attempt,
            "NICEPAY 인증 금액이 주문 금액과 일치하지 않습니다.",
            code="nicepay_amount_mismatch",
            status=drf_status.HTTP_409_CONFLICT,
        )
    if method and method != attempt.pay_method:
        return _auth_error(attempt, "NICEPAY 결제수단이 일치하지 않습니다.", code="nicepay_method_mismatch")
    expected = nicepay_auth_signature(auth_token, mid, amt, keys.merchant_key)
    if not _signature_matches(data.get("Signature"), expected):
        return _auth_error(attempt, "NICEPAY 인증 응답 서명이 올바르지 않습니다.", code="nicepay_auth_signature_invalid")
    if not nicepay_approval_url_allowed(next_url):
        return _auth_error(attempt, "NICEPAY 승인 URL이 허용 목록에 없습니다.", code="nicepay_approval_url_invalid")
    if net_url and not nicepay_net_cancel_url_allowed(net_url):
        return _auth_error(attempt, "NICEPAY 망취소 URL이 허용 목록에 없습니다.", code="nicepay_net_cancel_url_invalid")
    return None


def _approval_success_code(pay_method):
    return NICEPAY_SUCCESS_CODES.get(str(pay_method or "").upper(), "")


def _validate_approval_response(attempt, response, keys):
    if not isinstance(response, dict) or not response:
        return "NICEPAY 승인 응답이 비어 있습니다.", "nicepay_invalid_response"
    result_code = str(response.get("ResultCode") or "").strip()
    expected_code = _approval_success_code(attempt.pay_method)
    if not expected_code or result_code != expected_code:
        return (
            str(response.get("ResultMsg") or "NICEPAY 승인이 거절되었습니다.")[:300],
            "nicepay_payment_rejected",
        )
    if str(response.get("MID") or "").strip() != attempt.mid:
        return "NICEPAY 승인 응답의 MID가 일치하지 않습니다.", "nicepay_response_mid_mismatch"
    if str(response.get("Moid") or response.get("MOID") or "").strip() != str(attempt.od_id):
        return "NICEPAY 승인 응답의 주문번호가 일치하지 않습니다.", "nicepay_response_order_mismatch"
    response_tid = str(response.get("TID") or "").strip()
    if not response_tid or response_tid != attempt.tid:
        return "NICEPAY 승인 응답의 거래번호가 일치하지 않습니다.", "nicepay_response_tid_mismatch"
    if _amount_int(response.get("Amt")) != attempt.amount:
        return "NICEPAY 승인 응답의 금액이 주문 금액과 일치하지 않습니다.", "nicepay_response_amount_mismatch"
    method = str(response.get("PayMethod") or "").strip().upper()
    if method and method != attempt.pay_method:
        return "NICEPAY 승인 응답의 결제수단이 일치하지 않습니다.", "nicepay_response_method_mismatch"
    expected = nicepay_response_signature(
        response_tid,
        str(response.get("MID") or ""),
        str(response.get("Amt") or ""),
        keys.merchant_key,
    )
    if not _signature_matches(response.get("Signature"), expected):
        return "NICEPAY 승인 응답 서명이 올바르지 않습니다.", "nicepay_response_signature_invalid"
    return "", ""


def _approval_payload(attempt, keys, auth_token):
    edi_date = _now_edidate()
    amount = _amount_text(attempt.amount)
    return {
        "TID": attempt.tid,
        "AuthToken": auth_token,
        "MID": keys.mid,
        "Amt": amount,
        "EdiDate": edi_date,
        "SignData": nicepay_approval_signature(
            auth_token, keys.mid, amount, edi_date, keys.merchant_key
        ),
        "CharSet": "euc-kr",
        "EdiType": "JSON",
    }


def _net_cancel_payload(attempt, keys, auth_token):
    edi_date = _now_edidate()
    amount = _amount_text(attempt.amount)
    return {
        "TID": attempt.tid,
        "AuthToken": auth_token,
        "MID": keys.mid,
        "Amt": amount,
        "EdiDate": edi_date,
        "NetCancel": "1",
        "SignData": nicepay_approval_signature(
            auth_token, keys.mid, amount, edi_date, keys.merchant_key
        ),
        "CharSet": "euc-kr",
        "EdiType": "JSON",
    }


def _validate_cancel_response(order, response, keys, amount):
    if not isinstance(response, dict) or not response:
        return "NICEPAY 취소 응답이 비어 있습니다.", "nicepay_cancel_invalid_response"
    if str(response.get("ResultCode") or "").strip() not in NICEPAY_CANCEL_SUCCESS_CODES:
        return (
            str(response.get("ResultMsg") or response.get("ErrorMsg") or "NICEPAY 취소가 거절되었습니다.")[:300],
            "nicepay_cancel_rejected",
        )
    if str(response.get("TID") or "").strip() != str(order.od_tno or ""):
        return "NICEPAY 취소 응답의 거래번호가 일치하지 않습니다.", "nicepay_cancel_tid_mismatch"
    if str(response.get("MID") or "").strip() != keys.mid:
        return "NICEPAY 취소 응답의 MID가 일치하지 않습니다.", "nicepay_cancel_mid_mismatch"
    if _amount_int(response.get("CancelAmt")) != int(amount):
        return "NICEPAY 취소 응답의 금액이 일치하지 않습니다.", "nicepay_cancel_amount_mismatch"
    expected = nicepay_response_signature(
        str(response.get("TID") or ""),
        str(response.get("MID") or ""),
        str(response.get("CancelAmt") or ""),
        keys.merchant_key,
    )
    if not _signature_matches(response.get("Signature"), expected):
        return "NICEPAY 취소 응답 서명이 올바르지 않습니다.", "nicepay_cancel_signature_invalid"
    return "", ""


@sensitive_variables("attempt", "response", "keys")
def _save_vbank_authorization(attempt, response):
    """Persist the issued virtual account without marking the order paid."""
    order = attempt.order
    bank_code = str(response.get("VbankBankCode") or "").strip()[:10]
    account_number = str(response.get("VbankNum") or "").strip()[:20]
    if not bank_code or not account_number:
        return api_error(
            "NICEPAY가 가상계좌 정보를 반환하지 않았습니다.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="nicepay_vbank_details_missing",
        )
    with transaction.atomic():
        locked = ShopOrder.objects.select_for_update().filter(pk=order.pk).first()
        if locked is None:
            return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
        if str(locked.od_status or "") in CANCELLED_STATUSES:
            return api_error(
                "취소된 주문에는 가상계좌를 발급할 수 없습니다.",
                status=drf_status.HTTP_409_CONFLICT,
                code="order_cancelled",
            )
        newly_issued = str(locked.od_tno or "") != attempt.tid
        locked.od_pg = "nicepay"
        locked.od_tno = attempt.tid[:255]
        locked.od_vbank_bank_code = bank_code
        locked.od_vbank_account = account_number
        locked.od_vbank_customer_name = str(response.get("VbankBankName") or "")[:100]
        locked.od_vbank_due_date = (
            f"{response.get('VbankExpDate', '')}{response.get('VbankExpTime', '')}"[:40]
        )
        locked.od_vbank_secret_hash = ""
        locked.od_vbank_status = "WAITING_FOR_DEPOSIT"
        locked.od_misu = attempt.amount
        locked.save(update_fields=[
            "od_pg", "od_tno", "od_vbank_bank_code", "od_vbank_account",
            "od_vbank_customer_name", "od_vbank_due_date", "od_vbank_secret_hash",
            "od_vbank_status", "od_misu",
        ])
        if newly_issued:
            queue_order_placed_mails(locked)
            queue_order_placed_sms(locked)
    _mark_attempt(attempt, "pending_deposit", provider_data=response)
    return None


def _apply_approved_payment(attempt, response):
    """Apply a verified approval to the local order, safely if the provider already charged."""
    attempt.order.refresh_from_db()
    if str(attempt.order.od_status or "") in CANCELLED_STATUSES:
        # The customer/admin cancelled while the approval request was in flight. The card may
        # already be charged, so close the NICEPAY transaction before leaving the order unpaid.
        _mark_attempt(attempt, "uncertain", provider_data=response,
                      error="Order was cancelled while NICEPAY approval was in flight.")
        _net_cancel_attempt(attempt, "order cancelled during approval")
        return api_error(
            "주문이 취소되어 NICEPAY 승인을 반영하지 않았습니다. 망취소 결과를 관리자가 확인해야 합니다.",
            status=drf_status.HTTP_409_CONFLICT,
            code="order_cancelled_during_approval",
        )
    if attempt.state == "approved_local_failed":
        # A previous attempt got the approval but the local write failed. The response is stored
        # on the attempt, so a retry only repeats the local, idempotent order transition.
        if not attempt.provider_data:
            return api_error(
                "NICEPAY 승인은 완료됐지만 주문 저장 정보가 없습니다. 관리자에게 문의하세요.",
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="nicepay_local_recovery_required",
            )
        try:
            response = json.loads(attempt.provider_data)
        except ValueError:
            return api_error(
                "NICEPAY 승인은 완료됐지만 주문 저장 정보를 읽지 못했습니다. 관리자에게 문의하세요.",
                status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
                code="nicepay_local_recovery_required",
            )
    if settle_case_is_vbank(attempt.order.od_settle_case):
        error = _save_vbank_authorization(attempt, response)
        if error is None:
            _record_attempt_log(attempt, {"nicepay_payment": response}, prefix="nicepay-vbank")
        return error
    try:
        order, error = confirm_order_payment(
            attempt.od_id,
            attempt.amount,
            "nicepay",
            attempt.tid,
            {"nicepay_payment": response, "nicepay_attempt_id": attempt.pk},
            log_prefix="nicepay",
        )
    except Exception:  # noqa: BLE001 - the provider charged already; preserve a recoverable state
        logger.exception("order %s: NICEPAY approved but the local order update failed", attempt.od_id)
        _mark_attempt(attempt, "approved_local_failed", provider_data=response,
                      error="NICEPAY approved but the local order update failed.")
        return api_error(
            "NICEPAY 승인은 완료됐지만 주문 저장에 실패했습니다. 관리자에게 문의하세요.",
            status=drf_status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="nicepay_local_save_failed",
        )
    if error:
        error_data = getattr(error, "data", {}) if isinstance(getattr(error, "data", {}), dict) else {}
        if str(error_data.get("code") or "") in {"order_cancelled", "payment_amount_mismatch"}:
            _mark_attempt(attempt, "uncertain", provider_data=response,
                          error=str(error_data.get("message") or "local payment rejected"))
            _net_cancel_attempt(attempt, "local payment rejected after approval")
            return error
        _mark_attempt(attempt, "approved_local_failed", provider_data=response,
                      error=str(error_data.get("message") or "local save failed"))
        return error
    _mark_attempt(attempt, "approved", provider_data=response)
    return None


def _net_cancel_attempt(attempt, reason="approval result unknown"):
    """망취소 after an approval timeout/ambiguous response. Returns (answer, error message)."""
    try:
        keys = _keys_for_attempt(attempt)
        auth_token = _unseal_attempt_token(attempt)
        if not auth_token or not attempt.net_cancel_url:
            _mark_attempt(attempt, "uncertain", error="NICEPAY net-cancel data is incomplete.")
            return None, "NICEPAY 망취소에 필요한 인증 정보가 없습니다."
        endpoint = _canonical_endpoint(
            attempt.net_cancel_url, NICEPAY_NET_CANCEL_URLS, NICEPAY_NET_CANCEL_ENDPOINTS
        )
        if not endpoint:
            _mark_attempt(attempt, "uncertain", error="NICEPAY net-cancel URL is not allowed.")
            return None, "NICEPAY 망취소 URL이 허용 목록에 없습니다."
        response, status = _nicepay_post(
            endpoint,
            _net_cancel_payload(attempt, keys, auth_token),
            allowed_urls=NICEPAY_NET_CANCEL_URLS,
        )
        if str(response.get("ResultCode") or "").strip() != NICEPAY_NET_CANCEL_SUCCESS_CODE:
            _mark_attempt(attempt, "uncertain", provider_data=response,
                          error=str(response.get("ResultMsg") or "NICEPAY net-cancel was rejected."))
            _record_attempt_log(attempt, {"nicepay_net_cancel": response}, prefix="nicepay-net-cancel-reject")
            return response, "NICEPAY 망취소가 확인되지 않았습니다."
        expected = nicepay_response_signature(
            str(response.get("TID") or ""),
            str(response.get("MID") or ""),
            str(response.get("CancelAmt") or ""),
            keys.merchant_key,
        )
        if (
            str(response.get("TID") or "") != attempt.tid
            or str(response.get("MID") or "") != keys.mid
            or _amount_int(response.get("CancelAmt")) != attempt.amount
            or not _signature_matches(response.get("Signature"), expected)
        ):
            _mark_attempt(attempt, "uncertain", provider_data=response,
                          error="NICEPAY net-cancel response did not match the attempt.")
            _record_attempt_log(attempt, {"nicepay_net_cancel": response}, prefix="nicepay-net-cancel-mismatch")
            return response, "NICEPAY 망취소 응답이 결제 시도와 일치하지 않습니다."
        _mark_attempt(attempt, "net_canceled", provider_data=response)
        _record_attempt_log(attempt, {"nicepay_net_cancel": response, "reason": reason}, prefix="nicepay-net-cancel")
        return response, ""
    except (NicepayTransportError, PaymentCancelError) as exc:
        _mark_attempt(attempt, "uncertain", error=str(exc))
        _record_attempt_log(attempt, {"net_cancel_error": str(exc)}, prefix="nicepay-net-cancel-failed")
        return None, str(exc)


@sensitive_variables("attempt", "data", "keys", "response", "auth_token")
def confirm_nicepay_payment(data):
    """Verify an authentication response and perform the server-side approval once.

    Returns ``(attempt, error)``. The caller must use ``attempt.state`` for the response; the
    order is not marked paid until the approval response has passed every check.
    """
    attempt, reason = _find_attempt(data)
    if attempt is None:
        record_payment_raw_log(
            None, payment_order_id(data), "nicepay", str(data.get("TxTid") or data.get("TID") or ""),
            data, prefix="nicepay-reject",
        )
        return None, api_error(reason, status=drf_status.HTTP_404_NOT_FOUND, code="nicepay_attempt_not_found")
    if attempt.state in {"approved", "pending_deposit"}:
        # A replayed confirmation / browser retry: do not call the approval API again.
        order = attempt.order
        if str(order.od_status or "") in CANCELLED_STATUSES:
            return None, api_error("CANCELLED orders cannot be confirmed.", status=drf_status.HTTP_409_CONFLICT,
                                   code="order_cancelled")
        return attempt, None
    if attempt.state in {"approving", "uncertain", "net_canceled", "canceled", "failed"}:
        return None, api_error(
            "이 NICEPAY 결제는 이미 처리 중이거나 종료되었습니다. 주문 상태를 확인하세요.",
            status=drf_status.HTTP_409_CONFLICT,
            code=f"nicepay_attempt_{attempt.state}",
        )
    if str(attempt.order.od_status or "") in CANCELLED_STATUSES:
        _mark_attempt(attempt, "failed", error="Order was cancelled before approval.")
        return None, api_error("Cancelled orders cannot be confirmed.", status=drf_status.HTTP_409_CONFLICT,
                               code="order_cancelled")
    try:
        keys = _keys_for_attempt(attempt)
    except PaymentCancelError as exc:
        _mark_attempt(attempt, "failed", error=str(exc))
        return None, api_error(str(exc), status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
                               code="nicepay_payment_unconfigured")
    error = _validate_auth_response(attempt, data, keys)
    if error:
        return None, error
    auth_token = str(data.get("AuthToken") or "").strip()
    with transaction.atomic():
        locked = ShopPaymentAttempt.objects.select_for_update().select_related("order").get(pk=attempt.pk)
        if locked.state in {"approved", "pending_deposit"}:
            return locked, None
        if locked.state not in {"prepared", "authenticated"}:
            return None, api_error(
                "NICEPAY 승인 요청이 이미 진행 중입니다.",
                status=drf_status.HTTP_409_CONFLICT,
                code="nicepay_approval_in_progress",
            )
        locked.state = "approving"
        locked.tid = str(data.get("TxTid") or data.get("TID") or "")[:30]
        locked.auth_token_sealed = _seal_attempt_token(locked, auth_token)
        locked.next_app_url = str(data.get("NextAppURL") or "")[:255]
        locked.net_cancel_url = str(data.get("NetCancelURL") or "")[:255]
        locked.last_error = ""
        locked.save(update_fields=[
            "state", "tid", "auth_token_sealed", "next_app_url", "net_cancel_url", "last_error", "updated_at"
        ])
        attempt = locked

    endpoint = _canonical_endpoint(
        attempt.next_app_url, NICEPAY_APPROVAL_URLS, NICEPAY_APPROVAL_ENDPOINTS
    )
    if not endpoint:
        _mark_attempt(attempt, "failed", error="NICEPAY approval URL is not allowed.")
        _record_attempt_log(attempt, {"error": "approval URL not allowed"}, prefix="nicepay-reject")
        return None, api_error(
            "NICEPAY 승인 URL이 허용 목록에 없습니다.",
            status=drf_status.HTTP_400_BAD_REQUEST,
            code="nicepay_approval_url_invalid",
        )
    try:
        response, response_status = _nicepay_post(
            endpoint,
            _approval_payload(attempt, keys, auth_token),
            allowed_urls=NICEPAY_APPROVAL_URLS,
        )
    except NicepayTransportError as exc:
        logger.warning("order %s: NICEPAY approval result is unknown (%s)", attempt.od_id, exc.kind)
        _mark_attempt(attempt, "uncertain", error=f"NICEPAY approval result unknown: {exc.kind}")
        _record_attempt_log(attempt, {"approval_transport_error": exc.kind}, prefix="nicepay-unknown")
        _, net_cancel_error = _net_cancel_attempt(attempt, "approval response was not received")
        if not net_cancel_error:
            return None, api_error(
                "NICEPAY 승인 응답을 받지 못해 망취소를 요청했습니다. 주문은 결제 전 상태입니다.",
                status=drf_status.HTTP_502_BAD_GATEWAY,
                code="nicepay_result_unknown_net_canceled",
            )
        return None, api_error(
            "NICEPAY 승인 결과를 확인할 수 없습니다. 주문은 결제 전 상태이며 관리자 확인이 필요합니다.",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="nicepay_result_unknown",
        )

    error_message, error_code = _validate_approval_response(attempt, response, keys)
    if error_message:
        # A syntactically valid but invalid/unsigned response may mean the provider charged
        # something we cannot prove. Keep the attempt recoverable and try the official 망취소.
        if error_code in {
            "nicepay_invalid_response",
            "nicepay_response_mid_mismatch",
            "nicepay_response_order_mismatch",
            "nicepay_response_tid_mismatch",
            "nicepay_response_amount_mismatch",
            "nicepay_response_method_mismatch",
            "nicepay_response_signature_invalid",
        } or response_status >= 500:
            _mark_attempt(attempt, "uncertain", provider_data=response, error=error_message)
            _record_attempt_log(attempt, {"nicepay_approval": response}, prefix="nicepay-unknown")
            _net_cancel_attempt(attempt, "approval response failed verification")
            return None, api_error(
                "NICEPAY 승인 응답을 검증하지 못했습니다. 주문은 결제 전 상태이며 관리자 확인이 필요합니다.",
                status=drf_status.HTTP_502_BAD_GATEWAY,
                code="nicepay_approval_unverified",
            )
        _mark_attempt(attempt, "failed", provider_data=response, error=error_message)
        _record_attempt_log(attempt, {"nicepay_approval": response}, prefix="nicepay-reject")
        return None, api_error(
            error_message,
            status=drf_status.HTTP_400_BAD_REQUEST,
            code=error_code,
        )

    local_error = _apply_approved_payment(attempt, response)
    if local_error:
        return None, local_error
    attempt.refresh_from_db()
    return attempt, None


@sensitive_variables("order", "response", "keys", "reason")
def nicepay_cancel_payment(order, reason, *, amount=None, partial=None, refund_account=None):
    """Cancel an approved NICEPAY payment (full or partial).

    ``refund_account`` must contain ``account_no``, ``bank_code`` and ``holder`` for a virtual
    account that already received a deposit.  Without it the cancellation is refused rather than
    pretending the refund succeeded.
    """
    if str(order.od_pg or "").strip().lower() != "nicepay" or not str(order.od_tno or "").strip():
        raise PaymentCancelError("NICEPAY 거래번호가 없어 취소할 수 없습니다.")
    if settle_case_is_vbank(order.od_settle_case) and str(order.od_vbank_status or "").upper() == "DONE":
        if not refund_account:
            raise PaymentCancelError("입금된 가상계좌는 환불 계좌번호·은행코드·예금주가 필요합니다.")
    keys = _keys_for_order(order)
    total = max(0, safe_int(order.od_receipt_price, 0))
    cancel_amount = total if amount is None else max(0, safe_int(amount, 0))
    if cancel_amount <= 0 or cancel_amount > total:
        raise PaymentCancelError("NICEPAY 취소 금액이 올바르지 않습니다.")
    is_partial = bool(partial) if partial is not None else cancel_amount < total
    cancellation_id = f"{order.od_id}-C{timezone.localtime():%y%m%d%H%M%S}{secrets.token_hex(2)}"[:64]
    edi_date = _now_edidate()
    payload = {
        "TID": str(order.od_tno),
        "MID": keys.mid,
        "Moid": cancellation_id,
        "CancelAmt": _amount_text(cancel_amount),
        "CancelMsg": (str(reason or "").strip() or "쇼핑몰 취소")[:100],
        "PartialCancelCode": "1" if is_partial else "0",
        "EdiDate": edi_date,
        "SignData": nicepay_cancel_signature(keys.mid, _amount_text(cancel_amount), edi_date, keys.merchant_key),
        "CharSet": "euc-kr",
        "EdiType": "JSON",
    }
    if refund_account:
        account_no = str(refund_account.get("account_no") or "").strip()
        bank_code = str(refund_account.get("bank_code") or "").strip()
        holder = str(refund_account.get("holder") or "").strip()
        if not (account_no and bank_code and holder):
            raise PaymentCancelError("가상계좌 환불 계좌 정보가 완전하지 않습니다.")
        payload.update({"RefundAcctNo": account_no[:16], "RefundBankCd": bank_code[:3], "RefundAcctNm": holder[:10]})
    try:
        response, _ = _nicepay_post(NICEPAY_CANCEL_URL, payload, allowed_urls={
            "pg-api.nicepay.co.kr": "/webapi/cancel_process.jsp",
        })
    except NicepayTransportError as exc:
        _record_attempt_log_for_order(order, {"cancel_request": payload, "transport_error": exc.kind},
                                      prefix="nicepay-cancel-unknown")
        raise PaymentCancelError(
            "NICEPAY 취소 결과를 확인할 수 없습니다. NICEPAY 상점관리자에서 거래 상태를 확인하세요."
        ) from exc
    error_message, error_code = _validate_cancel_response(order, response, keys, cancel_amount)
    if error_message:
        _record_attempt_log_for_order(order, {"nicepay_cancel": response}, prefix="nicepay-cancel-reject")
        raise PaymentCancelError(error_message) from None
    _record_attempt_log_for_order(
        order,
        {"nicepay_cancel": response, "requested_amount": cancel_amount, "partial": is_partial},
        prefix="nicepay-cancel",
    )
    return response


def _record_attempt_log_for_order(order, data, *, prefix="nicepay-cancel"):
    try:
        record_payment_raw_log(
            order,
            order.od_id,
            "nicepay",
            str(order.od_tno or ""),
            data,
            prefix=prefix,
        )
    except Exception:  # noqa: BLE001
        logger.exception("order %s: could not record NICEPAY cancel log", order.od_id)


def nicepay_api_cancel_payment(order, reason):
    return nicepay_cancel_payment(order, reason, amount=safe_int(order.od_receipt_price, 0), partial=False)


def nicepay_api_partial_cancel_payment(order, amount, reason, *, idempotency_key=None, tax_free_amount=0):
    # NICEPAY does not take an idempotency key. The caller's local plan keeps the same amount and
    # line set; a retry after a lost answer must be reconciled from the transaction/cancel logs.
    return nicepay_cancel_payment(order, reason, amount=amount, partial=True)


def cancel_pending_nicepay_vbank(order, reason):
    """Close an issued virtual account that has not received a deposit. None on success/not needed."""
    if str(order.od_pg or "").strip().lower() != "nicepay" or not settle_case_is_vbank(order.od_settle_case):
        return None
    if not order.od_tno or str(order.od_vbank_status or "").upper() == "DONE":
        return None
    try:
        nicepay_cancel_payment(order, reason, amount=safe_int(order.od_receipt_price, 0), partial=False)
    except PaymentCancelError as exc:
        return api_error(
            f"NICEPAY 가상계좌를 취소하지 못했습니다. {exc}",
            status=drf_status.HTTP_502_BAD_GATEWAY,
            code="nicepay_vbank_cancel_failed",
        )
    return None


def order_paid_through_nicepay(order):
    """A card / transfer / phone NICEPAY payment that can be refunded with the cancel API."""
    return (
        str(order.od_pg or "").strip().lower() == "nicepay"
        and bool(str(order.od_tno or "").strip())
        and not settle_case_is_bank(order.od_settle_case)
        and not settle_case_is_vbank(order.od_settle_case)
    )


def _lookup_transaction(tid, mode=None):
    keys = effective_nicepay_keys(mode=mode)
    if not keys.enabled:
        raise PaymentCancelError("NICEPAY MID/MerchantKey가 설정되지 않았습니다.")
    edi_date = _now_edidate()
    payload = {
        "TID": str(tid or ""),
        "MID": keys.mid,
        "EdiDate": edi_date,
        "SignData": nicepay_lookup_signature(str(tid or ""), keys.mid, edi_date, keys.merchant_key),
        "CharSet": "euc-kr",
        "EdiType": "JSON",
    }
    try:
        response, _ = _nicepay_post(NICEPAY_LOOKUP_URL, payload, allowed_urls={
            "webapi.nicepay.co.kr": "/webapi/inquery/trans_status.jsp",
        })
    except NicepayTransportError as exc:
        raise PaymentCancelError("NICEPAY 거래 조회에 실패했습니다.") from exc
    if str(response.get("ResultCode") or "").strip() != "0000":
        raise PaymentCancelError(
            str(response.get("ResultMsg") or "NICEPAY 거래 조회에 실패했습니다.")[:300]
        )
    if str(response.get("TID") or "").strip() != str(tid or ""):
        raise PaymentCancelError("NICEPAY 거래 조회 응답의 거래번호가 일치하지 않습니다.")
    return response


def recover_nicepay_attempt(attempt):
    """Reconcile an uncertain/approved-but-unsaved attempt against the lookup API.

    Returns ``(attempt, error)``. It never approves again: the transaction lookup is the only
    source of truth, so an unknown or missing transaction stays for admin review.
    """
    attempt.refresh_from_db()
    if attempt.state == "approved_local_failed":
        error = _apply_approved_payment(attempt, {})
        attempt.refresh_from_db()
        return attempt, error
    if not attempt.tid:
        return attempt, api_error(
            "NICEPAY 거래번호가 없어 조회할 수 없습니다.",
            status=drf_status.HTTP_409_CONFLICT,
            code="nicepay_tid_missing",
        )
    try:
        lookup = _lookup_transaction(attempt.tid, attempt.mode)
    except PaymentCancelError as exc:
        return attempt, api_error(str(exc), status=drf_status.HTTP_502_BAD_GATEWAY,
                                  code="nicepay_lookup_failed")
    status = str(lookup.get("Status") or "").strip()
    if status == "0":
        if attempt.state == "pending_deposit":
            return attempt, None
        # Approved at NICEPAY. Apply the local payment once.
        attempt.provider_data = attempt.provider_data or json.dumps(lookup, ensure_ascii=False)
        error = _apply_approved_payment(attempt, lookup)
        attempt.refresh_from_db()
        return attempt, error
    if status == "1":
        _mark_attempt(attempt, "canceled", provider_data=lookup)
        return attempt, None
    if status == "9":
        _mark_attempt(attempt, "failed", provider_data=lookup, error="NICEPAY transaction not found.")
        return attempt, api_error(
            "NICEPAY에 승인 거래가 없습니다.",
            status=drf_status.HTTP_409_CONFLICT,
            code="nicepay_transaction_not_found",
        )
    return attempt, api_error("NICEPAY 거래 상태를 확인할 수 없습니다.",
                              status=drf_status.HTTP_502_BAD_GATEWAY,
                              code="nicepay_lookup_unknown")


@sensitive_variables("data", "attempt")
def process_nicepay_vbank_notification(data):
    """Verify a 결제통보 against the transaction lookup API, then mark the order paid once."""
    order_id = str(data.get("MOID") or data.get("Moid") or "").strip()
    tid = str(data.get("TID") or "").strip()
    mid = str(data.get("MID") or "").strip()
    amount = _amount_int(data.get("Amt"))
    if not order_id or not tid or not mid:
        return api_error("Invalid NICEPAY virtual account notification.",
                         status=drf_status.HTTP_400_BAD_REQUEST,
                         code="nicepay_vbank_notification_invalid")
    order = ShopOrder.objects.filter(pk=order_id, od_pg="nicepay").first()
    if order is None:
        return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
    attempt = order.payment_attempts.filter(provider="nicepay", tid=tid).order_by("-pk").first()
    if attempt is None:
        return api_error("NICEPAY payment attempt not found.", status=drf_status.HTTP_404_NOT_FOUND,
                         code="nicepay_attempt_not_found")
    if mid != attempt.mid or amount != attempt.amount:
        record_payment_raw_log(order, order_id, "nicepay-vbank", tid, data, prefix="nicepay-vbank-mismatch")
        return api_error("NICEPAY notification does not match the order.", status=drf_status.HTTP_409_CONFLICT,
                         code="nicepay_vbank_notification_mismatch")
    # Never trust the notification's ResultCode/StateCd: ask the PG. A network failure returns 503
    # so NICEPAY retries instead of leaving the order silently unpaid.
    try:
        lookup = _lookup_transaction(tid, attempt.mode)
    except PaymentCancelError as exc:
        record_payment_raw_log(order, order_id, "nicepay-vbank", tid, data, prefix="nicepay-vbank-retry")
        return api_error(str(exc), status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
                         code="nicepay_vbank_lookup_unavailable")
    status = str(lookup.get("Status") or "").strip()
    raw = {"notification": data, "lookup": lookup}
    if status == "1":
        _mark_attempt(attempt, "canceled", provider_data=lookup)
        if str(order.od_status or "") not in CANCELLED_STATUSES and str(order.od_status or "") not in PAID_STATUSES:
            try:
                from .v1_shop import cancel_order_and_refund_benefits

                cancel_order_and_refund_benefits(
                    order, "NICEPAY 가상계좌 취소 통보", history="NICEPAY 가상계좌 취소 통보"
                )
            except Exception:  # noqa: BLE001 - the payment log still records the provider state
                logger.exception("order %s: NICEPAY vbank cancellation could not cancel locally", order_id)
        record_payment_raw_log(order, order_id, "nicepay-vbank", tid, raw, prefix="nicepay-vbank-canceled")
        return None
    if status != "0":
        record_payment_raw_log(order, order_id, "nicepay-vbank", tid, raw, prefix="nicepay-vbank-not-found")
        return None
    if str(order.od_status or "") in CANCELLED_STATUSES:
        record_payment_raw_log(order, order_id, "nicepay-vbank", tid, raw, prefix="nicepay-vbank-late-paid")
        return None
    if str(order.od_status or "") in PAID_STATUSES:
        return None
    paid_order, error = confirm_order_payment(
        order.pk,
        attempt.amount,
        "nicepay",
        tid,
        {"nicepay_vbank_notification": data, "nicepay_lookup": lookup},
        log_prefix="nicepay-vbank",
    )
    if error:
        return error
    paid_order.refresh_from_db()
    paid_order.od_vbank_status = "DONE"
    paid_order._change_reason = "NICEPAY vbank deposit confirmed"
    paid_order.save(update_fields=["od_vbank_status"])
    _mark_attempt(attempt, "approved", provider_data=lookup)
    queue_order_status_mail(paid_order, MAIL_STATUS_PAID)
    queue_order_status_sms(paid_order, SMS_STATUS_PAID)
    record_payment_raw_log(paid_order, order_id, "nicepay-vbank", tid, raw, prefix="nicepay-vbank")
    return None


def _notify_allowed(request):
    configured = str(getattr(settings, "SHOP_NICEPAY_VBANK_NOTIFY_ALLOWED_IPS", "") or "").strip()
    if not configured:
        return True
    allowed = {value.strip() for value in configured.replace(";", ",").split(",") if value.strip()}
    return get_client_ip(request) in allowed


@csrf_exempt
@require_http_methods(["POST"])
def nicepay_vbank_notification_view(request):
    """NICEPAY 가상계좌 입금통보 endpoint. It always reconciles with 거래조회 first."""
    if not _notify_allowed(request):
        return HttpResponse("FORBIDDEN", status=403, content_type="text/plain; charset=utf-8")
    data = {key: value for key, value in request.POST.items()}
    error = process_nicepay_vbank_notification(data)
    if error:
        # A provider retry is desirable for a temporary lookup failure; a permanent mismatch is
        # still acknowledged so NICEPAY does not hammer the shop, but the payment log has it.
        status = int(getattr(error, "status_code", 400) or 400)
        if status >= 500:
            return HttpResponse("RETRY", status=503, content_type="text/plain; charset=utf-8")
        return HttpResponse("FAIL", status=status, content_type="text/plain; charset=utf-8")
    return HttpResponse("OK", content_type="text/plain; charset=utf-8")


def _redirect_success(request, *, order=None, status="error", message=""):
    base = nicepay_success_url()
    if not base:
        base = request.build_absolute_uri("/shop/payment/success")
    params = {"pg": "nicepay", "payment_status": status, "nicepay": "1"}
    if order is not None:
        params["order_id"] = order.od_id
        params["amount"] = str(max(0, safe_int(order.od_receipt_price, 0)))
        if not order.user_id:
            params["uid"] = order.uid
    if message:
        params["message"] = str(message)[:200]
    separator = "&" if "?" in base else "?"
    return HttpResponseRedirect(f"{base}{separator}{urlencode(params)}")


@csrf_exempt
@require_http_methods(["POST"])
def nicepay_return_view(request):
    """Mobile/PC ReturnURL receiver: approve server-side, then redirect to the Next.js result page."""
    data = {key: value for key, value in request.POST.items()}
    attempt, error = confirm_nicepay_payment(data)
    if error:
        message = str(getattr(error, "data", {}).get("message") or "NICEPAY 결제 승인에 실패했습니다.")
        return _redirect_success(request, status="error", message=message)
    if attempt.state == "pending_deposit":
        return _redirect_success(
            request, order=attempt.order, status="pending", message="가상계좌가 발급되었습니다."
        )
    return _redirect_success(request, order=attempt.order, status="paid", message="결제가 완료되었습니다.")


# Admin-facing small helpers keep the provider-specific Korean messages in one place.
def nicepay_missing_message(config):
    if config.get("pinned_mode"):
        label = MODE_LABELS.get(config["pinned_mode"], config["pinned_mode"])
        return (
            f"이 결제는 NICEPAY {label} 키로 시작되었습니다. 관리자 쇼핑몰 설정 > 결제설정에 "
            f"{label} MID와 MerchantKey를 등록해야 처리할 수 있습니다."
        )
    return "NICEPAY MID와 MerchantKey가 설정되지 않았습니다."
