import { apiBaseUrlForRuntime } from "@/lib/config";
import { parseApiEnvelope } from "@/lib/api-response";
import { localizeApiErrors, localizeApiMessage } from "@/lib/api-messages";
import type { ApiResponse } from "@/lib/api-response";

// Server-side: call PHP API directly. Client-side: use Next.js proxy to avoid CORS.
const API_URL = apiBaseUrlForRuntime();
const TOKEN_COOKIE = 'g5_token';
const REFRESH_COOKIE = 'g5_refresh';
const AUTO_LOGIN_COOKIE = 'g5_auto_login';
const AUTH_HINT_COOKIE = 'g5_auth_hint';
/**
 * 그누보드5 자동로그인과 같은 의미:
 * - g5_token: access token. 항상 session cookie.
 * - g5_refresh: auto login 선택 시 30일 cookie, 미선택 시 session cookie.
 * - g5_auto_login: refresh token rotation 때 persistent/session 상태를 유지하기 위한 marker.
 */
const REFRESH_COOKIE_MAX_AGE = 30 * 24 * 60 * 60;

export type { ApiResponse };

function getCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
  return match ? decodeURIComponent(match[1]) : null;
}

function cookieSecurityAttributes(): string {
  if (typeof document === 'undefined') return '';
  return window.location.protocol === 'https:' ? '; Secure' : '';
}

function setCookie(name: string, value: string, maxAgeSeconds?: number) {
  if (typeof document === 'undefined') return;
  // maxAge 없으면 session cookie. 있으면 영속 cookie.
  const maxAge = typeof maxAgeSeconds === 'number' ? `; max-age=${maxAgeSeconds}` : '';
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; SameSite=Lax${maxAge}${cookieSecurityAttributes()}`;
}

function deleteCookie(name: string) {
  if (typeof document === 'undefined') return;
  document.cookie = `${name}=; path=/; max-age=0; SameSite=Lax${cookieSecurityAttributes()}`;
}

function shouldPersistClientAuthCookies(): boolean {
  return false;
}

function clearClientAuthCookies() {
  if (typeof document === 'undefined') return;
  if (!shouldPersistClientAuthCookies()) {
    deleteCookie(TOKEN_COOKIE);
    deleteCookie(REFRESH_COOKIE);
    deleteCookie(AUTO_LOGIN_COOKIE);
  }
}

function setAuthHint(autoLogin?: boolean) {
  setCookie(AUTH_HINT_COOKIE, '1', autoLogin ? REFRESH_COOKIE_MAX_AGE : undefined);
}

class ApiClient {
  private baseUrl: string;
  private token: string | null = null;
  private refreshToken: string | null = null;
  private csrfToken: string | null = null;
  private csrfTokenInFlight: Promise<string> | null = null;
  /**
   * 동시 요청 여럿이 같이 401 받아도 refresh 는 한 번만 — 진행 중 promise 공유.
   */
  private refreshInFlight: Promise<string | null> | null = null;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
    if (typeof window !== 'undefined') {
      // Migrate legacy localStorage into memory, then remove it from persistent JS storage.
      try {
        const legacy = window.localStorage.getItem(TOKEN_COOKIE);
        if (legacy) {
          this.token = legacy;
          window.localStorage.removeItem(TOKEN_COOKIE);
        } else {
          deleteCookie(TOKEN_COOKIE);
          deleteCookie(REFRESH_COOKIE);
        }
      } catch {
        // Keep cookie authentication available when browser storage is restricted.
      }
    }
  }

  private canAttemptCookieRefresh(): boolean {
    return typeof window !== 'undefined';
  }

  private async getCsrfToken(): Promise<string> {
    if (this.csrfToken) return this.csrfToken;
    if (this.csrfTokenInFlight) return this.csrfTokenInFlight;

    this.csrfTokenInFlight = (async () => {
      const res = await fetch(`${this.baseUrl}/auth/csrf`, {
        method: 'GET',
        headers: { Accept: 'application/json' },
        credentials: 'include',
        cache: 'no-store',
      });
      const env = parseApiEnvelope<{ csrf_token?: string }>(await res.json());
      const token = env.data?.csrf_token;
      if (!res.ok || !env.success || !token) {
        throw new ApiError(env.message || 'Could not obtain a CSRF token.', res.status || 500);
      }
      this.csrfToken = token;
      return token;
    })();

    try {
      return await this.csrfTokenInFlight;
    } finally {
      this.csrfTokenInFlight = null;
    }
  }

  private shouldAttemptRefresh(path: string): boolean {
    const pathname = path.split(/[?#]/)[0] || '';
    if (pathname === '/auth/refresh') return false;
    return ![
      '/auth/login',
      '/auth/register',
      '/auth/password-reset',
      '/auth/verify-email',
      '/auth/check-id',
      '/auth/check-email',
    ].some((authPath) => pathname === authPath || pathname.startsWith(`${authPath}/`));
  }

  hasAuthHint(): boolean {
    if (this.token || this.refreshToken) return true;
    if (typeof window === 'undefined') return false;
    return (
      getCookie(AUTH_HINT_COOKIE) === '1'
    );
  }

  setToken(token: string | null) {
    this.token = token;
    if (typeof window !== 'undefined') {
      if (token) {
        deleteCookie(TOKEN_COOKIE);
      } else {
        deleteCookie(TOKEN_COOKIE);
        deleteCookie(AUTH_HINT_COOKIE);
      }
    }
  }

  setRefreshToken(token: string | null, options?: { autoLogin?: boolean }) {
    this.refreshToken = null;
    if (typeof window !== 'undefined') {
      if (!token) {
        clearClientAuthCookies();
        deleteCookie(AUTH_HINT_COOKIE);
        return;
      }

      const hasExplicitAutoLogin = typeof options?.autoLogin === 'boolean';
      const autoLogin = hasExplicitAutoLogin
        ? options.autoLogin
        : getCookie(AUTO_LOGIN_COOKIE) === '1';

      clearClientAuthCookies();
      if (hasExplicitAutoLogin || getCookie(AUTH_HINT_COOKIE) !== '1') {
        setAuthHint(autoLogin);
      }
    }
  }

  getToken() {
    return this.token;
  }

  getRefreshToken() {
    return this.refreshToken;
  }

  /**
   * Refresh token 으로 access token 교환. 결과 access token 반환 (실패 시 null).
   * 동시에 여러 요청이 호출하면 in-flight promise 공유 → 서버 부하 / race 제거.
   */
  async refreshAccessToken(): Promise<string | null> {
    if (!this.refreshToken && (!this.canAttemptCookieRefresh() || !this.hasAuthHint())) return null;
    if (this.refreshInFlight) return this.refreshInFlight;

    this.refreshInFlight = (async () => {
      try {
        const body = this.refreshToken ? JSON.stringify({ refresh_token: this.refreshToken }) : undefined;
        const headers = new Headers({ 'Content-Type': 'application/json', Accept: 'application/json' });
        if (this.canAttemptCookieRefresh()) {
          headers.set('X-CSRFToken', await this.getCsrfToken());
        }
        const res = await fetch(`${this.baseUrl}/auth/refresh`, {
          method: 'POST',
          headers,
          credentials: 'include',
          body,
        });
        if (!res.ok) {
          // 401/403 → refresh token 도 만료 또는 revoked. 둘 다 폐기.
          if (res.status === 401 || res.status === 403) {
            this.setToken(null);
            this.setRefreshToken(null);
          }
          return null;
        }
        const env = parseApiEnvelope<{ token: string; refresh_token?: string }>(await res.json());
        if (!env.success || !env.data?.token) return null;
        this.setToken(env.data.token);
        if (env.data.refresh_token) this.setRefreshToken(env.data.refresh_token);
        return env.data.token;
      } catch {
        return null;
      }
    })();

    try {
      return await this.refreshInFlight;
    } finally {
      this.refreshInFlight = null;
    }
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    options?: RequestInit & { _retried?: boolean }
  ): Promise<ApiResponse<T>> {
    const headers = new Headers(options?.headers);
    if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');

    const cookieRefreshPath = ['/auth/logout'].includes(path.split(/[?#]/)[0] || '');
    if (this.token) {
      headers.set('Authorization', `Bearer ${this.token}`);
    }
    if (
      this.canAttemptCookieRefresh() &&
      (!this.token || cookieRefreshPath) &&
      !['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method.toUpperCase())
    ) {
      headers.set('X-CSRFToken', await this.getCsrfToken());
    }

    const res = await fetch(`${this.baseUrl}${path}`, {
      ...options,
      method,
      headers,
      credentials: options?.credentials ?? 'include',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    // 401 + refresh 가능 + 미재시도 + refresh 대상 엔드포인트인 경우 → access 교환 후 재시도.
    if (
      res.status === 401 &&
      !options?._retried &&
      this.shouldAttemptRefresh(path) &&
      (this.refreshToken || (this.canAttemptCookieRefresh() && this.hasAuthHint()))
    ) {
      const newToken = await this.refreshAccessToken();
      if (newToken) {
        return this.request<T>(method, path, body, { ...options, _retried: true });
      }
    }

    return this.handleResponse<T>(res);
  }

  private async handleResponse<T>(res: Response): Promise<ApiResponse<T>> {
    let data: ApiResponse<T>;
    try {
      data = parseApiEnvelope<T>(await res.json());
    } catch {
      data = {
        success: false,
        message: res.statusText || 'API Error',
      };
    }

    if (!res.ok) {
      if (res.status === 401 && this.token) {
        // refresh 도 실패한 끝-단계 401 → 세션 만료 처리.
        this.setToken(null);
        this.setRefreshToken(null);
        if (typeof window !== 'undefined') {
          // Dispatch custom event so auth store can react
          window.dispatchEvent(new CustomEvent('auth:expired'));
        }
      }
      throw new ApiError(data.message || 'API Error', res.status, data.errors, data.code);
    }

    return data;
  }

  get<T>(path: string, options?: { params?: Record<string, unknown> }) {
    let url = path;
    if (options?.params) {
      const query = Object.entries(options.params)
        .filter(([, v]) => v !== undefined && v !== null)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
        .join('&');
      if (query) url += (url.includes('?') ? '&' : '?') + query;
    }
    return this.request<T>('GET', url);
  }

  post<T>(path: string, body?: unknown, options?: RequestInit) {
    return this.request<T>('POST', path, body, options);
  }

  put<T>(path: string, body?: unknown) {
    return this.request<T>('PUT', path, body);
  }

  patch<T>(path: string, body?: unknown) {
    return this.request<T>('PATCH', path, body);
  }

  delete<T>(path: string) {
    return this.request<T>('DELETE', path);
  }

  async upload<T>(
    path: string,
    formData: FormData,
    options?: { _retried?: boolean }
  ): Promise<ApiResponse<T>> {
    const headers = new Headers();
    if (this.token) {
      headers.set('Authorization', `Bearer ${this.token}`);
    } else if (this.canAttemptCookieRefresh()) {
      headers.set('X-CSRFToken', await this.getCsrfToken());
    }

    const res = await fetch(`${this.baseUrl}${path}`, {
      method: 'POST',
      headers,
      credentials: 'include',
      body: formData,
    });

    if (
      res.status === 401 &&
      !options?._retried &&
      this.shouldAttemptRefresh(path) &&
      (this.refreshToken || (this.canAttemptCookieRefresh() && this.hasAuthHint()))
    ) {
      const newToken = await this.refreshAccessToken();
      if (newToken) {
        return this.upload<T>(path, formData, { _retried: true });
      }
    }

    return this.handleResponse<T>(res);
  }
}

export class ApiError extends Error {
  status: number;
  errors?: Record<string, string>;
  /** The machine-readable error code of the API envelope (e.g. "cart_price_changed"). */
  code?: string;

  constructor(message: string, status: number, errors?: Record<string, string>, code?: string) {
    super(localizeApiMessage(message));
    this.status = status;
    this.errors = localizeApiErrors(errors);
    this.code = code;
  }
}

export const api = new ApiClient(API_URL);
export const apiClient = api;

// ---- Shop Types ----

export interface ShopProductInfoItem {
  key: string;
  title: string;
  value: string;
  example?: string;
}

export interface ShopProduct {
  it_id: string;
  ca_id: string;
  ca_name?: string;
  it_name: string;
  it_price: number;
  it_basic_price: number;
  it_cust_price: number;
  it_hit?: number;
  it_point: number;
  it_point_type?: number;
  it_stock_qty: number;
  it_buy_min_qty?: number;
  it_buy_max_qty?: number;
  it_tel_inq?: string;
  it_soldout: string;
  it_stock_sms?: string;
  stock_sms_privacy?: string;
  it_sc_type?: number;
  it_sc_method?: number;
  it_sc_price?: number;
  it_sc_minimum?: number;
  it_sc_qty?: number;
  it_type1: string;
  it_type2: string;
  it_type3: string;
  it_type4: string;
  it_type5: string;
  has_coupon?: boolean;
  it_content?: string;
  it_explan?: string;
  it_basic?: string;
  it_head_html?: string;
  it_tail_html?: string;
  it_info_gubun?: string;
  /** 상품정보제공고시 상품군 이름(예: 의류). */
  it_info_gubun_title?: string;
  it_info_title?: string;
  it_info_items?: ShopProductInfoItem[];
  it_option_subject?: string;
  it_supply_subject?: string;
  // 상품 메타 — 영카트 it_brand/it_maker/it_origin/it_model/it_seo_title.
  it_brand?: string;
  it_maker?: string;
  it_origin?: string;
  it_model?: string;
  it_seo_title?: string;
  image_url: string;
  images?: string[];
  options?: ShopProductOption[];
  category?: ShopCategory;
  review_count?: number;
  review_avg?: number;
  qa_count?: number;
  related_items?: ShopProduct[];
  prev_item?: ShopProductNavItem | null;
  next_item?: ShopProductNavItem | null;
}

export interface ShopProductNavItem {
  it_id: string;
  it_name: string;
  it_seo_title?: string;
  image_url?: string;
}

export interface ShopProductOption {
  io_no: number;
  it_id: string;
  io_id: string;
  io_type: string;
  io_value: string;
  io_price: number;
  io_stock_qty: number;
  io_noti_qty?: number;
  io_use?: number | string;
}

export interface ShopCategory {
  ca_id: string;
  ca_name: string;
  ca_order: number;
  ca_skin?: string;
  item_count?: number;
  children?: ShopCategory[];
  /** 분류 출력설정(1줄당 이미지 수 · 줄 수, PC · 모바일). 0 은 기본 진열. */
  ca_list_mod?: number;
  ca_list_row?: number;
  ca_mobile_list_mod?: number;
  ca_mobile_list_row?: number;
  ca_nocoupon?: boolean;
  /** 서버가 출력설정으로 정한 목록 격자 — lib/shop-display.ts shopCategoryGridOf 가 읽는다. */
  list_display?: unknown;
}

export interface ShopBanner {
  bn_id: number;
  bn_alt: string;
  bn_url: string;
  bn_position: string;
  bn_device: string;
  bn_border: number;
  bn_new_win: number;
  bn_order: number;
  image_url: string;
  hit_url?: string;
}

export interface ShopPopup {
  nw_id: number;
  nw_division: string;
  nw_device: string;
  nw_begin_time: string;
  nw_end_time: string;
  nw_disable_hours: number;
  nw_width: number;
  nw_height: number;
  nw_subject: string;
  nw_content: string;
  nw_content_text: string;
  nw_content_html: number;
}

export interface ShopNaverPayConfig {
  enabled: boolean;
  reason: string;
  test: boolean;
  mobile: boolean;
  shop_id: string;
  button_key: string;
  button_count_item: number;
  button_count_cart: number;
  script_url: string;
  order_url: string;
  wish_url: string;
}

export interface ShopNaverPayOrderOption {
  io_id: string;
  io_type: number;
  io_value: string;
  ct_qty: number;
}

export interface ShopNaverPayOrderRequest {
  source: "item" | "cart";
  it_id?: string;
  quantity?: number;
  options?: ShopNaverPayOrderOption[];
  ct_ids?: string[] | string;
  back_url?: string;
}

export interface ShopNaverPayOrderResponse {
  order_id: string;
  shop_id: string;
  total_price: number;
  redirect_url: string;
}

export interface ShopNaverPayWishResponse {
  shop_id: string;
  item_ids: string[];
  redirect_url: string;
}

export interface ShopCartItem {
  ct_id: string;
  it_id: string;
  it_name: string;
  it_seo_title?: string;
  ct_price: number;
  ct_qty: number;
  ct_option: string;
  io_type?: number;
  io_price?: number;
  ct_direct?: number;
  ct_send_cost?: number;
  it_sc_type?: number;
  it_sc_method?: number;
  it_sc_price?: number;
  it_sc_minimum?: number;
  it_sc_qty?: number;
  line_total: number;
  it_basic_price: number;
  it_stock_qty: number;
  it_soldout: string;
  it_use?: string;
  it_tel_inq?: string;
  image_url: string;
  // 상품/카테고리 쿠폰으로 행에 적용된 할인액 + 묶인 쿠폰 ID (없으면 0/빈 문자열).
  cp_price?: number;
  cp_id?: string;
}

export interface ShopCartResponse {
  items: ShopCartItem[];
  total_price: number;
  total_qty: number;
  // 카트 행들에 묶인 상품/카테고리 쿠폰 할인 합계 (cart_coupon).
  cart_coupon?: number;
  send_cost?: number;
  shipping_cost?: number;
}

export interface ShopShippingRule {
  limit: number;
  cost: number;
}

export interface ShopPolicy {
  de_admin_company_name?: string;
  de_admin_company_tel?: string;
  delivery_company: string;
  send_cost_case: string;
  send_cost_limit: string;
  send_cost_list: string;
  shipping_rules: ShopShippingRule[];
  base_shipping_cost: number;
  free_threshold: number;
  delivery_content: string;
  delivery_content_text: string;
  exchange_content: string;
  exchange_content_text: string;
  review_requires_completed_order?: boolean;
  review_requires_moderation?: boolean;
  point_use_enabled?: boolean;
  settle_min_point?: number;
  settle_max_point?: number;
  settle_point_unit?: number;
}

export interface ShopShippingQuote {
  item_total: number;
  cart_coupon: number;
  zip1: string;
  zip2: string;
  base: number;
  extra: number;
  total: number;
  free_threshold: number;
  free_remaining: number;
  policy: ShopPolicy;
}

/** 주문 상세의 현금영수증 상태: 발급 가능(available) · 신청 접수(requested) · 발급됨(issued) · 취소 필요 · 대상 아님. */
export interface ShopOrderCashReceipt {
  state: "available" | "requested" | "issued" | "cancel_needed" | "unavailable";
  can_request: boolean;
  amount: number;
  types: { value: "income" | "expense"; label: string }[];
  message: string;
  request_url: string;
}

export interface ShopOrder {
  od_id: string;
  item_count?: number;
  od_name: string;
  od_tel: string;
  od_hp: string;
  od_zip: string;
  od_addr1: string;
  od_addr2: string;
  od_addr3: string;
  od_b_name?: string;
  od_b_tel?: string;
  od_b_hp?: string;
  od_b_zip1?: string;
  od_b_zip2?: string;
  od_b_zip?: string;
  od_b_addr1?: string;
  od_b_addr2?: string;
  od_b_addr3?: string;
  od_b_addr_jibeon?: string;
  od_receipt_price: number;
  od_send_cost: number;
  od_status: string;
  od_time?: string;
  od_receipt_time: string;
  can_cancel?: boolean;
  cancel_block_reason?: string;
  od_settle_case: string;
  // 결제 결과 (PG/입금 정보). 가상계좌 결제면 od_bank_account 에 은행/계좌 안내가 들어옴.
  od_bank_account?: string;
  od_vbank_bank_code?: string;
  od_vbank_account?: string;
  od_vbank_customer_name?: string;
  od_vbank_due_date?: string;
  od_vbank_status?: string;
  od_deposit_name?: string;
  od_pg?: string;
  od_tno?: string;
  od_app_no?: string;
  od_memo?: string;
  // 쿠폰/포인트 할인 (없으면 0).
  od_cart_count?: number;
  od_cart_price?: number;
  od_cart_coupon?: number;
  od_coupon?: number;
  od_cancel_price?: number;
  od_misu?: number;
  od_receipt_point?: number;
  od_refund_price?: number;
  od_list_price?: number;
  od_order_price?: number;
  od_total_price?: number;
  od_receipt_total?: number;
  od_misu_price?: number;
  od_is_fully_paid?: boolean;
  od_total_point?: number;
  od_payment_app_label?: string;
  od_payment_app_value?: string;
  od_payment_display_bank?: boolean;
  od_payment_receipt_url?: string;
  receipt_url?: string;
  // 배송비 세분화 — od_send_cost(기본) + od_send_cost2(도서산간) - od_send_coupon(배송비 쿠폰).
  od_send_cost2?: number;
  od_send_coupon?: number;
  // 배송 추적 — 관리자가 송장번호 입력 시 노출.
  od_delivery_company?: string;
  od_invoice?: string;
  od_invoice_time?: string;
  od_delivery_inquiry_url?: string;
  delivery_inquiry_url?: string;
  /** 배송회사 문의전화(영카트 get_delivery_inquiry) — 목록에 없는 배송회사면 빈 값. */
  delivery_inquiry_tel?: string;
  // 현금영수증 — PG 발급 결과. od_cash=1 이면 발급된 상태.
  od_cash?: number;
  od_cash_request?: boolean;
  /** 현금영수증 종류: income(소득공제) · expense(지출증빙). */
  od_cash_type?: string;
  od_cash_no?: string;
  od_cash_info?: string;
  od_cash_receipt_url?: string;
  cash_receipt_url?: string;
  /** 주문 후 현금영수증 발급 신청 주소(API, POST) — 신청할 수 있을 때만 값이 있다. */
  od_cash_receipt_issue_url?: string;
  cash_receipt_issue_url?: string;
  /** 주문 상세에서만 오는 현금영수증 상태(영카트 taxsave.php). */
  cash_receipt?: ShopOrderCashReceipt | null;
  // 희망배송일 (YYYY-MM-DD), 모바일 주문 마킹, 세금계산서 신청 플래그.
  od_hope_date?: string;
  od_mobile?: number;
  od_tax_flag?: number;
  od_tax_invoice_request?: boolean;
  od_tax_mny?: number;
  od_vat_mny?: number;
  od_free_mny?: number;
  items?: ShopOrderItem[];
}

export interface ShopOrderItem {
  ct_id: string;
  it_id: string;
  it_name: string;
  it_seo_title?: string;
  ct_price: number;
  ct_qty: number;
  ct_point?: number;
  line_total?: number;
  line_point?: number;
  ct_option: string;
  ct_status: string;
  ct_stock_use?: number;
  io_type?: number;
  io_price?: number;
  ct_send_cost?: number;
  it_sc_type?: number;
  it_sc_method?: number;
  it_sc_price?: number;
  it_sc_minimum?: number;
  it_sc_qty?: number;
  image_url?: string;
}

export interface ShopWishItem {
  wi_id: string;
  it_id: string;
  it_name: string;
  it_seo_title?: string;
  it_basic_price: number;
  it_cust_price: number;
  it_tel_inq?: string;
  it_soldout?: string;
  it_use?: string;
  it_stock_qty?: number;
  option_count?: number;
  can_add_cart?: boolean;
  cart_block_reason?: string;
  image_url: string;
  wi_time: string;
}

export interface ShopReview {
  is_id: string;
  it_id: string;
  it_name?: string;
  it_seo_title?: string;
  ca_id?: string;
  it_price?: number;
  mb_id: string;
  mb_nick: string;
  is_name: string;
  is_score: number;
  is_subject: string;
  is_content: string;
  is_confirm?: string;
  is_time: string;
  product_image_url?: string;
}

export interface ShopReviewScoreSummary {
  score: number;
  count: number;
  percentage: number;
}

export interface ShopReviewSummary {
  total: number;
  average: number;
  photo_count: number;
  scores: ShopReviewScoreSummary[];
}

export interface ShopQA {
  iq_id: string;
  it_id: string;
  it_name?: string;
  it_seo_title?: string;
  ca_id?: string;
  it_price?: number;
  mb_id: string;
  mb_nick: string;
  iq_name: string;
  iq_subject: string;
  iq_question: string;
  iq_answer: string;
  iq_secret?: number;
  iq_email?: string;
  iq_hp?: string;
  is_answered?: boolean;
  can_view?: boolean;
  can_edit?: boolean;
  can_delete?: boolean;
  iq_time: string;
  product_image_url?: string;
}
