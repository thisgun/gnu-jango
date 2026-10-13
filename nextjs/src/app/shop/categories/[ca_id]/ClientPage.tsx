"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useRouter } from "@bprogress/next/app";
import { LayoutGrid, List } from "lucide-react";
import type { ShopCategory, ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { ProductCard } from "@/components/shop/ProductGridSection";
import { ProductListCard } from "@/components/shop/ProductListCard";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { applyClientPageMetadata } from "@/lib/client-metadata";
import { g5ShortHref } from "@/lib/g5-short-url";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import { cn } from "@/lib/utils";
import { getShopCategoryProductPage } from "@/services/shop";
import { getClientPublicSettings } from "@/services/settings";
import { ChevronLeft, ChevronRight } from "lucide-react";

const SORT_OPTIONS = [
  { value: "popular", label: "판매많은순" },
  { value: "price_asc", label: "낮은가격순" },
  { value: "price_desc", label: "높은가격순" },
  { value: "rating", label: "평점높은순" },
  { value: "reviews", label: "후기많은순" },
  { value: "latest", label: "최근등록순" },
];

function ProductGridSkeleton({ viewMode }: { viewMode: "grid" | "list" }) {
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

export default function CategoryPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const ca_id =
    useRuntimeRouteParam("ca_id", [
      "/shop/categories/:ca_id",
      "/shop/list-:ca_id",
    ]) ||
    searchParams.get("__g5_ca_id") ||
    "";

  const [category, setCategory] = useState<ShopCategory | null>(null);
  const [subcategories, setSubcategories] = useState<ShopCategory[]>([]);
  const [products, setProducts] = useState<ShopProduct[]>([]);
  const [loading, setLoading] = useState(true);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [errorMessage, setErrorMessage] = useState("");
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);
  const previousCategoryRef = useRef<string | null>(null);
  const [meta, setMeta] = useState({
    total: 0,
    current_page: 1,
    last_page: 1,
  });

  const currentPage = Number(searchParams.get("page") || "1");
  const sort = searchParams.get("sort") || "";
  const sortodr = searchParams.get("sortodr") || "";

  useEffect(() => {
    if (!ca_id) return;

    const previousCategory = previousCategoryRef.current;
    previousCategoryRef.current = ca_id;

    if (previousCategory && previousCategory !== ca_id && currentPage > 1) {
      const params = new URLSearchParams(searchParams.toString());
      params.delete("page");
      const search = params.toString();
      runtimeRouterPush(router, g5ShortHref(`/shop/categories/${ca_id}${search ? `?${search}` : ""}`));
    }
  }, [ca_id, currentPage, router, searchParams]);

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

  const updateParams = useCallback(
    (updates: Record<string, string>) => {
      const params = new URLSearchParams(searchParams.toString());
      Object.entries(updates).forEach(([key, value]) => {
        if (value) params.set(key, value);
        else params.delete(key);
      });
      const search = params.toString();
      runtimeRouterPush(router, g5ShortHref(`/shop/categories/${ca_id}${search ? `?${search}` : ""}`));
    },
    [router, searchParams, ca_id]
  );

  useEffect(() => {
    if (!ca_id) {
      setCategory(null);
      setSubcategories([]);
      setProducts([]);
      setErrorMessage("");
      setLoading(true);
      return;
    }

    let alive = true;

    const loadCategory = async () => {
      setLoading(true);
      setErrorMessage("");
      try {
        const params = {
          page: String(currentPage),
          per_page: "20",
          ...(sort ? { sort } : {}),
          ...(sortodr ? { sortodr } : {}),
        };
        const data = await getShopCategoryProductPage(ca_id, params);
        if (!alive) return;

        if (!data) {
          setCategory(null);
          setSubcategories([]);
          setProducts([]);
          setErrorMessage("카테고리를 찾을 수 없습니다");
          setMeta({ total: 0, current_page: 1, last_page: 1 });
          return;
        }
        setCategory(data.category);
        setSubcategories(data.subcategories);
        setProducts(data.items);
        setErrorMessage("");
        setMeta({
          total: data.meta.total,
          current_page: data.meta.current_page,
          last_page: data.meta.last_page,
        });
      } catch (err: unknown) {
        if (!alive) return;
        setCategory(null);
        setSubcategories([]);
        setProducts([]);
        setErrorMessage(err instanceof Error ? err.message : "카테고리를 불러오지 못했습니다");
        setMeta({ total: 0, current_page: 1, last_page: 1 });
      } finally {
        if (alive) setLoading(false);
      }
    };
    loadCategory();

    return () => {
      alive = false;
    };
  }, [ca_id, currentPage, sort, sortodr]);

  useEffect(() => {
    if (!category) return;

    applyClientPageMetadata({
      title: category.ca_name,
      description: `${category.ca_name} 카테고리에서 ${meta.total}개의 상품을 확인하세요.`,
      path: `/shop/categories/${category.ca_id}`,
    });
  }, [category, meta.total]);

  if (loading) {
    return (
      <div>
        <div className="mb-9 mt-8 h-8 w-56 max-w-full animate-pulse rounded bg-muted" />
        <div className="mb-10 h-4 w-36 animate-pulse rounded bg-muted" />
        <ProductGridSkeleton viewMode={viewMode} />
      </div>
    );
  }

  if (!category && errorMessage) {
    return (
      <div className="surface-panel flex flex-col items-center justify-center py-20 text-center">
        <p className="text-lg font-bold">{errorMessage}</p>
        <Button variant="outline" className="mt-4" asChild>
          <a href="/shop">쇼핑몰로 이동</a>
        </Button>
      </div>
    );
  }

  if (!category) {
    return (
      <div className="surface-panel flex flex-col items-center justify-center py-20 text-center">
        <p className="text-lg font-bold">카테고리를 찾을 수 없습니다</p>
        <Button variant="outline" className="mt-4" asChild>
          <a href="/shop">쇼핑몰로 이동</a>
        </Button>
      </div>
    );
  }

  const pages: number[] = [];
  const start = Math.max(1, meta.current_page - 2);
  const end = Math.min(meta.last_page, meta.current_page + 2);
  for (let i = start; i <= end; i++) pages.push(i);

  return (
    <div>
      <h1 className="mb-9 mt-8 text-2xl font-bold">{category.ca_name} 상품리스트</h1>
      <div className="mb-10">
        <Breadcrumb items={[{ label: "쇼핑몰", href: "/shop" }, { label: category.ca_name }]} />
      </div>

      {subcategories.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-2">
          {subcategories.map((sub) => (
            <a key={sub.ca_id} href={g5ShortHref(`/shop/categories/${sub.ca_id}`)} className="filter-chip">
              {sub.ca_name}
              {sub.item_count !== undefined && <span className="ml-1">({sub.item_count})</span>}
            </a>
          ))}
        </div>
      )}

      <div className="mb-10 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
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
          <span className="whitespace-nowrap text-sm text-muted-foreground">총 {meta.total.toLocaleString("ko-KR")}개</span>
          <div className="flex rounded-[4px] border border-border bg-base-100" role="group" aria-label="상품 보기 방식">
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

      {products.length === 0 ? (
        <div className="surface-panel flex flex-col items-center justify-center py-20 text-center">
          <p className="text-lg font-bold text-muted-foreground">이 카테고리에는 상품이 없습니다</p>
        </div>
      ) : (
        viewMode === "grid" ? (
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
        )
      )}

      {meta.last_page > 1 && (
        <div className="mt-8 flex items-center justify-center gap-1">
          <Button
            variant="outline"
            size="icon"
            disabled={currentPage <= 1}
            onClick={() => updateParams({ page: String(currentPage - 1) })}
            aria-label="이전 페이지"
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          {start > 1 && (
            <>
              <Button variant="outline" size="sm" onClick={() => updateParams({ page: "1" })}>
                1
              </Button>
              {start > 2 && <span className="px-1 text-muted-foreground">...</span>}
            </>
          )}
          {pages.map((p) => (
            <Button
              key={p}
              variant={p === currentPage ? "default" : "outline"}
              size="sm"
              onClick={() => updateParams({ page: String(p) })}
            >
              {p}
            </Button>
          ))}
          {end < meta.last_page && (
            <>
              {end < meta.last_page - 1 && <span className="px-1 text-muted-foreground">...</span>}
              <Button variant="outline" size="sm" onClick={() => updateParams({ page: String(meta.last_page) })}>
                {meta.last_page}
              </Button>
            </>
          )}
          <Button
            variant="outline"
            size="icon"
            disabled={currentPage >= meta.last_page}
            onClick={() => updateParams({ page: String(currentPage + 1) })}
            aria-label="다음 페이지"
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      )}
    </div>
  );
}
