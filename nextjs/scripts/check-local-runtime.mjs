const checkLabel = process.env.RUNTIME_CHECK_LABEL || 'check-local-runtime';
const appUrl = trimTrailingSlash(process.env.LOCAL_APP_URL || 'http://127.0.0.20');
const expectedApiUrl = trimTrailingSlash(
  process.env.LOCAL_EXPECTED_API_URL || `${appUrl}/api/v1`
);
const repoApiUrl = trimTrailingSlash(process.env.LOCAL_REPO_API_URL || `${appUrl}/api/v1`);
const legacyRssPath = process.env.LOCAL_SMOKE_RSS_PATH || '/rss/free';
const allowDisabledLegacyRss = process.env.LOCAL_SMOKE_RSS_ALLOW_DISABLED === '1';
const sitemapExpectedPaths = parseCsv(
  process.env.LOCAL_SMOKE_SITEMAP_PATHS || '/content/company,/shop/1446772772,/shop/list-2010101010'
);
const sitemapForbiddenParts = parseCsv(
  process.env.LOCAL_SMOKE_SITEMAP_FORBIDDEN ||
    '/shop/products/1446772772,/shop/categories/2010101010'
);
const privateNoindexPaths = parseCsv(
  process.env.LOCAL_SMOKE_PRIVATE_NOINDEX_PATHS ||
    '/login,/register,/forgot-password,/members/demo,/mypage,/admin,/shop/cart,/shop/order,/shop/orders,/shop/payment/success,/shop/wishlist'
);
const publicHtmlAssets = parseCsv(process.env.LOCAL_SMOKE_PUBLIC_HTML_ASSETS || '');
const publicMetadataPaths = parseCsv(
  process.env.LOCAL_SMOKE_PUBLIC_METADATA_PATHS ||
    '/,/bbs,/faq,/recent,/polls,/search,/shop,/bbs/free/6,/shop/1446772772,/shop/list-2010101010,/shop/reviews,/shop/qas,/shop/search?q=TH,/shop/largeimage?it_id=1446772772&no=1'
);
const legacyShopPassthroughPaths = parseCsv(
  process.env.LOCAL_SMOKE_LEGACY_SHOP_PASSTHROUGH_PATHS ||
    '/shop/bannerhit.php?bn_id=1,/shop/taxsave.php,/shop/naverpay/naverpay_order.php,/shop/price/naver.php,/shop/kcp/pp_ax_hub.php,/mobile/shop/toss/returnurl.php?orderId=demo,/mobile/shop/samsungpay/orderform.1.php'
);
const defaultLegacyShopRedirects = [
  '/mobile=>/',
  '/mobile/=>/',
  '/mobile/index.php=>/',
  '/mobile/group.php?gr_id=shop&page=2=>/bbs?page=2&group=shop',
  '/mobile/content.php?co_id=company=>/content/company',
  '/mobile/content.php?co_seo_title=%ED%9A%8C%EC%82%AC%EC%86%8C%EA%B0%9C=>/content/%ED%9A%8C%EC%82%AC%EC%86%8C%EA%B0%9C/',
  '/bbs/board.php?bo_table=free&page=2=>/bbs/free?page=2',
  '/bbs/board.php?bo_table=free&wr_id=6=>/bbs/free/6',
  '/bbs/write.php?bo_table=free=>/bbs/free/write',
  '/bbs/content.php?co_id=company=>/content/company',
  '/bbs/group.php?gr_id=shop&page=2=>/bbs?page=2&group=shop',
  '/bbs/faq.php?fm_id=1=>/faq?fm_id=1',
  '/bbs/new.php?gr_id=shop&page=2=>/recent?gr_id=shop&page=2',
  '/bbs/search.php?stx=delivery&sfl=wr_subject&bo_table=free&page=2=>/search?sfl=wr_subject&bo_table=free&page=2&q=delivery',
  '/bbs/login.php?url=%2Ffree%3Fpage%3D2=>/login?redirect=%2Ffree%3Fpage%3D2',
  '/bbs/register.php=>/register',
  '/bbs/register_form.php=>/register',
  '/bbs/register_result.php=>/register/result',
  '/bbs/password_lost.php=>/forgot-password',
  '/bbs/poll_result.php?po_id=3=>/polls?po_id=3',
  '/bbs/qalist.php?page=2=>/mypage/qas?page=2',
  '/bbs/qaview.php?qa_id=7=>/mypage/qas/7',
  '/bbs/qawrite.php=>/mypage/qas/new',
  '/bbs/qawrite.php?w=u&qa_id=7=>/mypage/qas/7',
  '/bbs/qawrite.php?w=r&qa_id=7=>/mypage/qas/new?reply_to=7',
  '/bbs/memo.php?kind=send&page=2=>/mypage/memos?page=2&type=send',
  '/bbs/memo_form.php?me_recv_mb_id=demo=>/mypage/memos/new?recv=demo',
  '/bbs/memo_view.php?me_id=9&kind=send=>/mypage/memos/9?type=send',
  '/bbs/profile.php?mb_id=demo=>/members/demo',
  '/bbs/point.php=>/mypage/points',
  '/bbs/scrap.php=>/mypage/scraps',
  '/mobile/shop=>/shop',
  '/mobile/shop/index.php=>/shop',
  '/mobile/shop/cart.php=>/shop/cart',
  '/mobile/shop/wishlist.php=>/shop/wishlist',
  '/mobile/shop/item.php?it_id=1446772772=>/shop/1446772772',
  '/mobile/shop/iteminfo.php?it_id=1446772772&info=qa=>/shop/1446772772?tab=qa',
  '/mobile/shop/itemqa.php?it_id=1446772772=>/shop/1446772772?tab=qa',
  '/mobile/shop/itemqaform.php?it_id=1446772772=>/shop/1446772772?tab=qa&form=qa',
  '/mobile/shop/itemrecommend.php?it_id=1446772772=>/shop/1446772772?modal=recommend',
  '/mobile/shop/itemstocksms.php?it_id=1446772772=>/shop/1446772772?modal=restock',
  '/mobile/shop/itemuse.php?it_id=1446772772=>/shop/1446772772?tab=reviews',
  '/mobile/shop/itemuseform.php?it_id=1446772772=>/shop/1446772772?tab=reviews&form=review',
  '/mobile/shop/category.php?ca_id=2010101010&page=2=>/shop/list-2010101010?page=2',
  '/mobile/shop/list.php?ca_id=2010101010&page=2=>/shop/list-2010101010?page=2',
  '/mobile/shop/listtype.php?type=2&page=3=>/shop/type-2?page=3',
  '/mobile/shop/coupon.php=>/mypage/coupons',
  '/mobile/shop/event.php?ev_id=1=>/shop/events/1',
  '/mobile/shop/largeimage.php?it_id=1446772772&no=1=>/shop/largeimage?it_id=1446772772&no=1',
  '/mobile/shop/mypage.php=>/mypage',
  '/mobile/shop/orderaddress.php=>/mypage/addresses',
  '/mobile/shop/orderform.php?sw_direct=1=>/shop/order?direct=1',
  '/mobile/shop/orderinquiry.php=>/shop/orders',
  '/mobile/shop/orderinquiryview.php?od_id=202606030001=>/shop/orders/202606030001',
  '/mobile/shop/personalpay.php=>/shop/personalpay',
  '/mobile/shop/personalpayform.php?pp_id=demo=>/shop/personalpay/demo/pay',
  '/mobile/shop/personalpayresult.php?pp_id=demo=>/shop/personalpay/demo',
  '/mobile/shop/search.php?q=TH&qcaid=2010101010=>/shop/search?q=TH&qcaid=2010101010',
  '/shop/item.php?it_id=1446772772=>/shop/1446772772',
  '/shop/iteminfo.php?it_id=1446772772&info=use=>/shop/1446772772?tab=reviews',
  '/shop/category.php?ca_id=2010101010=>/shop/list-2010101010',
  '/shop/list.php?ca_id=2010101010&page=2=>/shop/list-2010101010?page=2',
  '/shop/listtype.php?type=1&page=2=>/shop/type-1?page=2',
  '/shop/event.php?ev_id=1=>/shop/events/1',
  '/shop/orderform.php?sw_direct=1=>/shop/order?direct=1',
  '/shop/orderinquiryview.php?od_id=202606030001=>/shop/orders/202606030001',
  '/shop/orderinquirycancel.php?od_id=202606030001=>/shop/orders/202606030001',
  '/shop/personalpayform.php?pp_id=demo=>/shop/personalpay/demo/pay',
  '/shop/personalpayresult.php?pp_id=demo=>/shop/personalpay/demo',
].join(',');
const legacyShopRedirects = parseRedirects(
  process.env.LOCAL_SMOKE_LEGACY_SHOP_REDIRECTS || defaultLegacyShopRedirects
);
const canonicalRedirects = parseRedirects(
  process.env.LOCAL_SMOKE_CANONICAL_REDIRECTS ||
    '/boards/free=>/bbs/free,/boards/free/6=>/bbs/free/6,/boards/free/write=>/bbs/free/write,/boards/free/rss=>/rss/free,/shop/products/1446772772=>/shop/1446772772,/shop/categories/2010101010=>/shop/list-2010101010,/shop/products?it_type1=1=>/shop/type-1?it_type1=1'
);
const rscPayloads =
  process.env.RUNTIME_SKIP_STATIC_RSC_PAYLOADS === '1'
    ? []
    : parseRedirects(
        process.env.LOCAL_SMOKE_RSC_PAYLOADS ||
          '/index.txt=>/,/free.txt=>/free,/shop/products/1446772772.txt=>/shop/1446772772,/shop/1446772772.txt=>/shop/1446772772,/shop/list-2010101010.txt=>/shop/list-2010101010,/shop/type-1.txt=>/shop/type-1,/shop/reviews.txt=>/shop/reviews,/shop/qas.txt=>/shop/qas,/shop/search.txt=>/shop/search,/shop/largeimage.txt=>/shop/largeimage'
      );
const requireExpectedApiSecurityHeaders =
  process.env.RUNTIME_REQUIRE_EXPECTED_API_SECURITY_HEADERS === '1';
const expectedApiReferrerPolicies = parseCsv(
  process.env.RUNTIME_EXPECTED_API_REFERRER_POLICIES || 'no-referrer'
);

function trimTrailingSlash(value) {
  return String(value).replace(/\/+$/, '');
}

function fail(message) {
  console.error(`[${checkLabel}] ${message}`);
  process.exit(1);
}

function normalizePath(value) {
  return value.startsWith('/') ? value : `/${value}`;
}

function parseCsv(value) {
  return String(value)
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseRedirects(value) {
  return parseCsv(value).map((item) => {
    const [from, to] = item.split('=>').map((part) => part?.trim());
    if (!from || !to) {
      fail(`Invalid redirect expectation: ${item}`);
    }
    return { from, to };
  });
}

async function fetchText(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  return { response, text };
}

function sameUrl(actual, expected) {
  if (!actual || !expected) return false;

  const normalize = (value) => {
    const url = new URL(String(value).replace(/&amp;/g, '&'), appUrl);
    const pathname = url.pathname.replace(/\/+$/, '') || '/';
    return `${url.origin}${pathname}${url.search}${url.hash}`;
  };

  return normalize(actual) === normalize(expected);
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function appAbsoluteUrl(path) {
  const normalized = normalizePath(path);
  return normalized === '/' ? appUrl : `${appUrl}${normalized}`;
}

function appAbsoluteUrlWithQuery(path, params) {
  const url = new URL(appAbsoluteUrl(path));
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }
  return url.toString();
}

function appBasePath() {
  const pathname = new URL(appUrl).pathname.replace(/\/+$/, '');
  return pathname === '/' ? '' : pathname;
}

function g5PublicPath(path) {
  return `${appBasePath()}${normalizePath(path)}` || '/';
}

function g5PublicScope() {
  const basePath = appBasePath();
  return basePath ? `${basePath}/` : '/';
}

function isLocalSitePath(path) {
  const normalized = normalizePath(path);
  const exactPaths = new Set([
    '/',
    '/favicon.ico',
    '/manifest.json',
    '/manifest.webmanifest',
    '/og-default.png',
    '/robots.txt',
    '/sitemap.xml',
    '/sitemap-posts.xml',
    '/sw.js',
  ]);
  if (exactPaths.has(normalized) || /^\/icon-[0-9]+\.png$/.test(normalized)) {
    return true;
  }

  if (
    /^\/(?:admin|boards|content|faq|forgot-password|login|mypage|polls|recent|register|rss|search|shop)(?:\/|$)/.test(
      normalized
    )
  ) {
    return true;
  }

  return /^\/[0-9A-Za-z_]+(?:\/[^/]+)?$/.test(normalized);
}

function isRuntimeLocalHost(hostname) {
  const host = String(hostname || '').toLowerCase();
  const appHost = new URL(appUrl).hostname.toLowerCase();
  if (host === appHost || host === 'localhost' || host === '::1' || host.startsWith('127.')) {
    return true;
  }

  return /^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[0-1])\.)/.test(host);
}

function collectAbsoluteUrls(text) {
  return Array.from(String(text).matchAll(/https?:\/\/[^"'<>\s\\]+/gi)).map((match) => match[0]);
}

function readRuntimeConfig(html) {
  const assignment = html.match(
    /window\.__G5_NEXTJS25_CONFIG__\s*=\s*(?:Object\.assign\(\s*)?/
  );
  if (!assignment) {
    fail(`Missing window.__G5_NEXTJS25_CONFIG__ in ${appUrl}`);
  }

  const jsonStart = assignment.index + assignment[0].length;
  const objectStart = html.indexOf("{", jsonStart);
  if (objectStart < 0 || html.slice(jsonStart, objectStart).trim()) {
    fail(`Invalid runtime config assignment in ${appUrl}`);
  }

  let depth = 0;
  let inString = false;
  let escaped = false;
  let objectEnd = -1;
  for (let index = objectStart; index < html.length; index += 1) {
    const character = html[index];
    if (inString) {
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === '"') {
        inString = false;
      }
      continue;
    }

    if (character === '"') {
      inString = true;
    } else if (character === "{") {
      depth += 1;
    } else if (character === "}") {
      depth -= 1;
      if (depth === 0) {
        objectEnd = index + 1;
        break;
      }
    }
  }

  if (objectEnd < 0) {
    fail(`Incomplete runtime config JSON in ${appUrl}`);
  }

  try {
    return JSON.parse(html.slice(objectStart, objectEnd));
  } catch (error) {
    fail(`Invalid runtime config JSON: ${error.message}`);
  }
}

function readMetaContent(html, key, options = {}) {
  const tagMatch = html.match(
    new RegExp(`<meta\\b(?=[^>]*\\b(?:property|name)=["']${escapeRegExp(key)}["'])[^>]*>`, 'i')
  );

  if (!tagMatch) {
    if (options.required) {
      fail(`Missing ${key} meta tag in ${appUrl}`);
    }
    return null;
  }

  const contentMatch = tagMatch[0].match(/\bcontent=["']([^"']*)["']/i);
  if (!contentMatch) {
    fail(`${key} meta tag is missing content in ${appUrl}`);
  }

  return contentMatch[1];
}

function readLinkHref(html, rel, options = {}) {
  const tagMatch = html.match(
    new RegExp(`<link\\b(?=[^>]*\\brel=["']${escapeRegExp(rel)}["'])[^>]*>`, 'i')
  );

  if (!tagMatch) {
    if (options.required) {
      fail(`Missing ${rel} link in ${appUrl}`);
    }
    return null;
  }

  const hrefMatch = tagMatch[0].match(/\bhref=["']([^"']*)["']/i);
  if (!hrefMatch) {
    fail(`${rel} link is missing href in ${appUrl}`);
  }

  return hrefMatch[1];
}

function readJsonLdScripts(html) {
  const scripts = Array.from(
    html.matchAll(/<script\b(?=[^>]*\btype=["']application\/ld\+json["'])[^>]*>(.*?)<\/script>/gis)
  );

  if (scripts.length === 0) {
    fail(`Missing JSON-LD scripts in ${appUrl}`);
  }

  return scripts.map((match) => {
    try {
      return JSON.parse(match[1]);
    } catch (error) {
      fail(`Invalid JSON-LD in ${appUrl}: ${error.message}`);
    }
  });
}

function collectJsonLdNodes(value, nodes = []) {
  if (Array.isArray(value)) {
    for (const item of value) {
      collectJsonLdNodes(item, nodes);
    }
    return nodes;
  }

  if (value && typeof value === 'object') {
    nodes.push(value);
    if (Array.isArray(value['@graph'])) {
      collectJsonLdNodes(value['@graph'], nodes);
    }
  }

  return nodes;
}

function hasJsonLdType(node, type) {
  const nodeType = node?.['@type'];
  return Array.isArray(nodeType) ? nodeType.includes(type) : nodeType === type;
}

function findJsonLdNode(nodes, type) {
  const node = nodes.find((item) => hasJsonLdType(item, type));
  if (!node) {
    fail(`Missing ${type} JSON-LD node in ${appUrl}`);
  }
  return node;
}

function expectHeader(headers, name, expected) {
  const actual = headers.get(name);
  if (actual !== expected) {
    fail(`${name} is ${actual || '(missing)'}, expected ${expected}`);
  }
}

function expectHeaderOneOf(headers, name, expectedValues) {
  const actual = headers.get(name);
  if (!expectedValues.includes(actual)) {
    fail(`${name} is ${actual || '(missing)'}, expected one of ${expectedValues.join(', ')}`);
  }
}

function expectHeaderIncludes(headers, name, expectedParts) {
  const actual = headers.get(name) || '';
  for (const part of expectedParts) {
    if (!actual.includes(part)) {
      fail(`${name} is ${actual || '(missing)'}, expected to include ${part}`);
    }
  }
}

function cspDirectiveSources(csp, directiveName) {
  const directive = String(csp || '')
    .split(';')
    .map((part) => part.trim())
    .find((part) => part === directiveName || part.startsWith(`${directiveName} `));

  if (!directive) {
    return [];
  }

  return directive
    .split(/\s+/)
    .slice(1)
    .map((source) => source.trim())
    .filter(Boolean);
}

function expectCspConnectSource(headers, expectedUrl) {
  const csp = headers.get('content-security-policy') || '';
  const sources = cspDirectiveSources(csp, 'connect-src');
  const url = new URL(expectedUrl);
  const appOrigin = new URL(appUrl).origin;

  if (sources.includes(url.origin) || (sources.includes("'self'") && url.origin === appOrigin)) {
    return;
  }

  if (url.protocol === 'https:' && sources.includes('https:')) {
    return;
  }

  if (url.protocol === 'http:' && (sources.includes('http:') || sources.includes('http://localhost:*'))) {
    return;
  }

  fail(
    `content-security-policy connect-src is ${sources.join(' ') || '(missing)'}, expected to allow ${url.origin}`
  );
}

function isDisabledLegacyRssResponse(text) {
  const normalized = String(text).replace(/\s+/g, ' ');
  return /RSS/i.test(normalized) && normalized.includes('\uae08\uc9c0');
}

function expectApiSecurityHeaders(headers, options = {}) {
  expectHeader(headers, 'x-content-type-options', 'nosniff');
  expectHeader(headers, 'x-frame-options', 'DENY');
  expectHeaderOneOf(headers, 'referrer-policy', options.referrerPolicies || ['no-referrer']);
  expectHeaderIncludes(headers, 'content-type', ['application/json']);

  if (options.permissionsPolicy) {
    expectHeaderIncludes(headers, 'permissions-policy', ['camera=()', 'microphone=()', 'geolocation=()']);
    expectHeader(headers, 'x-permitted-cross-domain-policies', 'none');
  }
}

function expectThemeSecurityHeaders(headers) {
  expectHeader(headers, 'x-content-type-options', 'nosniff');
  expectHeader(headers, 'x-frame-options', 'DENY');
  expectHeader(headers, 'referrer-policy', 'strict-origin-when-cross-origin');
  expectHeaderIncludes(headers, 'permissions-policy', ['camera=()', 'microphone=()', 'geolocation=()']);
}

function expectNoindexHeader(headers, url) {
  expectHeaderIncludes(headers, 'x-robots-tag', ['noindex', 'nofollow']);
  expectHeaderIncludes(headers, 'cache-control', ['no-store', 'private']);
  expectHeader(headers, 'pragma', 'no-cache');
  const contentType = headers.get('content-type') || '';
  if (!contentType.includes('text/html')) {
    fail(`${url} returned content-type ${contentType || '(missing)'}, expected HTML`);
  }
}

function isNextStaticShellResponse(headers, text) {
  const contentType = headers.get('content-type') || '';
  return (
    contentType.includes('text/x-component') ||
    text.includes('<!--g5_nextjs25_static-->') ||
    text.includes('window.__G5_NEXTJS25_CONFIG__') ||
    text.includes('self.__next_f')
  );
}

const appCheckUrl = `${appUrl}/?runtime-check=${Date.now()}`;
const { response: appResponse, text: appHtml } = await fetchText(appCheckUrl);
if (!appResponse.ok) {
  fail(`${appCheckUrl} returned HTTP ${appResponse.status}`);
}

expectHeader(appResponse.headers, 'x-content-type-options', 'nosniff');
expectHeader(appResponse.headers, 'x-frame-options', 'DENY');
expectHeader(appResponse.headers, 'referrer-policy', 'strict-origin-when-cross-origin');
expectHeaderIncludes(appResponse.headers, 'permissions-policy', ['camera=()', 'microphone=()', 'geolocation=()']);
expectHeaderIncludes(appResponse.headers, 'content-security-policy', [
  "default-src 'self'",
  "script-src 'self'",
  "'unsafe-inline'",
  "https:",
  "http://t1.daumcdn.net",
  "object-src 'none'",
  "frame-ancestors 'none'",
]);
expectCspConnectSource(appResponse.headers, expectedApiUrl);

const runtimeConfig = readRuntimeConfig(appHtml);
const actualApiUrl = trimTrailingSlash(runtimeConfig.apiBaseUrl || '');
let resolvedApiUrl = actualApiUrl;
try {
  resolvedApiUrl = trimTrailingSlash(new URL(actualApiUrl, `${appUrl}/`).toString());
} catch {
  // Keep the raw value in the failure message below.
}
if (resolvedApiUrl !== expectedApiUrl) {
  fail(`apiBaseUrl is ${actualApiUrl || '(empty)'} (resolved ${resolvedApiUrl}), expected ${expectedApiUrl}`);
}

const expectedManifestPath = g5PublicPath('/manifest.webmanifest');
const manifestHref = readLinkHref(appHtml, 'manifest', { required: true });
if (manifestHref !== expectedManifestPath) {
  fail(`manifest href is ${manifestHref || '(missing)'}, expected ${expectedManifestPath}`);
}

const expectedOgImageUrl = `${appUrl}/og-default.png`;
for (const key of ['og:image', 'og:image:url', 'twitter:image', 'twitter:image:src']) {
  const content = readMetaContent(appHtml, key, { required: key === 'twitter:image' });
  if (content !== null && content !== expectedOgImageUrl) {
    fail(`${key} is ${content}, expected ${expectedOgImageUrl}`);
  }
}

const jsonLdNodes = readJsonLdScripts(appHtml).flatMap((item) => collectJsonLdNodes(item));
const organizationJsonLd = findJsonLdNode(jsonLdNodes, 'Organization');
if (organizationJsonLd.url !== appUrl) {
  fail(`Organization JSON-LD url is ${organizationJsonLd.url || '(missing)'}, expected ${appUrl}`);
}
if (organizationJsonLd.logo !== expectedOgImageUrl) {
  fail(`Organization JSON-LD logo is ${organizationJsonLd.logo || '(missing)'}, expected ${expectedOgImageUrl}`);
}

const websiteJsonLd = findJsonLdNode(jsonLdNodes, 'WebSite');
if (websiteJsonLd.url !== appUrl) {
  fail(`WebSite JSON-LD url is ${websiteJsonLd.url || '(missing)'}, expected ${appUrl}`);
}

const searchActions = Array.isArray(websiteJsonLd.potentialAction)
  ? websiteJsonLd.potentialAction
  : [websiteJsonLd.potentialAction].filter(Boolean);
const searchAction = searchActions.find((item) => hasJsonLdType(item, 'SearchAction'));
const expectedSearchTarget = `${appUrl}/search?q={search_term_string}`;
if (!searchAction || searchAction.target !== expectedSearchTarget) {
  fail(`WebSite SearchAction target is ${searchAction?.target || '(missing)'}, expected ${expectedSearchTarget}`);
}

for (const path of privateNoindexPaths) {
  const url = `${appUrl}${normalizePath(path)}?runtime-noindex-check=${Date.now()}`;
  const { response } = await fetchText(url);
  if (!response.ok) {
    fail(`${url} returned HTTP ${response.status}`);
  }
  expectNoindexHeader(response.headers, url);
}

for (const path of publicHtmlAssets) {
  const url = `${appUrl}${normalizePath(path)}?runtime-public-asset-check=${Date.now()}`;
  const { response } = await fetchText(url);
  if (!response.ok) {
    fail(`${url} returned HTTP ${response.status}`);
  }
  expectThemeSecurityHeaders(response.headers);
  expectHeaderIncludes(response.headers, 'content-type', ['text/html']);

}

for (const path of legacyShopPassthroughPaths) {
  const url = appAbsoluteUrlWithQuery(path, {
    'legacy-shop-passthrough-smoke': String(Date.now()),
  });
  const { response, text } = await fetchText(url, { redirect: 'manual' });
  if (response.status === 404) {
    fail(`${url} returned HTTP 404; expected an original YoungCart PHP route`);
  }
  if (isNextStaticShellResponse(response.headers, text)) {
    fail(`${url} returned the Next.js static shell; expected original YoungCart PHP passthrough`);
  }
}

for (const redirect of legacyShopRedirects) {
  const url = appAbsoluteUrl(redirect.from);
  let response = await fetch(url, { redirect: 'manual' });
  let location = response.headers.get('location') || '';
  const sourceUrl = new URL(url);
  const slashNormalizedPath = sourceUrl.pathname.replace(/\/+$/, '') || '/';
  const slashNormalizedUrl = `${sourceUrl.origin}${slashNormalizedPath}${sourceUrl.search}`;

  if (
    response.status === 308 &&
    sourceUrl.pathname.endsWith('/') &&
    sameUrl(location, slashNormalizedUrl)
  ) {
    response = await fetch(new URL(location, url), { redirect: 'manual' });
    location = response.headers.get('location') || '';
  }

  const expected = appAbsoluteUrl(redirect.to);
  if (![301, 307, 308].includes(response.status) || !sameUrl(location, expected)) {
    fail(
      `${url} legacy shop redirect is HTTP ${response.status} to ${location || '(missing)'}, expected ${expected}`
    );
  }
}

for (const path of publicMetadataPaths) {
  const normalizedPath = normalizePath(path);
  const expectedUrl = appAbsoluteUrl(normalizedPath);
  const url = appAbsoluteUrlWithQuery(normalizedPath, {
    'metadata-smoke': String(Date.now()),
    utm_source: 'runtime',
  });
  const { response, text } = await fetchText(url);
  if (!response.ok) {
    fail(`${url} returned HTTP ${response.status}`);
  }
  expectThemeSecurityHeaders(response.headers);

  const canonical = readLinkHref(text, 'canonical', { required: true });
  if (!sameUrl(canonical, expectedUrl)) {
    fail(`${url} canonical is ${canonical || '(missing)'}, expected ${expectedUrl}`);
  }

  const ogUrl = readMetaContent(text, 'og:url', { required: true });
  if (!sameUrl(ogUrl, expectedUrl)) {
    fail(`${url} og:url is ${ogUrl || '(missing)'}, expected ${expectedUrl}`);
  }
}

const manifestPaths = ['/manifest.webmanifest', '/manifest.json'];
for (const path of manifestPaths) {
  const manifestUrl = `${appUrl}${path}`;
  const { response: manifestResponse, text: manifestText } = await fetchText(manifestUrl);
  if (!manifestResponse.ok) {
    fail(`${manifestUrl} returned HTTP ${manifestResponse.status}`);
  }
  expectThemeSecurityHeaders(manifestResponse.headers);
  expectHeaderIncludes(manifestResponse.headers, 'content-type', [
    path.endsWith('.json') ? 'json' : 'manifest',
  ]);

  let manifest;
  try {
    manifest = JSON.parse(manifestText);
  } catch (error) {
    fail(`${manifestUrl} returned invalid JSON: ${error.message}`);
  }
  if (manifest.start_url !== g5PublicScope()) {
    fail(`${manifestUrl} start_url is ${manifest.start_url || '(missing)'}, expected ${g5PublicScope()}`);
  }
  if (manifest.scope !== g5PublicScope()) {
    fail(`${manifestUrl} scope is ${manifest.scope || '(missing)'}, expected ${g5PublicScope()}`);
  }
  if (!Array.isArray(manifest.icons) || !manifest.icons.some((icon) => icon?.src === g5PublicPath('/icon-192.png'))) {
    fail(`${manifestUrl} is missing root icon ${g5PublicPath('/icon-192.png')}`);
  }
}

for (const path of ['/icon-192.png', '/icon-512.png', '/og-default.png']) {
  const imageUrl = `${appUrl}${path}`;
  const { response } = await fetchText(imageUrl);
  if (!response.ok) {
    fail(`${imageUrl} returned HTTP ${response.status}`);
  }
  expectThemeSecurityHeaders(response.headers);
  expectHeaderIncludes(response.headers, 'content-type', ['image/png']);
}

const swUrl = `${appUrl}/sw.js`;
const { response: swResponse, text: swText } = await fetchText(swUrl);
if (!swResponse.ok) {
  fail(`${swUrl} returned HTTP ${swResponse.status}`);
}
expectThemeSecurityHeaders(swResponse.headers);
expectHeaderIncludes(swResponse.headers, 'content-type', ['javascript']);
expectHeader(swResponse.headers, 'service-worker-allowed', g5PublicScope());
if (!swText.includes('self.addEventListener') || !swText.includes('CACHE_NAME')) {
  fail(`${swUrl} did not return the service worker script`);
}

for (const payload of rscPayloads) {
  const payloadUrl = `${appUrl}${normalizePath(payload.from)}?_rsc=runtime-rsc-check-${Date.now()}`;
  const { response, text } = await fetchText(payloadUrl);
  if (!response.ok) {
    fail(`${payloadUrl} returned HTTP ${response.status}`);
  }

  expectThemeSecurityHeaders(response.headers);
  expectHeaderIncludes(response.headers, 'content-type', ['text/x-component']);
  expectHeaderIncludes(response.headers, 'x-robots-tag', ['noindex', 'nofollow']);

  const expectedPublicUrl = appAbsoluteUrl(payload.to);
  const foreignLocalUrls = collectAbsoluteUrls(text).filter((value) => {
    let parsed;
    try {
      parsed = new URL(value);
    } catch {
      return false;
    }

    return (
      isRuntimeLocalHost(parsed.hostname) &&
      isLocalSitePath(parsed.pathname) &&
      value !== appUrl &&
      !value.startsWith(`${appUrl}/`)
    );
  });
  if (foreignLocalUrls.length > 0) {
    fail(
      `${payloadUrl} contains local-site URLs outside ${appUrl}: ${foreignLocalUrls.slice(0, 10).join(', ')}`
    );
  }

  if (!text.includes(`${appUrl}/og-default.png`)) {
    fail(`${payloadUrl} is missing the runtime OG image origin ${appUrl}/og-default.png`);
  }
  if (!text.includes(`${appUrl}/search?q={search_term_string}`)) {
    fail(`${payloadUrl} is missing the runtime SearchAction target ${appUrl}/search?q={search_term_string}`);
  }
  if (payload.to !== '/' && !text.includes(`"property":"og:url","content":"${expectedPublicUrl}"`)) {
    fail(`${payloadUrl} is missing runtime og:url ${expectedPublicUrl}`);
  }
  if (text.includes('_rsc=runtime-rsc-check')) {
    fail(`${payloadUrl} leaked the internal _rsc query into metadata`);
  }
}

for (const redirect of canonicalRedirects) {
  const url = `${appUrl}${normalizePath(redirect.from)}`;
  const response = await fetch(url, { redirect: 'manual' });
  const location = response.headers.get('location') || '';
  const expected = `${appUrl}${normalizePath(redirect.to)}`;
  if (![301, 308].includes(response.status) || !sameUrl(location, expected)) {
    fail(
      `${url} canonical redirect is HTTP ${response.status} to ${location || '(missing)'}, expected ${expected}`
    );
  }
}

const apiOrigin = new URL(appUrl).origin;
const settingsUrl = `${expectedApiUrl}/settings`;
const { response: settingsResponse } = await fetchText(settingsUrl, {
  headers: { Origin: apiOrigin },
});

if (!settingsResponse.ok) {
  fail(`${settingsUrl} returned HTTP ${settingsResponse.status}`);
}

const allowOrigin = settingsResponse.headers.get('access-control-allow-origin');
if (new URL(expectedApiUrl).origin !== apiOrigin && allowOrigin !== apiOrigin) {
  fail(`CORS allow-origin is ${allowOrigin || '(missing)'}, expected ${apiOrigin}`);
}
expectApiSecurityHeaders(settingsResponse.headers, {
  permissionsPolicy: requireExpectedApiSecurityHeaders,
  referrerPolicies: expectedApiReferrerPolicies,
});

if (repoApiUrl !== expectedApiUrl) {
  const repoSettingsUrl = `${repoApiUrl}/settings`;
  const { response: repoSettingsResponse } = await fetchText(repoSettingsUrl, {
    headers: { Origin: apiOrigin },
  });

  if (!repoSettingsResponse.ok) {
    fail(`${repoSettingsUrl} returned HTTP ${repoSettingsResponse.status}`);
  }

  expectApiSecurityHeaders(repoSettingsResponse.headers, {
    permissionsPolicy: true,
    referrerPolicies: expectedApiReferrerPolicies,
  });
}

const rssUrl = `${appUrl}${normalizePath(legacyRssPath)}`;
const { response: rssResponse, text: rssText } = await fetchText(rssUrl);
if (!rssResponse.ok) {
  fail(`${rssUrl} returned HTTP ${rssResponse.status}`);
}

const rssContentType = rssResponse.headers.get('content-type') || '';
if (!/(?:xml|rss)/i.test(rssContentType)) {
  if (
    !allowDisabledLegacyRss ||
    rssText.includes('__g5_static__') ||
    !isDisabledLegacyRssResponse(rssText)
  ) {
    fail(`${rssUrl} returned content-type ${rssContentType || '(missing)'}, expected XML`);
  }
}

if (
  !allowDisabledLegacyRss &&
  (!rssText.includes('<rss') || !rssText.includes('<channel>') || rssText.includes('__g5_static__'))
) {
  fail(`${rssUrl} did not return a board RSS feed`);
}

if (
  allowDisabledLegacyRss &&
  !isDisabledLegacyRssResponse(rssText) &&
  (!rssText.includes('<rss') || !rssText.includes('<channel>') || rssText.includes('__g5_static__'))
) {
  fail(`${rssUrl} did not return a board RSS feed or a Gnuboard disabled RSS response`);
}

const robotsUrl = `${appUrl}/robots.txt`;
const { response: robotsResponse, text: robotsText } = await fetchText(robotsUrl);
if (!robotsResponse.ok) {
  fail(`${robotsUrl} returned HTTP ${robotsResponse.status}`);
}

if (!new RegExp(`^Host:\\s*${escapeRegExp(appUrl)}\\s*$`, 'mi').test(robotsText)) {
  fail(`${robotsUrl} Host does not match ${appUrl}`);
}

for (const sitemapPath of ['/sitemap.xml', '/sitemap-posts.xml']) {
  if (
    !new RegExp(`^Sitemap:\\s*${escapeRegExp(`${appUrl}${sitemapPath}`)}\\s*$`, 'mi').test(
      robotsText
    )
  ) {
    fail(`${robotsUrl} Sitemap does not match ${appUrl}${sitemapPath}`);
  }
}

const sitemapUrl = `${appUrl}/sitemap.xml`;
const { response: sitemapResponse, text: sitemapText } = await fetchText(sitemapUrl);
if (!sitemapResponse.ok) {
  fail(`${sitemapUrl} returned HTTP ${sitemapResponse.status}`);
}

const sitemapContentType = sitemapResponse.headers.get('content-type') || '';
if (!/(?:xml|text\/plain)/i.test(sitemapContentType)) {
  fail(`${sitemapUrl} returned content-type ${sitemapContentType || '(missing)'}, expected XML`);
}

for (const path of sitemapExpectedPaths) {
  const expectedLoc = `<loc>${appUrl}${normalizePath(path)}</loc>`;
  if (!sitemapText.includes(expectedLoc)) {
    fail(`${sitemapUrl} is missing ${expectedLoc}`);
  }
}

const sitemapLocs = Array.from(sitemapText.matchAll(/<loc>(.*?)<\/loc>/g)).map((match) => match[1]);
if (sitemapLocs.length === 0) {
  fail(`${sitemapUrl} has no <loc> entries`);
}

const foreignSitemapLocs = sitemapLocs.filter(
  (loc) => loc !== appUrl && !loc.startsWith(`${appUrl}/`)
);
if (foreignSitemapLocs.length > 0) {
  fail(`${sitemapUrl} contains URLs outside ${appUrl}: ${foreignSitemapLocs.slice(0, 10).join(', ')}`);
}

const sitemapBasePath = appBasePath();
if (sitemapBasePath !== '') {
  const duplicatedBasePath = `${sitemapBasePath}${sitemapBasePath}`;
  const duplicatedSitemapLocs = sitemapLocs.filter((loc) => {
    try {
      const { pathname } = new URL(loc);
      return pathname === duplicatedBasePath || pathname.startsWith(`${duplicatedBasePath}/`);
    } catch {
      return false;
    }
  });

  if (duplicatedSitemapLocs.length > 0) {
    fail(
      `${sitemapUrl} contains duplicated base path ${sitemapBasePath}: ${duplicatedSitemapLocs
        .slice(0, 10)
        .join(', ')}`
    );
  }
}

for (const part of sitemapForbiddenParts) {
  if (sitemapText.includes(part)) {
    fail(`${sitemapUrl} contains non-rewrite sitemap URL part ${part}`);
  }
}

const postsSitemapUrl = `${appUrl}/sitemap-posts.xml`;
const { response: postsSitemapResponse, text: postsSitemapText } = await fetchText(postsSitemapUrl);
if (!postsSitemapResponse.ok) {
  fail(`${postsSitemapUrl} returned HTTP ${postsSitemapResponse.status}`);
}

const postsSitemapContentType = postsSitemapResponse.headers.get('content-type') || '';
if (!/(?:xml|text\/plain)/i.test(postsSitemapContentType)) {
  fail(
    `${postsSitemapUrl} returned content-type ${postsSitemapContentType || '(missing)'}, expected XML`
  );
}

if (!postsSitemapText.includes('<urlset')) {
  fail(`${postsSitemapUrl} did not return a sitemap urlset`);
}

const postsSitemapLocs = Array.from(postsSitemapText.matchAll(/<loc>(.*?)<\/loc>/g)).map(
  (match) => match[1]
);
const foreignPostsSitemapLocs = postsSitemapLocs.filter(
  (loc) => loc !== appUrl && !loc.startsWith(`${appUrl}/`)
);
if (foreignPostsSitemapLocs.length > 0) {
  fail(
    `${postsSitemapUrl} contains URLs outside ${appUrl}: ${foreignPostsSitemapLocs
      .slice(0, 10)
      .join(', ')}`
  );
}

console.log(`[${checkLabel}] app=${appUrl}`);
console.log(`[${checkLabel}] api=${actualApiUrl}`);
console.log(`[${checkLabel}] repoApi=${repoApiUrl}`);
console.log(`[${checkLabel}] cors=${allowOrigin}`);
console.log(
  `[${checkLabel}] expectedApiSecurityHeaders=${
    requireExpectedApiSecurityHeaders ? 'full' : 'baseline'
  }`
);
console.log(`[${checkLabel}] rss=${rssUrl}`);
console.log(`[${checkLabel}] robots=${robotsUrl}`);
console.log(`[${checkLabel}] sitemap=${sitemapUrl}`);
console.log(`[${checkLabel}] manifests=${manifestPaths.map((path) => `${appUrl}${path}`).join(',')}`);
console.log(`[${checkLabel}] serviceWorker=${swUrl}`);
console.log(`[${checkLabel}] privateNoindex=${privateNoindexPaths.join(',')}`);
console.log(`[${checkLabel}] publicHtmlAssets=${publicHtmlAssets.join(',')}`);
console.log(`[${checkLabel}] publicMetadata=${publicMetadataPaths.join(',')}`);
console.log(`[${checkLabel}] legacyShopPassthrough=${legacyShopPassthroughPaths.join(',')}`);
console.log(
  `[${checkLabel}] legacyShopRedirects=${legacyShopRedirects
    .map((redirect) => `${redirect.from}=>${redirect.to}`)
    .join(',')}`
);
console.log(
  `[${checkLabel}] rscPayloads=${rscPayloads
    .map((payload) => `${payload.from}=>${payload.to}`)
    .join(',')}`
);
console.log(
  `[${checkLabel}] canonicalRedirects=${canonicalRedirects
    .map((redirect) => `${redirect.from}=>${redirect.to}`)
    .join(',')}`
);
