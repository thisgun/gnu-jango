"use client";

import { useState } from "react";
import { Loader2, Minus, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/dialog";
import type { ShopCartItem } from "@/lib/api";
import { toastError } from "@/lib/toast";
import { formatPrice } from "@/lib/utils";
import { removeCartItem, updateCartItemQuantity } from "@/services/cart";
import { cartLineOptionName, cartLineTotal, type CartGroup } from "./cartGroups";
import { CartDialogHead } from "./CartDialogHead";

interface CartOptionDialogProps {
  group: CartGroup;
  onClose: () => void;
  /** 고친 뒤 장바구니를 다시 부른다. */
  onChanged: () => Promise<void>;
}

const NO_BASE_OPTION = "선택옵션을 하나 이상 선택해 주십시오.";

/** 줄 한 개의 단가 — 서버가 준 줄 금액을 수량으로 나눈다(추가옵션 줄은 옵션 금액, 본품 줄은 상품가 + 옵션 금액). */
function unitPrice(line: ShopCartItem): number {
  return line.ct_qty > 0 ? cartLineTotal(line) / line.ct_qty : line.ct_price;
}

function isSupplyLine(line: ShopCartItem): boolean {
  return Number(line.io_type ?? 0) === 1;
}

function errorMessage(error: unknown): string {
  return error instanceof Error && error.message ? error.message : "선택사항 수정에 실패했습니다.";
}

/**
 * 선택사항수정 — 레퍼런스(영카트 cart.php 의 cartoption.php 자리)처럼 상품의 줄을 창에서 고친다.
 * 이 API 는 옵션을 통째로 바꾸는 요청이 없으므로 담긴 줄의 수량을 바꾸고 줄을 지우는 것까지만 한다
 * (PATCH · DELETE /shop/cart/:ct_id — 재고 · 구매수량 한도는 서버가 줄마다 다시 본다). 확인을 눌러야 보낸다.
 */
export function CartOptionDialog({ group, onClose, onChanged }: CartOptionDialogProps) {
  const [quantities, setQuantities] = useState<Record<string, number>>(() =>
    Object.fromEntries(group.lines.map((line) => [line.ct_id, line.ct_qty]))
  );
  const [removed, setRemoved] = useState<ReadonlySet<string>>(() => new Set());
  const [saving, setSaving] = useState(false);

  const remaining = group.lines.filter((line) => !removed.has(line.ct_id));
  const total = remaining.reduce((sum, line) => sum + Math.round(unitPrice(line) * (quantities[line.ct_id] ?? line.ct_qty)), 0);

  const setQty = (ctId: string, next: number) => {
    if (!Number.isFinite(next)) return;
    setQuantities((previous) => ({ ...previous, [ctId]: Math.max(1, Math.floor(next)) }));
  };

  const removeLine = (ctId: string) => {
    setRemoved((previous) => new Set(previous).add(ctId));
  };

  const handleConfirm = async () => {
    if (saving) return;
    // 추가옵션만 남기고 본품 줄을 모두 지우면 영카트처럼 막는다(상품을 통째로 지우려면 추가옵션까지 지운다).
    if (remaining.length > 0 && !remaining.some((line) => !isSupplyLine(line))) {
      toastError(NO_BASE_OPTION);
      return;
    }
    const toRemove = group.lines.filter((line) => removed.has(line.ct_id));
    const toUpdate = remaining.filter((line) => (quantities[line.ct_id] ?? line.ct_qty) !== line.ct_qty);
    if (toRemove.length === 0 && toUpdate.length === 0) {
      onClose();
      return;
    }

    setSaving(true);
    let failure = "";
    for (const line of toUpdate) {
      try {
        await updateCartItemQuantity(line.ct_id, quantities[line.ct_id]);
      } catch (err: unknown) {
        failure ||= errorMessage(err);
      }
    }
    for (const line of toRemove) {
      try {
        await removeCartItem(line.ct_id);
      } catch (err: unknown) {
        failure ||= errorMessage(err);
      }
    }
    await onChanged();
    setSaving(false);
    // 일부가 실패해도 창을 닫는다 — 다시 불러온 장바구니가 실제 상태이고, 창의 초안(지운 줄 · 수량)은 그와 어긋난다.
    if (failure) toastError(failure);
    onClose();
  };

  return (
    <Dialog open onOpenChange={(open) => (!open && !saving ? onClose() : undefined)}>
      {/* 테마가 상품 카드의 옵션 고르기 창과 같은 모양을 입히게 product-quick-add-* · product-selected-* 손잡이를 같이 단다. */}
      <DialogContent className="product-quick-add-dialog cart-option-dialog flex max-h-[88dvh] flex-col gap-0 overflow-hidden p-0 sm:max-w-md">
        <CartDialogHead group={group} kicker="선택사항수정" />

        <div className="product-quick-add-body min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          <div className="product-selected space-y-2" aria-label="선택된 옵션">
            <p className="product-selected-title pb-1 text-sm font-semibold" aria-hidden="true">선택된 옵션</p>
            {remaining.length === 0 && (
              <p className="text-sm text-muted-foreground">확인을 누르면 이 상품을 장바구니에서 삭제합니다.</p>
            )}
            {remaining.map((line) => {
              const label = cartLineOptionName(line);
              const qty = quantities[line.ct_id] ?? line.ct_qty;
              return (
                <div key={line.ct_id} className="product-selected-line relative rounded-lg border bg-background p-3">
                  <p className="pr-8 text-sm font-medium break-words">
                    {isSupplyLine(line) ? `추가옵션: ${label}` : label}
                  </p>
                  <button
                    type="button"
                    aria-label={`${label} 삭제`}
                    onClick={() => removeLine(line.ct_id)}
                    disabled={saving}
                    className="absolute right-2 top-2 grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
                  >
                    <X className="h-4 w-4" />
                  </button>
                  <div className="mt-2 flex items-center justify-between gap-3">
                    <div className="product-quantity-controls flex items-center gap-1">
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        aria-label={`${label} 수량 줄이기`}
                        onClick={() => setQty(line.ct_id, qty - 1)}
                        disabled={saving || qty <= 1}
                      >
                        <Minus className="h-4 w-4" />
                      </Button>
                      <input
                        type="number"
                        min={1}
                        aria-label={`${label} 수량`}
                        value={qty}
                        onChange={(event) => setQty(line.ct_id, Number(event.target.value))}
                        disabled={saving}
                        className="h-9 w-14 rounded-md border bg-background text-center text-sm outline-none"
                      />
                      <Button
                        type="button"
                        variant="outline"
                        size="icon"
                        aria-label={`${label} 수량 늘리기`}
                        onClick={() => setQty(line.ct_id, qty + 1)}
                        disabled={saving}
                      >
                        <Plus className="h-4 w-4" />
                      </Button>
                    </div>
                    <span className="product-selected-price text-sm font-semibold">
                      {formatPrice(Math.round(unitPrice(line) * qty))}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="product-total rounded-lg border bg-muted/50 p-4">
            <div className="flex items-center justify-between">
              <span className="product-total-label font-medium">총 금액</span>
              <span className="product-total-value text-xl font-bold text-primary">{formatPrice(total)}</span>
            </div>
          </div>
        </div>

        <DialogFooter className="product-quick-add-foot flex-row gap-2 border-t p-4 sm:justify-stretch">
          <Button variant="outline" className="product-quick-add-detail flex-1" onClick={onClose} disabled={saving}>
            닫기
          </Button>
          <Button
            className="product-quick-add-submit flex-1 gap-1.5"
            onClick={handleConfirm}
            disabled={saving}
            aria-busy={saving || undefined}
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : null}
            확인
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
