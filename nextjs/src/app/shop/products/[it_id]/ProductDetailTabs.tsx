"use client";

import { useEffect, useId, useState, type KeyboardEvent } from "react";
import { ChevronDown, Star } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import type {
  ShopPolicy,
  ShopProduct,
  ShopProductInfoItem,
  ShopQA,
  ShopReview,
  ShopReviewSummary,
} from "@/lib/api";
import { cn, formatDate, formatPrice } from "@/lib/utils";
import { sanitizeCommerceHtml, sanitizeUserHtml } from "@/lib/sanitize";
import { ReviewForm, QaForm, QaListItem } from "./ProductReviewQaForms";

type ProductDetailTab = {
  id: string;
  label: string;
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

  return (
    <div className="mt-12 border-t pt-8">
      <div role="tablist" aria-label="상품 상세 정보" className="scrollbar-hide flex overflow-x-auto border-b">
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
              "shrink-0 whitespace-nowrap px-3 py-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring sm:px-4",
              activeTab === tab.id
                ? "border-b-2 border-primary text-primary"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div
        id={panelId(activeTab)}
        role="tabpanel"
        tabIndex={0}
        aria-labelledby={tabId(tabs[activeIndex]?.id ?? activeTab)}
        className="py-6"
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
                {productInfoItems.map((item) => (
                  <tr key={item.key} className="border-b last:border-b-0">
                    <th
                      scope="row"
                      className="w-36 bg-muted/40 px-4 py-3 text-left align-top font-medium text-foreground sm:w-48"
                    >
                      {item.title}
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
  return (
    <div className="space-y-4">
      {canWriteReview ? (
        <ReviewForm
          itId={product.it_id}
          policy={shippingPolicy}
          initialOpen={legacyProductForm === "review"}
          onSubmitted={onReviewSubmitted}
        />
      ) : (
        <div className="rounded-lg border p-4 text-sm text-muted-foreground">
          후기 작성은 로그인 후 가능합니다.{" "}
          <Link href="/login" className="text-primary hover:underline">
            로그인
          </Link>
        </div>
      )}
      <div className="grid gap-4 rounded-lg border p-4 md:grid-cols-[180px_1fr]">
        <div className="flex flex-col justify-center">
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold">{reviewAverage.toFixed(1)}</span>
            <span className="text-sm text-muted-foreground">/ 5</span>
          </div>
          <div className="mt-2 flex">
            {Array.from({ length: 5 }).map((_, index) => (
              <Star
                key={index}
                className={cn(
                  "h-4 w-4",
                  index < Math.round(reviewAverage)
                    ? "fill-amber-400 text-amber-400"
                    : "text-muted-foreground/30"
                )}
              />
            ))}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">
            리뷰 {reviewTotal.toLocaleString()}개
            {reviewSummary && ` · 사진 ${reviewSummary.photo_count.toLocaleString()}개`}
          </p>
        </div>
        <div className="space-y-2">
          {reviewScores.map((item) => (
            <div
              key={item.score}
              className="grid grid-cols-[36px_1fr_44px] items-center gap-2 text-xs"
            >
              <span className="text-muted-foreground">{item.score}점</span>
              <div className="h-2 overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-amber-400"
                  style={{ width: `${Math.min(100, Math.max(0, item.percentage))}%` }}
                />
              </div>
              <span className="text-right text-muted-foreground">
                {item.count.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </div>
      {reviews.length === 0 ? (
        <p className="py-8 text-center text-muted-foreground">아직 리뷰가 없습니다.</p>
      ) : (
        reviews.map((review) => (
          <ProductReviewItem
            key={review.is_id}
            review={review}
            initiallyOpen={focusReviewId === Number(review.is_id)}
          />
        ))
      )}
      {reviewLastPage > 1 && (
        <ReviewPagination
          page={reviewPage}
          lastPage={reviewLastPage}
          onPageChange={onPageChange}
        />
      )}
    </div>
  );
}

function ProductReviewItem({
  review,
  initiallyOpen,
}: {
  review: ShopReview;
  initiallyOpen: boolean;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  const contentId = useId();

  useEffect(() => {
    if (initiallyOpen) setOpen(true);
  }, [initiallyOpen]);

  return (
    <article
      id={`is_${review.is_id}`}
      data-review-id={review.is_id}
      tabIndex={-1}
      className="rounded-lg border p-4 outline-none transition-[background-color,box-shadow] data-[focused=true]:bg-primary/5 data-[focused=true]:ring-2 data-[focused=true]:ring-primary"
    >
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <div className="flex" aria-hidden="true">
            {Array.from({ length: 5 }).map((_, index) => (
              <Star
                key={index}
                aria-hidden="true"
                className={cn(
                  "h-3.5 w-3.5",
                  index < review.is_score
                    ? "fill-amber-400 text-amber-400"
                    : "text-muted-foreground/30"
                )}
              />
            ))}
          </div>
          <span className="sr-only">{review.is_score}점</span>
          <span className="text-sm font-medium">{review.mb_nick}</span>
        </div>
        <span className="text-xs text-muted-foreground">{formatDate(review.is_time)}</span>
      </div>
      <h4 className="font-medium">{review.is_subject}</h4>
      <div id={contentId} hidden={!open}>
        <div
          className="prose prose-sm mt-2 max-w-none text-sm text-muted-foreground"
          dangerouslySetInnerHTML={{ __html: sanitizeUserHtml(review.is_content) }}
        />
      </div>
      <button
        type="button"
        className="btn btn-ghost btn-sm mt-2 min-h-8 h-8 px-3 text-xs"
        aria-expanded={open}
        aria-controls={contentId}
        onClick={() => setOpen((current) => !current)}
      >
        {open ? "접기" : "내용 보기"}
        <ChevronDown
          aria-hidden="true"
          className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")}
        />
      </button>
    </article>
  );
}

function ReviewPagination({
  page,
  lastPage,
  onPageChange,
  label = "상품 후기",
}: {
  page: number;
  lastPage: number;
  onPageChange: (page: number) => void;
  label?: string;
}) {
  const pages: (number | "ellipsis-start" | "ellipsis-end")[] =
    lastPage <= 7
      ? Array.from({ length: lastPage }, (_, index) => index + 1)
      : [
          1,
          ...(page > 3 ? (["ellipsis-start"] as const) : []),
          ...[page - 1, page, page + 1].filter((value) => value > 1 && value < lastPage),
          ...(page < lastPage - 2 ? (["ellipsis-end"] as const) : []),
          lastPage,
        ];

  return (
    <nav className="mt-2 flex justify-center" aria-label={`${label} 페이지`}>
      <div className="join">
        <button
          type="button"
          className="btn btn-sm join-item"
          aria-label={`${label} 이전 페이지`}
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
        >
          이전
        </button>
        {pages.map((item) =>
          typeof item === "number" ? (
            <button
              key={item}
              type="button"
              className={cn("btn btn-sm join-item", item === page && "btn-active")}
              aria-label={`${item}페이지`}
              aria-current={item === page ? "page" : undefined}
              onClick={() => onPageChange(item)}
            >
              {item}
            </button>
          ) : (
            <span key={item} className="join-item px-2 py-2 text-sm" aria-hidden="true">
              …
            </span>
          )
        )}
        <button
          type="button"
          className="btn btn-sm join-item"
          aria-label={`${label} 다음 페이지`}
          disabled={page >= lastPage}
          onClick={() => onPageChange(page + 1)}
        >
          다음
        </button>
      </div>
    </nav>
  );
}

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
  return (
    <div className="space-y-4">
      {canWriteQa ? (
        <QaForm
          itId={product.it_id}
          initialOpen={legacyProductForm === "qa"}
          onSubmitted={onQaSubmitted}
        />
      ) : (
        <div className="rounded-lg border p-4 text-sm text-muted-foreground">
          문의 작성은 로그인 후 가능합니다.{" "}
          <Link href="/login" className="text-primary hover:underline">
            로그인
          </Link>
        </div>
      )}
      <p className="text-sm text-muted-foreground">상품문의 {total.toLocaleString()}개</p>
      {qas.length === 0 ? (
        <p className="py-8 text-center text-muted-foreground">아직 문의가 없습니다.</p>
      ) : (
        qas.map((qa) => (
          <QaListItem
            key={qa.iq_id}
            qa={qa}
            initiallyOpen={focusQaId === Number(qa.iq_id)}
            onChanged={onQaChanged}
          />
        ))
      )}
      {lastPage > 1 && (
        <ReviewPagination
          page={page}
          lastPage={lastPage}
          onPageChange={onPageChange}
          label="상품 문의"
        />
      )}
    </div>
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
