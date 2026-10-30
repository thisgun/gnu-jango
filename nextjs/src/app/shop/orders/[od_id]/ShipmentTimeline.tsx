"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import type { ShopShipmentTracking } from "@/lib/api";
import { cn, formatDateTime } from "@/lib/utils";

/** 처음에 보여 줄 이벤트 수 — 나머지는 '이전 내역 보기'로 펼친다. */
const VISIBLE_EVENTS = 5;

interface ShipmentTimelineProps {
  tracking: ShopShipmentTracking;
}

/**
 * 배송조회(Delivery Tracker) 결과: 현재 상태와 배송 진행 내역(최신이 위). 배송 조회 링크는
 * 송장 정보 칸에 그대로 두고, 이 타임라인은 조회 결과가 있을 때만 그 아래에 붙는다.
 */
export function ShipmentTimeline({ tracking }: ShipmentTimelineProps) {
  const [expanded, setExpanded] = useState(false);
  const events = tracking.events ?? [];
  const shown = expanded ? events : events.slice(0, VISIBLE_EVENTS);
  const hidden = events.length - shown.length;
  const deliveredAt = tracking.delivered ? formatDateTime(tracking.delivered_at) : "";
  const checkedAt = formatDateTime(tracking.last_checked_at);

  return (
    <div className="shop-order-tracking mt-3 border-t pt-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={tracking.delivered ? "default" : "secondary"}>
          {tracking.status_label || "배송 조회 중"}
        </Badge>
        {deliveredAt && <span className="text-xs text-muted-foreground">배송완료 {deliveredAt}</span>}
        {checkedAt && <span className="ml-auto text-xs text-muted-foreground">{checkedAt} 조회 기준</span>}
      </div>
      {shown.length > 0 && (
        <ol className="mt-3" aria-label="배송 진행 내역">
          {shown.map((event, index) => {
            const time = formatDateTime(event.time);
            const isLatest = index === 0;
            return (
              <li key={`${event.time}-${event.status}-${index}`} className="flex gap-3">
                <span aria-hidden="true" className="flex w-3 flex-col items-center">
                  <span
                    className={cn(
                      "mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full",
                      isLatest ? "bg-primary ring-4 ring-primary/20" : "bg-muted-foreground/40"
                    )}
                  />
                  {index < shown.length - 1 && <span className="my-1 w-px flex-1 bg-border" />}
                </span>
                <div className="min-w-0 flex-1 pb-3">
                  <p className="flex flex-wrap items-baseline gap-x-2 text-sm">
                    <span className={cn("font-medium", isLatest && "text-primary")}>{event.status_label}</span>
                    {event.location && <span className="text-xs text-muted-foreground">{event.location}</span>}
                  </p>
                  {event.description && (
                    <p className="break-words text-xs text-muted-foreground">{event.description}</p>
                  )}
                  {time && (
                    <time dateTime={event.time} className="text-xs text-muted-foreground">
                      {time}
                    </time>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
      {(hidden > 0 || expanded) && events.length > VISIBLE_EVENTS && (
        <button
          type="button"
          className="text-xs text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "최근 내역만 보기" : `이전 내역 ${hidden}건 더 보기`}
        </button>
      )}
    </div>
  );
}
