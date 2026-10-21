"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useRouter } from "@bprogress/next/app";
import { ApiError } from "@/lib/api";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { G5Link } from "@/components/ui/g5-link";
import { g5PathForRuntime } from "@/lib/config";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { recordSearchClick, searchUnified, type SearchKind } from "@/services/search";

const kinds: Array<{ value: SearchKind; label: string }> = [
  { value: "all", label: "전체" }, { value: "post", label: "게시글" },
  { value: "product", label: "상품" }, { value: "document", label: "문서·매뉴얼" },
];

export default function UnifiedResults() {
  const params = useSearchParams();
  const router = useRouter();
  const query = (params.get("q") || params.get("stx") || "").trim();
  const kind = kinds.find((item) => item.value === params.get("type"))?.value ?? "all";
  const page = Math.max(1, Math.min(200, Number.parseInt(params.get("page") || "1", 10) || 1));
  const [input, setInput] = useState(query);
  const [data, setData] = useState<Awaited<ReturnType<typeof searchUnified>> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notReady, setNotReady] = useState(false);
  const currentPage = data?.meta?.current_page ?? page;

  useEffect(() => {
    let cancelled = false;
    setInput(query);
    setData(null);
    setError(null);
    setNotReady(false);
    if (!query) { setLoading(false); return; }
    setLoading(true);
    searchUnified(query, kind, page).then((result) => {
      if (!cancelled) setData(result);
    }).catch((failure: unknown) => {
      if (cancelled) return;
      setNotReady(failure instanceof ApiError && failure.code === "search_index_not_ready");
      setError(failure instanceof ApiError ? failure.message : "검색 결과를 불러오지 못했습니다.");
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [query, kind, page]);

  function navigate(nextQuery: string, nextKind = kind, nextPage = 1) {
    const search = new URLSearchParams();
    if (nextQuery) search.set("q", nextQuery);
    if (nextKind !== "all") search.set("type", nextKind);
    if (nextPage > 1) search.set("page", String(nextPage));
    runtimeRouterPush(router, `/search${search.size ? `?${search}` : ""}`);
  }

  return (
    <div className="search-page container mx-auto max-w-3xl px-4 py-8">
      <Breadcrumb items={[{ label: "통합 검색" }]} />
      <h1 className="search-title mb-3 text-3xl font-bold">통합 검색</h1>
      <p className="mb-6 text-sm text-base-content/70">게시글, 상품, 문서와 매뉴얼을 한 번에 찾아보세요.</p>
      <form className="mb-5 flex gap-2" action={g5PathForRuntime("/search")} method="get" onSubmit={(event) => {
        event.preventDefault(); navigate(input.trim());
      }}>
        <label htmlFor="unified-search-query" className="sr-only">검색어</label>
        <input id="unified-search-query" className="input min-w-0 flex-1" type="search" name="q"
          minLength={2} maxLength={200} value={input} onChange={(event) => setInput(event.target.value)}
          placeholder="예: 입금 확인은 어떻게 하나요?" />
        <button type="submit" className="btn">검색</button>
      </form>
      <nav aria-label="검색 종류" className="mb-6 flex flex-wrap gap-2">
        {kinds.map((item) => (
          <button key={item.value} type="button" className={`btn btn-sm ${kind === item.value ? "btn-active" : ""}`}
            aria-pressed={kind === item.value} onClick={() => navigate(query, item.value)}>{item.label}</button>
        ))}
      </nav>
      {loading && <p role="status" className="py-8 text-sm text-base-content/70">검색 결과를 불러오는 중...</p>}
      {error && (
        <div className="space-y-4">
          <ErrorState title={notReady ? "통합 검색을 준비 중입니다" : "검색 결과를 불러오지 못했습니다"} description={error} />
          <a className="btn" href={g5PathForRuntime(`/search?q=${encodeURIComponent(query)}&legacy=1`)}>기존 게시판 검색 이용하기</a>
        </div>
      )}
      {!query && <p className="py-8 text-sm text-base-content/70">궁금한 내용을 두 글자 이상 입력해 주세요. 상품명이나 질문으로도 검색할 수 있습니다.</p>}
      {!loading && !error && data && (
        <section aria-label="검색 결과" className="space-y-4">
          <p role="status" className="text-sm text-base-content/70">검색 결과 {(data.meta?.total ?? data.results.length).toLocaleString("ko-KR")}건</p>
          {data.results.length === 0 && <EmptyState title="검색 결과가 없습니다" description="다른 단어나 자료 종류로 다시 검색해 보세요." />}
          {data.results.map((row) => (
            <article key={`${row.type}:${row.bo_subject ?? ""}:${row.id}`} className="card border border-base-300 bg-base-100">
              <div className="card-body gap-2 p-5">
                <p className="text-xs text-base-content/60">{kinds.find((item) => item.value === row.type)?.label}{row.bo_subject ? ` · ${row.bo_subject}` : ""}</p>
                <h2 className="card-title break-words text-base">
                  <G5Link href={g5PathForRuntime(row.url)} className="hover:underline"
                    onClick={() => recordSearchClick(row.click_token)}>{row.title}</G5Link>
                </h2>
                {row.snippet && <p className="line-clamp-3 break-words text-sm leading-relaxed text-base-content/70">{row.snippet}</p>}
                {typeof row.price === "number" && <p className="text-sm font-semibold">{row.price.toLocaleString("ko-KR")}원</p>}
              </div>
            </article>
          ))}
          {data.meta?.truncated && <p className="text-sm text-base-content/70">관련도가 높은 200건까지 표시합니다. 자료 종류를 좁히거나 특징적인 단어로 다시 검색해 보세요.</p>}
          <nav aria-label="검색 결과 페이지" className="flex items-center justify-center gap-3 pt-4">
            {currentPage > 1 && <button className="btn btn-sm" onClick={() => navigate(query, kind, currentPage - 1)}>이전</button>}
            <span className="text-sm">{currentPage} / {data.meta?.total_pages ?? 1}</span>
            {currentPage < (data.meta?.total_pages ?? 1) && <button className="btn btn-sm" onClick={() => navigate(query, kind, currentPage + 1)}>다음</button>}
          </nav>
        </section>
      )}
    </div>
  );
}
