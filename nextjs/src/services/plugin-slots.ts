import { z } from "zod";
import { apiClient } from "@/lib/api";

// GET /api/v1/plugins/slots?name=... (gnu_jango/plugins/slots.py): widgets as plain data, never HTML.
const actionSchema = z.object({
  label: z.string(),
  method: z.enum(["GET", "POST"]),
  url: z.string(),
  primary: z.boolean(),
});

const widgetSchema = z.object({
  plugin: z.string(),
  title: z.string(),
  body: z.string(),
  stats: z.array(z.object({ label: z.string(), value: z.string() })),
  actions: z.array(actionSchema),
});

const slotSchema = z.object({ name: z.string(), widgets: z.array(widgetSchema) });

export type PluginWidget = z.infer<typeof widgetSchema>;
export type PluginWidgetAction = z.infer<typeof actionSchema>;

const API_PREFIX = "/api/v1/";

export async function fetchPluginSlot(name: string): Promise<PluginWidget[]> {
  const response = await apiClient.get<unknown>("/plugins/slots", { params: { name } });
  const parsed = slotSchema.safeParse(response.data);
  return parsed.success ? parsed.data.widgets : [];
}

/** The API path a POST action calls ("/api/v1/plugins/x" → "/plugins/x"), or null when it is not an API call. */
export function pluginActionApiPath(action: PluginWidgetAction): string | null {
  if (action.method !== "POST" || !action.url.startsWith(API_PREFIX)) return null;
  return `/${action.url.slice(API_PREFIX.length)}`;
}

export async function runPluginAction(action: PluginWidgetAction): Promise<void> {
  const path = pluginActionApiPath(action);
  if (!path) throw new Error("이 동작은 실행할 수 없습니다.");
  await apiClient.post<unknown>(path);
}
