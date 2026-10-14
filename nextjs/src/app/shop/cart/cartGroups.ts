import type { ShopCartItem } from "@/lib/api";
import { getShopCartShippingPaymentLabel } from "@/lib/shop-shipping-label";
import { formatCartOption, formatPrice } from "@/lib/utils";

/**
 * 장바구니 화면의 한 칸 — 영카트 cart.php 처럼 같은 상품의 줄(선택옵션 · 추가옵션)을 묶는다.
 * 숫자는 cart.php 의 상품별 합계와 같다: 총수량 Σ수량, 판매가 = 담을 때의 상품 가격(ct_price),
 * 소계 Σ줄 금액(쿠폰 할인 전). 레퍼런스의 포인트 칸은 이 API 의 장바구니 응답에 포인트가 없어 두지 않는다.
 */
export interface CartGroup {
  itId: string;
  /** 이름 · 그림 · 링크에 쓰는 대표 줄(본품 줄 중 먼저 담은 것). */
  item: ShopCartItem;
  /** 본품 줄 먼저, 그다음 담은 순서(cart.php 의 옵션 목록 순서). */
  lines: ShopCartItem[];
  ctIds: string[];
  totalQty: number;
  salePrice: number;
  subtotal: number;
  couponDiscount: number;
  shippingLabel: string;
}

export function cartLineTotal(line: ShopCartItem): number {
  return typeof line.line_total === "number" ? line.line_total : line.ct_price * line.ct_qty;
}

// 이 API 의 ct_id 는 순서가 없는 난수라 담은 순서는 응답 순서(담은 차례)로 본다. Array.prototype.sort 는 안정적이므로
// 본품 줄을 앞으로 올려도 같은 종류끼리는 담은 차례가 그대로 남는다.
function byLineType(a: ShopCartItem, b: ShopCartItem): number {
  return Number(a.io_type ?? 0) - Number(b.io_type ?? 0);
}

export function groupCartItems(items: ShopCartItem[]): CartGroup[] {
  const linesByItem = new Map<string, ShopCartItem[]>();
  for (const item of items) {
    linesByItem.set(item.it_id, [...(linesByItem.get(item.it_id) ?? []), item]);
  }

  // Map 은 처음 넣은 차례를 지키므로 상품 칸도 처음 담은 차례대로 나온다.
  return Array.from(linesByItem.entries()).map(([itId, unsorted]) => {
    const lines = [...unsorted].sort(byLineType);
    const item = lines[0];
    return {
      itId,
      item,
      lines,
      ctIds: lines.map((line) => line.ct_id),
      totalQty: lines.reduce((sum, line) => sum + line.ct_qty, 0),
      salePrice: item.ct_price,
      subtotal: lines.reduce((sum, line) => sum + cartLineTotal(line), 0),
      couponDiscount: lines.reduce((sum, line) => sum + (line.cp_price ?? 0), 0),
      shippingLabel: getShopCartShippingPaymentLabel(item, items),
    };
  });
}

/** cart.php 의 옵션 이름 — 옵션 없는 줄은 영카트가 상품명을 옵션 자리에 담으므로 상품명. */
export function cartLineOptionName(line: ShopCartItem): string {
  return formatCartOption(line.ct_option) || line.it_name;
}

/** cart.php 의 옵션 줄 — "옵션 수량개 (+옵션금액)". */
export function formatCartLineOption(line: ShopCartItem): string {
  const ioPrice = Number(line.io_price ?? 0);
  return `${cartLineOptionName(line)} ${line.ct_qty}개 (${ioPrice >= 0 ? "+" : ""}${formatPrice(ioPrice)})`;
}

export function selectedGroupCtIds(groups: CartGroup[], selected: ReadonlySet<string>): string[] {
  return groups.filter((group) => selected.has(group.itId)).flatMap((group) => group.ctIds);
}

/**
 * 주문하기 — 모두 골랐으면 그냥 주문서(장바구니 전체), 일부만 골랐으면 그 줄만(주문서가 ct_ids 로 받는다).
 * 아무것도 안 골랐으면 빈 글자.
 */
export function cartOrderHref(groups: CartGroup[], selected: ReadonlySet<string>): string {
  const ctIds = selectedGroupCtIds(groups, selected);
  if (ctIds.length === 0) return "";
  const allCount = groups.reduce((sum, group) => sum + group.ctIds.length, 0);
  if (ctIds.length === allCount) return "/shop/order";
  return `/shop/order?ct_ids=${encodeURIComponent(ctIds.join(","))}`;
}
