"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SearchIcon } from "lucide-react";
import type { Order, PaginationMeta } from "@/lib/types";

const STATUS_TABS = [
  { value: "", label: "전체" },
  { value: "주문", label: "주문" },
  { value: "입금", label: "입금" },
  { value: "준비", label: "준비" },
  { value: "배송", label: "배송" },
  { value: "완료", label: "완료" },
  { value: "취소", label: "취소" },
];

function getStatusBadgeVariant(
  status: string
): "default" | "secondary" | "destructive" | "outline" {
  switch (status) {
    case "입금":
      return "default";
    case "배송":
    case "준비":
      return "secondary";
    case "완료":
      return "outline";
    case "취소":
      return "destructive";
    default:
      return "secondary";
  }
}

export default function AdminOrdersPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [orders, setOrders] = useState<Order[]>([]);
  const [meta, setMeta] = useState<PaginationMeta | null>(null);
  const [loading, setLoading] = useState(true);

  const [statusFilter, setStatusFilter] = useState(
    searchParams.get("status") || ""
  );
  const [searchQuery, setSearchQuery] = useState(
    searchParams.get("stx") || ""
  );

  const page = Number(searchParams.get("page")) || 1;

  const fetchOrders = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("per_page", "20");
      if (statusFilter) params.set("status", statusFilter);
      if (searchQuery) params.set("stx", searchQuery);

      const res = await api.get<Order[]>(
        `/admin/shop/orders?${params.toString()}`
      );
      if (res.data) setOrders(res.data);
      if (res.meta) setMeta(res.meta);
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, searchQuery]);

  useEffect(() => {
    fetchOrders();
  }, [fetchOrders]);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const params = new URLSearchParams();
    params.set("page", "1");
    if (statusFilter) params.set("status", statusFilter);
    if (searchQuery) params.set("stx", searchQuery);
    runtimeRouterPush(router, `/admin/shop/orders?${params.toString()}`);
  }

  function handleStatusChange(status: string) {
    setStatusFilter(status);
    const params = new URLSearchParams();
    params.set("page", "1");
    if (status) params.set("status", status);
    if (searchQuery) params.set("stx", searchQuery);
    runtimeRouterPush(router, `/admin/shop/orders?${params.toString()}`);
  }

  function goToPage(p: number) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", String(p));
    runtimeRouterPush(router, `/admin/shop/orders?${params.toString()}`);
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">주문관리</h1>

      {/* Status Tabs */}
      <Tabs value={statusFilter} onValueChange={handleStatusChange}>
        <TabsList>
          {STATUS_TABS.map((tab) => (
            <TabsTrigger key={tab.value} value={tab.value}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {/* Search */}
      <Card>
        <CardContent className="pt-6">
          <form onSubmit={handleSearch} className="flex items-end gap-3">
            <div className="flex-1">
              <Input
                placeholder="주문번호 또는 주문자명 검색"
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

      {/* Orders Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">
            주문 목록 {meta && `(총 ${meta.total.toLocaleString()}건)`}
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
                    <TableHead>주문번호</TableHead>
                    <TableHead>주문자</TableHead>
                    <TableHead>주문일시</TableHead>
                    <TableHead>결제금액</TableHead>
                    <TableHead>상태</TableHead>
                    <TableHead>결제방법</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {orders.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={6}
                        className="text-center text-muted-foreground"
                      >
                        주문이 없습니다.
                      </TableCell>
                    </TableRow>
                  ) : (
                    orders.map((order) => (
                      <TableRow
                        key={order.od_id}
                        className="cursor-pointer"
                        onClick={() =>
                          runtimeRouterPush(router, `/admin/shop/orders/${order.od_id}`)
                        }
                      >
                        <TableCell className="font-medium text-primary">
                          {order.od_id}
                        </TableCell>
                        <TableCell>{order.od_name}</TableCell>
                        <TableCell className="text-xs text-muted-foreground">
                          {order.od_datetime}
                        </TableCell>
                        <TableCell>
                          {order.od_receipt_price.toLocaleString()}원
                        </TableCell>
                        <TableCell>
                          <Badge variant={getStatusBadgeVariant(order.od_status)}>
                            {order.od_status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {order.od_settle_case}
                        </TableCell>
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
