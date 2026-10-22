"use client";

import { useEffect, useId, useState, type KeyboardEvent, type ReactNode } from "react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { Button } from "@/components/ui/button";
import type {
  ShopPolicy,
  ShopProduct,
  ShopProductInfoItem,
  ShopQA,
  ShopReview,
  ShopReviewSummary,
} from "@/lib/api";
import { cn, formatPrice } from "@/lib/utils";
import { sanitizeCommerceHtml } from "@/lib/sanitize";
import { ReviewForm, QaForm, QaListItem } from "./ProductReviewQaForms";
import { ReviewList, ReviewPager, ReviewSummaryBox } from "./ProductReviewList";

export type ProductDetailTab = {
  id: string;
  label: string;
  /** 후기 · 문의 건수 — 라벨 옆에 옅은 숫자로 붙는다. */
  count?: number;
};

type ReviewScore = NonNullable<ShopReviewSummary["scores"]>[number];

export function ProductDetailTabs({
  activeTab,
  onActiveTabChange,
  tabs,
  product,
  productInfoItems,
  canWriteReview,
  canWriteQa,
  shippingPolicy,
  legacyProductForm,
  onReviewSubmitted,
  onQaSubmitted,
  reviews,
  reviewPage,
  reviewLastPage,
  focusReviewId,
  onReviewPageChange,
  reviewSummary,
  reviewAverage,
  reviewTotal,
  reviewScores,
  qas,
  qaPage,
  qaLastPage,
  qaTotal,
  focusQaId,
  onQaPageChange,
  onQaChanged,
  shippingFreeThreshold,
  purchaseControls,
}: {
  activeTab: string;
  onActiveTabChange: (tabId: string) => void;
  tabs: ProductDetailTab[];
  product: ShopProduct;
  productInfoItems: ShopProductInfoItem[];
  canWriteReview: boolean;
  canWriteQa: boolean;
  shippingPolicy: ShopPolicy | null;
  legacyProductForm: string;
  onReviewSubmitted: () => void;
  onQaSubmitted: () => void;
  reviews: ShopReview[];
  reviewPage: number;
  reviewLastPage: number;
  focusReviewId: number;
  onReviewPageChange: (page: number) => void;
  reviewSummary: ShopReviewSummary | null;
  reviewAverage: number;
  reviewTotal: number;
  reviewScores: ReviewScore[];
  qas: ShopQA[];
  qaPage: number;
  qaLastPage: number;
  qaTotal: number;
  focusQaId: number;
  onQaPageChange: (page: number) => void;
  onQaChanged: () => void;
  shippingFreeThreshold: number;
  /** 넓은 화면에서 본문 옆에 따라다니는 구매 상자의 알맹이(ProductPurchaseControls). */
  purchaseControls?: ReactNode;
}) {
  const baseId = useId();
  const activeIndex = Math.max(0, tabs.findIndex((tab) => tab.id === activeTab));
  const tabId = (id: string) => `${baseId}-${id}-tab`;
  const panelId = (id: string) => `${baseId}-${id}-panel`;

  const focusTab = (nextIndex: number) => {
    const nextTab = tabs[nextIndex];
    if (!nextTab) return;
    onActiveTabChange(nextTab.id);
    window.setTimeout(() => document.getElementById(tabId(nextTab.id))?.focus(), 0);
  };

  const handleTabKeyDown = (
    event: KeyboardEvent<HTMLButtonElement>,
    index: number
  ) => {
    if (tabs.length === 0) return;
    if (event.key === "ArrowRight") {
      event.preventDefault();
      focusTab((index + 1) % tabs.length);
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      focusTab((index - 1 + tabs.length) % tabs.length);
    } else if (event.key === "Home") {
      event.preventDefault();
      focusTab(0);
    } else if (event.key === "End") {
      event.preventDefault();
      focusTab(tabs.length - 1);
    }
  };

  /* 레퍼런스 Solune 테마 product-detail-tabs(#sit_info): 왼쪽에 탭 띠와 본문, 넓은 화면에서는 오른쪽에
     따라다니는 구매 상자(선택옵션 · 고른 옵션 · 합계 · 담기/사기). 모양은 solune-shop.detail.css 의 solune-pdp-*. */
  return (
    <section className={cn("solune-pdp-body", purchaseControls && "has-aside")}>
      <div className="solune-pdp-main">
        <div role="tablist" aria-label="상품 상세 정보" className="solune-pdp-tabs">
          {tabs.map((tab, index) => (
            <button
              key={tab.id}
              id={tabId(tab.id)}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              aria-controls={panelId(tab.id)}
              tabIndex={activeTab === tab.id ? 0 : -1}
              onClick={() => onActiveTabChange(tab.id)}
              onKeyDown={(event) => handleTabKeyDown(event, index)}
              className={cn(
                "solune-pdp-tab focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
                activeTab === tab.id && "is-selected"
              )}
            >
              {tab.label}
              {tab.count !== undefined ? (
                <span className="solune-pdp-tab-count">{tab.count.toLocaleString()}</span>
              ) : null}
            </button>
          ))}
        </div>
  
        <div
          id={panelId(activeTab)}
          role="tabpanel"
          tabIndex={0}
          aria-labelledby={tabId(tabs[activeIndex]?.id ?? activeTab)}
          className="product-tabpanel py-6"
        >
          {activeTab === "description" && (
            <DescriptionTab product={product} productInfoItems={productInfoItems} />
          )}
  
          {activeTab === "reviews" && (
            <ReviewsTab
              product={product}
              canWriteReview={canWriteReview}
              shippingPolicy={shippingPolicy}
              legacyProductForm={legacyProductForm}
              onReviewSubmitted={onReviewSubmitted}
              reviews={reviews}
              reviewPage={reviewPage}
              reviewLastPage={reviewLastPage}
              focusReviewId={focusReviewId}
              onPageChange={onReviewPageChange}
              reviewSummary={reviewSummary}
              reviewAverage={reviewAverage}
              reviewTotal={reviewTotal}
              reviewScores={reviewScores}
            />
          )}
  
          {activeTab === "qa" && (
            <QaTab
              product={product}
              canWriteQa={canWriteQa}
              legacyProductForm={legacyProductForm}
              onQaSubmitted={onQaSubmitted}
              qas={qas}
              page={qaPage}
              lastPage={qaLastPage}
              total={qaTotal}
              focusQaId={focusQaId}
              onPageChange={onQaPageChange}
              onQaChanged={onQaChanged}
            />
          )}
  
          {activeTab === "shipping" && (
            <ShippingTab
              shippingPolicy={shippingPolicy}
              shippingFreeThreshold={shippingFreeThreshold}
            />
          )}
        </div>
      </div>
      {purchaseControls ? (
        <aside className="solune-pdp-aside" aria-label="구매 옵션">
          <p className="solune-pdp-aside-eyebrow">선택옵션</p>
          {purchaseControls}
        </aside>
      ) : null}
    </section>
  );
}

function hasVisibleDescriptionContent(html: string): boolean {
  const text = html
    .replace(/<\s*(script|style)\b[^>]*>[\s\S]*?<\s*\/\s*\1\s*>/gi, " ")
    .replace(/<[^>]*>/g, " ")
    .replace(/&nbsp;|&#160;|&#xA0;/gi, " ")
    .replace(/[\u00a0\u200b\uFEFF]/g, " ")
    .trim();

  return Boolean(text) || /<\s*(img|video|audio|iframe|object|embed|table)\b/i.test(html);
}

function DescriptionTab({
  product,
  productInfoItems,
}: {
  product: ShopProduct;
  productInfoItems: ShopProductInfoItem[];
}) {
  const descriptionHtml = [product.it_explan, product.it_basic]
    .map((html) => sanitizeCommerceHtml(html))
    .find(hasVisibleDescriptionContent);

  return (
    <div className="prose max-w-none">
      {descriptionHtml ? (
        <div dangerouslySetInnerHTML={{ __html: descriptionHtml }} />
      ) : (
        <p className="text-muted-foreground">상품 설명이 없습니다.</p>
      )}
      {productInfoItems.length > 0 && (
        <section className="not-prose mt-8 overflow-hidden rounded-lg border">
          <div className="border-b bg-muted/30 px-4 py-3">
            <h3 className="text-base font-semibold">
              {product.it_info_title || "상품 정보 고시"}
            </h3>
          </div>
          <div className="overflow-x-auto">
            <table id="sit_inf_open" className="w-full border-collapse text-sm">
              <tbody>
                {productInfoItems.map((item, index) => (
                  <tr key={`${item.key}-${index}`} className="border-b last:border-b-0">
                    <th
                      scope="row"
                      className="w-36 bg-muted/40 px-4 py-3 text-left align-top font-medium text-foreground sm:w-48"
                    >
                      {item.title || item.key}
                    </th>
                    <td
                      className="px-4 py-3 align-top text-muted-foreground"
                      dangerouslySetInnerHTML={{
                        __html: sanitizeCommerceHtml(item.value || "-"),
                      }}
                    />
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}

function ReviewsTab({
  product,
  canWriteReview,
  shippingPolicy,
  legacyProductForm,
  onReviewSubmitted,
  reviews,
  reviewPage,
  reviewLastPage,
  focusReviewId,
  onPageChange,
  reviewSummary,
  reviewAverage,
  reviewTotal,
  reviewScores,
}: {
  product: ShopProduct;
  canWriteReview: boolean;
  shippingPolicy: ShopPolicy | null;
  legacyProductForm: string;
  onReviewSubmitted: () => void;
  reviews: ShopReview[];
  reviewPage: number;
  reviewLastPage: number;
  focusReviewId: number;
  onPageChange: (page: number) => void;
  reviewSummary: ShopReviewSummary | null;
  reviewAverage: number;
  reviewTotal: number;
  reviewScores: ReviewScore[];
}) {
  // 쓰기 폼은 평점 요약 상자 오른쪽 [사용후기 쓰기]가 연다. 옛 주소 ?form=review 로 오면 처음부터 연다.
  const [formOpen, setFormOpen] = useWriteFormOpen(legacyProductForm === "review");
  const loginHref = loginHrefFor(product);
  return (
    <section className="product-reviews">
      <ReviewSummaryBox
        average={reviewAverage}
        total={reviewTotal}
        photoCount={reviewSummary?.photo_count ?? 0}
        scores={reviewScores}
        action={
          canWriteReview ? (
            <Button
              type="button"
              className={REVIEW_WRITE_CLASS}
              aria-expanded={formOpen}
              onClick={() => setFormOpen(!formOpen)}
            >
              사용후기 쓰기
            </Button>
          ) : (
            <Link
              href={loginHref}
              className={cn("inline-flex items-center justify-center", REVIEW_WRITE_CLASS)}
              title="로그인 후 쓸 수 있습니다"
            >
              사용후기 쓰기
            </Link>
          )
        }
      />
      {canWriteReview && formOpen && (
        <div className="mt-4">
          <ReviewForm
            itId={product.it_id}
            policy={shippingPolicy}
            open={formOpen}
            onOpenChange={setFormOpen}
            onSubmitted={onReviewSubmitted}
          />
        </div>
      )}
      <ReviewList
        reviews={reviews}
        total={reviewTotal}
        photoCount={reviewSummary?.photo_count ?? 0}
        focusReviewId={focusReviewId}
        pager={<ReviewPager page={reviewPage} lastPage={reviewLastPage} onPageChange={onPageChange} />}
      />
    </section>
  );
}

/** 쓰기 폼 여닫기 — 옛 주소(?form=review · ?form=qa)로 오면 처음부터 연다. */
function useWriteFormOpen(initialOpen: boolean) {
  const [open, setOpen] = useState(initialOpen);
  useEffect(() => {
    if (initialOpen) setOpen(true);
  }, [initialOpen]);
  return [open, setOpen] as const;
}

/** 로그인 뒤 이 상품으로 돌아오는 로그인 주소 */
function loginHrefFor(product: ShopProduct) {
  return `/login?redirect=${encodeURIComponent(`/shop/products/${product.it_id}`)}`;
}

// 레퍼런스 solune 쓰기 단추 — 후기는 초록 채움(모서리 10, 테마 CSS), 문의는 본문색 네모.
const REVIEW_WRITE_CLASS =
  "product-review-write h-11 rounded-md border-0 bg-primary px-6 text-[13.5px] font-semibold text-primary-foreground hover:bg-primary/90 hover:text-primary-foreground max-sm:w-full";
const QA_WRITE_CLASS =
  "product-qa-write h-9 rounded-none border-foreground bg-foreground px-4 text-[13px] font-bold text-background hover:bg-primary hover:text-primary-foreground";

function QaTab({
  product,
  canWriteQa,
  legacyProductForm,
  onQaSubmitted,
  qas,
  page,
  lastPage,
  total,
  focusQaId,
  onPageChange,
  onQaChanged,
}: {
  product: ShopProduct;
  canWriteQa: boolean;
  legacyProductForm: string;
  onQaSubmitted: () => void;
  qas: ShopQA[];
  page: number;
  lastPage: number;
  total: number;
  focusQaId: number;
  onPageChange: (page: number) => void;
  onQaChanged: () => void;
}) {
  // 쓰기 폼은 머리 오른쪽 [문의하기]가 연다. 옛 주소 ?form=qa 로 오면 처음부터 연다.
  const [formOpen, setFormOpen] = useWriteFormOpen(legacyProductForm === "qa");
  return (
    <section className="product-qa">
      <div className="product-qa-head flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-foreground pb-4">
        <h3 className="product-qa-title text-[15px] font-bold">
          상품문의 <span className="font-semibold tabular-nums text-muted-foreground">{total.toLocaleString()}</span>
        </h3>
        <div className="ml-auto">
          {canWriteQa ? (
            <Button
              type="button"
              className={cn("border", QA_WRITE_CLASS)}
              aria-expanded={formOpen}
              onClick={() => setFormOpen(!formOpen)}
            >
              문의하기
            </Button>
          ) : (
            <Link
              href={loginHrefFor(product)}
              className={cn("inline-flex items-center border", QA_WRITE_CLASS)}
              title="로그인 후 문의할 수 있습니다"
            >
              문의하기
            </Link>
          )}
        </div>
      </div>
      {canWriteQa && formOpen && (
        <div className="mt-4">
          <QaForm
            itId={product.it_id}
            open={formOpen}
            onOpenChange={setFormOpen}
            onSubmitted={onQaSubmitted}
          />
        </div>
      )}
      <p className="product-qa-notice mt-3.5 text-xs leading-relaxed text-muted-foreground">
        비밀글은 작성자와 관리자만 볼 수 있습니다. 주문·배송 문의는{" "}
        <Link href="/mypage/qas" className="text-foreground underline underline-offset-2">
          1:1문의
        </Link>
        를 이용해 주세요.
      </p>
      {qas.length === 0 ? (
        <p className="py-12 text-center text-sm text-muted-foreground">상품문의가 없습니다.</p>
      ) : (
        <ol className="product-qa-list mt-3">
          {qas.map((qa) => (
            <li key={qa.iq_id}>
              <QaListItem
                qa={qa}
                initiallyOpen={focusQaId === Number(qa.iq_id)}
                onChanged={onQaChanged}
              />
            </li>
          ))}
        </ol>
      )}
      <ReviewPager page={page} lastPage={lastPage} onPageChange={onPageChange} label="상품 문의" />
    </section>
  );
}

function ShippingTab({
  shippingPolicy,
  shippingFreeThreshold,
}: {
  shippingPolicy: ShopPolicy | null;
  shippingFreeThreshold: number;
}) {
  return (
    <div className="space-y-4 text-sm">
      <div className="rounded-lg border p-4">
        <h4 className="mb-2 font-medium">배송 안내</h4>
        {shippingPolicy?.delivery_content ? (
          <div
            className="prose prose-sm max-w-none text-muted-foreground"
            dangerouslySetInnerHTML={{
              __html: sanitizeCommerceHtml(shippingPolicy.delivery_content),
            }}
          />
        ) : (
          <ul className="space-y-1 text-muted-foreground">
            <li>- 배송비: 기본 배송비 참고</li>
            <li>- 배송 기간: 결제 확인 후 2~3일 이내 발송</li>
            <li>- 도서/산간 지역은 추가 배송비가 발생할 수 있습니다.</li>
          </ul>
        )}
        {shippingPolicy && (
          <dl className="mt-4 grid gap-2 rounded-md bg-muted/50 p-3 text-xs">
            {shippingPolicy.delivery_company && (
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">택배사</dt>
                <dd className="font-medium">{shippingPolicy.delivery_company}</dd>
              </div>
            )}
            {shippingFreeThreshold > 0 && (
              <div className="flex justify-between gap-4">
                <dt className="text-muted-foreground">무료배송 기준</dt>
                <dd className="font-medium">{formatPrice(shippingFreeThreshold)} 이상</dd>
              </div>
            )}
          </dl>
        )}
      </div>
      <div className="rounded-lg border p-4">
        <h4 className="mb-2 font-medium">교환/반품 안내</h4>
        {shippingPolicy?.exchange_content ? (
          <div
            className="prose prose-sm max-w-none text-muted-foreground"
            dangerouslySetInnerHTML={{
              __html: sanitizeCommerceHtml(shippingPolicy.exchange_content),
            }}
          />
        ) : (
          <ul className="space-y-1 text-muted-foreground">
            <li>- 상품 수령 후 7일 이내 교환/반품 가능</li>
            <li>- 고객 변심에 의한 교환/반품 시 배송비 고객 부담</li>
            <li>- 상품 하자 시 무료 교환/반품</li>
          </ul>
        )}
      </div>
    </div>
  );
}
