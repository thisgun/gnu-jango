import {
  type AddressForm,
  type AddressSelection,
} from "./orderAddressHelpers";
import {
  PAYMENT_METHODS,
  type HopeDateRule,
  type PayMethodDef,
} from "./orderPaymentHelpers";
import {
  isValidKoreanPhone,
  isValidKoreanZip,
} from "@/lib/address-validation";
import { parseIsoDate } from "@/lib/hope-date";

type ValidateOrderSubmissionInput = {
  orderer: AddressForm;
  recipient: AddressForm;
  addressSelection: AddressSelection;
  paymentMethod: string;
  bankAccount: string;
  depositName: string;
  guestPassword: string;
  isMemberOrder: boolean;
  agreeTerms: boolean;
  agreePrivacy: boolean;
  taxRequest: boolean;
  taxCompany: string;
  taxBusinessNo: string;
  taxInvoiceEmail: string;
  cashRequest: boolean;
  cashReceiptType: "income" | "expense";
  cashReceiptIdentityNumber: string;
  /** 희망배송일 and the shop's rule; checked only while the rule is on. */
  hopeDate?: string;
  hopeDateRule?: HopeDateRule | null;
};

export type OrderSubmitValidationResult =
  | {
      ok: true;
      methodDef: PayMethodDef;
      recipient: AddressForm;
    }
  | {
      ok: false;
      message?: string;
    };

function hasRequiredAddressFields(address: AddressForm): boolean {
  return !!(address.name && address.hp && address.zip && address.addr1);
}

function validateAddressFormat(
  address: AddressForm,
  label: string
): string | null {
  if (!isValidKoreanPhone(address.hp)) {
    return `${label} 휴대폰 번호를 올바르게 입력해 주세요.`;
  }
  if (!isValidKoreanZip(address.zip)) {
    return `${label} 우편번호는 5자리 숫자로 입력해 주세요.`;
  }
  return null;
}

export function resolveRecipientAddress(
  orderer: AddressForm,
  recipient: AddressForm,
  addressSelection: AddressSelection
): AddressForm {
  return addressSelection === "same" ? orderer : recipient;
}

/** YoungCart orderform: while 희망배송일 is on a date inside [min, max] must be chosen. */
export function validateHopeDate(
  hopeDate: string,
  rule: HopeDateRule | null | undefined
): string | null {
  if (!rule?.use) return null;
  const value = hopeDate.trim();
  if (!value) return "희망배송일을 선택하여 주십시오.";
  if (!parseIsoDate(value)) return "희망배송일이 올바르지 않습니다.";
  if (value < rule.min || value > rule.max) {
    return `희망배송일은 ${rule.min} 부터 ${rule.max} 사이에서 선택해 주십시오.`;
  }
  return null;
}

export function shouldPersistAddress(
  addressSelection: AddressSelection,
  saveAsNewAddress: boolean
): boolean {
  return addressSelection === "new" && saveAsNewAddress;
}

export function validateOrderSubmission({
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
  hopeDate = "",
  hopeDateRule = null,
}: ValidateOrderSubmissionInput): OrderSubmitValidationResult {
  if (!hasRequiredAddressFields(orderer)) {
    return { ok: false, message: "주문자 정보를 모두 입력해주세요." };
  }

  const ordererFormatError = validateAddressFormat(orderer, "주문자");
  if (ordererFormatError) {
    return { ok: false, message: ordererFormatError };
  }

  const resolvedRecipient = resolveRecipientAddress(
    orderer,
    recipient,
    addressSelection
  );
  if (!hasRequiredAddressFields(resolvedRecipient)) {
    return { ok: false, message: "받으시는 분 정보를 모두 입력해주세요." };
  }

  const recipientFormatError = validateAddressFormat(
    resolvedRecipient,
    "받는 분"
  );
  if (recipientFormatError) {
    return { ok: false, message: recipientFormatError };
  }

  const hopeDateError = validateHopeDate(hopeDate, hopeDateRule);
  if (hopeDateError) {
    return { ok: false, message: hopeDateError };
  }

  const methodDef = PAYMENT_METHODS.find(
    (method) => method.value === paymentMethod
  );
  if (!methodDef) return { ok: false };

  // Receipt options are shown to members only and buildOrderBody sends them only for members, so a
  // guest's (hidden) tax invoice state must not block the order.
  if (taxRequest && isMemberOrder) {
    if (!taxCompany.trim()) {
      return { ok: false, message: "세금계산서 상호명을 입력해 주세요." };
    }
    if (taxBusinessNo.replace(/\D/g, "").length !== 10) {
      return {
        ok: false,
        message: "세금계산서 사업자등록번호 10자리를 입력해 주세요.",
      };
    }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(taxInvoiceEmail.trim())) {
      return {
        ok: false,
        message: "세금계산서를 받을 이메일 주소를 확인해 주세요.",
      };
    }
  }

  if (cashRequest && isMemberOrder && methodDef.value !== "bank") {
    const identityLength = cashReceiptIdentityNumber.replace(/\D/g, "").length;
    const identityIsValid =
      cashReceiptType === "expense"
        ? identityLength === 10
        : identityLength >= 8 && identityLength <= 30;
    if (!identityIsValid) {
      return {
        ok: false,
        message:
          cashReceiptType === "expense"
            ? "현금영수증 지출증빙 사업자등록번호 10자리를 입력해 주세요."
            : "현금영수증 발급 번호를 확인해 주세요.",
      };
    }
  }

  if (methodDef.value === "bank" && !depositName) {
    return { ok: false, message: "입금자명을 입력해주세요." };
  }
  if (methodDef.value === "bank" && !bankAccount) {
    return {
      ok: false,
      message: "무통장 입금 계좌가 설정되어 있지 않습니다.",
    };
  }

  if (!isMemberOrder && !/^[A-Za-z0-9]{3,}$/.test(guestPassword.trim())) {
    return {
      ok: false,
      message:
        "비회원 주문조회에 사용할 비밀번호를 영문/숫자 3자리 이상 입력해주세요.",
    };
  }

  if (!agreeTerms || !agreePrivacy) {
    return { ok: false, message: "필수 약관에 동의해주세요." };
  }

  return { ok: true, methodDef, recipient: resolvedRecipient };
}
