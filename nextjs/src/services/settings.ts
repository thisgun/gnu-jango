import { apiClient } from "@/lib/api";
import { apiUrl } from "@/lib/config";
import { fetchApiData, validateApiData } from "@/lib/api-response";
import { publicSettingsSchema, type PublicSettings } from "@/lib/schemas";

export const DEFAULT_PUBLIC_SETTINGS: PublicSettings = {
  cf_bbs_rewrite: 0,
  infinite_scroll: false,
  comment_editor: false,
  pwa_enabled: false,
};

export function getPublicSettings(revalidate = 60): Promise<PublicSettings> {
  return fetchApiData(apiUrl("/settings"), publicSettingsSchema, DEFAULT_PUBLIC_SETTINGS, {
    next: { revalidate },
  });
}

export async function getClientPublicSettings(): Promise<PublicSettings> {
  const response = await apiClient.get<unknown>("/settings");
  return validateApiData(response.data, publicSettingsSchema, DEFAULT_PUBLIC_SETTINGS);
}
