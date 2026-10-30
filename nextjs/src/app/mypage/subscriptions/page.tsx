"use client";

import { useCallback, useEffect, useState } from "react";
import { CalendarClock, CreditCard, History, Pause, Play, Repeat, SkipForward, XCircle } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { openSubscriptionBillingWindow, SUBSCRIPTION_BILLING_CANCELLED_MESSAGE } from "@/lib/subscription-billing";
import { toastError, toastSuccess } from "@/lib/toast";
import { cn, formatPrice } from "@/lib/utils";
import {
  changeSubscription,
  discardSubscriptionBilling,
  getMySubscription,
  getMySubscriptions,
  startSubscriptionCardChange,
  type ShopSubscription,
  type ShopSubscriptionAction,
  type ShopSubscriptionCharge,
} from "@/services/subscriptions";
import { MypagePanel } from "../MypagePanel";

const STATUS_STYLES: Record<string, string> = {
  active: "bg-green-600 hover:bg-green-600",
  paused: "bg-amber-500 hover:bg-amber-500",
  cancelled: "bg-muted-foreground/60 hover:bg-muted-foreground/60",
};
const CHARGE_STYLES: Record<string, string> = {
  done: "text-green-700",
  failed: "text-red-700",
  review: "text-red-700",
  pending: "text-primary",
  skipped: "text-muted-foreground",
};
const ACTION_DONE: Record<ShopSubscriptionAction, string> = {
  pause: "정기구독을 일시정지했습니다.",
  resume: "정기구독을 다시 시작했습니다.",
  skip: "이번 회차를 건너뛰었습니다.",
  cycle: "배송 주기를 바꿨습니다.",
  cancel: "정기구독을 해지했습니다.",
};

function ChargeHistory({ charges }: { charges: ShopSubscriptionCharge[] }) {
  if (charges.length === 0) return <p className="text-sm text-muted-foreground">결제 내역이 없습니다.</p>;
  return (
    <ul className="divide-y rounded-md border text-sm">
      {charges.map((charge) => (
        <li key={charge.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2">
          <span className="min-w-0">
            <span className="font-medium">{charge.cycle_no}회차</span>
            <span className="ml-2 text-muted-foreground">{charge.scheduled_date}</span>
            {charge.failure_message && (
              <span className="block break-words text-xs text-muted-foreground">{charge.failure_message}</span>
            )}
          </span>
          <span className="flex items-center gap-3">
            {charge.amount > 0 && <span>{formatPrice(charge.amount)}</span>}
            <span className={cn("font-medium", CHARGE_STYLES[charge.status])}>{charge.status_label}</span>
            {charge.order_id && (
              <Link href={`/shop/orders/${encodeURIComponent(charge.order_id)}`} className="text-primary underline">
                주문
              </Link>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}

function SubscriptionCard({
  subscription,
  busy,
  onAction,
  onChangeCard,
}: {
  subscription: ShopSubscription;
  busy: boolean;
  onAction: (subscription: ShopSubscription, action: ShopSubscriptionAction, cycle?: string) => void;
  onChangeCard: (subscription: ShopSubscription) => void;
}) {
  const [charges, setCharges] = useState<ShopSubscriptionCharge[] | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const cancelled = subscription.status === "cancelled";
  const locked = busy || subscription.charge_in_progress;

  const toggleHistory = async () => {
    const next = !historyOpen;
    setHistoryOpen(next);
    if (next) {
      try {
        setCharges((await getMySubscription(subscription.id)).charges);
      } catch {
        setCharges([]);
      }
    }
  };

  return (
    <article className="mypage-subscription space-y-4 rounded-xl border bg-background p-4" aria-labelledby={`subscription-${subscription.id}`}>
      <div className="flex gap-4">
        {subscription.image_url ? (
          <img src={subscription.image_url} alt="" width={72} height={72} className="h-[72px] w-[72px] shrink-0 rounded-md border object-cover" />
        ) : null}
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge className={cn("text-[11px]", STATUS_STYLES[subscription.status])}>
              {subscription.status_label}
              {subscription.pause_reason_label ? ` · ${subscription.pause_reason_label}` : ""}
            </Badge>
            <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
              <Repeat className="h-3 w-3" aria-hidden /> {subscription.cycle_label}
            </span>
          </div>
          <h3 id={`subscription-${subscription.id}`} className="break-words font-semibold">
            <Link href={`/shop/products/${encodeURIComponent(subscription.it_id)}`} className="hover:text-primary">
              {subscription.it_name}
            </Link>
          </h3>
          <p className="text-sm text-muted-foreground">
            {subscription.option_label ? `${subscription.option_label} · ` : ""}
            {subscription.qty}개
            {subscription.discount_rate > 0 ? ` · 정기구독 ${subscription.discount_rate}% 할인` : ""}
          </p>
        </div>
      </div>

      <dl className="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
        <div className="flex gap-2">
          <dt className="flex items-center gap-1 text-muted-foreground">
            <CalendarClock className="h-4 w-4" aria-hidden /> 다음 결제
          </dt>
          <dd className="m-0 font-medium">
            {cancelled || subscription.status === "paused" ? "-" : subscription.next_charge_date ?? "-"}
            {subscription.retry_date && !cancelled ? " (재시도)" : ""}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="text-muted-foreground">예상 금액</dt>
          <dd className="m-0">
            {subscription.estimated_amount != null ? formatPrice(subscription.estimated_amount) : "-"}
          </dd>
        </div>
        <div className="flex gap-2">
          <dt className="flex items-center gap-1 text-muted-foreground">
            <CreditCard className="h-4 w-4" aria-hidden /> 카드
          </dt>
          <dd className="m-0">{subscription.card ? `${subscription.card.company} ${subscription.card.number}` : "-"}</dd>
        </div>
        <div className="flex gap-2 sm:col-span-2">
          <dt className="shrink-0 text-muted-foreground">배송지</dt>
          <dd className="m-0 min-w-0 break-words">
            {subscription.delivery.name} · {[subscription.delivery.addr1, subscription.delivery.addr2].filter(Boolean).join(" ")}
          </dd>
        </div>
      </dl>
      {!cancelled && (
        <p className="text-xs text-muted-foreground">
          예상 금액은 오늘 가격 기준(배송비 포함)입니다. 실제 결제 금액은 결제하는 날의 상품 가격으로 정해집니다.
        </p>
      )}
      {subscription.last_error && !cancelled && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900">{subscription.last_error}</p>
      )}
      {subscription.charge_in_progress && (
        <p className="text-sm text-primary">결제를 처리하고 있습니다. 잠시 후 다시 확인해 주세요.</p>
      )}

      {!cancelled && (
        <div className="flex flex-wrap items-center gap-2">
          {subscription.status === "active" ? (
            <Button size="sm" variant="outline" disabled={locked} onClick={() => onAction(subscription, "pause")}>
              <Pause className="mr-1 h-4 w-4" aria-hidden /> 일시정지
            </Button>
          ) : (
            <Button size="sm" variant="outline" disabled={locked} onClick={() => onAction(subscription, "resume")}>
              <Play className="mr-1 h-4 w-4" aria-hidden /> 다시 시작
            </Button>
          )}
          {subscription.status === "active" && (
            <Button size="sm" variant="outline" disabled={locked} onClick={() => onAction(subscription, "skip")}>
              <SkipForward className="mr-1 h-4 w-4" aria-hidden /> 이번 회차 건너뛰기
            </Button>
          )}
          {subscription.cycle_choices.length > 1 && (
            <label className="inline-flex items-center gap-2 text-sm">
              <span className="sr-only">배송 주기 변경</span>
              <select
                value={subscription.cycle}
                disabled={locked}
                onChange={(event) => onAction(subscription, "cycle", event.target.value)}
                className="h-8 rounded-md border bg-background px-2 text-sm outline-none focus:ring-2 focus:ring-ring"
              >
                {subscription.cycle_choices.map((choice) => (
                  <option key={choice.value} value={choice.value}>
                    {choice.label}
                  </option>
                ))}
              </select>
            </label>
          )}
          <Button size="sm" variant="outline" disabled={locked} onClick={() => onChangeCard(subscription)}>
            <CreditCard className="mr-1 h-4 w-4" aria-hidden /> 카드 변경
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-red-700 hover:text-red-800"
            disabled={locked}
            onClick={() => onAction(subscription, "cancel")}
          >
            <XCircle className="mr-1 h-4 w-4" aria-hidden /> 해지
          </Button>
        </div>
      )}

      <div>
        <Button size="sm" variant="ghost" onClick={toggleHistory} aria-expanded={historyOpen}>
          <History className="mr-1 h-4 w-4" aria-hidden /> 결제 내역 {historyOpen ? "닫기" : "보기"}
        </Button>
        {historyOpen && (
          <div className="mt-2">
            {charges === null ? <p className="text-sm text-muted-foreground">불러오는 중…</p> : <ChargeHistory charges={charges} />}
          </div>
        )}
      </div>
    </article>
  );
}

/** 마이페이지 > 정기구독 — 다음 결제일 · 주기 · 카드 · 결제 내역, 일시정지 · 건너뛰기 · 주기 변경 · 카드 변경 · 해지. */
export default function MySubscriptionsPage() {
  const [subscriptions, setSubscriptions] = useState<ShopSubscription[] | null>(null);
  const [busyId, setBusyId] = useState(0);
  const [loadError, setLoadError] = useState("");

  const load = useCallback(async () => {
    try {
      setSubscriptions(await getMySubscriptions());
      setLoadError("");
    } catch (err: unknown) {
      setSubscriptions([]);
      setLoadError(err instanceof Error ? err.message : "정기구독을 불러오지 못했습니다.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleAction = async (subscription: ShopSubscription, action: ShopSubscriptionAction, cycle = "") => {
    if (action === "cancel" && !window.confirm("정기구독을 해지할까요? 등록한 카드 정보도 삭제됩니다.")) return;
    if (action === "skip" && !window.confirm(`${subscription.next_charge_date ?? "다음"} 회차를 건너뛸까요?`)) return;
    setBusyId(subscription.id);
    try {
      const updated = await changeSubscription(subscription.id, action, cycle);
      setSubscriptions((rows) => (rows ?? []).map((row) => (row.id === updated.id ? updated : row)));
      toastSuccess(ACTION_DONE[action]);
    } catch (err: unknown) {
      toastError(err instanceof Error ? err.message : "변경하지 못했습니다.");
    } finally {
      setBusyId(0);
    }
  };

  const handleChangeCard = async (subscription: ShopSubscription) => {
    setBusyId(subscription.id);
    let registrationToken = "";
    try {
      const registration = await startSubscriptionCardChange(subscription.id);
      registrationToken = registration.registration_token;
      await openSubscriptionBillingWindow(registration, window.location.origin);
    } catch (err: unknown) {
      if (registrationToken) await discardSubscriptionBilling(registrationToken).catch(() => undefined);
      const message = err instanceof Error ? err.message : "카드 변경을 시작하지 못했습니다.";
      if (message !== SUBSCRIPTION_BILLING_CANCELLED_MESSAGE) toastError(message);
      setBusyId(0);
    }
  };

  return (
    <MypagePanel
      title="정기구독"
      description="정기구독은 고른 주기마다 등록한 카드로 자동 결제하고 일반 주문으로 배송합니다."
    >
      {subscriptions === null ? (
        <p className="text-sm text-muted-foreground">불러오는 중…</p>
      ) : loadError ? (
        <p className="text-sm text-muted-foreground">{loadError}</p>
      ) : subscriptions.length === 0 ? (
        <div className="flex flex-col items-center py-12 text-center">
          <Repeat className="mb-4 h-16 w-16 text-muted-foreground/40" aria-hidden />
          <p className="text-muted-foreground">정기구독 중인 상품이 없습니다.</p>
          <p className="mt-1 text-sm text-muted-foreground">상품 상세에서 정기구독을 신청할 수 있습니다.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {subscriptions.map((subscription) => (
            <SubscriptionCard
              key={subscription.id}
              subscription={subscription}
              busy={busyId === subscription.id}
              onAction={handleAction}
              onChangeCard={handleChangeCard}
            />
          ))}
        </div>
      )}
    </MypagePanel>
  );
}
