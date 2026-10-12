"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import { toastSuccess, toastError } from "@/lib/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import type { Board } from "@/lib/types";

export default function AdminBoardEditPage() {
  const router = useRouter();
  const boTable = useRuntimeRouteParam("bo_table", "/admin/boards/:bo_table");

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState({
    bo_subject: "",
    bo_skin: "basic",
    bo_mobile_skin: "basic",
    bo_category_list: "",
    bo_use_list_view: 0,
    bo_read_level: 1,
    bo_write_level: 1,
    bo_comment_level: 1,
    bo_upload_level: 1,
    bo_download_level: 1,
    bo_gallery_cols: 4,
    bo_gallery_width: 202,
    bo_gallery_height: 150,
    bo_image_width: 835,
    bo_table_width: 100,
    bo_subject_len: 60,
    bo_page_rows: 15,
  });

  useEffect(() => {
    async function fetchBoard() {
      try {
        const res = await api.get<Board>(`/admin/boards/${boTable}`);
        if (res.data) {
          const b = res.data;
          setForm({
            bo_subject: b.bo_subject || "",
            bo_skin: b.bo_skin || "basic",
            bo_mobile_skin: b.bo_mobile_skin || "basic",
            bo_category_list: b.bo_category_list || "",
            bo_use_list_view: b.bo_use_list_view,
            bo_read_level: b.bo_read_level,
            bo_write_level: b.bo_write_level,
            bo_comment_level: b.bo_comment_level,
            bo_upload_level: b.bo_upload_level,
            bo_download_level: b.bo_download_level,
            bo_gallery_cols: b.bo_gallery_cols,
            bo_gallery_width: b.bo_gallery_width,
            bo_gallery_height: b.bo_gallery_height,
            bo_image_width: b.bo_image_width,
            bo_table_width: 100,
            bo_subject_len: b.bo_subject_len,
            bo_page_rows: b.bo_page_rows,
          });
        }
      } catch {
        toastError("게시판 정보를 불러올 수 없습니다.");
        runtimeRouterPush(router, "/admin/boards");
      } finally {
        setLoading(false);
      }
    }

    fetchBoard();
  }, [boTable, router]);

  function handleChange(field: string, value: string | number) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch(`/admin/boards/${boTable}`, form);
      toastSuccess("저장되었습니다.");
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
      <h1 className="text-2xl font-bold">게시판 설정 - {boTable}</h1>

      <form onSubmit={handleSave} className="space-y-6" noValidate>
        {/* Basic Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">기본 설정</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="bo_subject">게시판 제목</Label>
              <Input
                id="bo_subject"
                value={form.bo_subject}
                onChange={(e) => handleChange("bo_subject", e.target.value)}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="bo_skin">PC 스킨</Label>
                <Input
                  id="bo_skin"
                  value={form.bo_skin}
                  onChange={(e) => handleChange("bo_skin", e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bo_mobile_skin">모바일 스킨</Label>
                <Input
                  id="bo_mobile_skin"
                  value={form.bo_mobile_skin}
                  onChange={(e) =>
                    handleChange("bo_mobile_skin", e.target.value)
                  }
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="bo_category_list">분류 (쉼표로 구분)</Label>
              <Input
                id="bo_category_list"
                placeholder="분류1,분류2,분류3"
                value={form.bo_category_list}
                onChange={(e) =>
                  handleChange("bo_category_list", e.target.value)
                }
              />
            </div>

            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label htmlFor="bo_page_rows">페이지당 행 수</Label>
                <Input
                  id="bo_page_rows"
                  type="number"
                  min={1}
                  value={form.bo_page_rows}
                  onChange={(e) =>
                    handleChange("bo_page_rows", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bo_subject_len">제목 글자 수</Label>
                <Input
                  id="bo_subject_len"
                  type="number"
                  min={1}
                  value={form.bo_subject_len}
                  onChange={(e) =>
                    handleChange("bo_subject_len", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bo_use_list_view">목록 보이기</Label>
                <Input
                  id="bo_use_list_view"
                  type="number"
                  min={0}
                  max={1}
                  value={form.bo_use_list_view}
                  onChange={(e) =>
                    handleChange("bo_use_list_view", Number(e.target.value))
                  }
                />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Permission Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">권한 설정</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              {[
                { id: "bo_read_level", label: "읽기 권한" },
                { id: "bo_write_level", label: "쓰기 권한" },
                { id: "bo_comment_level", label: "댓글 권한" },
                { id: "bo_upload_level", label: "업로드 권한" },
                { id: "bo_download_level", label: "다운로드 권한" },
              ].map((item) => (
                <div key={item.id} className="space-y-2">
                  <Label htmlFor={item.id}>{item.label}</Label>
                  <Input
                    id={item.id}
                    type="number"
                    min={1}
                    max={10}
                    value={form[item.id as keyof typeof form]}
                    onChange={(e) =>
                      handleChange(item.id, Number(e.target.value))
                    }
                  />
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Gallery Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">갤러리 / 이미지 설정</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <div className="space-y-2">
                <Label htmlFor="bo_gallery_cols">갤러리 열 수</Label>
                <Input
                  id="bo_gallery_cols"
                  type="number"
                  min={1}
                  value={form.bo_gallery_cols}
                  onChange={(e) =>
                    handleChange("bo_gallery_cols", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bo_gallery_width">갤러리 너비</Label>
                <Input
                  id="bo_gallery_width"
                  type="number"
                  min={1}
                  value={form.bo_gallery_width}
                  onChange={(e) =>
                    handleChange("bo_gallery_width", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bo_gallery_height">갤러리 높이</Label>
                <Input
                  id="bo_gallery_height"
                  type="number"
                  min={1}
                  value={form.bo_gallery_height}
                  onChange={(e) =>
                    handleChange("bo_gallery_height", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bo_image_width">이미지 너비</Label>
                <Input
                  id="bo_image_width"
                  type="number"
                  min={1}
                  value={form.bo_image_width}
                  onChange={(e) =>
                    handleChange("bo_image_width", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bo_table_width">테이블 너비(%)</Label>
                <Input
                  id="bo_table_width"
                  type="number"
                  min={1}
                  max={100}
                  value={form.bo_table_width}
                  onChange={(e) =>
                    handleChange("bo_table_width", Number(e.target.value))
                  }
                />
              </div>
            </div>
          </CardContent>
        </Card>

        <Separator />

        <div className="flex items-center justify-end gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={() => runtimeRouterPush(router, "/admin/boards")}
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
