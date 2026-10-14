"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { useSearchParams } from "next/navigation";
import { useRouter } from "@bprogress/next/app";
import type { ShopQA } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import type { ApiMeta } from "@/lib/api-response";
import { shopProductHref } from "@/lib/product-url";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { shopQaListSchema } from "@/lib/schemas";
import { getClientPublicSettings } from "@/services/settings";
import { fetchShopBoardList, parseListPage } from "@/components/shop/shopBoardList";
import { ShopBoardPagination, ShopBoardSearchForm } from "@/components/shop/ShopBoardListControls";
import { ShopQaItem } from "./ShopQaItem";

/*
 * 상품문의 전체 목록 — 그누보드 shop/itemqalist.php(레퍼런스 solune 스킨)과 같은 짜임.
 *   검색 줄(항목 고르기 · 검색어 · 검색) → "전체 N건 | 전체보기" → 문의 하나가 한 줄인 접는 목록(ShopQaItem) → 쪽 번호.
 *   예전의 답변 상태 단추(전체 · 답변대기 · 답변완료)는 레퍼런스에 없고, 답변 상태는 줄마다 이름표로 보인다.
 */

/** 그누보드 itemqalist 의 검색 항목(sfl). 레퍼런스 API 가 같은 이름을 받는다. */
const SEARCH_FIELDS = [
  { value: "i.it_name", label: "상품명" },
  { value: "q.it_id", label: "상품코드" },
  { value: "q.iq_subject", label: "문의제목" },
  { value: "q.iq_question", label: "문의내용" },
  { value: "q.iq_name", label: "작성자명" },
  { value: "q.mb_id", label: "작성자아이디" },
] as const;
const DEFAULT_SEARCH_FIELD: string = SEARCH_FIELDS[0].value;
const PER_PAGE = 15;

export default function ShopQasPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const page = parseListPage(searchParams.get("page"));
  const query = (searchParams.get("q") || searchParams.get("stx") || "").trim();
  const requestedField = searchParams.get("sfl") || "";
  const field = SEARCH_FIELDS.some((option) => option.value === requestedField) ? requestedField : DEFAULT_SEARCH_FIELD;

  const [items, setItems] = useState<ShopQA[]>([]);
  const [meta, setMeta] = useState<ApiMeta | undefined>();
  const [loading, setLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [searchText, setSearchText] = useState(query);
  const [searchField, setSearchField] = useState(field);
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);

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
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    // 쪽 · 검색을 빨리 바꾸면 먼저 보낸 느린 응답이 나중 것을 덮지 않게, 지난 요청의 결과는 버린다.
    let alive = true;
    setLoading(true);
    setErrorMessage("");
    fetchShopBoardList("/shop/reviews/qna", shopQaListSchema, { page, perPage: PER_PAGE, q: query, sfl: field })
      .then((result) => {
        if (!alive) return;
        setItems(result.items);
        setMeta(result.meta);
      })
      .catch((err: unknown) => {
        if (!alive) return;
        setItems([]);
        setMeta(undefined);
        setErrorMessage(err instanceof Error ? err.message : "상품문의를 불러오지 못했습니다.");
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
    runtimeRouterPush(router, `/shop/qas${params.toString() ? `?${params}` : ""}`);
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

  return (
    <div className="shop-qas-page pt-6 md:pt-10">
      <h1 className="mb-6 text-[28px] font-bold tracking-tight">상품문의</h1>

      <ShopBoardSearchForm
        idPrefix="shop-qa"
        className="shop-qas-search"
        fields={SEARCH_FIELDS}
        field={searchField}
        text={searchText}
        onFieldChange={setSearchField}
        onTextChange={setSearchText}
        onSubmit={submitSearch}
      />

      <div className="mb-4 flex min-h-5 flex-wrap items-center justify-between gap-x-3 gap-y-2 text-sm text-muted-foreground">
        <span>
          {meta ? (
            <>
              {query ? "검색 결과" : "전체"}{" "}
              <strong className="font-medium tabular-nums text-foreground">{total.toLocaleString()}</strong>건
            </>
          ) : null}
        </span>
        <Link href="/shop/qas" className="underline underline-offset-[3px] hover:text-primary">
          전체보기
        </Link>
      </div>

      {loading ? (
        <ul className="flex flex-col gap-2.5">
          {Array.from({ length: 6 }).map((_, index) => (
            <li key={index} className="skeleton h-20 rounded-xl border" />
          ))}
        </ul>
      ) : errorMessage ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 py-16 text-center text-sm text-destructive">
          {errorMessage}
        </div>
      ) : items.length === 0 ? (
        <p className="py-16 text-center text-[13px] text-muted-foreground">자료가 없습니다.</p>
      ) : (
        <ol className="flex flex-col gap-2.5">
          {items.map((item) => (
            <ShopQaItem key={item.iq_id} item={item} productHref={shopProductHref(item, productRewriteMode)} />
          ))}
        </ol>
      )}

      <ShopBoardPagination page={page} lastPage={meta?.last_page ?? 1} onPageChange={goToPage} />
    </div>
  );
}
