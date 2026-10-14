"use client";

import { useEffect, useRef, useState } from "react";
import { Home, Loader2, LogIn, MailCheck, MailWarning } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { certifyEmail } from "@/services/auth";
import { stripQueryFromAddressBar } from "@/lib/sensitive-url";

type CertifyState = "pending" | "done" | "failed";

/**
 * 메일인증 링크 도착 페이지 (bbs/email_certify.php).
 * 메일의 링크는 /email-certify?mb_id=...&token=... 으로 열린다. 메일 검사기가 링크를 미리 열어도
 * 인증되지 않도록 화면이 뜬 뒤에 POST 로 한 번만 보낸다.
 */
export default function EmailCertifyPage() {
  const [state, setState] = useState<CertifyState>("pending");
  const [message, setMessage] = useState("");
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current) return;
    sent.current = true;

    const params = new URLSearchParams(window.location.search);
    const mbId = params.get("mb_id") ?? "";
    const token = params.get("token") ?? params.get("mb_md5") ?? "";
    // 토큰이 주소창 · 방문 기록 · 분석 도구에 남지 않도록 읽자마자 쿼리를 지운다.
    stripQueryFromAddressBar();
    if (!mbId || !token) {
      setState("failed");
      setMessage("제대로 된 값이 넘어오지 않았습니다.");
      return;
    }

    certifyEmail(mbId, token)
      .then((text) => {
        setState("done");
        setMessage(text);
      })
      .catch((err: unknown) => {
        setState("failed");
        setMessage(err instanceof Error ? err.message : "메일인증 요청 정보가 올바르지 않습니다.");
      });
  }, []);

  const Icon = state === "pending" ? Loader2 : state === "done" ? MailCheck : MailWarning;

  return (
    <div className="flex min-h-[calc(100vh-8rem)] items-center justify-center px-4 py-12">
      <Card className="w-full max-w-md">
        <CardHeader className="text-center">
          <div
            className={
              state === "failed"
                ? "mx-auto mb-3 flex size-14 items-center justify-center rounded-full bg-destructive/10 text-destructive"
                : "mx-auto mb-3 flex size-14 items-center justify-center rounded-full bg-primary/10 text-primary"
            }
          >
            <Icon className={state === "pending" ? "size-7 animate-spin" : "size-7"} aria-hidden="true" />
          </div>
          <CardTitle className="text-2xl">메일인증</CardTitle>
          <CardDescription>
            {state === "pending" ? "메일인증을 처리하고 있습니다..." : "회원 메일인증 결과입니다."}
          </CardDescription>
        </CardHeader>
        {state !== "pending" && message ? (
          <CardContent>
            <Alert variant={state === "failed" ? "destructive" : "default"} role="status">
              <AlertDescription className="whitespace-pre-line">{message}</AlertDescription>
            </Alert>
            {state === "failed" ? (
              <p className="mt-3 text-sm text-muted-foreground">
                로그인 화면에서 아이디와 비밀번호를 입력하면 인증메일을 다시 받을 수 있습니다.
              </p>
            ) : null}
          </CardContent>
        ) : null}
        <CardFooter className="flex flex-wrap justify-center gap-2">
          <Button asChild>
            <Link href="/login">
              <LogIn className="size-4" aria-hidden="true" />
              로그인
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href="/">
              <Home className="size-4" aria-hidden="true" />
              홈으로
            </Link>
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
