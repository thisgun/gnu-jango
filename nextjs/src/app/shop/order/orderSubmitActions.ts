import { api, type ApiResponse } from "@/lib/api";
import { requestPayment as requestPaymentAction } from "@/lib/payment";
import type { AddressForm, AddressSelection } from "./orderAddressHelpers";
import type { PaymentConfig, PaymentNotice } from "./orderPaymentHelpers";
import type { PayMethodDef } from "./orderPaymentHelpers";
import { getPaymentProgressNotice } from "./orderSubmitFeedback";
import { buildAddressBookPayload } from "./orderSubmitPayload";
import type {
  CreatedOrderResponse,
  OrderBody,
  PreparedPaymentResponse,
} from "./orderSubmitTypes";
import { shouldPersistAddress } from "./orderSubmitValidation";

type PersistAddressBookEntryInput = {
  addressSelection: AddressSelection;
  saveAsNewAddress: boolean;
  recipient: AddressForm;
  newAddressSubject: string;
  newAddressDefault: boolean;
  deps?: Partial<OrderSubmitActionsDeps>;
};

type CreateBankOrderInput = {
  orderBody: OrderBody;
  bankAccount: string;
  depositName: string;
  deps?: Partial<OrderSubmitActionsDeps>;
};

type RequestPreparedOrderPaymentInput = {
  orderBody: OrderBody;
  paymentConfig: PaymentConfig;
  methodDef: PayMethodDef;
  origin: string;
  onPaymentProgress: (notice: PaymentNotice) => void;
  deps?: Partial<OrderSubmitActionsDeps>;
};

type ApiPost = <T>(path: string, body?: unknown) => Promise<ApiResponse<T>>;

export type OrderSubmitActionsDeps = {
  post: ApiPost;
  requestPayment: typeof requestPaymentAction;
};

const defaultOrderSubmitActionsDeps: OrderSubmitActionsDeps = {
  post: (path, body) => api.post(path, body),
  requestPayment: requestPaymentAction,
};

function resolveOrderSubmitActionsDeps(
  deps?: Partial<OrderSubmitActionsDeps>
): OrderSubmitActionsDeps {
  return { ...defaultOrderSubmitActionsDeps, ...deps };
}

export async function persistAddressBookEntryIfNeeded({
  addressSelection,
  saveAsNewAddress,
  recipient,
  newAddressSubject,
  newAddressDefault,
  deps,
}: PersistAddressBookEntryInput): Promise<void> {
  if (!shouldPersistAddress(addressSelection, saveAsNewAddress)) return;

  const actionDeps = resolveOrderSubmitActionsDeps(deps);

  try {
    await actionDeps.post(
      "/shop/addresses",
      buildAddressBookPayload(
        recipient,
        newAddressSubject,
        newAddressDefault
      )
    );
  } catch {
    // Address book persistence is non-fatal for the order itself.
  }
}

export async function createBankOrder({
  orderBody,
  bankAccount,
  depositName,
  deps,
}: CreateBankOrderInput): Promise<CreatedOrderResponse | undefined> {
  const actionDeps = resolveOrderSubmitActionsDeps(deps);
  const res = await actionDeps.post<CreatedOrderResponse>("/shop/orders", {
    ...orderBody,
    od_bank_account: bankAccount,
    od_deposit_name: depositName,
  });

  return res.data;
}

export async function requestPreparedOrderPayment({
  orderBody,
  paymentConfig,
  methodDef,
  origin,
  onPaymentProgress,
  deps,
}: RequestPreparedOrderPaymentInput): Promise<void> {
  const actionDeps = resolveOrderSubmitActionsDeps(deps);

  if (!methodDef.pg_method) {
    throw new Error("결제 수단을 다시 선택해주세요.");
  }

  const prepRes = await actionDeps.post<PreparedPaymentResponse>(
    "/shop/payment/prepare",
    orderBody
  );

  const prepared = prepRes.data;
  if (!prepared) {
    throw new Error("결제 준비에 실패했습니다.");
  }
  const preparedPgService = prepared.pg_service || paymentConfig.pg_service;
  if (preparedPgService === "bank") {
    throw new Error("PG 결제 설정을 확인할 수 없습니다. 주문 화면을 새로고침한 후 다시 시도해주세요.");
  }
  if (preparedPgService !== "toss") {
    throw new Error("현재 결제 화면에서 시작할 수 없는 PG입니다. 상점 관리자에게 문의해주세요.");
  }

  onPaymentProgress(getPaymentProgressNotice(preparedPgService));

  await actionDeps.requestPayment({
    pg_service: preparedPgService,
    client_key: paymentConfig.client.client_key || "",
    client_mid: paymentConfig.client.mid,
    script_url: paymentConfig.client.script_url,
    method: methodDef.pg_method,
    order: {
      order_id: prepared.order_id,
      order_name: prepared.order_name,
      amount: prepared.amount,
      buyer_name: prepared.buyer_name,
      buyer_email: prepared.buyer_email || "noemail@example.com",
      buyer_tel: prepared.buyer_tel,
      cash_receipt_request: prepared.cash_receipt_request,
      cash_receipt_type: prepared.cash_receipt_type,
      cash_receipt_registration_number:
        prepared.cash_receipt_registration_number,
      pg_extra: prepared.pg_extra,
    },
    success_url: `${origin}/shop/payment/success`,
    fail_url: `${origin}/shop/payment/fail`,
  });
}
