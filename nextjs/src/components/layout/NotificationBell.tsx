"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Bell } from "lucide-react";
import { useAuthStore } from "@/store/auth";
import { formatDate } from "@/lib/utils";
import { g5ShortHref } from "@/lib/g5-short-url";
import {
  getNotifications,
  markNotificationsRead,
  type NotificationItem,
} from "@/services/notifications";

const POLL_INTERVAL = 60_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringFromData(data: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = data[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return "";
}

function safeNotificationHref(value: string): string | null {
  const raw = value.trim();
  if (!raw || /[\u0000-\u001F\u007F]/.test(raw)) return null;
  if (raw.startsWith("/") && !raw.startsWith("//")) {
    return g5ShortHref(raw);
  }
  if (typeof window === "undefined") return null;

  try {
    const url = new URL(raw, window.location.origin);
    if (url.origin !== window.location.origin) return null;
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return g5ShortHref(`${url.pathname}${url.search}${url.hash}` || "/");
  } catch {
    return null;
  }
}

function notificationHref(notification: NotificationItem): string | null {
  if (!isRecord(notification.nt_data)) return null;

  const directHref = stringFromData(notification.nt_data, ["href", "url", "link"]);
  if (directHref) {
    return safeNotificationHref(directHref);
  }

  const boTable = stringFromData(notification.nt_data, ["bo_table", "boTable"]);
  const postId = stringFromData(notification.nt_data, ["post_id", "postId", "wr_id", "wrId"]);
  if (boTable && postId) {
    return g5ShortHref(`/boards/${boTable}/${postId}`);
  }

  return null;
}

export function NotificationBell() {
  const { user } = useAuthStore();
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const fetchNotifications = useCallback(async () => {
    if (!user) return;
    try {
      const summary = await getNotifications();
      setNotifications(summary.items);
      setCount(summary.count);
    } catch {
      // The header should stay usable even if notifications are temporarily unavailable.
    }
  }, [user]);

  useEffect(() => {
    if (!user) {
      setNotifications([]);
      setCount(0);
      return;
    }
    fetchNotifications();
    const interval = setInterval(fetchNotifications, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [user, fetchNotifications]);

  useEffect(() => {
    const handler = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const handleMarkAllRead = async () => {
    try {
      await markNotificationsRead();
      setNotifications([]);
      setCount(0);
    } catch {
      // Keep the current list visible if the server did not accept the update.
    }
  };

  if (!user) return null;

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="relative flex h-9 w-9 items-center justify-center rounded-md transition-colors hover:bg-accent"
        aria-label="알림"
        aria-expanded={open}
      >
        <Bell className="h-5 w-5" />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-bold text-destructive-foreground">
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-2 w-80 rounded-lg border bg-popover shadow-lg">
          <div className="flex items-center justify-between border-b px-4 py-3">
            <h3 className="text-sm font-semibold">알림</h3>
            {count > 0 && (
              <button
                type="button"
                onClick={handleMarkAllRead}
                className="text-xs text-primary hover:underline"
              >
                모두 읽음
              </button>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">
                새로운 알림이 없습니다.
              </div>
            ) : (
              notifications.map((notification) => {
                const href = notificationHref(notification);
                const content = (
                  <>
                    <p className="text-sm font-medium">
                      {notification.nt_title || "알림"}
                    </p>
                    <p className="line-clamp-2 text-xs text-muted-foreground">
                      {notification.nt_body}
                    </p>
                    <p className="text-xs text-muted-foreground/70">
                      {formatDate(notification.nt_sent_at)}
                    </p>
                  </>
                );
                const className =
                  "flex flex-col gap-1 border-b px-4 py-3 transition-colors last:border-b-0";

                return href ? (
                  <a
                    key={notification.nt_id}
                    href={href}
                    onClick={() => setOpen(false)}
                    className={`${className} hover:bg-accent/50`}
                  >
                    {content}
                  </a>
                ) : (
                  <div key={notification.nt_id} className={className}>
                    {content}
                  </div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
