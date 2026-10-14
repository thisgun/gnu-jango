import type { ShopProduct } from "@/lib/api";
import { isProductDetailSoldOut } from "@/components/shop/productDetailHelpers";
import { formatPrice } from "@/lib/utils";

/**
 * 상품 카드의 품절 판정 — 영카트 is_soldout() 과 같다(레퍼런스 앱 lib/shop-product-state 에서 옮김).
 * 이 앱의 목록 응답은 상품마다 옵션(options)을 함께 주므로, 옵션이 있으면 상세와 같은 판정
 * (선택옵션이 모두 품절이면 품절)을 쓴다. 옵션 목록이 없으면 품절 표시, 또는 옵션 없는 상품의 재고 0 이하로 본다 —
 * 선택옵션 상품은 재고를 옵션마다 따로 세므로 상품 재고(it_stock_qty)로 품절을 정하지 않는다.
 *
 * 서버 컴포넌트와 클라이언트 카드가 함께 부를 수 있도록 "use client" 파일에 두지 않는다.
 */
export function isProductSoldOut(
  product: Pick<ShopProduct, "it_soldout" | "it_stock_qty" | "it_option_subject" | "options">
): boolean {
  if (product.options) return isProductDetailSoldOut(product);
  if (String(product.it_soldout ?? "0") === "1") return true;
  return !(product.it_option_subject || "").trim() && Number(product.it_stock_qty) <= 0;
}

/** 선택옵션을 골라야 담을 수 있는 상품인가 — 옵션 목록이 있으면 그것으로, 없으면 선택옵션 제목으로 본다. */
export function hasProductBaseOptions(product: Pick<ShopProduct, "it_option_subject" | "options">): boolean {
  if (product.options) return product.options.some((option) => Number(option.io_type) === 0);
  return Boolean((product.it_option_subject || "").trim());
}

/** 가격 칸에 쓰는 상품 정보 — 목록 줄 · 장바구니 줄 · 위시 줄 · 비교 줄이 모두 이 정도는 갖는다. */
export interface ProductPriceSource {
  it_price?: number | null;
  it_cust_price?: number | null;
  it_tel_inq?: string | number | null;
}

/** 전화문의 상품인가(영카트 it_tel_inq). 온라인으로 담거나 살 수 없고 가격 대신 "전화문의"를 보인다. */
export function isTelInquiry(item?: Pick<ProductPriceSource, "it_tel_inq"> | null): boolean {
  return String(item?.it_tel_inq ?? "0") === "1";
}

/** 할인으로 보이는가: 전화문의가 아니고, 판매가 > 0, 정가 > 판매가. (판매가 0 이면 "100%" 가 나오지 않게 뺀다.) */
export function hasProductDiscount(item: ProductPriceSource): boolean {
  const price = Number(item.it_price ?? 0);
  const cust = Number(item.it_cust_price ?? 0);
  return !isTelInquiry(item) && price > 0 && cust > price;
}

/** 할인율(%) — 할인이 아니면 0. */
export function productDiscountPercent(item: ProductPriceSource): number {
  if (!hasProductDiscount(item)) return 0;
  const price = Number(item.it_price ?? 0);
  const cust = Number(item.it_cust_price ?? 0);
  return Math.round(((cust - price) / cust) * 100);
}

/** 가격 칸 글자: 전화문의면 "전화문의", 아니면 원 단위 가격. */
export function formatProductPrice(item: ProductPriceSource, price: number | null | undefined = item.it_price): string {
  return isTelInquiry(item) ? "전화문의" : formatPrice(price);
}
