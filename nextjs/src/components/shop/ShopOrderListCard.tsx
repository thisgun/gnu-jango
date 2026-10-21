"use client";

import Image from "next/image";
import { G5Link as Link } from "@/components/ui/g5-link";
import { ProductImageFallback } from "@/components/shop/ProductImageFallback";
import type { ShopOrder } from "@/lib/api";
import { shouldBypassImageOptimization } from "@/lib/image";
import { ORDER_STATUS_BADGE_CLASS, orderStatusLabel } from "@/lib/order-status";
import { cn, formatDateTime, formatPrice } from "@/lib/utils";
import { ChevronRight } from "lucide-react";

// 상태 라벨은 주문 상세·마이페이지와 같은 표(영카트 orderinquiry.sub.php)를 쓴다.
function StatusBadge({ status }: { status: string }) {
  const { label, tone } = orderStatusLabel(status);

  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        ORDER_STATUS_BADGE_CLASS[tone]
      )}
    >
      {label}
    </span>
  );
}

function orderListPrice(order: ShopOrder) {
  return (
    order.od_list_price ??
    order.od_order_price ??
    Math.max(
      0,
      (order.od_cart_price ?? 0) +
        (order.od_send_cost ?? 0) +
        (order.od_send_cost2 ?? 0)
    )
  );
}

function orderMisuPrice(order: ShopOrder) {
  return order.od_misu ?? order.od_misu_price ?? 0;
}

export function ShopOrderListCard({ order }: { order: ShopOrder }) {
  const firstItem = order.items?.[0];
  const itemCount = order.od_cart_count ?? order.item_count ?? order.items?.length ?? 0;
  const itemTitle = firstItem
    ? `${firstItem.it_name}${itemCount > 1 ? ` 외 ${itemCount - 1}건` : ""}`
    : `상품 ${itemCount.toLocaleString()}건`;
  const dateText = order.od_time || order.od_receipt_time;
  const listPrice = orderListPrice(order);
  const misuPrice = orderMisuPrice(order);

  return (
    // order-card · -thumb · -body · -amounts · -go: 레퍼런스와 같은 손잡이 — solune-theme.internal-pages.css 가
    // 쇼핑몰 주문 목록과 마이페이지 주문 목록을 같은 격자 카드로 그린다.
    <Link
      href={`/shop/orders/${order.od_id}`}
      className="order-card flex gap-4 rounded-lg border p-4 transition-colors hover:bg-accent/50 sm:p-5"
    >
      <div className="order-card-thumb relative hidden h-16 w-16 shrink-0 overflow-hidden rounded-md bg-muted sm:block">
        {firstItem?.image_url ? (
          <Image
            src={firstItem.image_url}
            alt={firstItem.it_name}
            fill
            className="object-cover"
            sizes="64px"
            unoptimized={shouldBypassImageOptimization(firstItem.image_url)}
          />
        ) : (
          <ProductImageFallback compact />
        )}
      </div>

      <div className="order-card-body min-w-0 flex-1 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-sm font-semibold">{order.od_id}</span>
          <StatusBadge status={order.od_status} />
          <span className="text-xs text-muted-foreground">
            상품수 {itemCount.toLocaleString()}개
          </span>
        </div>

        <div className="space-y-1">
          <p className="truncate text-sm font-medium">{itemTitle}</p>
          <p className="text-xs text-muted-foreground">
            주문일시: {formatDateTime(dateText) || "-"}
          </p>
        </div>

        <div className="order-card-amounts grid gap-2 text-xs sm:grid-cols-3">
          <div className="rounded-md bg-muted/35 p-2">
            <p className="text-muted-foreground">주문금액</p>
            <p className="mt-0.5 font-semibold">{formatPrice(listPrice)}</p>
          </div>
          <div className="rounded-md bg-muted/35 p-2">
            <p className="text-muted-foreground">입금액</p>
            <p className="mt-0.5 font-semibold">
              {formatPrice(order.od_receipt_price)}
            </p>
          </div>
          <div className="rounded-md bg-muted/35 p-2">
            <p className="text-muted-foreground">미입금액</p>
            <p
              className={cn(
                "mt-0.5 font-semibold",
                misuPrice > 0 && "text-red-600"
              )}
            >
              {formatPrice(misuPrice)}
            </p>
          </div>
        </div>
      </div>

      <div className="order-card-go flex shrink-0 items-center">
        <ChevronRight className="h-5 w-5 text-muted-foreground" />
      </div>
    </Link>
  );
}
