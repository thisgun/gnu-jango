import { loadTossPayments } from "@tosspayments/tosspayments-sdk";
import { cancelPreparedPayment, paymentTaxAmounts } from "./payment.shared";
import type { PaymentRequest, TossEscrowProduct } from "./payment.types";

export const TOSS_CANCELLED_MESSAGE = "결제가 취소되었습니다.";
export const TOSS_FALLBACK_ERROR_MESSAGE =
  "토스페이먼츠 결제가 완료되지 않았습니다.";

export function tossCustomerKey(orderId: string, randomId?: string) {
  const generated =
    randomId !== undefined
      ? randomId
      : typeof globalThis.crypto?.randomUUID === "function"
      ? globalThis.crypto.randomUUID()
      : "";
  const source = generated || orderId || "anonymous";
  const normalized = source.replace(/[^a-zA-Z0-9._=-]/g, "_");
  return `customer-${normalized}`.slice(0, 50);
}

export function normalizeTossError(err: unknown) {
  const record =
    err && typeof err === "object" ? (err as Record<string, unknown>) : {};
  const code = String(record.code ?? record.errorCode ?? "");
  const rawMessage =
    err instanceof Error
      ? err.message
      : String(record.message ?? record.errorMessage ?? "");
  const cancelled =
    /CANCEL|USER_CANCEL|PAY_PROCESS_CANCELED/i.test(code) ||
    /취소|cancel/i.test(rawMessage);

  return {
    cancelled,
    message:
      rawMessage ||
      (cancelled ? TOSS_CANCELLED_MESSAGE : TOSS_FALLBACK_ERROR_MESSAGE),
  };
}

export function createTossCommonPaymentRequest(req: PaymentRequest) {
  const taxAmounts = paymentTaxAmounts(req.order);

  return {
    amount: { currency: "KRW" as const, value: req.order.amount },
    orderId: req.order.order_id,
    orderName: req.order.order_name,
    successUrl: req.success_url + "?pg=toss",
    failUrl: req.fail_url,
    customerEmail: req.order.buyer_email,
    customerName: req.order.buyer_name,
    customerMobilePhone: req.order.buyer_tel.replace(/-/g, ""),
    taxFreeAmount: taxAmounts.enabled ? taxAmounts.free : 0,
  };
}

/**
 * 에스크로 사용 (youngcart de_escrow_use): useEscrow and escrowProducts for a Toss transfer or
 * virtual account. The server decides (use_escrow); nothing is added when it is off.
 */
export function tossEscrowOptions(order: {
  use_escrow?: boolean;
  escrow_products?: TossEscrowProduct[];
}): { useEscrow?: true; escrowProducts?: TossEscrowProduct[] } {
  if (!order.use_escrow) return {};
  const products = (order.escrow_products || []).map((product) => ({
    id: String(product.id),
    name: String(product.name),
    code: String(product.code),
    unitPrice: Math.max(0, Math.trunc(Number(product.unitPrice) || 0)),
    quantity: Math.max(1, Math.trunc(Number(product.quantity) || 1)),
  }));
  return products.length
    ? { useEscrow: true, escrowProducts: products }
    : { useEscrow: true };
}

function createCashReceiptRequest(req: PaymentRequest) {
  return {
    type:
      req.order.cash_receipt_type === "expense"
        ? ("지출증빙" as const)
        : ("소득공제" as const),
    registrationNumber: req.order.cash_receipt_registration_number || "",
  };
}

/**
 * Toss Payments v2 SDK
 */
export async function requestTossPayment(req: PaymentRequest): Promise<void> {
  const tossPayments = await loadTossPayments(req.client_key);
  // v2 requires a customerKey. Keep it free of personal identifiers.
  const customerKey = tossCustomerKey(req.order.order_id);
  const payment = tossPayments.payment({ customerKey });

  // Toss SDK has discriminated unions per method literal, build per-method.
  const common = createTossCommonPaymentRequest(req);

  try {
    switch (req.method) {
      case "card":
        await payment.requestPayment({
          method: "CARD",
          ...common,
          card: { useEscrow: false, flowMode: "DEFAULT" },
        });
        break;
      case "vbank":
        await payment.requestPayment({
          method: "VIRTUAL_ACCOUNT",
          ...common,
          virtualAccount: {
            useEscrow: false,
            ...tossEscrowOptions(req.order),
            validHours: 24,
            ...(req.order.cash_receipt_request
              ? { cashReceipt: createCashReceiptRequest(req) }
              : {}),
          },
        });
        break;
      case "iche":
        await payment.requestPayment({
          method: "TRANSFER",
          ...common,
          transfer: {
            ...(req.order.cash_receipt_request
              ? { cashReceipt: createCashReceiptRequest(req) }
              : {}),
            ...tossEscrowOptions(req.order),
          },
        });
        break;
      case "hp":
        await payment.requestPayment({ method: "MOBILE_PHONE", ...common });
        break;
      case "easy_pay":
        await payment.requestPayment({
          method: "CARD",
          ...common,
          card: { flowMode: "DEFAULT" },
        });
        break;
      default:
        await payment.requestPayment({ method: "CARD", ...common });
    }
  } catch (err) {
    const tossError = normalizeTossError(err);
    await cancelPreparedPayment(
      req,
      tossError.cancelled ? "Toss payment cancelled" : tossError.message
    );
    throw new Error(
      tossError.cancelled ? TOSS_CANCELLED_MESSAGE : tossError.message
    );
  }
}
