"use client";

import { useState } from "react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { resendCertifyEmail } from "@/services/auth";

interface EmailCertifyNoticeProps {
  message: string;
  mbId: string;
  mbPassword: string;
}

/**
 * 메일인증을 마치지 않아 로그인이 막혔을 때 (bbs/login_check.php) 보여 주는 안내.
 * 같은 아이디 · 비밀번호로 인증메일을 다시 받거나, 다른 주소로 바꿔 받을 수 있다
 * (bbs/register_email.php · register_email_update.php).
 */
export function EmailCertifyNotice({ message, mbId, mbPassword }: EmailCertifyNoticeProps) {
  const [newEmail, setNewEmail] = useState("");
  const [showEmailInput, setShowEmailInput] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [sending, setSending] = useState(false);

  const handleResend = async () => {
    setSending(true);
    setResult(null);
    try {
      const text = await resendCertifyEmail({
        mb_id: mbId,
        mb_password: mbPassword,
        ...(showEmailInput && newEmail.trim() ? { mb_email: newEmail.trim() } : {}),
      });
      setResult({ ok: true, text });
    } catch (err: unknown) {
      setResult({
        ok: false,
        text: err instanceof Error ? err.message : "인증메일을 보내지 못했습니다.",
      });
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="space-y-2" role="alert">
      <Alert variant="destructive">
        <AlertDescription className="whitespace-pre-line">{message}</AlertDescription>
      </Alert>
      {showEmailInput ? (
        <Input
          type="email"
          aria-label="인증받을 새 메일주소"
          placeholder="인증받을 새 메일주소"
          value={newEmail}
          onChange={(event) => setNewEmail(event.target.value)}
          autoComplete="email"
          disabled={sending}
        />
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" variant="outline" onClick={handleResend} disabled={sending}>
          {sending ? "보내는 중..." : "인증메일 다시 받기"}
        </Button>
        <button
          type="button"
          className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          onClick={() => setShowEmailInput((value) => !value)}
          disabled={sending}
        >
          {showEmailInput ? "기존 메일주소로 받기" : "다른 메일주소로 받기"}
        </button>
      </div>
      {result ? (
        <Alert variant={result.ok ? "default" : "destructive"}>
          <AlertDescription className="whitespace-pre-line">{result.text}</AlertDescription>
        </Alert>
      ) : null}
    </div>
  );
}

export default EmailCertifyNotice;
