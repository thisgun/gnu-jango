"use client";

import { useState, useEffect, useRef } from "react";
import Image from "next/image";
import { useRouter } from "@bprogress/next/app";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { useAuthStore } from "@/store/auth";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Camera, Loader2 } from "lucide-react";
import { toastSuccess, toastError } from "@/lib/toast";
import { shouldBypassImageOptimization } from "@/lib/image";
import { updateMyProfile, uploadMyIcon } from "@/services/member";
import { LeaveSection } from "./LeaveSection";

export default function ProfilePage() {
  const router = useRouter();
  const { user, fetchUser, expireSession } = useAuthStore();
  const [form, setForm] = useState({
    mb_nick: "",
    mb_name: "",
    mb_email: "",
  });
  // 정보공개 (mb_open) — 다른 회원이 내 자기소개를 볼 수 있는지.
  const [openProfile, setOpenProfile] = useState(true);
  // 정보 메일 수신 (mb_mailling) — 장바구니 알림 같은 광고성 메일.
  const [mailing, setMailing] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [msg, setMsg] = useState({ type: "", text: "" });
  const [loading, setLoading] = useState(false);
  const [avatarUrl, setAvatarUrl] = useState<string | null>(null);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (user) {
      setForm({
        mb_nick: user.mb_nick || "",
        mb_name: user.mb_name || "",
        mb_email: user.mb_email || "",
      });
      setOpenProfile(user.mb_open === undefined ? true : user.mb_open === 1);
      setMailing(user.mb_mailling === 1);
      setCurrentPassword("");
      setAvatarUrl(user.mb_icon_path || null);
    }
  }, [user]);

  const handleAvatarUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      toastError("이미지 파일만 업로드 가능합니다.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      toastError("파일 크기는 5MB 이하여야 합니다.");
      return;
    }
    setUploadingAvatar(true);
    try {
      await uploadMyIcon(file);
      await fetchUser();
      // Force refresh avatar with cache buster
      setAvatarUrl((user?.mb_icon_path || "") + "?t=" + Date.now());
      toastSuccess("프로필 이미지가 변경되었습니다.");
    } catch {
      toastError("프로필 이미지 업로드에 실패했습니다.");
    } finally {
      setUploadingAvatar(false);
      e.target.value = "";
    }
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
    setMsg({ type: "", text: "" });
  };

  // 서버와 같이 앞뒤 공백만 떼고 비교한다 — 대소문자만 바꿔도 메일주소 변경이라 비밀번호를 묻는다.
  const emailChanged = Boolean(user && form.mb_email.trim() !== (user.mb_email || "").trim());

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.mb_nick || !form.mb_name || !form.mb_email) {
      setMsg({ type: "error", text: "모든 필드를 입력해주세요." });
      return;
    }
    if (emailChanged && !currentPassword) {
      setMsg({ type: "error", text: "이메일을 변경하려면 현재 비밀번호를 입력해주세요." });
      return;
    }
    setLoading(true);
    try {
      const response = await updateMyProfile({
        ...form,
        mb_open: openProfile ? 1 : 0,
        mb_mailling: mailing ? 1 : 0,
        ...(emailChanged ? { mb_password_current: currentPassword } : {}),
      });
      if (response.data?.email_certify_required) {
        // register_form_update.php: 바뀐 메일주소는 다시 인증해야 하므로 서버가 로그아웃시켰다.
        expireSession();
        window.alert(
          response.data.message ||
            "회원 정보가 수정 되었습니다.\n\nE-mail 주소가 변경되었으므로 다시 인증하셔야 합니다."
        );
        runtimeRouterPush(router, "/login");
        return;
      }
      await fetchUser();
      setCurrentPassword("");
      setMsg({ type: "success", text: "프로필이 수정되었습니다." });
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "프로필 수정에 실패했습니다.";
      setMsg({ type: "error", text: message });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>프로필 수정</CardTitle>
        </CardHeader>
        <form onSubmit={handleSubmit}>
          <CardContent className="space-y-4">
            {msg.text && (
              <Alert variant={msg.type === "error" ? "destructive" : "default"}>
                <AlertDescription>{msg.text}</AlertDescription>
              </Alert>
            )}

            {/* Avatar */}
            <div className="flex items-center gap-4">
              <div className="relative">
                <div className="h-20 w-20 rounded-full bg-muted overflow-hidden border-2 border-border">
                  {avatarUrl ? (
                    <Image
                      src={avatarUrl}
                      alt="프로필"
                      width={80}
                      height={80}
                      className="h-full w-full object-cover"
                      unoptimized={shouldBypassImageOptimization(avatarUrl)}
                    />
                  ) : (
                    <div className="h-full w-full flex items-center justify-center text-2xl font-bold text-muted-foreground">
                      {(user?.mb_nick || "?")[0].toUpperCase()}
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  aria-label="프로필 사진 변경"
                  onClick={() => fileInputRef.current?.click()}
                  disabled={uploadingAvatar}
                  className="absolute -bottom-1 -right-1 flex h-7 w-7 items-center justify-center rounded-full bg-primary text-primary-foreground shadow hover:bg-[#08783a] transition-colors"
                >
                  {uploadingAvatar ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Camera className="h-3.5 w-3.5" />
                  )}
                </button>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={handleAvatarUpload}
                />
              </div>
              <div className="text-sm text-muted-foreground">
                <p className="font-medium text-foreground">{user?.mb_id}</p>
                <p>프로필 이미지를 변경하려면 카메라 아이콘을 클릭하세요.</p>
              </div>
            </div>

            <div className="space-y-2">
              <Label htmlFor="mb_nick">닉네임</Label>
              <Input
                id="mb_nick"
                name="mb_nick"
                value={form.mb_nick}
                onChange={handleChange}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="mb_name">이름</Label>
              <Input
                id="mb_name"
                name="mb_name"
                value={form.mb_name}
                onChange={handleChange}
                required
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="mb_email">이메일</Label>
              <Input
                id="mb_email"
                name="mb_email"
                type="email"
                value={form.mb_email}
                onChange={handleChange}
                required
              />
            </div>
            <label
              htmlFor="mb_open"
              className="flex cursor-pointer items-start gap-2 rounded-[4px] border border-border bg-base-200 p-3 text-sm"
            >
              <input
                id="mb_open"
                name="mb_open"
                type="checkbox"
                checked={openProfile}
                onChange={(event) => {
                  setOpenProfile(event.target.checked);
                  setMsg({ type: "", text: "" });
                }}
                className="mt-0.5 size-4 rounded border-border accent-primary"
              />
              <span className="min-w-0">
                <span className="block font-bold text-base-content">정보공개</span>
                <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                  다른 회원이 나의 정보를 볼 수 있도록 합니다. 정보를 공개하지 않으면 다른 회원의 정보도 볼 수
                  없습니다. 정보공개를 바꾸면 일정 기간 동안 다시 바꿀 수 없을 수 있습니다.
                </span>
              </span>
            </label>
            <label
              htmlFor="mb_mailling"
              className="flex cursor-pointer items-start gap-2 rounded-[4px] border border-border bg-base-200 p-3 text-sm"
            >
              <input
                id="mb_mailling"
                name="mb_mailling"
                type="checkbox"
                checked={mailing}
                onChange={(event) => {
                  setMailing(event.target.checked);
                  setMsg({ type: "", text: "" });
                }}
                className="mt-0.5 size-4 rounded border-border accent-primary"
              />
              <span className="min-w-0">
                <span className="block font-bold text-base-content">정보 메일 수신</span>
                <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
                  할인 쿠폰, 장바구니 알림 같은 광고성 정보를 메일로 받습니다. 주문·배송 안내 메일은 이 설정과 관계없이 보냅니다.
                </span>
              </span>
            </label>
            {emailChanged && (
              <div className="space-y-2">
                <Label htmlFor="mb_password_current">현재 비밀번호</Label>
                <Input
                  id="mb_password_current"
                  name="mb_password_current"
                  type="password"
                  value={currentPassword}
                  onChange={(event) => {
                    setCurrentPassword(event.target.value);
                    setMsg({ type: "", text: "" });
                  }}
                  autoComplete="current-password"
                  required
                  aria-describedby="mb_password_current_help"
                />
                <p id="mb_password_current_help" className="text-xs text-muted-foreground">
                  이메일을 변경하려면 현재 비밀번호를 입력해주세요.
                </p>
              </div>
            )}
            <div className="flex justify-end">
              <Button type="submit" disabled={loading}>
                {loading ? "저장 중..." : "프로필 저장"}
              </Button>
            </div>
          </CardContent>
        </form>
      </Card>
      <LeaveSection />
    </div>
  );
}
