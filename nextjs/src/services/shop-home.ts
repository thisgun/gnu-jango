import { z } from "zod";
import { getPageBootstrap } from "./page-bootstrap";
import {
  boardSchema, publicSettingsSchema, shopBannerListSchema, shopCategorySchema,
  shopPopupListSchema, shopProductListSchema, shopReviewListSchema, writePostListSchema,
} from "@/lib/schemas";
import { shopHomeDisplaySchema } from "@/lib/shop-display";

const shopHomeSchema = z.object({
  settings: publicSettingsSchema,
  categories: shopCategorySchema.array(),
  banners: shopBannerListSchema,
  popups: shopPopupListSchema,
  products: z.object({
    type1: shopProductListSchema, type2: shopProductListSchema, type3: shopProductListSchema,
    type4: shopProductListSchema, type5: shopProductListSchema,
  }),
  /** 섹션별 출력 여부 · 칸 수 · 표시 수(관리자 쇼핑몰 초기화면 진열). 예전 응답에는 없어 기본값. */
  display: shopHomeDisplaySchema,
  catalogPreview: shopProductListSchema.optional().default([]),
  reviews: shopReviewListSchema,
  noticeBoard: boardSchema.nullable(),
  noticePosts: writePostListSchema,
});

export function getShopHomeData() {
  return getPageBootstrap("shop").then(payload => shopHomeSchema.parse(payload));
}
