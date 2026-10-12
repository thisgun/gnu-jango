"use client";

import Image from "next/image";
import type { ShopCartItem } from "@/lib/api";
import { getShopCartShippingPaymentLabel } from "@/lib/shop-shipping-label";
import { formatCartOption, formatPrice } from "@/lib/utils";
import {
  cartItemLineTotal,
  cartItemUnitPrice,
} from "./orderPricingHelpers";

export function OrderItemsSummary({ items }: { items: ShopCartItem[] }) {
  return (
    <section className="box-border w-full min-w-0 rounded-lg border p-4 sm:p-6">
      <h2 className="mb-4 text-lg font-bold">주문 상품</h2>
      <div className="space-y-3">
        {items.map((item) => (
          <div key={item.ct_id} className="flex min-w-0 items-center gap-3">
            <div className="relative h-14 w-14 flex-shrink-0 overflow-hidden rounded-md bg-muted">
              {item.image_url ? (
                <Image
                  src={item.image_url}
                  alt={item.it_name}
                  fill
                  className="object-cover"
                  sizes="56px"
                />
              ) : (
                <div className="flex h-full items-center justify-center text-[10px] text-muted-foreground">
                  No Image
                </div>
              )}
            </div>
            <div className="min-w-0 flex-1">
              <p className="break-words text-sm font-medium">{item.it_name}</p>
              {item.ct_option && (
                <p className="break-words text-xs text-muted-foreground">
                  {formatCartOption(item.ct_option)}
                </p>
              )}
              <p className="text-xs text-muted-foreground">
                {formatPrice(cartItemUnitPrice(item))} x {item.ct_qty}개
              </p>
              <p
                className="text-xs text-muted-foreground"
                data-shop-order-send-cost-label="1"
              >
                배송비: {getShopCartShippingPaymentLabel(item, items)}
              </p>
            </div>
            <span className="ml-2 flex-shrink-0 text-sm font-bold">
              {formatPrice(cartItemLineTotal(item))}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}
