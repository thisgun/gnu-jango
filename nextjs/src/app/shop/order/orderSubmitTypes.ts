import type {
  InicisExtra,
  KcpExtra,
  NicepayExtra,
  ConfiguredPgService,
  TossEscrowProduct,
} from "@/lib/payment";

export type OrderBody = Record<string, string | number>;

export type AddressBookPayload = {
  ad_subject: string;
  ad_default: 0 | 1;
  ad_name: string;
  ad_tel: string;
  ad_hp: string;
  ad_zip1: string;
  ad_zip2: string;
  ad_addr1: string;
  ad_addr2: string;
  ad_addr3: string;
  ad_jibeon: string;
};

export type CreatedOrderResponse = {
  order?: { od_id: string; uid?: string };
  od_id?: string;
  uid?: string;
  redirect_url?: string;
};

export type PreparedPaymentResponse = {
  order_id: string;
  order_name: string;
  amount: number;
  buyer_name: string;
  buyer_email: string;
  buyer_tel: string;
  cash_receipt_request?: boolean;
  cash_receipt_type?: "income" | "expense";
  cash_receipt_registration_number?: string;
  /** 복합과세 결제 (de_tax_flag_use): comm_free_mny goes to Toss as taxFreeAmount. */
  tax_flag?: number;
  comm_tax_mny?: number;
  comm_vat_mny?: number;
  comm_free_mny?: number;
  use_escrow?: boolean;
  escrow_products?: TossEscrowProduct[];
  pg_service?: ConfiguredPgService;
  uid?: string;
  pg_extra?: {
    inicis?: InicisExtra;
    kcp?: KcpExtra;
    nicepay?: NicepayExtra;
  };
};
