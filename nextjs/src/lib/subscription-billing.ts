import { loadTossPayments } from "@tosspayments/tosspayments-sdk";
import { g5PathForRuntime } from "@/lib/config";
import { normalizeTossError } from "@/lib/payment.toss";
import type { ShopSubscriptionRegistration } from "@/services/subscriptions";

/** 정기구독 카드 등록(토스 자동결제 등록창)이 돌아오는 주소 — 쿼리의 토큰 · authKey 는 읽은 뒤 주소창에서 지운다. */
export const SUBSCRIPTION_BILLING_SUCCESS_PATH = "/shop/subscriptions/billing/success";
export const SUBSCRIPTION_BILLING_FAIL_PATH = "/shop/subscriptions/billing/fail";
export const SUBSCRIPTION_BILLING_CANCELLED_MESSAGE = "카드 등록을 취소했습니다.";

interface SearchParamsLike {
  get(name: string): string | null;
}

export function subscriptionBillingReturnUrl(origin: string, result: "success" | "fail", registrationToken: string) {
  const path = result === "success" ? SUBSCRIPTION_BILLING_SUCCESS_PATH : SUBSCRIPTION_BILLING_FAIL_PATH;
  return `${origin}${g5PathForRuntime(path)}?token=${encodeURIComponent(registrationToken)}`;
}

/** 등록창 요청(SDK v2 payment.requestBillingAuth) — 카드만, 고객 이름 · 메일은 서버가 준 값. */
export function createSubscriptionBillingRequest(registration: ShopSubscriptionRegistration, origin: string) {
  return {
    method: "CARD" as const,
    successUrl: subscriptionBillingReturnUrl(origin, "success", registration.registration_token),
    failUrl: subscriptionBillingReturnUrl(origin, "fail", registration.registration_token),
    ...(registration.customer_name ? { customerName: registration.customer_name } : {}),
    ...(registration.customer_email ? { customerEmail: registration.customer_email } : {}),
  };
}

/**
 * 토스 자동결제 카드 등록창을 연다. customerKey 는 서버가 회원마다 만든 무작위 값이다.
 * 창은 성공 · 실패 주소로 이동하므로 정상이면 돌아오지 않는다. 고객이 창을 닫으면 Error 를 던진다.
 */
export async function openSubscriptionBillingWindow(registration: ShopSubscriptionRegistration, origin: string) {
  const tossPayments = await loadTossPayments(registration.client_key);
  const payment = tossPayments.payment({ customerKey: registration.customer_key });
  try {
    await payment.requestBillingAuth(createSubscriptionBillingRequest(registration, origin));
  } catch (err) {
    const tossError = normalizeTossError(err);
    throw new Error(tossError.cancelled ? SUBSCRIPTION_BILLING_CANCELLED_MESSAGE : tossError.message);
  }
}

export type SubscriptionBillingReturn =
  | { kind: "success"; registrationToken: string; authKey: string; customerKey: string }
  | { kind: "fail"; registrationToken: string; code: string; message: string }
  | { kind: "invalid" };

/** 성공 주소: token + 토스가 붙인 customerKey · authKey. 실패 주소: token + code · message. */
export function parseSubscriptionBillingReturn(params: SearchParamsLike, result: "success" | "fail"): SubscriptionBillingReturn {
  const registrationToken = params.get("token") || "";
  if (result === "fail") {
    return {
      kind: "fail",
      registrationToken,
      code: params.get("code") || "",
      message: params.get("message") || "카드 등록이 완료되지 않았습니다.",
    };
  }
  const authKey = params.get("authKey") || "";
  const customerKey = params.get("customerKey") || "";
  if (!registrationToken || !authKey || !customerKey) return { kind: "invalid" };
  return { kind: "success", registrationToken, authKey, customerKey };
}
