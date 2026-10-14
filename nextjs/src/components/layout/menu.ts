import { g5ShortHref } from "@/lib/g5-short-url";

export interface MenuItem {
  me_id: number;
  me_code: string;
  me_name: string;
  me_link: string;
  me_target: string;
  children?: MenuItem[];
}

export function isExternalMenuLink(link: string): boolean {
  return /^https?:\/\//.test(link);
}

export function menuHref(link: string): string {
  const href = link.trim();
  if (!href || isExternalMenuLink(href)) return href;
  if (/^(#|mailto:|tel:|javascript:)/i.test(href)) return href;

  return g5ShortHref(href.startsWith("/") ? href : `/${href}`);
}

export function isUnsafeMenuLink(link: string): boolean {
  return /^\s*javascript:/i.test(link);
}

export function menuAnchorTarget(target?: string): "_blank" | undefined {
  return target?.trim().replace(/^_/, "") === "blank" ? "_blank" : undefined;
}

export type MenuNavLink = { href: string; target?: "_blank" };

/**
 * 관리자 메뉴 하나가 화면에서 쓸 링크. 링크가 비었거나 위험하거나 제자리("#")면 그 링크는 쓰지 않되, 메뉴를 빼면
 * 하위 메뉴까지 사라지므로(메뉴 동기화 규칙: 관리자 메뉴를 임의로 지우지 않고, 상위 메뉴도 링크다) 첫 하위 메뉴의
 * 링크(제자리가 아닌 첫 하위 메뉴)로 잇는다. children 은 이미 화면용으로 바꾼 하위 메뉴다.
 */
export function menuNavLink(menu: Pick<MenuItem, "me_link" | "me_target">, children: MenuNavLink[]): MenuNavLink | null {
  const raw = (menu.me_link || "").trim();
  const target = menuAnchorTarget(menu.me_target);
  if (isUsableMenuLink(raw)) return { href: menuHref(raw), target };
  const first = children.find((child) => isUsableMenuLink(child.href));
  if (first) return { href: first.href, target: first.target };
  // 이을 하위 메뉴가 없으면 — 제자리("#")는 관리자가 둔 그대로 두고(빼지 않는다), 빈 · 위험한 링크는 보일 것이 없어 null.
  return raw === "#" ? { href: "#", target } : null;
}

/** 실제로 어딘가로 가는 링크인지 — 빈 값 · 위험한 값 · 제자리("#", 그누보드에서 묶음 이름만 둘 때 흔하다)는 아니다. */
function isUsableMenuLink(link: string): boolean {
  const value = link.trim();
  return value !== "" && value !== "#" && !isUnsafeMenuLink(value);
}
