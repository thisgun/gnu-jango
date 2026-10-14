import { apiClient } from "@/lib/api";
import { apiUrl } from "@/lib/config";
import { fetchApiData, validateApiData } from "@/lib/api-response";
import { publicSettingsSchema, type PublicSettings } from "@/lib/schemas";
import { currentBootstrapScope, getPageBootstrap } from "./page-bootstrap";

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

/** The page and the community rail both read these switches — share one request for a minute. */
const CLIENT_SETTINGS_TTL_MS = 60_000;
let clientSettings: { at: number; request: Promise<PublicSettings> } | null = null;

export function getClientPublicSettings(): Promise<PublicSettings> {
  const now = Date.now();
  if (clientSettings && now - clientSettings.at < CLIENT_SETTINGS_TTL_MS) {
    return clientSettings.request;
  }
  const scope = currentBootstrapScope();
  const source = scope
    ? getPageBootstrap(scope).then(payload => ({ data: payload.settings }))
    : apiClient.get<unknown>("/settings");
  const request = source
    .then((response) => {
      const settings = validateApiData(response.data, publicSettingsSchema, DEFAULT_PUBLIC_SETTINGS);
      // A response that failed validation falls back to the defaults; don't keep that for the next callers.
      if (settings === DEFAULT_PUBLIC_SETTINGS && clientSettings === entry) clientSettings = null;
      return settings;
    });
  const entry = { at: now, request };
  clientSettings = entry;
  // A failed request is not reused: the next caller asks again.
  request.catch(() => {
    if (clientSettings === entry) clientSettings = null;
  });
  return request;
}
