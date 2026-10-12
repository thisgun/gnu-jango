"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { useRouter } from "next/navigation";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { useAuthStore } from "@/store/auth";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { SocialLoginButtons } from "@/components/auth/SocialLoginButtons";
import { EmailCertifyNotice } from "@/components/auth/EmailCertifyNotice";
import { ApiError } from "@/lib/api";

interface LoginFormProps {
  redirectAfterLogin?: string | null;
  onNavigate?: () => void;
  onSuccess?: () => void;
  variant?: "default" | "compact";
}

export function LoginForm({
  redirectAfterLogin,
  onNavigate,
  onSuccess,
  variant = "default",
}: LoginFormProps) {
  const router = useRouter();
  const idPrefix = useId();
  const { login, fetchUser } = useAuthStore();
  const [formData, setFormData] = useState({
    mb_id: "",
    mb_password: "",
    auto_login: false,
  });
  const [error, setError] = useState("");
  // 메일인증을 마치지 않아 로그인이 막힌 경우 (code: email_not_certified) — 다시 받기를 내 준다.
  const [certifyPending, setCertifyPending] = useState<{
    message: string;
    mbId: string;
    mbPassword: string;
  } | null>(null);
  const [loading, setLoading] = useState(false);

  const finishLogin = useCallback(() => {
    if (onSuccess) {
      onSuccess();
      return;
    }

    runtimeRouterPush(router, redirectAfterLogin || "/");
  }, [onSuccess, redirectAfterLogin, router]);

  useEffect(() => {
    const handler = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      const data = event.data;
      if (!data || data.type !== "social-login-result") return;

      if (data.status === "success") {
        void fetchUser().then(finishLogin);
      } else if (data.status === "error") {
        setError(typeof data.message === "string" ? data.message : "소셜 로그인에 실패했습니다.");
      }
    };
    window.addEventListener("message", handler);
    return () => window.removeEventListener("message", handler);
  }, [fetchUser, finishLogin]);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { checked, name, type, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: type === "checkbox" ? checked : value,
    }));
    setError("");
    setCertifyPending(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setCertifyPending(null);

    if (!formData.mb_id || !formData.mb_password) {
      setError("아이디와 비밀번호를 입력해주세요.");
      return;
    }

    setLoading(true);
    try {
      await login(formData.mb_id, formData.mb_password, formData.auto_login);
      finishLogin();
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : "로그인에 실패했습니다. 아이디와 비밀번호를 확인해주세요.";
      if (err instanceof ApiError && err.code === "email_not_certified") {
        setCertifyPending({ message, mbId: formData.mb_id, mbPassword: formData.mb_password });
      } else {
        setError(message);
      }
    } finally {
      setLoading(false);
    }
  };

  const usernameId = `${idPrefix}-mb-id`;
  const passwordId = `${idPrefix}-mb-password`;
  const autoLoginId = `${idPrefix}-auto-login`;

  if (variant === "compact") {
    return (
      <form onSubmit={handleSubmit} className="login-form login-form--compact">
        <div className="space-y-2">
          {certifyPending ? (
            <EmailCertifyNotice {...certifyPending} />
          ) : error ? (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
          <Input
            id={usernameId}
            name="mb_id"
            type="text"
            placeholder="아이디"
            aria-label="아이디"
            value={formData.mb_id}
            onChange={handleChange}
            autoComplete="username"
            disabled={loading}
            required
            className="input"
          />
          <Input
            id={passwordId}
            name="mb_password"
            type="password"
            placeholder="비밀번호"
            aria-label="비밀번호"
            value={formData.mb_password}
            onChange={handleChange}
            autoComplete="current-password"
            disabled={loading}
            required
            className="input"
          />
          <Button
            type="submit"
            className="login-submit btn btn-primary btn-block w-full"
            disabled={loading}
          >
            {loading ? "로그인 중..." : "로그인"}
          </Button>
          <div className="login-form-links flex flex-wrap items-center justify-between gap-x-3 gap-y-1 text-xs text-muted-foreground">
            <label htmlFor={autoLoginId} className="flex cursor-pointer items-center gap-1.5">
              <input
                id={autoLoginId}
                name="auto_login"
                type="checkbox"
                checked={formData.auto_login}
                onChange={handleChange}
                disabled={loading}
                className="checkbox checkbox-primary checkbox-sm"
              />
              자동로그인
            </label>
            <span className="flex items-center gap-2">
              <Link href="/register" className="hover:text-foreground hover:underline" onClick={onNavigate}>
                회원가입
              </Link>
              <Link href="/forgot-password" className="hover:text-foreground hover:underline" onClick={onNavigate}>
                아이디·비밀번호 찾기
              </Link>
            </span>
          </div>
        </div>
        <SocialLoginButtons redirectAfterLogin={redirectAfterLogin} layout="stacked" />
      </form>
    );
  }

  return (
    <form onSubmit={handleSubmit}>
      <div className="space-y-4">
        {certifyPending ? (
          <EmailCertifyNotice {...certifyPending} />
        ) : error ? (
          <Alert variant="destructive">
            <AlertDescription className="whitespace-pre-line">{error}</AlertDescription>
          </Alert>
        ) : null}
        <div className="space-y-2">
          <Label htmlFor={usernameId}>아이디</Label>
          <Input
            id={usernameId}
            name="mb_id"
            type="text"
            placeholder="아이디를 입력하세요"
            value={formData.mb_id}
            onChange={handleChange}
            autoComplete="username"
            disabled={loading}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={passwordId}>비밀번호</Label>
          <Input
            id={passwordId}
            name="mb_password"
            type="password"
            placeholder="비밀번호를 입력하세요"
            value={formData.mb_password}
            onChange={handleChange}
            autoComplete="current-password"
            disabled={loading}
          />
        </div>

        <label
          htmlFor={autoLoginId}
          className="flex cursor-pointer items-start gap-2 rounded-[4px] border border-border bg-base-200 p-3 text-sm"
        >
          <input
            id={autoLoginId}
            name="auto_login"
            type="checkbox"
            checked={formData.auto_login}
            onChange={handleChange}
            disabled={loading}
            className="mt-0.5 size-4 rounded border-border accent-primary"
          />
          <span className="min-w-0">
            <span className="block font-bold text-base-content">자동로그인</span>
            <span className="mt-0.5 block text-xs leading-5 text-muted-foreground">
              브라우저를 닫아도 30일 동안 로그인 상태를 유지합니다.
            </span>
          </span>
        </label>

        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? "로그인 중..." : "로그인"}
        </Button>

        <SocialLoginButtons redirectAfterLogin={redirectAfterLogin} />

        <div className="space-y-2 text-center text-sm text-muted-foreground">
          <p>
            비밀번호를 잊으셨나요?{" "}
            <Link
              href="/forgot-password"
              className="font-medium text-primary hover:underline"
              onClick={onNavigate}
            >
              비밀번호 찾기
            </Link>
          </p>
          <p>
            계정이 없으신가요?{" "}
            <Link
              href="/register"
              className="font-medium text-primary hover:underline"
              onClick={onNavigate}
            >
              회원가입
            </Link>
          </p>
        </div>
      </div>
    </form>
  );
}

export default LoginForm;
