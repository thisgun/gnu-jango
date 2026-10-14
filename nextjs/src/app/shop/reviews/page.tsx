"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { useSearchParams } from "next/navigation";
import { useRouter } from "@bprogress/next/app";
import type { ShopReview } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import type { ApiMeta } from "@/lib/api-response";
import { shopProductHref } from "@/lib/product-url";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { shopReviewListSchema } from "@/lib/schemas";
import { cn } from "@/lib/utils";
import { getClientPublicSettings } from "@/services/settings";
import { fetchShopBoardList, fetchShopReviewOverallSummary, parseListPage } from "@/components/shop/shopBoardList";
import { ShopBoardPagination, ShopBoardSearchForm } from "@/components/shop/ShopBoardListControls";
import { STAR_CLASS, ShopReviewCard, ShopReviewDialog } from "./ShopReviewCard";

/*
 * 사용후기 전체 목록 — 그누보드 shop/itemuselist.php(레퍼런스 solune 스킨)과 같은 짜임.
 *   검색 줄(항목 고르기 · 검색어 · 검색) → "전체 N건 · 평균 N.N★ | 전체보기" → 후기 하나가 카드 하나인 격자
 *   (상품 · 별점 · 제목 · 두 줄 발췌 · 사진 셋과 +N · 작성자 · 날짜 · 후기 바로가기 · 내용보기) → 쪽 번호.
 *   "내용보기" 는 이 자리에서 본문 전체를 겹창으로 연다.
 */

/** 그누보드 itemuselist 의 검색 항목(sfl). 레퍼런스 API 가 같은 이름을 받는다. */
const SEARCH_FIELDS = [
  { value: "i.it_name", label: "상품명" },
  { value: "r.it_id", label: "상품코드" },
  { value: "r.is_subject", label: "후기제목" },
  { value: "r.is_content", label: "후기내용" },
  { value: "r.is_name", label: "작성자명" },
  { value: "r.mb_id", label: "작성자아이디" },
] as const;
const DEFAULT_SEARCH_FIELD: string = SEARCH_FIELDS[0].value;
const PER_PAGE = 15;

export default function ShopReviewsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const page = parseListPage(searchParams.get("page"));
  const query = (searchParams.get("q") || searchParams.get("stx") || "").trim();
  const requestedField = searchParams.get("sfl") || "";
  const field = SEARCH_FIELDS.some((option) => option.value === requestedField) ? requestedField : DEFAULT_SEARCH_FIELD;

  const [items, setItems] = useState<ShopReview[]>([]);
  const [meta, setMeta] = useState<ApiMeta | undefined>();
  const [average, setAverage] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [searchText, setSearchText] = useState(query);
  const [searchField, setSearchField] = useState(field);
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);
  const [openReview, setOpenReview] = useState<ShopReview | null>(null);

  useEffect(() => {
    setSearchText(query);
    setSearchField(field);
  }, [query, field]);

  useEffect(() => {
    let alive = true;
    getClientPublicSettings()
      .then((settings) => {
        if (alive) setProductRewriteMode(settings.cf_bbs_rewrite);
      })
      .catch(() => {
        if (alive) setProductRewriteMode(0);
      });
    // 전체 평균은 검색과 상관없이 한 번 — 검색 중에는 보이지 않는다(레퍼런스와 같다).
    fetchShopReviewOverallSummary()
      .then((summary) => {
        if (alive && summary && summary.total > 0) setAverage(summary.average);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    // 쪽 · 검색을 빨리 바꾸면 먼저 보낸 느린 응답이 나중 것을 덮지 않게, 지난 요청의 결과는 버린다.
    let alive = true;
    setLoading(true);
    setErrorMessage("");
    fetchShopBoardList("/shop/reviews", shopReviewListSchema, { page, perPage: PER_PAGE, q: query, sfl: field })
      .then((result) => {
        if (!alive) return;
        setItems(result.items);
        setMeta(result.meta);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setItems([]);
        setMeta(undefined);
        setErrorMessage(err instanceof Error ? err.message : "사용후기를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [page, query, field]);

  const baseParams = useMemo(() => {
    const params = new URLSearchParams();
    if (query) {
      params.set("sfl", field);
      params.set("q", query);
    }
    return params;
  }, [field, query]);

  function moveTo(params: URLSearchParams) {
    runtimeRouterPush(router, `/shop/reviews${params.toString() ? `?${params}` : ""}`);
  }

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const params = new URLSearchParams();
    const nextQuery = searchText.trim();
    if (nextQuery) {
      params.set("sfl", searchField);
      params.set("q", nextQuery);
    }
    moveTo(params);
  }

  function goToPage(nextPage: number) {
    const params = new URLSearchParams(baseParams.toString());
    if (nextPage > 1) params.set("page", String(nextPage));
    moveTo(params);
  }

  const total = meta?.total ?? 0;
  const hrefFor = (item: ShopReview) => shopProductHref(item, productRewriteMode);

  return (
    <div className="shop-reviews-page pt-6 md:pt-10">
      <h1 className="mb-6 text-[28px] font-bold tracking-tight">사용후기</h1>

      <ShopBoardSearchForm
        idPrefix="shop-review"
        className="shop-reviews-search"
        fields={SEARCH_FIELDS}
        field={searchField}
        text={searchText}
        onFieldChange={setSearchField}
        onTextChange={setSearchText}
        onSubmit={submitSearch}
      />

      <div className="mb-4 flex min-h-5 flex-wrap items-center justify-between gap-x-3 gap-y-2 text-sm text-muted-foreground">
        <span>
          {query ? (
            <>
              검색 결과 <strong className="font-medium tabular-nums text-foreground">{total.toLocaleString()}</strong>건
            </>
          ) : meta ? (
            <>
              전체 <strong className="font-medium tabular-nums text-foreground">{total.toLocaleString()}</strong>건
              {average !== null ? (
                <>
                  <span className="mx-1.5" aria-hidden="true">·</span>
                  평균 <strong className="font-medium tabular-nums text-foreground">{average.toFixed(1)}</strong>
                  <span className={cn("ml-0.5", STAR_CLASS)} aria-hidden="true">★</span>
                </>
              ) : null}
            </>
          ) : null}
        </span>
        <Link href="/shop/reviews" className="underline underline-offset-[3px] hover:text-primary">
          전체보기
        </Link>
      </div>

      {/* 칸 수는 화면 폭이 아니라 이 목록이 받은 폭으로 정한다(셋 · 둘 · 하나). */}
      <div className="@container">
        {loading ? (
          <ul className="grid grid-cols-1 gap-3.5 @min-[620px]:grid-cols-2 @min-[900px]:grid-cols-3">
            {Array.from({ length: 6 }).map((_, index) => (
              <li key={index} className="skeleton h-64 rounded-xl border" />
            ))}
          </ul>
        ) : errorMessage ? (
          <div className="rounded-xl border border-destructive/30 bg-destructive/5 py-16 text-center text-sm text-destructive">
            {errorMessage}
          </div>
        ) : items.length === 0 ? (
          <p className="py-16 text-center text-[13px] text-muted-foreground">자료가 없습니다.</p>
        ) : (
          <ul className="grid grid-cols-1 gap-3.5 @min-[620px]:grid-cols-2 @min-[900px]:grid-cols-3">
            {items.map((item) => (
              <ShopReviewCard key={item.is_id} item={item} productHref={hrefFor(item)} onOpen={() => setOpenReview(item)} />
            ))}
          </ul>
        )}
      </div>

      <ShopBoardPagination page={page} lastPage={meta?.last_page ?? 1} onPageChange={goToPage} />

      <ShopReviewDialog
        item={openReview}
        productHref={openReview ? hrefFor(openReview) : "/shop"}
        onClose={() => setOpenReview(null)}
      />
    </div>
  );
}
