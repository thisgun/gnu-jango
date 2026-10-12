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
