"use client";

import { useEffect, useState } from "react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { sanitizeCommerceHtml } from "@/lib/sanitize";
import { g5PathForRuntime } from "@/lib/config";
import { applyClientPageMetadata } from "@/lib/client-metadata";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import { getClientContent, getClientContentBySeo } from "@/services/content";
import type { ContentData } from "@/lib/schemas";

function decodeRouteSegment(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

export default function ContentPage() {
  const co_id = useRuntimeRouteParam("co_id", "/content/:co_id");
  const isLegacySeoPath =
    typeof window !== "undefined" &&
    window.location.pathname !== "/" &&
    window.location.pathname.endsWith("/") &&
    /\/content\//.test(window.location.pathname);
  const [content, setContent] = useState<ContentData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchContent() {
      try {
        setLoading(true);
        setError(null);
        if (isLegacySeoPath) {
          const data = await getClientContentBySeo(decodeRouteSegment(co_id));
          if (data?.co_id) {
            window.location.replace(g5PathForRuntime(`/content/${data.co_id}`));
            return;
          }

          setContent(null);
          setError("컨텐츠를 찾을 수 없습니다.");
          return;
        }

        const data = await getClientContent(co_id);
        if (data) {
          setContent(data);
        } else {
          setError("컨텐츠를 찾을 수 없습니다.");
        }
      } catch {
        setError("컨텐츠를 불러오는데 실패했습니다.");
      } finally {
        setLoading(false);
      }
    }

    if (co_id) {
      fetchContent();
    }
  }, [co_id, isLegacySeoPath]);

  useEffect(() => {
    if (!content) return;

    applyClientPageMetadata({
      title: content.co_subject,
      description: content.co_content,
      path: `/content/${content.co_id}`,
    });
  }, [content]);

  if (loading) {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-12">
        <div className="animate-pulse space-y-4">
          <div className="h-8 w-48 rounded bg-muted" />
          <div className="h-4 w-full rounded bg-muted" />
          <div className="h-4 w-3/4 rounded bg-muted" />
          <div className="h-4 w-1/2 rounded bg-muted" />
        </div>
      </div>
    );
  }

  if (error || !content) {
    return (
      <div className="container mx-auto max-w-4xl px-4 py-12">
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-center">
          <p className="text-destructive">{error || "컨텐츠를 찾을 수 없습니다."}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto max-w-4xl px-4 py-12">
      <Breadcrumb items={[{ label: content.co_subject }]} />
      <article>
        <header className="mb-8 border-b pb-4">
          <h1 className="text-2xl font-bold">{content.co_subject}</h1>
        </header>
        <div
          className="prose prose-sm dark:prose-invert max-w-none"
          dangerouslySetInnerHTML={{ __html: sanitizeCommerceHtml(content.co_content) }}
        />
      </article>
    </div>
  );
}
