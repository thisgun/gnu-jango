"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Image from "next/image";
import { api } from "@/lib/api";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { shouldBypassImageOptimization } from "@/lib/image";
import { toastSuccess, toastError } from "@/lib/toast";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { PlusIcon, PencilIcon, TrashIcon, SearchIcon } from "lucide-react";
import type { PaginationMeta } from "@/lib/types";
import type { ShopProduct, ShopCategory } from "@/lib/api";

export default function AdminProductsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [products, setProducts] = useState<ShopProduct[]>([]);
  const [categories, setCategories] = useState<ShopCategory[]>([]);
  const [meta, setMeta] = useState<PaginationMeta | null>(null);
  const [loading, setLoading] = useState(true);
  const [failedImages, setFailedImages] = useState<Set<string>>(() => new Set());

  const [searchQuery, setSearchQuery] = useState(
    searchParams.get("stx") || ""
  );
  const [categoryFilter, setCategoryFilter] = useState(
    searchParams.get("ca_id") || ""
  );

  const page = Number(searchParams.get("page")) || 1;

  const fetchProducts = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      params.set("page", String(page));
      params.set("per_page", "20");
      if (searchQuery) params.set("stx", searchQuery);
      if (categoryFilter) params.set("ca_id", categoryFilter);

      const res = await api.get<ShopProduct[]>(
        `/admin/shop/products?${params.toString()}`
      );
      if (res.data) setProducts(res.data);
      if (res.meta) setMeta(res.meta);
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }, [page, searchQuery, categoryFilter]);

  useEffect(() => {
    fetchProducts();
  }, [fetchProducts]);

  useEffect(() => {
    async function fetchCategories() {
      try {
        const res = await api.get<ShopCategory[]>("/admin/shop/categories");
        if (res.data) setCategories(res.data);
      } catch {
        // silently fail
      }
    }
    fetchCategories();
  }, []);

  function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    const params = new URLSearchParams();
    params.set("page", "1");
    if (searchQuery) params.set("stx", searchQuery);
    if (categoryFilter) params.set("ca_id", categoryFilter);
    runtimeRouterPush(router, `/admin/shop/products?${params.toString()}`);
  }

  async function handleDelete(itId: string) {
    if (!confirm(`상품 '${itId}'을(를) 삭제하시겠습니까?`)) return;
    try {
      await api.delete(`/admin/shop/products/${itId}`);
      toastSuccess("삭제되었습니다.");
      fetchProducts();
    } catch {
      toastError("삭제에 실패했습니다.");
    }
  }

  function goToPage(p: number) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("page", String(p));
    runtimeRouterPush(router, `/admin/shop/products?${params.toString()}`);
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">상품관리</h1>
        <Button onClick={() => runtimeRouterPush(router, "/admin/shop/products/new")}>
          <PlusIcon className="size-4 mr-1" />
          상품등록
        </Button>
      </div>

      {/* Search & Filter */}
      <Card>
        <CardContent className="pt-6">
          <form onSubmit={handleSearch} className="flex items-end gap-3">
            <div className="w-44">
              <Select
                value={categoryFilter}
                onValueChange={(val) =>
                  setCategoryFilter(val === "all" ? "" : val)
                }
              >
                <SelectTrigger>
                  <SelectValue placeholder="전체 분류" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">전체 분류</SelectItem>
                  {categories.map((cat) => (
                    <SelectItem key={cat.ca_id} value={cat.ca_id}>
                      {cat.ca_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1">
              <Input
                placeholder="상품명 검색"
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

      {/* Products Table */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">
            상품 목록 {meta && `(총 ${meta.total.toLocaleString()}개)`}
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
                    <TableHead className="w-16">이미지</TableHead>
                    <TableHead>상품코드</TableHead>
                    <TableHead>상품명</TableHead>
                    <TableHead>가격</TableHead>
                    <TableHead>분류</TableHead>
                    <TableHead>재고</TableHead>
                    <TableHead>품절</TableHead>
                    <TableHead>사용</TableHead>
                    <TableHead className="text-right">관리</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {products.length === 0 ? (
                    <TableRow>
                      <TableCell
                        colSpan={9}
                        className="text-center text-muted-foreground"
                      >
                        상품이 없습니다.
                      </TableCell>
                    </TableRow>
                  ) : (
                    products.map((item) => (
                      <TableRow key={item.it_id}>
                        <TableCell>
                          {item.image_url && !failedImages.has(item.image_url) ? (
                            <Image
                              src={item.image_url}
                              alt={item.it_name}
                              width={48}
                              height={48}
                              className="size-12 rounded object-cover"
                              unoptimized={shouldBypassImageOptimization(item.image_url)}
                              onError={() =>
                                setFailedImages((previous) => {
                                  const next = new Set(previous);
                                  next.add(item.image_url!);
                                  return next;
                                })
                              }
                            />
                          ) : (
                            <div className="size-12 rounded bg-muted" aria-hidden="true" />
                          )}
                        </TableCell>
                        <TableCell className="font-medium">
                          {item.it_id}
                        </TableCell>
                        <TableCell>{item.it_name}</TableCell>
                        <TableCell>
                          {item.it_basic_price.toLocaleString()}원
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {item.ca_name || item.ca_id}
                        </TableCell>
                        <TableCell>{item.it_stock_qty}</TableCell>
                        <TableCell>
                          {item.it_soldout === "1" ? (
                            <Badge variant="destructive">품절</Badge>
                          ) : (
                            <Badge variant="secondary">판매중</Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          {item.it_type1 === "1" ? (
                            <Badge>사용</Badge>
                          ) : (
                            <Badge variant="outline">미사용</Badge>
                          )}
                        </TableCell>
                        <TableCell className="text-right">
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={`Edit product ${item.it_id}`}
                              onClick={() =>
                                runtimeRouterPush(
                                  router,
                                  `/admin/shop/products/${item.it_id}`
                                )
                              }
                            >
                              <PencilIcon className="size-4" />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              aria-label={`Delete product ${item.it_id}`}
                              onClick={() => handleDelete(item.it_id)}
                            >
                              <TrashIcon className="size-4 text-destructive" />
                            </Button>
                          </div>
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
