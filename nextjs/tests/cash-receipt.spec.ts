import { expect, test } from "@playwright/test";
import {
  cashReceiptIdentityPlaceholder,
  isCashReceiptType,
  normalizeCashReceiptIdentity,
} from "../src/lib/cash-receipt";

test.describe("cash receipt identity", () => {
  test("keeps only the digits of a phone number for 소득공제", () => {
    expect(normalizeCashReceiptIdentity("income", " 010-1234-5678 ")).toEqual({
      digits: "01012345678",
      error: "",
    });
  });

  test("accepts a cash receipt card number up to 30 digits", () => {
    expect(normalizeCashReceiptIdentity("income", "1234 5678 9012 3456 789").error).toBe("");
    expect(normalizeCashReceiptIdentity("income", "1".repeat(31)).error).not.toBe("");
  });

  test("refuses a short number for 소득공제", () => {
    expect(normalizeCashReceiptIdentity("income", "1234").error).toContain("휴대폰번호");
  });

  test("takes exactly ten digits for 지출증빙", () => {
    expect(normalizeCashReceiptIdentity("expense", "123-45-67890")).toEqual({
      digits: "1234567890",
      error: "",
    });
    expect(normalizeCashReceiptIdentity("expense", "010-1234-5678").error).toContain("사업자등록번호");
  });

  test("knows the receipt types and their placeholders", () => {
    expect(isCashReceiptType("income")).toBe(true);
    expect(isCashReceiptType("expense")).toBe(true);
    expect(isCashReceiptType("gift")).toBe(false);
    expect(cashReceiptIdentityPlaceholder("expense")).toContain("사업자등록번호");
    expect(cashReceiptIdentityPlaceholder("income")).toContain("휴대폰번호");
  });
});
