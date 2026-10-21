/**
 * 주문 상태 라벨 — 영카트 shop/orderinquiry.sub.php 와 같은 말을 주문 목록·주문 상세·마이페이지가 함께 쓴다.
 * 백엔드는 그누보드5 표준 상태값(주문·입금·준비·배송·완료·취소·반품·품절)을 그대로 보낸다.
 */
export type OrderStatusTone = "warning" | "info" | "neutral" | "primary" | "success" | "error";

const ORDER_STATUS_LABELS: Record<string, { label: string; tone: OrderStatusTone }> = {
  주문: { label: "입금확인중", tone: "warning" },
  입금: { label: "입금완료", tone: "info" },
  준비: { label: "상품준비중", tone: "neutral" },
  배송: { label: "상품배송", tone: "primary" },
  완료: { label: "배송완료", tone: "success" },
  취소: { label: "주문취소", tone: "error" },
  // 관리자가 상품을 반품 · 품절 처리해 끝난 주문(영카트 orderformcartupdate.php)
  반품: { label: "반품", tone: "error" },
  품절: { label: "품절취소", tone: "error" },
};

/** 영카트 $status_cancel — 주문 · 상품줄이 이 상태면 끝난(취소된) 것이다. */
const CLOSED_ORDER_STATUSES = new Set(["취소", "반품", "품절"]);

export function isClosedOrderStatus(status?: string | null): boolean {
  return CLOSED_ORDER_STATUSES.has(normalizeOrderStatus(status));
}

/** 예전 화면·외부 데이터가 쓰던 표시용 상태 이름도 같은 표준 상태로 읽는다. */
const ORDER_STATUS_ALIASES: Record<string, string> = {
  입금대기: "주문",
  결제완료: "입금",
  배송준비: "준비",
  배송중: "배송",
  배송완료: "완료",
};

export function normalizeOrderStatus(status?: string | null): string {
  const value = String(status ?? "").trim();
  return ORDER_STATUS_ALIASES[value] ?? value;
}

/** 영카트처럼 알 수 없는 상태는 주문취소로 보인다(orderinquiry.sub.php 의 default). */
export function orderStatusLabel(status?: string | null): { label: string; tone: OrderStatusTone } {
  return ORDER_STATUS_LABELS[normalizeOrderStatus(status)] ?? ORDER_STATUS_LABELS["취소"];
}

/** 쇼핑몰 주문 목록·상세의 상태 배지 색. */
export const ORDER_STATUS_BADGE_CLASS: Record<OrderStatusTone, string> = {
  warning: "bg-amber-100 text-amber-700",
  info: "bg-blue-100 text-blue-700",
  neutral: "bg-gray-100 text-gray-700",
  primary: "bg-indigo-100 text-indigo-700",
  success: "bg-green-100 text-green-700",
  error: "bg-red-100 text-red-700",
};

/** 주문 상세의 진행 단계 — 주문접수부터 배송완료까지. */
export const ORDER_PROGRESS_STEPS = ["주문", "입금", "준비", "배송", "완료"] as const;
