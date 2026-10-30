import { apiClient } from "@/lib/api";
import { z } from "zod";
import type { ApiMeta } from "@/lib/api-response";
import { validateApiData } from "@/lib/api-response";
import {
  couponListSchema,
  memberProfileSchema,
  myMemberDetailsSchema,
  myCommentListSchema,
  myPostListSchema,
  pointItemListSchema,
  shopOrderListSchema,
  shopOrderSchema,
  type Coupon,
  type MyComment,
  type MyPost,
  type PointItem,
} from "@/lib/schemas";
import type { ShopOrder } from "@/lib/api";
import type { MemberProfile, MyMemberDetails } from "@/lib/types";

export interface PointsResult {
  items: PointItem[];
  meta?: ApiMeta;
}

export interface MyOrdersResult {
  orders: ShopOrder[];
  totalPages: number;
}

export interface GuestOrderLookupResult {
  od_id: string;
  uid: string;
  redirect_url?: string;
}

export interface MyDashboardCounts {
  orders: number;
  wishlist: number;
  scraps: number;
  posts: number;
  comments: number;
  addresses: number;
  coupons: number;
}

export interface MyProfilePayload {
  mb_nick: string;
  mb_name: string;
  mb_email: string;
  mb_password_current?: string;
  // 정보공개 (g5_member.mb_open) — 1 공개, 0 비공개.
  mb_open?: number;
  // 정보 메일 수신 (g5_member.mb_mailling) — 1 받음, 0 받지 않음.
  mb_mailling?: number;
}

export interface MyProfileUpdateResult {
  member?: Record<string, string | number | undefined>;
  // 메일인증을 쓰는 사이트에서 이메일을 바꾸면 서버가 로그아웃시키고 새 주소로 인증 메일을 보낸다.
  email_certify_required?: boolean;
  logged_out?: boolean;
  message?: string;
}

export interface LeaveResult {
  left?: boolean;
  mb_leave_date?: string;
  message?: string;
}

export interface MyPasswordPayload {
  mb_password_current: string;
  mb_password: string;
  mb_password_re: string;
}

export interface LoginSession {
  token_id: number;
  /** True for the session this browser is signed in with. */
  current: boolean;
  device_label: string;
  user_agent: string;
  ip: string;
  created_at: string;
  expires_at: string;
  last_used_at: string;
}

const loginSessionSchema = z.object({
  token_id: z.coerce.number().int().positive(),
  current: z.boolean().catch(false),
  device_label: z.coerce.string().catch(""),
  user_agent: z.coerce.string().catch(""),
  ip: z.coerce.string().catch(""),
  created_at: z.coerce.string().catch(""),
  expires_at: z.coerce.string().catch(""),
  last_used_at: z.coerce.string().catch(""),
});

const loginSessionListSchema = z.array(loginSessionSchema);

export function updateMyProfile(payload: MyProfilePayload) {
  return apiClient.patch<MyProfileUpdateResult>("/members/me", payload);
}

export async function getMyMemberDetails(): Promise<MyMemberDetails> {
  const response = await apiClient.get<{ member?: unknown }>("/members/me");
  const parsed = myMemberDetailsSchema.safeParse(response.data?.member);
  if (!parsed.success) {
    throw new Error("회원 요약 정보를 불러오지 못했습니다.");
  }

  return parsed.data;
}

/** 회원탈퇴 (bbs/member_leave.php) — 현재 비밀번호가 맞아야 한다. */
export async function leaveMembership(password: string): Promise<string> {
  const response = await apiClient.post<LeaveResult>("/members/me/leave", { mb_password: password });
  return response.data?.message || "회원에서 탈퇴하셨습니다.";
}

export function updateMyPassword(payload: MyPasswordPayload) {
  return apiClient.patch("/members/me", payload);
}

export function uploadMyIcon(file: File) {
  const formData = new FormData();
  formData.append("mb_icon", file);
  return apiClient.upload("/members/me/icon", formData);
}

export async function getMemberProfile(mbId: string): Promise<MemberProfile> {
  const response = await apiClient.get<{ member?: unknown }>(
    `/members/${encodeURIComponent(mbId)}/profile`
  );
  const parsed = memberProfileSchema.safeParse(response.data?.member);
  if (!parsed.success) {
    throw new Error("회원 프로필 응답 형식이 올바르지 않습니다.");
  }

  return parsed.data;
}

export async function getLoginSessions(): Promise<LoginSession[]> {
  const response = await apiClient.get<unknown>("/auth/sessions");
  const source =
    response.data && typeof response.data === "object" && "sessions" in response.data
      ? (response.data as { sessions?: unknown }).sessions
      : [];
  return validateApiData(source, loginSessionListSchema, []);
}

export async function revokeLoginSession(tokenId: number): Promise<{ revoked: boolean; current: boolean }> {
  if (!Number.isSafeInteger(tokenId) || tokenId <= 0) {
    throw new Error("로그인 세션 번호가 올바르지 않습니다.");
  }
  const response = await apiClient.delete<{ revoked: boolean; current: boolean }>(
    `/auth/sessions/${encodeURIComponent(String(tokenId))}`
  );
  if (!response.data) {
    throw new Error("로그아웃 응답이 올바르지 않습니다.");
  }
  return response.data;
}

export async function getMyPosts(perPage = 30): Promise<MyPost[]> {
  const response = await apiClient.get<unknown>("/members/me/posts", {
    params: { per_page: perPage },
  });

  return validateApiData(response.data, myPostListSchema, []);
}

export async function getMyComments(perPage = 30): Promise<MyComment[]> {
  const response = await apiClient.get<unknown>("/members/me/comments", {
    params: { per_page: perPage },
  });

  return validateApiData(response.data, myCommentListSchema, []);
}

export async function getMyPoints(page = 1, perPage = 15): Promise<PointsResult> {
  const response = await apiClient.get<unknown>("/members/me/points", {
    params: { page, per_page: perPage },
  });

  return {
    items: validateApiData(response.data, pointItemListSchema, []),
    meta: response.meta,
  };
}

export async function getMyCoupons(): Promise<Coupon[]> {
  const response = await apiClient.get<unknown>("/shop/coupons");
  return validateApiData(response.data, couponListSchema, []);
}

export async function getMyUsableCouponCount(): Promise<number> {
  const response = await apiClient.get<unknown>("/shop/coupons", {
    params: { usable: 1, per_page: 1 },
  });
  return response.meta?.total ?? 0;
}

export async function getMyOrders(
  page = 1,
  perPage = 10
): Promise<MyOrdersResult> {
  const response = await apiClient.get<unknown>("/shop/orders", {
    params: { page, per_page: perPage },
  });

  return {
    orders: validateApiData(response.data, shopOrderListSchema, []),
    totalPages: response.meta?.last_page ?? 1,
  };
}

export async function lookupGuestOrder(
  orderId: string,
  password: string
): Promise<GuestOrderLookupResult> {
  const response = await apiClient.post<GuestOrderLookupResult>("/shop/orders/lookup", {
    od_id: orderId.trim(),
    od_pwd: password,
  });
  if (!response.data?.od_id || !response.data?.uid) {
    throw new Error("주문 정보를 확인할 수 없습니다.");
  }
  return response.data;
}

export async function getMyOrder(
  orderId: string,
  uid = ""
): Promise<ShopOrder | null> {
  const normalizedOrderId = orderId.trim();
  if (!normalizedOrderId) return null;

  const response = await apiClient.get<unknown>(
    `/shop/orders/${encodeURIComponent(normalizedOrderId)}`,
    uid ? { params: { uid } } : undefined
  );
  const parsed = shopOrderSchema.safeParse(response.data);
  return parsed.success ? parsed.data : null;
}

export interface CashReceiptRequestResult {
  issued: boolean;
  message: string;
  order: ShopOrder | null;
}

/** 주문 후 현금영수증 발급 신청(영카트 taxsave.php) — 회원 본인 또는 비회원 주문 조회 uid. */
export async function requestOrderCashReceipt(
  orderId: string,
  cashType: "income" | "expense",
  identity: string,
  uid = ""
): Promise<CashReceiptRequestResult> {
  const query = uid ? `?uid=${encodeURIComponent(uid)}` : "";
  const response = await apiClient.post<{ issued?: boolean; message?: string; order?: unknown }>(
    `/shop/orders/${encodeURIComponent(orderId.trim())}/cash-receipt${query}`,
    { od_cash_type: cashType, cash_receipt_registration_number: identity }
  );
  const parsed = shopOrderSchema.safeParse(response.data?.order);
  return {
    issued: response.data?.issued === true,
    message: String(response.data?.message ?? ""),
    order: parsed.success ? parsed.data : null,
  };
}

export function cancelMyOrder(orderId: string, reason = "본인 취소", uid = "") {
  return apiClient.patch(`/shop/orders/${encodeURIComponent(orderId)}`, {
    reason,
    ...(uid ? { uid } : {}),
  });
}

async function getMetaTotal(path: string): Promise<number> {
  const response = await apiClient.get<unknown>(path, {
    params: { per_page: 1 },
  });

  return response.meta?.total ?? 0;
}

export async function getMyDashboardCounts(): Promise<MyDashboardCounts> {
  const [orders, wishlist, scraps, posts, comments, addresses, coupons] = await Promise.all([
    getMetaTotal("/shop/orders").catch(() => 0),
    getMetaTotal("/shop/wishlist").catch(() => 0),
    getMetaTotal("/scraps").catch(() => 0),
    getMetaTotal("/members/me/posts").catch(() => 0),
    getMetaTotal("/members/me/comments").catch(() => 0),
    getMetaTotal("/shop/addresses").catch(() => 0),
    getMyUsableCouponCount().catch(() => 0),
  ]);

  return {
    orders,
    wishlist,
    scraps,
    posts,
    comments,
    addresses,
    coupons,
  };
}
