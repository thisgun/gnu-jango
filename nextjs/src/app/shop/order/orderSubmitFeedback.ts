import type { PgService } from "@/lib/payment";
import type { PaymentNotice } from "./orderPaymentHelpers";
import type { CreatedOrderResponse } from "./orderSubmitTypes";

export const PAYMENT_PREPARING_NOTICE: PaymentNotice = {
  tone: "info",
  title: "결제 준비 중입니다.",
  message: "주문 정보를 확인하고 결제창을 여는 중입니다.",
};

export const CART_PAGE_PATH = "/shop/cart";

/** YoungCart orderform: a price changed since the cart was shown, so the customer goes back to the cart. */
export function isCartPriceChangedError(err: unknown): boolean {
  if (!err || typeof err !== "object") return false;
  const { code, errors } = err as { code?: string; errors?: Record<string, string> };
  return code === "cart_price_changed" || Boolean(errors && "cart_price_changed" in errors);
}

export function getCreatedOrderPath(
  data: CreatedOrderResponse | undefined
): string {
  if (data?.redirect_url) return data.redirect_url;

  const odId = data?.order?.od_id ?? data?.od_id ?? "";
  const uid = data?.order?.uid ?? data?.uid ?? "";
  if (!odId) {
    throw new Error(
      "주문 생성 응답에서 주문번호를 확인하지 못했습니다. 주문 내역을 새로고침해 확인해 주세요."
    );
  }

  return `/shop/orders/${odId}${uid ? `?uid=${encodeURIComponent(uid)}` : ""}`;
}

export function getPaymentProgressNotice(pgService: PgService): PaymentNotice {
  return {
    tone: "info",
    title:
      pgService === "kcp"
        ? "NHN KCP 결제 진행 중입니다."
        : pgService === "kakaopay"
          ? "KAKAOPAY 결제 진행 중입니다."
          : "결제 진행 중입니다.",
    message:
      pgService === "kcp"
        ? "결제창에서 인증을 완료해주세요. 완료되면 자동으로 주문 내역으로 이동합니다."
        : "결제창에서 인증을 완료해주세요.",
  };
}

export function isPaymentCancelMessage(message: string): boolean {
  return message.includes("취소");
}
