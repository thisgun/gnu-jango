"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { G5Link as Link } from "@/components/ui/g5-link";
import { DEFAULT_CONTENT_LINKS, contentHref } from "@/lib/content-links";
import { getClientPublicSettings } from "@/services/settings";
import type { PublicSettings } from "@/lib/schemas";

const communityFooterLinks = [
  { href: "/faq", label: "FAQ" },
  { href: "/qa", label: "Q&A" },
  { href: "/recent", label: "새글" },
  ...DEFAULT_CONTENT_LINKS.map((link) => ({ href: contentHref(link.co_id), label: link.label })),
];

const shopFooterLinks = [
  { href: "/shop", label: "쇼핑몰 홈" },
  { href: "/shop/products", label: "전체 상품" },
  { href: "/shop/reviews", label: "상품 후기" },
  { href: "/shop/qas", label: "상품 문의" },
  { href: "/shop/orders", label: "주문 조회" },
  ...DEFAULT_CONTENT_LINKS.map((link) => ({ href: contentHref(link.co_id), label: link.label })),
];

function Footer() {
  const [settings, setSettings] = useState<PublicSettings | null>(null);
  const pathname = usePathname();
  const isShop = pathname === "/shop" || pathname.startsWith("/shop/");

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

  const siteTitle = settings?.cf_title?.trim() || "그누보드5";
  const brandTitle = isShop ? "youngcart" : siteTitle;
  const companyDetails = [
    ["회사명", settings?.cf_company_name],
    ["대표", settings?.cf_company_owner],
    ["주소", settings?.cf_company_addr],
    ["사업자등록번호", settings?.cf_company_biz_no],
    ["전화", settings?.cf_company_tel],
    ["통신판매업 신고번호", settings?.cf_company_tongsin_no],
    ["개인정보관리책임자", settings?.cf_company_info_name],
    ["정보관리책임자 이메일", settings?.cf_company_email],
  ].filter(([, value]) => Boolean(value?.trim()));

  return (
    <footer className="solune-footer">
      <div className="solune-shell solune-footer-inner">
        <div className="solune-footer-top">
          <div>
            <Link href={isShop ? "/shop" : "/"} className="solune-brand-name">{brandTitle}</Link>
            <p className="solune-footer-description">
              {isShop ? "youngcart 쇼핑몰" : `${siteTitle} 커뮤니티`}
            </p>
          </div>
          <nav className="solune-footer-nav" aria-label={isShop ? "쇼핑몰 하단 메뉴" : "하단 메뉴"}>
            {(isShop ? shopFooterLinks : communityFooterLinks).map((link) => <Link href={link.href} key={link.href}>{link.label}</Link>)}
          </nav>
        </div>
        <div className="solune-footer-company">
          <h2 className="solune-footer-company-title">{isShop ? "쇼핑몰 사업자 정보" : "사이트 정보"}</h2>
          <dl className="solune-footer-company-list">
            {companyDetails.length ? companyDetails.map(([label, value]) => (
              <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
            )) : (
              <>
                <div><dt>서비스</dt><dd>{isShop ? "youngcart 쇼핑몰" : `${siteTitle} 커뮤니티`}</dd></div>
                <div><dt>고객센터</dt><dd><Link href={isShop ? "/shop/qas" : "/qa"}>{isShop ? "상품 문의" : "문의하기"}</Link></dd></div>
              </>
            )}
          </dl>
        </div>
        <div className="solune-footer-bottom">
          <p>© {new Date().getFullYear()} {brandTitle}. All rights reserved.</p>
          <p>Powered by Gnuboard5</p>
        </div>
      </div>
    </footer>
  );
}

export { Footer };
export default Footer;
