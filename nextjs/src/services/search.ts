import { apiClient } from "@/lib/api";
import { apiUrl } from "@/lib/config";
import { z } from "zod";
import { fetchApiData, fetchApiResult, validateApiData, type ApiResult } from "@/lib/api-response";
import {
  popularKeywordListSchema,
  searchResultListSchema,
  type PopularKeyword,
  type SearchResult,
} from "@/lib/schemas";

type SearchSiteOptions = {
  query: string;
  sfl?: string;
  boTable?: string;
  page?: number;
  perPage?: number;
  revalidate?: number;
};

export function searchSite(
  input: string | SearchSiteOptions,
  revalidate = 30
): Promise<ApiResult<SearchResult[]>> {
  const options = typeof input === "string" ? { query: input, revalidate } : input;
  const params = new URLSearchParams({ q: options.query.trim() });

  if (options.sfl) params.set("sfl", options.sfl);
  if (options.boTable) params.set("bo_table", options.boTable);
  if (options.page && options.page > 1) params.set("page", String(options.page));
  if (options.perPage) params.set("per_page", String(options.perPage));

  return fetchApiResult(apiUrl(`/search?${params.toString()}`), searchResultListSchema, {
    next: { revalidate: options.revalidate ?? revalidate },
  });
}

/** Popular search words from Gnuboard's short-term keyword list. */
export function getPopularKeywords(limit = 5, days = 3, revalidate = 300): Promise<PopularKeyword[]> {
  const params = new URLSearchParams({ limit: String(limit), days: String(days) });
  return fetchApiData(apiUrl(`/search/popular?${params.toString()}`), popularKeywordListSchema, [], {
    next: { revalidate },
  });
}

export async function getClientSearchSuggestions(
  query: string,
  limit = 8
): Promise<string[]> {
  const trimmed = query.trim();
  if (trimmed.length < 2) return [];

  const boundedLimit = Math.min(10, Math.max(1, Math.floor(limit)));
  const response = await apiClient.get<unknown>("/search", {
    params: {
      q: trimmed,
      sfl: "wr_subject",
      limit: boundedLimit,
      per_page: boundedLimit,
    },
  });
  const groups = validateApiData(response.data, searchResultListSchema, []);
  const suggestions: string[] = [];

  for (const group of groups) {
    for (const item of group.list.slice(0, 3)) {
      if (suggestions.length >= boundedLimit) return suggestions;
      if (item.wr_subject) suggestions.push(item.wr_subject);
    }
  }

  return suggestions;
}

export const unifiedSearchSchema = z.object({
  query: z.string(),
  results: z.array(z.object({
    type: z.enum(["post", "product", "document"]),
    id: z.string(),
    title: z.string(),
    url: z.string().refine((value) => value.startsWith("/") && !value.startsWith("//") && !/[\\\u0000-\u001f]/.test(value)),
    snippet: z.string(),
    score: z.number(),
    click_token: z.string(),
    price: z.number().optional(),
    bo_subject: z.string().optional(),
  })),
});

export type UnifiedSearchResult = z.infer<typeof unifiedSearchSchema>["results"][number];
export type SearchKind = "all" | "post" | "product" | "document";

export async function searchUnified(query: string, type: SearchKind, page = 1) {
  const response = await apiClient.get<unknown>("/search/unified", { params: { q: query, type, page, limit: 20 } });
  return { ...unifiedSearchSchema.parse(response.data), meta: response.meta };
}

export function recordSearchClick(token: string) {
  if (!token || (typeof navigator !== "undefined" && navigator.doNotTrack === "1")) return;
  // Logging must not delay navigation. Keepalive lets an in-flight request finish
  // when the next page requires a full document navigation in the Django theme.
  void apiClient.post("/search/click", { token }, { keepalive: true }).catch(() => undefined);
}
