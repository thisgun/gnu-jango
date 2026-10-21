"use client";

import { useId, useRef, useState, type FormEvent } from "react";
import type { ShopOrder } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { formatPrice } from "@/lib/utils";
import { toastError, toastSuccess } from "@/lib/toast";
import {
  CASH_RECEIPT_TYPE_LABELS,
  cashReceiptIdentityPlaceholder,
  isCashReceiptType,
  normalizeCashReceiptIdentity,
  type CashReceiptType,
} from "@/lib/cash-receipt";
import { requestOrderCashReceipt } from "@/services/member";

interface CashReceiptPanelProps {
  order: ShopOrder;
  guestUid: string;
  onOrderUpdated: (order: ShopOrder) => void;
}

/**
 * 영카트 orderinquiryview.php 의 현금영수증 칸: 발급됐으면 승인번호와 확인 링크, 결제를 마친
 * 무통장·가상계좌·계좌이체 주문이면 발급 신청(taxsave.php), 신청이 접수됐으면 안내.
 */
export function CashReceiptPanel({ order, guestUid, onOrderUpdated }: CashReceiptPanelProps) {
  const receipt = order.cash_receipt;
  const [open, setOpen] = useState(false);
  const [cashType, setCashType] = useState<CashReceiptType>(
    isCashReceiptType(order.od_cash_type) ? order.od_cash_type : "income"
  );
  const [identity, setIdentity] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const identityId = useId();
  const errorId = useId();

  if (order.od_cash_no && order.od_cash === 1) {
    return (
      <div className="mt-4 rounded-md border bg-muted/30 p-3 text-sm">
        <p className="text-xs text-muted-foreground">현금영수증</p>
        <p className="mt-1 font-mono">{order.od_cash_no}</p>
        {order.od_cash_info && (
          <p className="mt-1 text-xs text-muted-foreground">{order.od_cash_info}</p>
        )}
        {/* the 현금영수증 확인 link sits with the payment receipts above */}
      </div>
    );
  }

  if (receipt?.state === "requested" || (!receipt && order.od_cash_request)) {
    return (
      <div role="status" className="alert alert-info mt-4">
        <div>
          <p className="font-semibold">현금영수증 신청 접수</p>
          <p className="text-sm">
            {receipt?.message || "현금영수증 신청이 접수되었습니다. 발급되면 이 화면에 표시됩니다."}
          </p>
        </div>
      </div>
    );
  }

  if (!receipt?.can_request) return null;

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (submittingRef.current) return;
    const checked = normalizeCashReceiptIdentity(cashType, identity);
    if (checked.error) {
      setError(checked.error);
      return;
    }
    submittingRef.current = true;
    setSubmitting(true);
    setError("");
    try {
      const result = await requestOrderCashReceipt(order.od_id, cashType, checked.digits, guestUid);
      if (result.order) onOrderUpdated(result.order);
      setOpen(false);
      setIdentity("");
      toastSuccess(result.message || "현금영수증 발급 신청이 접수되었습니다.");
    } catch (err: unknown) {
      const message = err instanceof Error && err.message ? err.message : "현금영수증을 발급하지 못했습니다.";
      setError(message);
      toastError(message);
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return (
    <section className="mt-4 rounded-md border p-3 text-sm" aria-labelledby={`${identityId}-title`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p id={`${identityId}-title`} className="font-semibold">
            현금영수증
          </p>
          <p className="text-xs text-muted-foreground">
            {receipt.message || `발급 금액 ${formatPrice(receipt.amount)}`}
          </p>
        </div>
        {!open && (
          <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
            현금영수증 발급
          </Button>
        )}
      </div>

      {open && (
        <form onSubmit={submit} className="mt-3 space-y-3" noValidate>
          <fieldset>
            <legend className="text-xs font-medium text-muted-foreground">발급 용도</legend>
            <div className="mt-1 flex gap-4">
              {receipt.types.map((type) => (
                <label key={type.value} className="flex items-center gap-1.5">
                  <input
                    type="radio"
                    name="cash_receipt_type"
                    value={type.value}
                    checked={cashType === type.value}
                    onChange={() => {
                      setCashType(type.value);
                      if (error) setError("");
                    }}
                  />
                  {type.label || CASH_RECEIPT_TYPE_LABELS[type.value]}
                </label>
              ))}
            </div>
          </fieldset>
          <div>
            <label htmlFor={identityId} className="text-xs font-medium text-muted-foreground">
              {cashType === "expense" ? "사업자등록번호" : "휴대폰번호 · 현금영수증카드 번호"}
            </label>
            <input
              id={identityId}
              value={identity}
              onChange={(event) => {
                setIdentity(event.target.value);
                if (error) setError("");
              }}
              inputMode="numeric"
              autoComplete="off"
              maxLength={40}
              required
              aria-invalid={error ? true : undefined}
              aria-describedby={error ? errorId : undefined}
              placeholder={cashReceiptIdentityPlaceholder(cashType)}
              className="mt-1 w-full rounded-[4px] border bg-background px-3 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
            <p id={errorId} className="mt-1 text-xs text-destructive" role="alert">
              {error}
            </p>
          </div>
          <p className="text-xs text-muted-foreground">
            {formatPrice(receipt.amount)}에 대해 {CASH_RECEIPT_TYPE_LABELS[cashType]}용 현금영수증을 발급합니다. 입력한 번호는
            발급에만 쓰입니다.
          </p>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" size="sm" onClick={() => setOpen(false)} disabled={submitting}>
              닫기
            </Button>
            <Button type="submit" size="sm" disabled={submitting}>
              {submitting ? "발급 요청 중..." : "발급 요청"}
            </Button>
          </div>
        </form>
      )}
    </section>
  );
}
