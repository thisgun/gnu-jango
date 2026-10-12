import type { MetadataRoute } from 'next';
import { APP_BASE_URL } from '@/lib/config';

export const dynamic = 'force-static';

export default function robots(): MetadataRoute.Robots {
  const base = APP_BASE_URL.replace(/\/+$/, '');
  return {
    rules: [
      {
        userAgent: '*',
        allow: '/',
        // 로그인 / 회원 영역은 크롤링 막기 — 검색 엔진이 인증 페이지를 인덱싱하면
        // 빈 페이지가 노출됨.
        disallow: [
          '/login',
          '/register',
          '/forgot-password',
          '/mypage',
          '/admin',
          '/api',
          // 쇼핑 — 개인 장바구니/주문/결제 흐름은 인덱싱 불필요.
          '/shop/cart',
          '/shop/order',
          '/shop/orders',
          '/shop/payment',
          '/shop/personalpay',
          '/shop/search',
          '/shop/wishlist',
        ],
      },
      // bad-bot 들 명시 차단 — 필요하면 운영자가 NEXT_BLOCKED_BOTS 환경변수로 추가.
    ],
    sitemap: [`${base}/sitemap.xml`, `${base}/sitemap-posts.xml`],
    host: base,
  };
}
