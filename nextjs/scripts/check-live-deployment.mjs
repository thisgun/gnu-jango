const appUrl = trimTrailingSlash(process.env.LIVE_APP_URL || 'https://nextjs.thisgun.net');
const expectedApiUrl = trimTrailingSlash(
  process.env.LIVE_EXPECTED_API_URL || `${appUrl}/api/v1`
);
const appOrigin = new URL(appUrl).origin;
const liveDeployRemoteDir = process.env.LIVE_DEPLOY_REMOTE_DIR || '/tmp/g5-nextjs25-live-deploy';
const liveDeployWebRoot = process.env.LIVE_DEPLOY_WEB_ROOT || '/home/nextjs/www/study-gnuboard';
const liveDeployNginxConf = process.env.LIVE_DEPLOY_NGINX_CONF || '/etc/nginx/nginx.conf';
const liveDeployNginxSiteConf =
  process.env.LIVE_DEPLOY_NGINX_SITE_CONF || '/etc/nginx/sites-enabled/nextjs.thisgun.net';
const liveDeployNginxSnippetsDir =
  process.env.LIVE_DEPLOY_NGINX_SNIPPETS_DIR || '/etc/nginx/snippets';
const rscPayloads = parseRedirects(
  process.env.LIVE_SMOKE_RSC_PAYLOADS ||
    '/index.txt=>/,/free.txt=>/free,/shop/products/1446772772.txt=>/shop/1446772772,/shop/1446772772.txt=>/shop/1446772772,/shop/list-2010101010.txt=>/shop/list-2010101010,/shop/type-1.txt=>/shop/type-1,/shop/reviews.txt=>/shop/reviews,/shop/qas.txt=>/shop/qas,/shop/search.txt=>/shop/search,/shop/largeimage.txt=>/shop/largeimage'
);
const legacyShopPassthroughPaths = parseCsv(
  process.env.LIVE_SMOKE_LEGACY_SHOP_PASSTHROUGH_PATHS ||
    '/shop/bannerhit.php?bn_id=1,/shop/taxsave.php,/shop/naverpay/naverpay_order.php,/shop/price/naver.php,/shop/kcp/pp_ax_hub.php'
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
  process.env.LIVE_SMOKE_LEGACY_SHOP_REDIRECTS || defaultLegacyShopRedirects
);
const checks = [];
const rootApplyHint =
  'run SERVER-ROOT-COMMANDS.sh status, then dry-run/apply from the live deploy package to install theme/nextjs25, insert nginx includes, and activate the theme';
const exactPhpHint =
  'run SERVER-ROOT-COMMANDS.sh status, then dry-run/apply, or use SERVER-NGINX-PLAN.sh to generate and include the exact PHP-FPM locations';
const themeLocationsHint =
  'run SERVER-ROOT-COMMANDS.sh status, then dry-run/apply, or include g5-nextjs25-theme-locations.conf before generic Gnuboard locations and activate theme/nextjs25';

function trimTrailingSlash(value) {
  return String(value).replace(/\/+$/, '');
}

function shellQuote(value) {
  return `'${String(value).replaceAll("'", "'\\''")}'`;
}

function shellAssignments(values) {
  return Object.entries(values)
    .filter(([, value]) => value !== undefined && value !== null && value !== '')
    .map(([key, value]) => `${key}=${shellQuote(value)}`)
    .join(' ');
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
      throw new Error(`Invalid redirect expectation: ${item}`);
    }
    return { from, to };
  });
}

function appAbsoluteUrl(path) {
  return `${appUrl}${path.startsWith('/') ? path : `/${path}`}`;
}

function normalizeRedirectLocation(value) {
  return trimTrailingSlash(value || '');
}

function appAbsoluteUrlWithQuery(path, params) {
  const url = new URL(appAbsoluteUrl(path));
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }
  return url.toString();
}

function record(area, name, ok, detail, hint = '') {
  checks.push({
    area,
    name,
    status: ok ? 'ok' : 'fail',
    detail: detail || '',
    hint: ok ? '' : hint,
  });
}

function header(headers, name) {
  return headers.get(name) || '';
}

function hasDuplicateHeaderValue(value) {
  return value.includes(',');
}

function expectHeaderEquals(area, headers, name, expected, hint) {
  const actual = header(headers, name);
  record(area, name, actual === expected, actual || '(missing)', hint || `expected ${expected}`);
}

function expectHeaderOneOf(area, headers, name, expectedValues, hint) {
  const actual = header(headers, name);
  record(
    area,
    name,
    expectedValues.includes(actual),
    actual || '(missing)',
    hint || `expected one of ${expectedValues.join(', ')}`
  );
}

function expectHeaderIncludes(area, headers, name, expectedParts, hint) {
  const actual = header(headers, name);
  const missing = expectedParts.filter((part) => !actual.includes(part));
  record(
    area,
    name,
    missing.length === 0,
    actual || '(missing)',
    hint || `missing ${missing.join(', ')}`
  );
}

function expectNoDuplicateHeader(area, headers, name, hint) {
  const actual = header(headers, name);
  record(
    area,
    `${name} duplicate`,
    actual !== '' && !hasDuplicateHeaderValue(actual),
    actual || '(missing)',
    hint || 'remove parent/frontend add_header inheritance for this location'
  );
}

function isNextStaticShellResponse(headers, text) {
  const contentType = header(headers, 'content-type');
  return (
    contentType.includes('text/x-component') ||
    text.includes('<!--g5_nextjs25_static-->') ||
    text.includes('window.__G5_NEXTJS25_CONFIG__') ||
    text.includes('self.__next_f')
  );
}

function setCookieHeaders(headers) {
  if (typeof headers.getSetCookie === 'function') {
    return headers.getSetCookie();
  }

  const value = headers.get('set-cookie');
  return value ? [value] : [];
}

function cookieName(value) {
  const firstPart = String(value || '').split(';', 1)[0] || '';
  return firstPart.split('=', 1)[0].trim();
}

async function fetchText(url, options = {}) {
  const response = await fetch(url, {
    redirect: options.redirect || 'follow',
    headers: options.headers,
  });
  const text = await response.text();
  return { response, text };
}

async function checkFrontend() {
  const url = `${appUrl}/?live-deployment-check=${Date.now()}`;
  const { response, text } = await fetchText(url);

  record('frontend', 'root http', response.ok, `HTTP ${response.status}`, 'root must render');
  record(
    'frontend',
    'nextjs25 runtime config',
    text.includes('window.__G5_NEXTJS25_CONFIG__'),
    text.includes('window.__G5_NEXTJS25_CONFIG__') ? 'present' : 'missing',
    themeLocationsHint
  );
  record(
    'frontend',
    'nextjs25 static assets',
    text.includes('/theme/nextjs25/app/_next/') || text.includes('/_next/static/'),
    text.includes('/theme/nextjs25/app/_next/') || text.includes('/_next/static/')
      ? 'present'
      : 'missing',
    rootApplyHint
  );
  record(
    'frontend',
    'legacy basic theme leakage',
    !text.includes('/theme/basic/'),
    text.includes('/theme/basic/') ? 'theme/basic detected' : 'not detected',
    themeLocationsHint
  );

  expectHeaderEquals(
    'frontend',
    response.headers,
    'x-content-type-options',
    'nosniff',
    exactPhpHint
  );
  expectHeaderEquals(
    'frontend',
    response.headers,
    'x-frame-options',
    'DENY',
    exactPhpHint
  );
  expectHeaderEquals(
    'frontend',
    response.headers,
    'referrer-policy',
    'strict-origin-when-cross-origin',
    'run SERVER-ROOT-APPLY.sh so the frontend snippet is used on route.php and the API snippet is used on /api/index.php'
  );
  expectHeaderIncludes(
    'frontend',
    response.headers,
    'permissions-policy',
    ['camera=()', 'microphone=()', 'geolocation=()'],
    exactPhpHint
  );
  expectHeaderIncludes(
    'frontend',
    response.headers,
    'content-security-policy',
    ["default-src 'self'", "frame-ancestors 'none'"],
    'run SERVER-ROOT-APPLY.sh so the CSP map is included in nginx http {} and frontend locations use the frontend snippet'
  );
}

async function checkApi() {
  const url = `${expectedApiUrl}/settings`;
  const { response, text } = await fetchText(url, {
    headers: { Origin: appOrigin },
  });
  const contentType = header(response.headers, 'content-type');

  record('api', 'settings http', response.ok, `HTTP ${response.status}`, 'API must answer settings');
  record(
    'api',
    'json content',
    contentType.includes('application/json'),
    contentType || '(missing)',
    'route /api/v1/settings to api/index.php'
  );

  try {
    const payload = JSON.parse(text);
    record('api', 'settings payload', payload?.success === true, `success=${payload?.success}`, '');
  } catch (error) {
    record('api', 'settings payload', false, error.message, 'API returned non-JSON body');
  }

  expectHeaderEquals(
    'api',
    response.headers,
    'access-control-allow-origin',
    appOrigin,
    'allow the live frontend origin in API CORS'
  );
  expectHeaderEquals(
    'api',
    response.headers,
    'x-content-type-options',
    'nosniff',
    exactPhpHint
  );
  expectHeaderEquals(
    'api',
    response.headers,
    'x-frame-options',
    'DENY',
    exactPhpHint
  );
  expectHeaderOneOf(
    'api',
    response.headers,
    'referrer-policy',
    ['no-referrer', 'strict-origin-when-cross-origin'],
    'expected no-referrer after SERVER-ROOT-APPLY.sh, or the parent strict-origin policy before root nginx access is available'
  );
  expectNoDuplicateHeader(
    'api',
    response.headers,
    'referrer-policy',
    'run SERVER-ROOT-APPLY.sh so parent/frontend Referrer-Policy is hidden before adding the API value'
  );
  expectHeaderIncludes(
    'api',
    response.headers,
    'permissions-policy',
    ['camera=()', 'microphone=()', 'geolocation=()'],
    exactPhpHint
  );
  expectHeaderEquals(
    'api',
    response.headers,
    'x-permitted-cross-domain-policies',
    'none',
    exactPhpHint
  );
}

async function checkPublicAsset(path, expected) {
  const url = appAbsoluteUrl(path);
  const { response, text } = await fetchText(url);
  const contentType = header(response.headers, 'content-type');

  record('public asset', `${path} http`, response.ok, `HTTP ${response.status}`, 'asset must be routed');
  record(
    'public asset',
    `${path} content-type`,
    expected.contentType.some((part) => contentType.includes(part)),
    contentType || '(missing)',
    `expected one of ${expected.contentType.join(', ')}`
  );
  record(
    'public asset',
    `${path} body`,
    expected.body(text),
    expected.describe(text),
    expected.hint
  );
  expectHeaderIncludes(
    'public asset',
    response.headers,
    'permissions-policy',
    ['camera=()', 'microphone=()', 'geolocation=()'],
    'run SERVER-ROOT-APPLY.sh so public asset locations include the frontend security snippet'
  );
}

async function checkRedirect(from, to) {
  const url = appAbsoluteUrl(from);
  const response = await fetch(url, { redirect: 'manual' });
  const location = header(response.headers, 'location');
  const expected = appAbsoluteUrl(to);
  record(
    'rewrite',
    `${from} => ${to}`,
    [301, 308].includes(response.status) &&
      normalizeRedirectLocation(location) === normalizeRedirectLocation(expected),
    `HTTP ${response.status} location=${location || '(missing)'}`,
    themeLocationsHint
  );
}

async function checkLegacyShopRedirect(redirect) {
  const url = appAbsoluteUrl(redirect.from);
  const response = await fetch(url, { redirect: 'manual' });
  const location = header(response.headers, 'location');
  const expected = appAbsoluteUrl(redirect.to);
  record(
    'legacy shop redirect',
    `${redirect.from} => ${redirect.to}`,
    [301, 302, 307, 308].includes(response.status) &&
      normalizeRedirectLocation(location) === normalizeRedirectLocation(expected),
    `HTTP ${response.status} location=${location || '(missing)'}`,
    themeLocationsHint
  );
}

async function checkLegacyAdminLogin() {
  const adminUrl = `${appUrl}/adm/`;
  const path = `/bbs/login.php?url=${encodeURIComponent(adminUrl)}`;
  const url = appAbsoluteUrl(path);
  const { response, text } = await fetchText(url, { redirect: 'manual' });
  const location = header(response.headers, 'location');
  const contentType = header(response.headers, 'content-type');
  const sessionCookies = setCookieHeaders(response.headers).filter(
    (value) => cookieName(value) === 'PHPSESSID' || cookieName(value).endsWith('PHPSESSID')
  );

  record(
    'legacy admin login',
    'original login http',
    response.status === 200,
    `HTTP ${response.status} location=${location || '(none)'}`,
    'keep /bbs/login.php?url=/adm on original Gnuboard PHP login.php'
  );
  record(
    'legacy admin login',
    'html content',
    contentType.includes('text/html'),
    contentType || '(missing)',
    'original Gnuboard login.php must render an HTML form'
  );
  record(
    'legacy admin login',
    'original form action',
    text.includes('/bbs/login_check.php') && text.includes('name="flogin"'),
    text.includes('/bbs/login_check.php') ? 'form action detected' : 'form action missing',
    'admin login must post to /bbs/login_check.php so Gnuboard sessions and admin checks work'
  );
  record(
    'legacy admin login',
    'not nextjs shell',
    !isNextStaticShellResponse(response.headers, text),
    `HTTP ${response.status} content-type=${contentType || '(missing)'}`,
    'admin login target must not be rewritten to the Next.js login route'
  );
  record(
    'legacy admin login',
    'single session cookie',
    sessionCookies.length <= 1,
    `${sessionCookies.length} session Set-Cookie header(s)`,
    'Gnuboard session SameSite adjustment must replace the PHPSESSID Set-Cookie header instead of appending a duplicate'
  );
}

async function checkLegacyShopPassthrough(path) {
  const url = appAbsoluteUrlWithQuery(path, {
    'legacy-shop-passthrough-smoke': String(Date.now()),
  });
  const { response, text } = await fetchText(url, { redirect: 'manual' });
  record(
    'legacy shop php',
    `${path} http`,
    response.status !== 404,
    `HTTP ${response.status}`,
    exactPhpHint
  );
  record(
    'legacy shop php',
    `${path} passthrough`,
    !isNextStaticShellResponse(response.headers, text),
    `HTTP ${response.status} content-type=${header(response.headers, 'content-type') || '(missing)'}`,
    'keep original YoungCart PHP/PG/price paths before the Next.js catch-all route'
  );
}

async function checkRscPayload(payload) {
  const path = payload.from.startsWith('/') ? payload.from : `/${payload.from}`;
  const url = `${appAbsoluteUrl(path)}?_rsc=live-rsc-check-${Date.now()}`;
  const { response, text } = await fetchText(url);
  const contentType = header(response.headers, 'content-type');
  const expectedPublicUrl = appAbsoluteUrl(payload.to);

  record('rsc payload', `${payload.from} http`, response.ok, `HTTP ${response.status}`, themeLocationsHint);
  record(
    'rsc payload',
    `${payload.from} content-type`,
    contentType.includes('text/x-component') || contentType.includes('text/plain'),
    contentType || '(missing)',
    'dynamic .txt RSC payloads must be routed to their static sentinel payload'
  );
  record(
    'rsc payload',
    `${payload.from} body`,
    text.includes('$Sreact.fragment') && !text.includes('404:') && !text.includes('NOT_FOUND'),
    text.slice(0, 80).replace(/\s+/g, ' '),
    `expected RSC payload for ${expectedPublicUrl}`
  );
}

await checkFrontend();
await checkApi();
await checkPublicAsset('/manifest.webmanifest', {
  contentType: ['manifest', 'json'],
  body: (text) => {
    try {
      const manifest = JSON.parse(text);
      return manifest.start_url === '/' && manifest.scope === '/';
    } catch {
      return false;
    }
  },
  describe: (text) => {
    try {
      const manifest = JSON.parse(text);
      return `start_url=${manifest.start_url || '(missing)'} scope=${manifest.scope || '(missing)'}`;
    } catch {
      return 'not JSON';
    }
  },
  hint: themeLocationsHint,
});
await checkPublicAsset('/robots.txt', {
  contentType: ['text/plain'],
  body: (text) =>
    text.includes('User-agent:') &&
    text.includes(`Host: ${appUrl}`) &&
    text.includes(`Sitemap: ${appUrl}/sitemap.xml`) &&
    text.includes(`Sitemap: ${appUrl}/sitemap-posts.xml`),
  describe: (text) => text.slice(0, 80).replace(/\s+/g, ' '),
  hint: themeLocationsHint,
});
await checkPublicAsset('/sitemap.xml', {
  contentType: ['xml', 'text/plain'],
  body: (text) => text.includes('<urlset') && text.includes(`<loc>${appUrl}`),
  describe: (text) => text.slice(0, 80).replace(/\s+/g, ' '),
  hint: themeLocationsHint,
});
await checkPublicAsset('/sitemap-posts.xml', {
  contentType: ['xml', 'text/plain'],
  body: (text) => text.includes('<urlset'),
  describe: (text) => text.slice(0, 80).replace(/\s+/g, ' '),
  hint: themeLocationsHint,
});
await checkPublicAsset('/sw.js', {
  contentType: ['javascript'],
  body: (text) => text.includes('self.addEventListener') && text.includes('CACHE_NAME'),
  describe: (text) => text.slice(0, 80).replace(/\s+/g, ' '),
  hint: themeLocationsHint,
});
for (const payload of rscPayloads) {
  await checkRscPayload(payload);
}
for (const path of legacyShopPassthroughPaths) {
  await checkLegacyShopPassthrough(path);
}
await checkLegacyAdminLogin();
for (const redirect of legacyShopRedirects) {
  await checkLegacyShopRedirect(redirect);
}
await checkRedirect('/boards/free', '/bbs/free');
await checkRedirect('/boards/free/6', '/bbs/free/6');
await checkRedirect('/shop/products/1446772772', '/shop/1446772772');
await checkRedirect('/shop/categories/2010101010', '/shop/list-2010101010');

console.table(
  checks.map(({ area, name, status, detail }) => ({
    area,
    check: name,
    status,
    detail,
  }))
);

const failures = checks.filter((check) => check.status === 'fail');
if (failures.length > 0) {
  const rootCommandEnv = shellAssignments({
    WEB_ROOT: liveDeployWebRoot,
    NGINX_CONF: liveDeployNginxConf,
    SITE_CONF: liveDeployNginxSiteConf,
    NGINX_SNIPPETS_DIR: liveDeployNginxSnippetsDir,
  });

  console.error(`[check-live-deployment] ${failures.length} issue(s) found for ${appUrl}`);
  console.error(
    [
      '[check-live-deployment] recommended root steps:',
      `  cd ${liveDeployRemoteDir}/nextjs25-live`,
      '  bash SERVER-ROOT-COMMANDS.sh status',
      `  sudo env ${rootCommandEnv} bash SERVER-ROOT-COMMANDS.sh dry-run`,
      `  sudo env ${rootCommandEnv} CONFIRM_APPLY=nextjs25 bash SERVER-ROOT-COMMANDS.sh apply-and-verify`,
    ].join('\n')
  );
  for (const failure of failures) {
    console.error(`- [${failure.area}] ${failure.name}: ${failure.detail}`);
    if (failure.hint) {
      console.error(`  hint: ${failure.hint}`);
    }
  }
  process.exit(1);
}

console.log(`[check-live-deployment] live deployment posture passed for ${appUrl}`);
