"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { G5Link as Link } from "@/components/ui/g5-link";
import { AlertCircle, ArrowLeft, CheckCircle2, Clock3, CreditCard, Loader2, XCircle } from "lucide-react";
import { api } from "@/lib/api";
import { useRuntimeRouteParam } from "@/hooks/use-runtime-route-param";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import { formatDate, formatPrice } from "@/lib/utils";
import type { PaymentConfig } from "@/app/shop/order/orderPaymentHelpers";
import { parsePersonalPayReturn, type PersonalPayReturn } from "@/lib/personal-pay-checkout";
import { PersonalPayCheckoutForm } from "./PersonalPayCheckoutForm";
import { personalPayPaymentConfig, type PersonalPay } from "./personalPayTypes";

type ConfirmState =
  | { status: "idle" }
  | { status: "processing" }
  | { status: "success" }
  | { status: "error"; message: string };

const BREADCRUMB = [
  { label: "쇼핑몰", href: "/shop" },
  { label: "개인결제", href: "/shop/personalpay" },
];

function detailHref(ppId: string) {
  return `/shop/personalpay/${encodeURIComponent(ppId)}`;
}

function clearReturnQuery() {
  // 새로고침해도 승인 요청을 다시 보내지 않도록 결제창이 붙인 쿼리를 지운다
  try {
    window.history.replaceState(window.history.state, "", window.location.pathname);
  } catch {
    // ignore
  }
}

function PersonalPayPaymentContent() {
  const ppId = useRuntimeRouteParam("pp_id", "/shop/personalpay/:pp_id/pay");
  const searchParams = useSearchParams();
  const [pp, setPp] = useState<PersonalPay | null>(null);
  const [config, setConfig] = useState<PaymentConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [returned] = useState<PersonalPayReturn>(() => parsePersonalPayReturn(searchParams));
  const [confirm, setConfirm] = useState<ConfirmState>({ status: "idle" });
  const [bankSaved, setBankSaved] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  // React Strict Mode runs effects twice: the confirm POST must go out once per return
  const confirmedRef = useRef(false);

  const load = useCallback(async (id: string) => {
    const [ppRes, configRes] = await Promise.allSettled([
      api.get<PersonalPay>(`/shop/personalpay/${encodeURIComponent(id)}`),
      api.get<PaymentConfig>("/shop/payment/config"),
    ]);
    if (ppRes.status === "rejected") throw ppRes.reason;
    return {
      pp: (ppRes.value.data as PersonalPay) ?? null,
      config: configRes.status === "fulfilled" ? ((configRes.value.data as PaymentConfig) ?? null) : null,
    };
  }, []);

  // Toss returned to this page: approve once, then reload the request
  useEffect(() => {
    if (!ppId || returned.kind !== "success" || confirmedRef.current) return;
    confirmedRef.current = true;
    setConfirm({ status: "processing" });
    api
      .post<PersonalPay>(`/shop/personalpay/${encodeURIComponent(ppId)}/toss/confirm`, {
        paymentKey: returned.paymentKey,
        orderId: returned.orderId,
        amount: returned.amount,
      })
      .then(() => setConfirm({ status: "success" }))
      .catch((err: unknown) =>
        setConfirm({
          status: "error",
          message: err instanceof Error ? err.message : "결제 승인에 실패했습니다.",
        })
      )
      .finally(() => {
        clearReturnQuery();
        setReloadKey((key) => key + 1);
      });
  }, [ppId, returned]);

  useEffect(() => {
    if (!ppId) return;
    let alive = true;
    setLoading(true);
    setError("");

    load(ppId)
      .then((loaded) => {
        if (alive) {
          setPp(loaded.pp);
          setConfig(loaded.config);
        }
      })
      .catch((err: unknown) => {
        if (alive) {
          setPp(null);
          setError(err instanceof Error ? err.message : "개인결제 정보를 불러오지 못했습니다.");
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [ppId, reloadKey, load]);

  if (loading || confirm.status === "processing") {
    return (
      <div className="mx-auto flex max-w-2xl flex-col items-center py-16 text-center" role="status">
        <Loader2 className="mb-4 h-10 w-10 animate-spin text-primary" />
        <p className="font-medium">
          {confirm.status === "processing" ? "결제 승인 처리 중..." : "개인결제 정보를 불러오는 중..."}
        </p>
      </div>
    );
  }

  if (error || !pp) {
    return (
      <div>
        <Breadcrumb items={[...BREADCRUMB, { label: "결제" }]} />
        <div className="flex flex-col items-center py-16 text-center text-muted-foreground">
          <AlertCircle className="mb-4 h-14 w-14 text-muted-foreground/40" />
          <p className="font-medium">{error || "개인결제 정보를 찾을 수 없습니다."}</p>
          <Button className="mt-6" variant="outline" asChild>
            <Link href="/shop/personalpay">개인결제 목록</Link>
          </Button>
        </div>
      </div>
    );
  }

  const paymentConfig = personalPayPaymentConfig(config, pp);
  const isPaid = pp.already_paid || confirm.status === "success";
  const canCheckout = pp.can_pay === true || pp.can_change_deposit === true;
  const failMessage =
    confirm.status === "error"
      ? confirm.message
      : returned.kind === "fail" || returned.kind === "invalid"
        ? returned.message
        : "";

  return (
    <div>
      <Breadcrumb items={[...BREADCRUMB, { label: pp.pp_id }, { label: "결제" }]} />

      <div className="mx-auto max-w-2xl space-y-5 py-6">
        <Button variant="ghost" size="sm" asChild>
          <Link href={detailHref(pp.pp_id)}>
            <ArrowLeft className="h-4 w-4" />
            상세로 돌아가기
          </Link>
        </Button>

        {isPaid ? (
          <section className="rounded-lg border border-green-200 bg-green-50 p-6 text-green-900" role="status">
            <CheckCircle2 className="mb-3 h-10 w-10 text-green-600" />
            <h1 className="text-xl font-bold">결제가 완료되었습니다.</h1>
            <p className="mt-1 text-sm">
              {formatPrice(pp.pp_price)}
              {pp.pp_receipt_time ? ` · ${formatDate(pp.pp_receipt_time)}` : ""}
            </p>
            <Button className="mt-4" asChild>
              <Link href={detailHref(pp.pp_id)}>결제 내역 보기</Link>
            </Button>
          </section>
        ) : null}

        {failMessage && !isPaid ? (
          <div
            className="flex gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
            role="alert"
          >
            <XCircle className="mt-0.5 h-5 w-5 shrink-0" />
            <div>
              <p className="font-semibold">결제가 완료되지 않았습니다.</p>
              <p className="mt-1">{failMessage}</p>
              {returned.kind === "fail" && returned.code ? (
                <p className="mt-1 text-xs opacity-80">코드: {returned.code}</p>
              ) : null}
            </div>
          </div>
        ) : null}

        <section className="rounded-lg border bg-background p-6">
          <div className="flex flex-wrap items-start gap-4">
            <div className="flex size-12 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <CreditCard className="h-6 w-6" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-primary">개인결제</p>
              <h2 className="mt-1 text-2xl font-bold">{pp.pp_name}님 개인결제</h2>
              <p className="mt-1 text-sm text-muted-foreground">결제번호 {pp.pp_id}</p>
              {pp.pp_time ? (
                <p className="mt-1 text-xs text-muted-foreground">발급일 {formatDate(pp.pp_time)}</p>
              ) : null}
            </div>
            <div className="text-right">
              <p className="text-sm text-muted-foreground">결제 금액</p>
              <p className="mt-1 text-2xl font-extrabold text-primary">
                {formatPrice(isPaid ? pp.pp_price : (pp.pp_misu_price ?? pp.pp_price))}
              </p>
              <p className="mt-1 text-sm font-semibold">{pp.payment_state_label || "결제 대기"}</p>
            </div>
          </div>

          {pp.pp_content ? (
            <div className="mt-5 whitespace-pre-wrap rounded-md bg-muted/30 p-4 text-sm">{pp.pp_content}</div>
          ) : null}

          {pp.awaiting_deposit ? (
            <div className="mt-5 rounded-md border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900" role="status">
              <p className="flex items-center gap-1.5 font-semibold">
                <Clock3 className="h-4 w-4" />
                {bankSaved ? "입금 계좌가 등록되었습니다." : "입금 확인을 기다리고 있습니다."}
              </p>
              <p className="mt-1 font-mono">{pp.pp_bank_account}</p>
              <p className="mt-1 text-xs text-amber-700">입금자명: {pp.pp_deposit_name}</p>
              <p className="mt-2 text-xs text-amber-700">
                입금이 확인되면 결제 완료로 바뀝니다. 입금 정보를 바꾸려면 아래에서 다시 신청하세요.
              </p>
            </div>
          ) : null}
        </section>

        {!isPaid ? (
          canCheckout ? (
            <PersonalPayCheckoutForm
              key={`${pp.payment_state}-${pp.pp_bank_account}-${pp.pp_deposit_name}`}
              pp={pp}
              paymentConfig={paymentConfig}
              onBankSaved={(saved) => {
                setPp(saved);
                setBankSaved(true);
              }}
            />
          ) : (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
              {pp.payment_block_reason || "결제할 수 없는 개인결제입니다."}
            </div>
          )
        ) : null}
      </div>
    </div>
  );
}

export default function PersonalPayPaymentPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      }
    >
      <PersonalPayPaymentContent />
    </Suspense>
  );
}
