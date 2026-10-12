"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboardIcon,
  UsersIcon,
  TableIcon,
  ShoppingCartIcon,
  PackageIcon,
  ClipboardListIcon,
  FolderTreeIcon,
  SettingsIcon,
  HelpCircleIcon,
} from "lucide-react";
import { api } from "@/lib/api";
import { runtimeRouterReplace } from "@/lib/runtime-router";
import { Sidebar } from "@/components/layout/Sidebar";
import type { SidebarItem } from "@/components/layout/Sidebar";
import type { Member } from "@/lib/types";
import { applyClientPageMetadata } from "@/lib/client-metadata";
import { currentPathForRuntime } from "@/lib/config";

interface AuthMeResponse {
  member?: Member;
  authenticated?: boolean;
  is_super_admin?: boolean;
}

const adminNavItems: SidebarItem[] = [
  {
    href: "/admin",
    label: "대시보드",
    icon: <LayoutDashboardIcon className="size-4" />,
  },
  {
    href: "/admin/members",
    label: "회원관리",
    icon: <UsersIcon className="size-4" />,
  },
  {
    href: "/admin/boards",
    label: "게시판관리",
    icon: <TableIcon className="size-4" />,
  },
  {
    href: "/admin/qas",
    label: "1:1 문의",
    icon: <HelpCircleIcon className="size-4" />,
  },
  {
    href: "/admin/shop",
    label: "쇼핑몰",
    icon: <ShoppingCartIcon className="size-4" />,
    children: [
      {
        href: "/admin/shop/products",
        label: "상품",
        icon: <PackageIcon className="size-4" />,
      },
      {
        href: "/admin/shop/orders",
        label: "주문",
        icon: <ClipboardListIcon className="size-4" />,
      },
      {
        href: "/admin/shop/categories",
        label: "분류",
        icon: <FolderTreeIcon className="size-4" />,
      },
    ],
  },
  {
    href: "/admin/settings",
    label: "환경설정",
    icon: <SettingsIcon className="size-4" />,
  },
];

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [authorized, setAuthorized] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    applyClientPageMetadata({
      title: "Admin",
      description: "그누보드5 admin console",
      path: currentPathForRuntime(pathname || "/admin"),
    });
  }, [pathname]);

  useEffect(() => {
    const loginRedirect = `/login?redirect=${encodeURIComponent(pathname || "/admin")}`;

    async function checkAdmin() {
      if (!api.hasAuthHint()) {
        runtimeRouterReplace(router, loginRedirect);
        setLoading(false);
        return;
      }

      try {
        const res = await api.get<AuthMeResponse>("/auth/me");
        const member = res.data?.member;
        const isAdmin = !!res.data?.is_super_admin;
        if (!member) {
          runtimeRouterReplace(router, loginRedirect);
          return;
        }
        if (!isAdmin) {
          runtimeRouterReplace(router, "/");
          return;
        }

        setAuthorized(true);
      } catch {
        runtimeRouterReplace(router, loginRedirect);
      } finally {
        setLoading(false);
      }
    }

    checkAdmin();
  }, [pathname, router]);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-muted-foreground">로딩 중...</p>
      </div>
    );
  }

  if (!authorized) {
    return null;
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar title="관리자" items={adminNavItems} className="hidden md:flex" />
      <main className="flex-1 overflow-y-auto p-6">{children}</main>
    </div>
  );
}
