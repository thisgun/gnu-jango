import { z } from "zod";
import { getPageBootstrap } from "./page-bootstrap";
import {
  boardSchema, publicSettingsSchema, shopBannerListSchema, shopCategorySchema,
  shopPopupListSchema, shopProductListSchema, shopReviewListSchema, writePostListSchema,
} from "@/lib/schemas";

const shopHomeSchema = z.object({
  settings: publicSettingsSchema,
  categories: shopCategorySchema.array(),
  banners: shopBannerListSchema,
  popups: shopPopupListSchema,
  products: z.object({
    type1: shopProductListSchema, type2: shopProductListSchema, type3: shopProductListSchema,
    type4: shopProductListSchema, type5: shopProductListSchema,
  }),
  reviews: shopReviewListSchema,
  noticeBoard: boardSchema.nullable(),
  noticePosts: writePostListSchema,
});

export function getShopHomeData() {
  return getPageBootstrap("shop").then(payload => shopHomeSchema.parse(payload));
}
