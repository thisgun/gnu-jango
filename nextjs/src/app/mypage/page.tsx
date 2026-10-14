"use client";

import Image from "next/image";
import { useEffect, useState } from "react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { ShopOrder, ShopWishItem } from "@/lib/api";
import type { BbsRewriteMode } from "@/lib/board-url";
import { formatDate, formatPrice } from "@/lib/utils";
import { shopProductHref } from "@/lib/product-url";
import {
  getMyDashboardCounts,
  getMyOrders,
  type MyDashboardCounts,
} from "@/services/member";
import { getWishlist } from "@/services/cart";
import { getClientPublicSettings } from "@/services/settings";
import { useAuthStore } from "@/store/auth";
import {
  ShoppingBag,
  Heart,
  Bookmark,
  FileText,
  MessageSquare,
  MapPin,
  Coins,
  Ticket,
} from "lucide-react";

type LoadState = "loading" | "loaded" | "error";

const ORDER_STATUS: Record<string, { label: string; className: string }> = {
  주문: { label: "입금확인중", className: "badge-warning" },
  입금대기: { label: "입금확인중", className: "badge-warning" },
  입금: { label: "입금완료", className: "badge-info" },
  결제완료: { label: "입금완료", className: "badge-info" },
  준비: { label: "상품준비중", className: "badge-neutral" },
  배송준비: { label: "상품준비중", className: "badge-neutral" },
  배송: { label: "상품배송", className: "badge-primary" },
  배송중: { label: "상품배송", className: "badge-primary" },
  완료: { label: "배송완료", className: "badge-success" },
  배송완료: { label: "배송완료", className: "badge-success" },
  취소: { label: "주문취소", className: "badge-error" },
};

function orderAmount(order: ShopOrder) {
  return (
    order.od_list_price ??
    order.od_order_price ??
    Math.max(
      0,
      (order.od_cart_price ?? 0) +
        (order.od_send_cost ?? 0) +
        (order.od_send_cost2 ?? 0),
    )
  );
}

function OrderStatus({ status }: { status: string }) {
  const config = ORDER_STATUS[status] ?? {
    label: status || "주문취소",
    className: "badge-error",
  };

  return <span className={`badge badge-sm ${config.className}`}>{config.label}</span>;
}

function LoadingMessage({ children }: { children: string }) {
  return (
    <div className="flex items-center gap-3 py-6 text-sm text-base-content/70" role="status">
      <span className="loading loading-spinner loading-sm text-primary" aria-hidden="true" />
      {children}
    </div>
  );
}

export default function MyPageDashboard() {
  const user = useAuthStore((state) => state.user);
  const userId = user?.mb_id ?? "";
  const [counts, setCounts] = useState<MyDashboardCounts>({
    orders: 0,
    wishlist: 0,
    scraps: 0,
    posts: 0,
    comments: 0,
    addresses: 0,
    coupons: 0,
  });
  const [loading, setLoading] = useState(true);
  const [recentOrders, setRecentOrders] = useState<ShopOrder[]>([]);
  const [recentWishlist, setRecentWishlist] = useState<ShopWishItem[]>([]);
  const [ordersState, setOrdersState] = useState<LoadState>("loading");
  const [wishlistState, setWishlistState] = useState<LoadState>("loading");
  const [productRewriteMode, setProductRewriteMode] = useState<BbsRewriteMode>(0);

  useEffect(() => {
    if (!userId) {
      setLoading(false);
      return;
    }

    let alive = true;
    setLoading(true);

    getMyDashboardCounts()
      .then((nextCounts) => {
        if (alive) setCounts(nextCounts);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });

    return () => {
      alive = false;
    };
  }, [userId]);

  useEffect(() => {
    if (!userId) {
      setRecentOrders([]);
      setRecentWishlist([]);
      setOrdersState("loaded");
      setWishlistState("loaded");
      return;
    }

    let alive = true;
    setOrdersState("loading");
    setWishlistState("loading");

    getMyOrders(1, 5)
      .then((result) => {
        if (!alive) return;
        setRecentOrders(result.orders.slice(0, 5));
        setOrdersState("loaded");
      })
      .catch(() => {
        if (alive) setOrdersState("error");
      });

    getWishlist(1, 8)
      .then((items) => {
        if (!alive) return;
        setRecentWishlist(items.slice(0, 8));
        setWishlistState("loaded");
      })
      .catch(() => {
        if (alive) setWishlistState("error");
      });

    getClientPublicSettings()
      .then((settings) => {
        if (alive) setProductRewriteMode(settings.cf_bbs_rewrite);
      })
      .catch(() => {
        if (alive) setProductRewriteMode(0);
      });

    return () => {
      alive = false;
    };
  }, [userId]);

  const cards = [
    {
      href: "/mypage/orders",
      title: "주문 내역",
      count: counts.orders,
      icon: ShoppingBag,
      color: "text-blue-600",
    },
    {
      href: "/mypage/wishlist",
      title: "위시리스트",
      count: counts.wishlist,
      icon: Heart,
      color: "text-red-600",
    },
    {
      href: "/mypage/scraps",
      title: "스크랩",
      count: counts.scraps,
      icon: Bookmark,
      color: "text-cyan-600",
    },
    {
      href: "/mypage/posts",
      title: "내 게시글",
      count: counts.posts,
      icon: FileText,
      color: "text-green-700",
    },
    {
      href: "/mypage/comments",
      title: "내 댓글",
      count: counts.comments,
      icon: MessageSquare,
      color: "text-purple-600",
    },
    {
      href: "/mypage/addresses",
      title: "배송지",
      count: counts.addresses,
      icon: MapPin,
      color: "text-amber-700",
    },
    {
      href: "/mypage/points",
      title: "포인트",
      count: user?.mb_point ?? 0,
      icon: Coins,
      color: "text-yellow-600",
      suffix: "점",
    },
    {
      href: "/mypage/coupons",
      title: "사용 가능 쿠폰",
      count: counts.coupons,
      icon: Ticket,
      color: "text-orange-600",
    },
  ];

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold">대시보드</h2>

      {/* 레퍼런스 대시보드의 mypage-stats · mypage-stat-card 손잡이 — 숫자 카드마다 제 색 아이콘. */}
      <div className="mypage-stats grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cards.map((card) => {
          const Icon = card.icon;
          return (
            <Link key={card.href} href={card.href}>
              <Card className="mypage-stat-card transition-shadow hover:shadow-md">
                <CardHeader className="pb-2">
                  <CardTitle className="flex items-center justify-between text-sm font-medium text-muted-foreground">
                    {card.title}
                    <Icon className={`h-5 w-5 ${card.color}`} aria-hidden="true" />
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-2xl font-bold">
                    {loading
                      ? "..."
                      : `${card.count.toLocaleString()}${card.suffix ?? ""}`}
                  </p>
                </CardContent>
              </Card>
            </Link>
          );
        })}
      </div>

      <section className="card border border-base-300 bg-base-100" aria-labelledby="recent-orders-title">
        <div className="card-body gap-4 p-4 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="recent-orders-title" className="card-title text-lg">최근 주문내역</h2>
            <Link className="link link-primary text-sm" href="/mypage/orders">
              주문 내역 더보기
            </Link>
          </div>

          {ordersState === "loading" ? (
            <LoadingMessage>최근 주문을 불러오는 중입니다.</LoadingMessage>
          ) : ordersState === "error" ? (
            <p className="py-6 text-sm text-base-content/70" role="alert">
              최근 주문을 불러오지 못했습니다. 전체 주문 내역에서 다시 확인해 주세요.
            </p>
          ) : recentOrders.length === 0 ? (
            <p className="py-6 text-sm text-base-content/70">주문 내역이 없습니다.</p>
          ) : (
            <div className="overflow-x-auto rounded-box border border-base-300">
              <table className="table table-zebra table-sm sm:table-md">
                <thead>
                  <tr>
                    <th scope="col">주문서번호</th>
                    <th scope="col">주문일시</th>
                    <th scope="col" className="text-right">상품 수</th>
                    <th scope="col" className="text-right">주문금액</th>
                    <th scope="col" className="text-right">입금액</th>
                    <th scope="col" className="text-right">미입금액</th>
                    <th scope="col">상태</th>
                  </tr>
                </thead>
                <tbody>
                  {recentOrders.map((order) => {
                    const itemCount = order.od_cart_count ?? order.item_count ?? 0;
                    const unpaid = order.od_misu ?? order.od_misu_price ?? 0;
                    return (
                      <tr key={order.od_id}>
                        <th scope="row">
                          <Link className="link link-hover whitespace-nowrap font-mono" href={`/shop/orders/${encodeURIComponent(order.od_id)}`}>
                            {order.od_id}
                          </Link>
                        </th>
                        <td className="whitespace-nowrap">
                          {formatDate(order.od_time || order.od_receipt_time)}
                        </td>
                        <td className="text-right">{itemCount.toLocaleString()}</td>
                        <td className="whitespace-nowrap text-right">{formatPrice(orderAmount(order))}</td>
                        <td className="whitespace-nowrap text-right">{formatPrice(order.od_receipt_price)}</td>
                        <td className={`whitespace-nowrap text-right ${unpaid > 0 ? "text-error" : ""}`}>
                          {formatPrice(unpaid)}
                        </td>
                        <td><OrderStatus status={order.od_status} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      <section className="card border border-base-300 bg-base-100" aria-labelledby="recent-wishlist-title">
        <div className="card-body gap-4 p-4 sm:p-6">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 id="recent-wishlist-title" className="card-title text-lg">최근 위시리스트</h2>
            <Link className="link link-primary text-sm" href="/mypage/wishlist">
              위시리스트 더보기
            </Link>
          </div>

          {wishlistState === "loading" ? (
            <LoadingMessage>위시리스트를 불러오는 중입니다.</LoadingMessage>
          ) : wishlistState === "error" ? (
            <p className="py-6 text-sm text-base-content/70" role="alert">
              위시리스트를 불러오지 못했습니다. 전체 위시리스트에서 다시 확인해 주세요.
            </p>
          ) : recentWishlist.length === 0 ? (
            <p className="py-6 text-sm text-base-content/70">보관 내역이 없습니다.</p>
          ) : (
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {recentWishlist.map((item) => (
                <li key={item.wi_id}>
                  <Link
                    className="card h-full border border-base-300 bg-base-100 transition-shadow hover:shadow-md"
                    href={shopProductHref(item, productRewriteMode)}
                  >
                    <div className="relative aspect-square overflow-hidden rounded-t-box bg-base-200">
                      {item.image_url ? (
                        <Image
                          src={item.image_url}
                          alt={item.it_name}
                          fill
                          className="object-cover"
                          sizes="(max-width: 640px) 50vw, 25vw"
                        />
                      ) : (
                        <div className="flex h-full items-center justify-center text-sm text-base-content/60">
                          이미지 없음
                        </div>
                      )}
                    </div>
                    <div className="card-body gap-1 p-3">
                      <h3 className="line-clamp-2 min-h-10 text-sm font-medium">{item.it_name}</h3>
                      <p className="text-sm font-bold">{formatPrice(item.it_basic_price)}</p>
                      <time className="text-xs text-base-content/60" dateTime={item.wi_time}>
                        {formatDate(item.wi_time)}
                      </time>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </div>
      </section>
    </div>
  );
}
