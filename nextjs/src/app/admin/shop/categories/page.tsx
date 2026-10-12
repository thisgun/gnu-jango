"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toastSuccess, toastError } from "@/lib/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  PlusIcon,
  PencilIcon,
  TrashIcon,
  ChevronRightIcon,
  ArrowUpIcon,
  ArrowDownIcon,
} from "lucide-react";
import type { Category } from "@/lib/types";

interface CategoryForm {
  ca_id: string;
  ca_name: string;
  ca_order: number;
  ca_id_parent: string;
}

const defaultForm: CategoryForm = {
  ca_id: "",
  ca_name: "",
  ca_order: 0,
  ca_id_parent: "",
};

export default function AdminCategoriesPage() {
  const [categories, setCategories] = useState<Category[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editMode, setEditMode] = useState(false);
  const [form, setForm] = useState<CategoryForm>(defaultForm);
  const [saving, setSaving] = useState(false);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  async function fetchCategories() {
    setLoading(true);
    try {
      const res = await api.get<Category[]>("/admin/shop/categories");
      if (res.data) setCategories(res.data);
    } catch {
      // silently fail
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchCategories();
  }, []);

  function toggleExpand(caId: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(caId)) {
        next.delete(caId);
      } else {
        next.add(caId);
      }
      return next;
    });
  }

  function openCreateDialog(parentId = "") {
    setEditMode(false);
    setForm({ ...defaultForm, ca_id_parent: parentId });
    setDialogOpen(true);
  }

  function openEditDialog(cat: Category) {
    setEditMode(true);
    setForm({
      ca_id: cat.ca_id,
      ca_name: cat.ca_name,
      ca_order: cat.ca_order,
      ca_id_parent: cat.ca_id_parent || "",
    });
    setDialogOpen(true);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    if (!form.ca_name) {
      toastError("분류명을 입력하세요.");
      return;
    }
    setSaving(true);
    try {
      if (editMode) {
        await api.patch(`/admin/shop/categories/${form.ca_id}`, {
          ca_name: form.ca_name,
          ca_order: form.ca_order,
        });
        toastSuccess("수정되었습니다.");
      } else {
        await api.post("/admin/shop/categories", form);
        toastSuccess("분류가 생성되었습니다.");
      }
      setDialogOpen(false);
      setForm(defaultForm);
      fetchCategories();
    } catch {
      toastError("저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(caId: string) {
    if (!confirm(`분류 '${caId}'을(를) 삭제하시겠습니까?`)) return;
    try {
      await api.delete(`/admin/shop/categories/${caId}`);
      toastSuccess("삭제되었습니다.");
      fetchCategories();
    } catch {
      toastError("삭제에 실패했습니다.");
    }
  }

  async function handleMove(caId: string, direction: "up" | "down") {
    try {
      await api.patch(`/admin/shop/categories/${caId}/order`, { direction });
      fetchCategories();
    } catch {
      toastError("순서 변경에 실패했습니다.");
    }
  }

  function renderCategoryTree(items: Category[], depth = 0) {
    return items.map((cat) => {
      const hasChildren = cat.children && cat.children.length > 0;
      const isExpanded = expandedIds.has(cat.ca_id);

      return (
        <div key={cat.ca_id}>
          <div
            className="flex items-center gap-2 rounded-md px-3 py-2 hover:bg-accent/50 transition-colors"
            style={{ paddingLeft: `${depth * 24 + 12}px` }}
          >
            {/* Expand toggle */}
            {hasChildren ? (
              <button
                type="button"
                className="size-5 flex items-center justify-center"
                aria-label={`${isExpanded ? "Collapse" : "Expand"} category ${cat.ca_id}`}
                aria-expanded={isExpanded}
                onClick={() => toggleExpand(cat.ca_id)}
              >
                <ChevronRightIcon
                  className={`size-4 transition-transform ${
                    isExpanded ? "rotate-90" : ""
                  }`}
                />
              </button>
            ) : (
              <span className="size-5" aria-hidden="true" />
            )}

            {/* Category name */}
            <span className="flex-1 text-sm font-medium">
              {cat.ca_name}
              <span className="ml-2 text-xs text-muted-foreground">
                ({cat.ca_id})
              </span>
              {cat.item_count !== undefined && (
                <span className="ml-2 text-xs text-muted-foreground">
                  상품 {cat.item_count}개
                </span>
              )}
            </span>

            {/* Actions */}
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                className="size-7 p-0"
                onClick={() => handleMove(cat.ca_id, "up")}
                title="위로"
              >
                <ArrowUpIcon className="size-3" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="size-7 p-0"
                onClick={() => handleMove(cat.ca_id, "down")}
                title="아래로"
              >
                <ArrowDownIcon className="size-3" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="size-7 p-0"
                onClick={() => openCreateDialog(cat.ca_id)}
                title="하위 분류 추가"
              >
                <PlusIcon className="size-3" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="size-7 p-0"
                onClick={() => openEditDialog(cat)}
                title="수정"
              >
                <PencilIcon className="size-3" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="size-7 p-0"
                onClick={() => handleDelete(cat.ca_id)}
                title="삭제"
              >
                <TrashIcon className="size-3 text-destructive" />
              </Button>
            </div>
          </div>

          {/* Children */}
          {hasChildren && isExpanded && (
            <div>{renderCategoryTree(cat.children!, depth + 1)}</div>
          )}
        </div>
      );
    });
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">분류관리</h1>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
          <DialogTrigger asChild>
            <Button onClick={() => openCreateDialog()}>
              <PlusIcon className="size-4 mr-1" />
              분류 추가
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>
                {editMode ? "분류 수정" : "분류 추가"}
              </DialogTitle>
              <DialogDescription>
                {editMode
                  ? "분류 정보를 수정합니다."
                  : "새 분류를 추가합니다."}
              </DialogDescription>
            </DialogHeader>
            <form onSubmit={handleSave} className="space-y-4">
              {!editMode && (
                <div className="space-y-2">
                  <Label htmlFor="ca_id">분류 코드</Label>
                  <Input
                    id="ca_id"
                    placeholder="예: 10, 1010"
                    value={form.ca_id}
                    onChange={(e) =>
                      setForm((prev) => ({ ...prev, ca_id: e.target.value }))
                    }
                  />
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="ca_name">분류명</Label>
                <Input
                  id="ca_name"
                  placeholder="분류 이름"
                  value={form.ca_name}
                  onChange={(e) =>
                    setForm((prev) => ({ ...prev, ca_name: e.target.value }))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="ca_order">정렬순서</Label>
                <Input
                  id="ca_order"
                  type="number"
                  value={form.ca_order}
                  onChange={(e) =>
                    setForm((prev) => ({
                      ...prev,
                      ca_order: Number(e.target.value),
                    }))
                  }
                />
              </div>
              {form.ca_id_parent && (
                <p className="text-sm text-muted-foreground">
                  상위 분류: {form.ca_id_parent}
                </p>
              )}
              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setDialogOpen(false)}
                >
                  취소
                </Button>
                <Button type="submit" disabled={saving}>
                  {saving ? "저장 중..." : editMode ? "수정" : "추가"}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">카테고리 트리</CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <p className="py-8 text-center text-muted-foreground">로딩 중...</p>
          ) : categories.length === 0 ? (
            <p className="py-8 text-center text-muted-foreground">
              등록된 분류가 없습니다.
            </p>
          ) : (
            <div className="divide-y">
              {renderCategoryTree(categories)}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
