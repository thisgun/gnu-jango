"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { useRouter } from "@bprogress/next/app";
import Image from "next/image";
import { ChevronLeft, ChevronRight, LayoutGrid, List, Search } from "lucide-react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { ProductCard } from "@/components/shop/ProductGridSection";
import { ProductListCard } from "@/components/shop/ProductListCard";
import type { BbsRewriteMode } from "@/lib/board-url";
import { applyClientPageMetadata } from "@/lib/client-metadata";
import { currentPathForRuntime } from "@/lib/config";
import { shouldBypassImageOptimization } from "@/lib/image";
import { shopProductHref } from "@/lib/product-url";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { cn, formatPrice } from "@/lib/utils";
import { useShopProductSuggest } from "@/hooks/useShopProductSuggest";
import { getShopProductList, type ShopProductParams } from "@/services/shop";
import { getClientPublicSettings } from "@/services/settings";
import type { ShopProduct } from "@/lib/api";

const SORT_OPTIONS = [
  { value: "popular", label: "판매많은순" },
  { value: "price_asc", label: "낮은가격순" },
  { value: "price_desc", label: "높은가격순" },
  { value: "rating", label: "평점높은순" },
  { value: "reviews", label: "후기많은순" },
  { value: "latest", label: "최근등록순" },
];

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
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [searchInput, setSearchInput] = useState(searchParams.get("q") || "");
  const [suggestOpen, setSuggestOpen] = useState(false);
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);
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
        if (alive) setProductRewriteMode(settings.cf_bbs_rewrite);
      })
      .catch(() => {
        if (alive) setProductRewriteMode(0);
      });

    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const loadProducts = async () => {
      setLoading(true);
      try {
        const params: ShopProductParams = {
          page: String(currentPage),
          per_page: "20",
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
  }, [currentPage, sort, sortodr, caId, query, priceFrom, priceTo, searchParams, effectiveTypeKey, explicitTypeKey]);

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

  return (
    <div>
      <Breadcrumb items={[{ label: "쇼핑몰", href: "/shop" }, { label: "전체 상품" }]} />

      <section className="page-hero mb-4">
        <div className="flex flex-col justify-between gap-4 md:flex-row md:items-end">
          <div>
            <p className="section-eyebrow">상품 탐색</p>
            <h1 className="page-hero-title">{listTitle}</h1>
            <p className="page-hero-desc">총 {total.toLocaleString("ko-KR")}개의 상품을 조건에 맞춰 살펴보세요.</p>
          </div>
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
        </div>
      </section>

      <div className="surface-toolbar mb-5">
        <form onSubmit={handleSearch} className="flex min-w-0 flex-1 gap-2">
          <div className="relative min-w-0 flex-1 sm:max-w-[360px]">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              type="text"
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

      </div>

      <div className="surface-toolbar mb-5 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap gap-2" role="group" aria-label="상품 정렬">
          {SORT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              aria-pressed={sort === opt.value}
              onClick={() => updateParams({ sort: sort === opt.value ? "" : opt.value, sortodr: "", page: "1" })}
              className={cn("btn btn-sm", sort === opt.value ? "btn-primary" : "btn-outline")}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <div className="flex items-center justify-between gap-3 sm:justify-end">
          <span className="whitespace-nowrap text-sm text-muted-foreground">총 {total.toLocaleString("ko-KR")}개</span>
          <div className="flex rounded-[4px] border border-border bg-base-100">
            <button
              type="button"
              aria-label="그리드 보기"
              aria-pressed={viewMode === "grid"}
              onClick={() => setViewMode("grid")}
              className={cn("p-2 transition-colors", viewMode === "grid" ? "bg-primary text-primary-foreground" : "hover:bg-accent")}
            >
              <LayoutGrid className="h-4 w-4" />
            </button>
            <button
              type="button"
              aria-label="목록 보기"
              aria-pressed={viewMode === "list"}
              onClick={() => setViewMode("list")}
              className={cn("p-2 transition-colors", viewMode === "list" ? "bg-primary text-primary-foreground" : "hover:bg-accent")}
            >
              <List className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {loading ? (
        <ProductListSkeleton viewMode={viewMode} />
      ) : products.length === 0 ? (
        <div className="surface-panel flex flex-col items-center justify-center py-20 text-center">
          <p className="text-lg font-bold text-muted-foreground">상품이 없습니다</p>
          <p className="mt-1 text-sm text-muted-foreground">다른 검색어나 필터를 사용해보세요.</p>
        </div>
      ) : viewMode === "grid" ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4">
          {products.map((product, index) => (
            <ProductCard
              key={product.it_id}
              product={product}
              priority={index < 4}
              productRewriteMode={productRewriteMode}
            />
          ))}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {products.map((product) => (
            <ProductListCard
              key={product.it_id}
              product={product}
              productRewriteMode={productRewriteMode}
            />
          ))}
        </div>
      )}

      <Pagination currentPage={currentPage} totalPages={totalPages} onPageChange={(page) => updateParams({ page: String(page) })} />
    </div>
  );
}
