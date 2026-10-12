"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { g5ShortHref } from "@/lib/g5-short-url";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { RecentFilters } from "./RecentFilters";
import { getRecentGroups, getRecentItems, type RecentResult } from "@/services/recent";
import type { RecentGroup } from "@/lib/types";

function formatRecentDate(datetime: string): string {
  if (!datetime) return "";
  const date = datetime.substring(0, 10);
  const today = new Date().toISOString().substring(0, 10);
  return date === today ? datetime.substring(11, 16) : datetime.substring(5, 10);
}

export default function ClientPage() {
  const searchParams = useSearchParams();
  const view = searchParams.get("view") === "w" || searchParams.get("view") === "c" ? (searchParams.get("view") as "w" | "c") : "";
  const grId = searchParams.get("gr_id") || "";
  const mbId = searchParams.get("mb_id") || "";
  const page = Math.max(1, Number(searchParams.get("page") || "1") || 1);
  const [groups, setGroups] = useState<RecentGroup[]>([]);
  const [result, setResult] = useState<RecentResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setResult(null);
    Promise.all([
      getRecentItems({ view, grId, mbId, page, limit: 20 }),
      getRecentGroups(),
    ])
      .then(([items, groupList]) => {
        if (!cancelled) {
          setResult(items);
          setGroups(groupList);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setResult(null);
          setGroups([]);
          setError(err instanceof Error ? err.message : "최근글을 불러오지 못했습니다.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [view, grId, mbId, page]);

  const items = result?.items ?? [];
  const displayError = error || result?.error || "";

  return (
    <div className="container mx-auto space-y-4 px-4 py-6">
      <Breadcrumb items={[{ label: "전체 게시물" }]} />
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-bold">전체 게시물</h1>
        {result && <span className="text-sm text-muted-foreground">총 {result.total.toLocaleString()}건</span>}
      </div>
      <RecentFilters groups={groups} initialView={view} initialGroup={grId} mbId={mbId} />
      {displayError && <ErrorState title="전체 게시물을 불러오지 못했습니다" description={displayError} actionHref="/recent" />}
      {loading && (
        <p role="status" className="text-sm text-muted-foreground">
          로딩 중...
        </p>
      )}
      {!loading && result && (
        <Card>
          <CardContent className="p-0">
            {items.length === 0 ? (
              <EmptyState className="min-h-[160px] border-0" title="표시할 글이 없습니다" />
            ) : (
              <table className="w-full text-sm">
                <tbody>
                  {items.map((item) => (
                    <tr key={item.bn_id} className="border-b hover:bg-muted/30">
                      <td className="px-4 py-3">
                        <a href={g5ShortHref(item.href)} className="hover:text-primary">
                          {item.is_comment && <Badge variant="secondary" className="mr-1.5 text-xs">댓글</Badge>}
                          {item.wr_subject}
                        </a>
                      </td>
                      <td className="hidden px-4 py-3 text-muted-foreground md:table-cell">{item.bo_subject}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">{formatRecentDate(item.wr_datetime)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
