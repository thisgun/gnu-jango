import { apiClient } from "@/lib/api";
import { validateApiData } from "@/lib/api-response";
import { contentDataSchema, type ContentData } from "@/lib/schemas";

export async function getClientContent(coId: string): Promise<ContentData | null> {
  const response = await apiClient.get<unknown>(`/content/${coId}`);
  return validateApiData(response.data, contentDataSchema.nullable(), null);
}

export async function getClientContentBySeo(slug: string): Promise<ContentData | null> {
  const response = await apiClient.get<unknown>(`/content/seo/${encodeURIComponent(slug)}`);
  return validateApiData(response.data, contentDataSchema.nullable(), null);
}
