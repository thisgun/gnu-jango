"use client";

import { G5Link as Link } from "@/components/ui/g5-link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuthStore } from "@/store/auth";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { cn } from "@/lib/utils";
import {
  User,
  Lock,
  FileText,
  MessageSquare,
  ShoppingBag,
  Heart,
  MapPin,
  Coins,
  Ticket,
  Star,
  LayoutDashboard,
  Mail,
  Bookmark,
  HelpCircle,
  MonitorSmartphone,
} from "lucide-react";
import { Breadcrumb } from "@/components/ui/breadcrumb";
import { formatDate } from "@/lib/utils";
import { getMyMemberDetails, getMyUsableCouponCount } from "@/services/member";
import type { MyMemberDetails } from "@/lib/types";

interface MenuItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
}

interface MenuGroup {
  title: string;
  items: MenuItem[];
}

const MENU_GROUPS: MenuGroup[] = [
  {
    title: "내 정보",
    items: [
      { href: "/mypage", label: "대시보드", icon: LayoutDashboard },
      { href: "/mypage/profile", label: "프로필 수정", icon: User },
      { href: "/mypage/password", label: "비밀번호 변경", icon: Lock },
      { href: "/mypage/sessions", label: "로그인 기기", icon: MonitorSmartphone },
    ],
  },
  {
    title: "커뮤니티",
    items: [
      { href: "/mypage/posts", label: "내 게시글", icon: FileText },
      { href: "/mypage/comments", label: "내 댓글", icon: MessageSquare },
      { href: "/mypage/scraps", label: "스크랩", icon: Bookmark },
      { href: "/mypage/memos", label: "쪽지함", icon: Mail },
      { href: "/mypage/qas", label: "1:1 문의", icon: HelpCircle },
    ],
  },
  {
    title: "쇼핑몰",
    items: [
      { href: "/mypage/orders", label: "주문 내역", icon: ShoppingBag },
      { href: "/mypage/reviews", label: "상품후기", icon: Star },
      { href: "/mypage/wishlist", label: "위시리스트", icon: Heart },
      { href: "/mypage/shop-qas", label: "상품문의", icon: HelpCircle },
      { href: "/mypage/addresses", label: "배송지 관리", icon: MapPin },
      { href: "/mypage/points", label: "포인트 내역", icon: Coins },
      { href: "/mypage/coupons", label: "쿠폰함", icon: Ticket },
    ],
  },
];

export default function MyPageLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, isInitialized } = useAuthStore();
  const [memberDetails, setMemberDetails] = useState<MyMemberDetails | null>(null);
  const [usableCouponCount, setUsableCouponCount] = useState<number | null>(null);

  useEffect(() => {
    if (!user?.mb_id) {
      setMemberDetails(null);
      setUsableCouponCount(null);
      return;
    }

    let alive = true;
    getMyMemberDetails()
      .then((details) => {
        if (alive) setMemberDetails(details);
      })
      .catch(() => {
        if (alive) setMemberDetails(null);
      });
    getMyUsableCouponCount()
      .then((count) => {
        if (alive) setUsableCouponCount(count);
      })
      .catch(() => {
        if (alive) setUsableCouponCount(null);
      });

    return () => {
      alive = false;
    };
  }, [user?.mb_id]);

  useEffect(() => {
    if (isInitialized && !user) {
      const redirect = pathname || "/mypage";
      runtimeRouterPush(router, `/login?redirect=${encodeURIComponent(redirect)}`);
    }
  }, [isInitialized, pathname, user, router]);

  if (!isInitialized) {
    return (
      <div className="container mx-auto max-w-6xl px-4 py-8">
        <div className="animate-pulse">
          <div className="mb-6 h-8 w-40 rounded bg-muted" />
          <div className="h-32 rounded-lg bg-muted" />
        </div>
      </div>
    );
  }

  if (!user) {
    return null;
  }

  // Find current menu label for breadcrumb
  const allItems = MENU_GROUPS.flatMap((g) => g.items);
  const currentItem = allItems.find(
    (item) =>
      pathname === item.href ||
      (item.href !== "/mypage" && pathname.startsWith(item.href))
  );
  const breadcrumbItems = [
    { label: "마이페이지", href: "/mypage" },
    ...(currentItem && currentItem.href !== "/mypage"
      ? [{ label: currentItem.label }]
      : []),
  ];

  return (
    <div className="container mx-auto max-w-6xl px-4 py-8">
      <Breadcrumb items={breadcrumbItems} />

      {/* Member Overview Card */}
      <div className="mb-6 rounded-lg border bg-card p-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold">
              {user.mb_nick || user.mb_name}
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                ({user.mb_id})
              </span>
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {user.mb_email}
            </p>
          </div>
          <div className="flex gap-6 text-sm">
            <div>
              <p className="text-muted-foreground">레벨</p>
              <p className="text-lg font-bold">{user.mb_level}</p>
            </div>
            <div>
              <p className="text-muted-foreground">포인트</p>
              <p className="text-lg font-bold text-primary">
                {(user.mb_point ?? 0).toLocaleString()}점
              </p>
            </div>
            <div>
              <p className="text-muted-foreground">사용 가능 쿠폰</p>
              <Link href="/mypage/coupons" className="link link-primary text-lg font-bold">
                {usableCouponCount === null ? "확인 중" : `${usableCouponCount.toLocaleString()}장`}
              </Link>
            </div>
          </div>
        </div>
        <details className="collapse collapse-arrow mt-4 rounded-box border border-base-300 bg-base-100">
          <summary className="collapse-title min-h-0 px-4 py-3 text-sm font-semibold">
            회원 상세 정보
          </summary>
          <div className="collapse-content px-4 pb-4">
            <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-base-content/70">연락처</dt>
                <dd>{memberDetails?.mb_hp || memberDetails?.mb_tel || "미등록"}</dd>
              </div>
              <div>
                <dt className="text-base-content/70">최근 접속</dt>
                <dd>{memberDetails?.mb_today_login ? formatDate(memberDetails.mb_today_login) : "기록 없음"}</dd>
              </div>
              <div>
                <dt className="text-base-content/70">가입일</dt>
                <dd>{memberDetails?.mb_datetime ? formatDate(memberDetails.mb_datetime) : "기록 없음"}</dd>
              </div>
              <div>
                <dt className="text-base-content/70">주소</dt>
                <dd>
                  {memberDetails
                    ? [
                        memberDetails.mb_zip ? `(${memberDetails.mb_zip})` : "",
                        memberDetails.mb_addr1,
                        memberDetails.mb_addr2,
                        memberDetails.mb_addr3,
                      ]
                        .filter(Boolean)
                        .join(" ") || "미등록"
                    : "불러오는 중…"}
                </dd>
              </div>
            </dl>
          </div>
        </details>
      </div>

      <div className="grid gap-6 md:grid-cols-[220px_1fr]">
        {/* Sidebar */}
        <aside>
          <nav className="sticky top-4 space-y-6 rounded-lg border bg-card p-4">
            {MENU_GROUPS.map((group) => (
              <div key={group.title}>
                <h3 className="mb-2 px-2 text-xs font-semibold uppercase text-muted-foreground">
                  {group.title}
                </h3>
                <ul className="space-y-1">
                  {group.items.map((item) => {
                    const Icon = item.icon;
                    const isActive =
                      pathname === item.href ||
                      (item.href !== "/mypage" && pathname.startsWith(item.href));
                    return (
                      <li key={item.href}>
                        <Link
                          href={item.href}
                          className={cn(
                            "flex items-center gap-2 rounded-md px-2 py-2 text-sm transition-colors",
                            isActive
                              ? "bg-primary/10 font-medium text-[hsl(var(--primary-accessible))]"
                              : "text-muted-foreground hover:bg-accent hover:text-foreground"
                          )}
                        >
                          <Icon className="h-4 w-4" />
                          {item.label}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
          </nav>
        </aside>

        {/* Main Content */}
        <main className="min-w-0">{children}</main>
      </div>
    </div>
  );
}
