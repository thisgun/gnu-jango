import { formatPrice } from "@/lib/utils";

interface CartTotalsProps {
  shippingCost: number;
  coupon: number;
  total: number;
  /** 무료배송 기준 금액(0 이면 안내하지 않는다). */
  freeThreshold: number;
}

/**
 * 영카트 cart.php 아래의 합계 막대 — 배송비 · 총계 가격(쿠폰을 묶었으면 쿠폰 할인도).
 * 레퍼런스의 포인트 칸은 장바구니 응답에 포인트가 없어 두지 않고, 대신 무료배송 기준을 막대 아래에 알린다.
 */
export function CartTotals({ shippingCost, coupon, total, freeThreshold }: CartTotalsProps) {
  const cell = "cart-total-cell flex items-center justify-between gap-4 px-6 py-5";
  return (
    <>
      <dl className="cart-totals mt-8 grid overflow-hidden rounded-md bg-muted text-sm md:auto-cols-fr md:grid-flow-col">
        <div className={cell}>
          <dt>배송비</dt>
          <dd className="font-bold">{shippingCost === 0 ? "무료" : formatPrice(shippingCost)}</dd>
        </div>
        {coupon > 0 && (
          <div className={`${cell} border-t text-green-700 md:border-l md:border-t-0`}>
            <dt>쿠폰 할인</dt>
            <dd className="font-bold">-{formatPrice(coupon)}</dd>
          </div>
        )}
        <div className={`${cell} cart-total-grand bg-foreground text-background`}>
          <dt>총계 가격</dt>
          <dd className="text-base font-bold">{formatPrice(total)}</dd>
        </div>
      </dl>
      {shippingCost > 0 && freeThreshold > 0 && (
        <p className="cart-free-shipping mt-2 text-right text-xs text-muted-foreground">
          {formatPrice(freeThreshold)} 이상 구매 시 무료배송
        </p>
      )}
    </>
  );
}
