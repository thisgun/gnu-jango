"use client";

import { useEffect, useState } from "react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ErrorState";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  UsersIcon,
  UserPlusIcon,
  FileTextIcon,
  ShoppingBagIcon,
} from "lucide-react";

interface DashboardStats {
  total_members: number;
  today_members: number;
  total_posts: number;
  today_orders: number;
}

interface RecentOrder {
  od_id: string;
  od_name: string;
  od_receipt_price: number;
  od_status: string;
  od_datetime: string;
}

interface RecentMember {
  mb_id: string;
  mb_nick: string;
  mb_email: string;
  mb_datetime: string;
}

export default function AdminDashboardPage() {
  const [stats, setStats] = useState<DashboardStats>({
    total_members: 0,
    today_members: 0,
    total_posts: 0,
    today_orders: 0,
  });
  const [recentOrders, setRecentOrders] = useState<RecentOrder[]>([]);
  const [recentMembers, setRecentMembers] = useState<RecentMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchDashboard() {
      setError(null);
      try {
        const [statsRes, ordersRes, membersRes] = await Promise.allSettled([
          api.get<DashboardStats>("/admin/dashboard/stats"),
          api.get<RecentOrder[]>("/admin/dashboard/recent-orders?limit=5"),
          api.get<RecentMember[]>("/admin/dashboard/recent-members?limit=5"),
        ]);

        const failures: string[] = [];

        if (statsRes.status === "fulfilled" && statsRes.value.data) {
          setStats(statsRes.value.data);
        } else {
          failures.push("통계");
        }

        if (ordersRes.status === "fulfilled" && ordersRes.value.data) {
          setRecentOrders(ordersRes.value.data);
        } else {
          failures.push("최근 주문");
        }

        if (membersRes.status === "fulfilled" && membersRes.value.data) {
          setRecentMembers(membersRes.value.data);
        } else {
          failures.push("최근 회원");
        }

        if (failures.length > 0) {
          setError(`${failures.join(", ")} 데이터를 불러오지 못했습니다.`);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "대시보드 데이터를 불러오지 못했습니다.");
      } finally {
        setLoading(false);
      }
    }

    fetchDashboard();
  }, []);

  const statCards = [
    {
      title: "총회원수",
      value: stats.total_members.toLocaleString(),
      icon: <UsersIcon className="size-5 text-blue-500" />,
      href: "/admin/members",
    },
    {
      title: "오늘가입",
      value: stats.today_members.toLocaleString(),
      icon: <UserPlusIcon className="size-5 text-green-500" />,
      href: "/admin/members",
    },
    {
      title: "총게시글",
      value: stats.total_posts.toLocaleString(),
      icon: <FileTextIcon className="size-5 text-purple-500" />,
      href: "/admin/boards",
    },
    {
      title: "오늘주문",
      value: stats.today_orders.toLocaleString(),
      icon: <ShoppingBagIcon className="size-5 text-orange-500" />,
      href: "/admin/shop/orders",
    },
  ];

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-muted-foreground">로딩 중...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">대시보드</h1>
      {error && (
        <ErrorState
          title="대시보드 일부 데이터를 불러오지 못했습니다"
          description={error}
          actionHref="/admin"
          className="min-h-[120px]"
        />
      )}

      {/* Stats Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {statCards.map((card) => (
          <Link key={card.title} href={card.href}>
            <Card className="hover:shadow-md transition-shadow">
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium text-muted-foreground">
                  {card.title}
                </CardTitle>
                {card.icon}
              </CardHeader>
              <CardContent>
                <p className="text-2xl font-bold">{card.value}</p>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Recent Orders */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-lg">최근 주문</CardTitle>
            <Button asChild variant="ghost" size="sm">
              <Link href="/admin/shop/orders">더보기</Link>
            </Button>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>주문번호</TableHead>
                  <TableHead>주문자</TableHead>
                  <TableHead>금액</TableHead>
                  <TableHead>상태</TableHead>
                  <TableHead>일시</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentOrders.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={5} className="text-center text-muted-foreground">
                      주문이 없습니다.
                    </TableCell>
                  </TableRow>
                ) : (
                  recentOrders.map((order) => (
                    <TableRow key={order.od_id}>
                      <TableCell>
                        <Link
                          href={`/admin/shop/orders/${order.od_id}`}
                          className="text-primary hover:underline"
                        >
                          {order.od_id}
                        </Link>
                      </TableCell>
                      <TableCell>{order.od_name}</TableCell>
                      <TableCell>{order.od_receipt_price.toLocaleString()}원</TableCell>
                      <TableCell>{order.od_status}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {order.od_datetime}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        {/* Recent Members */}
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-lg">최근 가입회원</CardTitle>
            <Button asChild variant="ghost" size="sm">
              <Link href="/admin/members">더보기</Link>
            </Button>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>아이디</TableHead>
                  <TableHead>닉네임</TableHead>
                  <TableHead>이메일</TableHead>
                  <TableHead>가입일</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentMembers.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={4} className="text-center text-muted-foreground">
                      회원이 없습니다.
                    </TableCell>
                  </TableRow>
                ) : (
                  recentMembers.map((member) => (
                    <TableRow key={member.mb_id}>
                      <TableCell>
                        <Link
                          href={`/admin/members/${member.mb_id}`}
                          className="text-primary hover:underline"
                        >
                          {member.mb_id}
                        </Link>
                      </TableCell>
                      <TableCell>{member.mb_nick}</TableCell>
                      <TableCell>{member.mb_email}</TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {member.mb_datetime}
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      {/* Quick Links */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">빠른 링크</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-3">
            <Button asChild variant="outline">
              <Link href="/admin/members">회원관리</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/admin/boards">게시판관리</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/admin/shop/products">상품관리</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/admin/shop/orders">주문관리</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/admin/shop/categories">분류관리</Link>
            </Button>
            <Button asChild variant="outline">
              <Link href="/admin/settings">환경설정</Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
