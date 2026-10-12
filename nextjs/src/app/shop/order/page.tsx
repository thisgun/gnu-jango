"use client";

import { useState } from "react";
import Script from "next/script";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { AddressBookModal } from "./AddressBookModal";
import { OrderAgreementsSection } from "./OrderAgreementsSection";
import { OrderCouponPointSection } from "./OrderCouponPointSection";
import { OrderItemsSummary } from "./OrderItemsSummary";
import { OrderPaymentMethodSection } from "./OrderPaymentMethodSection";
import { OrderSummarySidebar } from "./OrderSummarySidebar";
import { OrdererInfoSection } from "./OrdererInfoSection";
import { RecipientInfoSection } from "./RecipientInfoSection";
import { useOrderPageController } from "./useOrderPageController";

export default function OrderPage() {
  const [postcodeLoadFailed, setPostcodeLoadFailed] = useState(false);
  const {
    loading,
    inputClassName,
    isMemberOrder,
    items,
    paymentNoticeState,
    handleSubmit,
    ordererInfo,
    recipientInfo,
    paymentMethodSection,
    couponPointSection,
    agreements,
    summary,
    addressModal,
  } = useOrderPageController();

  if (loading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-8 w-40 rounded bg-muted" />
        <div className="h-64 rounded-lg bg-muted" />
      </div>
    );
  }

  return (
    <div>
      <Script
        src="//t1.daumcdn.net/mapjsapi/bundle/postcode/prod/postcode.v2.js"
        strategy="afterInteractive"
        onLoad={() => setPostcodeLoadFailed(false)}
        onError={() => setPostcodeLoadFailed(true)}
      />

      <Breadcrumb items={[{ label: "쇼핑몰", href: "/shop" }, { label: "장바구니", href: "/shop/cart" }, { label: "주문/결제" }]} />
      <h1 className="mb-6 text-2xl font-bold">주문/결제</h1>
      {postcodeLoadFailed && (
        <div
          className="mb-6 rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive"
          role="alert"
        >
          우편번호 검색 서비스를 불러오지 못했습니다. 우편번호와 주소를 직접 입력해 주세요.
        </div>
      )}
      {paymentNoticeState.paymentNotice && (
        <div
          className={`mb-6 rounded-md border px-4 py-3 text-sm ${paymentNoticeState.noticeClassName}`}
          role="alert"
        >
          <p className="font-semibold">{paymentNoticeState.paymentNotice.title}</p>
          {paymentNoticeState.paymentNotice.message !==
            paymentNoticeState.paymentNotice.title && (
            <p className="mt-1">{paymentNoticeState.paymentNotice.message}</p>
          )}
        </div>
      )}

      <form onSubmit={handleSubmit} className="min-w-0">
        <div className="grid min-w-0 gap-6 lg:grid-cols-3 lg:gap-8">
          <div className="min-w-0 space-y-6 lg:col-span-2 lg:space-y-8">
            <OrderItemsSummary items={items} />

            <OrdererInfoSection
              inputClassName={inputClassName}
              {...ordererInfo}
            />

            <RecipientInfoSection
              inputClassName={inputClassName}
              {...recipientInfo}
            />
            <OrderPaymentMethodSection
              inputClassName={inputClassName}
              {...paymentMethodSection}
            />
            {isMemberOrder && (
              <OrderCouponPointSection
                inputClassName={inputClassName}
                {...couponPointSection}
              />
            )}
            <OrderAgreementsSection {...agreements} />
          </div>

          <OrderSummarySidebar {...summary} />
        </div>
      </form>

      <AddressBookModal {...addressModal} />
    </div>
  );
}
