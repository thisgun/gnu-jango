"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { api } from "@/lib/api";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import { shouldBypassImageOptimization } from "@/lib/image";
import { toastSuccess, toastError } from "@/lib/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import type { ShopProduct, ShopCategory } from "@/lib/api";

interface ProductForm {
  it_id: string;
  it_name: string;
  ca_id: string;
  it_basic_price: number;
  it_cust_price: number;
  it_point: number;
  it_stock_qty: number;
  it_content: string;
  it_explan: string;
  it_type1: string;
  it_type2: string;
  it_type3: string;
  it_type4: string;
  it_type5: string;
  it_soldout: string;
}

const defaultForm: ProductForm = {
  it_id: "",
  it_name: "",
  ca_id: "",
  it_basic_price: 0,
  it_cust_price: 0,
  it_point: 0,
  it_stock_qty: 0,
  it_content: "",
  it_explan: "",
  it_type1: "0",
  it_type2: "0",
  it_type3: "0",
  it_type4: "0",
  it_type5: "0",
  it_soldout: "0",
};

export default function AdminProductEditPage() {
  const router = useRouter();
  const itId = useRuntimeRouteParam("it_id", "/admin/shop/products/:it_id");
  const isNew = itId === "new";

  const [form, setForm] = useState<ProductForm>(defaultForm);
  const [categories, setCategories] = useState<ShopCategory[]>([]);
  const [options, setOptions] = useState<
    { io_id: string; io_value: string; io_price: number }[]
  >([]);
  const [images, setImages] = useState<string[]>([]);
  const [loading, setLoading] = useState(!isNew);
  const [saving, setSaving] = useState(false);

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

  useEffect(() => {
    if (isNew) return;

    async function fetchProduct() {
      try {
        const res = await api.get<ShopProduct>(
          `/admin/shop/products/${itId}`
        );
        if (res.data) {
          const p = res.data;
          setForm({
            it_id: p.it_id || "",
            it_name: p.it_name || "",
            ca_id: p.ca_id || "",
            it_basic_price: p.it_basic_price,
            it_cust_price: p.it_cust_price,
            it_point: p.it_point,
            it_stock_qty: p.it_stock_qty,
            it_content: p.it_content || "",
            it_explan: p.it_explan || "",
            it_type1: p.it_type1 || "0",
            it_type2: p.it_type2 || "0",
            it_type3: p.it_type3 || "0",
            it_type4: p.it_type4 || "0",
            it_type5: p.it_type5 || "0",
            it_soldout: p.it_soldout || "0",
          });
          if (p.options) {
            setOptions(
              p.options.map((o) => ({
                io_id: o.io_id,
                io_value: o.io_value,
                io_price: o.io_price,
              }))
            );
          }
          if (p.images) setImages(p.images);
        }
      } catch {
        toastError("상품 정보를 불러올 수 없습니다.");
        runtimeRouterPush(router, "/admin/shop/products");
      } finally {
        setLoading(false);
      }
    }

    fetchProduct();
  }, [itId, isNew, router]);

  function handleChange(field: keyof ProductForm, value: string | number) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function handleOptionChange(
    index: number,
    field: string,
    value: string | number
  ) {
    setOptions((prev) =>
      prev.map((opt, i) => (i === index ? { ...opt, [field]: value } : opt))
    );
  }

  function addOption() {
    setOptions((prev) => [...prev, { io_id: "", io_value: "", io_price: 0 }]);
  }

  function removeOption(index: number) {
    setOptions((prev) => prev.filter((_, i) => i !== index));
  }

  async function handleImageUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    const formData = new FormData();
    Array.from(files).forEach((file) => formData.append("images[]", file));

    try {
      const res = await api.upload<string[]>(
        `/admin/shop/products/${itId}/images`,
        formData
      );
      if (res.data) setImages((prev) => [...prev, ...res.data!]);
    } catch {
      toastError("이미지 업로드에 실패했습니다.");
    }
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const payload = { ...form, options };
      if (isNew) {
        await api.post("/admin/shop/products", payload);
        toastSuccess("상품이 등록되었습니다.");
        runtimeRouterPush(router, "/admin/shop/products");
      } else {
        await api.patch(`/admin/shop/products/${itId}`, payload);
        toastSuccess("저장되었습니다.");
      }
    } catch {
      toastError("저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-muted-foreground">로딩 중...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <h1 className="text-2xl font-bold">
        {isNew ? "상품 등록" : `상품 수정 - ${itId}`}
      </h1>

      <form onSubmit={handleSave} className="space-y-6">
        {/* Basic Info */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">기본 정보</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {isNew && (
              <div className="space-y-2">
                <Label htmlFor="it_id">상품코드</Label>
                <Input
                  id="it_id"
                  value={form.it_id}
                  onChange={(e) => handleChange("it_id", e.target.value)}
                  placeholder="미입력 시 자동 생성"
                />
              </div>
            )}

            <div className="space-y-2">
              <Label htmlFor="it_name">상품명</Label>
              <Input
                id="it_name"
                value={form.it_name}
                onChange={(e) => handleChange("it_name", e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="ca_id">분류</Label>
              <Select
                value={form.ca_id}
                onValueChange={(val) => handleChange("ca_id", val)}
              >
                <SelectTrigger aria-label="Product category">
                  <SelectValue placeholder="분류 선택" />
                </SelectTrigger>
                <SelectContent>
                  {categories.map((cat) => (
                    <SelectItem key={cat.ca_id} value={cat.ca_id}>
                      {cat.ca_name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label htmlFor="it_basic_price">판매가</Label>
                <Input
                  id="it_basic_price"
                  type="number"
                  value={form.it_basic_price}
                  onChange={(e) =>
                    handleChange("it_basic_price", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="it_cust_price">시중가</Label>
                <Input
                  id="it_cust_price"
                  type="number"
                  value={form.it_cust_price}
                  onChange={(e) =>
                    handleChange("it_cust_price", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="it_point">포인트</Label>
                <Input
                  id="it_point"
                  type="number"
                  value={form.it_point}
                  onChange={(e) =>
                    handleChange("it_point", Number(e.target.value))
                  }
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="it_stock_qty">재고수량</Label>
                <Input
                  id="it_stock_qty"
                  type="number"
                  value={form.it_stock_qty}
                  onChange={(e) =>
                    handleChange("it_stock_qty", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="it_soldout">품절 여부</Label>
                <Select
                  value={form.it_soldout}
                  onValueChange={(val) => handleChange("it_soldout", val)}
                >
                  <SelectTrigger aria-label="Soldout status">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="0">판매중</SelectItem>
                    <SelectItem value="1">품절</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Flags */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">상품 플래그</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-5 gap-4">
              {(["it_type1", "it_type2", "it_type3", "it_type4", "it_type5"] as const).map(
                (field, idx) => (
                  <div key={field} className="space-y-2">
                    <Label htmlFor={field}>타입{idx + 1}</Label>
                    <Select
                      value={form[field]}
                      onValueChange={(val) => handleChange(field, val)}
                    >
                      <SelectTrigger aria-label={`Product flag ${idx + 1}`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="0">미사용</SelectItem>
                        <SelectItem value="1">사용</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                )
              )}
            </div>
          </CardContent>
        </Card>

        {/* Description */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">상품 설명</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="it_content">상품 상세</Label>
              <Textarea
                id="it_content"
                rows={8}
                value={form.it_content}
                onChange={(e) => handleChange("it_content", e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="it_explan">상품 요약</Label>
              <Textarea
                id="it_explan"
                rows={4}
                value={form.it_explan}
                onChange={(e) => handleChange("it_explan", e.target.value)}
              />
            </div>
          </CardContent>
        </Card>

        {/* Options */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-lg">옵션</CardTitle>
            <Button type="button" variant="outline" size="sm" onClick={addOption}>
              옵션 추가
            </Button>
          </CardHeader>
          <CardContent className="space-y-3">
            {options.length === 0 ? (
              <p className="text-sm text-muted-foreground">등록된 옵션이 없습니다.</p>
            ) : (
              options.map((opt, idx) => (
                <div key={idx} className="flex items-end gap-3">
                  <div className="flex-1 space-y-1">
                    <Label>옵션명</Label>
                    <Input
                      aria-label={`Option ${idx + 1} name`}
                      value={opt.io_value}
                      onChange={(e) =>
                        handleOptionChange(idx, "io_value", e.target.value)
                      }
                    />
                  </div>
                  <div className="w-32 space-y-1">
                    <Label>추가금액</Label>
                    <Input
                      type="number"
                      aria-label={`Option ${idx + 1} extra price`}
                      value={opt.io_price}
                      onChange={(e) =>
                        handleOptionChange(idx, "io_price", Number(e.target.value))
                      }
                    />
                  </div>
                  <Button
                    type="button"
                    variant="destructive"
                    size="sm"
                    onClick={() => removeOption(idx)}
                  >
                    삭제
                  </Button>
                </div>
              ))
            )}
          </CardContent>
        </Card>

        {/* Images */}
        {!isNew && (
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">이미지</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap gap-3">
                {images.map((url, idx) => (
                  <Image
                    key={idx}
                    src={url}
                    alt={`상품 이미지 ${idx + 1}`}
                    width={96}
                    height={96}
                    className="size-24 rounded object-cover border"
                    unoptimized={shouldBypassImageOptimization(url)}
                  />
                ))}
              </div>
              <Input
                type="file"
                accept="image/*"
                multiple
                aria-label="Upload product images"
                onChange={handleImageUpload}
              />
            </CardContent>
          </Card>
        )}

        <Separator />

        <div className="flex items-center justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => runtimeRouterPush(router, "/admin/shop/products")}
          >
            목록
          </Button>
          <Button type="submit" disabled={saving}>
            {saving ? "저장 중..." : "저장"}
          </Button>
        </div>
      </form>
    </div>
  );
}
