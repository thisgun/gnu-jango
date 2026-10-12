"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toastSuccess, toastError } from "@/lib/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";

interface SiteConfig {
  cf_title: string;
  cf_admin: string;
  cf_admin_email: string;
  cf_use_point: number;
  cf_login_point: number;
  cf_write_point: number;
  cf_comment_point: number;
  cf_use_copy_log: number;
  cf_use_email_certify: number;
  cf_register_level: number;
  cf_page_rows: number;
  cf_mobile_page_rows: number;
}

const defaultConfig: SiteConfig = {
  cf_title: "",
  cf_admin: "",
  cf_admin_email: "",
  cf_use_point: 1,
  cf_login_point: 100,
  cf_write_point: 5,
  cf_comment_point: 1,
  cf_use_copy_log: 0,
  cf_use_email_certify: 0,
  cf_register_level: 2,
  cf_page_rows: 15,
  cf_mobile_page_rows: 15,
};

export default function AdminSettingsPage() {
  const [form, setForm] = useState<SiteConfig>(defaultConfig);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    async function fetchConfig() {
      try {
        const res = await api.get<SiteConfig>("/admin/settings");
        if (res.data) setForm(res.data);
      } catch {
        // silently fail
      } finally {
        setLoading(false);
      }
    }

    fetchConfig();
  }, []);

  function handleChange(field: keyof SiteConfig, value: string | number) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch("/admin/settings", form);
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
      <h1 className="text-2xl font-bold">환경설정</h1>

      <form onSubmit={handleSave} className="space-y-6">
        {/* Site Info */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">사이트 기본 설정</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="cf_title">사이트 제목</Label>
              <Input
                id="cf_title"
                value={form.cf_title}
                onChange={(e) => handleChange("cf_title", e.target.value)}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="cf_admin">최고관리자 아이디</Label>
                <Input
                  id="cf_admin"
                  value={form.cf_admin}
                  onChange={(e) => handleChange("cf_admin", e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cf_admin_email">관리자 이메일</Label>
                <Input
                  id="cf_admin_email"
                  type="email"
                  value={form.cf_admin_email}
                  onChange={(e) =>
                    handleChange("cf_admin_email", e.target.value)
                  }
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="cf_register_level">가입 레벨</Label>
                <Input
                  id="cf_register_level"
                  type="number"
                  min={1}
                  max={10}
                  value={form.cf_register_level}
                  onChange={(e) =>
                    handleChange("cf_register_level", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cf_use_email_certify">이메일 인증 사용</Label>
                <Select
                  value={String(form.cf_use_email_certify)}
                  onValueChange={(val) =>
                    handleChange("cf_use_email_certify", Number(val))
                  }
                >
                  <SelectTrigger id="cf_use_email_certify">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="0">미사용</SelectItem>
                    <SelectItem value="1">사용</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Point Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">포인트 설정</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="cf_use_point">포인트 사용</Label>
              <Select
                value={String(form.cf_use_point)}
                onValueChange={(val) =>
                  handleChange("cf_use_point", Number(val))
                }
              >
                <SelectTrigger id="cf_use_point">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="0">미사용</SelectItem>
                  <SelectItem value="1">사용</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label htmlFor="cf_login_point">로그인 포인트</Label>
                <Input
                  id="cf_login_point"
                  type="number"
                  value={form.cf_login_point}
                  onChange={(e) =>
                    handleChange("cf_login_point", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cf_write_point">글쓰기 포인트</Label>
                <Input
                  id="cf_write_point"
                  type="number"
                  value={form.cf_write_point}
                  onChange={(e) =>
                    handleChange("cf_write_point", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cf_comment_point">댓글 포인트</Label>
                <Input
                  id="cf_comment_point"
                  type="number"
                  value={form.cf_comment_point}
                  onChange={(e) =>
                    handleChange("cf_comment_point", Number(e.target.value))
                  }
                />
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Display Settings */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">표시 설정</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="cf_page_rows">PC 페이지당 행 수</Label>
                <Input
                  id="cf_page_rows"
                  type="number"
                  min={1}
                  value={form.cf_page_rows}
                  onChange={(e) =>
                    handleChange("cf_page_rows", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="cf_mobile_page_rows">
                  모바일 페이지당 행 수
                </Label>
                <Input
                  id="cf_mobile_page_rows"
                  type="number"
                  min={1}
                  value={form.cf_mobile_page_rows}
                  onChange={(e) =>
                    handleChange(
                      "cf_mobile_page_rows",
                      Number(e.target.value)
                    )
                  }
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="cf_use_copy_log">복사 로그 사용</Label>
              <Select
                value={String(form.cf_use_copy_log)}
                onValueChange={(val) =>
                  handleChange("cf_use_copy_log", Number(val))
                }
              >
                <SelectTrigger id="cf_use_copy_log">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="0">미사용</SelectItem>
                  <SelectItem value="1">사용</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </CardContent>
        </Card>

        <Separator />

        <div className="flex justify-end">
          <Button type="submit" disabled={saving}>
            {saving ? "저장 중..." : "저장"}
          </Button>
        </div>
      </form>
    </div>
  );
}
