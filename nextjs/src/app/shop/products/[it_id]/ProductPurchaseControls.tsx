"use client";

import { Bell, BellOff, BellRing, Heart, ShoppingCart } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ShopProduct } from "@/lib/api";
import {
  ProductOptionPicker,
  type ProductOptionPickerProps,
} from "@/components/shop/ProductOptionPicker";

export type ProductPurchaseControlsProps = Omit<ProductOptionPickerProps, "productName"> & {
  product: ShopProduct;
  canPurchaseProduct: boolean;
  isTelInquiry: boolean;
  /** 품절이면 재입고 알림 · 품절 단추를 보인다(영카트 is_soldout — 선택옵션이 모두 품절이어도 품절). */
  isSoldOut: boolean;
  restockAlerted: boolean;
  onRemoveRestockAlert: () => void;
  onOpenRestockDialog: () => void;
  addingToCart: boolean;
  onAddToCart: () => void;
  onBuyNow: () => void;
  onWishlist: () => void;
  /** 가격 인하 알림 — 쇼핑몰이 켰을 때만 단추를 보인다(useProductPriceAlert). */
  priceAlertEnabled: boolean;
  priceAlerted: boolean;
  priceAlertBusy: boolean;
  onTogglePriceAlert: () => void;
};

/**
 * 재입고 알림을 받을 수 있는가 — 서버 stock-notify 와 같은 조건: 알림을 켠 상품(it_stock_sms)이고,
 * 품절 표시이거나 상품 재고가 0 이하. 선택옵션만 모두 품절인 상품은 서버가 "재고 있음"으로 거절하므로 품절 단추만.
 */
function canRequestRestock(product: ShopProduct) {
  return (
    String(product.it_stock_sms ?? "0") === "1" &&
    (String(product.it_soldout ?? "0") === "1" || Number(product.it_stock_qty ?? 0) <= 0)
  );
}

/**
 * 선택옵션 → 추가옵션 → 선택된 옵션 → 총 금액 → [장바구니][바로구매][♡] — 구매 패널의 아래 절반
 * (레퍼런스 앱 ProductPurchaseControls). 상세 설명 옆에 따라다니는 구매 상자도 같은 것을 한 번 더 놓는다 —
 * 상태는 전부 위(ProductDetailClient)에 있어 두 벌이 저절로 같이 움직인다.
 * 조각(fragment)으로 돌려준다: 패널(.product-panel)의 flex order 가 각 덩어리 자리를 정한다(solune-shop.detail.css).
 */
export function ProductPurchaseControls({
  product,
  canPurchaseProduct,
  isTelInquiry,
  isSoldOut,
  restockAlerted,
  onRemoveRestockAlert,
  onOpenRestockDialog,
  addingToCart,
  onAddToCart,
  onBuyNow,
  onWishlist,
  priceAlertEnabled,
  priceAlerted,
  priceAlertBusy,
  onTogglePriceAlert,
  ...pickerProps
}: ProductPurchaseControlsProps) {
  return (
    <>
      {canPurchaseProduct && <ProductOptionPicker productName={product.it_name} {...pickerProps} />}

      <div className="product-actions flex gap-3">
        {isTelInquiry ? (
          <Button className="flex-1" size="lg" variant="outline" disabled>
            전화문의
          </Button>
        ) : isSoldOut ? (
          !canRequestRestock(product) ? (
            <Button className="flex-1" size="lg" variant="outline" disabled>
              품절
            </Button>
          ) : restockAlerted ? (
            <Button className="flex-1" size="lg" variant="outline" onClick={onRemoveRestockAlert}>
              <BellOff className="mr-2 h-4 w-4" />
              알림 해제
            </Button>
          ) : (
            <Button className="flex-1" size="lg" onClick={onOpenRestockDialog}>
              <Bell className="mr-2 h-4 w-4" />
              재입고 알림 신청
            </Button>
          )
        ) : (
          <>
            <Button
              className="product-action-cart flex-1"
              size="lg"
              onClick={onAddToCart}
              disabled={addingToCart}
            >
              <ShoppingCart className="mr-2 h-4 w-4" />
              {addingToCart ? "추가 중..." : "장바구니"}
            </Button>
            <Button className="product-action-buy flex-1" size="lg" variant="secondary" onClick={onBuyNow}>
              바로구매
            </Button>
          </>
        )}
        {priceAlertEnabled && canPurchaseProduct && (
          <Button
            className="product-action-price-alert"
            variant="outline"
            size="lg"
            aria-label={priceAlerted ? "가격 인하 알림 해제" : "가격 인하 알림 신청"}
            aria-pressed={priceAlerted}
            title={priceAlerted ? "가격 인하 알림 해제" : "가격이 내려가면 알림 받기"}
            onClick={onTogglePriceAlert}
            disabled={priceAlertBusy}
          >
            <BellRing className="h-4 w-4" />
          </Button>
        )}
        <Button
          className="product-action-wish"
          variant="outline"
          size="lg"
          aria-label="위시리스트에 추가"
          onClick={onWishlist}
        >
          <Heart className="h-4 w-4" />
        </Button>
      </div>
    </>
  );
}
