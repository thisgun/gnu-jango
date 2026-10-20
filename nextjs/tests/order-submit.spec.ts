import { expect, test } from "@playwright/test";
import type { AddressForm } from "../src/app/shop/order/orderAddressHelpers";
import type { PayMethodDef } from "../src/app/shop/order/orderPaymentHelpers";
import {
  buildAddressBookPayload,
  buildOrderBody,
} from "../src/app/shop/order/orderSubmitPayload";
import {
  resolveRecipientAddress,
  shouldPersistAddress,
  validateHopeDate,
  validateOrderSubmission,
} from "../src/app/shop/order/orderSubmitValidation";
import { formatHopeDate } from "../src/lib/hope-date";

function address(overrides: Partial<AddressForm> = {}): AddressForm {
  return {
    name: "Orderer",
    tel: "02-1234-5678",
    hp: "010-1234-5678",
    zip: "12345",
    addr1: "Seoul",
    addr2: "101",
    addr3: "Extra",
    addr_jibeon: "N",
    ...overrides,
  };
}

/** No receipt requested: the fields the receipt options add to every submission. */
const noReceipts = {
  taxRequest: false,
  taxCompany: "",
  taxBusinessNo: "",
  taxInvoiceEmail: "",
  cashRequest: false,
  cashReceiptType: "income" as const,
  cashReceiptIdentityNumber: "",
};

const bankMethod: PayMethodDef = {
  value: "bank",
  label: "Bank",
  settle_case: "Bank transfer",
};

test.describe("order submit validation", () => {
  test("resolves recipient address based on address selection", () => {
    const orderer = address({ name: "Orderer" });
    const recipient = address({ name: "Recipient" });

    expect(resolveRecipientAddress(orderer, recipient, "same")).toBe(orderer);
    expect(resolveRecipientAddress(orderer, recipient, "new")).toBe(recipient);
    expect(resolveRecipientAddress(orderer, recipient, 3)).toBe(recipient);
  });

  test("persists only new addresses explicitly requested by the user", () => {
    expect(shouldPersistAddress("new", true)).toBe(true);
    expect(shouldPersistAddress("new", false)).toBe(false);
    expect(shouldPersistAddress("same", true)).toBe(false);
    expect(shouldPersistAddress(7, true)).toBe(false);
  });

  test("accepts a complete guest bank order with agreements", () => {
    const recipient = address({ name: "Recipient" });
    const result = validateOrderSubmission({
      ...noReceipts,
      orderer: address(),
      recipient,
      addressSelection: "new",
      paymentMethod: "bank",
      bankAccount: "Bank 123-456",
      depositName: "Buyer",
      guestPassword: "abc123",
      isMemberOrder: false,
      agreeTerms: true,
      agreePrivacy: true,
    });

    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.methodDef.value).toBe("bank");
    expect(result.recipient).toBe(recipient);
  });

  test("rejects missing required fields before order submission", () => {
    const validInput = {
      ...noReceipts,
      orderer: address(),
      recipient: address({ name: "Recipient" }),
      addressSelection: "new" as const,
      paymentMethod: "bank",
      bankAccount: "Bank 123-456",
      depositName: "Buyer",
      guestPassword: "abc123",
      isMemberOrder: false,
      agreeTerms: true,
      agreePrivacy: true,
    };

    expect(
      validateOrderSubmission({
        ...validInput,
        orderer: address({ hp: "" }),
      }).ok
    ).toBe(false);
    expect(
      validateOrderSubmission({
        ...validInput,
        recipient: address({ addr1: "" }),
      }).ok
    ).toBe(false);
    expect(
      validateOrderSubmission({
        ...validInput,
        depositName: "",
      }).ok
    ).toBe(false);
    expect(
      validateOrderSubmission({
        ...validInput,
        bankAccount: "",
      }).ok
    ).toBe(false);
    expect(
      validateOrderSubmission({
        ...validInput,
        guestPassword: "ab",
      }).ok
    ).toBe(false);
    expect(
      validateOrderSubmission({
        ...validInput,
        agreePrivacy: false,
      }).ok
    ).toBe(false);
  });
});

test.describe("hope date (희망배송일) validation", () => {
  const rule = { use: true, after: 3, min: "2026-10-23", max: "2026-10-29" };
  const validInput = {
    ...noReceipts,
    orderer: address(),
    recipient: address({ name: "Recipient" }),
    addressSelection: "new" as const,
    paymentMethod: "bank",
    bankAccount: "Bank 123-456",
    depositName: "Buyer",
    guestPassword: "abc123",
    isMemberOrder: false,
    agreeTerms: true,
    agreePrivacy: true,
  };

  test("is not checked while the shop does not use it", () => {
    expect(validateHopeDate("", null)).toBeNull();
    expect(validateHopeDate("junk", { ...rule, use: false })).toBeNull();
    expect(validateOrderSubmission({ ...validInput, hopeDate: "", hopeDateRule: { ...rule, use: false } }).ok).toBe(true);
  });

  test("requires a real date inside the allowed range while it is used", () => {
    expect(validateHopeDate("", rule)).toBe("희망배송일을 선택하여 주십시오.");
    expect(validateHopeDate("2026-02-30", rule)).toBe("희망배송일이 올바르지 않습니다.");
    expect(validateHopeDate("2026-10-22", rule)).toContain("2026-10-23 부터 2026-10-29");
    expect(validateHopeDate("2026-10-30", rule)).toContain("사이에서 선택해 주십시오");
    expect(validateHopeDate("2026-10-23", rule)).toBeNull();
    expect(validateHopeDate("2026-10-29", rule)).toBeNull();

    const missing = validateOrderSubmission({ ...validInput, hopeDateRule: rule });
    expect(missing.ok).toBe(false);
    if (!missing.ok) expect(missing.message).toBe("희망배송일을 선택하여 주십시오.");
    expect(validateOrderSubmission({ ...validInput, hopeDate: "2026-10-25", hopeDateRule: rule }).ok).toBe(true);
  });

  test("formats the date with its Korean weekday", () => {
    expect(formatHopeDate("2026-10-25")).toBe("2026-10-25 (일)");
    expect(formatHopeDate("2026-10-26")).toBe("2026-10-26 (월)");
    expect(formatHopeDate("not-a-date")).toBe("not-a-date");
  });
});

test.describe("order submit payload", () => {
  test("builds address book payload with zip split and fallback subject", () => {
    const payload = buildAddressBookPayload(
      address({
        name: "Recipient",
        tel: "02-0000-0000",
        hp: "010-0000-0000",
        zip: "54321",
        addr1: "Busan",
        addr2: "202",
        addr3: "",
        addr_jibeon: "Y",
      }),
      "",
      true
    );

    expect(payload).toEqual({
      ad_subject: "Recipient",
      ad_default: 1,
      ad_name: "Recipient",
      ad_tel: "02-0000-0000",
      ad_hp: "010-0000-0000",
      ad_zip1: "543",
      ad_zip2: "21",
      ad_addr1: "Busan",
      ad_addr2: "202",
      ad_addr3: "",
      ad_jibeon: "Y",
    });
  });

  test("builds guest order body with optional checkout fields", () => {
    const body = buildOrderBody({
      ...noReceipts,
      orderer: address({
        name: "Buyer",
        tel: "02-1111-2222",
        hp: "010-1111-2222",
        zip: "12345",
        addr1: "Seoul",
        addr2: "1F",
        addr3: "",
        addr_jibeon: "N",
      }),
      recipient: address({
        name: "Receiver",
        tel: "02-3333-4444",
        hp: "010-3333-4444",
        zip: "67890",
        addr1: "Incheon",
        addr2: "2F",
        addr3: "Door",
        addr_jibeon: "Y",
      }),
      addressSelection: "new",
      saveAsNewAddress: true,
      newAddressSubject: "",
      newAddressDefault: true,
      email: "buyer@example.com",
      memo: "Leave at door",
      hopeDate: "2026-06-20",
      taxRequest: true,
      cashRequest: true,
      guestPassword: "  guest123  ",
      isMemberOrder: false,
      methodDef: bankMethod,
      selectedCouponId: "coupon-order",
      selectedSendCouponId: "coupon-send",
      pointUse: 1200,
      directCheckout: true,
      directCtIds: "10,11",
      paymentDevice: "mobile",
    });

    expect(body).toMatchObject({
      od_name: "Buyer",
      od_email: "buyer@example.com",
      od_b_name: "Receiver",
      od_b_zip1: "678",
      od_b_zip2: "90",
      od_memo: "Leave at door",
      ad_subject: "Receiver",
      ad_default: 1,
      save_address: 1,
      od_settle_case: "Bank transfer",
      od_pwd: "guest123",
      ct_ids: "10,11",
      direct: 1,
      cp_id: "coupon-order",
      cp_id_send: "coupon-send",
      point_use: 1200,
      od_hope_date: "2026-06-20",
      payment_device: "mobile",
    });
    // receipt requests are kept on member orders only
    expect(body).not.toHaveProperty("od_tax_invoice_request");
    expect(body).not.toHaveProperty("od_cash_request");
  });

  test("omits guest and optional fields for member orders", () => {
    const body = buildOrderBody({
      ...noReceipts,
      orderer: address({ name: "Member" }),
      recipient: address({ name: "Ignored recipient" }),
      addressSelection: "same",
      saveAsNewAddress: true,
      newAddressSubject: "Home",
      newAddressDefault: true,
      email: "member@example.com",
      memo: "",
      hopeDate: "",
      taxRequest: false,
      cashRequest: false,
      guestPassword: "guest123",
      isMemberOrder: true,
      methodDef: bankMethod,
      selectedCouponId: "",
      selectedSendCouponId: "",
      pointUse: 0,
      directCheckout: false,
      directCtIds: "",
      paymentDevice: "pc",
    });

    expect(body.od_b_name).toBe("Member");
    expect(body.od_b_zip1).toBe("123");
    expect(body.od_b_zip2).toBe("45");
    expect(body).not.toHaveProperty("od_pwd");
    expect(body).not.toHaveProperty("save_address");
    expect(body).not.toHaveProperty("cp_id");
    expect(body).not.toHaveProperty("point_use");
    expect(body).not.toHaveProperty("direct");
    expect(body.payment_device).toBe("pc");
  });
});

test.describe("receipt requests", () => {
  const transferMethod: PayMethodDef = { value: "iche", label: "Transfer", settle_case: "계좌이체" };
  const memberTransfer = {
    ...noReceipts,
    orderer: address(),
    recipient: address({ name: "Recipient" }),
    addressSelection: "new" as const,
    paymentMethod: "iche",
    bankAccount: "",
    depositName: "",
    guestPassword: "",
    isMemberOrder: true,
    agreeTerms: true,
    agreePrivacy: true,
  };
  const validTax = {
    taxRequest: true,
    taxCompany: "주식회사 예시",
    taxBusinessNo: "123-45-67890",
    taxInvoiceEmail: "tax@example.test",
  };

  test("a member tax invoice needs a company, a 10-digit business number and an email", () => {
    expect(validateOrderSubmission({ ...memberTransfer, ...validTax }).ok).toBe(true);
    for (const broken of [{ taxCompany: " " }, { taxBusinessNo: "123-45" }, { taxInvoiceEmail: "nope" }]) {
      const result = validateOrderSubmission({ ...memberTransfer, ...validTax, ...broken });
      expect(result.ok).toBe(false);
    }
  });

  test("a guest's hidden tax invoice option never blocks the order", () => {
    const guestBank = {
      ...memberTransfer,
      paymentMethod: "bank",
      bankAccount: "Bank 123-456",
      depositName: "Buyer",
      guestPassword: "abc123",
      isMemberOrder: false,
    };
    expect(validateOrderSubmission({ ...guestBank, taxRequest: true }).ok).toBe(true);
  });

  test("transfer cash receipts check the identification number for the receipt type", () => {
    const cash = { ...memberTransfer, cashRequest: true };
    expect(validateOrderSubmission({ ...cash, cashReceiptIdentityNumber: "010-1234-5678" }).ok).toBe(true);
    expect(validateOrderSubmission({ ...cash, cashReceiptIdentityNumber: "1234" }).ok).toBe(false);
    expect(
      validateOrderSubmission({ ...cash, cashReceiptType: "expense", cashReceiptIdentityNumber: "010-1234-5678" }).ok
    ).toBe(false);
    expect(
      validateOrderSubmission({ ...cash, cashReceiptType: "expense", cashReceiptIdentityNumber: "123-45-67890" }).ok
    ).toBe(true);
  });

  test("the order body carries receipt details only for members, digits only", () => {
    const base = {
      ...noReceipts,
      orderer: address(),
      recipient: address(),
      addressSelection: "same" as const,
      saveAsNewAddress: false,
      newAddressSubject: "",
      newAddressDefault: false,
      email: "member@example.com",
      memo: "",
      hopeDate: "",
      guestPassword: "",
      isMemberOrder: true,
      methodDef: transferMethod,
      selectedCouponId: "",
      selectedSendCouponId: "",
      pointUse: 0,
      directCheckout: false,
      directCtIds: "",
      paymentDevice: "pc" as const,
    };
    const member = buildOrderBody({
      ...base,
      ...validTax,
      cashRequest: true,
      cashReceiptType: "income",
      cashReceiptIdentityNumber: "010-1234-5678",
    });
    expect(member).toMatchObject({
      od_tax_invoice_request: 1,
      od_tax_company: "주식회사 예시",
      od_tax_business_no: "1234567890",
      od_tax_email: "tax@example.test",
      od_cash_request: 1,
      od_cash_type: "income",
      cash_receipt_registration_number: "01012345678",
    });

    const bankMember = buildOrderBody({ ...base, methodDef: bankMethod, cashRequest: true });
    expect(bankMember.od_cash_request).toBe(1);
    expect(bankMember).not.toHaveProperty("cash_receipt_registration_number");

    const guest = buildOrderBody({ ...base, ...validTax, cashRequest: true, isMemberOrder: false });
    expect(guest).not.toHaveProperty("od_tax_invoice_request");
    expect(guest).not.toHaveProperty("od_cash_request");
  });
});
