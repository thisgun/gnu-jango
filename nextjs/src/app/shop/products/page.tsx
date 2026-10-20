"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useRouter } from "@bprogress/next/app";
import Image from "next/image";
import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ShopListHeader } from "@/components/shop/ShopListHeader";
import { SoluneProductCard } from "@/components/shop/SoluneProductCard";
import { useShopListView } from "@/hooks/useShopListView";
import type { BbsRewriteMode } from "@/lib/board-url";
import { applyClientPageMetadata } from "@/lib/client-metadata";
import { currentPathForRuntime } from "@/lib/config";
import { shouldBypassImageOptimization } from "@/lib/image";
import { shopProductHref } from "@/lib/product-url";
import { DEFAULT_SHOP_LIST_DISPLAY, shopGridStyle, shopListDisplayOf, type ShopListDisplay } from "@/lib/shop-display";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { cn, formatPrice } from "@/lib/utils";
import { useShopProductSuggest } from "@/hooks/useShopProductSuggest";
import { getShopProductList, type ShopProductParams } from "@/services/shop";
import { getClientPublicSettings } from "@/services/settings";
import type { ShopProduct } from "@/lib/api";

const TYPE_CHIPS: { key: `it_type${1 | 2 | 3 | 4 | 5}`; label: string }[] = [
  { key: "it_type1", label: "베스트" },
  { key: "it_type2", label: "추천" },
  { key: "it_type3", label: "신상품" },
  { key: "it_type4", label: "인기" },
  { key: "it_type5", label: "할인" },
];

function ProductListSkeleton({ viewMode }: { viewMode: "grid" | "list" }) {
  if (viewMode === "list") {
    return (
      <div className="flex flex-col gap-3">
        {Array.from({ length: 8 }).map((_, index) => (
          <div key={index} className="product-list-card animate-pulse">
            <div className="aspect-square rounded-[6px] bg-muted" />
            <div className="space-y-2 py-1">
              <div className="h-3 w-16 rounded bg-muted" />
              <div className="h-4 w-4/5 rounded bg-muted" />
              <div className="h-4 w-2/3 rounded bg-muted" />
              <div className="h-5 w-20 rounded bg-muted" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
      {Array.from({ length: 8 }).map((_, index) => (
        <div key={index} className="product-card animate-pulse">
          <div className="aspect-square rounded-[6px] bg-muted" />
          <div className="mt-3 space-y-2">
            <div className="h-3 w-14 rounded bg-muted" />
            <div className="h-4 w-full rounded bg-muted" />
            <div className="h-4 w-2/3 rounded bg-muted" />
            <div className="h-5 w-20 rounded bg-muted" />
          </div>
        </div>
      ))}
    </div>
  );
}

function Pagination({
  currentPage,
  totalPages,
  onPageChange,
}: {
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}) {
  if (totalPages <= 1) return null;

  const pages: number[] = [];
  const start = Math.max(1, currentPage - 2);
  const end = Math.min(totalPages, currentPage + 2);
  for (let i = start; i <= end; i++) pages.push(i);

  return (
    <div className="mt-8 flex items-center justify-center gap-1">
      <Button
        variant="outline"
        size="icon"
        disabled={currentPage <= 1}
        onClick={() => onPageChange(currentPage - 1)}
        aria-label="이전 페이지"
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>
      {start > 1 && (
        <>
          <Button variant="outline" size="sm" onClick={() => onPageChange(1)}>
            1
          </Button>
          {start > 2 && <span className="px-1 text-muted-foreground">...</span>}
        </>
      )}
      {pages.map((p) => (
        <Button key={p} variant={p === currentPage ? "default" : "outline"} size="sm" onClick={() => onPageChange(p)}>
          {p}
        </Button>
      ))}
      {end < totalPages && (
        <>
          {end < totalPages - 1 && <span className="px-1 text-muted-foreground">...</span>}
          <Button variant="outline" size="sm" onClick={() => onPageChange(totalPages)}>
            {totalPages}
          </Button>
        </>
      )}
      <Button
        variant="outline"
        size="icon"
        disabled={currentPage >= totalPages}
        onClick={() => onPageChange(currentPage + 1)}
        aria-label="다음 페이지"
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
    </div>
  );
}

export default function ProductListPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();

  const [products, setProducts] = useState<ShopProduct[]>([]);
  const [loading, setLoading] = useState(true);
  const [totalPages, setTotalPages] = useState(1);
  const [total, setTotal] = useState(0);
  const [listView, setListView] = useShopListView();
  const [searchInput, setSearchInput] = useState(searchParams.get("q") || "");
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);
  // 한 쪽 상품 수 · 칸 수(관리자 진열 설정). 받기 전에는 목록을 부르지 않는다 — 쪽 크기가 바뀌면 쪽 번호가 어긋난다.
  const [listDisplay, setListDisplay] = useState<ShopListDisplay | null>(null);
  const { items: suggestItems } = useShopProductSuggest(searchInput, suggestOpen);

  const currentPage = Number(searchParams.get("page") || "1");
  const sort = searchParams.get("sort") || searchParams.get("qsort") || "";
  const sortodr = searchParams.get("sortodr") || searchParams.get("qorder") || "";
  const caId = searchParams.get("ca_id") || searchParams.get("qcaid") || "";
  const query = searchParams.get("q") || "";
  const runtimePath = currentPathForRuntime(pathname || undefined);
  const listRoute = runtimePath.startsWith("/shop/search") ? "/shop/search" : "/shop/products";
  const isSearchRoute = listRoute === "/shop/search";
  const priceFrom = searchParams.get("qfrom") || searchParams.get("price_min") || "";
  const priceTo = searchParams.get("qto") || searchParams.get("price_max") || "";
  const legacyTypeMatch = runtimePath.match(/^\/shop\/type-([1-5])$/);
  const rewrittenType = searchParams.get("__g5_type") || "";
  const legacyType = legacyTypeMatch?.[1] || (/^[1-5]$/.test(rewrittenType) ? rewrittenType : "");
  const legacyTypeKey = legacyType ? `it_type${legacyType}` : "";
  const explicitTypeKey = TYPE_CHIPS.find((chip) => searchParams.get(chip.key) === "1")?.key || "";
  const effectiveTypeKey = explicitTypeKey || legacyTypeKey;

  useEffect(() => {
    setSearchInput(query);
  }, [query]);

  const updateParams = useCallback(
    (updates: Record<string, string>) => {
      const params = new URLSearchParams(searchParams.toString());
      Object.entries(updates).forEach(([key, value]) => {
        if (value) params.set(key, value);
        else params.delete(key);
      });
      const search = params.toString();
      runtimeRouterPush(router, `${listRoute}${search ? `?${search}` : ""}`);
    },
    [listRoute, searchParams, router]
  );

  useEffect(() => {
    let alive = true;
    getClientPublicSettings()
      .then((settings) => {
        if (!alive) return;
        setProductRewriteMode(settings.cf_bbs_rewrite);
        setListDisplay(shopListDisplayOf(settings));
      })
      .catch(() => {
        if (!alive) return;
        setProductRewriteMode(0);
        setListDisplay(DEFAULT_SHOP_LIST_DISPLAY);
      });

    return () => {
      alive = false;
    };
  }, []);

  // 히트 · 추천 · 최신 · 인기 · 할인 목록(/shop/type-N, 유형 칩)은 유형별 목록 설정, 나머지(검색 · 전체)는 검색결과 설정.
  const grid = (listDisplay ?? DEFAULT_SHOP_LIST_DISPLAY)[effectiveTypeKey ? "listtype" : "search"];
  const perPage = listDisplay ? grid.per_page : 0;

  useEffect(() => {
    if (!perPage) return;
    const loadProducts = async () => {
      setLoading(true);
      try {
        const params: ShopProductParams = {
          page: String(currentPage),
          per_page: String(perPage),
        };
        if (sort) params.sort = sort;
        if (sortodr) params.sortodr = sortodr;
        if (caId) params.ca_id = caId;
        if (query) params.q = query;
        if (priceFrom) params.qfrom = priceFrom;
        if (priceTo) params.qto = priceTo;

        TYPE_CHIPS.forEach((chip) => {
          const val = searchParams.get(chip.key);
          if (val) params[chip.key] = val;
        });
        ["qname", "qexplan", "qid", "qbasic"].forEach((key) => {
          const val = searchParams.get(key);
          if (val) params[key] = val;
        });
        if (effectiveTypeKey && !explicitTypeKey) {
          params[effectiveTypeKey] = "1";
        }

        const result = await getShopProductList(params);
        setProducts(result.products);
        setTotalPages(result.meta?.last_page || 1);
        setTotal(result.meta?.total ?? 0);
      } catch {
        setProducts([]);
        setTotalPages(1);
        setTotal(0);
      } finally {
        setLoading(false);
      }
    };

    loadProducts();
  }, [currentPage, perPage, sort, sortodr, caId, query, priceFrom, priceTo, searchParams, effectiveTypeKey, explicitTypeKey]);

  const activeChip = TYPE_CHIPS.find((chip) => chip.key === effectiveTypeKey);
  const listTitle = query ? `상품 검색: ${query}` : activeChip ? `${activeChip.label} 상품` : "상품 목록";

  useEffect(() => {
    const params = new URLSearchParams(searchParams.toString());
    if (effectiveTypeKey && !explicitTypeKey) {
      params.set(effectiveTypeKey, "1");
    }
    const search = params.toString();

    applyClientPageMetadata({
      title: isSearchRoute && !query ? "상품 검색" : listTitle,
      description: `${listTitle}에서 총 ${total}개의 상품을 확인하세요.`,
      path: `${listRoute}${search ? `?${search}` : ""}`,
    });
  }, [effectiveTypeKey, explicitTypeKey, isSearchRoute, listRoute, listTitle, query, searchParams, total]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    updateParams({ q: searchInput.trim(), page: "1" });
  };

  function setTypeChip(key: string, active: boolean) {
    const params = new URLSearchParams(searchParams.toString());
    TYPE_CHIPS.forEach((chip) => params.delete(chip.key));
    if (!active) params.set(key, "1");
    params.delete("page");
    const search = params.toString();
    runtimeRouterPush(router, `${listRoute}${search ? `?${search}` : ""}`);
  }

  const typeChips = (
    <div className="flex flex-wrap gap-2">
      <button type="button" onClick={() => setTypeChip("", true)} className={cn("filter-chip", !activeChip && "filter-chip-active")}>
        전체
      </button>
      {TYPE_CHIPS.map((chip) => {
        const active = activeChip?.key === chip.key;
        return (
          <button
            key={chip.key}
            type="button"
            onClick={() => setTypeChip(chip.key, active)}
            className={cn("filter-chip", active && "filter-chip-active")}
          >
            {chip.label}
          </button>
        );
      })}
    </div>
  );

  return (
    <div>
      {/* 레퍼런스 목록 머리: 제목 · 빵부스러기 · 유형 칩 · 정렬 줄(오른쪽에 검색창 · 개수 · 리스트/갤러리 전환). */}
      <ShopListHeader
        title={listTitle}
        total={total}
        sort={sort}
        onSortChange={(value) => updateParams({ sort: sort === value ? "" : value, sortodr: "", page: "1" })}
        view={listView}
        onViewChange={setListView}
        filters={typeChips}
        toolbar={
        <form action={listRoute} method="get" onSubmit={handleSearch} className="flex min-w-0 flex-1 gap-2">
          <div className="relative min-w-0 flex-1 sm:max-w-[360px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <label htmlFor="shop-product-search-query" className="sr-only">
              상품 검색
            </label>
            <input
              id="shop-product-search-query"
              name="q"
              type="search"
              placeholder="상품 검색"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onFocus={() => setSuggestOpen(true)}
              onBlur={() => setTimeout(() => setSuggestOpen(false), 150)}
              className="h-10 w-full rounded-[4px] border bg-background pl-9 pr-3 text-sm outline-none focus:ring-2 focus:ring-ring"
            />
            {suggestOpen && suggestItems.length > 0 && (
              <div className="absolute left-0 top-full z-20 mt-1 w-full min-w-[280px] rounded-[4px] border bg-popover p-1 shadow-md">
                {suggestItems.map((item) => (
                  <a
                    key={item.it_id}
                    href={shopProductHref(item, productRewriteMode)}
                    className="flex items-center gap-2 rounded-[4px] px-2 py-1.5 text-sm hover:bg-accent"
                    onMouseDown={(e) => e.preventDefault()}
                  >
                    {item.image_url ? (
                      <Image
                        src={item.image_url}
                        alt={item.it_name}
                        width={32}
                        height={32}
                        className="h-8 w-8 flex-shrink-0 rounded object-cover"
                        unoptimized={shouldBypassImageOptimization(item.image_url)}
                      />
                    ) : (
                      <div className="h-8 w-8 flex-shrink-0 rounded bg-muted" />
                    )}
                    <span className="flex-1 truncate">{item.it_name}</span>
                    <span className="text-xs text-muted-foreground">
                      {String(item.it_tel_inq ?? "0") === "1" ? "전화문의" : formatPrice(item.it_price)}
                    </span>
                  </a>
                ))}
              </div>
            )}
          </div>
          <Button type="submit" size="sm" className="h-10">
            검색
          </Button>
        </form>
        }
      />

      {loading ? (
        <ProductListSkeleton viewMode={listView} />
      ) : products.length === 0 ? (
        <div className="surface-panel flex flex-col items-center justify-center py-20 text-center">
          <p className="text-lg font-bold text-muted-foreground">상품이 없습니다</p>
          <p className="mt-1 text-sm text-muted-foreground">다른 검색어나 필터를 사용해보세요.</p>
        </div>
      ) : (
        // 리스트/갤러리 모양은 data-view 를 보고 CSS 가 정한다. 갤러리 칸 수는 진열 설정(PC · 모바일 1줄당 수)을
        // solune-shop.display.css 가 단계별로 건다(기본 2 · 3 · 4 · 5 — 레퍼런스 listtype.php).
        <div
          className="shop-product-list shop-product-list--all shop-display-grid grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4"
          data-view={listView}
          data-shop-grid=""
          style={shopGridStyle(grid.mobile_cols, grid.pc_cols)}
        >
          {products.map((product, index) => (
            <SoluneProductCard
              key={product.it_id}
              product={product}
              priority={index < 4}
              productRewriteMode={productRewriteMode}
            />
          ))}
        </div>
      )}

      <Pagination currentPage={currentPage} totalPages={totalPages} onPageChange={(page) => updateParams({ page: String(page) })} />
    </div>
  );
}
