import { isMobileDevice as defaultIsMobileDevice } from "@/lib/payment";
import { toastError as defaultToastError } from "@/lib/toast";
import {
  type AddressForm,
  type AddressSelection,
} from "./orderAddressHelpers";
import {
  type PaymentConfig,
  type PaymentNotice,
} from "./orderPaymentHelpers";
import {
  submitBankOrder as submitBankOrderAction,
  submitPaymentOrder as submitPaymentOrderAction,
} from "./orderSubmitFlow";
import { buildOrderBody as buildOrderBodyAction } from "./orderSubmitPayload";
import { validateOrderSubmission as validateOrderSubmissionAction } from "./orderSubmitValidation";

type RouterLike = {
  push(href: string): void;
  replace(href: string): void;
};

type SetSubmitting = (submitting: boolean) => void;
type SetPaymentNotice = (notice: PaymentNotice | null) => void;

export type UseOrderSubmitOptions = {
  orderer: AddressForm;
  recipient: AddressForm;
  addressSelection: AddressSelection;
  saveAsNewAddress: boolean;
  newAddressSubject: string;
  newAddressDefault: boolean;
  email: string;
  memo: string;
  hopeDate: string;
  taxRequest: boolean;
  taxCompany: string;
  taxBusinessNo: string;
  taxInvoiceEmail: string;
  cashRequest: boolean;
  cashReceiptType: "income" | "expense";
  cashReceiptIdentityNumber: string;
  guestPassword: string;
  isMemberOrder: boolean;
  paymentMethod: string;
  paymentConfig: PaymentConfig | null;
  bankAccount: string;
  depositName: string;
  agreeTerms: boolean;
  agreePrivacy: boolean;
  selectedCouponId: string;
  selectedSendCouponId: string;
  pointUse: number;
  directCheckout: boolean;
  directCtIds: string;
  setSubmitting: SetSubmitting;
  setPaymentNotice: SetPaymentNotice;
};

type SubmitOrderInput = UseOrderSubmitOptions & {
  router: RouterLike;
  origin: string;
  deps?: Partial<OrderSubmitHandlerDeps>;
};

export type OrderSubmitHandlerDeps = {
  buildOrderBody: typeof buildOrderBodyAction;
  isMobileDevice: typeof defaultIsMobileDevice;
  submitBankOrder: typeof submitBankOrderAction;
  submitPaymentOrder: typeof submitPaymentOrderAction;
  toastError: typeof defaultToastError;
  validateOrderSubmission: typeof validateOrderSubmissionAction;
};

const defaultOrderSubmitHandlerDeps: OrderSubmitHandlerDeps = {
  buildOrderBody: buildOrderBodyAction,
  isMobileDevice: defaultIsMobileDevice,
  submitBankOrder: submitBankOrderAction,
  submitPaymentOrder: submitPaymentOrderAction,
  toastError: defaultToastError,
  validateOrderSubmission: validateOrderSubmissionAction,
};

function resolveOrderSubmitHandlerDeps(
  deps?: Partial<OrderSubmitHandlerDeps>
): OrderSubmitHandlerDeps {
  return { ...defaultOrderSubmitHandlerDeps, ...deps };
}

export async function submitOrder({
  orderer,
  recipient,
  addressSelection,
  saveAsNewAddress,
  newAddressSubject,
  newAddressDefault,
  email,
  memo,
  hopeDate,
  taxRequest,
  taxCompany,
  taxBusinessNo,
  taxInvoiceEmail,
  cashRequest,
  cashReceiptType,
  cashReceiptIdentityNumber,
  guestPassword,
  isMemberOrder,
  paymentMethod,
  paymentConfig,
  bankAccount,
  depositName,
  agreeTerms,
  agreePrivacy,
  selectedCouponId,
  selectedSendCouponId,
  pointUse,
  directCheckout,
  directCtIds,
  setSubmitting,
  setPaymentNotice,
  router,
  origin,
  deps,
}: SubmitOrderInput): Promise<void> {
  const handlerDeps = resolveOrderSubmitHandlerDeps(deps);

  const validation = handlerDeps.validateOrderSubmission({
    orderer,
    recipient,
    addressSelection,
    paymentMethod,
    bankAccount,
    depositName,
    guestPassword,
    isMemberOrder,
    agreeTerms,
    agreePrivacy,
    taxRequest,
    taxCompany,
    taxBusinessNo,
    taxInvoiceEmail,
    cashRequest,
    cashReceiptType,
    cashReceiptIdentityNumber,
  });

  if (!validation.ok) {
    if (validation.message) handlerDeps.toastError(validation.message);
    return;
  }
  const { methodDef } = validation;

  setSubmitting(true);
  setPaymentNotice(null);

  const orderBody = handlerDeps.buildOrderBody({
    orderer,
    recipient,
    addressSelection,
    saveAsNewAddress,
    newAddressSubject,
    newAddressDefault,
    email,
    memo,
    hopeDate,
    taxRequest,
    taxCompany,
    taxBusinessNo,
    taxInvoiceEmail,
    cashRequest,
    cashReceiptType,
    cashReceiptIdentityNumber,
    guestPassword,
    isMemberOrder,
    methodDef,
    selectedCouponId,
    selectedSendCouponId,
    pointUse,
    directCheckout,
    directCtIds,
    paymentDevice: handlerDeps.isMobileDevice() ? "mobile" : "pc",
  });

  if (methodDef.value === "bank") {
    await handlerDeps.submitBankOrder({
      orderBody,
      bankAccount,
      depositName,
      router,
      setSubmitting,
    });
    return;
  }

  await handlerDeps.submitPaymentOrder({
    orderBody,
    paymentConfig,
    methodDef,
    origin,
    router,
    setSubmitting,
    setPaymentNotice,
  });
}
