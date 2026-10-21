/**
 * 현금영수증 발급 신청(영카트 shop/taxsave.php) 입력 검사 — 서버(gnu_jango/shop/cash_receipts.py
 * normalize_identity)와 같은 규칙: 지출증빙은 사업자등록번호 10자리, 소득공제는 휴대폰번호
 * 또는 현금영수증카드 번호(8~30자리). 숫자만 남겨 보낸다.
 */

export type CashReceiptType = "income" | "expense";

export interface CashReceiptIdentityResult {
  digits: string;
  error: string;
}

export const CASH_RECEIPT_TYPE_LABELS: Record<CashReceiptType, string> = {
  income: "소득공제",
  expense: "지출증빙",
};

export function isCashReceiptType(value: unknown): value is CashReceiptType {
  return value === "income" || value === "expense";
}

export function normalizeCashReceiptIdentity(
  type: CashReceiptType,
  value: string
): CashReceiptIdentityResult {
  const digits = String(value ?? "").replace(/\D+/g, "");
  if (type === "expense") {
    return digits.length === 10
      ? { digits, error: "" }
      : { digits, error: "사업자등록번호 10자리를 정확히 입력하세요." };
  }
  return digits.length >= 8 && digits.length <= 30
    ? { digits, error: "" }
    : { digits, error: "휴대폰번호 또는 현금영수증카드 번호를 정확히 입력하세요." };
}

export function cashReceiptIdentityPlaceholder(type: CashReceiptType): string {
  return type === "expense" ? "사업자등록번호 (예: 123-45-67890)" : "휴대폰번호 (예: 010-1234-5678)";
}
