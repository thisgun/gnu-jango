"use client";

import { useEffect, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { SHOP_HOME_ROW_LIMIT, ShopProductRow, ShopProductRowSkeleton } from "@/components/shop/ShopProductRow";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { getShopProductList } from "@/services/shop";
import { getClientPublicSettings } from "@/services/settings";

export function ShopHomeHit() {
  const [products, setProducts] = useState<ShopProduct[]>([]);
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;

    Promise.all([
      getShopProductList({ it_type1: "1", per_page: SHOP_HOME_ROW_LIMIT }),
      getClientPublicSettings(),
    ])
      .then(([popular, settings]) => {
        if (!alive) return;
        setProducts(popular.products);
        setProductRewriteMode(settings.cf_bbs_rewrite);
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
      eyebrow="HIT"
      title="히트상품"
      subtitle="가장 많이 나간 상품입니다."
      products={products}
      viewAllHref="/shop/type-1"
      productRewriteMode={productRewriteMode}
      className="shop-home-hit-section"
    />
  );
}
