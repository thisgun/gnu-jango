"use client";

import { G5Link as Link } from "@/components/ui/g5-link";
import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { HelpCircle, Search } from "lucide-react";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { cn } from "@/lib/utils";
import { sanitizeCommerceHtml, sanitizeInlineHtml } from "@/lib/sanitize";
import { getFaqs } from "@/services/faqs";
import type { FaqPageData } from "@/lib/types";

function buildFaqHref({ fmId, stx, page }: { fmId?: number; stx?: string; page?: number }) {
  const params = new URLSearchParams();
  if (fmId) params.set("fm_id", String(fmId));
  if (stx) params.set("stx", stx);
  if (page && page > 1) params.set("page", String(page));
  const query = params.toString();
  return query ? `/faq?${query}` : "/faq";
}

export default function ClientPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const fmId = Math.max(0, Number(searchParams.get("fm_id") || "0") || 0);
  const keyword = (searchParams.get("stx") || "").trim();
  const page = Math.max(1, Number(searchParams.get("page") || "1") || 1);
  const [term, setTerm] = useState(keyword);
  const [data, setData] = useState<FaqPageData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setTerm(keyword);
    setData(null);
    setError(null);
    setLoading(true);
    let cancelled = false;
    getFaqs({ fmId, stx: keyword, page })
      .then((result) => {
        if (cancelled) return;
        if (result.ok) {
          setData(result.data);
          setError(null);
        } else {
          setData(null);
          setError(result.error);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setData(null);
        setError(err instanceof Error ? err.message : "FAQ를 불러오지 못했습니다.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [fmId, keyword, page]);

  const currentFmId = data?.current?.fm_id;

  return (
    <div className="container mx-auto max-w-4xl px-4 py-8">
      <Breadcrumb items={[{ label: "FAQ" }]} />
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">FAQ</h1>
          <p className="mt-1 text-sm text-muted-foreground">자주 묻는 질문을 확인하세요.</p>
        </div>
        {data && <span className="text-sm text-muted-foreground">총 {data.meta.total.toLocaleString()}건</span>}
      </div>

      {data && data.masters.length > 0 && (
        <div className="mb-5 flex gap-2 overflow-x-auto border-b">
          {data.masters.map((master) => (
            <Link
              key={master.fm_id}
              href={buildFaqHref({ fmId: master.fm_id, stx: keyword })}
              className={cn(
                "whitespace-nowrap border-b-2 px-4 py-2 text-sm font-medium",
                master.fm_id === currentFmId ? "border-primary text-primary" : "border-transparent text-muted-foreground"
              )}
            >
              {master.fm_subject}
            </Link>
          ))}
        </div>
      )}

      <form
        className="mb-6 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          const params = new URLSearchParams();
          if (currentFmId) params.set("fm_id", String(currentFmId));
          if (term.trim()) params.set("stx", term.trim());
          runtimeRouterPush(router, params.toString() ? `/faq?${params.toString()}` : "/faq");
        }}
      >
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={term} onChange={(event) => setTerm(event.target.value)} placeholder="FAQ 검색" className="pl-9" />
        </div>
        <Button type="submit">검색</Button>
      </form>

      {loading && (
        <p role="status" className="text-sm text-muted-foreground">
          로딩 중...
        </p>
      )}
      {!loading && error && <ErrorState title="FAQ를 불러오지 못했습니다" description={error} actionHref="/faq" />}
      {!loading && !data && !error && <p className="text-sm text-muted-foreground">FAQ가 없습니다.</p>}

      {!loading && data && (
        <Card>
          <CardContent className="p-0">
            {data.items.length === 0 ? (
              <EmptyState className="m-4" icon={<HelpCircle className="size-6" />} title="등록된 FAQ가 없습니다" />
            ) : (
              <div className="divide-y">
                {data.items.map((item, index) => (
                  <details key={item.fa_id} className="group" open={index === 0 && page === 1}>
                    <summary className="flex cursor-pointer list-none items-start gap-3 px-4 py-4 hover:bg-muted/50">
                      <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-sm font-bold text-primary">Q</span>
                      <span className="min-w-0 flex-1 text-sm font-medium" dangerouslySetInnerHTML={{ __html: sanitizeInlineHtml(item.fa_subject) }} />
                    </summary>
                    <div className="border-t bg-muted/20 px-4 py-5">
                      <div className="prose prose-sm max-w-none dark:prose-invert" dangerouslySetInnerHTML={{ __html: sanitizeCommerceHtml(item.fa_content) }} />
                    </div>
                  </details>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
