import {
  api,
  type ShopCartResponse,
  type ShopPolicy,
  type ShopShippingQuote,
} from "@/lib/api";
import { getShopPolicy, getShopShippingQuote } from "@/services/shop";
import type { SavedAddress } from "./orderAddressHelpers";
import {
  buildCartRequestOptions,
  buildShippingQuoteParams,
  type OrderMember,
} from "./orderDataHelpers";
import type { PaymentConfig } from "./orderPaymentHelpers";
import type { MyCoupon, PointSummary } from "./orderPricingHelpers";

type LoadOrderInitialDataInput = {
  directCheckout: boolean;
  directCtIds: string;
};

type LoadOrderInitialDataResult = {
  cartData: ShopCartResponse | undefined;
  paymentConfig: PaymentConfig | null;
  shippingPolicy: ShopPolicy | null;
  member: OrderMember | undefined;
  savedAddresses: SavedAddress[];
};

type LoadShippingQuoteInput = {
  shippingZip: string;
  directCheckout: boolean;
  directCtIds: string;
};

const ORDER_LOOKUP_PAGE_SIZE = 100;
const ORDER_LOOKUP_CONCURRENCY = 5;

async function loadAllPages<T>(
  path: string,
  extraParams: Record<string, string | number> = {}
): Promise<T[]> {
  const firstPage = await api.get<T[]>(path, {
    params: { ...extraParams, page: 1, per_page: ORDER_LOOKUP_PAGE_SIZE },
  });
  const firstItems = firstPage.data;
  if (!Array.isArray(firstItems)) {
    throw new Error(`Expected a list response from ${path}.`);
  }

  const lastPage = Math.max(1, firstPage.meta?.last_page ?? 1);
  const items = [...firstItems];

  for (
    let firstPageNumber = 2;
    firstPageNumber <= lastPage;
    firstPageNumber += ORDER_LOOKUP_CONCURRENCY
  ) {
    const pages = await Promise.all(
      Array.from(
        {
          length: Math.min(
            ORDER_LOOKUP_CONCURRENCY,
            lastPage - firstPageNumber + 1
          ),
        },
        (_, index) =>
          api.get<T[]>(path, {
            params: {
              ...extraParams,
              page: firstPageNumber + index,
              per_page: ORDER_LOOKUP_PAGE_SIZE,
            },
          })
      )
    );

    for (const page of pages) {
      if (!Array.isArray(page.data)) {
        throw new Error(`Expected a list response from ${path}.`);
      }
      items.push(...page.data);
    }
  }

  return items;
}

export async function loadOrderInitialData({
  directCheckout,
  directCtIds,
}: LoadOrderInitialDataInput): Promise<LoadOrderInitialDataResult> {
  const [cartRes, payCfgRes, policyRes] = await Promise.all([
    api.get<ShopCartResponse>(
      "/shop/cart",
      buildCartRequestOptions(directCheckout, directCtIds)
    ),
    api.get<PaymentConfig>("/shop/payment/config").catch(() => null),
    getShopPolicy().catch(() => null),
  ]);

  const cartData = cartRes.data;
  const hasCartItems = (cartData?.items?.length ?? 0) > 0;
  const shouldLoadMember = hasCartItems && api.hasAuthHint();
  const meRes = shouldLoadMember
    ? await api.get<{ member: OrderMember | null }>("/auth/me").catch(() => null)
    : null;
  const member = meRes?.data?.member ?? undefined;
  const savedAddresses = member
    ? await loadAllPages<SavedAddress>("/shop/addresses").catch(() => [])
    : [];

  return {
    cartData,
    paymentConfig: payCfgRes?.data ?? null,
    shippingPolicy: policyRes,
    member,
    savedAddresses,
  };
}

export async function loadMemberOrderBenefits(): Promise<{
  coupons?: MyCoupon[];
  pointBalance?: number;
  couponsLoadFailed: boolean;
  pointLoadFailed: boolean;
}> {
  const [couponRes, pointRes] = await Promise.allSettled([
    // Only coupons that can still be used: unused and inside their validity period.
    loadAllPages<MyCoupon>("/shop/coupons/mine", { usable: 1 }),
    api.get<PointSummary>("/shop/points/summary"),
  ]);
  const coupons =
    couponRes.status === "fulfilled" && Array.isArray(couponRes.value)
      ? couponRes.value
      : undefined;
  const pointBalance =
    pointRes.status === "fulfilled" &&
    typeof pointRes.value.data?.balance === "number"
      ? pointRes.value.data.balance
      : undefined;

  return {
    coupons,
    pointBalance,
    couponsLoadFailed: couponRes.status === "rejected",
    pointLoadFailed: pointRes.status === "rejected",
  };
}

export function loadShippingQuote({
  shippingZip,
  directCheckout,
  directCtIds,
}: LoadShippingQuoteInput): Promise<ShopShippingQuote | null> {
  return getShopShippingQuote(
    buildShippingQuoteParams({ shippingZip, directCheckout, directCtIds })
  );
}
