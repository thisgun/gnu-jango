import { z } from "zod";
import { shopListDisplaySchema } from "./shop-display";
import type {
  Board,
  BoardCategoryCounts,
  Comment,
  PostFile,
  RecentGroup,
  RecentItem,
  Poll,
  PollComment,
  PollSummary,
  QaConfig,
  QaItem,
  Scrap,
  FaqPageData,
  WritePost,
  Memo,
  MemberProfile,
  MyMemberDetails,
} from "@/lib/types";
import type { MenuItem } from "@/components/layout/menu";
import type {
  ShopCartItem,
  ShopCartResponse,
  ShopBanner,
  ShopCategory,
  ShopNaverPayConfig,
  ShopNaverPayOrderResponse,
  ShopNaverPayWishResponse,
  ShopOrder,
  ShopPolicy,
  ShopPopup,
  ShopProduct,
  ShopProductOption,
  ShopQA,
  ShopReview,
  ShopReviewScoreSummary,
  ShopReviewSummary,
  ShopShippingQuote,
  ShopShippingRule,
  ShopWishItem,
} from "@/lib/api";

const stringValue = z.preprocess(
  (value) => (value === null || value === undefined ? "" : value),
  z.coerce.string()
);

const optionalString = z.preprocess(
  (value) => (value === null || value === undefined ? undefined : value),
  z.coerce.string().optional()
);

const numberValue = z.preprocess(
  (value) => (value === null || value === undefined || value === "" ? 0 : value),
  z.coerce.number().catch(0)
);

const booleanValue = z.preprocess((value) => {
  if (value === "1" || value === 1 || value === true) return true;
  if (value === "0" || value === 0 || value === false) return false;
  return value;
}, z.coerce.boolean().catch(false));

export const memberProfileSchema = z
  .object({
    mb_id: stringValue,
    mb_nick: stringValue,
    mb_level: numberValue,
    mb_point: numberValue,
    mb_open: numberValue,
    mb_datetime: stringValue,
    mb_icon_path: optionalString,
    mb_homepage: optionalString,
    mb_profile: optionalString,
    reg_days: numberValue,
  })
  .passthrough() as unknown as z.ZodType<MemberProfile>;

export const myMemberDetailsSchema = z
  .object({
    mb_hp: stringValue,
    mb_tel: stringValue,
    mb_today_login: stringValue,
    mb_datetime: stringValue,
    mb_zip: stringValue,
    mb_addr1: stringValue,
    mb_addr2: stringValue,
    mb_addr3: stringValue,
  })
  .passthrough() as unknown as z.ZodType<MyMemberDetails>;

export const boardSchema = z
  .object({
    bo_table: stringValue,
    gr_id: stringValue,
    bo_subject: stringValue,
    bo_content: optionalString,
    bo_category_list: stringValue,
    bo_page_rows: numberValue,
    bo_gallery_cols: numberValue,
    bo_count_write: numberValue,
    bo_count_comment: numberValue,
    bo_use_dhtml_editor: numberValue,
  })
  .passthrough() as unknown as z.ZodType<Board>;

export const boardListSchema = z.array(boardSchema);

export const boardCategoryCountsSchema = z.object({
  counts: z.record(z.string(), numberValue).nullable(),
  reason: z.string().nullable(),
}) as unknown as z.ZodType<BoardCategoryCounts>;

const writePostShape = {
  wr_id: numberValue,
  wr_num: numberValue,
  wr_parent: numberValue,
  wr_is_comment: numberValue,
  ca_name: stringValue,
  wr_option: stringValue,
  wr_subject: stringValue,
  wr_content: stringValue,
  wr_seo_title: stringValue,
  wr_name: stringValue,
  wr_email: stringValue,
  wr_homepage: stringValue,
  wr_datetime: stringValue,
  wr_last: stringValue,
  wr_ip: stringValue,
  wr_comment: numberValue,
  wr_hit: numberValue,
  wr_good: numberValue,
  wr_nogood: numberValue,
  mb_id: stringValue,
  mb_nick: optionalString,
  mb_icon_path: optionalString,
  thumbnail: optionalString,
  is_notice: booleanValue.optional(),
  is_new: booleanValue.optional(),
  is_hot: booleanValue.optional(),
  is_secret: booleanValue.optional(),
  bo_use_good: numberValue.optional(),
  bo_use_nogood: numberValue.optional(),
  is_scrapped: booleanValue.optional(),
  scrap_id: numberValue.optional(),
};

const writePostObjectSchema = z.object(writePostShape).passthrough();

export const writePostSchema = writePostObjectSchema as unknown as z.ZodType<WritePost>;

export const writePostListSchema = z.array(writePostSchema);

export const postFileSchema = z
  .object({
    bf_no: numberValue,
    bo_table: stringValue,
    wr_id: numberValue,
    bf_source: stringValue,
    bf_file: stringValue,
    bf_download: numberValue,
    bf_content: stringValue,
    // bf_fileurl/bf_thumburl/bf_storage 는 백엔드 API 가 항상 내려보내지 않음.
    // 누락 시 zod parse 실패로 단건 게시글 fetch 가 null 반환 → notFound() 호출되는
    // 사고가 있어 optional 로 처리. UI 는 bf_url 우선 사용 (bf_fileurl 은 DB 원본).
    bf_fileurl: optionalString,
    bf_thumburl: optionalString,
    bf_storage: optionalString,
    bf_filesize: numberValue,
    bf_width: numberValue,
    bf_height: numberValue,
    bf_type: numberValue,
    bf_datetime: stringValue,
    bf_url: optionalString,
    bf_download_url: optionalString,
    bf_download_available: z.boolean().optional(),
  })
  .passthrough() as unknown as z.ZodType<PostFile>;

export const commentSchema = z
  .object({
    wr_id: numberValue,
    wr_parent: numberValue,
    wr_is_comment: numberValue,
    wr_comment: numberValue,
    wr_comment_reply: stringValue,
    wr_content: stringValue,
    wr_name: stringValue,
    mb_id: stringValue,
    wr_datetime: stringValue,
    wr_last: stringValue,
    wr_ip: stringValue,
    wr_option: stringValue,
    mb_nick: optionalString,
  })
  .passthrough() as unknown as z.ZodType<Comment>;

export const postNavItemSchema = z
  .object({
    wr_id: numberValue,
    wr_subject: stringValue,
    wr_seo_title: stringValue.optional(),
  })
  .passthrough();

export const postDetailSchema = writePostObjectSchema
  .extend({
    files: z.array(postFileSchema).optional(),
    comments: z.array(commentSchema).optional(),
    prev_post: postNavItemSchema.nullable().optional(),
    next_post: postNavItemSchema.nullable().optional(),
  })
  .passthrough();

export const menuItemSchema: z.ZodType<MenuItem> = z.lazy(() =>
  z
    .object({
      me_id: numberValue,
      me_code: stringValue,
      me_name: stringValue,
      me_link: stringValue,
      me_target: stringValue,
      children: z.array(menuItemSchema).optional(),
    })
    .passthrough()
) as z.ZodType<MenuItem>;

export const menuItemListSchema = z.array(menuItemSchema);

export const shopCategorySchema = z
  .object({
    ca_id: stringValue,
    ca_name: stringValue,
    ca_order: numberValue,
    item_count: numberValue.optional(),
  })
  .passthrough() as unknown as z.ZodType<ShopCategory>;

const shopProductNavItemSchema = z
  .object({
    it_id: stringValue,
    it_name: stringValue,
    it_seo_title: optionalString,
    image_url: optionalString,
  })
  .passthrough();

const shopProductInfoItemSchema = z
  .object({
    key: stringValue,
    title: stringValue,
    value: stringValue,
    example: optionalString,
  })
  .passthrough();

const shopProductOptionSchema = z
  .object({
    io_no: numberValue,
    it_id: optionalString,
    io_id: stringValue,
    io_type: numberValue,
    io_value: optionalString,
    io_price: numberValue,
    io_stock_qty: numberValue,
    io_noti_qty: numberValue.optional(),
    io_use: z.union([numberValue, stringValue]).optional(),
  })
  .passthrough() as unknown as z.ZodType<ShopProductOption>;

export const shopProductSchema = z
  .object({
    it_id: stringValue,
    ca_id: stringValue,
    ca_name: optionalString,
    it_name: stringValue,
    it_seo_title: optionalString,
    it_price: numberValue,
    it_basic_price: numberValue,
    it_cust_price: numberValue,
    it_point: numberValue,
    it_point_type: numberValue.optional(),
    it_stock_qty: numberValue,
    it_buy_min_qty: numberValue.optional(),
    it_buy_max_qty: numberValue.optional(),
    it_tel_inq: stringValue.optional(),
    it_soldout: stringValue,
    it_stock_sms: stringValue.optional(),
    stock_sms_privacy: optionalString,
    it_sc_type: numberValue.optional(),
    it_sc_method: numberValue.optional(),
    it_sc_price: numberValue.optional(),
    it_sc_minimum: numberValue.optional(),
    it_sc_qty: numberValue.optional(),
    it_type1: stringValue,
    it_type2: stringValue,
    it_type3: stringValue,
    it_type4: stringValue,
    it_type5: stringValue,
    has_coupon: z.boolean().optional(),
    it_content: optionalString,
    it_explan: optionalString,
    it_basic: optionalString,
    it_head_html: optionalString,
    it_tail_html: optionalString,
    it_info_gubun: optionalString,
    it_info_gubun_title: optionalString,
    it_info_title: optionalString,
    it_info_items: z.array(shopProductInfoItemSchema).optional(),
    image_url: stringValue,
    images: z.array(stringValue).optional(),
    options: z.array(shopProductOptionSchema).optional(),
    // Django returns null for a product without a primary category. Such products
    // are public and searchable, so normalize it to the existing optional shape.
    category: shopCategorySchema.nullish().transform((value) => value ?? undefined),
    prev_item: shopProductNavItemSchema.nullable().optional(),
    next_item: shopProductNavItemSchema.nullable().optional(),
  })
  .passthrough() as unknown as z.ZodType<ShopProduct>;

export const shopProductListSchema = z.array(shopProductSchema);

const paginationMetaSchema = z
  .object({
    total: numberValue,
    per_page: numberValue,
    current_page: numberValue,
    last_page: numberValue,
  })
  .passthrough();

export const shopCategoryProductPageSchema = z
  .object({
    category: shopCategorySchema,
    subcategories: z.array(shopCategorySchema).default([]),
    items: z.array(shopProductSchema).default([]),
    meta: paginationMetaSchema,
  })
  .passthrough();

export type ShopCategoryProductPage = z.infer<
  typeof shopCategoryProductPageSchema
>;

export const shopBannerSchema = z
  .object({
    bn_id: numberValue,
    bn_alt: stringValue,
    bn_url: stringValue,
    bn_position: stringValue,
    bn_device: stringValue,
    bn_border: numberValue,
    bn_new_win: numberValue,
    bn_order: numberValue,
    image_url: stringValue,
    hit_url: optionalString,
  })
  .passthrough() as unknown as z.ZodType<ShopBanner>;

export const shopBannerListSchema = z.array(shopBannerSchema);

export const shopPopupSchema = z
  .object({
    nw_id: numberValue,
    nw_division: stringValue,
    nw_device: stringValue,
    nw_begin_time: stringValue,
    nw_end_time: stringValue,
    nw_disable_hours: numberValue,
    nw_width: numberValue,
    nw_height: numberValue,
    nw_subject: stringValue,
    nw_content: stringValue,
    nw_content_text: stringValue,
    nw_content_html: numberValue,
  })
  .passthrough() as unknown as z.ZodType<ShopPopup>;

export const shopPopupListSchema = z.array(shopPopupSchema);

export const shopCartItemSchema = z
  .object({
    ct_id: stringValue,
    it_id: stringValue,
    it_name: stringValue,
    it_seo_title: optionalString,
    ct_price: numberValue,
    ct_qty: numberValue,
    ct_option: stringValue,
    io_type: numberValue.optional(),
    io_price: numberValue.optional(),
    ct_direct: numberValue.optional(),
    ct_send_cost: numberValue.optional(),
    it_sc_type: numberValue.optional(),
    it_sc_method: numberValue.optional(),
    it_sc_price: numberValue.optional(),
    it_sc_minimum: numberValue.optional(),
    it_sc_qty: numberValue.optional(),
    line_total: numberValue,
    it_basic_price: numberValue,
    it_stock_qty: numberValue,
    it_soldout: stringValue,
    it_use: stringValue.optional(),
    it_tel_inq: stringValue.optional(),
    image_url: stringValue,
  })
  .passthrough() as unknown as z.ZodType<ShopCartItem>;

export const shopCartResponseSchema = z
  .object({
    items: z.array(shopCartItemSchema).default([]),
    total_price: numberValue,
    total_qty: numberValue,
    send_cost: numberValue.optional(),
    shipping_cost: numberValue.optional(),
  })
  .passthrough() as unknown as z.ZodType<ShopCartResponse>;

export const shopNaverPayConfigSchema = z
  .object({
    enabled: z.boolean().default(false),
    reason: stringValue,
    test: z.boolean().default(false),
    mobile: z.boolean().default(false),
    shop_id: stringValue,
    button_key: stringValue,
    button_count_item: numberValue,
    button_count_cart: numberValue,
    script_url: stringValue,
    order_url: stringValue,
    wish_url: stringValue,
  })
  .passthrough() as unknown as z.ZodType<ShopNaverPayConfig>;

export const shopNaverPayOrderResponseSchema = z
  .object({
    order_id: stringValue,
    shop_id: stringValue,
    total_price: numberValue,
    redirect_url: stringValue,
  })
  .passthrough() as unknown as z.ZodType<ShopNaverPayOrderResponse>;

export const shopNaverPayWishResponseSchema = z
  .object({
    shop_id: stringValue,
    item_ids: z.array(stringValue).default([]),
    redirect_url: stringValue,
  })
  .passthrough() as unknown as z.ZodType<ShopNaverPayWishResponse>;

export const shopShippingRuleSchema = z
  .object({
    limit: numberValue,
    cost: numberValue,
  })
  .passthrough() as unknown as z.ZodType<ShopShippingRule>;

export const shopPolicySchema = z
  .object({
    de_admin_company_name: optionalString,
    de_admin_company_tel: optionalString,
    delivery_company: stringValue,
    send_cost_case: stringValue,
    send_cost_limit: stringValue,
    send_cost_list: stringValue,
    shipping_rules: z.array(shopShippingRuleSchema).default([]),
    base_shipping_cost: numberValue,
    free_threshold: numberValue,
    delivery_content: stringValue,
    delivery_content_text: stringValue,
    exchange_content: stringValue,
    exchange_content_text: stringValue,
    review_requires_completed_order: z.boolean().optional().default(false),
    review_requires_moderation: z.boolean().optional().default(false),
    point_use_enabled: z.boolean().optional().default(false),
    settle_min_point: numberValue.optional().default(0),
    settle_max_point: numberValue.optional().default(0),
    settle_point_unit: numberValue.optional().default(1),
  })
  .passthrough() as unknown as z.ZodType<ShopPolicy>;

export const shopShippingQuoteSchema = z
  .object({
    item_total: numberValue,
    cart_coupon: numberValue,
    zip1: stringValue,
    zip2: stringValue,
    base: numberValue,
    extra: numberValue,
    total: numberValue,
    free_threshold: numberValue,
    free_remaining: numberValue,
    policy: shopPolicySchema,
  })
  .passthrough() as unknown as z.ZodType<ShopShippingQuote>;

export const shopWishItemSchema = z
  .object({
    wi_id: stringValue,
    it_id: stringValue,
    it_name: stringValue,
    it_seo_title: optionalString,
    it_basic_price: numberValue,
    it_cust_price: numberValue,
    it_tel_inq: stringValue.optional(),
    it_soldout: stringValue.optional(),
    it_use: stringValue.optional(),
    it_stock_qty: numberValue.optional(),
    option_count: numberValue.optional(),
    can_add_cart: z.boolean().optional(),
    cart_block_reason: optionalString,
    image_url: stringValue,
    wi_time: stringValue,
  })
  .passthrough() as unknown as z.ZodType<ShopWishItem>;

export const shopWishItemListSchema = z.array(shopWishItemSchema);

const shopOrderItemSchema = z
  .object({
    ct_id: stringValue,
    it_id: stringValue,
    it_name: stringValue,
    it_seo_title: optionalString,
    ct_price: numberValue,
    ct_qty: numberValue,
    ct_point: numberValue.optional(),
    line_total: numberValue.optional(),
    line_point: numberValue.optional(),
    ct_option: stringValue,
    ct_status: stringValue,
    ct_stock_use: numberValue.optional(),
    io_type: numberValue.optional(),
    io_price: numberValue.optional(),
    ct_send_cost: numberValue.optional(),
    it_sc_type: numberValue.optional(),
    it_sc_method: numberValue.optional(),
    it_sc_price: numberValue.optional(),
    it_sc_minimum: numberValue.optional(),
    it_sc_qty: numberValue.optional(),
    image_url: optionalString,
  })
  .passthrough();

export const shopOrderSchema = z
  .object({
    od_id: stringValue,
    od_name: stringValue,
    od_tel: stringValue,
    od_hp: stringValue,
    od_zip: stringValue,
    od_addr1: stringValue,
    od_addr2: stringValue,
    od_addr3: stringValue,
    od_receipt_price: numberValue,
    od_send_cost: numberValue,
    od_cancel_price: numberValue.optional(),
    od_misu: numberValue.optional(),
    od_refund_price: numberValue.optional(),
    od_cart_count: numberValue.optional(),
    od_list_price: numberValue.optional(),
    od_order_price: numberValue.optional(),
    od_total_price: numberValue.optional(),
    od_receipt_total: numberValue.optional(),
    od_misu_price: numberValue.optional(),
    od_is_fully_paid: z.boolean().optional(),
    od_total_point: numberValue.optional(),
    od_tax_mny: numberValue.optional(),
    od_vat_mny: numberValue.optional(),
    od_free_mny: numberValue.optional(),
    od_status: stringValue,
    od_time: optionalString,
    od_receipt_time: stringValue,
    can_cancel: z.boolean().optional(),
    cancel_block_reason: optionalString,
    od_settle_case: stringValue,
    od_payment_display_bank: z.boolean().optional(),
    items: z.array(shopOrderItemSchema).optional(),
  })
  .passthrough() as unknown as z.ZodType<ShopOrder>;

export const shopOrderListSchema = z.array(shopOrderSchema);

export const shopReviewSchema = z
  .object({
    is_id: stringValue,
    it_id: stringValue,
    it_name: optionalString,
    mb_id: stringValue,
    mb_nick: stringValue,
    it_seo_title: optionalString,
    ca_id: optionalString,
    it_price: numberValue.optional(),
    is_name: stringValue,
    is_score: numberValue,
    is_subject: stringValue,
    is_content: stringValue,
    is_confirm: stringValue.optional(),
    is_time: stringValue,
    product_image_url: optionalString,
  })
  .passthrough() as unknown as z.ZodType<ShopReview>;

export const shopReviewListSchema = z.array(shopReviewSchema);

export const shopReviewScoreSummarySchema = z
  .object({
    score: numberValue,
    count: numberValue,
    percentage: numberValue,
  })
  .passthrough() as unknown as z.ZodType<ShopReviewScoreSummary>;

export const shopReviewSummarySchema = z
  .object({
    total: numberValue,
    average: numberValue,
    photo_count: numberValue,
    scores: z.array(shopReviewScoreSummarySchema).default([]),
  })
  .passthrough() as unknown as z.ZodType<ShopReviewSummary>;

export const shopQaSchema = z
  .object({
    iq_id: stringValue,
    it_id: stringValue,
    it_name: optionalString,
    it_seo_title: optionalString,
    ca_id: optionalString,
    it_price: numberValue.optional(),
    mb_id: stringValue,
    mb_nick: stringValue,
    iq_name: stringValue,
    iq_subject: stringValue,
    iq_question: stringValue,
    iq_answer: stringValue,
    iq_secret: numberValue.optional(),
    iq_email: optionalString,
    iq_hp: optionalString,
    is_answered: z.coerce.boolean().optional(),
    can_view: z.coerce.boolean().optional(),
    can_edit: z.coerce.boolean().optional(),
    can_delete: z.coerce.boolean().optional(),
    iq_time: stringValue,
    product_image_url: optionalString,
  })
  .passthrough() as unknown as z.ZodType<ShopQA>;

export const shopQaListSchema = z.array(shopQaSchema);

export const searchResultItemSchema = z
  .object({
    wr_id: numberValue,
    wr_subject: stringValue,
    wr_seo_title: stringValue.optional(),
    wr_name: stringValue,
    wr_datetime: stringValue,
    mb_nick: optionalString,
    ca_name: optionalString,
    /** 검색어 주변을 잘라 낸 본문(읽을 수 있는 글만). API 가 만들어 준다 — 본문 전체는 오지 않는다. */
    wr_content_preview: optionalString,
  })
  .passthrough();

export const searchResultSchema = z
  .object({
    bo_table: stringValue,
    bo_subject: stringValue,
    count: numberValue.optional(),
    list: z.array(searchResultItemSchema).default([]),
  })
  .passthrough();

// Raw board group as returned by PHP /api/v1/search — uses `posts` instead of `list`.
const searchResultGroupSchema = z
  .object({
    bo_table: stringValue,
    bo_subject: stringValue,
    count: numberValue.optional(),
    posts: z.array(searchResultItemSchema).default([]),
  })
  .passthrough();

// PHP wraps the groups: { keyword, total_count, results: [...] } with `posts`.
// Accept both the wrapped shape (current backend) and a bare array of
// SearchResult (legacy / future), normalizing into SearchResult[] so callers
// see a stable shape.
export const searchResultListSchema = z.union([
  z
    .object({
      keyword: stringValue.optional(),
      total_count: numberValue.optional(),
      results: z.array(searchResultGroupSchema).default([]),
    })
    .transform((envelope): SearchResult[] =>
      envelope.results.map((group) => ({
        bo_table: group.bo_table,
        bo_subject: group.bo_subject,
        // 이 게시판의 전체 일치 수. list 는 그중 한 페이지분이라, 이 값이 없으면 화면이 "더 있는지" 를 알 수 없다.
        count: group.count,
        list: group.posts,
      }))
    ),
  z.array(searchResultSchema),
]);

export type SearchResult = {
  bo_table: string;
  bo_subject: string;
  count?: number;
  list: z.infer<typeof searchResultItemSchema>[];
};

export const publicSettingsSchema = z
  .object({
    cf_title: optionalString,
    cf_company_name: optionalString,
    cf_company_owner: optionalString,
    cf_company_addr: optionalString,
    cf_company_biz_no: optionalString,
    cf_company_tel: optionalString,
    cf_company_tongsin_no: optionalString,
    cf_company_buga_no: optionalString,
    cf_company_fax: optionalString,
    cf_company_info_name: optionalString,
    cf_company_email: optionalString,
    de_admin_company_tel: optionalString,
    de_bank_use: optionalString,
    de_bank_account: optionalString,
    cf_home_boards: optionalString,
    cf_home_gallery: optionalString,
    cf_bbs_rewrite: numberValue.optional(),
    infinite_scroll: booleanValue.optional(),
    comment_editor: booleanValue.optional(),
    pwa_enabled: booleanValue.optional(),
    /** 가격 인하 알림 (de_price_alert_use): 상품 페이지에 알림 단추를 보인다. */
    price_alert_enabled: booleanValue.optional(),
    /** 쇼핑몰 설정에서 올린 로고(없으면 ""): 상단 · 하단 · 모바일 상단 · 모바일 하단. */
    shop_logo: optionalString,
    shop_logo_footer: optionalString,
    shop_logo_mobile: optionalString,
    shop_logo_mobile_footer: optionalString,
    /** 검색 · 유형별 목록 · 관련상품 진열(lib/shop-display.ts). */
    shop_display: shopListDisplaySchema.optional(),
    visit: z.object({
      today: numberValue,
      yesterday: numberValue,
      max: numberValue,
      total: numberValue,
    }).optional(),
  })
  .passthrough();

export type PublicSettings = z.infer<typeof publicSettingsSchema>;

export const popularKeywordSchema = z.object({
  pp_word: stringValue,
  cnt: numberValue,
});

export const popularKeywordListSchema = z.array(popularKeywordSchema);
export type PopularKeyword = z.infer<typeof popularKeywordSchema>;
export type VisitStats = NonNullable<PublicSettings["visit"]>;

export const recentItemSchema = z
  .object({
    bn_id: numberValue,
    gr_id: stringValue,
    gr_subject: stringValue,
    bo_table: stringValue,
    bo_subject: stringValue,
    wr_id: numberValue,
    wr_parent: numberValue,
    wr_subject: stringValue,
    wr_seo_title: stringValue.optional(),
    comment_excerpt: optionalString,
    is_comment: booleanValue,
    mb_id: stringValue,
    wr_name: stringValue,
    wr_email: stringValue,
    wr_homepage: stringValue,
    wr_datetime: stringValue,
    href: stringValue,
  })
  .passthrough() as unknown as z.ZodType<RecentItem>;

export const recentItemListSchema = z.array(recentItemSchema);

export const recentGroupSchema = z
  .object({
    gr_id: stringValue,
    gr_subject: stringValue,
  })
  .passthrough() as unknown as z.ZodType<RecentGroup>;

export const recentGroupListSchema = z.array(recentGroupSchema);

export const myPostSchema = z
  .object({
    wr_id: numberValue,
    wr_subject: stringValue,
    wr_seo_title: stringValue.optional(),
    wr_datetime: stringValue,
    bo_table: stringValue,
    bo_subject: optionalString,
  })
  .passthrough();

export const myPostListSchema = z.array(myPostSchema);

export const myCommentSchema = z
  .object({
    wr_id: numberValue,
    wr_content: stringValue,
    wr_datetime: stringValue,
    bo_table: stringValue,
    bo_subject: optionalString,
    wr_parent: numberValue,
  })
  .passthrough();

export const myCommentListSchema = z.array(myCommentSchema);

export const pointItemSchema = z
  .object({
    po_id: numberValue,
    po_content: stringValue,
    po_point: numberValue,
    po_use_point: numberValue,
    po_mb_point: numberValue,
    po_datetime: stringValue,
    po_rel_table: stringValue,
    po_rel_action: stringValue,
  })
  .passthrough();

export const pointItemListSchema = z.array(pointItemSchema);

export const couponSchema = z
  .object({
    cp_id: stringValue,
    cp_subject: stringValue,
    cp_method: stringValue,
    cp_price: numberValue,
    cp_start: stringValue,
    cp_end: stringValue,
    cp_minimum: numberValue,
    cp_used: stringValue,
  })
  .passthrough();

export const couponListSchema = z.array(couponSchema);

export const savedAddressSchema = z
  .object({
    ad_id: numberValue,
    ad_subject: stringValue,
    ad_default: numberValue,
    ad_name: stringValue,
    ad_tel: stringValue,
    ad_hp: stringValue,
    ad_zip1: stringValue,
    ad_zip2: stringValue,
    ad_addr1: stringValue,
    ad_addr2: stringValue,
    ad_addr3: stringValue,
    ad_jibeon: stringValue,
  })
  .passthrough();

export const savedAddressListSchema = z.array(savedAddressSchema);

export const contentDataSchema = z
  .object({
    co_id: stringValue,
    co_subject: stringValue,
    co_content: stringValue,
    co_html: numberValue,
    co_skin: stringValue,
  })
  .passthrough();

export type MyPost = z.infer<typeof myPostSchema>;
export type MyComment = z.infer<typeof myCommentSchema>;
export type PointItem = z.infer<typeof pointItemSchema>;
export type Coupon = z.infer<typeof couponSchema>;
export type SavedAddress = z.infer<typeof savedAddressSchema>;
export type ContentData = z.infer<typeof contentDataSchema>;

export const notificationItemSchema = z
  .object({
    nt_id: numberValue,
    nt_type: stringValue,
    nt_title: stringValue,
    nt_body: stringValue,
    nt_data: z.unknown().nullable().optional(),
    nt_sent_at: stringValue,
    nt_read_at: optionalString.nullable().optional(),
    is_read: booleanValue,
  })
  .passthrough();

export const notificationListSchema = z.array(notificationItemSchema);

export const notificationResponseSchema = z
  .object({
    count: numberValue,
    items: z.array(notificationItemSchema).default([]),
  })
  .passthrough();

export const notificationReadSchema = z
  .object({
    read_at: optionalString,
    message: optionalString,
  })
  .passthrough();

export type NotificationItem = z.infer<typeof notificationItemSchema>;

export const authAvailabilitySchema = z
  .object({
    available: booleanValue,
    message: stringValue,
  })
  .passthrough();

export const passwordResetRequestSchema = z
  .object({
    reset_token: stringValue,
  })
  .passthrough();

export type AuthAvailability = z.infer<typeof authAvailabilitySchema>;

export const memoSchema = z
  .object({
    me_id: numberValue,
    me_recv_mb_id: stringValue,
    me_send_mb_id: stringValue,
    me_send_datetime: stringValue,
    me_read_datetime: stringValue,
    me_memo: stringValue,
    me_send_id: numberValue,
    me_type: z.enum(["send", "recv"]).catch("recv"),
    me_send_ip: stringValue,
  })
  .passthrough() as unknown as z.ZodType<Memo>;

export const memoListSchema = z.array(memoSchema);

export const scrapSchema = z
  .object({
    ms_id: numberValue,
    mb_id: stringValue,
    bo_table: stringValue,
    wr_id: numberValue,
    ms_datetime: stringValue,
    bo_subject: stringValue,
    wr_subject: stringValue,
    wr_datetime: stringValue,
    wr_name: stringValue,
    post_mb_id: stringValue,
    href: stringValue,
  })
  .passthrough() as unknown as z.ZodType<Scrap>;

export const scrapListSchema = z.array(scrapSchema);

export const faqMasterSchema = z
  .object({
    fm_id: numberValue,
    fm_subject: stringValue,
    fm_head_html: stringValue,
    fm_tail_html: stringValue,
    fm_mobile_head_html: stringValue,
    fm_mobile_tail_html: stringValue,
    fm_order: numberValue,
  })
  .passthrough();

export const faqItemSchema = z
  .object({
    fa_id: numberValue,
    fm_id: numberValue,
    fa_subject: stringValue,
    fa_content: stringValue,
    fa_order: numberValue,
  })
  .passthrough();

export const faqPageDataSchema = z
  .object({
    masters: z.array(faqMasterSchema).default([]),
    current: faqMasterSchema.nullable(),
    items: z.array(faqItemSchema).default([]),
    meta: paginationMetaSchema.extend({
      from: numberValue.nullable().optional(),
      to: numberValue.nullable().optional(),
    }),
  })
  .passthrough() as unknown as z.ZodType<FaqPageData>;

export const pollOptionSchema = z
  .object({
    num: numberValue,
    content: stringValue,
    count: numberValue,
    rate: numberValue,
    bar: numberValue,
  })
  .passthrough();

export const pollCommentSchema = z
  .object({
    pc_id: numberValue,
    po_id: numberValue,
    mb_id: stringValue,
    pc_name: stringValue,
    pc_idea: stringValue,
    pc_datetime: stringValue,
    can_delete: booleanValue,
  })
  .passthrough() as unknown as z.ZodType<PollComment>;

export const pollSummarySchema = z
  .object({
    po_id: numberValue,
    po_subject: stringValue,
    po_date: stringValue,
    po_use: numberValue,
    is_current: booleanValue.optional(),
  })
  .passthrough() as unknown as z.ZodType<PollSummary>;

export const pollSchema = z
  .object({
    po_id: numberValue,
    po_subject: stringValue,
    po_etc: stringValue,
    po_level: numberValue,
    po_point: numberValue,
    po_date: stringValue,
    po_use: numberValue,
    is_active: booleanValue,
    options: z.array(pollOptionSchema).default([]),
    total_count: numberValue,
    has_voted: booleanValue,
    can_vote: booleanValue,
    can_view_result: booleanValue,
    can_comment: booleanValue,
    etc_comments: z.array(pollCommentSchema).default([]),
    other_polls: z.array(pollSummarySchema).default([]),
  })
  .passthrough() as unknown as z.ZodType<Poll>;

export const qaConfigSchema = z
  .object({
    qa_title: stringValue,
    qa_category: stringValue,
    categories: z.array(stringValue).default([]),
    qa_use_email: numberValue,
    qa_req_email: numberValue,
    qa_use_hp: numberValue,
    qa_req_hp: numberValue,
    qa_use_sms: numberValue,
    qa_subject_len: numberValue,
    qa_page_rows: numberValue,
    qa_mobile_page_rows: numberValue,
    qa_insert_content: stringValue,
    qa_content_head: stringValue,
    qa_content_tail: stringValue,
    qa_mobile_content_head: stringValue,
    qa_mobile_content_tail: stringValue,
  })
  .passthrough() as unknown as z.ZodType<QaConfig>;

export const qaItemSchema: z.ZodType<QaItem> = z.lazy(() =>
  z
    .object({
      qa_id: numberValue,
      qa_num: numberValue,
      qa_parent: numberValue,
      qa_related: numberValue,
      mb_id: stringValue,
      qa_name: stringValue,
      qa_email: stringValue,
      qa_hp: stringValue,
      qa_type: numberValue,
      qa_category: stringValue,
      qa_email_recv: numberValue,
      qa_sms_recv: numberValue,
      qa_html: numberValue,
      qa_subject: stringValue,
      qa_content: stringValue,
      qa_status: numberValue,
      qa_file1: stringValue,
      qa_source1: stringValue,
      qa_file2: stringValue,
      qa_source2: stringValue,
      qa_file1_url: stringValue,
      qa_file2_url: stringValue,
      qa_datetime: stringValue,
      can_edit: booleanValue,
      can_delete: booleanValue,
      answer: qaItemSchema.nullable(),
      related_questions: z.array(qaItemSchema).default([]),
    })
    .passthrough()
) as z.ZodType<QaItem>;

export const qaItemListSchema = z.array(qaItemSchema);
