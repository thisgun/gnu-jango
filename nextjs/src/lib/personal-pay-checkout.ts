/**
 * 개인결제(영카트 personalpayform.php) 결제 흐름 도우미.
 *
 * 무통장입금은 POST /shop/personalpay/:id/bank 로 끝난다. 토스페이먼츠는
 * POST .../toss/prepare 가 서버 금액과 개인결제 전용 orderId 를 주고, 결제창이 같은 결제
 * 페이지(?result=success|fail)로 돌아오면 POST .../toss/confirm 으로 승인한다.
 * 주문 결제(lib/payment.toss.ts)와 달리 실패해도 취소할 "준비된 주문"이 없다.
 */
import { loadTossPayments } from "@tosspayments/tosspayments-sdk";
import { normalizeTossError, TOSS_CANCELLED_MESSAGE, tossCustomerKey } from "./payment.toss";

export const PERSONAL_PAY_TOSS_METHODS = ["card", "iche", "hp", "easy_pay"] as const;
export type PersonalPayTossMethod = (typeof PERSONAL_PAY_TOSS_METHODS)[number];

export interface PersonalPayTossPrepared {
  pp_id: string;
  order_id: string;
  order_name: string;
  amount: number;
  buyer_name: string;
  buyer_email: string;
  buyer_tel: string;
  method: PersonalPayTossMethod;
  client_key: string;
}

export type PersonalPayReturn =
  | { kind: "none" }
  | { kind: "success"; paymentKey: string; orderId: string; amount: number }
  | { kind: "fail"; code: string; message: string }
  | { kind: "invalid"; message: string };

type SearchParamsLike = { get(name: string): string | null };

export const PERSONAL_PAY_RETURN_INVALID_MESSAGE =
  "결제 결과 정보가 올바르지 않습니다. 개인결제 화면에서 다시 시도해 주세요.";
export const PERSONAL_PAY_FAIL_DEFAULT_MESSAGE = "결제가 완료되지 않았습니다.";

export function isPersonalPayTossMethod(value: string): value is PersonalPayTossMethod {
  return (PERSONAL_PAY_TOSS_METHODS as readonly string[]).includes(value);
}

export function personalPayReturnUrl(origin: string, ppId: string, result: "success" | "fail") {
  return `${origin}/shop/personalpay/${encodeURIComponent(ppId)}/pay?result=${result}`;
}

/** 토스 결제창이 붙여 준 쿼리를 읽는다. 금액은 서버가 다시 확인하므로 형식만 본다. */
export function parsePersonalPayReturn(params: SearchParamsLike): PersonalPayReturn {
  const result = params.get("result");
  if (result === "fail") {
    return {
      kind: "fail",
      code: params.get("code") || "",
      message: params.get("message") || PERSONAL_PAY_FAIL_DEFAULT_MESSAGE,
    };
  }
  if (result !== "success") return { kind: "none" };
  const paymentKey = params.get("paymentKey") || "";
  const orderId = params.get("orderId") || "";
  const rawAmount = params.get("amount") || "";
  if (!paymentKey || !orderId || !/^\d+$/.test(rawAmount)) {
    return { kind: "invalid", message: PERSONAL_PAY_RETURN_INVALID_MESSAGE };
  }
  return { kind: "success", paymentKey, orderId, amount: parseInt(rawAmount, 10) };
}

function tossMethod(method: PersonalPayTossMethod) {
  switch (method) {
    case "iche":
      return "TRANSFER" as const;
    case "hp":
      return "MOBILE_PHONE" as const;
    default:
      return "CARD" as const;
  }
}

export function createPersonalPayTossRequest(prepared: PersonalPayTossPrepared, origin: string) {
  return {
    method: tossMethod(prepared.method),
    amount: { currency: "KRW" as const, value: prepared.amount },
    orderId: prepared.order_id,
    orderName: prepared.order_name,
    successUrl: personalPayReturnUrl(origin, prepared.pp_id, "success"),
    failUrl: personalPayReturnUrl(origin, prepared.pp_id, "fail"),
    ...(prepared.buyer_email ? { customerEmail: prepared.buyer_email } : {}),
    customerName: prepared.buyer_name,
    ...(prepared.buyer_tel ? { customerMobilePhone: prepared.buyer_tel.replace(/\D/g, "") } : {}),
  };
}

/** 토스 결제창을 연다. 결제창은 성공/실패 주소로 이동하므로 정상이면 돌아오지 않는다. */
export async function openPersonalPayTossWindow(prepared: PersonalPayTossPrepared, origin: string) {
  const tossPayments = await loadTossPayments(prepared.client_key);
  const payment = tossPayments.payment({ customerKey: tossCustomerKey(prepared.order_id) });
  const request = createPersonalPayTossRequest(prepared, origin);
  try {
    switch (request.method) {
      case "TRANSFER":
        await payment.requestPayment({ ...request, method: "TRANSFER", transfer: {} });
        break;
      case "MOBILE_PHONE":
        await payment.requestPayment({ ...request, method: "MOBILE_PHONE" });
        break;
      default:
        await payment.requestPayment({
          ...request,
          method: "CARD",
          card: { useEscrow: false, flowMode: "DEFAULT" },
        });
    }
  } catch (err) {
    const tossError = normalizeTossError(err);
    throw new Error(tossError.cancelled ? TOSS_CANCELLED_MESSAGE : tossError.message);
  }
}
