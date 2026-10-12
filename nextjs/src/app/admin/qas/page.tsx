"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { SearchIcon } from "lucide-react";
import { runtimeRouterPush } from "@/lib/runtime-router";
import type { ApiMeta } from "@/lib/api-response";
import type { QaItem } from "@/lib/types";
import { cn, formatDate, truncate } from "@/lib/utils";
import { getQas } from "@/services/qas";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { toastError } from "@/lib/toast";

function statusLabel(status: number) {
  return status === 1 ? "답변완료" : "답변대기";
}

export default function AdminQasPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const page = Math.max(1, Number(searchParams.get("page") || "1"));
  const statusParam = searchParams.get("status");
  const status = statusParam === "0" || statusParam === "1" ? Number(statusParam) : "all";
  const [searchQuery, setSearchQuery] = useState(searchParams.get("stx") || "");

  const [items, setItems] = useState<QaItem[]>([]);
  const [meta, setMeta] = useState<ApiMeta | undefined>();
  const [loading, setLoading] = useState(true);

  const loadQas = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getQas({
        scope: "admin",
        page,
        perPage: 20,
        status: status as 0 | 1 | "all",
        stx: searchParams.get("stx") || undefined,
        sfl: "qa_subject",
      });
      setItems(result.items);
      setMeta(result.meta);
    } catch (error) {
      setItems([]);
      setMeta(undefined);
      toastError(error instanceof Error ? error.message : "1:1 문의 목록을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, [page, searchParams, status]);

  useEffect(() => {
    loadQas();
  }, [loadQas]);

  function updateParams(next: { page?: number; status?: "all" | 0 | 1; stx?: string }) {
    const params = new URLSearchParams(searchParams.toString());
    if (next.page !== undefined) {
      if (next.page > 1) params.set("page", String(next.page));
      else params.delete("page");
    }
    if (next.status !== undefined) {
      if (next.status === "all") params.delete("status");
      else params.set("status", String(next.status));
      params.delete("page");
    }
    if (next.stx !== undefined) {
      if (next.stx.trim()) params.set("stx", next.stx.trim());
      else params.delete("stx");
      params.delete("page");
    }
    runtimeRouterPush(router, `/admin/qas${params.toString() ? `?${params.toString()}` : ""}`);
  }

  function handleSearch(event: React.FormEvent) {
    event.preventDefault();
    updateParams({ stx: searchQuery });
  }

  const lastPage = meta?.last_page ?? 1;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">1:1 문의 관리</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          회원 문의를 확인하고 답변을 등록합니다.
        </p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <form onSubmit={handleSearch} className="flex flex-wrap items-end gap-3">
            <div className="min-w-[220px] flex-1">
              <Input
                placeholder="제목으로 검색"
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
              />
            </div>
            <Button type="submit">
              <SearchIcon className="mr-1 size-4" />
              검색
            </Button>
          </form>
        </CardContent>
      </Card>

      <div className="flex gap-2 border-b">
        {[
          { value: "all" as const, label: "전체" },
          { value: 0 as const, label: "답변대기" },
          { value: 1 as const, label: "답변완료" },
        ].map((item) => (
          <button
            key={String(item.value)}
            type="button"
            onClick={() => updateParams({ status: item.value })}
            className={cn(
              "border-b-2 px-4 py-2 text-sm font-medium transition-colors",
              status === item.value
                ? "border-primary text-primary"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">
            문의 목록 {meta ? `(${meta.total.toLocaleString()}건)` : ""}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="py-8 text-center text-muted-foreground">로딩 중...</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>상태</TableHead>
                  <TableHead>제목</TableHead>
                  <TableHead>작성자</TableHead>
                  <TableHead>분류</TableHead>
                  <TableHead>작성일</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground">
                      문의가 없습니다.
                    </TableCell>
                  </TableRow>
                ) : (
                  items.map((item) => (
                    <TableRow
                      key={item.qa_id}
                      className="cursor-pointer"
                      onClick={() => runtimeRouterPush(router, `/admin/qas/${item.qa_id}`)}
                    >
                      <TableCell>
                        <span
                          className={cn(
                            "rounded-full px-2 py-0.5 text-xs font-medium",
                            item.qa_status === 1
                              ? "bg-primary/10 text-primary"
                              : "bg-muted text-muted-foreground"
                          )}
                        >
                          {statusLabel(item.qa_status)}
                        </span>
                      </TableCell>
                      <TableCell className="max-w-[360px]">
                        <p className="truncate font-medium">{item.qa_subject}</p>
                        <p className="truncate text-xs text-muted-foreground">
                          {truncate(item.qa_content.replace(/\s+/g, " "), 80)}
                        </p>
                      </TableCell>
                      <TableCell>
                        <div className="text-sm">{item.qa_name}</div>
                        <div className="text-xs text-muted-foreground">{item.mb_id}</div>
                      </TableCell>
                      <TableCell>{item.qa_category || "-"}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {formatDate(item.qa_datetime)}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {lastPage > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => updateParams({ page: page - 1 })}
          >
            이전
          </Button>
          <span className="px-2 text-sm text-muted-foreground">
            {page} / {lastPage}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= lastPage}
            onClick={() => updateParams({ page: page + 1 })}
          >
            다음
          </Button>
        </div>
      )}
    </div>
  );
}
