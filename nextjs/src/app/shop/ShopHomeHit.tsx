"use client";

import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { ShopProductRow, ShopProductRowSkeleton } from "@/components/shop/ShopProductRow";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { getShopHomeData } from "@/services/shop-home";

export function ShopHomeHit() {
  const [products, setProducts] = useState<ShopProduct[]>([]);
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [catalogFallback, setCatalogFallback] = useState(false);
  const [hasOtherSections, setHasOtherSections] = useState(false);

  useEffect(() => {
    let alive = true;

    getShopHomeData()
      .then((home) => {
        if (!alive) return;
        setProducts(home.products.type1.length ? home.products.type1 : home.catalogPreview);
        setCatalogFallback(home.products.type1.length === 0 && home.catalogPreview.length > 0);
        setHasOtherSections(Object.values(home.products).some(section => section.length > 0));
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
      <ShopProductRowSkeleton eyebrow="HIT" title="히트상품" subtitle="가장 많이 나간 상품입니다." className="shop-home-hit-section" />
    );
  }

  if (!error && products.length === 0 && hasOtherSections) return null;

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
      eyebrow={catalogFallback ? "COLLECTION" : "HIT"}
      title={catalogFallback ? "전체 상품" : "히트상품"}
      subtitle={catalogFallback ? "쇼핑몰에 등록된 상품을 둘러보세요." : "가장 많이 나간 상품입니다."}
      products={products}
      viewAllHref={catalogFallback ? "/shop/search" : "/shop/type-1"}
      productRewriteMode={productRewriteMode}
      className="shop-home-hit-section"
    />
  );
}
