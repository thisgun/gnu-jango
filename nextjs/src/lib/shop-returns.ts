/**
 * 반품·교환 신청 — 주문 상세의 신청 폼 · 신청 내역과 주문 목록의 배지가 함께 쓰는 타입과 말.
 * 타입은 API 계약(gnu_jango/api/contracts/returns.py)에서 만든 생성 타입을 그대로 쓴다.
 */
import type { ApiSchema } from "@/lib/api-contract";
import type { OrderStatusTone } from "@/lib/order-status";

export type ShopOrderReturns = ApiSchema<"ShopOrderReturns">;
export type ShopReturnRequest = ApiSchema<"ShopReturnRequest">;
export type ShopReturnOrderLine = ApiSchema<"ShopReturnOrderLine">;
export type ShopReturnKind = ApiSchema<"ShopReturnKindEnum">;
export type ShopReturnReason = ApiSchema<"ShopReturnReasonEnum">;
export type ShopReturnStatus = ApiSchema<"ShopReturnStatusEnum">;
export type ShopReturnCreate = ApiSchema<"ShopReturnCreate">;

const KIND_WORDS: Record<ShopReturnKind, string> = { return: "반품", exchange: "교환" };

const STATUS_WORDS: Record<ShopReturnStatus, string> = {
  requested: "신청",
  approved: "승인",
  completed: "완료",
  rejected: "거절",
  withdrawn: "철회",
};

/** 신청 상태 배지 색 — 주문 상태 배지(ORDER_STATUS_BADGE_CLASS)와 같은 표를 쓴다. */
export const RETURN_STATUS_TONE: Record<ShopReturnStatus, OrderStatusTone> = {
  requested: "warning",
  approved: "info",
  completed: "success",
  rejected: "error",
  withdrawn: "neutral",
};

function isKind(value: string): value is ShopReturnKind {
  return value in KIND_WORDS;
}

function isStatus(value: string): value is ShopReturnStatus {
  return value in STATUS_WORDS;
}

/** 주문 목록 카드의 배지 — "반품 신청", "교환 승인" 처럼. 신청이 없으면 null. */
export function returnRequestBadge(
  kind?: string | null,
  status?: string | null
): { label: string; tone: OrderStatusTone } | null {
  const kindValue = String(kind ?? "");
  const statusValue = String(status ?? "");
  if (!isKind(kindValue) || !isStatus(statusValue)) return null;
  return { label: `${KIND_WORDS[kindValue]} ${STATUS_WORDS[statusValue]}`, tone: RETURN_STATUS_TONE[statusValue] };
}
