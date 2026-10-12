"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { G5Link as Link } from "@/components/ui/g5-link";
import { runtimeRouterPush } from "@/lib/runtime-router";
import type { RecentGroup } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { X } from "lucide-react";

interface Props {
  groups: RecentGroup[];
  initialView: string;
  initialGroup: string;
  mbId: string;
}

export function RecentFilters({ groups, initialView, initialGroup, mbId }: Props) {
  const router = useRouter();
  const sp = useSearchParams();

  const updateParam = (key: string, value: string) => {
    const next = new URLSearchParams(sp.toString());
    if (value) {
      next.set(key, value);
    } else {
      next.delete(key);
    }
    next.delete("page");
    runtimeRouterPush(router, `/recent?${next.toString()}`);
  };

  const clearMbFilter = () => {
    const next = new URLSearchParams(sp.toString());
    next.delete("mb_id");
    next.delete("page");
    runtimeRouterPush(router, `/recent?${next.toString()}`);
  };

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {/* 글/댓글 탭 */}
      <div className="inline-flex rounded-md border overflow-hidden text-sm">
        {[
          { v: "", label: "전체" },
          { v: "w", label: "글" },
          { v: "c", label: "댓글" },
        ].map((tab) => (
          <button
            key={tab.v || "all"}
            onClick={() => updateParam("view", tab.v)}
            className={
              "px-3 py-1.5 transition-colors " +
              (initialView === tab.v
                ? "bg-primary text-primary-foreground"
                : "hover:bg-accent")
            }
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* 그룹 select */}
      <select
        aria-label="그룹 선택"
        value={initialGroup}
        onChange={(e) => updateParam("gr_id", e.target.value)}
        className="border rounded px-3 py-1.5 text-sm bg-background"
      >
        <option value="">전체 그룹</option>
        {groups.map((g) => (
          <option key={g.gr_id} value={g.gr_id}>
            {g.gr_subject}
          </option>
        ))}
      </select>

      {/* 회원 필터 칩 (URL에 mb_id가 있을 때만) */}
      {mbId && (
        <div className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded border bg-accent text-sm">
          <span>작성자: {mbId}</span>
          <button
            onClick={clearMbFilter}
            aria-label="회원 필터 해제"
            className="hover:text-destructive"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {/* gnuboard 원본의 경계 */}
      <Link href="/recent" className="ml-auto">
        <Button variant="ghost" size="sm">초기화</Button>
      </Link>
    </div>
  );
}
