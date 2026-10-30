import { apiClient } from "@/lib/api";
import type { ApiSchema } from "@/lib/api-contract";

/** 정기구독 (gnu_jango/api/shop_subscriptions.py) — 응답 모양은 OpenAPI 계약에서 온다. */
export type ShopSubscription = ApiSchema<"ShopSubscription">;
export type ShopSubscriptionDetail = ApiSchema<"ShopSubscriptionDetail">;
export type ShopSubscriptionCharge = ApiSchema<"ShopSubscriptionCharge">;
export type ShopSubscriptionRegistration = ApiSchema<"ShopSubscriptionRegistration">;
export type ShopSubscriptionBillingResult = ApiSchema<"ShopSubscriptionBillingResult">;
export type ShopSubscriptionAction = "pause" | "resume" | "skip" | "cycle" | "cancel";

function required<T>(data: T | undefined): T {
  if (data === undefined || data === null) throw new Error("응답을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.");
  return data;
}

export interface StartSubscriptionPayload {
  it_id: string;
  /** 선택옵션(io_type 0) — 옵션 없는 상품은 "". */
  io_id: string;
  qty: number;
  cycle: string;
  /** 저장된 배송지(ShopAddress) 번호. */
  ad_id: number;
  od_memo?: string;
}

export async function getMySubscriptions(): Promise<ShopSubscription[]> {
  const response = await apiClient.get<ShopSubscription[]>("/shop/subscriptions");
  return Array.isArray(response.data) ? response.data : [];
}

export async function getMySubscription(id: number): Promise<ShopSubscriptionDetail> {
  const response = await apiClient.get<ShopSubscriptionDetail>(`/shop/subscriptions/${id}`);
  return required(response.data);
}

/** 카드 등록 대기 줄을 만들고 토스 자동결제 등록창에 넘길 값을 받는다(금액은 서버가 결제일에 정한다). */
export async function startSubscription(payload: StartSubscriptionPayload): Promise<ShopSubscriptionRegistration> {
  const response = await apiClient.post<ShopSubscriptionRegistration>("/shop/subscriptions/start", payload);
  return required(response.data);
}

export async function startSubscriptionCardChange(id: number): Promise<ShopSubscriptionRegistration> {
  const response = await apiClient.post<ShopSubscriptionRegistration>(`/shop/subscriptions/${id}/card`, {});
  return required(response.data);
}

/** 등록창 성공 주소의 authKey · customerKey 를 등록 토큰과 함께 서버에 넘긴다 — 빌링키는 서버에만 남는다. */
export async function completeSubscriptionBilling(params: {
  registrationToken: string;
  authKey: string;
  customerKey: string;
}): Promise<ShopSubscriptionBillingResult> {
  const response = await apiClient.post<ShopSubscriptionBillingResult>("/shop/subscriptions/billing-auth", {
    registration_token: params.registrationToken,
    authKey: params.authKey,
    customerKey: params.customerKey,
  });
  return required(response.data);
}

export function discardSubscriptionBilling(registrationToken: string) {
  return apiClient.post("/shop/subscriptions/billing-auth/cancel", { registration_token: registrationToken });
}

export async function changeSubscription(
  id: number,
  action: ShopSubscriptionAction,
  cycle = ""
): Promise<ShopSubscriptionDetail> {
  const response = await apiClient.post<ShopSubscriptionDetail>(`/shop/subscriptions/${id}/action`, {
    action,
    ...(cycle ? { cycle } : {}),
  });
  return required(response.data);
}
