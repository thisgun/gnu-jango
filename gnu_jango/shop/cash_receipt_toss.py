"""Toss Payments cash receipt API (현금영수증 발급 / 취소), as youngcart shop/toss/toss.inc.php
issueCashReceipt / cancelCashReceipt call it:

POST /v1/cash-receipts with amount, orderId, orderName, customerIdentityNumber and type
(소득공제 or 지출증빙), and POST /v1/cash-receipts/{receiptKey}/cancel. Toss answers with a
CashReceipt object (receiptKey, issueNumber, receiptUrl, issueStatus, ...)."""

import base64
import hashlib
import json
import logging
import socket
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote

from django.conf import settings

logger = logging.getLogger(__name__)

TOSS_RECEIPT_TYPES = {"income": "소득공제", "expense": "지출증빙"}
TOSS_ALREADY_CANCELED_CODES = {"ALREADY_CANCELED_CASH_RECEIPT", "ALREADY_CANCELED"}


class CashReceiptApiError(Exception):
    """Toss refused or could not confirm the request; the message is shown (Korean)."""


def toss_cash_receipts_enabled():
    from gnu_jango.api.shop_payments import toss_payment_config

    return bool(toss_payment_config()["enabled"])


def _post(path, body, idempotency_key, *, action):
    from gnu_jango.api.shop_payments import toss_payment_config

    config = toss_payment_config()
    secret_key = str(getattr(settings, "SHOP_TOSS_SECRET_KEY", "") or "").strip()
    if not config["enabled"] or not secret_key:
        raise CashReceiptApiError("토스페이먼츠 키가 설정되지 않았습니다.")
    credentials = base64.b64encode(f"{secret_key}:".encode("utf-8")).decode("ascii")
    request = urllib_request.Request(
        f"{config['api_base_url']}{path}",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Idempotency-Key": idempotency_key[:300],
        },
    )
    try:
        with urllib_request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
    except urllib_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:1000]
        try:
            payload = json.loads(raw or "{}")
        except ValueError:
            payload = {}
        payload = payload if isinstance(payload, dict) else {}
        code = str(payload.get("code") or "")
        if action == "cancel" and code in TOSS_ALREADY_CANCELED_CODES:
            return {"transactionType": "CANCEL", "already_canceled": True}
        message = str(payload.get("message") or "").strip()[:200]
        detail = f"{message} ({code})" if message and code else message or code or f"HTTP {exc.code}"
        verb = "발급" if action == "issue" else "취소"
        raise CashReceiptApiError(f"토스페이먼츠가 현금영수증 {verb}을 거절했습니다: {detail}") from exc
    except (urllib_error.URLError, TimeoutError, socket.timeout) as exc:
        logger.warning("Toss cash receipt %s request failed: %s", action, exc)
        raise CashReceiptApiError("토스페이먼츠에 연결하지 못했습니다. 잠시 후 다시 시도하세요.") from exc
    except ValueError as exc:
        raise CashReceiptApiError("토스페이먼츠의 현금영수증 응답을 확인하지 못했습니다.") from exc
    if not isinstance(payload, dict):
        raise CashReceiptApiError("토스페이먼츠의 현금영수증 응답을 확인하지 못했습니다.")
    return payload


def issue_toss_cash_receipt(*, order_id, order_name, amount, cash_type, identity, tax_free=0):
    """Issue a cash receipt; returns Toss's CashReceipt (with receiptKey) or raises
    CashReceiptApiError. The identity number goes to Toss only and is never logged."""
    body = {
        "amount": int(amount),
        "orderId": str(order_id),
        "orderName": str(order_name or "")[:100] or str(order_id),
        "customerIdentityNumber": identity,
        "type": TOSS_RECEIPT_TYPES[cash_type],
    }
    if int(tax_free or 0) > 0:
        body["taxFreeAmount"] = int(tax_free)
    digest = hashlib.sha256(f"{order_id}|{amount}|{tax_free}|{cash_type}|{identity}".encode()).hexdigest()[:24]
    receipt = _post("/v1/cash-receipts", body, f"cash-receipt-{order_id}-{digest}", action="issue")
    if not str(receipt.get("receiptKey") or "").strip():
        raise CashReceiptApiError("토스페이먼츠가 현금영수증 발급을 확인하지 않았습니다.")
    if str(receipt.get("orderId") or order_id) != str(order_id):
        raise CashReceiptApiError("토스페이먼츠의 현금영수증 응답이 이 주문과 맞지 않습니다.")
    if str(receipt.get("issueStatus") or "").upper() == "FAILED":
        raise CashReceiptApiError("토스페이먼츠가 현금영수증 발급에 실패했다고 응답했습니다.")
    return receipt


def cancel_toss_cash_receipt(receipt_key):
    """Cancel a cash receipt issued through issue_toss_cash_receipt; returns Toss's answer
    ("already_canceled" when Toss had cancelled it before) or raises CashReceiptApiError."""
    key = str(receipt_key or "").strip()
    if not key:
        raise CashReceiptApiError("취소할 현금영수증 키가 없습니다.")
    return _post(
        f"/v1/cash-receipts/{quote(key, safe='')}/cancel", {}, f"cash-receipt-cancel-{key}", action="cancel"
    )
