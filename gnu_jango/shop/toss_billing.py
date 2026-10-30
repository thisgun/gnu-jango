"""Toss Payments card billing (자동결제) API calls for 정기구독 (shop/subscriptions.py).

Checked against the Toss docs (docs.tosspayments.com, reference and guides/v2/billing):
- POST /v1/billing/authorizations/issue {authKey, customerKey} turns the one-time authKey the
  billing registration window sent to successUrl into a Billing object (billingKey, customerKey,
  card.number masked, card.issuerCode, ...). A billing key cannot be looked up again later.
- POST /v1/billing/{billingKey} {customerKey, amount, orderId, orderName, customerEmail,
  customerName, taxFreeAmount} approves a payment and answers with a Payment object. Toss says the
  approval can take up to 60 seconds, so that call waits that long.
- GET /v1/payments/orders/{orderId} finds the payment of an orderId (404 NOT_FOUND_PAYMENT when
  there is none); DELETE /v1/billing/{billingKey} removes a billing key (empty 200).
- Every POST takes an Idempotency-Key (at most 300 characters, valid 15 days): a repeated request
  with the same key gets the first answer and is not processed again.

Keys and the API base come from shop_payments.toss_api_context, pinned to the 테스트 / 실결제 pair
the billing key was issued with. The billing key itself never appears in a log or an exception.
"""

import json
import logging
from types import SimpleNamespace
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote

from django.views.decorators.debug import sensitive_variables

from gnu_jango.api.shop_payments import NETWORK_ERRORS, toss_api_context

logger = logging.getLogger(__name__)

ISSUE_TIMEOUT_SECONDS = 15
APPROVAL_TIMEOUT_SECONDS = 60
LOOKUP_TIMEOUT_SECONDS = 10
NOT_FOUND_CODES = {"NOT_FOUND_PAYMENT", "NOT_FOUND"}
# Toss is still working on an earlier request with the same Idempotency-Key
PROCESSING_CODES = {"IDEMPOTENT_REQUEST_PROCESSING"}


# Toss 카드사 코드 (docs.tosspayments.com/codes/org-codes): the Billing object names the issuer by
# card.issuerCode since API version 2024-06-01 (cardCompany is deprecated)
CARD_COMPANIES = {
    "3K": "기업비씨", "46": "광주", "71": "롯데", "30": "산업", "31": "비씨", "51": "삼성", "38": "새마을",
    "41": "신한", "62": "신협", "36": "씨티", "33": "우리", "W1": "우리", "37": "우체국", "39": "저축",
    "35": "전북", "42": "제주", "15": "카카오뱅크", "3A": "케이뱅크", "24": "토스뱅크", "21": "하나",
    "61": "현대", "11": "국민", "91": "농협", "34": "수협",
}


def card_company_name(issuer_code):
    code = str(issuer_code or "").strip()
    return CARD_COMPANIES.get(code, code)


class TossBillingError(Exception):
    """Toss refused a billing call (``code`` / ``message`` from its error object), or its outcome is
    unknown (``uncertain``: no answer, a 5xx or a request still processing), in which case the
    payment must be looked up before anything is decided."""

    def __init__(self, message, *, code="", status=None, uncertain=False):
        super().__init__(message)
        self.code = str(code or "")
        self.status = status
        self.uncertain = uncertain


def _context(mode):
    """(api base url, Authorization header) for the key pair of ``mode`` (od_test "1" / "0")."""
    config, authorization = toss_api_context(SimpleNamespace(od_test=mode or ""))
    if not authorization:
        raise TossBillingError("Toss Payments is not configured.", code="toss_payment_unconfigured")
    return config["api_base_url"], authorization


def _error_payload(exc):
    try:
        payload = json.loads(exc.read().decode("utf-8", errors="replace")[:2000] or "{}")
    except ValueError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


@sensitive_variables("authorization", "path", "request", "headers")
def _call(method, path, *, mode, body=None, timeout, idempotency_key=""):
    """The JSON answer of one Toss API call (a dict; {} for an empty body)."""
    base_url, authorization = _context(mode)
    headers = {"Authorization": authorization, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key[:300]
    request = urllib_request.Request(f"{base_url}{path}", data=data, method=method, headers=headers)
    try:
        with urllib_request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib_error.HTTPError as exc:
        payload = _error_payload(exc)
        code = str(payload.get("code") or "")
        message = str(payload.get("message") or "").strip()[:200] or f"HTTP {exc.code}"
        raise TossBillingError(
            message, code=code, status=exc.code, uncertain=exc.code >= 500 or code in PROCESSING_CODES
        ) from None
    except NETWORK_ERRORS as exc:
        # the exception text can name hosts; the billing key is in the URL, so it is not logged
        logger.warning("Toss billing %s request failed: %s", method, type(exc).__name__)
        raise TossBillingError("Toss Payments did not answer.", code="toss_unavailable", uncertain=True) from None
    try:
        payload = json.loads(raw or "{}")
    except ValueError:
        raise TossBillingError("Toss Payments returned an invalid response.", code="invalid_response", uncertain=True) from None
    if not isinstance(payload, dict):
        raise TossBillingError("Toss Payments returned an invalid response.", code="invalid_response", uncertain=True)
    return payload


@sensitive_variables("auth_key")
def issue_billing_key(auth_key, customer_key, *, mode, idempotency_key=""):
    """The Billing object Toss issues for a card registration (authKey + customerKey)."""
    return _call(
        "POST",
        "/v1/billing/authorizations/issue",
        mode=mode,
        body={"authKey": str(auth_key), "customerKey": str(customer_key)},
        timeout=ISSUE_TIMEOUT_SECONDS,
        idempotency_key=idempotency_key,
    )


@sensitive_variables("billing_key")
def charge_billing_key(billing_key, *, mode, customer_key, amount, order_id, order_name, idempotency_key,
                       customer_email="", customer_name="", tax_free_amount=0):
    """Approve ``amount`` on the billing key; the Payment object Toss answers with."""
    body = {
        "customerKey": customer_key,
        "amount": int(amount),
        "orderId": order_id,
        "orderName": str(order_name or "정기구독")[:100],
        "taxFreeAmount": max(0, int(tax_free_amount or 0)),
    }
    if customer_email:
        body["customerEmail"] = str(customer_email)[:100]
    if customer_name:
        body["customerName"] = str(customer_name)[:100]
    return _call(
        "POST",
        f"/v1/billing/{quote(str(billing_key), safe='')}",
        mode=mode,
        body=body,
        timeout=APPROVAL_TIMEOUT_SECONDS,
        idempotency_key=idempotency_key,
    )


def payment_by_order_id(order_id, *, mode):
    """The Payment object of ``order_id``, or None when Toss has no payment for it."""
    try:
        return _call(
            "GET", f"/v1/payments/orders/{quote(str(order_id), safe='')}", mode=mode, timeout=LOOKUP_TIMEOUT_SECONDS
        )
    except TossBillingError as exc:
        if exc.status == 404 or exc.code in NOT_FOUND_CODES:
            return None
        # a lookup that could not be made decides nothing
        exc.uncertain = True
        raise


@sensitive_variables("billing_key")
def delete_billing_key(billing_key, *, mode):
    """Remove a billing key at Toss (a replaced card, a cancelled subscription). Returns whether
    Toss confirmed it; a failure is logged and left, the key is dropped locally either way."""
    if not billing_key:
        return False
    try:
        _call("DELETE", f"/v1/billing/{quote(str(billing_key), safe='')}", mode=mode, timeout=LOOKUP_TIMEOUT_SECONDS)
    except TossBillingError as exc:
        logger.warning("Toss billing key removal failed: %s", exc.code or exc.status or "unknown")
        return False
    return True
