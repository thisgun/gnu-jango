"use client";

import { useEffect, useState } from "react";
import { CalendarClock, CreditCard, MapPin, Repeat } from "lucide-react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ShopProduct, ShopSubscriptionOffer } from "@/lib/api";
import type { SavedAddress } from "@/lib/schemas";
import { openSubscriptionBillingWindow, SUBSCRIPTION_BILLING_CANCELLED_MESSAGE } from "@/lib/subscription-billing";
import { toastError } from "@/lib/toast";
import { cn, formatPrice } from "@/lib/utils";
import { getSavedAddresses } from "@/services/addresses";
import { discardSubscriptionBilling, startSubscription } from "@/services/subscriptions";
import type { SelectedCartOption } from "@/components/shop/productDetailHelpers";

type SubscriptionLine = { ioId: string; qty: number; label: string } | { error: string };

/** 정기구독은 한 줄(선택옵션 하나 + 수량)만 — 추가옵션은 담지 않는다. */
export function subscriptionLineOf(
  hasOptionSubjects: boolean,
  selectedCartOptions: SelectedCartOption[],
  quantity: number
): SubscriptionLine {
  if (!hasOptionSubjects) return { ioId: "", qty: Math.max(1, quantity), label: "" };
  const base = selectedCartOptions.filter((option) => option.ioType === 0);
  if (base.length === 0) return { error: "정기구독할 옵션을 먼저 선택해 주세요." };
  if (base.length > 1) return { error: "정기구독은 옵션 하나만 고를 수 있습니다." };
  return { ioId: base[0].io_id, qty: Math.max(1, base[0].qty), label: base[0].label };
}

function addressLine(address: SavedAddress) {
  const zip = [address.ad_zip1, address.ad_zip2].join("");
  return [zip ? `(${zip})` : "", address.ad_addr1, address.ad_addr2, address.ad_addr3].filter(Boolean).join(" ");
}

export type ProductSubscriptionPanelProps = {
  product: ShopProduct;
  offer: ShopSubscriptionOffer;
  hasOptionSubjects: boolean;
  selectedCartOptions: SelectedCartOption[];
  quantity: number;
  onRequireLogin: () => boolean;
};

/**
 * 상품 상세의 정기구독 칸 — 주기를 고르고, 저장된 배송지를 골라 토스 자동결제 카드 등록창을 연다.
 * 금액은 서버가 결제하는 날의 상품 가격으로 정한다(여기 보이는 값은 오늘 기준 안내).
 */
export function ProductSubscriptionPanel({
  product,
  offer,
  hasOptionSubjects,
  selectedCartOptions,
  quantity,
  onRequireLogin,
}: ProductSubscriptionPanelProps) {
  const [cycle, setCycle] = useState(offer.cycles[0]?.value ?? "");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [addresses, setAddresses] = useState<SavedAddress[] | null>(null);
  const [addressId, setAddressId] = useState(0);
  const [memo, setMemo] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const line = subscriptionLineOf(hasOptionSubjects, selectedCartOptions, quantity);
  const cycleLabel = offer.cycles.find((item) => item.value === cycle)?.label ?? "";

  useEffect(() => {
    if (!dialogOpen || addresses !== null) return;
    let alive = true;
    getSavedAddresses()
      .then((rows) => {
        if (!alive) return;
        setAddresses(rows);
        const preferred = rows.find((row) => Number(row.ad_default) === 1) ?? rows[0];
        setAddressId(preferred ? Number(preferred.ad_id) : 0);
      })
      .catch(() => alive && setAddresses([]));
    return () => {
      alive = false;
    };
  }, [dialogOpen, addresses]);

  const openDialog = () => {
    if ("error" in line) {
      toastError(line.error);
      return;
    }
    if (!onRequireLogin()) return;
    setDialogOpen(true);
  };

  const submit = async () => {
    if ("error" in line || !addressId || submitting) return;
    setSubmitting(true);
    let registrationToken = "";
    try {
      const registration = await startSubscription({
        it_id: product.it_id,
        io_id: line.ioId,
        qty: line.qty,
        cycle,
        ad_id: addressId,
        od_memo: memo.trim(),
      });
      registrationToken = registration.registration_token;
      await openSubscriptionBillingWindow(registration, window.location.origin);
    } catch (err: unknown) {
      if (registrationToken) {
        // 등록창을 닫았거나 열지 못했다 — 기다리던 등록을 지운다
        await discardSubscriptionBilling(registrationToken).catch(() => undefined);
      }
      const message = err instanceof Error ? err.message : "카드 등록을 시작하지 못했습니다.";
      if (message !== SUBSCRIPTION_BILLING_CANCELLED_MESSAGE) toastError(message);
      setSubmitting(false);
    }
  };

  return (
    <section
      className="product-subscription space-y-3 rounded-md border border-primary/30 bg-primary/5 p-4"
      aria-labelledby="product-subscription-title"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 id="product-subscription-title" className="flex items-center gap-2 text-sm font-semibold">
          <Repeat className="h-4 w-4 text-primary" aria-hidden />
          정기구독
        </h2>
        {offer.discount_rate > 0 && (
          <span className="rounded bg-primary px-2 py-0.5 text-xs font-bold text-primary-foreground">
            {offer.discount_rate}% 할인
          </span>
        )}
      </div>
      <p className="text-sm">
        정기구독가 <b className="text-base">{formatPrice(offer.price)}</b>
        {offer.discount_rate > 0 && (
          <span className="ml-2 text-xs text-muted-foreground line-through">{formatPrice(product.it_price)}</span>
        )}
      </p>
      <div role="radiogroup" aria-label="배송 주기" className="flex flex-wrap gap-2">
        {offer.cycles.map((item) => (
          <button
            key={item.value}
            type="button"
            role="radio"
            aria-checked={cycle === item.value}
            onClick={() => setCycle(item.value)}
            className={cn(
              "rounded-full border px-3 py-1.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              cycle === item.value
                ? "border-primary bg-primary text-primary-foreground"
                : "bg-background hover:border-primary/60"
            )}
          >
            {item.label}
          </button>
        ))}
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">
        카드를 한 번 등록하면 고른 주기마다 자동으로 결제하고 배송합니다. 결제 금액은 <b>결제하는 날의 상품 가격</b>
        (옵션 금액 포함, 배송비 별도)으로 정해지며 첫 결제는 카드 등록 직후에 진행됩니다. 마이페이지에서 언제든 일시정지 ·
        건너뛰기 · 해지할 수 있습니다.
      </p>
      <Button type="button" variant="outline" className="w-full border-primary/60" onClick={openDialog}>
        <CreditCard className="mr-2 h-4 w-4" aria-hidden />
        정기구독 신청
      </Button>

      <Dialog open={dialogOpen} onOpenChange={(open) => !submitting && setDialogOpen(open)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>정기구독 신청</DialogTitle>
            <DialogDescription>
              배송지를 고른 뒤 토스페이먼츠 카드 등록창에서 결제할 카드를 등록합니다.
            </DialogDescription>
          </DialogHeader>
          <dl className="grid grid-cols-[5rem_minmax(0,1fr)] gap-x-3 gap-y-1.5 rounded-md bg-muted/40 p-3 text-sm">
            <dt className="text-muted-foreground">상품</dt>
            <dd className="m-0 min-w-0 break-words font-medium">
              {product.it_name}
              {"label" in line && line.label ? <span className="block text-xs text-muted-foreground">{line.label}</span> : null}
            </dd>
            <dt className="text-muted-foreground">수량</dt>
            <dd className="m-0">{"qty" in line ? line.qty : 1}개</dd>
            <dt className="text-muted-foreground">주기</dt>
            <dd className="m-0 flex items-center gap-1">
              <CalendarClock className="h-3.5 w-3.5" aria-hidden /> {cycleLabel}
            </dd>
          </dl>
          <fieldset className="space-y-2">
            <legend className="mb-1 flex items-center gap-1 text-sm font-medium">
              <MapPin className="h-4 w-4" aria-hidden /> 배송지
            </legend>
            {addresses === null ? (
              <p className="text-sm text-muted-foreground">배송지를 불러오는 중…</p>
            ) : addresses.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                저장된 배송지가 없습니다.{" "}
                <Link href="/mypage/addresses" className="font-medium text-primary underline">
                  배송지 관리
                </Link>
                에서 먼저 등록해 주세요.
              </p>
            ) : (
              <div className="max-h-52 space-y-2 overflow-y-auto">
                {addresses.map((address) => (
                  <label
                    key={address.ad_id}
                    className={cn(
                      "flex cursor-pointer gap-3 rounded-md border p-3 text-sm",
                      addressId === Number(address.ad_id) ? "border-primary bg-primary/5" : "hover:border-primary/40"
                    )}
                  >
                    <input
                      type="radio"
                      name="subscription-address"
                      className="mt-1"
                      checked={addressId === Number(address.ad_id)}
                      onChange={() => setAddressId(Number(address.ad_id))}
                    />
                    <span className="min-w-0">
                      <span className="block font-medium">
                        {address.ad_subject || address.ad_name} · {address.ad_name}
                      </span>
                      <span className="block break-words text-muted-foreground">{addressLine(address)}</span>
                      <span className="block text-muted-foreground">{address.ad_hp || address.ad_tel}</span>
                    </span>
                  </label>
                ))}
              </div>
            )}
          </fieldset>
          <label className="block space-y-1 text-sm">
            <span className="font-medium">배송 메모</span>
            <input
              value={memo}
              onChange={(event) => setMemo(event.target.value)}
              maxLength={255}
              placeholder="예: 문 앞에 놓아 주세요"
              className="h-9 w-full rounded-md border bg-background px-3 outline-none focus:ring-2 focus:ring-ring"
            />
          </label>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDialogOpen(false)} disabled={submitting}>
              닫기
            </Button>
            <Button type="button" onClick={submit} disabled={submitting || !addressId}>
              {submitting ? "카드 등록창 여는 중…" : "카드 등록하고 시작"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
