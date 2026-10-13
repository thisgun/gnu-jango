"use client";

import { useState } from "react";
import { useRouter } from "@bprogress/next/app";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { useAuthStore } from "@/store/auth";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { leaveMembership } from "@/services/member";

/** 회원탈퇴 (bbs/member_confirm.php → member_leave.php): 비밀번호를 확인하고 탈퇴한다. */
export function LeaveSection() {
  const router = useRouter();
  const { user, expireSession } = useAuthStore();
  const [password, setPassword] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [leaving, setLeaving] = useState(false);

  if (user?.is_super_admin) {
    return null;
  }

  const handleLeave = async (event: React.FormEvent) => {
    event.preventDefault();
    setError("");
    if (!password) {
      setError("비밀번호를 입력해주세요.");
      return;
    }
    if (!confirmed) {
      setError("탈퇴 안내를 확인하고 동의해주세요.");
      return;
    }
    if (!window.confirm("회원에서 탈퇴하시겠습니까? 탈퇴하면 같은 아이디로 다시 로그인할 수 없습니다.")) {
      return;
    }
    setLeaving(true);
    try {
      const message = await leaveMembership(password);
      // 서버가 토큰을 모두 폐기하고 쿠키를 지웠으므로 화면의 로그인 상태만 정리한다.
      expireSession();
      window.alert(message);
      runtimeRouterPush(router, "/");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "회원탈퇴를 처리하지 못했습니다.");
      setLeaving(false);
    }
  };

  return (
    <Card className="border-destructive/40">
      <CardHeader>
        <CardTitle className="text-destructive">회원탈퇴</CardTitle>
        <CardDescription>
          탈퇴한 아이디로는 다시 로그인할 수 없으며, 같은 아이디와 이메일로 다시 가입할 수 없습니다.
        </CardDescription>
      </CardHeader>
      <form onSubmit={handleLeave}>
        <CardContent className="space-y-4">
          {error ? (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          <div className="space-y-2">
            <Label htmlFor="leave_password">비밀번호 확인</Label>
            <Input
              id="leave_password"
              name="mb_password"
              type="password"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
                setError("");
              }}
              autoComplete="current-password"
              disabled={leaving}
            />
          </div>
          <label htmlFor="leave_confirm" className="flex cursor-pointer items-start gap-2 text-sm">
            <input
              id="leave_confirm"
              type="checkbox"
              checked={confirmed}
              onChange={(event) => {
                setConfirmed(event.target.checked);
                setError("");
              }}
              disabled={leaving}
              className="mt-0.5 size-4 rounded border-border accent-destructive"
            />
            <span>위 안내를 확인했으며 회원탈퇴에 동의합니다.</span>
          </label>
          <div className="flex justify-end">
            <Button type="submit" variant="destructive" disabled={leaving}>
              {leaving ? "처리 중..." : "회원탈퇴"}
            </Button>
          </div>
        </CardContent>
      </form>
    </Card>
  );
}

export default LeaveSection;
