"use client";

import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { Button } from "@/components/ui/button";
import { parseSubscriptionBillingReturn } from "@/lib/subscription-billing";
import { stripQueryFromAddressBar } from "@/lib/sensitive-url";
import { formatPrice } from "@/lib/utils";
import { completeSubscriptionBilling, type ShopSubscriptionBillingResult } from "@/services/subscriptions";

type BillingState =
  | { kind: "working" }
  | { kind: "done"; result: ShopSubscriptionBillingResult }
  | { kind: "error"; message: string };

function resultText(result: ShopSubscriptionBillingResult) {
  if (!result.charge_status) return { title: "결제 카드를 변경했습니다", body: "다음 결제부터 새 카드로 결제합니다." };
  if (result.charge_status === "pending") {
    return {
      title: "정기구독을 신청했습니다",
      body: "첫 결제 결과를 토스페이먼츠에서 확인하고 있습니다. 확인되면 주문 내역과 알림으로 알려 드립니다.",
    };
  }
  const first = result.subscription.charges.find((charge) => charge.order_id === result.order_id);
  return {
    title: "정기구독을 시작했습니다",
    body: first ? `첫 결제 ${formatPrice(first.amount)}이 완료되었습니다. 주문번호 ${result.order_id}` : "첫 결제가 완료되었습니다.",
  };
}

/**
 * 토스 자동결제 등록창의 성공 주소 — token(우리 등록) · customerKey · authKey 를 한 번만 서버에 넘긴다.
 * 서버가 빌링키를 발급받아 보관하고 첫 회차를 결제한다. 쿼리는 읽자마자 주소창에서 지운다.
 */
function SubscriptionBillingSuccessContent() {
  const searchParams = useSearchParams();
  const started = useRef(false);
  const [state, setState] = useState<BillingState>({ kind: "working" });

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const parsed = parseSubscriptionBillingReturn(searchParams, "success");
    stripQueryFromAddressBar();
    if (parsed.kind !== "success") {
      setState({ kind: "error", message: "카드 등록 결과를 확인할 수 없습니다. 다시 신청해 주세요." });
      return;
    }
    completeSubscriptionBilling(parsed)
      .then((result) => setState({ kind: "done", result }))
      .catch((err: unknown) =>
        setState({ kind: "error", message: err instanceof Error ? err.message : "카드를 등록하지 못했습니다." })
      );
  }, [searchParams]);

  if (state.kind === "working") {
    return (
      <div className="text-center" role="status">
        <Loader2 className="mx-auto mb-4 h-12 w-12 animate-spin text-primary" aria-hidden />
        <h1 className="text-xl font-bold">카드를 등록하고 있습니다</h1>
        <p className="mt-2 text-sm text-muted-foreground">창을 닫지 말고 잠시만 기다려 주세요.</p>
      </div>
    );
  }
  if (state.kind === "error") {
    return (
      <div className="text-center">
        <XCircle className="mx-auto mb-4 h-16 w-16 text-red-600" aria-hidden />
        <h1 className="text-xl font-bold">정기구독을 시작하지 못했습니다</h1>
        <p className="mt-2 text-sm text-muted-foreground">{state.message}</p>
        <Button asChild className="mt-6">
          <Link href="/mypage/subscriptions">정기구독 관리</Link>
        </Button>
      </div>
    );
  }
  const text = resultText(state.result);
  return (
    <div className="text-center">
      <CheckCircle2 className="mx-auto mb-4 h-16 w-16 text-primary" aria-hidden />
      <h1 className="text-xl font-bold">{text.title}</h1>
      <p className="mt-2 text-sm text-muted-foreground">{text.body}</p>
      <dl className="mx-auto mt-6 grid max-w-sm grid-cols-[5.5rem_minmax(0,1fr)] gap-y-1.5 rounded-lg border bg-card p-4 text-left text-sm">
        <dt className="text-muted-foreground">상품</dt>
        <dd className="m-0 break-words">{state.result.subscription.it_name} {state.result.subscription.qty}개</dd>
        <dt className="text-muted-foreground">주기</dt>
        <dd className="m-0">{state.result.subscription.cycle_label}</dd>
        <dt className="text-muted-foreground">다음 결제일</dt>
        <dd className="m-0">{state.result.subscription.next_charge_date ?? "-"}</dd>
        {state.result.subscription.card && (
          <>
            <dt className="text-muted-foreground">결제 카드</dt>
            <dd className="m-0">
              {state.result.subscription.card.company} {state.result.subscription.card.number}
            </dd>
          </>
        )}
      </dl>
      <div className="mt-6 flex justify-center gap-3">
        <Button asChild>
          <Link href="/mypage/subscriptions">정기구독 관리</Link>
        </Button>
        {state.result.order_id && state.result.charge_status === "charged" && (
          <Button asChild variant="outline">
            <Link href={`/shop/orders/${encodeURIComponent(state.result.order_id)}`}>주문 상세</Link>
          </Button>
        )}
      </div>
    </div>
  );
}

export default function SubscriptionBillingSuccessPage() {
  return (
    <div className="container mx-auto flex min-h-[60vh] max-w-md items-center justify-center px-4 py-16">
      <Suspense fallback={<div className="p-16 text-center">로딩...</div>}>
        <SubscriptionBillingSuccessContent />
      </Suspense>
    </div>
  );
}
