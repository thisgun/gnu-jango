import type { ZodType } from "zod";
import { apiClient, type ShopReviewSummary } from "@/lib/api";
import { validateApiData, type ApiMeta } from "@/lib/api-response";
import { shopReviewSummarySchema } from "@/lib/schemas";

/*
 * 사용후기 · 상품문의 전체 목록(/shop/reviews · /shop/qas)이 함께 쓰는 목록 읽기.
 * services/shop 의 getShopReviews · getShopQas 와 같은 요청에 레퍼런스 계약의 검색 항목(sfl — 그누보드
 * itemuselist · itemqalist 의 i.it_name · r.is_subject …)을 더한다. 지금 이 앱의 API 는 sfl 을 읽지 않고
 * q 하나로 상품명 · 제목 · 내용을 함께 찾으므로, API 가 sfl 을 받게 되면 이 화면은 고칠 것이 없다.
 */

export interface ShopBoardListParams {
  page: number;
  perPage: number;
  q?: string;
  sfl?: string;
}

export interface ShopBoardListResult<T> {
  items: T[];
  meta?: ApiMeta;
}

/** 주소의 ?page= — 숫자가 아니거나 1보다 작으면 1쪽. */
export function parseListPage(value: string | null): number {
  const page = Number.parseInt(value || "", 10);
  return Number.isFinite(page) && page > 0 ? page : 1;
}

export async function fetchShopBoardList<T>(
  path: string,
  schema: ZodType<T[]>,
  { page, perPage, q, sfl }: ShopBoardListParams
): Promise<ShopBoardListResult<T>> {
  const response = await apiClient.get<unknown>(path, {
    params: {
      page,
      per_page: perPage,
      q: q || undefined,
      sfl: q && sfl ? sfl : undefined,
    },
  });

  return {
    items: validateApiData(response.data, schema, []),
    meta: response.meta,
  };
}

/** 승인된 사용후기 전체의 건수 · 평균(사용후기 목록의 "전체 N건 · 평균 N.N★"). */
export async function fetchShopReviewOverallSummary(): Promise<ShopReviewSummary | null> {
  const response = await apiClient.get<unknown>("/shop/reviews/summary");
  const parsed = shopReviewSummarySchema.safeParse(response.data);

  return parsed.success ? parsed.data : null;
}
