"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { G5Link as Link } from "@/components/ui/g5-link";
import { contentHref } from "@/lib/content-links";
import { hasShopLogo, ShopLogoPicture, shopLogoSources } from "@/components/layout/ShopLogo";
import { getClientPublicSettings } from "@/services/settings";
import type { PublicSettings } from "@/lib/schemas";

type CompanyKey =
  | "cf_company_name"
  | "cf_company_owner"
  | "cf_company_addr"
  | "cf_company_biz_no"
  | "cf_company_tel"
  | "cf_company_tongsin_no"
  | "cf_company_buga_no"
  | "cf_company_fax"
  | "cf_company_info_name";

/* 레퍼런스 site-company.tsx 의 사이트 정보 항목 · 순서. 커뮤니티와 쇼핑몰이 이름표와 순서가 조금 다르다. */
const COMMUNITY_FIELDS: [CompanyKey, string][] = [
  ["cf_company_name", "회사명"],
  ["cf_company_owner", "대표"],
  ["cf_company_addr", "주소"],
  ["cf_company_biz_no", "사업자등록번호"],
  ["cf_company_tel", "전화"],
  ["cf_company_tongsin_no", "통신판매업신고번호"],
  ["cf_company_info_name", "개인정보관리책임자"],
];

const SHOP_FIELDS: [CompanyKey, string][] = [
  ["cf_company_name", "회사명"],
  ["cf_company_addr", "주소"],
  ["cf_company_biz_no", "사업자 등록번호"],
  ["cf_company_owner", "대표"],
  ["cf_company_tel", "전화"],
  ["cf_company_fax", "팩스"],
  ["cf_company_tongsin_no", "통신판매업신고번호"],
  ["cf_company_info_name", "개인정보 보호책임자"],
  ["cf_company_buga_no", "부가통신사업신고번호"],
];

/* 레퍼런스 layout-shell · shop-shell 의 FOOTER_LINKS — 내용 페이지 셋. */
const COMMUNITY_FOOTER_LINKS = [
  { label: "사이트 소개", href: contentHref("company") },
  { label: "개인정보처리방침", href: contentHref("privacy") },
  { label: "이용약관", href: contentHref("provision") },
];

const SHOP_FOOTER_LINKS = [
  { label: "회사소개", href: contentHref("company") },
  { label: "개인정보처리방침", href: contentHref("privacy") },
  { label: "이용약관", href: contentHref("provision") },
];

function isShopPath(pathname: string): boolean {
  return pathname === "/shop" || pathname.startsWith("/shop/");
}

/** 사이트 이름 · 사업자 정보 — 공개 설정에서 브라우저가 받는다(정적 테마에 한 설치본의 값을 굽지 않는다). */
function usePublicSettings(): PublicSettings | null {
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  useEffect(() => {
    let active = true;
    void getClientPublicSettings()
      .then((data) => {
        if (active) setSettings(data);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, []);
  return settings;
}

function siteTitleOf(settings: PublicSettings | null): string {
  return settings?.cf_title?.trim() || "그누보드5";
}

/** 사이트 정보(사업자 정보) — 값이 있는 항목만 dt/dd 로 늘어놓는다. 하나도 없으면 그리지 않는다(레퍼런스와 같다). */
function CompanyInfo({
  settings,
  fields,
  className,
}: {
  settings: PublicSettings | null;
  fields: [CompanyKey, string][];
  className: string;
}) {
  const rows = fields
    .map(([key, label]) => [label, settings?.[key]?.trim() || ""] as const)
    .filter(([, value]) => value !== "");
  if (rows.length === 0) return null;

  return (
    <section className={className} aria-labelledby={`${className}-title`}>
      <h2 id={`${className}-title`} className={`${className}-title`}>
        사이트 정보
      </h2>
      <dl className={`${className}-list`}>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

/**
 * 커뮤니티 푸터 — 레퍼런스 tail.layout.php(테마 layout-shell 의 ShellFooter):
 * [로고 ………… 푸터 메뉴] / 사이트 정보(사업자 정보) / [한 줄 소개 ………… 저작권].
 * 쇼핑몰은 제 레이아웃이 ShopFooter 를 .solune-shop-page 안에 그리므로 여기서는 빠진다.
 */
function Footer() {
  const settings = usePublicSettings();
  const pathname = usePathname() || "/";
  if (isShopPath(pathname)) return null;

  const siteTitle = siteTitleOf(settings);

  return (
    <footer className="solune-footer">
      <div className="solune-shell solune-footer-inner">
        <div className="solune-footer-top">
          <Link href="/" className="solune-community-brand" aria-label={`${siteTitle} 홈`}>
            <Image className="solune-brand-logo" src="/img/logo.png" alt="" width={149} height={36} unoptimized />
          </Link>
          <nav aria-label="푸터 메뉴" className="solune-footer-nav">
            {COMMUNITY_FOOTER_LINKS.map((link) => (
              <Link key={link.href} href={link.href}>
                {link.label}
              </Link>
            ))}
          </nav>
        </div>
        <CompanyInfo settings={settings} fields={COMMUNITY_FIELDS} className="solune-footer-company" />
        <div className="solune-footer-bottom">
          <p>{siteTitle}의 커뮤니티 공간입니다.</p>
          <p>
            Copyright © {new Date().getFullYear()} <strong>{siteTitle}</strong>. All rights reserved.
          </p>
        </div>
      </div>
    </footer>
  );
}

/**
 * 쇼핑몰 푸터 — 레퍼런스 shop.tail.php(테마 shop-shell 의 ShopFooter):
 * [사이트 이름 · 한 줄 소개 ………… 푸터 메뉴] / 사이트 정보 / 저작권(회사명).
 * 모양은 solune-shop.footer.css 가 .solune-shop-page 아래에서 입히므로 app/shop/layout.tsx 가 그 안에 그린다.
 */
function ShopFooter() {
  const settings = usePublicSettings();
  const siteTitle = siteTitleOf(settings);
  const owner = settings?.cf_company_name?.trim() || siteTitle;
  // 쇼핑몰 설정에서 올린 하단 로고(모바일 하단 로고는 폰 폭에서). 없으면 사이트 이름 글자를 그대로 둔다.
  const footerLogo = shopLogoSources(settings, "footer");

  return (
    <footer className="solune-shop-footer">
      <div className="solune-shop-shell solune-shop-footer-inner">
        <div className="solune-shop-footer-brand">
          <Link href="/shop" aria-label={`${siteTitle} 쇼핑몰 홈`}>
            {footerLogo.pc ? (
              <ShopLogoPicture sources={footerLogo} alt={siteTitle} className="solune-shop-footer-logo" />
            ) : hasShopLogo(footerLogo) ? (
              // 모바일 하단 로고만 올렸다: 폰 폭은 그 그림, 넓은 화면은 지금처럼 사이트 이름 글자.
              <>
                <span className="solune-shop-footer-name solune-shop-logo-wide-only">{siteTitle}</span>
                <ShopLogoPicture sources={footerLogo} alt={siteTitle} className="solune-shop-footer-logo solune-shop-logo-narrow-only" />
              </>
            ) : (
              <span className="solune-shop-footer-name">{siteTitle}</span>
            )}
          </Link>
          <p>Solune가 고른 상품과 더 나은 쇼핑 경험을 만나보세요.</p>
        </div>
        <nav className="solune-shop-footer-links" aria-label="푸터 메뉴">
          {SHOP_FOOTER_LINKS.map((link) => (
            <Link key={link.href} href={link.href}>
              {link.label}
            </Link>
          ))}
        </nav>
        <CompanyInfo settings={settings} fields={SHOP_FIELDS} className="solune-shop-footer-company" />
        <p className="solune-shop-footer-copy">
          Copyright © {new Date().getFullYear()} {owner}. All rights reserved.
        </p>
      </div>
    </footer>
  );
}

export { Footer, ShopFooter };
export default Footer;
