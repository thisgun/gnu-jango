import type { NextConfig } from 'next';
import bundleAnalyzer from '@next/bundle-analyzer';
import { withSentryConfig } from '@sentry/nextjs';

const withBundleAnalyzer = bundleAnalyzer({
  enabled: process.env.ANALYZE === 'true',
});

const STATIC_EXPORT = process.env.G5_NEXT_RUNTIME !== 'server';
const shortBoardSegment =
  ':bo_table((?!__g5_static__$|admin/|admin$|api/|api$|baby/|baby$|bbs/|bbs$|boards/|boards$|content/|content$|faq/|faq$|login/|login$|members/|members$|mobile/|mobile$|mypage/|mypage$|offline/|offline$|polls/|polls$|recent/|recent$|register/|register$|rss/|rss$|search/|search$|shop/|shop$)[A-Za-z0-9_]+)';
// Board pages are published under /bbs/<bo_table>[/<wr_id>|/write]; board names may be Korean, and
// bbs/*.php stays the Gnuboard5 file handler (src/app/bbs/[...path]/route.ts).
const bbsBoardSegment = ':bo_table((?!.*\\.php$)[^/]+)';
const boardsRouteSegment = ':bo_table((?!__g5_static__$)[^/]+)';

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, '');
}

function appPublicScope(): string {
  try {
    const pathname = new URL(
      process.env.NEXT_PUBLIC_APP_URL || 'http://localhost'
    ).pathname.replace(/\/+$/, '');
    return pathname ? `${pathname}/` : '/';
  } catch {
    return '/';
  }
}

function apiRewriteDestination(): string {
  const value = process.env.G5_API_INTERNAL_URL || process.env.NEXT_PUBLIC_API_URL;
  if (value) return trimTrailingSlash(value);
  return 'http://127.0.0.9/api/v1';
}

function mediaRewriteDestination(): string {
  const g5Origin = originFromUrl(process.env.NEXT_PUBLIC_G5_URL);
  return g5Origin || originFromUrl(apiRewriteDestination()) || 'http://127.0.0.9';
}

function originFromUrl(value?: string): string {
  if (!value) return '';

  try {
    return new URL(trimTrailingSlash(value)).origin;
  } catch {
    return '';
  }
}

function configuredG5ImagePattern(): { protocol: 'http' | 'https'; hostname: string; port: string; pathname: string } | undefined {
  const value = process.env.NEXT_PUBLIC_G5_URL?.trim();
  if (!value) return undefined;

  try {
    const url = new URL(value);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return undefined;
    return {
      protocol: url.protocol.slice(0, -1) as 'http' | 'https',
      hostname: url.hostname,
      port: url.port,
      pathname: '/**',
    };
  } catch {
    return undefined;
  }
}

function hostOf(value: string | undefined): string | undefined {
  try {
    return value ? new URL(value).hostname : undefined;
  } catch {
    return undefined;
  }
}

// the site's own host comes from NEXT_PUBLIC_APP_URL (set per deployment, e.g. in .env.production)
const SITE_IMAGE_HOST = hostOf(process.env.NEXT_PUBLIC_APP_URL);

const DEFAULT_IMAGE_HOSTS = [
  ...(SITE_IMAGE_HOST ? [SITE_IMAGE_HOST] : []),
  'graph.facebook.com',
  'lh3.googleusercontent.com',
  'k.kakaocdn.net',
  'phinf.pstatic.net',
];

const extraHosts = (process.env.NEXT_IMAGE_EXTRA_HOSTS ?? '')
  .split(',')
  .map((host) => host.trim())
  .filter(Boolean);

const ALLOWED_IMAGE_HOSTS = [...new Set([...DEFAULT_IMAGE_HOSTS, ...extraHosts])];

const isDev = process.env.NODE_ENV !== 'production';
const pgFrameSources = [
  'https://*.tosspayments.com',
  'https://testpay.kcp.co.kr',
  'https://*.kcp.co.kr',
  'https://stdpay.inicis.com',
  'https://stgstdpay.inicis.com',
  'https://*.inicis.com',
  'https://web.nicepay.co.kr',
  'https://*.nicepay.co.kr',
].join(' ');
const pgScriptSources = pgFrameSources;
const postcodeScriptSources = ['https://t1.daumcdn.net', 'http://t1.daumcdn.net'].join(' ');
const postcodeImageSources = ['https://t1.daumcdn.net', 'http://t1.daumcdn.net', 'https://t1.kakaocdn.net'].join(' ');
const postcodeFrameSources = ['https://postcode.map.daum.net', 'https://postcode.map.kakao.com'].join(' ');
const apiConnectSources = [
  originFromUrl(process.env.NEXT_PUBLIC_API_URL),
  originFromUrl(process.env.NEXT_PUBLIC_G5_URL),
  originFromUrl(process.env.G5_API_INTERNAL_URL),
]
  .filter((source) => source.startsWith('https://'))
  .filter((source, index, sources) => sources.indexOf(source) === index)
  .join(' ');
const scriptSources = [
  `'self'`,
  `'unsafe-inline'`,
  ...(process.env.NEXT_CSP_ALLOW_UNSAFE_EVAL === '1' ? [`'unsafe-eval'`] : []),
  'https://js.tosspayments.com',
  pgScriptSources,
  postcodeScriptSources,
].join(' ');
const csp = [
  `default-src 'self'`,
  `script-src ${scriptSources}`,
  `style-src 'self' 'unsafe-inline'`,
  `img-src 'self' blob: data: https: ${postcodeImageSources}`,
  `font-src 'self' data:`,
  `connect-src 'self' https: ${apiConnectSources} ${isDev ? 'http://127.0.0.9 http://localhost:* ws://localhost:*' : ''}`.trim(),
  `frame-src ${pgFrameSources} ${postcodeFrameSources}`,
  `frame-ancestors 'none'`,
  `base-uri 'self'`,
  `form-action 'self' ${pgFrameSources}`,
  `object-src 'none'`,
].join('; ');

const noindexHeaders = [
  { key: 'X-Robots-Tag', value: 'noindex, nofollow' },
  { key: 'Cache-Control', value: 'no-store, no-cache, must-revalidate, max-age=0, private' },
  { key: 'Pragma', value: 'no-cache' },
];

const privateNoindexSources = [
  '/login',
  '/register',
  '/forgot-password',
  '/members/:path*',
  '/mypage/:path*',
  '/admin/:path*',
  '/shop/cart',
  '/shop/order',
  '/shop/orders/:path*',
  '/shop/payment/success',
  '/shop/payment/fail',
  '/shop/personalpay',
  '/shop/personalpay/:path*',
  '/shop/personalpayform.php',
  '/shop/personalpayformupdate.php',
  '/shop/personalpayresult.php',
  '/shop/wishlist',
];

const youngCartServerRedirects: NonNullable<NextConfig['redirects']> = async () => [
  {
    source: '/shop/index.php',
    destination: '/shop',
    permanent: true,
  },
  {
    source: '/shop/cart.php',
    destination: '/shop/cart',
    permanent: true,
  },
  {
    source: '/shop/wishlist.php',
    destination: '/shop/wishlist',
    permanent: true,
  },
  {
    source: '/shop/couponzone.php',
    destination: '/shop/couponzone',
    permanent: true,
  },
  {
    source: '/shop/search.php',
    destination: '/shop/search',
    permanent: true,
  },
  {
    source: '/shop/largeimage.php',
    destination: '/shop/largeimage',
    permanent: true,
  },
  {
    source: '/shop/mypage.php',
    destination: '/mypage',
    permanent: true,
  },
  {
    source: '/shop/orderinquiry.php',
    destination: '/shop/orders',
    permanent: true,
  },
  {
    source: '/shop/personalpay.php',
    destination: '/shop/personalpay',
    permanent: true,
  },
];

const serverRuntimeConfig: NextConfig = STATIC_EXPORT
  ? {}
  : {
      async headers() {
        return [
          ...privateNoindexSources.map((source) => ({
            source,
            headers: noindexHeaders,
          })),
          {
            source: '/sw.js',
            headers: [{ key: 'Service-Worker-Allowed', value: appPublicScope() }],
          },
          {
            source: '/:path*.txt',
            headers: [{ key: 'X-Robots-Tag', value: 'noindex, nofollow' }],
          },
          {
            source: '/(.*)',
            headers: [
              { key: 'X-Content-Type-Options', value: 'nosniff' },
              { key: 'X-Frame-Options', value: 'DENY' },
              { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
              { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
              { key: 'X-DNS-Prefetch-Control', value: 'on' },
              ...(isDev
                ? []
                : [
                    { key: 'Content-Security-Policy', value: csp },
                    {
                      key: 'Strict-Transport-Security',
                      value: 'max-age=31536000; includeSubDomains',
                    },
                  ]),
            ],
          },
        ];
      },
      async redirects() {
        return [
          ...(await youngCartServerRedirects()),
          {
            source: `/boards/${boardsRouteSegment}/rss`,
            destination: '/rss/:bo_table',
            permanent: true,
          },
          {
            source: `/boards/${boardsRouteSegment}/write`,
            destination: '/bbs/:bo_table/write',
            permanent: true,
          },
          {
            source: `/boards/${boardsRouteSegment}/:wr_id((?!0$)[^/]+)`,
            destination: '/bbs/:bo_table/:wr_id',
            permanent: true,
          },
          {
            source: `/boards/${boardsRouteSegment}`,
            destination: '/bbs/:bo_table',
            permanent: true,
          },
          {
            source: '/shop/products/:it_id((?!__g5_static__$)[^/]+)',
            destination: '/shop/:it_id',
            permanent: true,
          },
          {
            source: '/shop/categories/:ca_id((?!__g5_static__$)[^/]+)',
            destination: '/shop/list-:ca_id',
            permanent: true,
          },
          {
            source: '/shop/products',
            has: [{ type: 'query', key: 'it_type1', value: '1' }],
            destination: '/shop/type-1',
            permanent: true,
          },
          {
            source: '/board',
            destination: '/bbs',
            permanent: true,
          },
          {
            source: '/boards',
            destination: '/bbs',
            permanent: true,
          },
          {
            source: '/member/:path*',
            destination: '/mypage',
            permanent: false,
          },
        ];
      },
      async rewrites() {
        const g5ApiUrl = apiRewriteDestination();
        return {
          // /bbs/<bo_table>... must win over the bbs/*.php route handler, so it is rewritten to
          // the /boards pages before the file-system routes are matched.
          beforeFiles: [
            { source: '/bbs', destination: '/boards' },
            {
              source: `/bbs/${bbsBoardSegment}/write`,
              destination: STATIC_EXPORT ? '/boards/__g5_static__/write' : '/boards/:bo_table/write',
            },
            {
              source: `/bbs/${bbsBoardSegment}/:wr_id((?!.*\\.php$)[^/]+)`,
              destination: STATIC_EXPORT ? '/boards/__g5_static__/0' : '/boards/:bo_table/:wr_id',
            },
            {
              source: `/bbs/${bbsBoardSegment}`,
              destination: STATIC_EXPORT ? '/boards/__g5_static__' : '/boards/:bo_table',
            },
          ],
          afterFiles: [
            // Product uploads use Gnuboard's /data/* paths. In independent
            // Next.js server mode, send those media requests to the G5 host so
            // both browser images and the Next image optimizer can resolve them.
            {
              source: '/data/:path*',
              destination: `${mediaRewriteDestination()}/data/:path*`,
            },
            // BFF proxy: the browser calls the Vercel domain at /api/v1/* and
            // Next.js forwards it to the API server. This keeps the API
            // first-party to the front-end origin, so auth cookies (SameSite=Lax)
            // and sessions work across a separate API host without CORS.
            {
              source: '/api/v1/:path*',
              destination: `${g5ApiUrl}/:path*`,
            },
            {
              source: '/api/g5/:path*',
              destination: `${g5ApiUrl}/:path*`,
            },
            // Static exports need sentinel shells for IDs created after build;
            // the independent server preserves IDs for server-rendered metadata.
            {
              source: '/shop/list-:ca_id',
              destination: STATIC_EXPORT
                ? '/shop/categories/__g5_static__?__g5_ca_id=:ca_id'
                : '/shop/categories/:ca_id',
            },
            {
              source: '/shop/type-:type',
              destination: '/shop/products?__g5_type=:type',
            },
            {
              source: '/shop/:itemId',
              destination: STATIC_EXPORT
                ? '/shop/products/__g5_static__?__g5_item_id=:itemId'
                : '/shop/products/:itemId',
            },
            // g5ShortHref emits /rss/{bo_table}; route it to the generated
            // board feed handler instead of treating it as a board slug.
            {
              source: '/rss/:bo_table',
              destination: '/boards/:bo_table/rss',
            },
          ],
          // Keep these rewrites in the fallback phase so real application
          // pages such as /members/:mb_id and /faq/:id keep their own routes.
          // Any remaining short Gnuboard board URL is served by its sentinel
          // page, which reads board/post identifiers from the browser path.
          fallback: [
            {
              source: `/${shortBoardSegment}/write`,
              destination: STATIC_EXPORT
                ? '/boards/__g5_static__/write'
                : '/boards/:bo_table/write',
            },
            {
              source: `/${shortBoardSegment}/:wr_id`,
              destination: STATIC_EXPORT
                ? '/boards/__g5_static__/0'
                : '/boards/:bo_table/:wr_id',
            },
            {
              source: `/${shortBoardSegment}`,
              destination: STATIC_EXPORT
                ? '/boards/__g5_static__'
                : '/boards/:bo_table',
            },
          ],
        };
      },
    };

const nextConfig: NextConfig = {
  // Static theme builds use this as their export folder; build-next isolates the
  // Next-internal `.next` directory in a temporary project copy.
  distDir: process.env.G5_NEXT_DIST_DIR?.trim() || '.next',
  ...(STATIC_EXPORT ? { output: 'export' as const } : {}),
  generateBuildId: async () => process.env.G5_NEXT_BUILD_ID || 'g5-nextjs25-static',
  trailingSlash: false,
  images: {
    unoptimized: STATIC_EXPORT,
    remotePatterns: [
      ...(configuredG5ImagePattern() ? [configuredG5ImagePattern()!] : []),
      ...(isDev || STATIC_EXPORT || process.env.NEXT_IMAGE_ALLOW_LOCAL_HOSTS === '1'
        ? [
            { protocol: 'http' as const, hostname: 'localhost' },
            { protocol: 'http' as const, hostname: '127.0.0.1' },
            { protocol: 'http' as const, hostname: '127.0.0.9' },
            { protocol: 'http' as const, hostname: '127.0.0.3' },
          ]
        : []),
      ...ALLOWED_IMAGE_HOSTS.map((hostname) => ({
        protocol: 'https' as const,
        hostname,
      })),
    ],
  },
  ...serverRuntimeConfig,
};

const SENTRY_ENABLED = !!(process.env.SENTRY_AUTH_TOKEN && process.env.NEXT_PUBLIC_SENTRY_DSN);

const baseConfig = withBundleAnalyzer(nextConfig);

export default SENTRY_ENABLED
  ? withSentryConfig(baseConfig, {
      silent: !process.env.CI,
      org: process.env.SENTRY_ORG,
      project: process.env.SENTRY_PROJECT,
      widenClientFileUpload: true,
      sourcemaps: { disable: false },
      disableLogger: true,
      ...(process.env.NEXT_PUBLIC_SENTRY_TUNNEL_ROUTE
        ? { tunnelRoute: process.env.NEXT_PUBLIC_SENTRY_TUNNEL_ROUTE }
        : {}),
    })
  : baseConfig;
