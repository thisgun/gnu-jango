"use client";

import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { ShopProductRow, ShopProductRowSkeleton } from "@/components/shop/ShopProductRow";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { DEFAULT_HOME_SECTION_DISPLAY, type ShopHomeSectionDisplay } from "@/lib/shop-display";
import { getShopHomeData } from "@/services/shop-home";

export function ShopHomePopular() {
  const [products, setProducts] = useState<ShopProduct[]>([]);
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [display, setDisplay] = useState<ShopHomeSectionDisplay>(DEFAULT_HOME_SECTION_DISPLAY);

  useEffect(() => {
    let alive = true;

    getShopHomeData()
      .then((home) => {
        if (!alive) return;
        setDisplay(home.display.type4);
        setProducts(home.display.type4.use ? home.products.type4 : []);
        setProductRewriteMode(home.settings.cf_bbs_rewrite);
        setError(false);
      })
      .catch(() => {
        if (!alive) return;
        setProducts([]);
        setError(true);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, []);

  if (loading) {
    return (
      <ShopProductRowSkeleton eyebrow="POPULAR" title="많이 보고 계신 상품" peek={false} className="shop-home-popular-section" />
    );
  }

  // 관리자가 인기상품 출력을 끄면 빈 자리 안내도 그리지 않는다.
  if (!error && !display.use) return null;

  if (error || products.length === 0) {
    return (
      <EmptyState
        className="mb-8"
        title={error ? "상품을 불러오지 못했습니다" : "표시할 상품이 없습니다"}
        description={
          error
            ? "상품 정보를 확인할 수 없습니다. 잠시 후 다시 시도해 주세요."
            : "상품을 등록하면 쇼핑몰 첫 화면에 표시됩니다."
        }
      />
    );
  }

  return (
    <ShopProductRow
      eyebrow="POPULAR"
      title="많이 보고 계신 상품"
      products={products}
      viewAllHref="/shop/type-4"
      productRewriteMode={productRewriteMode}
      peek={false}
      display={display}
      className="shop-home-popular-section"
    />
  );
}
