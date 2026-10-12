export const PAYMENT_REQUIRED_INFO_MESSAGE =
  "필수 결제 정보가 누락되었습니다.";
export const PAYMENT_FAIL_DEFAULT_MESSAGE =
  "결제가 취소되었거나 실패하였습니다.";

export type PaymentSearchParams = {
  get(name: string): string | null;
  forEach(callback: (value: string, key: string) => void): void;
};

export type PaymentConfirmBody = Record<string, string | number> & {
  pg_service: string;
  order_id: string;
  amount: number;
  payment_key?: string;
};

export type PaymentSuccessParams =
  | {
      ok: true;
      pg: string;
      orderId: string;
      amount: number;
      paymentKey: string;
      body: PaymentConfirmBody;
    }
  | {
      ok: false;
      message: string;
    };

export type PaymentHostResultPayload =
  | { status: "success"; orderId: string; uid?: string }
  | { status: "pending"; orderId: string; uid?: string }
  | { status: "error"; message: string };

const PAYMENT_CONFIRM_PARAM_ALLOWLIST = new Set([
  "pg",
  "pg_service",
  "od_pg",
  "de_pg_service",
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
  "paymentKey",
  "transactionId",
  "tno",
  "TID",
  "tid",
  "P_TID",
  "LGD_TID",
  "LGD_PAYKEY",
  "authToken",
  "approvalKey",
  "res_cd",
  "resultCode",
  "ResultCode",
  "P_STATUS",
  "LGD_RESPCODE",
  "status",
  "paymentStatus",
  "pay_status",
  "resultStatus",
  "trade_state",
  "state",
  "good_mny",
  "good_mny2",
  "Amt",
  "TotPrice",
  "price",
  "P_AMT",
  "LGD_AMOUNT",
  "P_AUTH_NO",
  "P_REQ_URL",
  "enc_data",
  "enc_info",
  "tran_cd",
  "site_cd",
  "authSignature",
  "authUrl",
  "netCancelUrl",
  "merchantData",
  "mKey",
  "mid",
]);

export function parsePaymentSuccessParams(
  params: PaymentSearchParams
): PaymentSuccessParams {
  const pg = params.get("pg") || "toss";
  const orderId = params.get("orderId") || "";
  // The amount here is client-supplied (PG redirect query). The server re-derives
  // the authoritative amount from the prepared-order record and also cross-checks
  // the PG-approved amount, so this value is only a redundant check — never the
  // source of truth. Parse strictly so a malformed value ("1abc") is rejected
  // rather than silently coerced.
  const rawAmount = params.get("amount") || "";
  const hasValidAmount = /^\d+$/.test(rawAmount);
  const amount = hasValidAmount ? parseInt(rawAmount, 10) : 0;
  const paymentKey = params.get("paymentKey") || "";

  if (!orderId || !hasValidAmount) {
    return {
      ok: false,
      message: PAYMENT_REQUIRED_INFO_MESSAGE,
    };
  }

  const body: PaymentConfirmBody = {
    pg_service: pg,
    order_id: orderId,
    amount,
  };
  if (pg === "toss") body.payment_key = paymentKey;

  params.forEach((value, key) => {
    if (PAYMENT_CONFIRM_PARAM_ALLOWLIST.has(key) && !(key in body)) {
      body[key] = value;
    }
  });

  return {
    ok: true,
    pg,
    orderId,
    amount,
    paymentKey,
    body,
  };
}

export function paymentOrderDetailUrl(orderId: string, uid?: string) {
  return `/shop/orders/${orderId}${uid ? `?uid=${encodeURIComponent(uid)}` : ""}`;
}

export function paymentSuccessHostPayload(
  orderId: string,
  uid = ""
): PaymentHostResultPayload {
  return {
    status: "success",
    orderId,
    uid,
  };
}

export function paymentPendingHostPayload(
  orderId: string,
  uid = ""
): PaymentHostResultPayload {
  return { status: "pending", orderId, uid };
}

export function paymentErrorHostPayload(
  message: string
): PaymentHostResultPayload {
  return {
    status: "error",
    message,
  };
}

export function parsePaymentFailParams(params: PaymentSearchParams) {
  return {
    code: params.get("code") || "",
    message: params.get("message") || PAYMENT_FAIL_DEFAULT_MESSAGE,
  };
}
