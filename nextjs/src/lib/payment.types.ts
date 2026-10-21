/**
 * Shop payment gateway types — shared by the payment dispatcher (lib/payment.ts)
 * and its consumers. Pure type declarations, no runtime.
 */

export type PgService = "toss" | "inicis" | "kakaopay" | "kcp" | "nicepay";
export type ConfiguredPgService = PgService | "bank" | "kcp_v2" | "naverpay" | "samsungpay";

export type PaymentMethod =
  | "card"
  | "vbank"
  | "iche"
  | "hp"
  | "easy_pay"
  | "kakaopay";

export interface InicisExtra {
  mid: string;
  module_type?: "pc" | "mobile";
  oid: string;
  price: string;
  timestamp: string;
  signature: string;
  verification: string;
  mKey: string;
  return_url?: string;
  close_url?: string;
  popup_url?: string;
  script_url?: string;
  acceptmethod?: string;
  direct_method?: "kakaopay" | string;
  mobile_url?: string;
  mobile_next_url?: string;
  mobile_return_url?: string;
  mobile_noti_url?: string;
  mobile_reserved?: string;
  mobile_chkfake?: string;
  registration_error?: string;
}

export interface KcpExtra {
  site_cd: string;
  module_type?: "pc" | "mobile";
  approval_key?: string;
  pay_url?: string;
  pay_method?: string;
  return_url?: string;
  easy_pay_services?: string[];
  easy_pay_service?: string;
  naverpay_point_enabled?: boolean;
  registration_error?: string;
}

export interface NicepayExtra {
  mid: string;
  module_type?: "pc" | "mobile";
  edi_date: string;
  sign_data: string;
  return_url?: string;
  script_url?: string;
  mobile_url?: string;
  wap_url?: string;
  isp_cancel_url?: string;
  vbank_exp_date?: string;
  trans_type?: string;
  easy_pay_services?: string[];
  easy_pay_service?: string;
  registration_error?: string;
}

/** Toss escrowProducts entry (youngcart orderform.sub.php $escrow_products), built by the server. */
export interface TossEscrowProduct {
  id: string;
  name: string;
  code: string;
  unitPrice: number;
  quantity: number;
}

export interface PreparedOrder {
  order_id: string;
  order_name: string;
  amount: number;
  tax_flag?: number;
  comm_tax_mny?: number;
  comm_vat_mny?: number;
  comm_free_mny?: number;
  buyer_name: string;
  buyer_email: string;
  buyer_tel: string;
  cash_receipt_request?: boolean;
  cash_receipt_type?: "income" | "expense";
  cash_receipt_registration_number?: string;
  /** 에스크로 사용 (de_escrow_use): the server sets it for Toss transfers and virtual accounts. */
  use_escrow?: boolean;
  escrow_products?: TossEscrowProduct[];
  pg_extra?: {
    inicis?: InicisExtra;
    kcp?: KcpExtra;
    nicepay?: NicepayExtra;
  };
}

export interface PaymentRequest {
  pg_service: PgService;
  client_key: string;
  client_mid?: string;
  script_url?: string;
  method: PaymentMethod;
  order: PreparedOrder;
  success_url: string;
  fail_url: string;
}
