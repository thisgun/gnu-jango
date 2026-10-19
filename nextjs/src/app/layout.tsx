import type { Metadata } from "next";
import "./globals.css";
import "./solune-theme.css";
import { ThemeProvider } from "@/components/theme-provider";
import { AuthProvider } from "@/components/providers/AuthProvider";
import { NavigationProgressProvider } from "@/components/providers/NavigationProgressProvider";
import { Header } from "@/components/layout/Header";
import { Footer } from "@/components/layout/Footer";
import { CommunityInnerShell } from "@/components/layout/CommunityInnerShell";
import { ThemeSlotsProvider } from "@/components/providers/ThemeSlotsProvider";
import { themeComponents, themeConfig } from "@/lib/theme";
import { Toaster } from "@/components/ui/toaster";
import { BackToTop } from "@/components/layout/BackToTop";
import { CompareTray } from "@/components/shop/CompareTray";
import { PWAProvider } from "@/components/providers/PWAProvider";
import { WebVitals } from "@/components/WebVitals";
import { APP_BASE_URL, CLIENT_API_BASE_URL, G5_BASE_URL } from "@/lib/config";
import { getMenuItems } from "@/services/menus";
import { OrganizationJsonLd, WebSiteJsonLd } from "@/components/seo/JsonLd";
import { GoogleAnalytics } from "@/components/analytics/GoogleAnalytics";
import { LegacyRouteBridge } from "@/components/legacy-route-bridge";
import { RuntimeNavigationBridge } from "@/components/runtime-navigation-bridge";
import type { ServerUser } from "@/lib/auth-server";

const SITE_NAME = themeConfig.site.name;
const SITE_DESC = themeConfig.site.description;

function safeJsonForInlineScript(value: unknown): string {
  return (JSON.stringify(value) ?? "null").replace(/[<>&\u2028\u2029]/g, (char) => {
    switch (char) {
      case "<":
        return "\\u003c";
      case ">":
        return "\\u003e";
      case "&":
        return "\\u0026";
      case "\u2028":
        return "\\u2028";
      case "\u2029":
        return "\\u2029";
      default:
        return char;
    }
  });
}

function runtimeConfigScript(): string {
  const config = {
    apiBaseUrl: process.env.NEXT_PUBLIC_API_URL?.trim() || CLIENT_API_BASE_URL,
    g5BaseUrl: G5_BASE_URL,
    appBaseUrl: APP_BASE_URL,
  };

  return [
    `window.__G5_NEXTJS25_CONFIG__ = Object.assign(`,
    `${safeJsonForInlineScript(config)},`,
    `window.__G5_NEXTJS25_CONFIG__ || {}`,
    `);`,
  ].join("");
}

async function getInitialUserForLayout(): Promise<ServerUser | null> {
  if (process.env.G5_NEXT_RUNTIME !== "server") {
    return null;
  }

  const { getCurrentUser } = await import("@/lib/auth-server");
  return getCurrentUser();
}

export const metadata: Metadata = {
  metadataBase: new URL(APP_BASE_URL),
  title: {
    default: SITE_NAME,
    // 자식 페이지가 generateMetadata 로 title 만 넘기면 "글 제목 — 사이트명" 형태로 합성
    template: `%s — ${SITE_NAME}`,
  },
  description: SITE_DESC,
  applicationName: SITE_NAME,
  // 브라우저 탭 파비콘 — 정적 호스트의 route.php 가 icon-[0-9]+\.png 를 서빙하므로
  // 별도 favicon.ico 없이 기존 PWA 아이콘을 재사용. <link rel="icon"> 가 주입되어
  // 브라우저가 /favicon.ico 를 추가로 찾지 않게 되어 404 도 사라진다.
  icons: {
    icon: [{ url: '/icon-192.png', type: 'image/png', sizes: '192x192' }],
    shortcut: ['/icon-192.png'],
    apple: [{ url: '/icon-512.png', sizes: '512x512' }],
  },
  // 카톡 / Twitter 등 공유 시 카드 미리보기.
  openGraph: {
    type: 'website',
    siteName: SITE_NAME,
    title: SITE_NAME,
    description: SITE_DESC,
    locale: 'ko_KR',
    url: APP_BASE_URL,
    images: [
      {
        url: '/og-default.png',
        width: 1200,
        height: 630,
        alt: SITE_NAME,
      },
    ],
  },
  twitter: {
    card: 'summary_large_image',
    title: SITE_NAME,
    description: SITE_DESC,
    images: ['/og-default.png'],
  },
  robots: {
    index: true,
    follow: true,
    googleBot: { index: true, follow: true, 'max-image-preview': 'large' },
  },
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const ThemeLayoutShell = themeComponents.LayoutShell;
  const [menus, initialUser] = await Promise.all([
    // A static export is built once and served by every installation: menus fetched now would be the
    // build machine's (links to its boards). The page gets the site's menus at run time instead.
    process.env.G5_NEXT_RUNTIME === "server" ? getMenuItems() : Promise.resolve([]),
    getInitialUserForLayout(),
  ]);

  return (
    <html lang="ko" suppressHydrationWarning>
      <body data-g5-theme-source={themeConfig.name}>
        <script dangerouslySetInnerHTML={{ __html: runtimeConfigScript() }} />
        {/* SEO — Organization + WebSite SearchAction JSON-LD. 모든 페이지에 한 번씩. */}
        <OrganizationJsonLd name={SITE_NAME} />
        <WebSiteJsonLd name={SITE_NAME} />
        {/* GA4 — NEXT_PUBLIC_GA_ID 미설정 시 자동 skip. */}
        <GoogleAnalytics id={process.env.NEXT_PUBLIC_GA_ID} />
        {/* 접근성 — 키보드 사용자가 첫 Tab 으로 본문 바로 이동. */}
        <a href="#main-content" className="skip-link">본문 바로가기</a>
        <ThemeProvider
          attribute="data-theme"
          value={{ light: "gnu-default", dark: "gnu-dark" }}
          defaultTheme="light"
          disableTransitionOnChange
        >
          <NavigationProgressProvider>
            <AuthProvider initialUser={initialUser}>
              {/* 테마의 클라이언트 프레젠테이션 슬롯만 골라 컨텍스트로 넘긴다. */}
              <ThemeSlotsProvider
                slots={{ BoardViewHeader: themeComponents.BoardViewHeader }}
                features={themeConfig.features}
              >
                {ThemeLayoutShell ? (
                  <ThemeLayoutShell config={themeConfig} menus={menus}>
                    {children}
                  </ThemeLayoutShell>
                ) : (
                  <div className="min-h-screen flex flex-col">
                    <Header initialMenus={menus} initialUser={initialUser} />
                    {/* #wrapper.solune-wrapper: the reference layout's hook for inner-page styles (breadcrumb, mypage).
                        Community inner pages get the right rail here, as in the reference layout shell. */}
                    <div id="wrapper" className="solune-wrapper flex flex-1 flex-col">
                      <CommunityInnerShell>{children}</CommunityInnerShell>
                    </div>
                    <Footer />
                  </div>
                )}
              </ThemeSlotsProvider>
              <Toaster />
              {!ThemeLayoutShell && <BackToTop />}
              <CompareTray />
              <PWAProvider />
              <WebVitals />
              <LegacyRouteBridge />
              <RuntimeNavigationBridge />
            </AuthProvider>
          </NavigationProgressProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
