"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { useSearchParams } from "next/navigation";
import { useRouter } from "@bprogress/next/app";
import { HelpCircle, PenSquare } from "lucide-react";
import { runtimeRouterPush } from "@/lib/runtime-router";
import type { ApiMeta } from "@/lib/api-response";
import type { QaConfig, QaItem } from "@/lib/types";
import { cn } from "@/lib/utils";
import { g5ShortHref } from "@/lib/g5-short-url";
import { getQaConfig, getQas } from "@/services/qas";
import { Button } from "@/components/ui/button";
import { Pagination } from "@/components/ui/pagination";
import { toastError } from "@/lib/toast";
import { MypagePanel } from "../MypagePanel";
import { QaListRow, QaSearchForm, qaSearchField, type QaSearchField } from "./QaListParts";

/*
 * 1:1 문의 목록(레퍼런스 mypage/qas) — 그누보드 bbs/qalist.php 처럼 회원은 자기 문의만 본다.
 * 흰 카드 한 장(MypagePanel) 안에 답변 상태 알약 탭(g5-tabs) · 검색 · 번호 붙은 목록 · 쪽 번호.
 * 제목 길이는 1:1문의 설정(qa_subject_len)을 따른다. 쪽당 줄 수는 이 화면이 20 으로 정한다.
 */

const STATUS_TABS = [
  { value: "all" as const, label: "전체" },
  { value: 0 as const, label: "답변대기" },
  { value: 1 as const, label: "답변완료" },
];

export default function MyQasPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const page = Math.max(1, Number(searchParams.get("page") || "1"));
  const statusParam = searchParams.get("status");
  const status = statusParam === "0" || statusParam === "1" ? Number(statusParam) : "all";
  const sca = searchParams.get("sca") || undefined;
  const stx = searchParams.get("stx") || searchParams.get("q") || undefined;
  const sfl = qaSearchField(searchParams.get("sfl"));

  const [config, setConfig] = useState<QaConfig | null>(null);
  const [items, setItems] = useState<QaItem[]>([]);
  const [meta, setMeta] = useState<ApiMeta | undefined>();
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getQaConfig()
      .then(setConfig)
      .catch(() => setConfig(null));
  }, []);

  // 가장 마지막 요청의 응답만 쓴다 — 쪽 · 상태를 빠르게 바꿀 때 앞 요청이 늦게 와서 덮지 않게.
  const requestSeq = useRef(0);
  const loadQas = useCallback(async () => {
    const request = ++requestSeq.current;
    setLoading(true);
    try {
      const result = await getQas({
        page,
        perPage: 20,
        status: status as 0 | 1 | "all",
        sca,
        sfl,
        stx,
      });
      if (request !== requestSeq.current) return;
      setItems(result.items);
      setMeta(result.meta);
    } catch (error) {
      if (request !== requestSeq.current) return;
      setItems([]);
      setMeta(undefined);
      toastError(error instanceof Error ? error.message : "1:1 문의를 불러오지 못했습니다.");
    } finally {
      if (request === requestSeq.current) setLoading(false);
    }
  }, [page, sca, sfl, status, stx]);

  useEffect(() => {
    loadQas();
  }, [loadQas]);

  /** 주소의 조건을 바꾼다(쪽은 처음으로). undefined 는 지운다. */
  function updateQuery(patch: Record<string, string | undefined>) {
    const params = new URLSearchParams(searchParams.toString());
    params.delete("page");
    params.delete("q");
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined || value === "") params.delete(key);
      else params.set(key, value);
    }
    const query = params.toString();
    runtimeRouterPush(router, `/mypage/qas${query ? `?${query}` : ""}`);
  }

  const lastPage = meta?.last_page ?? 1;
  const perPage = meta?.per_page || items.length;
  const total = meta?.total ?? items.length;

  return (
    <MypagePanel
      title="1:1 문의"
      description="문의를 남기고 답변 상태를 확인합니다."
      actions={
        <Button asChild>
          <Link href="/mypage/qas/new">
            <PenSquare className="mr-2 size-4" />
            문의하기
          </Link>
        </Button>
      }
    >
      <div className="g5-tabs flex flex-wrap gap-2 border-b">
        {STATUS_TABS.map((item) => (
          <button
            key={String(item.value)}
            type="button"
            onClick={() => updateQuery({ status: item.value === "all" ? undefined : String(item.value) })}
            aria-pressed={status === item.value}
            className={cn(
              "g5-tab border-b-2 px-4 py-2 text-sm font-medium transition-colors",
              status === item.value
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {item.label}
          </button>
        ))}
        {meta && (
          <span className="ml-auto self-center text-xs text-muted-foreground">
            총 {meta.total.toLocaleString()}건 · {page} 페이지
          </span>
        )}
      </div>

      <QaSearchForm
        key={`${sfl}:${stx ?? ""}`}
        field={sfl}
        keyword={stx}
        onSearch={(field: QaSearchField, keyword) => updateQuery({ sfl: field, stx: keyword })}
        onReset={() => updateQuery({ sfl: undefined, stx: undefined })}
      />

      <div>
        {loading ? (
          <div className="space-y-3">
            {Array.from({ length: 4 }).map((_, index) => (
              <div key={index} className="skeleton h-20 rounded-md" />
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <HelpCircle className="mb-3 size-12 text-muted-foreground/50" />
            <p className="text-sm text-muted-foreground">{stx ? "검색 결과가 없습니다." : "등록된 문의가 없습니다."}</p>
          </div>
        ) : (
          <ul className="divide-y rounded-md border">
            {items.map((item, index) => (
              <QaListRow
                key={item.qa_id}
                item={item}
                number={total - (page - 1) * perPage - index}
                subjectLength={config?.qa_subject_len ?? 0}
              />
            ))}
          </ul>
        )}
      </div>

      <Pagination
        currentPage={Math.min(page, lastPage)}
        totalPages={lastPage}
        baseUrl={g5ShortHref("/mypage/qas")}
        searchParams={{
          status: status === "all" ? undefined : String(status),
          sca,
          sfl: stx ? sfl : undefined,
          stx,
        }}
      />
    </MypagePanel>
  );
}
