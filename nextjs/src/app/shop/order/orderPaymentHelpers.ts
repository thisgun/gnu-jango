import type { ConfiguredPgService, PaymentMethod } from "@/lib/payment";

export interface PaymentConfig {
  pg_service: ConfiguredPgService;
  client: {
    client_key?: string;
    mid?: string;
    site_key?: string;
    script_url?: string;
  };
  payment_methods: {
    card: boolean;
    vbank: boolean;
    bank: boolean;
    iche: boolean;
    hp: boolean;
    easy_pay: boolean;
    kakaopay?: boolean;
  };
  cash_receipt?: {
    enabled: boolean;
    methods: {
      bank: boolean;
      vbank: boolean;
      iche: boolean;
    };
  };
  easy_pay_services?: string[];
  bank_accounts?: string[];
  /** 희망배송일 rule (de_hope_date_use / de_hope_date_after); min/max are server-local YYYY-MM-DD. */
  hope_date?: HopeDateRule;
  /** 비회원 개인정보 수집 안내 (de_guest_privacy), sanitized by the server; "" when not set. */
  guest_privacy?: string;
  is_test_mode: boolean;
}

export type HopeDateRule = {
  use: boolean;
  after: number;
  min: string;
  max: string;
};

export type PaymentNotice = {
  tone: "info" | "error" | "success";
  title: string;
  message: string;
};

export const PAYMENT_NOTICE_AUTO_DISMISS_MS = 15000;

export interface PayMethodDef {
  value: string;
  label: string;
  settle_case: string;
  pg_method?: PaymentMethod;
}

export const PAYMENT_METHODS: PayMethodDef[] = [
  { value: "bank", label: "무통장입금", settle_case: "무통장" },
  {
    value: "card",
    label: "신용카드",
    settle_case: "신용카드",
    pg_method: "card",
  },
  {
    value: "vbank",
    label: "가상계좌",
    settle_case: "가상계좌",
    pg_method: "vbank",
  },
  {
    value: "iche",
    label: "실시간계좌이체",
    settle_case: "계좌이체",
    pg_method: "iche",
  },
  {
    value: "hp",
    label: "휴대폰결제",
    settle_case: "휴대폰",
    pg_method: "hp",
  },
  {
    value: "easy_pay",
    label: "간편결제",
    settle_case: "간편결제",
    pg_method: "easy_pay",
  },
  {
    value: "kakaopay",
    label: "KAKAOPAY",
    settle_case: "KAKAOPAY",
    pg_method: "kakaopay",
  },
];

export function isPaymentMethodEnabled(
  method: PayMethodDef,
  config: PaymentConfig | null
): boolean {
  if (!config) return false;
  if (method.value === "bank") return config.payment_methods.bank;
  if (method.value === "card") return config.payment_methods.card;
  if (method.value === "vbank") return config.payment_methods.vbank;
  if (method.value === "iche") return config.payment_methods.iche;
  if (method.value === "hp") return config.payment_methods.hp;
  if (method.value === "easy_pay") return config.payment_methods.easy_pay;
  if (method.value === "kakaopay") return !!config.payment_methods.kakaopay;
  return false;
}

export function easyPayButtonLabel(services?: string[]): string {
  const labels: Record<string, string> = {
    nhnkcp_payco: "PAYCO",
    nhnkcp_naverpay: "네이버페이",
    nhnkcp_kakaopay: "카카오페이",
    nicepay_samsungpay: "삼성페이",
    nicepay_naverpay: "네이버페이",
    nicepay_kakaopay: "카카오페이",
    nicepay_paycopay: "PAYCO",
    nicepay_skpay: "SK페이",
    nicepay_ssgpay: "SSGPAY",
    nicepay_lpay: "LPAY",
  };
  const unique = Array.from(
    new Set((services || []).map((service) => labels[service]).filter(Boolean))
  );

  return unique.length === 1 ? unique[0] : "간편결제";
}
