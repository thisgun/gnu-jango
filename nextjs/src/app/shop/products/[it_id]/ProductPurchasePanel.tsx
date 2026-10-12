"use client";

import { useEffect, useId, useState, type Dispatch, type SetStateAction } from "react";
import {
  Bell,
  BellOff,
  ChevronLeft,
  ChevronRight,
  CreditCard,
  Heart,
  Mail,
  Minus,
  Plus,
  Star,
} from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { Button } from "@/components/ui/button";
import { ShareButtons } from "@/components/ShareButtons";
import type { ShopNaverPayConfig, ShopProduct, ShopProductOption } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { plainTextSummary } from "@/lib/client-metadata";
import { g5ShortHref } from "@/lib/g5-short-url";
import { shopProductHref } from "@/lib/product-url";
import { cn, formatPrice } from "@/lib/utils";
import {
  clampBuyQuantity,
  isShopOptionPurchasable,
  type SelectedCartOption,
} from "./productDetailHelpers";

type AvailableOptionValue = {
  value: string;
  price?: number;
  soldOut?: boolean;
};

type ShippingPaymentDisplay = {
  label: string;
  value: string;
  detail?: string;
  selectable: boolean;
};

export function ProductPurchasePanel({
  product,
  productRewriteMode,
  hasDiscount,
  discountPercent,
  isTelInquiry,
  pointLabel,
  shippingPayment,
  ctSendCostSelection,
  onCtSendCostSelectionChange,
  canPurchaseProduct,
  optionSubjects,
  optionSelections,
  onOptionSelectionsChange,
  getAvailableValues,
  supplyOptions,
  supplyLabel,
  supplySelection,
  onSupplySelectionChange,
  onAddSupplyOption,
  quantity,
  onQuantityChange,
  quantityMinQty,
  quantityMaxQty,
  minBuyQty,
  selectedOption,
  selectedCartOptions,
  onAddSelectedOption,
  onUpdateSelectedOptionQty,
  onRemoveSelectedOption,
  displayTotal,
  restockAlerted,
  onRemoveRestockAlert,
  onOpenRestockDialog,
  addingToCart,
  onAddToCart,
  onBuyNow,
  onWishlist,
  onOpenRecommendDialog,
  naverPayConfig,
  naverPaySubmitting,
  onNaverPayOrder,
  naverPayWishSubmitting,
  onNaverPayWish,
  variant = "full",
}: {
  product: ShopProduct;
  productRewriteMode: BbsRewriteMode;
  hasDiscount: boolean;
  discountPercent: number;
  isTelInquiry: boolean;
  pointLabel: string;
  shippingPayment: ShippingPaymentDisplay;
  ctSendCostSelection: number;
  onCtSendCostSelectionChange: (value: number) => void;
  canPurchaseProduct: boolean;
  optionSubjects: string[];
  optionSelections: string[];
  onOptionSelectionsChange: Dispatch<SetStateAction<string[]>>;
  getAvailableValues: (levelIndex: number) => AvailableOptionValue[];
  supplyOptions: ShopProductOption[];
  supplyLabel: string;
  supplySelection: string;
  onSupplySelectionChange: (value: string) => void;
  onAddSupplyOption: () => void;
  quantity: number;
  onQuantityChange: Dispatch<SetStateAction<number>>;
  quantityMinQty: number;
  quantityMaxQty: number;
  minBuyQty: number;
  selectedOption?: ShopProductOption | null;
  selectedCartOptions: SelectedCartOption[];
  onAddSelectedOption: () => void;
  onUpdateSelectedOptionQty: (ioId: string, ioType: number, qty: number) => void;
  onRemoveSelectedOption: (ioId: string, ioType: number) => void;
  displayTotal: number;
  restockAlerted: boolean;
  onRemoveRestockAlert: () => void;
  onOpenRestockDialog: () => void;
  addingToCart: boolean;
  onAddToCart: () => void;
  onBuyNow: () => void;
  onWishlist: () => void;
  onOpenRecommendDialog: () => void;
  naverPayConfig: ShopNaverPayConfig | null;
  naverPaySubmitting: boolean;
  onNaverPayOrder: () => void;
  naverPayWishSubmitting: boolean;
  onNaverPayWish: () => void;
  variant?: "full" | "compact";
}) {
  const optionIdPrefix = useId();
  const [quantityInput, setQuantityInput] = useState(String(quantity));
  const compact = variant === "compact";
  const productBrand = product.it_brand?.includes("\uFFFD") ? "" : product.it_brand?.trim() || "";
  const productSubtitle = plainTextSummary(
    product.it_basic?.includes("\uFFFD") ? "" : product.it_basic,
    ""
  );
  const productDetails = (
    [
      ["제조사", product.it_maker],
      ["원산지", product.it_origin],
      ["모델명", product.it_model],
    ] as const
  ).flatMap(([label, value]) => {
    const normalizedValue = value?.trim();
    return normalizedValue && !normalizedValue.includes("\uFFFD")
      ? [{ label, value: normalizedValue }]
      : [];
  });

  useEffect(() => {
    setQuantityInput(String(quantity));
  }, [quantity]);

  const commitQuantityInput = () => {
    const parsed = Number(quantityInput);
    if (!Number.isFinite(parsed)) {
      setQuantityInput(String(quantity));
      return;
    }
    const nextQuantity = clampBuyQuantity(parsed, quantityMinQty, quantityMaxQty);
    onQuantityChange(nextQuantity);
    setQuantityInput(String(nextQuantity));
  };

  return (
    <div className={compact ? "space-y-4 rounded-box border border-base-300 bg-base-100 p-4 shadow-sm" : "solune-shop-purchase-panel"}>
      {!compact && productBrand ? (
        <p className="solune-shop-product-brand text-sm text-base-content/70">{productBrand}</p>
      ) : !compact && product.ca_name ? (
        <a
          href={g5ShortHref(`/shop/categories/${product.ca_id}`)}
          className="solune-shop-product-brand text-sm text-base-content/70 hover:text-primary"
        >
          {product.ca_name}
        </a>
      ) : null}

      <div className="solune-shop-product-heading space-y-3">
        {compact ? (
          <h2 className="line-clamp-2 min-w-0 text-lg font-bold">{product.it_name}</h2>
        ) : (
          <>
            <h1 className="min-w-0 break-words text-[22px] leading-7 font-bold md:text-3xl md:leading-[1.25]">{product.it_name}</h1>
            <ShareButtons title={product.it_name} />
          </>
        )}
      </div>

      {!compact && productSubtitle && (
        <p className="solune-shop-product-subtitle text-sm text-base-content/70">{productSubtitle}</p>
      )}

      {product.review_count !== undefined && product.review_count > 0 && (
        <div className="solune-shop-product-rating flex items-center gap-2">
          <div className="flex">
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
          <span className="text-sm text-muted-foreground">
            {product.review_avg}점 ({product.review_count}개 리뷰)
          </span>
        </div>
      )}

      <div className="solune-shop-product-price space-y-1">
        {hasDiscount && (
          <div className="flex items-center gap-2">
            <span className="text-sm text-muted-foreground line-through">
              {formatPrice(product.it_cust_price)}
            </span>
            <span className="rounded bg-red-500 px-1.5 py-0.5 text-xs font-bold text-white">
              {discountPercent}% OFF
            </span>
          </div>
        )}
        <p className="text-3xl font-bold">
          {isTelInquiry ? "전화문의" : formatPrice(product.it_price)}
        </p>
        {!isTelInquiry && pointLabel && (
          <p className="text-sm text-muted-foreground">적립 포인트: {pointLabel}</p>
        )}
      </div>

      <div className="solune-shop-shipping-summary text-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="font-medium">{shippingPayment.label}</span>
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

      {!compact && productDetails.length > 0 && (
        <dl aria-label="상품 정보" className="solune-shop-product-info space-y-2">
          {productDetails.map(({ label, value }) => (
            <div
              key={label}
              className="solune-shop-product-info-row grid grid-cols-[5rem_minmax(0,1fr)] items-start gap-3"
            >
              <dt className="text-sm text-base-content/70">{label}</dt>
              <dd className="min-w-0 break-words text-sm">{value}</dd>
            </div>
          ))}
        </dl>
      )}

      <div className="solune-shop-stock text-sm">
        {isTelInquiry ? (
          <span className="font-medium text-primary">전화문의 상품</span>
        ) : product.it_soldout === "1" ? (
          <span className="font-medium text-red-700">품절</span>
        ) : product.it_stock_qty > 0 ? (
          <span className="text-success">재고: {product.it_stock_qty}개</span>
        ) : (
          <span className="text-success">재고 있음</span>
        )}
      </div>

      {canPurchaseProduct && optionSubjects.length > 0 && (
        <div className="space-y-3">
          {optionSubjects.map((subject, levelIndex) => {
            const available = getAvailableValues(levelIndex);
            const isDisabled = levelIndex > 0 && !optionSelections[levelIndex - 1];
            return (
              <div key={levelIndex} className="solune-option-field" data-disabled={isDisabled || undefined}>
                <label htmlFor={`${optionIdPrefix}-option-${levelIndex}`} className="solune-option-label">
                  {subject}
                </label>
                <select
                  id={`${optionIdPrefix}-option-${levelIndex}`}
                  aria-label={subject}
                  data-shop-option-select="1"
                  value={optionSelections[levelIndex] || ""}
                  disabled={isDisabled}
                  onChange={(event) => {
                    onOptionSelectionsChange((previous) => {
                      const next = [...previous];
                      next[levelIndex] = event.target.value;
                      for (let i = levelIndex + 1; i < optionSubjects.length; i++) {
                        next[i] = "";
                      }
                      return next;
                    });
                  }}
                  className="solune-option-select"
                >
                  <option value="">선택해주세요</option>
                  {available.map((item) => (
                    <option key={item.value} value={item.value} disabled={item.soldOut}>
                      {item.value}
                      {item.price && item.price > 0
                        ? ` (+${formatPrice(item.price)})`
                        : item.price && item.price < 0
                          ? ` (${formatPrice(item.price)})`
                          : ""}
                      {item.soldOut ? " [품절]" : ""}
                    </option>
                  ))}
                </select>
              </div>
            );
          })}
        </div>
      )}

      {canPurchaseProduct && supplyOptions.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-stretch gap-2">
            <div className="solune-option-field min-w-0 flex-1">
              <label htmlFor={`${optionIdPrefix}-supply`} className="solune-option-label">
                {supplyLabel}
              </label>
              <select
                id={`${optionIdPrefix}-supply`}
                aria-label={supplyLabel}
                value={supplySelection}
                onChange={(event) => onSupplySelectionChange(event.target.value)}
                className="solune-option-select"
              >
              <option value="">추가옵션을 선택해주세요</option>
              {supplyOptions.map((option) => (
                <option
                  key={option.io_id}
                  value={option.io_id}
                  disabled={!isShopOptionPurchasable(option)}
                >
                  {option.io_value || option.io_id}
                  {option.io_price > 0
                    ? ` (+${formatPrice(option.io_price)})`
                    : option.io_price < 0
                      ? ` (${formatPrice(option.io_price)})`
                      : ""}
                  {!isShopOptionPurchasable(option) ? " [품절]" : ""}
                </option>
              ))}
              </select>
            </div>
            <Button
              type="button"
              variant="outline"
              className="h-auto"
              onClick={onAddSupplyOption}
              disabled={!supplySelection}
            >
              추가
            </Button>
          </div>
        </div>
      )}

      {canPurchaseProduct && (
        <div>
          <label className="mb-1 block text-sm font-medium">수량</label>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="icon"
              aria-label="수량 감소"
              onClick={() =>
                onQuantityChange((quantity) =>
                  clampBuyQuantity(quantity - 1, quantityMinQty, quantityMaxQty)
                )
              }
              disabled={quantity <= quantityMinQty}
            >
              <Minus className="h-4 w-4" />
            </Button>
            <input
              type="number"
              min={quantityMinQty}
              max={quantityMaxQty > 0 ? Math.max(quantityMinQty, quantityMaxQty) : undefined}
              aria-label="구매 수량"
              value={quantityInput}
              onChange={(event) => setQuantityInput(event.target.value)}
              onBlur={commitQuantityInput}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.currentTarget.blur();
                }
              }}
              className="h-9 w-16 rounded-md border bg-background text-center text-sm outline-none"
            />
            <Button
              variant="outline"
              size="icon"
              aria-label="수량 증가"
              onClick={() =>
                onQuantityChange((quantity) =>
                  clampBuyQuantity(quantity + 1, quantityMinQty, quantityMaxQty)
                )
              }
              disabled={quantityMaxQty > 0 && quantity >= Math.max(quantityMinQty, quantityMaxQty)}
            >
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          {(minBuyQty > 0 || quantityMaxQty > 0) && (
            <p className="mt-1 text-xs text-muted-foreground">
              {[
                minBuyQty > 0 ? `최소 ${minBuyQty}개` : "",
                quantityMaxQty > 0 ? `최대 ${quantityMaxQty}개` : "",
              ]
                .filter(Boolean)
                .join(" / ")}
            </p>
          )}
        </div>
      )}

      {canPurchaseProduct && (optionSubjects.length > 0 || supplyOptions.length > 0) && (
        <div className="space-y-3">
          {optionSubjects.length > 0 && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onAddSelectedOption}
              disabled={!selectedOption}
            >
              선택 옵션 추가
            </Button>
          )}

          {selectedCartOptions.length > 0 && (
            <div className="space-y-2 rounded-lg border p-3">
              {selectedCartOptions.map((option) => (
                <div
                  key={`${option.ioType}:${option.io_id}`}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-muted/40 p-2"
                >
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{option.label}</p>
                    {option.price !== 0 && (
                      <p className="text-xs text-muted-foreground">
                        {option.price > 0 ? "+" : ""}
                        {formatPrice(option.price)}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      aria-label={`${option.label} 수량 감소`}
                      onClick={() => onUpdateSelectedOptionQty(option.io_id, option.ioType, option.qty - 1)}
                      disabled={option.qty <= 1}
                    >
                      <Minus className="h-4 w-4" />
                    </Button>
                    <input
                      type="number"
                      min={1}
                      max={option.stockQty > 0 ? option.stockQty : undefined}
                      aria-label={`${option.label} 수량`}
                      value={option.qty}
                      onChange={(event) =>
                        onUpdateSelectedOptionQty(option.io_id, option.ioType, Number(event.target.value))
                      }
                      className="h-9 w-16 rounded-md border bg-background text-center text-sm outline-none"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      size="icon"
                      aria-label={`${option.label} 수량 증가`}
                      onClick={() => onUpdateSelectedOptionQty(option.io_id, option.ioType, option.qty + 1)}
                      disabled={option.stockQty > 0 && option.qty >= option.stockQty}
                    >
                      <Plus className="h-4 w-4" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => onRemoveSelectedOption(option.io_id, option.ioType)}
                    >
                      삭제
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {canPurchaseProduct && (
        <div className="rounded-lg border bg-muted/50 p-4">
          <div className="flex items-center justify-between">
            <span className="font-medium">총 상품 금액</span>
            <span className="text-xl font-bold text-primary">{formatPrice(displayTotal)}</span>
          </div>
        </div>
      )}

      <div className="flex flex-wrap gap-3">
        {isTelInquiry ? (
          <Button className="flex-1" size="lg" variant="outline" disabled>
            전화문의
          </Button>
        ) : product.it_soldout === "1" ? (
          <>
            {product.it_stock_sms !== "1" ? (
              <Button className="flex-1" size="lg" variant="outline" disabled>
                품절
              </Button>
            ) : restockAlerted ? (
              <Button className="flex-1" size="lg" variant="outline" onClick={onRemoveRestockAlert}>
                <BellOff className="mr-2 h-4 w-4" />
                알림 해제
              </Button>
            ) : (
              <Button
                className="flex-1"
                size="lg"
                variant="default"
                onClick={onOpenRestockDialog}
              >
                <Bell className="mr-2 h-4 w-4" />
                재입고 알림 신청
              </Button>
            )}
          </>
        ) : (
          <>
            <Button className="flex-1" size="lg" variant="outline" onClick={onAddToCart} disabled={addingToCart}>
              {addingToCart ? "추가 중..." : "장바구니"}
            </Button>
            <Button className="flex-1" size="lg" onClick={onBuyNow}>
              바로구매
            </Button>
          </>
        )}
        <div className="flex gap-3">
          <Button variant="outline" size="lg" aria-label="위시리스트에 추가" onClick={onWishlist}>
            <Heart className="h-4 w-4" />
          </Button>
          <Button
            variant="outline"
            size="lg"
            aria-label="지인에게 메일로 추천"
            title="지인에게 메일로 추천"
            onClick={onOpenRecommendDialog}
          >
            <Mail className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {naverPayConfig?.enabled && canPurchaseProduct && (
        <div className="rounded-md border border-[#0c8040]/30 bg-[#0c8040]/5 p-3">
          <div className="grid gap-2 sm:grid-cols-2">
            <Button
              type="button"
              className="bg-[#0c8040] text-white hover:bg-[#08783a]"
              onClick={onNaverPayOrder}
              disabled={naverPaySubmitting}
            >
              <CreditCard className="mr-2 h-4 w-4" />
              {naverPaySubmitting ? "네이버페이 등록 중..." : "N Pay 구매"}
            </Button>
            <Button
              type="button"
              variant="outline"
              className="border-[#0c8040]/50 text-[#0c8040] hover:bg-[#0c8040]/10"
              onClick={onNaverPayWish}
              disabled={naverPayWishSubmitting}
            >
              <Heart className="mr-2 h-4 w-4" />
              {naverPayWishSubmitting ? "찜 등록 중..." : "N Pay 찜"}
            </Button>
          </div>
        </div>
      )}
      {!compact && (product.prev_item || product.next_item) && (
        <nav aria-label="상품 이전 다음" className="grid gap-2 text-sm sm:grid-cols-2">
          {product.prev_item ? (
            <Button
              variant="outline"
              className="h-auto justify-start gap-2 px-3 py-2 text-left"
              asChild
            >
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
            <Button
              variant="outline"
              className="h-auto justify-end gap-2 px-3 py-2 text-right"
              asChild
            >
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
    </div>
  );
}
