import { apiClient } from "@/lib/api";
import { validateApiData } from "@/lib/api-response";
import {
  notificationListSchema,
  notificationReadSchema,
  type NotificationItem,
} from "@/lib/schemas";

export interface NotificationSummary {
  count: number;
  items: NotificationItem[];
}

export async function getNotifications(): Promise<NotificationSummary> {
  const params = {
    unread_only: 1,
    per_page: 30,
  };

  const response = await apiClient.get<unknown>("/notifications", { params });
  const items = validateApiData(response.data, notificationListSchema, []);

  return {
    count: response.meta?.total ?? items.length,
    items,
  };
}

export async function markNotificationsRead(): Promise<string | null> {
  const response = await apiClient.post<unknown>("/notifications/read-all");
  const data = validateApiData(response.data, notificationReadSchema, {});

  return data.read_at ?? new Date().toISOString();
}

export type { NotificationItem };
