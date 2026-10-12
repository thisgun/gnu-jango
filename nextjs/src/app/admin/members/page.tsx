"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { SearchIcon } from "lucide-react";
import type { Member, PaginationMeta } from "@/lib/types";

export default function AdminMembersPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [members, setMembers] = useState<Member[]>([]);
  const [meta, setMeta] = useState<PaginationMeta | null>(null);
  const [loading, setLoading] = useState(true);

  const [searchField, setSearchField] = useState(
    searchParams.get("sfl") || "mb_id"
  );
  const [searchQuery, setSearchQuery] = useState(
    searchParams.get("stx") || ""
  );

  const page = Number(searchParams.get("page")) || 1;

  const fetchMembers = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("per_page", "20");
      if (searchQuery) {
        params.set("sfl", searchField);
        params.set("stx", searchQuery);
      }

      const res = await api.get<Member[]>(`/admin/members?${params.toString()}`);
      if (res.data) setMembers(res.data);
      if (res.meta) setMeta(res.meta);
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }, [page, searchField, searchQuery]);

  useEffect(() => {
    fetchMembers();
  }, [fetchMembers]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const params = new URLSearchParams();
    params.set("page", "1");
    if (searchQuery) {
      params.set("sfl", searchField);
      params.set("stx", searchQuery);
    }
    runtimeRouterPush(router, `/admin/members?${params.toString()}`);
  }

  function goToPage(p: number) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", String(p));
    runtimeRouterPush(router, `/admin/members?${params.toString()}`);
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">회원관리</h1>

      {/* Search Form */}
      <Card>
        <CardContent className="pt-6">
          <form onSubmit={handleSearch} className="flex items-end gap-3">
            <div className="w-36">
              <Select value={searchField} onValueChange={setSearchField}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="mb_id">아이디</SelectItem>
                  <SelectItem value="mb_nick">닉네임</SelectItem>
                  <SelectItem value="mb_name">이름</SelectItem>
                  <SelectItem value="mb_email">이메일</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1">
              <Input
                placeholder="검색어를 입력하세요"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
            </div>
            <Button type="submit">
              <SearchIcon className="size-4 mr-1" />
              검색
            </Button>
          </form>
        </CardContent>
      </Card>

      {/* Members Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">
            회원 목록 {meta && `(총 ${meta.total.toLocaleString()}명)`}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="py-8 text-center text-muted-foreground">로딩 중...</p>
          ) : (
            <>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>아이디</TableHead>
                    <TableHead>닉네임</TableHead>
                    <TableHead>이름</TableHead>
                    <TableHead>이메일</TableHead>
                    <TableHead>레벨</TableHead>
                    <TableHead>가입일</TableHead>
                    <TableHead>포인트</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {members.length === 0 ? (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center text-muted-foreground">
                        회원이 없습니다.
                      </TableCell>
                    </TableRow>
                  ) : (
                    members.map((m) => (
                      <TableRow
                        key={m.mb_id}
                        className="cursor-pointer"
                        onClick={() => runtimeRouterPush(router, `/admin/members/${m.mb_id}`)}
                      >
                        <TableCell className="font-medium text-primary">
                          {m.mb_id}
                        </TableCell>
                        <TableCell>{m.mb_nick}</TableCell>
                        <TableCell>{m.mb_name}</TableCell>
                        <TableCell>{m.mb_email}</TableCell>
                        <TableCell>{m.mb_level}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {m.mb_datetime}
                        </TableCell>
                        <TableCell>{m.mb_point.toLocaleString()}</TableCell>
                      </TableRow>
                    ))
                  )}
                </TableBody>
              </Table>

              {/* Pagination */}
              {meta && meta.last_page > 1 && (
                <div className="flex items-center justify-center gap-2 pt-4">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page <= 1}
                    onClick={() => goToPage(page - 1)}
                  >
                    이전
                  </Button>
                  {Array.from({ length: meta.last_page }, (_, i) => i + 1)
                    .filter(
                      (p) =>
                        p === 1 ||
                        p === meta.last_page ||
                        Math.abs(p - page) <= 2
                    )
                    .map((p, idx, arr) => (
                      <span key={p} className="flex items-center gap-1">
                        {idx > 0 && arr[idx - 1] !== p - 1 && (
                          <span className="text-muted-foreground">...</span>
                        )}
                        <Button
                          variant={p === page ? "default" : "outline"}
                          size="sm"
                          onClick={() => goToPage(p)}
                        >
                          {p}
                        </Button>
                      </span>
                    ))}
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={page >= meta.last_page}
                    onClick={() => goToPage(page + 1)}
                  >
                    다음
                  </Button>
                </div>
              )}
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
