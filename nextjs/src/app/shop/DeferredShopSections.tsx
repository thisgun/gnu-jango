"use client";

import { useEffect, useState } from "react";
import type { ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { DEFAULT_HOME_DISPLAY, type ShopHomeDisplay } from "@/lib/shop-display";
import { ShopProductRow, ShopProductRowSkeleton } from "@/components/shop/ShopProductRow";
import { getShopHomeData } from "@/services/shop-home";

type SectionKey = "type3" | "type2" | "type5";

type ProductSections = Record<SectionKey, ShopProduct[]>;

const EMPTY_SECTIONS: ProductSections = {
  type3: [],
  type2: [],
  type5: [],
};

/** 그리는 차례: 최신 · 추천 · 할인. key 는 쇼핑 홈 스냅샷의 products · display 키(it_typeN). */
const SECTIONS: { key: SectionKey; eyebrow: string; title: string; subtitle: string }[] = [
  { key: "type3", eyebrow: "NEW ARRIVAL", title: "최신상품", subtitle: "가장 최근에 등록된 상품입니다." },
  { key: "type2", eyebrow: "MD PICK", title: "추천상품", subtitle: "오래 쓰이는 것으로 골랐습니다." },
  { key: "type5", eyebrow: "SALE", title: "할인상품", subtitle: "지금 값을 내린 상품입니다." },
];

export function DeferredShopSections() {
  const [sections, setSections] = useState<ProductSections>(EMPTY_SECTIONS);
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [display, setDisplay] = useState<ShopHomeDisplay>(DEFAULT_HOME_DISPLAY);

  useEffect(() => {
    let alive = true;

    getShopHomeData()
      .then((home) => {
        if (!alive) return;
        setError("");
        // 관리자가 끈 섹션은 상품이 와도 비워 둔다(ShopProductRow 는 빈 줄을 그리지 않는다).
        const shown = (key: SectionKey) => (home.display[key].use ? home.products[key] : []);
        setDisplay(home.display);
        setSections({ type2: shown("type2"), type3: shown("type3"), type5: shown("type5") });
        setProductRewriteMode(home.settings.cf_bbs_rewrite);
      })
      .catch(() => {
        if (!alive) return;
        setSections(EMPTY_SECTIONS);
        setError("상품 섹션을 불러오지 못했습니다.");
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
      <>
        {SECTIONS.map((section) => (
          <ShopProductRowSkeleton key={section.key} eyebrow={section.eyebrow} title={section.title} subtitle={section.subtitle} />
        ))}
      </>
    );
  }

  if (error) {
    return (
      <p role="status" className="rounded-[4px] border bg-muted/30 px-4 py-3 text-sm text-muted-foreground">
        {error}
      </p>
    );
  }

  if (SECTIONS.every(({ key }) => sections[key].length === 0)) {
    return null;
  }

  return (
    <>
      {SECTIONS.map((section) => (
        <ShopProductRow
          key={section.key}
          eyebrow={section.eyebrow}
          title={section.title}
          subtitle={section.subtitle}
          products={sections[section.key]}
          viewAllHref={`/shop/type-${section.key.slice(4)}`}
          productRewriteMode={productRewriteMode}
          display={display[section.key]}
        />
      ))}
    </>
  );
}
