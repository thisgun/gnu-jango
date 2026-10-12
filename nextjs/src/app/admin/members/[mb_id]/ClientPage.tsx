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
import { Badge } from "@/components/ui/badge";
import type { Member } from "@/lib/types";

export default function AdminMemberEditPage() {
  const router = useRouter();
  const mbId = useRuntimeRouteParam("mb_id", "/admin/members/:mb_id");

  const [member, setMember] = useState<Member | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState({
    mb_nick: "",
    mb_name: "",
    mb_email: "",
    mb_level: 1,
    mb_point: 0,
    mb_hp: "",
    mb_tel: "",
  });

  useEffect(() => {
    async function fetchMember() {
      try {
        const res = await api.get<Member>(`/admin/members/${mbId}`);
        if (res.data) {
          setMember(res.data);
          setForm({
            mb_nick: res.data.mb_nick || "",
            mb_name: res.data.mb_name || "",
            mb_email: res.data.mb_email || "",
            mb_level: res.data.mb_level,
            mb_point: res.data.mb_point,
            mb_hp: res.data.mb_hp || "",
            mb_tel: res.data.mb_tel || "",
          });
        }
      } catch {
        toastError("회원 정보를 불러올 수 없습니다.");
        runtimeRouterPush(router, "/admin/members");
      } finally {
        setLoading(false);
      }
    }

    fetchMember();
  }, [mbId, router]);

  function handleChange(field: string, value: string | number) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await api.patch(`/admin/members/${mbId}`, form);
      toastSuccess("저장되었습니다.");
    } catch {
      toastError("저장에 실패했습니다.");
    } finally {
      setSaving(false);
    }
  }

  async function handleBan() {
    if (!confirm("이 회원을 차단하시겠습니까?")) return;
    try {
      await api.patch(`/admin/members/${mbId}/ban`, {});
      toastSuccess("차단되었습니다.");
      runtimeRouterPush(router, "/admin/members");
    } catch {
      toastError("차단에 실패했습니다.");
    }
  }

  async function handleLeave() {
    if (!confirm("이 회원을 탈퇴 처리하시겠습니까?")) return;
    try {
      await api.patch(`/admin/members/${mbId}/leave`, {});
      toastSuccess("탈퇴 처리되었습니다.");
      runtimeRouterPush(router, "/admin/members");
    } catch {
      toastError("탈퇴 처리에 실패했습니다.");
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-muted-foreground">로딩 중...</p>
      </div>
    );
  }

  if (!member) return null;

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">회원 수정 - {mbId}</h1>
        <div className="flex gap-2">
          {member.mb_intercept_date && (
            <Badge variant="destructive">차단</Badge>
          )}
          {member.mb_leave_date && (
            <Badge variant="secondary">탈퇴</Badge>
          )}
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">회원 정보</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSave} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="mb_nick">닉네임</Label>
                <Input
                  id="mb_nick"
                  value={form.mb_nick}
                  onChange={(e) => handleChange("mb_nick", e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="mb_name">이름</Label>
                <Input
                  id="mb_name"
                  value={form.mb_name}
                  onChange={(e) => handleChange("mb_name", e.target.value)}
                />
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="mb_email">이메일</Label>
              <Input
                id="mb_email"
                type="email"
                value={form.mb_email}
                onChange={(e) => handleChange("mb_email", e.target.value)}
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="mb_level">레벨</Label>
                <Input
                  id="mb_level"
                  type="number"
                  min={1}
                  max={10}
                  value={form.mb_level}
                  onChange={(e) =>
                    handleChange("mb_level", Number(e.target.value))
                  }
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="mb_point">포인트</Label>
                <Input
                  id="mb_point"
                  type="number"
                  value={form.mb_point}
                  onChange={(e) =>
                    handleChange("mb_point", Number(e.target.value))
                  }
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label htmlFor="mb_hp">휴대폰</Label>
                <Input
                  id="mb_hp"
                  value={form.mb_hp}
                  onChange={(e) => handleChange("mb_hp", e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="mb_tel">전화번호</Label>
                <Input
                  id="mb_tel"
                  value={form.mb_tel}
                  onChange={(e) => handleChange("mb_tel", e.target.value)}
                />
              </div>
            </div>

            <div className="flex items-center justify-between pt-4">
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="destructive"
                  onClick={handleBan}
                >
                  차단
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleLeave}
                >
                  탈퇴처리
                </Button>
              </div>
              <div className="flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => runtimeRouterPush(router, "/admin/members")}
                >
                  목록
                </Button>
                <Button type="submit" disabled={saving}>
                  {saving ? "저장 중..." : "저장"}
                </Button>
              </div>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
