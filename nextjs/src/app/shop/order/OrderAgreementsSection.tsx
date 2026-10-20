"use client";

import { sanitizeCommerceHtml } from "@/lib/sanitize";

type OrderAgreementsSectionProps = {
  agreeAll: boolean;
  agreeTerms: boolean;
  setAgreeTerms: (checked: boolean) => void;
  agreePrivacy: boolean;
  setAgreePrivacy: (checked: boolean) => void;
  handleAgreeAll: (checked: boolean) => void;
  /** A guest (non-member) order shows the youngcart guest notes. */
  isGuestOrder?: boolean;
  /** 비회원 개인정보 수집 안내 (de_guest_privacy), already sanitized by the server. */
  guestPrivacyHtml?: string;
};

export function OrderAgreementsSection({
  agreeAll,
  agreeTerms,
  setAgreeTerms,
  agreePrivacy,
  setAgreePrivacy,
  handleAgreeAll,
  isGuestOrder = false,
  guestPrivacyHtml = "",
}: OrderAgreementsSectionProps) {
  // Sanitized on the server; sanitized again here so only safe markup reaches the page.
  const guestPrivacy = isGuestOrder ? sanitizeCommerceHtml(guestPrivacyHtml).trim() : "";

  return (
    <section className="shop-order-section shop-order-section--agree box-border w-full min-w-0 rounded-lg border p-4 sm:p-6">
      <h2 className="mb-4 text-lg font-bold">약관 동의</h2>
      <div className="space-y-3">
        <label className="shop-order-agree-all flex items-center gap-2 rounded-md border p-3 font-medium">
          <input
            type="checkbox"
            checked={agreeAll}
            onChange={(event) => handleAgreeAll(event.target.checked)}
            className="h-4 w-4 rounded"
          />
          전체 동의
        </label>
        <label className="flex items-center gap-2 pl-2 text-sm">
          <input
            type="checkbox"
            checked={agreeTerms}
            onChange={(event) => setAgreeTerms(event.target.checked)}
            className="h-4 w-4 rounded"
          />
          <span>[필수] 이용약관 동의</span>
        </label>
        {guestPrivacy && (
          <div
            className="shop-order-guest-privacy prose prose-sm ml-2 max-h-40 max-w-none overflow-y-auto rounded-md border bg-base-200/40 p-3 text-xs dark:prose-invert"
            role="region"
            tabIndex={0}
            aria-label="비회원 개인정보 수집 안내"
            dangerouslySetInnerHTML={{ __html: guestPrivacy }}
          />
        )}
        <label className="flex items-center gap-2 pl-2 text-sm">
          <input
            type="checkbox"
            checked={agreePrivacy}
            onChange={(event) => setAgreePrivacy(event.target.checked)}
            className="h-4 w-4 rounded"
          />
          <span>[필수] 개인정보 수집 및 이용 동의</span>
        </label>
        {isGuestOrder && (
          <p className="pl-2 text-xs text-base-content/60">
            비회원으로 주문하시면 포인트를 적립해 드리지 않습니다.
          </p>
        )}
      </div>
    </section>
  );
}
