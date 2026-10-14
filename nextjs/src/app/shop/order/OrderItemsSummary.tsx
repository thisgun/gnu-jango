"use client";

import Image from "next/image";
import { ProductImageFallback } from "@/components/shop/ProductImageFallback";
import type { ShopCartItem } from "@/lib/api";
import { shouldBypassImageOptimization } from "@/lib/image";
import { formatPrice } from "@/lib/utils";
import { formatCartLineOption, groupCartItems } from "../cart/cartGroups";

/**
 * 주문 상품 — 영카트 orderform.sub.php 처럼 상품마다 한 칸(group by it_id)으로 묶고, 그 아래에 옵션 줄을
 * "옵션 수량개 (+옵션금액)" 으로 나열한다(print_item_options). 같은 상품의 옵션 줄이 여러 상품처럼 보이지 않게.
 */
export function OrderItemsSummary({ items }: { items: ShopCartItem[] }) {
  const groups = groupCartItems(items);
  return (
    <section className="shop-order-section shop-order-section--items box-border w-full min-w-0 rounded-lg border p-4 sm:p-6">
      <h2 className="mb-4 text-lg font-bold">주문 상품</h2>
      <div className="shop-order-items space-y-3">
        {groups.map((group) => {
          const item = group.item;
          return (
            <div key={group.itId} className="shop-order-item flex min-w-0 items-start gap-3">
              <div className="shop-order-item-thumb relative h-14 w-14 flex-shrink-0 overflow-hidden rounded-md bg-muted">
                {item.image_url ? (
                  <Image
                    src={item.image_url}
                    alt={item.it_name}
                    fill
                    className="object-cover"
                    sizes="64px"
                    unoptimized={shouldBypassImageOptimization(item.image_url)}
                  />
                ) : (
                  <ProductImageFallback compact />
                )}
              </div>
              <div className="min-w-0 flex-1">
                <p className="break-words text-sm font-medium">{item.it_name}</p>
                <ul className="shop-order-item-options mt-1 space-y-0.5">
                  {group.lines.map((line) => (
                    <li key={line.ct_id} className="break-words text-xs text-muted-foreground">
                      {formatCartLineOption(line)}
                    </li>
                  ))}
                </ul>
                <p className="mt-1 text-xs text-muted-foreground">
                  총수량 {group.totalQty}개 · 판매가 {formatPrice(group.salePrice)}
                </p>
                <p
                  className="text-xs text-muted-foreground"
                  data-shop-order-send-cost-label="1"
                >
                  배송비: {group.shippingLabel}
                </p>
              </div>
              <span className="shop-order-item-price ml-2 flex-shrink-0 text-sm font-bold">
                {formatPrice(group.subtotal)}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
