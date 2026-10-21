import type { PaymentConfig } from "@/app/shop/order/orderPaymentHelpers";

export interface PersonalPay {
  pp_id: string;
  pp_name: string;
  pp_email?: string;
  pp_hp?: string;
  pp_content: string;
  pp_price: number;
  pp_misu_price?: number;
  pp_settle_case: string;
  pp_bank_account: string;
  pp_deposit_name: string;
  pp_receipt_time?: string | null;
  pp_time?: string;
  already_paid: boolean;
  awaiting_deposit?: boolean;
  payment_in_progress?: boolean;
  payment_state?: string;
  payment_state_label?: string;
  can_pay?: boolean;
  can_change_deposit?: boolean;
  payment_block_reason?: string;
}

/**
 * 개인결제에서 고를 수 있는 결제수단. 주문서와 같은 설정(checkout_payment_methods)을 쓰되,
 * 가상계좌(입금 통보가 주문 전용)와 카카오페이는 빼고, 입금 확인을 기다리는 동안에는
 * 무통장입금(입금 정보 변경)만 남긴다.
 */
export function personalPayPaymentConfig(
  config: PaymentConfig | null,
  pp: PersonalPay
): PaymentConfig | null {
  if (!config) return null;
  const bankOnly = Boolean(pp.awaiting_deposit);
  const methods = config.payment_methods;
  return {
    ...config,
    // 구매 포인트 안내는 상품 주문에만 해당한다
    purchase_point: undefined,
    payment_methods: {
      bank: methods.bank,
      card: !bankOnly && methods.card,
      iche: !bankOnly && methods.iche,
      hp: !bankOnly && methods.hp,
      easy_pay: !bankOnly && methods.easy_pay,
      vbank: false,
      kakaopay: false,
    },
  };
}
