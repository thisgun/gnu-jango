"use client";

import {
  useEffect,
  useId,
  useState,
  type AnchorHTMLAttributes,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react";
import { G5Link as Link } from "@/components/ui/g5-link";
import { usePathname } from "next/navigation";
import Image from "next/image";
import { ChevronDown } from "lucide-react";
import { HeaderClientActions } from "@/components/layout/HeaderClientActions";
import { ShopHeaderNav } from "@/components/layout/ShopHeaderNav";
import { isExternalMenuLink, menuHref, type MenuItem } from "@/components/layout/menu";
import { buildNavigationMenus, type NavigationBoard } from "@/components/layout/navigation-menus";
import { clientNavigationBoards } from "@/lib/config";
import { useRuntimeMenus } from "@/hooks/useRuntimeMenus";
import type { ServerUser } from "@/lib/auth-server";
import { ThemeToggle } from "@/components/theme-toggle";
import { useAuthStore } from "@/store/auth";
import { runtimeRouterPush } from "@/lib/runtime-router";
import { useRouter } from "@bprogress/next/app";

function MenuLink({
  menu,
  className,
  children,
  linkProps,
}: {
  menu: MenuItem;
  className: string;
  children: ReactNode;
  linkProps?: Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href" | "className" | "children">;
}) {
  if (isExternalMenuLink(menu.me_link)) {
    return (
      <a href={menu.me_link} target="_blank" rel="noopener noreferrer" className={className} {...linkProps}>
        {children}
      </a>
    );
  }

  return (
    <Link href={menuHref(menu.me_link)} className={className} {...linkProps}>
      {children}
    </Link>
  );
}

function getMenuItems(menuId: string): HTMLElement[] {
  const menu = document.getElementById(menuId);
  if (!menu) return [];
  return Array.from(menu.querySelectorAll<HTMLElement>('[role="menuitem"]'));
}

function focusFirstMenuItem(menuId: string) {
  requestAnimationFrame(() => {
    getMenuItems(menuId)[0]?.focus();
  });
}

function moveMenuFocus(event: ReactKeyboardEvent<HTMLElement>, menuId: string, offset: number) {
  const items = getMenuItems(menuId);
  if (items.length === 0) return;

  const currentIndex = items.indexOf(event.currentTarget);
  const nextIndex = currentIndex < 0 ? 0 : (currentIndex + offset + items.length) % items.length;
  items[nextIndex]?.focus();
}

function DesktopNav({ menus }: { menus: MenuItem[] }) {
  const primaryMenus = menus.slice(0, 5);
  const [openMenuCode, setOpenMenuCode] = useState<string | null>(null);
  const idPrefix = useId();

  useEffect(() => {
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === "Escape") setOpenMenuCode(null);
    }

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, []);

  return (
    <nav className="solune-community-mega" aria-label="주 메뉴">
      <div className="solune-community-mega-list">
      {primaryMenus.map((menu) => {
        const children = menu.children ?? [];
        const hasChildren = children.length > 0;
        const isOpen = openMenuCode === menu.me_code;
        const menuId = `${idPrefix}-${menu.me_code}-menu`;

        return (
          <div
            key={menu.me_code}
            className={`solune-community-mega-item${isOpen ? " is-open" : ""}`}
            onMouseEnter={() => {
              if (hasChildren) setOpenMenuCode(menu.me_code);
            }}
            onMouseLeave={() => {
              setOpenMenuCode((current) => (current === menu.me_code ? null : current));
            }}
            onFocus={() => {
              if (hasChildren) setOpenMenuCode(menu.me_code);
            }}
            onBlur={(event) => {
              const nextTarget = event.relatedTarget as Node | null;
              if (!nextTarget || !event.currentTarget.contains(nextTarget)) {
                setOpenMenuCode((current) => (current === menu.me_code ? null : current));
              }
            }}
          >
            <MenuLink
              menu={menu}
              className="solune-community-mega-trigger"
              linkProps={
                hasChildren
                  ? {
                      "aria-haspopup": "menu",
                      "aria-expanded": isOpen,
                      "aria-controls": menuId,
                      onKeyDown: (event) => {
                        if (event.key === "Escape") {
                          setOpenMenuCode(null);
                          return;
                        }

                        if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") {
                          event.preventDefault();
                          setOpenMenuCode(menu.me_code);
                          focusFirstMenuItem(menuId);
                        }
                      },
                    }
                  : undefined
              }
            >
              {menu.me_name}
              {hasChildren && <ChevronDown className="solune-community-mega-caret size-3" />}
            </MenuLink>

            {hasChildren && (
              <div className="solune-community-mega-panel">
                <div
                  id={menuId}
                  role="menu"
                  aria-label={`${menu.me_name} 하위 메뉴`}
                  className="solune-community-mega-panel-inner"
                >
                  <div className="solune-community-mega-links">
                    {children.map((child) => (
                      <MenuLink
                        key={child.me_code}
                        menu={child}
                        className="solune-community-mega-link"
                        linkProps={{
                        role: "menuitem",
                        tabIndex: isOpen ? 0 : -1,
                        onKeyDown: (event) => {
                          if (event.key === "Escape") {
                            event.preventDefault();
                            setOpenMenuCode(null);
                            return;
                          }

                          if (event.key === "ArrowDown") {
                            event.preventDefault();
                            moveMenuFocus(event, menuId, 1);
                            return;
                          }

                          if (event.key === "ArrowUp") {
                            event.preventDefault();
                            moveMenuFocus(event, menuId, -1);
                            return;
                          }

                          if (event.key === "Home") {
                            event.preventDefault();
                            getMenuItems(menuId)[0]?.focus();
                            return;
                          }

                          if (event.key === "End") {
                            event.preventDefault();
                            const items = getMenuItems(menuId);
                            items[items.length - 1]?.focus();
                          }
                        },
                        }}
                      >
                        {child.me_name}
                      </MenuLink>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}

      </div>
    </nav>
  );
}

function CommunityMemberMenu({ initialUser }: { initialUser?: ServerUser | null }) {
  const router = useRouter();
  const { user, logout, isInitialized } = useAuthStore();
  const displayUser = isInitialized ? user : initialUser;

  async function handleLogout() {
    await logout();
    runtimeRouterPush(router, "/");
  }

  return (
    <nav aria-label="회원 메뉴" className="solune-community-member-menu">
      <Link href="/faq" className="solune-community-member-utility">FAQ</Link>
      <Link href="/qa" className="solune-community-member-utility">Q&amp;A</Link>
      <Link href="/recent" className="solune-community-member-utility">새글</Link>
      {displayUser ? (
        <>
          <Link href="/mypage" className="solune-community-member-account">마이페이지</Link>
          <button type="button" className="solune-community-member-account" onClick={() => void handleLogout()}>로그아웃</button>
        </>
      ) : (
        <>
          <Link href="/login" className="solune-community-member-account">로그인</Link>
          <Link href="/register" className="solune-community-member-signup">회원가입</Link>
        </>
      )}
      <span className="solune-community-member-theme"><ThemeToggle /></span>
    </nav>
  );
}

export function Header({
  initialMenus = [],
  initialUser = null,
}: {
  initialMenus?: MenuItem[];
  initialUser?: ServerUser | null;
}) {
  // The site's own menus and boards arrive with the page (runtime config); the export itself was
  // built elsewhere and must not decide which boards this site links to.
  const runtimeMenus = useRuntimeMenus(initialMenus);
  const [navBoards, setNavBoards] = useState<NavigationBoard[] | undefined>(undefined);
  useEffect(() => {
    setNavBoards(clientNavigationBoards());
  }, []);
  const menus = buildNavigationMenus(runtimeMenus, navBoards);
  const pathname = usePathname();
  const isShop = pathname === "/shop" || pathname.startsWith("/shop/");
  const [searchOpen, setSearchOpen] = useState(false);
  const [headerScrolled, setHeaderScrolled] = useState(false);
  const [headerCondensed, setHeaderCondensed] = useState(false);

  useEffect(() => {
    let frame = 0;
    const updateScroll = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        setHeaderScrolled(window.scrollY > 8);
        setHeaderCondensed(window.scrollY > 70);
      });
    };
    updateScroll();
    window.addEventListener("scroll", updateScroll, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("scroll", updateScroll);
    };
  }, []);

  useEffect(() => {
    setSearchOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (!searchOpen) return;
    document.getElementById("solune-community-search-input")?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setSearchOpen(false);
    };
    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [searchOpen]);

  return (
    // 바깥은 상자를 만들지 않는(display: contents) 묶음이다 — 안쪽 .solune-community-header-sticky 가 페이지 높이의
    // 부모 아래에서 sticky 로 붙어 있도록(레퍼런스 layout-shell 과 같다). 쇼핑몰 토큰은 이 묶음에서 그대로 물려받는다.
    <div className="g5-default-header">
      <div className="solune-community-header-shell">
        <div className="solune-community-service-switch">
          <div className="solune-shell solune-community-service-switch-inner">
            <nav aria-label="서비스 선택" className="solune-community-service-links">
              <Link href="/" aria-current={!isShop ? "page" : undefined} className={`solune-community-service-link${!isShop ? " solune-community-service-link-active" : ""}`}>커뮤니티</Link>
              <Link href="/shop" aria-current={isShop ? "page" : undefined} className={`solune-community-service-link${isShop ? " solune-community-service-link-active" : ""}`}>쇼핑몰</Link>
            </nav>
            {isShop ? (
              <nav aria-label="회원 메뉴" className="solune-community-member-menu">
                <Link href="/faq" className="solune-community-member-utility solune-shop-utility solune-shop-utility-faq">FAQ</Link>
                <Link href="/mypage/qas" className="solune-community-member-utility solune-shop-utility solune-shop-utility-contact">1:1 문의</Link>
                <Link href="/shop/personalpay" className="solune-community-member-utility solune-shop-utility solune-shop-utility-personalpay">개인결제</Link>
                <Link href="/shop/reviews" className="solune-community-member-utility solune-shop-utility solune-shop-utility-reviews">사용후기</Link>
                <Link href="/shop/qas" className="solune-community-member-utility solune-shop-utility solune-shop-utility-qas">상품문의</Link>
                <Link href="/shop/couponzone" className="solune-community-member-utility solune-shop-utility solune-shop-utility-couponzone">쿠폰존</Link>
                <Link href="/content/privacy" className="solune-community-member-utility solune-shop-utility solune-shop-utility-legal">개인정보 처리방침</Link>
                <span className="solune-community-member-theme"><ThemeToggle /></span>
              </nav>
            ) : <CommunityMemberMenu initialUser={initialUser} />}
          </div>
        </div>
      </div>
      <div className="solune-community-header-sticky">
        <header className={`solune-community-header${headerScrolled ? " is-scrolled" : ""}${headerCondensed ? " is-condensed" : ""}`}>
          <div className="solune-shell solune-community-mainbar">
            <Link
              href={isShop ? "/shop" : "/"}
              className="solune-community-brand"
              aria-label={isShop ? "영카트 쇼핑몰 홈" : "그누보드5 홈"}
            >
              {isShop ? (
                <Image className="solune-brand-logo solune-shop-brand-logo" src="/img/shop-logo.png" alt="영카트" width={167} height={33} priority unoptimized />
              ) : (
                <Image className="solune-brand-logo" src="/img/logo.png" alt="그누보드5" width={124} height={30} priority unoptimized />
              )}
            </Link>
            {isShop ? <ShopHeaderNav /> : <DesktopNav menus={menus} />}
            <div className={`solune-community-header-actions${isShop ? " is-shop" : ""}`}>
              <HeaderClientActions
                menus={menus}
                initialUser={initialUser}
                isCommunity={!isShop}
                searchOpen={searchOpen}
                onSearchOpenChange={setSearchOpen}
              />
            </div>
          </div>
        </header>
        {!isShop ? (
          <div id="solune-community-search-dock" className={`solune-community-search-dock${searchOpen ? " is-open" : ""}`} hidden={!searchOpen}>
            <div className="solune-shell">
              <form className="solune-community-search-panel" action="/search" method="get" role="search">
                <label className="sr-only" htmlFor="solune-community-search-input">통합 검색</label>
                <input id="solune-community-search-input" type="search" name="q" placeholder="검색어를 입력하세요" />
                <button type="submit" className="btn btn-primary btn-sm">검색</button>
              </form>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export type { MenuItem };
export default Header;
