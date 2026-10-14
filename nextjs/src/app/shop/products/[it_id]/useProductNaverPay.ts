"use client";

import { useCallback, useEffect, useState } from "react";
import type { ShopNaverPayConfig, ShopNaverPayOrderOption, ShopProduct } from "@/lib/api";
import { toastError } from "@/lib/toast";
import {
  getShopNaverPayConfig,
  registerShopNaverPayOrder,
  registerShopNaverPayWish,
} from "@/services/shop";
import {
  isProductDetailSoldOut,
  type SelectedCartOption,
} from "@/components/shop/productDetailHelpers";

interface UseProductNaverPayInput {
  product: ShopProduct | null;
  isTelInquiry: boolean;
  /** 옵션 없는 상품의 본품 수량 */
  quantity: number;
  hasOptionSubjects: boolean;
  buildSelectedCartOptions: () => SelectedCartOption[];
  validateBuyQtyBeforeSubmit: (cartOptions: SelectedCartOption[]) => boolean;
}

export interface ProductNaverPayActions {
  submitting: boolean;
  wishSubmitting: boolean;
  onOrder: () => void;
  onWish: () => void;
}

/**
 * 네이버페이 구매 · 찜 — 이 앱에만 있는 기능(레퍼런스 앱에는 없다). 설정이 켜져 있을 때만 구매 패널에 단추가 선다.
 * 담을 줄은 장바구니와 같다: 선택옵션 상품은 고른 줄, 옵션 없는 상품은 본품(수량) 한 줄 뒤에 추가옵션 줄.
 */
export function useProductNaverPay({
  product,
  isTelInquiry,
  quantity,
  hasOptionSubjects,
  buildSelectedCartOptions,
  validateBuyQtyBeforeSubmit,
}: UseProductNaverPayInput) {
  const [config, setConfig] = useState<ShopNaverPayConfig | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [wishSubmitting, setWishSubmitting] = useState(false);

  useEffect(() => {
    let alive = true;

    getShopNaverPayConfig()
      .then((nextConfig) => {
        if (alive) setConfig(nextConfig);
      })
      .catch(() => {
        if (alive) setConfig(null);
      });

    return () => {
      alive = false;
    };
  }, []);

  const buildOrderOptions = useCallback((): ShopNaverPayOrderOption[] => {
    const lines = buildSelectedCartOptions().map((option) => ({
      io_id: option.io_id,
      io_type: option.ioType,
      io_value: option.label,
      ct_qty: option.qty,
    }));
    if (hasOptionSubjects) return lines;
    return [{ io_id: "", io_type: 0, io_value: "", ct_qty: quantity }, ...lines];
  }, [buildSelectedCartOptions, hasOptionSubjects, quantity]);

  const validateSelection = useCallback(() => {
    if (!product) return false;
    if (isTelInquiry) {
      toastError("전화문의 상품은 네이버페이로 주문할 수 없습니다.");
      return false;
    }
    if (isProductDetailSoldOut(product)) {
      toastError("품절 상품은 네이버페이로 주문할 수 없습니다.");
      return false;
    }

    const cartOptions = buildSelectedCartOptions();
    if (hasOptionSubjects && !cartOptions.some((option) => option.ioType === 0)) {
      toastError("옵션을 선택해주세요.");
      return false;
    }

    return validateBuyQtyBeforeSubmit(cartOptions);
  }, [buildSelectedCartOptions, hasOptionSubjects, isTelInquiry, product, validateBuyQtyBeforeSubmit]);

  const onOrder = useCallback(async () => {
    if (!product || !config?.enabled || !validateSelection()) return;

    setSubmitting(true);
    try {
      const response = await registerShopNaverPayOrder({
        source: "item",
        it_id: product.it_id,
        quantity,
        options: buildOrderOptions(),
        back_url: window.location.href,
      });
      if (!response.redirect_url) {
        throw new Error("네이버페이 이동 URL이 없습니다.");
      }
      window.location.href = response.redirect_url;
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "네이버페이 주문 등록에 실패했습니다.";
      toastError(message);
    } finally {
      setSubmitting(false);
    }
  }, [buildOrderOptions, config?.enabled, product, quantity, validateSelection]);

  const onWish = useCallback(async () => {
    if (!product || !config?.enabled) return;

    const popup = window.open(
      "about:blank",
      "win_naverpay_wishlist",
      "scrollbars=yes,width=400,height=267"
    );
    setWishSubmitting(true);
    try {
      const response = await registerShopNaverPayWish({ it_id: product.it_id });
      if (!response.redirect_url) {
        throw new Error("네이버페이 찜 URL이 없습니다.");
      }
      if (popup) {
        popup.location.href = response.redirect_url;
      } else {
        window.open(response.redirect_url, "_blank", "noopener,noreferrer");
      }
    } catch (err: unknown) {
      if (popup) popup.close();
      const message =
        err instanceof Error ? err.message : "네이버페이 찜 등록에 실패했습니다.";
      toastError(message);
    } finally {
      setWishSubmitting(false);
    }
  }, [config?.enabled, product]);

  const actions: ProductNaverPayActions | null = config?.enabled
    ? { submitting, wishSubmitting, onOrder, onWish }
    : null;

  return actions;
}
