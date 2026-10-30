"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { XCircle } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { Button } from "@/components/ui/button";
import { parseSubscriptionBillingReturn } from "@/lib/subscription-billing";
import { stripQueryFromAddressBar } from "@/lib/sensitive-url";
import { discardSubscriptionBilling } from "@/services/subscriptions";

/** 토스 자동결제 등록창의 실패 주소 — 기다리던 카드 등록을 지우고 토스가 준 사유를 보인다. */
function SubscriptionBillingFailContent() {
  const searchParams = useSearchParams();
  const started = useRef(false);
  const [failure, setFailure] = useState({ code: "", message: "" });

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const parsed = parseSubscriptionBillingReturn(searchParams, "fail");
    stripQueryFromAddressBar();
    if (parsed.kind !== "fail") return;
    setFailure({ code: parsed.code, message: parsed.message });
    if (parsed.registrationToken) {
      discardSubscriptionBilling(parsed.registrationToken).catch(() => undefined);
    }
  }, [searchParams]);

  return (
    <div className="text-center">
      <XCircle className="mx-auto mb-4 h-16 w-16 text-red-600" aria-hidden />
      <h1 className="text-xl font-bold">카드 등록이 완료되지 않았습니다</h1>
      <p className="mt-2 text-sm text-muted-foreground">{failure.message || "카드 등록이 완료되지 않았습니다."}</p>
      {failure.code && <p className="mt-1 text-xs text-muted-foreground">코드: {failure.code}</p>}
      <p className="mt-3 text-xs text-muted-foreground">결제된 금액은 없습니다. 상품 페이지에서 다시 신청할 수 있습니다.</p>
      <Button asChild className="mt-6">
        <Link href="/mypage/subscriptions">정기구독 관리</Link>
      </Button>
    </div>
  );
}

export default function SubscriptionBillingFailPage() {
  return (
    <div className="container mx-auto flex min-h-[60vh] max-w-md items-center justify-center px-4 py-16">
      <Suspense fallback={<div className="p-16 text-center">로딩...</div>}>
        <SubscriptionBillingFailContent />
      </Suspense>
    </div>
  );
}
