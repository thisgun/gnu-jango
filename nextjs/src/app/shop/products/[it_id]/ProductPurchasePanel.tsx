"use client";

import { ChevronLeft, ChevronRight, CreditCard, Heart, Mail, Star } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { Button } from "@/components/ui/button";
import { ShareButtons } from "@/components/ShareButtons";
import type { BbsRewriteMode } from "@/lib/board-url";
import { plainTextSummary } from "@/lib/client-metadata";
import { g5ShortHref } from "@/lib/g5-short-url";
import { shopProductHref } from "@/lib/product-url";
import {
  formatProductPrice,
  hasProductDiscount,
  productDiscountPercent,
} from "@/lib/shop-product-state";
import { cn, formatPrice } from "@/lib/utils";
import {
  ProductPurchaseControls,
  type ProductPurchaseControlsProps,
} from "./ProductPurchaseControls";
import type { ProductNaverPayActions } from "./useProductNaverPay";

export type ShippingPaymentDisplay = {
  label: string;
  value: string;
  detail?: string;
  selectable: boolean;
};

export type ProductPurchasePanelProps = ProductPurchaseControlsProps & {
  productRewriteMode: BbsRewriteMode;
  pointLabel: string;
  shippingPayment: ShippingPaymentDisplay;
  ctSendCostSelection: number;
  onCtSendCostSelectionChange: (value: number) => void;
  /** 지인에게 메일로 추천 창 열기 */
  onOpenRecommendDialog: () => void;
  /** 네이버페이가 켜진 쇼핑몰에서만 준다. */
  naverPay: ProductNaverPayActions | null;
};

/** 깨진 글자(U+FFFD)가 섞인 옛 데이터는 보이지 않게 비운다. */
function cleanText(value: string | null | undefined) {
  const text = value?.trim() ?? "";
  return text.includes("�") ? "" : text;
}

/**
 * 상품 상세 오른쪽 구매 패널 — 레퍼런스 앱 ProductPurchasePanel 의 마크업과 이름(product-*)을 그대로 쓴다.
 * 테마 CSS(solune-shop.detail.css)가 이 이름들을 손잡이로 flex order 와 간격을 정한다 — 마크업 순서는 레퍼런스와 같게 둔다.
 * 이 앱에만 있는 것: 지인에게 메일 추천 단추, 네이버페이 구매 · 찜(.product-naverpay), 깨진 브랜드 · 요약 글자 거르기.
 */
export function ProductPurchasePanel({
  productRewriteMode,
  pointLabel,
  shippingPayment,
  ctSendCostSelection,
  onCtSendCostSelectionChange,
  onOpenRecommendDialog,
  naverPay,
  ...controlProps
}: ProductPurchasePanelProps) {
  const { product, isTelInquiry, canPurchaseProduct, isSoldOut } = controlProps;
  const brand = cleanText(product.it_brand);
  const subtitle = plainTextSummary(cleanText(product.it_basic), "");
  const hasDiscount = hasProductDiscount(product);
  const metaRows = (
    [
      ["제조사", product.it_maker],
      ["원산지", product.it_origin],
      ["모델명", product.it_model],
    ] as const
  ).flatMap(([label, value]) => {
    const text = cleanText(value);
    return text ? [{ label, value: text }] : [];
  });

  return (
    <div className="product-panel space-y-6">
      {product.ca_name ? (
        <a
          href={g5ShortHref(`/shop/categories/${product.ca_id}`)}
          className="product-brand text-sm text-muted-foreground hover:text-primary"
        >
          {brand || product.ca_name}
        </a>
      ) : brand ? (
        <p className="product-brand text-sm text-muted-foreground">{brand}</p>
      ) : null}

      <div className="product-title-row flex items-center justify-between gap-4">
        <h1 className="product-title min-w-0 break-words text-2xl font-bold">{product.it_name}</h1>
        {/* 지인에게 메일로 추천(이 앱에만 있다)은 공유 단추 줄 끝에 — 담기 줄은 레퍼런스처럼 [장바구니][바로구매][♡] 만. */}
        <div className="product-share flex items-center gap-1">
          <ShareButtons title={product.it_name} />
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            aria-label="지인에게 메일로 추천"
            title="지인에게 메일로 추천"
            onClick={onOpenRecommendDialog}
          >
            <Mail className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* 요약설명(it_basic)은 에디터 HTML 일 수 있다. 부제로는 글자만 쓴다 — 서식은 상품설명 탭이 낸다. */}
      {subtitle ? <p className="product-subtitle text-sm text-muted-foreground">{subtitle}</p> : null}

      {(product.prev_item || product.next_item) && (
        <nav aria-label="상품 이전 다음" className="product-siblings grid gap-2 text-sm sm:grid-cols-2">
          {product.prev_item ? (
            <Button variant="outline" className="h-auto justify-start gap-2 px-3 py-2 text-left" asChild>
              <Link href={shopProductHref(product.prev_item, productRewriteMode)}>
                <ChevronLeft className="size-4 shrink-0" />
                <span className="min-w-0">
                  <span className="block text-xs text-muted-foreground">이전 상품</span>
                  <span className="block truncate font-medium">{product.prev_item.it_name}</span>
                </span>
              </Link>
            </Button>
          ) : (
            <span className="hidden sm:block" />
          )}
          {product.next_item ? (
            <Button variant="outline" className="h-auto justify-end gap-2 px-3 py-2 text-right" asChild>
              <Link href={shopProductHref(product.next_item, productRewriteMode)}>
                <span className="min-w-0">
                  <span className="block text-xs text-muted-foreground">다음 상품</span>
                  <span className="block truncate font-medium">{product.next_item.it_name}</span>
                </span>
                <ChevronRight className="size-4 shrink-0" />
              </Link>
            </Button>
          ) : (
            <span className="hidden sm:block" />
          )}
        </nav>
      )}

      {product.review_count !== undefined && product.review_count > 0 && (
        <div className="product-rating flex items-center gap-2">
          <div className="product-rating-stars flex">
            {Array.from({ length: 5 }).map((_, index) => (
              <Star
                key={index}
                className={cn(
                  "h-4 w-4",
                  index < Math.round(product.review_avg ?? 0)
                    ? "fill-amber-400 text-amber-400"
                    : "text-muted-foreground/30"
                )}
              />
            ))}
          </div>
          <span className="product-rating-text text-sm text-muted-foreground">
            <b>{product.review_avg}</b>점 ({product.review_count}개 리뷰)
          </span>
        </div>
      )}

      <div className="product-price space-y-1">
        {hasDiscount && (
          <div className="product-price-before flex items-center gap-2">
            <span className="product-price-was text-sm text-muted-foreground line-through">
              {formatPrice(product.it_cust_price)}
            </span>
            <span className="product-price-off rounded bg-red-500 px-1.5 py-0.5 text-xs font-bold text-white">
              {productDiscountPercent(product)}% OFF
            </span>
          </div>
        )}
        <p className="product-price-now text-3xl font-bold">{formatProductPrice(product)}</p>
        {!isTelInquiry && pointLabel && (
          <p className="product-price-point text-sm text-muted-foreground">적립 포인트: {pointLabel}</p>
        )}
      </div>

      <div className="product-shipping rounded-md border bg-muted/30 p-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="product-shipping-label font-medium">{shippingPayment.label}</span>
          {shippingPayment.selectable ? (
            <select
              aria-label="배송비 결제 방법"
              data-shop-send-cost-select="1"
              value={ctSendCostSelection}
              onChange={(event) => onCtSendCostSelectionChange(Number(event.target.value))}
              className="h-9 min-w-[140px] rounded-md border bg-background px-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            >
              <option value={0}>주문시 결제</option>
              <option value={1}>수령후 지불</option>
            </select>
          ) : (
            <span className="font-medium text-foreground">{shippingPayment.value}</span>
          )}
        </div>
        {shippingPayment.detail && (
          <p className="mt-2 text-xs text-muted-foreground">{shippingPayment.detail}</p>
        )}
      </div>

      {/* 제조사 · 원산지 · 모델명. 값이 있는 항목만 — 빈 줄이 늘어서면 정보가 아니라 잡음이 된다. */}
      {metaRows.length > 0 && (
        <dl className="product-meta grid gap-[0.4rem]">
          {metaRows.map(({ label, value }) => (
            <div key={label} className="product-meta-row grid grid-cols-[5.5rem_minmax(0,1fr)] gap-2">
              <dt>{label}</dt>
              <dd className="m-0 min-w-0 break-words">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      <div className="product-stock text-sm">
        {isTelInquiry ? (
          <span className="font-medium text-primary">전화문의 상품</span>
        ) : isSoldOut ? (
          <span className="font-medium text-red-700">품절</span>
        ) : product.it_stock_qty > 0 ? (
          <span className="text-green-700">재고: {product.it_stock_qty}개</span>
        ) : (
          <span className="text-green-700">재고 있음</span>
        )}
      </div>

      <ProductPurchaseControls {...controlProps} />

      {naverPay && canPurchaseProduct && (
        <div className="product-naverpay grid gap-2 sm:grid-cols-2">
          <Button
            type="button"
            className="bg-[#0c8040] text-white hover:bg-[#08783a]"
            onClick={naverPay.onOrder}
            disabled={naverPay.submitting}
          >
            <CreditCard className="mr-2 h-4 w-4" />
            {naverPay.submitting ? "네이버페이 등록 중..." : "N Pay 구매"}
          </Button>
          <Button
            type="button"
            variant="outline"
            className="border-[#0c8040]/50 text-[#0c8040] hover:bg-[#0c8040]/10"
            onClick={naverPay.onWish}
            disabled={naverPay.wishSubmitting}
          >
            <Heart className="mr-2 h-4 w-4" />
            {naverPay.wishSubmitting ? "찜 등록 중..." : "N Pay 찜"}
          </Button>
        </div>
      )}
    </div>
  );
}
