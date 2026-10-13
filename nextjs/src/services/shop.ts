import { apiUrl } from "@/lib/config";
import { apiClient } from "@/lib/api";
import {
  fetchApiData,
  fetchApiResult,
  validateApiData,
  type ApiMeta,
  type ApiResult,
} from "@/lib/api-response";
import {
  shopCategoryProductPageSchema,
  shopCategorySchema,
  shopBannerListSchema,
  shopNaverPayConfigSchema,
  shopNaverPayOrderResponseSchema,
  shopNaverPayWishResponseSchema,
  shopPolicySchema,
  shopPopupListSchema,
  shopQaSchema,
  shopProductListSchema,
  shopProductSchema,
  shopQaListSchema,
  shopReviewListSchema,
  shopReviewSchema,
  shopReviewSummarySchema,
  shopShippingQuoteSchema,
  type ShopCategoryProductPage,
} from "@/lib/schemas";
import type {
  ShopCategory,
  ShopBanner,
  ShopNaverPayConfig,
  ShopNaverPayOrderRequest,
  ShopNaverPayOrderResponse,
  ShopNaverPayWishResponse,
  ShopPolicy,
  ShopPopup,
  ShopProduct,
  ShopQA,
  ShopReview,
  ShopReviewSummary,
  ShopShippingQuote,
} from "@/lib/api";

export type ShopProductParams = Record<string, string | number | undefined>;

const FALLBACK_SHIPPING_COST = 3000;
const FALLBACK_FREE_THRESHOLD = 50000;

export interface ShopProductListResult {
  products: ShopProduct[];
  meta?: ApiMeta;
}

export function getShopCategories(revalidate = 300): Promise<ShopCategory[]> {
  return fetchApiData(apiUrl("/shop/categories"), shopCategorySchema.array(), [], {
    next: { revalidate },
  });
}

export function getShopCategoriesResult(init?: RequestInit): Promise<ApiResult<ShopCategory[]>> {
  return fetchApiResult(apiUrl("/shop/categories"), shopCategorySchema.array(), init);
}

export function getShopBanners(
  params: { position?: string; device?: "pc" | "mobile" | "all" } = {},
  revalidate = 300
): Promise<ShopBanner[]> {
  const query = new URLSearchParams();
  query.set("position", params.position || "메인");
  query.set("device", params.device || "all");
  const suffix = `?${query.toString()}`;

  return fetchApiData(apiUrl(`/shop/banners${suffix}`), shopBannerListSchema, [], {
    next: { revalidate },
  });
}

export function getShopBannersResult(
  params: { position?: string; device?: "pc" | "mobile" | "all" } = {},
  init?: RequestInit
): Promise<ApiResult<ShopBanner[]>> {
  const query = new URLSearchParams();
  query.set("position", params.position || "메인");
  query.set("device", params.device || "all");

  return fetchApiResult(apiUrl(`/shop/banners?${query.toString()}`), shopBannerListSchema, init);
}

export function getShopPopups(
  params: { device?: "pc" | "mobile" | "all"; limit?: number } = {},
  revalidate = 60
): Promise<ShopPopup[]> {
  const query = new URLSearchParams();
  query.set("device", params.device || "all");
  query.set("limit", String(params.limit || 5));
  const suffix = `?${query.toString()}`;

  return fetchApiData(apiUrl(`/shop/popups${suffix}`), shopPopupListSchema, [], {
    next: { revalidate },
  });
}

export function getShopProducts(
  params: Record<string, string | number | undefined>,
  revalidate = 30
): Promise<ShopProduct[]> {
  const query = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined) query.set(key, String(value));
  });

  const suffix = query.toString() ? `?${query.toString()}` : "";

  return fetchApiData(apiUrl(`/shop/products${suffix}`), shopProductListSchema, [], {
    next: { revalidate },
  });
}

export async function getShopProduct(
  itId: string,
  revalidate = 60
): Promise<ShopProduct | null> {
  const result = await getShopProductResult(itId, revalidate);

  return result.ok ? result.data : null;
}

export function getShopProductResult(
  itId: string,
  revalidate = 60
): Promise<ApiResult<ShopProduct>> {
  return fetchApiResult(apiUrl(`/shop/products/${itId}`), shopProductSchema, {
    next: { revalidate },
  });
}

export async function getShopProductBySeo(
  slug: string,
  revalidate = 60
): Promise<ShopProduct | null> {
  const result = await getShopProductBySeoResult(slug, revalidate);

  return result.ok ? result.data : null;
}

export function getShopProductBySeoResult(
  slug: string,
  revalidate = 60
): Promise<ApiResult<ShopProduct>> {
  return fetchApiResult(
    apiUrl(`/shop/products/seo/${encodeURIComponent(slug)}`),
    shopProductSchema,
    { next: { revalidate } }
  );
}

export async function getShopProductList(
  params: ShopProductParams
): Promise<ShopProductListResult> {
  const response = await apiClient.get<unknown>("/shop/products", { params });
  const parsed = shopProductListSchema.safeParse(response.data);

  if (!parsed.success) {
    console.error(
      "[shop.products] API response schema validation failed",
      parsed.error.issues
    );
    throw new Error("쇼핑 상품 응답 형식이 올바르지 않습니다.");
  }

  return {
    products: parsed.data,
    meta: response.meta,
  };
}

export async function getShopCategoryProductPage(
  caId: string,
  params: ShopProductParams
): Promise<ShopCategoryProductPage | null> {
  const response = await apiClient.get<unknown>(
    `/shop/categories/${encodeURIComponent(caId)}`,
    { params }
  );
  const parsed = shopCategoryProductPageSchema.safeParse(response.data);

  return parsed.success ? parsed.data : null;
}

function shippingRules(policy?: ShopPolicy | null) {
  return [...(policy?.shipping_rules ?? [])]
    .filter((rule) => Number(rule.limit) > 0)
    .sort((a, b) => Number(a.limit) - Number(b.limit));
}

export function getShopShippingFreeThreshold(policy?: ShopPolicy | null): number {
  if (!policy) return FALLBACK_FREE_THRESHOLD;
  if (policy.send_cost_case === "무료") return 0;

  const rules = shippingRules(policy);
  if (rules.length > 0) {
    return Math.max(...rules.map((rule) => Number(rule.limit)));
  }

  return Math.max(0, Number(policy.free_threshold || 0));
}

export function getShopShippingFreeRemaining(
  subtotal: number,
  policy?: ShopPolicy | null
): number {
  const threshold = getShopShippingFreeThreshold(policy);
  if (threshold <= 0) return 0;

  return Math.max(0, threshold - Math.max(0, Math.floor(subtotal)));
}

export function estimateShopShippingCost(
  subtotal: number,
  policy?: ShopPolicy | null
): number {
  const amount = Math.max(0, Math.floor(subtotal));
  if (amount <= 0) return 0;

  if (!policy) {
    return amount >= FALLBACK_FREE_THRESHOLD ? 0 : FALLBACK_SHIPPING_COST;
  }
  if (policy.send_cost_case === "무료") return 0;

  const rules = shippingRules(policy);
  if (rules.length > 0) {
    const matched = rules.find((rule) => amount < Number(rule.limit));
    return matched ? Math.max(0, Number(matched.cost || 0)) : 0;
  }

  const baseCost = Math.max(0, Number(policy.base_shipping_cost || 0));
  const threshold = Math.max(0, Number(policy.free_threshold || 0));

  if (baseCost <= 0 && threshold <= 0) return 0;
  if (threshold > 0 && amount >= threshold) return 0;

  return baseCost > 0 ? baseCost : FALLBACK_SHIPPING_COST;
}

export async function getShopPolicy(revalidate = 300): Promise<ShopPolicy | null> {
  const result = await fetchApiResult(apiUrl("/shop/policy"), shopPolicySchema, {
    next: { revalidate },
  });

  return result.ok ? result.data : null;
}

export async function getShopNaverPayConfig(): Promise<ShopNaverPayConfig | null> {
  try {
    const response = await apiClient.get<unknown>("/shop/naverpay");
    const parsed = shopNaverPayConfigSchema.safeParse(response.data);
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

export async function registerShopNaverPayOrder(
  payload: ShopNaverPayOrderRequest
): Promise<ShopNaverPayOrderResponse> {
  const response = await apiClient.post<unknown>("/shop/naverpay/order", payload);
  const parsed = shopNaverPayOrderResponseSchema.safeParse(response.data);

  if (!parsed.success) {
    throw new Error("네이버페이 주문 등록 응답 형식이 올바르지 않습니다.");
  }

  return parsed.data;
}

export async function registerShopNaverPayWish(
  payload: { it_id?: string; it_ids?: string[] }
): Promise<ShopNaverPayWishResponse> {
  const response = await apiClient.post<unknown>("/shop/naverpay/wish", payload);
  const parsed = shopNaverPayWishResponseSchema.safeParse(response.data);

  if (!parsed.success) {
    throw new Error("네이버페이 찜 등록 응답 형식이 올바르지 않습니다.");
  }

  return parsed.data;
}

export async function getShopShippingQuote(params: {
  zip1?: string;
  zip2?: string;
  ct_ids?: string;
  direct?: string | number;
  sw_direct?: string | number;
} = {}): Promise<ShopShippingQuote | null> {
  try {
    const response = await apiClient.get<unknown>("/shop/shipping/quote", { params });
    const parsed = shopShippingQuoteSchema.safeParse(response.data);
    return parsed.success ? parsed.data : null;
  } catch {
    return null;
  }
}

export async function getShopProductReviews(
  itId: string,
  page = 1
): Promise<ShopReview[]> {
  const response = await apiClient.get<unknown>("/shop/reviews", {
    params: { it_id: itId, page },
  });

  return validateApiData(response.data, shopReviewListSchema, []);
}

export async function getShopProductReviewPage(
  itId: string,
  page = 1,
  focusIsId?: number
): Promise<ShopReviewListResult> {
  const response = await apiClient.get<unknown>("/shop/reviews", {
    params: { it_id: itId, page, per_page: 20, focus_is_id: focusIsId || undefined },
  });

  return {
    items: validateApiData(response.data, shopReviewListSchema, []),
    meta: response.meta,
  };
}

export async function getShopReviews(
  params: ShopReviewListParams = {}
): Promise<ShopReviewListResult> {
  const response = await apiClient.get<unknown>("/shop/reviews", {
    params: {
      page: params.page,
      per_page: params.perPage,
      q: params.q || undefined,
    },
  });

  return {
    items: validateApiData(response.data, shopReviewListSchema, []),
    meta: response.meta,
  };
}

export async function getShopProductReviewSummary(
  itId: string
): Promise<ShopReviewSummary | null> {
  const response = await apiClient.get<unknown>("/shop/reviews/summary", {
    params: { it_id: itId },
  });
  const parsed = shopReviewSummarySchema.safeParse(response.data);

  return parsed.success ? parsed.data : null;
}

export interface ShopReviewListParams {
  page?: number;
  perPage?: number;
  status?: "all" | "confirmed" | "pending";
  q?: string;
}

export interface ShopReviewListResult {
  items: ShopReview[];
  meta?: ApiMeta;
}

export interface ShopReviewPayload {
  is_subject: string;
  is_content: string;
  is_score: number;
}

function parseShopReview(data: unknown): ShopReview {
  const parsed = shopReviewSchema.safeParse(data);
  if (!parsed.success) {
    throw new Error("상품후기 응답 형식이 올바르지 않습니다.");
  }
  return parsed.data;
}

export async function getMyShopReviews(
  params: ShopReviewListParams = {}
): Promise<ShopReviewListResult> {
  const response = await apiClient.get<unknown>("/shop/reviews/mine", {
    params: {
      page: params.page,
      per_page: params.perPage,
      status: params.status === "all" ? undefined : params.status,
      q: params.q || undefined,
    },
  });

  return {
    items: validateApiData(response.data, shopReviewListSchema, []),
    meta: response.meta,
  };
}

export async function getShopReview(reviewId: string | number): Promise<ShopReview> {
  const response = await apiClient.get<unknown>(`/shop/reviews/${reviewId}`);
  return parseShopReview(response.data);
}

export async function updateShopReview(
  reviewId: string | number,
  payload: ShopReviewPayload
): Promise<ShopReview> {
  const response = await apiClient.patch<unknown>(`/shop/reviews/${reviewId}`, payload);
  return parseShopReview(response.data);
}

export function deleteShopReview(reviewId: string | number) {
  return apiClient.delete(`/shop/reviews/${reviewId}`);
}

export async function getShopProductQas(
  itId: string,
  page = 1
): Promise<ShopQA[]> {
  const response = await apiClient.get<unknown>("/shop/reviews/qna", {
    params: { it_id: itId, page },
  });

  return validateApiData(response.data, shopQaListSchema, []);
}

export async function getShopProductQaPage(
  itId: string,
  page = 1,
  focusIqId?: number
): Promise<ShopQaListResult> {
  const response = await apiClient.get<unknown>("/shop/reviews/qna", {
    params: {
      it_id: itId,
      page,
      per_page: 20,
      focus_iq_id: focusIqId || undefined,
    },
  });

  return {
    items: validateApiData(response.data, shopQaListSchema, []),
    meta: response.meta,
  };
}

export async function getShopQas(
  params: ShopQaListParams = {}
): Promise<ShopQaListResult> {
  const response = await apiClient.get<unknown>("/shop/reviews/qna", {
    params: {
      page: params.page,
      per_page: params.perPage,
      status: params.status === "all" ? undefined : params.status,
      q: params.q || undefined,
    },
  });

  return {
    items: validateApiData(response.data, shopQaListSchema, []),
    meta: response.meta,
  };
}

export interface ShopQaListParams {
  page?: number;
  perPage?: number;
  status?: "all" | "answered" | "unanswered";
  q?: string;
}

export interface ShopQaListResult {
  items: ShopQA[];
  meta?: ApiMeta;
}

export interface ShopQaPayload {
  iq_subject: string;
  iq_question: string;
  iq_secret?: boolean | number;
  iq_email?: string;
  iq_hp?: string;
}

function parseShopQa(data: unknown): ShopQA {
  const parsed = shopQaSchema.safeParse(data);
  if (!parsed.success) {
    throw new Error("상품문의 응답 형식이 올바르지 않습니다.");
  }
  return parsed.data;
}

export async function getMyShopQas(
  params: ShopQaListParams = {}
): Promise<ShopQaListResult> {
  const response = await apiClient.get<unknown>("/shop/reviews/qna/mine", {
    params: {
      page: params.page,
      per_page: params.perPage,
      status: params.status === "all" ? undefined : params.status,
      q: params.q || undefined,
    },
  });

  return {
    items: validateApiData(response.data, shopQaListSchema, []),
    meta: response.meta,
  };
}

export async function getShopQa(iqId: string | number): Promise<ShopQA> {
  const response = await apiClient.get<unknown>(`/shop/reviews/qna/${iqId}`);
  return parseShopQa(response.data);
}

export async function updateShopQa(
  iqId: string | number,
  payload: ShopQaPayload
): Promise<ShopQA> {
  const response = await apiClient.patch<unknown>(`/shop/reviews/qna/${iqId}`, payload);
  return parseShopQa(response.data);
}

export function deleteShopQa(iqId: string | number) {
  return apiClient.delete(`/shop/reviews/qna/${iqId}`);
}
