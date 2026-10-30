"use client";

import { useCallback, useEffect, useId, useRef, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { ORDER_STATUS_BADGE_CLASS } from "@/lib/order-status";
import {
  RETURN_STATUS_TONE,
  type ShopOrderReturns,
  type ShopReturnKind,
  type ShopReturnOrderLine,
  type ShopReturnReason,
  type ShopReturnRequest,
} from "@/lib/shop-returns";
import { toastError, toastSuccess } from "@/lib/toast";
import { cn, formatCartOption, formatDateTime, formatPrice } from "@/lib/utils";
import { getOrderReturns, requestOrderReturn, withdrawOrderReturn } from "@/services/member";

const DETAIL_MAX_LENGTH = 1000;

/** 주문의 반품·교환 상태를 불러온다 — 불러오지 못하면(신청 기능이 없는 서버 등) null 로 두고 화면에서 감춘다. */
export function useOrderReturns(orderId: string, guestUid: string, ready: boolean) {
  const [state, setState] = useState<ShopOrderReturns | null>(null);

  useEffect(() => {
    if (!ready || !orderId) return;
    let alive = true;
    getOrderReturns(orderId, guestUid)
      .then((loaded) => {
        if (alive) setState(loaded);
      })
      .catch(() => {
        if (alive) setState(null);
      });
    return () => {
      alive = false;
    };
  }, [guestUid, orderId, ready]);

  return { state, setState };
}

function lineName(line: { it_name: string; ct_option: string }): string {
  const option = formatCartOption(line.ct_option);
  return option && option !== line.it_name ? `${line.it_name} / ${option}` : line.it_name;
}

function RequestStatusBadge({ request }: { request: ShopReturnRequest }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        ORDER_STATUS_BADGE_CLASS[RETURN_STATUS_TONE[request.status]]
      )}
    >
      {request.status_label}
    </span>
  );
}

function RequestOutcome({ request }: { request: ShopReturnRequest }) {
  if (request.status === "rejected" && request.reject_reason) {
    return (
      <div role="status" className="alert alert-error mt-2 text-sm">
        <div>
          <p className="font-semibold">거절 사유</p>
          <p>{request.reject_reason}</p>
        </div>
      </div>
    );
  }
  if (request.status === "approved") {
    return (
      <p className="mt-2 text-xs text-muted-foreground">
        신청이 승인되었습니다. 안내에 따라 상품을 보내 주시면 확인한 뒤 {request.kind === "return" ? "환불" : "교환 상품 발송"}을 진행합니다.
      </p>
    );
  }
  if (request.status === "completed" && request.kind === "return") {
    return (
      <p className="mt-2 text-sm">
        환불금액 <strong>{formatPrice(request.refund_amount)}</strong>
        {request.return_fee > 0 && (
          <span className="text-xs text-muted-foreground"> (반품 배송비 {formatPrice(request.return_fee)} 차감)</span>
        )}
      </p>
    );
  }
  if (request.status === "completed" && request.exchange_invoice) {
    return (
      <p className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground">교환 상품 발송</span>
        <span className="font-medium">{request.exchange_delivery_company}</span>
        <span className="font-mono">{request.exchange_invoice}</span>
        {request.exchange_inquiry_url && (
          <a
            href={request.exchange_inquiry_url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-xs text-primary hover:underline"
          >
            배송 조회 →
          </a>
        )}
      </p>
    );
  }
  return null;
}

interface OrderReturnsPanelProps {
  orderId: string;
  guestUid: string;
  state: ShopOrderReturns | null;
  onStateChange: (state: ShopOrderReturns) => void;
  onOpenForm: (lineIds: number[]) => void;
}

/** 주문 상세의 "반품·교환" — 신청 버튼, 신청 기간 안내, 신청 내역과 철회. */
export function OrderReturnsPanel({ orderId, guestUid, state, onStateChange, onOpenForm }: OrderReturnsPanelProps) {
  const [withdrawingId, setWithdrawingId] = useState<number | null>(null);
  const withdrawingRef = useRef(false);
  const titleId = useId();

  if (!state || (!state.can_request && state.requests.length === 0)) return null;
  const eligibleIds = state.lines.filter((line) => line.eligible).map((line) => line.line_id);

  const withdraw = async (request: ShopReturnRequest) => {
    if (withdrawingRef.current) return;
    if (!window.confirm(`${request.kind_label} 신청 #${request.id}을(를) 철회할까요?`)) return;
    withdrawingRef.current = true;
    setWithdrawingId(request.id);
    try {
      const next = await withdrawOrderReturn(orderId, request.id, guestUid);
      if (next) onStateChange(next);
      toastSuccess(`${request.kind_label} 신청을 철회했습니다.`);
    } catch (err: unknown) {
      toastError(err instanceof Error && err.message ? err.message : "신청을 철회하지 못했습니다.");
    } finally {
      withdrawingRef.current = false;
      setWithdrawingId(null);
    }
  };

  return (
    <section className="shop-order-section shop-order-returns rounded-lg border p-6" aria-labelledby={titleId}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id={titleId} className="text-lg font-bold">
            반품·교환
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            배송완료 후 {state.request_days}일 이내에 신청할 수 있습니다. 배송중인 상품도 신청할 수 있습니다.
          </p>
        </div>
        {state.can_request && (
          <Button variant="outline" size="sm" onClick={() => onOpenForm(eligibleIds)}>
            반품/교환 신청
          </Button>
        )}
      </div>
      {!state.can_request && state.block_reason && (
        <p className="mt-2 text-xs text-muted-foreground">{state.block_reason}</p>
      )}

      {state.requests.length > 0 && (
        <ul className="mt-4 space-y-3" aria-label="반품·교환 신청 내역">
          {state.requests.map((request) => (
            <li key={request.id} className="shop-order-return-request rounded-md border p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-semibold">
                    {request.kind_label} 신청 #{request.id}
                  </span>
                  <RequestStatusBadge request={request} />
                  <span className="text-xs text-muted-foreground">{formatDateTime(request.created_at)}</span>
                </div>
                {request.can_withdraw && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => withdraw(request)}
                    disabled={withdrawingId !== null}
                  >
                    {withdrawingId === request.id ? "철회 중..." : "신청 철회"}
                  </Button>
                )}
              </div>
              <ul className="mt-2 space-y-0.5">
                {request.lines.map((line) => (
                  <li key={`${request.id}-${line.line_id}`} className="break-words text-xs text-muted-foreground">
                    {lineName(line)} {line.qty}개
                  </li>
                ))}
              </ul>
              <p className="mt-1 text-xs">
                <span className="text-muted-foreground">사유</span> {request.reason_label}
                {request.detail ? ` · ${request.detail}` : ""}
              </p>
              <RequestOutcome request={request} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

interface ReturnRequestDialogProps {
  orderId: string;
  guestUid: string;
  state: ShopOrderReturns;
  /** 처음 고른 상품(줄 id) — 상품 카드의 버튼은 그 상품의 줄만, 위쪽 버튼은 신청할 수 있는 모든 줄 */
  initialLineIds: number[];
  onClose: () => void;
  onSubmitted: (state: ShopOrderReturns) => void;
}

/** 반품/교환 신청서 — 구분, 상품과 수량, 사유, 상세 사유. */
export function ReturnRequestDialog({
  orderId,
  guestUid,
  state,
  initialLineIds,
  onClose,
  onSubmitted,
}: ReturnRequestDialogProps) {
  const eligible = state.lines.filter((line) => line.eligible);
  const [kind, setKind] = useState<ShopReturnKind>("return");
  const [reason, setReason] = useState<ShopReturnReason | "">("");
  const [detail, setDetail] = useState("");
  const [quantities, setQuantities] = useState<Record<number, number>>(() =>
    Object.fromEntries(
      eligible.filter((line) => initialLineIds.includes(line.line_id)).map((line) => [line.line_id, line.ct_qty])
    )
  );
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const detailId = useId();
  const errorId = useId();

  const toggleLine = (line: ShopReturnOrderLine, checked: boolean) => {
    setQuantities((current) => {
      const next = { ...current };
      if (checked) next[line.line_id] = line.ct_qty;
      else delete next[line.line_id];
      return next;
    });
    if (error) setError("");
  };

  const setQuantity = (line: ShopReturnOrderLine, value: string) => {
    const qty = Math.min(line.ct_qty, Math.max(1, Math.floor(Number(value) || 1)));
    setQuantities((current) => ({ ...current, [line.line_id]: qty }));
  };

  const close = useCallback(() => {
    if (!submittingRef.current) onClose();
  }, [onClose]);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submittingRef.current) return;
    const lines = Object.entries(quantities).map(([lineId, qty]) => ({ line_id: Number(lineId), qty }));
    const trimmed = detail.trim();
    if (lines.length === 0) return setError("신청할 상품을 하나 이상 선택해 주세요.");
    if (!reason) return setError("신청 사유를 선택해 주세요.");
    if (reason === "other" && !trimmed) return setError("기타 사유를 입력해 주세요.");
    submittingRef.current = true;
    setSubmitting(true);
    setError("");
    try {
      const next = await requestOrderReturn(orderId, { kind, reason, detail: trimmed, lines }, guestUid);
      if (next) onSubmitted(next);
      toastSuccess(`${kind === "return" ? "반품" : "교환"} 신청이 접수되었습니다.`);
      submittingRef.current = false;
      onClose();
    } catch (err: unknown) {
      const message = err instanceof Error && err.message ? err.message : "신청하지 못했습니다.";
      setError(message);
      toastError(message);
      submittingRef.current = false;
    } finally {
      setSubmitting(false);
    }
  };

  const showFee = kind === "return" && reason === "change_of_mind" && state.return_shipping_fee > 0;

  return (
    <Dialog open onOpenChange={(open) => (!open ? close() : undefined)}>
      <DialogContent className="shop-order-return-dialog flex max-h-[88dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-lg">
        <DialogHeader className="border-b p-4 pr-12 text-left">
          <DialogTitle>반품/교환 신청</DialogTitle>
          <DialogDescription>
            상품을 받은 뒤 배송완료 {state.request_days}일 이내에 신청할 수 있습니다. 신청을 확인한 뒤 회수 방법을 안내해 드립니다.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col" noValidate>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 text-sm">
            <fieldset>
              <legend className="text-xs font-medium text-muted-foreground">구분</legend>
              <div className="mt-1 flex gap-4">
                {state.kinds.map((option) => (
                  <label key={option.value} className="flex items-center gap-1.5">
                    <input
                      type="radio"
                      name="return_kind"
                      value={option.value}
                      checked={kind === option.value}
                      onChange={() => setKind(option.value)}
                    />
                    {option.label}
                  </label>
                ))}
              </div>
            </fieldset>

            <fieldset>
              <legend className="text-xs font-medium text-muted-foreground">상품</legend>
              <ul className="mt-1 space-y-2">
                {eligible.map((line) => {
                  const checked = line.line_id in quantities;
                  return (
                    <li key={line.line_id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-2">
                      <label className="flex min-w-0 flex-1 items-center gap-2">
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={(event) => toggleLine(line, event.target.checked)}
                        />
                        <span className="min-w-0 break-words">
                          {lineName(line)}
                          <span className="block text-xs text-muted-foreground">
                            {line.ct_status} · {formatPrice(line.line_total)}
                            {line.deadline ? ` · ${formatDateTime(line.deadline)}까지` : ""}
                          </span>
                        </span>
                      </label>
                      {line.ct_qty > 1 ? (
                        <label className="flex items-center gap-1 text-xs">
                          <span className="sr-only">{lineName(line)} 신청 수량</span>
                          <input
                            type="number"
                            min={1}
                            max={line.ct_qty}
                            step={1}
                            value={quantities[line.line_id] ?? line.ct_qty}
                            disabled={!checked}
                            onChange={(event) => setQuantity(line, event.target.value)}
                            className="w-16 rounded-[4px] border bg-background px-2 py-1 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                          />
                          / {line.ct_qty}개
                        </label>
                      ) : (
                        <span className="text-xs text-muted-foreground">1개</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </fieldset>

            <fieldset>
              <legend className="text-xs font-medium text-muted-foreground">사유</legend>
              <div className="mt-1 grid grid-cols-2 gap-2">
                {state.reasons.map((option) => (
                  <label key={option.value} className="flex items-center gap-1.5">
                    <input
                      type="radio"
                      name="return_reason"
                      value={option.value}
                      checked={reason === option.value}
                      onChange={() => {
                        setReason(option.value);
                        if (error) setError("");
                      }}
                    />
                    {option.label}
                  </label>
                ))}
              </div>
            </fieldset>

            <div>
              <label htmlFor={detailId} className="text-xs font-medium text-muted-foreground">
                상세 사유{reason === "other" ? " (필수)" : " (선택)"}
              </label>
              <textarea
                id={detailId}
                value={detail}
                onChange={(event) => {
                  setDetail(event.target.value);
                  if (error) setError("");
                }}
                maxLength={DETAIL_MAX_LENGTH}
                rows={4}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? errorId : undefined}
                className="mt-1 w-full rounded-[4px] border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                placeholder="예: 포장을 뜯어 보니 제품 한쪽이 깨져 있었습니다."
              />
              <p className="text-right text-xs text-muted-foreground">
                {detail.length}/{DETAIL_MAX_LENGTH}
              </p>
            </div>

            {showFee && (
              <p role="note" className="rounded-md bg-amber-50 p-2 text-xs text-amber-800 dark:bg-amber-900/10 dark:text-amber-200">
                단순변심 반품은 반품 배송비 {formatPrice(state.return_shipping_fee)}을(를) 환불금액에서 뺍니다.
              </p>
            )}
            <p id={errorId} className="text-xs text-destructive" role="alert">
              {error}
            </p>
          </div>
          <DialogFooter className="border-t p-4">
            <Button type="button" variant="outline" onClick={close} disabled={submitting}>
              닫기
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "신청 중..." : "신청하기"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
