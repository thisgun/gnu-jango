"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useRouter } from "@bprogress/next/app";
import type { ShopCategory, ShopProduct } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { ShopListHeader } from "@/components/shop/ShopListHeader";
import { SoluneProductCard } from "@/components/shop/SoluneProductCard";
import { Button } from "@/components/ui/button";
import { applyClientPageMetadata } from "@/lib/client-metadata";
import { g5ShortHref } from "@/lib/g5-short-url";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import { useShopListView } from "@/hooks/useShopListView";
import { getShopCategoryProductPage } from "@/services/shop";
import { getClientPublicSettings } from "@/services/settings";
import { ChevronLeft, ChevronRight } from "lucide-react";

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
  const [listView, setListView] = useShopListView();
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
        <ProductGridSkeleton viewMode={listView} />
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
      {/* 레퍼런스 목록 머리: 제목 · 빵부스러기(분류 ▾) · 하위 분류 · 정렬 줄 · 리스트/갤러리 전환. */}
      <ShopListHeader
        title={category.ca_name}
        category={category}
        subcategories={subcategories}
        total={meta.total}
        sort={sort}
        onSortChange={(value) => updateParams({ sort: sort === value ? "" : value, sortodr: "", page: "1" })}
        view={listView}
        onViewChange={setListView}
      />

      {products.length === 0 ? (
        <div className="surface-panel flex flex-col items-center justify-center py-20 text-center">
          <p className="text-lg font-bold text-muted-foreground">이 카테고리에는 상품이 없습니다</p>
        </div>
      ) : (
        // 리스트/갤러리 모양은 data-view 를 보고 solune-shop.list.css 가 정한다(카드는 같은 한 장).
        <div className="shop-product-list grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-4" data-view={listView}>
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
