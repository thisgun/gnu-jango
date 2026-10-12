"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { g5ShortHref } from "@/lib/g5-short-url";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { formatDate } from "@/lib/utils";
import { searchSite } from "@/services/search";
import { getClientPublicSettings } from "@/services/settings";
import type { SearchResult } from "@/lib/schemas";
import { boardPostHref } from "@/lib/board-url";

function toPage(value: string | null): number {
  const parsed = Number.parseInt(value || "1", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

export default function ClientPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const query = (searchParams.get("q") || searchParams.get("stx") || "").trim();
  const sfl = searchParams.get("sfl") || undefined;
  const boTable = searchParams.get("bo_table") || undefined;
  const page = toPage(searchParams.get("page"));
  const [input, setInput] = useState(query);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [bbsRewriteMode, setBbsRewriteMode] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setInput(query);
    if (!query) {
      setResults([]);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    Promise.all([
      searchSite({ query, sfl, boTable, page }),
      getClientPublicSettings().catch(() => null),
    ])
      .then(([result, settings]) => {
        if (cancelled) return;
        setBbsRewriteMode(Number(settings?.cf_bbs_rewrite ?? 0));
        if (result.ok) {
          setResults(result.data);
          setError(null);
        } else {
          setResults([]);
          setError(result.error);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setResults([]);
          setError("검색 결과를 불러오지 못했습니다.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [boTable, page, query, sfl]);

  return (
    <div className="container mx-auto max-w-3xl px-4 py-8">
      <Breadcrumb items={[{ label: "검색" }]} />
      <h1 className="mb-8 text-3xl font-bold">검색</h1>

      <form
        className="mb-8 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          const next = input.trim();
          const params = new URLSearchParams();
          if (next) params.set("q", next);
          if (sfl) params.set("sfl", sfl);
          if (boTable) params.set("bo_table", boTable);
          const target = params.toString();
          runtimeRouterPush(router, target ? `/search?${target}` : "/search");
        }}
      >
        <Input value={input} onChange={(event) => setInput(event.target.value)} placeholder="검색어" />
        <Button type="submit">검색</Button>
      </form>

      {loading && <p className="text-sm text-muted-foreground">검색 중...</p>}

      {error && <ErrorState title="검색 결과를 불러오지 못했습니다" description={error} />}

      {!loading && !error && query && results.length === 0 && (
        <EmptyState title="검색 결과가 없습니다" description={`"${query}"에 대한 결과가 없습니다.`} />
      )}

      {!error && results.length > 0 && (
        <div className="space-y-6">
          {results.map((group) => (
            <Card key={group.bo_table}>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-lg">
                  <a href={g5ShortHref(`/boards/${group.bo_table}`)} className="hover:text-primary">
                    {group.bo_subject}
                  </a>
                  <Badge variant="secondary">{group.list.length}</Badge>
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="divide-y">
                  {group.list.map((item) => (
                    <li key={item.wr_id} className="flex items-start justify-between gap-4 py-3">
                      <a
                        href={boardPostHref(group.bo_table, item, bbsRewriteMode)}
                        className="min-w-0 flex-1 break-words text-sm hover:text-primary"
                      >
                        {item.wr_subject}
                      </a>
                      <span className="shrink-0 text-xs text-muted-foreground">{formatDate(item.wr_datetime)}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
