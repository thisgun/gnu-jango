import { chromium } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const appUrl = trimTrailingSlash(process.env.LOCAL_APP_URL || 'http://127.0.0.20');
const expectedApiUrl = trimTrailingSlash(
  process.env.LOCAL_EXPECTED_API_URL || `${appUrl}/api/v1`
);
let authId = process.env.LOCAL_SMOKE_LOGIN_ID || '';
let authPassword = process.env.LOCAL_SMOKE_LOGIN_PASSWORD || '';
let adminAuthId = process.env.LOCAL_SMOKE_ADMIN_LOGIN_ID || '';
let adminAuthPassword = process.env.LOCAL_SMOKE_ADMIN_LOGIN_PASSWORD || '';
let adminSmokeQaId = process.env.LOCAL_SMOKE_ADMIN_QA_ID || '';
let adminSmokeOrderId = process.env.LOCAL_SMOKE_ADMIN_ORDER_ID || '';
const adminMemberDetailId =
  process.env.LOCAL_SMOKE_AUTH_ADMIN_MEMBER_DETAIL_ID || 'nextjs_admin_smoke';
const requireAuth =
  process.argv.includes('--require-auth') || process.env.LOCAL_SMOKE_REQUIRE_AUTH === '1';
const requireAdminAuth =
  process.argv.includes('--require-admin') || process.env.LOCAL_SMOKE_REQUIRE_ADMIN === '1';
const seedAuth =
  process.argv.includes('--seed-auth') || process.env.LOCAL_SMOKE_SEED_AUTH === '1';
const seedAdminAuth =
  process.argv.includes('--seed-admin') || process.env.LOCAL_SMOKE_SEED_ADMIN === '1';
const mobileViewport =
  process.argv.includes('--mobile') || process.env.LOCAL_SMOKE_MOBILE === '1';
const activeViewport = mobileViewport
  ? { name: 'mobile', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }
  : { name: 'desktop', viewport: { width: 1366, height: 900 } };
const browserRuntimeRetries = Math.max(
  0,
  Number.parseInt(process.env.LOCAL_SMOKE_BROWSER_RUNTIME_RETRIES || '0', 10) || 0
);

function parseCsvEnv(name, fallback) {
  if (!Object.prototype.hasOwnProperty.call(process.env, name)) {
    return fallback;
  }

  return (process.env[name] || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

for (const arg of process.argv.slice(2)) {
  if (
    !['--require-auth', '--require-admin', '--seed-auth', '--seed-admin', '--mobile'].includes(arg)
  ) {
    console.error(`[check-local-browser] Unknown argument: ${arg}`);
    console.error(
      '[check-local-browser] Supported arguments: --require-auth, --require-admin, --seed-auth, --seed-admin, --mobile'
    );
    process.exit(1);
  }
}

const smokePaths = [
  {
    label: 'home',
    path: '/',
    checkShortLinks: true,
    expectedHeaderHrefs: parseCsvEnv('LOCAL_SMOKE_EXPECTED_HEADER_HREFS', [
      '/free',
      '/shop',
      '/faq',
      '/mypage',
      '/content/company',
    ]),
    forbiddenHeaderHrefParts: parseCsvEnv('LOCAL_SMOKE_FORBIDDEN_HEADER_HREF_PARTS', [
      '/boards/',
    ]),
  },
  {
    label: 'board list',
    path: process.env.LOCAL_SMOKE_BOARD_PATH || '/free',
    expectedApiParts: ['/settings', '/boards/free', '/boards/free/posts'],
    expectedTitleIncludes: '자유게시판',
    expectedH1: '자유게시판',
  },
  {
    label: 'board post',
    path: process.env.LOCAL_SMOKE_POST_PATH || '/free/6',
    expectedApiParts: ['/settings', '/boards/free', '/posts/free/6'],
    expectedTitleIncludes: 'Сериал Моя геройская академия',
    expectedH1:
      'Сериал Моя геройская академия: Вне закона (2 сезон) 6 серия смотреть онлайн в HD 1080 Lordfilm',
    expectedJsonLdTypes: ['Article', 'BreadcrumbList'],
  },
  {
    label: 'board post seo',
    path:
      process.env.LOCAL_SMOKE_POST_SEO_PATH ||
      '/free/%D0%A1%D0%B5%D1%80%D0%B8%D0%B0%D0%BB-%D0%9C%D0%BE%D1%8F-%D0%B3%D0%B5%D1%80%D0%BE%D0%B9%D1%81%D0%BA%D0%B0%D1%8F-%D0%B0%D0%BA%D0%B0%D0%B4%D0%B5%D0%BC%D0%B8%D1%8F-%D0%92%D0%BD%D0%B5-%D0%B7%D0%B0%D0%BA%D0%BE%D0%BD%D0%B0-2-%D1%81%D0%B5%D0%B7%D0%BE%D0%BD/',
    expectedFinalPath: process.env.LOCAL_SMOKE_POST_PATH || '/free/6',
    expectedApiParts: ['/settings', '/boards/free', '/posts/free/seo/'],
    expectedTitleIncludes: 'Сериал Моя геройская академия',
    expectedH1:
      'Сериал Моя геройская академия: Вне закона (2 сезон) 6 серия смотреть онлайн в HD 1080 Lordfilm',
    expectedJsonLdTypes: ['Article', 'BreadcrumbList'],
  },
  {
    label: 'board write',
    path: process.env.LOCAL_SMOKE_WRITE_PATH || '/free/write',
    expectedFinalPath: process.env.LOCAL_SMOKE_WRITE_FINAL_PATH || '/login',
    expectedApiParts: ['/boards/free'],
    expectedSelectors: ['form', 'input[name="mb_id"]', 'input[name="mb_password"]'],
  },
  {
    label: 'content',
    path: process.env.LOCAL_SMOKE_CONTENT_PATH || '/content/company',
    expectedApiParts: ['/content/company'],
    expectedTitleIncludes: '회사소개',
    expectedH1: '회사소개',
  },
  {
    label: 'faq',
    path: process.env.LOCAL_SMOKE_FAQ_PATH || '/faq',
    expectedApiParts: ['/settings', '/faqs'],
    expectedTitleIncludes: 'FAQ',
  },
  {
    label: 'polls',
    path: process.env.LOCAL_SMOKE_POLLS_PATH || '/polls',
    expectedApiParts: ['/settings', '/polls/current'],
    expectedTitleIncludes: '설문조사',
    allowedBadResponses: [`404 ${expectedApiUrl}/polls/current`],
  },
  {
    label: 'recent',
    path: process.env.LOCAL_SMOKE_RECENT_PATH || '/recent',
    expectedApiParts: ['/settings', '/recent/groups', '/recent?page=1&limit=20'],
    expectedTitleIncludes: '전체 게시물',
  },
  {
    label: 'search',
    path: process.env.LOCAL_SMOKE_SEARCH_PATH || '/search?q=test',
    expectedApiParts: ['/settings', '/search?q=test'],
    expectedTitleIncludes: '검색',
    allowSeoQueryStripping: true,
  },
  {
    label: 'shop product',
    path: process.env.LOCAL_SMOKE_PRODUCT_PATH || '/shop/1446772772',
    // Product details are loaded in the server component for the server runtime;
    // the browser assertion below checks the rendered product and metadata.
    expectedApiParts: ['/settings'],
    expectedTitleIncludes: 'TH-블락체크 셔츠-그레이2 [면세]',
    expectedH1: 'TH-블락체크 셔츠-그레이2 [면세]',
    expectedJsonLdTypes: ['Product', 'BreadcrumbList'],
  },
  {
    label: 'shop product seo',
    path:
      process.env.LOCAL_SMOKE_PRODUCT_SEO_PATH ||
      '/shop/th-%EB%B8%94%EB%9D%BD%EC%B2%B4%ED%81%AC-%EC%85%94%EC%B8%A0-%EA%B7%B8%EB%A0%88%EC%9D%B42-%EB%A9%B4%EC%84%B8/',
    expectedFinalPath: process.env.LOCAL_SMOKE_PRODUCT_PATH || '/shop/1446772772',
    expectedApiParts: ['/settings', '/shop/products/seo/'],
    // The product page probes an item ID first, then resolves the SEO slug.
    allowedBadResponses: [`404 ${expectedApiUrl}/shop/products/`],
    expectedJsonLdTypes: ['Product', 'BreadcrumbList'],
  },
  {
    label: 'shop category',
    path: process.env.LOCAL_SMOKE_CATEGORY_PATH || '/shop/list-2010101010',
    expectedApiParts: ['/settings', '/shop/categories/2010101010'],
    expectedTitleIncludes: '체크',
    expectedH1: '체크',
  },
  {
    label: 'shop type',
    path: process.env.LOCAL_SMOKE_TYPE_PATH || '/shop/type-1',
    expectedApiParts: ['/settings', '/shop/products?', 'it_type1=1'],
    expectedTitleIncludes: '베스트 상품',
    expectedH1: '베스트 상품',
  },
  {
    label: 'shop search',
    path: process.env.LOCAL_SMOKE_SHOP_SEARCH_PATH || '/shop/search?q=TH&qcaid=2010101010&qname=1',
    expectedApiParts: ['/settings', '/shop/products?', 'q=TH', 'ca_id=2010101010', 'qname=1'],
    expectedTitleIncludes: 'TH',
    allowSeoQueryStripping: true,
  },
  {
    label: 'shop largeimage',
    path: process.env.LOCAL_SMOKE_SHOP_LARGEIMAGE_PATH || '/shop/largeimage?it_id=1446772772&no=1',
    expectedApiParts: ['/settings', '/shop/products/1446772772'],
    expectedTitleIncludes: '큰 이미지',
    expectedSelectors: ['a[href^="/shop/"]'],
  },
  {
    label: 'shop events',
    path: process.env.LOCAL_SMOKE_EVENTS_PATH || '/shop/events',
    expectedApiParts: ['/settings', '/shop/events'],
    expectedTitleIncludes: '기획전',
    expectedH1: '기획전',
  },
  {
    label: 'shop couponzone',
    path: process.env.LOCAL_SMOKE_COUPONZONE_PATH || '/shop/couponzone',
    expectedApiParts: ['/settings', '/shop/coupons/zone'],
    expectedTitleIncludes: '쿠폰존',
    expectedH1: '쿠폰존',
  },
  {
    label: 'shop cart',
    path: process.env.LOCAL_SMOKE_CART_PATH || '/shop/cart',
    expectedApiParts: ['/settings', '/shop/cart'],
    expectedTitleIncludes: '장바구니',
  },
  {
    label: 'shop order guest',
    path: process.env.LOCAL_SMOKE_ORDER_PATH || '/shop/order',
    expectedFinalPath: process.env.LOCAL_SMOKE_ORDER_FINAL_PATH || '/shop/cart',
    expectedApiParts: ['/settings', '/shop/cart', '/shop/payment/config'],
    forbiddenApiParts: ['/auth/me'],
    skipSeoUrlCheck: true,
    expectedTitleIncludes: '장바구니',
  },
  {
    label: 'shop compare',
    path: process.env.LOCAL_SMOKE_COMPARE_PATH || '/shop/compare',
    expectedApiParts: ['/settings'],
    expectedTitleIncludes: '상품 비교',
  },
  {
    label: 'mypage requires login',
    path: process.env.LOCAL_SMOKE_MYPAGE_GUEST_PATH || '/mypage',
    expectedFinalPath:
      process.env.LOCAL_SMOKE_MYPAGE_GUEST_FINAL_PATH || '/login?redirect=%2Fmypage',
    expectedApiParts: ['/settings'],
    forbiddenApiParts: ['/shop/orders', '/shop/wishlist', '/members/me', '/shop/addresses'],
    expectedSelectors: ['form', 'input[name="mb_id"]', 'input[name="mb_password"]'],
    skipSeoUrlCheck: true,
  },
  {
    label: 'admin orders requires login',
    path: process.env.LOCAL_SMOKE_ADMIN_ORDERS_PATH || '/admin/shop/orders',
    expectedFinalPath:
      process.env.LOCAL_SMOKE_ADMIN_ORDERS_FINAL_PATH ||
      '/login?redirect=%2Fadmin%2Fshop%2Forders',
    expectedApiParts: ['/settings'],
    forbiddenApiParts: ['/admin/shop/orders', '/me'],
    expectedSelectors: ['form', 'input[name="mb_id"]', 'input[name="mb_password"]'],
    skipSeoUrlCheck: true,
  },
  {
    label: 'shop orders guest lookup',
    path: process.env.LOCAL_SMOKE_ORDERS_PATH || '/shop/orders',
    expectedApiParts: ['/settings'],
    forbiddenApiParts: ['/shop/orders'],
    expectedSelectors: ['form', 'input[type="text"]', 'input[type="password"]', 'a[href="/login?redirect=%2Fshop%2Forders"]'],
    skipSeoUrlCheck: true,
  },
  {
    label: 'shop wishlist requires login',
    path: process.env.LOCAL_SMOKE_WISHLIST_PATH || '/shop/wishlist',
    expectedFinalPath:
      process.env.LOCAL_SMOKE_WISHLIST_FINAL_PATH || '/login?redirect=%2Fshop%2Fwishlist',
    expectedApiParts: ['/settings'],
    forbiddenApiParts: ['/shop/wishlist'],
    expectedSelectors: ['form', 'input[name="mb_id"]', 'input[name="mb_password"]'],
    skipSeoUrlCheck: true,
  },
];

const authSmokePaths = [
  {
    label: 'mypage authenticated',
    path: process.env.LOCAL_SMOKE_MYPAGE_PATH || '/mypage',
    expectedApiParts: [
      '/auth/me',
      '/shop/orders?per_page=1',
      '/shop/wishlist',
      '/members/me/posts?per_page=1',
      '/members/me/comments?per_page=1',
      '/shop/addresses',
    ],
    forbiddenFinalPathParts: ['/login'],
  },
  {
    label: 'shop orders authenticated',
    path: process.env.LOCAL_SMOKE_AUTH_ORDERS_PATH || '/shop/orders',
    expectedApiParts: ['/auth/me', '/shop/orders?page=1&per_page=10'],
    forbiddenFinalPathParts: ['/login'],
  },
  {
    label: 'shop wishlist authenticated',
    path: process.env.LOCAL_SMOKE_AUTH_WISHLIST_PATH || '/shop/wishlist',
    expectedApiParts: ['/auth/me', '/shop/wishlist'],
    forbiddenFinalPathParts: ['/login'],
  },
];

const adminAuthSmokePaths = [
  {
    label: 'admin dashboard authenticated',
    path: process.env.LOCAL_SMOKE_AUTH_ADMIN_DASHBOARD_PATH || '/admin',
    expectedApiParts: [
      '/auth/me',
      '/admin/dashboard/stats',
      '/admin/dashboard/recent-orders?limit=5',
      '/admin/dashboard/recent-members?limit=5',
    ],
    forbiddenFinalPathParts: ['/login'],
  },
  {
    label: 'admin orders authenticated',
    path: process.env.LOCAL_SMOKE_AUTH_ADMIN_ORDERS_PATH || '/admin/shop/orders',
    expectedApiParts: ['/auth/me', '/admin/shop/orders?page=1&per_page=20'],
    expectedSelectors: ['table'],
    forbiddenFinalPathParts: ['/login'],
  },
  {
    label: 'admin members authenticated',
    path: process.env.LOCAL_SMOKE_AUTH_ADMIN_MEMBERS_PATH || '/admin/members',
    expectedApiParts: ['/auth/me', '/admin/members?page=1&per_page=20'],
    expectedSelectors: ['form', 'table'],
    forbiddenFinalPathParts: ['/login'],
  },
  {
    label: 'admin member detail authenticated',
    path:
      process.env.LOCAL_SMOKE_AUTH_ADMIN_MEMBER_DETAIL_PATH ||
      `/admin/members/${encodeURIComponent(adminMemberDetailId)}`,
    expectedApiParts: ['/auth/me', `/admin/members/${encodeURIComponent(adminMemberDetailId)}`],
    expectedSelectors: ['form'],
    forbiddenFinalPathParts: ['/login'],
  },
  {
    label: 'admin boards authenticated',
    path: process.env.LOCAL_SMOKE_AUTH_ADMIN_BOARDS_PATH || '/admin/boards',
    expectedApiParts: ['/auth/me', '/admin/boards'],
    expectedSelectors: ['form', 'table'],
    forbiddenFinalPathParts: ['/login'],
  },
  {
    label: 'admin board detail authenticated',
    path: process.env.LOCAL_SMOKE_AUTH_ADMIN_BOARD_DETAIL_PATH || '/admin/boards/free',
    expectedApiParts: ['/auth/me', '/admin/boards/free'],
    expectedSelectors: ['form'],
    forbiddenFinalPathParts: ['/login'],
  },
  {
    label: 'admin settings authenticated',
    path: process.env.LOCAL_SMOKE_AUTH_ADMIN_SETTINGS_PATH || '/admin/settings',
    expectedApiParts: ['/auth/me', '/admin/settings'],
    expectedSelectors: ['form'],
    forbiddenFinalPathParts: ['/login'],
  },
  {
    label: 'admin qas authenticated',
    path: process.env.LOCAL_SMOKE_AUTH_ADMIN_QAS_PATH || '/admin/qas',
    expectedApiParts: ['/auth/me', '/qas?page=1&per_page=20&scope=admin&sfl=qa_subject'],
    expectedSelectors: ['form', 'table'],
    forbiddenFinalPathParts: ['/login'],
  },
  {
    label: 'admin shop categories authenticated',
    path: process.env.LOCAL_SMOKE_AUTH_ADMIN_CATEGORIES_PATH || '/admin/shop/categories',
    expectedApiParts: ['/auth/me', '/admin/shop/categories'],
    expectedSelectors: ['form'],
    forbiddenFinalPathParts: ['/login'],
  },
  {
    label: 'admin shop products authenticated',
    path: process.env.LOCAL_SMOKE_AUTH_ADMIN_PRODUCTS_PATH || '/admin/shop/products',
    expectedApiParts: [
      '/auth/me',
      '/admin/shop/products?page=1&per_page=20',
      '/admin/shop/categories',
    ],
    expectedSelectors: ['form', 'table'],
    forbiddenFinalPathParts: ['/login'],
    // Legacy catalog rows can reference images that no longer exist. The
    // page replaces these failed thumbnails with its neutral placeholder.
    allowedBadResponses: ['/_next/image?url=%2Fdata%2Fitem%2Fimage'],
  },
  {
    label: 'admin shop product detail authenticated',
    path:
      process.env.LOCAL_SMOKE_AUTH_ADMIN_PRODUCT_DETAIL_PATH ||
      '/admin/shop/products/1446772772',
    expectedApiParts: [
      '/auth/me',
      '/admin/shop/categories',
      '/admin/shop/products/1446772772',
    ],
    expectedSelectors: ['form'],
    forbiddenFinalPathParts: ['/login'],
  },
];

function overrideSmokePath(label, values) {
  const check = smokePaths.find((item) => item.label === label);
  if (!check) return;

  for (const [key, value] of Object.entries(values)) {
    if (value) {
      check[key] = value;
    }
  }
}

overrideSmokePath('board post', {
  expectedTitleIncludes: process.env.LOCAL_SMOKE_POST_TITLE,
  expectedH1: process.env.LOCAL_SMOKE_POST_H1,
});

overrideSmokePath('board post seo', {
  expectedFinalPath: process.env.LOCAL_SMOKE_POST_SEO_FINAL_PATH,
  expectedTitleIncludes: process.env.LOCAL_SMOKE_POST_SEO_TITLE || process.env.LOCAL_SMOKE_POST_TITLE,
  expectedH1: process.env.LOCAL_SMOKE_POST_SEO_H1 || process.env.LOCAL_SMOKE_POST_H1,
});

const skippedSmokeLabels = new Set(
  (process.env.LOCAL_SMOKE_SKIP_LABELS || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
);

function filterSkippedChecks(checks) {
  if (skippedSmokeLabels.size === 0) {
    return checks;
  }

  return checks.filter((check) => !skippedSmokeLabels.has(check.label));
}

function trimTrailingSlash(value) {
  return String(value).replace(/\/+$/, '');
}

function normalizePath(value) {
  return value.startsWith('/') ? value : `/${value}`;
}

function fail(message, details = undefined) {
  console.error(`[check-local-browser] ${message}`);
  if (details) {
    console.error(JSON.stringify(details, null, 2));
  }
  process.exit(1);
}

if (seedAuth) {
  seedLocalSmokeUser();
}

if (seedAdminAuth) {
  seedLocalSmokeAdmin();
  seedLocalSmokeOrder();
  seedLocalSmokeQa();
}

if (adminSmokeOrderId) {
  adminAuthSmokePaths.push({
    label: 'admin order detail authenticated',
    path:
      process.env.LOCAL_SMOKE_AUTH_ADMIN_ORDER_DETAIL_PATH ||
      `/admin/shop/orders/${adminSmokeOrderId}`,
    expectedApiParts: ['/auth/me', `/admin/shop/orders/${adminSmokeOrderId}`],
    expectedSelectors: ['table', '#tracking'],
    forbiddenFinalPathParts: ['/login'],
  });
}

if (adminSmokeQaId) {
  adminAuthSmokePaths.push({
    label: 'admin qa detail authenticated',
    path:
      process.env.LOCAL_SMOKE_AUTH_ADMIN_QA_DETAIL_PATH || `/admin/qas/${adminSmokeQaId}`,
    expectedApiParts: ['/auth/me', `/qas/${adminSmokeQaId}`],
    expectedSelectors: ['form'],
    forbiddenFinalPathParts: ['/login'],
  });
}

if (requireAuth && (!authId || !authPassword)) {
  fail('authenticated checks require LOCAL_SMOKE_LOGIN_ID and LOCAL_SMOKE_LOGIN_PASSWORD');
}

if (requireAdminAuth && (!adminAuthId || !adminAuthPassword)) {
  fail(
    'admin authenticated checks require LOCAL_SMOKE_ADMIN_LOGIN_ID and LOCAL_SMOKE_ADMIN_LOGIN_PASSWORD'
  );
}

async function authenticateContext(context, credentials) {
  const { id, password, label, idEnv, passwordEnv } = credentials;
  if (!id && !password) return false;
  if (!id || !password) {
    fail(`${idEnv} and ${passwordEnv} must be set together`);
  }

  const response = await fetch(`${expectedApiUrl}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ mb_id: id, mb_password: password }),
  });

  let envelope = null;
  try {
    envelope = await response.json();
  } catch {
    // handled below with a clearer failure message
  }

  const token = envelope?.data?.token;
  const refreshToken = envelope?.data?.refresh_token;
  if (!response.ok || !envelope?.success || !token) {
    fail(`${label} smoke login failed`, {
      status: response.status,
      message: envelope?.message || response.statusText,
    });
  }

  const cookies = [
    {
      name: 'g5_token',
      value: token,
      url: appUrl,
      sameSite: 'Lax',
    },
  ];

  if (refreshToken) {
    cookies.push({
      name: 'g5_refresh',
      value: refreshToken,
      url: appUrl,
      sameSite: 'Lax',
    });
  }

  await context.addCookies(cookies);
  await context.addInitScript((accessToken) => {
    window.localStorage.setItem('g5_token', accessToken);
  }, token);
  return true;
}

function seedLocalSmokeUser() {
  const scriptPath = fileURLToPath(
    new URL('../../scripts/seed_nextjs_smoke_user.php', import.meta.url)
  );
  const seedEnv = {
    ...process.env,
    LOCAL_SMOKE_LOGIN_ID: authId || 'nextjs_smoke',
    LOCAL_SMOKE_LOGIN_PASSWORD: authPassword || 'NextjsSmoke123!',
  };

  const result = spawnSync('php', [scriptPath, '--json'], {
    env: seedEnv,
    encoding: 'utf8',
    windowsHide: true,
  });

  if (result.error) {
    fail(`failed to run local smoke user seed: ${result.error.message}`);
  }

  if (result.status !== 0) {
    fail('local smoke user seed failed', {
      status: result.status,
      stderr: result.stderr.trim(),
      stdout: result.stdout.trim(),
    });
  }

  let payload = null;
  try {
    payload = JSON.parse(result.stdout.trim());
  } catch {
    fail('local smoke user seed returned invalid JSON', {
      stdout: result.stdout.trim(),
      stderr: result.stderr.trim(),
    });
  }

  if (!payload?.success || !payload.id || !payload.password) {
    fail('local smoke user seed did not return credentials', payload);
  }

  authId = String(payload.id);
  authPassword = String(payload.password);
}

function seedLocalSmokeAdmin() {
  const scriptPath = fileURLToPath(
    new URL('../../scripts/seed_nextjs_smoke_user.php', import.meta.url)
  );
  const seedEnv = {
    ...process.env,
    LOCAL_SMOKE_ADMIN_LOGIN_ID: adminAuthId || 'nextjs_admin_smoke',
    LOCAL_SMOKE_ADMIN_LOGIN_PASSWORD: adminAuthPassword || 'NextjsAdminSmoke123!',
  };

  const result = spawnSync('php', [scriptPath, '--admin', '--json'], {
    env: seedEnv,
    encoding: 'utf8',
    windowsHide: true,
  });

  if (result.error) {
    fail(`failed to run local smoke admin seed: ${result.error.message}`);
  }

  if (result.status !== 0) {
    fail('local smoke admin seed failed', {
      status: result.status,
      stderr: result.stderr.trim(),
      stdout: result.stdout.trim(),
    });
  }

  let payload = null;
  try {
    payload = JSON.parse(result.stdout.trim());
  } catch {
    fail('local smoke admin seed returned invalid JSON', {
      stdout: result.stdout.trim(),
      stderr: result.stderr.trim(),
    });
  }

  if (!payload?.success || !payload.id || !payload.password) {
    fail('local smoke admin seed did not return credentials', payload);
  }

  adminAuthId = String(payload.id);
  adminAuthPassword = String(payload.password);
}

function seedLocalSmokeOrder() {
  const scriptPath = fileURLToPath(
    new URL('../../scripts/seed_nextjs_smoke_order.php', import.meta.url)
  );
  const seedEnv = {
    ...process.env,
    LOCAL_SMOKE_ADMIN_LOGIN_ID: adminAuthId || 'nextjs_admin_smoke',
  };

  const result = spawnSync('php', [scriptPath, '--json'], {
    env: seedEnv,
    encoding: 'utf8',
    windowsHide: true,
  });

  if (result.error) {
    fail(`failed to run local smoke order seed: ${result.error.message}`);
  }

  if (result.status !== 0) {
    fail('local smoke order seed failed', {
      status: result.status,
      stderr: result.stderr.trim(),
      stdout: result.stdout.trim(),
    });
  }

  let payload = null;
  try {
    payload = JSON.parse(result.stdout.trim());
  } catch {
    fail('local smoke order seed returned invalid JSON', {
      stdout: result.stdout.trim(),
      stderr: result.stderr.trim(),
    });
  }

  if (!payload?.success || !payload.id) {
    fail('local smoke order seed did not return an id', payload);
  }

  adminSmokeOrderId = String(payload.id);
}

function seedLocalSmokeQa() {
  const scriptPath = fileURLToPath(
    new URL('../../scripts/seed_nextjs_smoke_qa.php', import.meta.url)
  );
  const seedEnv = {
    ...process.env,
    LOCAL_SMOKE_ADMIN_LOGIN_ID: adminAuthId || 'nextjs_admin_smoke',
  };

  const result = spawnSync('php', [scriptPath, '--json'], {
    env: seedEnv,
    encoding: 'utf8',
    windowsHide: true,
  });

  if (result.error) {
    fail(`failed to run local smoke Q&A seed: ${result.error.message}`);
  }

  if (result.status !== 0) {
    fail('local smoke Q&A seed failed', {
      status: result.status,
      stderr: result.stderr.trim(),
      stdout: result.stdout.trim(),
    });
  }

  let payload = null;
  try {
    payload = JSON.parse(result.stdout.trim());
  } catch {
    fail('local smoke Q&A seed returned invalid JSON', {
      stdout: result.stdout.trim(),
      stderr: result.stderr.trim(),
    });
  }

  if (!payload?.success || !payload.id) {
    fail('local smoke Q&A seed did not return an id', payload);
  }

  adminSmokeQaId = String(payload.id);
}

function sameUrlWithoutTrailingSlash(actual, expected) {
  return trimTrailingSlash(actual) === trimTrailingSlash(expected);
}

function sameUrlAllowingQueryStripping(actual, expected) {
  if (sameUrlWithoutTrailingSlash(actual, expected)) return true;

  try {
    const actualUrl = new URL(actual);
    const expectedUrl = new URL(expected);
    return (
      actualUrl.origin === expectedUrl.origin &&
      trimTrailingSlash(actualUrl.pathname) === trimTrailingSlash(expectedUrl.pathname) &&
      !actualUrl.search &&
      Boolean(expectedUrl.search)
    );
  } catch {
    return false;
  }
}

function unique(values) {
  return Array.from(new Set(values));
}

function isIgnorableFailedRequest(request, check) {
  if (isExternalContentAssetFailure(request)) {
    return true;
  }

  if (!request.errorText.includes('ERR_ABORTED')) {
    return false;
  }

  if (
    request.method === 'GET' &&
    request.resourceType === 'script' &&
    request.url.startsWith(`${appUrl}/_next/static/webpack/`) &&
    request.url.includes('.hot-update.js')
  ) {
    return true;
  }

  if (check.expectedFinalPath) {
    return true;
  }

  if (request.method !== 'GET' || !request.url.startsWith(`${appUrl}/`)) {
    return false;
  }

  try {
    const url = new URL(request.url);
    return url.searchParams.has('_rsc') && url.pathname.endsWith('.txt');
  } catch {
    return false;
  }
}

function isExternalContentAssetFailure(request) {
  if (request.method !== 'GET') {
    return false;
  }

  try {
    const requestUrl = new URL(request.url);
    const appOrigin = new URL(appUrl).origin;
    const apiOrigin = new URL(expectedApiUrl).origin;

    if (requestUrl.origin === appOrigin || requestUrl.origin === apiOrigin) {
      return false;
    }

    if (['image', 'media', 'font'].includes(request.resourceType || '')) {
      return true;
    }

    return /\.(?:avif|gif|ico|jpe?g|png|svg|webp|woff2?|ttf|otf)$/i.test(requestUrl.pathname);
  } catch {
    return false;
  }
}

function isAllowedBadResponse(value, check) {
  return (check.allowedBadResponses || []).some((allowed) => value.includes(allowed));
}

function isIgnorableConsoleError(value, check, badResponses, failedRequests) {
  if (!String(value).includes('Failed to load resource')) {
    return false;
  }

  const actionableBadResponses = badResponses.filter((item) => !isAllowedBadResponse(item, check));
  const actionableFailedRequests = failedRequests.filter(
    (request) => !isIgnorableFailedRequest(request, check)
  );

  return (
    (badResponses.length > 0 && actionableBadResponses.length === 0) ||
    (failedRequests.length > 0 && actionableFailedRequests.length === 0)
  );
}

function browserRuntimeProblems(result) {
  const { check, consoleErrors, pageErrors, failedRequests, badResponses } = result;
  const actionableFailedRequests = failedRequests.filter(
    (request) => !isIgnorableFailedRequest(request, check)
  );
  const actionableBadResponses = badResponses.filter(
    (response) => !isAllowedBadResponse(response, check)
  );
  const actionableConsoleErrors = consoleErrors.filter(
    (error) => !isIgnorableConsoleError(error, check, badResponses, failedRequests)
  );

  return {
    consoleErrors: actionableConsoleErrors,
    pageErrors,
    failedRequests: actionableFailedRequests,
    badResponses: actionableBadResponses,
  };
}

function isRetryableHydrationResult(result) {
  const problems = browserRuntimeProblems(result);
  const messages = [...problems.pageErrors, ...problems.consoleErrors].join('\n');
  return /Hydration failed|Minified React error #(418|423|425)/i.test(messages);
}

async function inspectPage(page, check) {
  const path = normalizePath(check.path);
  const url = `${appUrl}${path === '/' ? '/' : path}`;
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  const badResponses = [];
  const apiUrls = [];

  page.removeAllListeners();
  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push(message.text());
    }
  });
  page.on('pageerror', (error) => {
    pageErrors.push(error.message);
  });
  page.on('requestfailed', (request) => {
    const requestUrl = request.url();
    if (requestUrl.includes('/api/')) {
      apiUrls.push(requestUrl);
    }
    failedRequests.push({
      method: request.method(),
      url: requestUrl,
      errorText: request.failure()?.errorText || '',
      resourceType: request.resourceType(),
    });
  });
  page.on('response', (response) => {
    const responseUrl = response.url();
    if (responseUrl.includes('/api/')) {
      apiUrls.push(responseUrl);
    }
    if (response.status() >= 400 && !responseUrl.includes('favicon.ico')) {
      badResponses.push(`${response.status()} ${responseUrl}`);
    }
  });

  const response = await page.goto(url, { waitUntil: 'networkidle', timeout: 30000 });
  if (check.expectedFinalPath) {
    const expectedFinalUrl = new URL(normalizePath(check.expectedFinalPath), appUrl);
    try {
      await page.waitForURL(
        (currentUrl) =>
          currentUrl.origin === expectedFinalUrl.origin &&
          currentUrl.pathname === expectedFinalUrl.pathname &&
          (!expectedFinalUrl.search || currentUrl.search === expectedFinalUrl.search),
        { timeout: 10000 }
      );
    } catch (error) {
      fail(`${check.label} did not reach its expected final URL`, {
        expectedFinalUrl: expectedFinalUrl.toString(),
        actualFinalUrl: page.url(),
        reason: error instanceof Error ? error.message : String(error),
      });
    }
    await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => undefined);
  }
  await page.waitForTimeout(800);

  const expectedSelectors = check.expectedSelectors || [];
  const actual = await page.evaluate((selectors) => {
    const anchors = Array.from(document.querySelectorAll('a[href]')).map(
      (anchor) => anchor.getAttribute('href') || ''
    );
    const headerHrefs = Array.from(document.querySelectorAll('header.g5-default-header a[href]')).map(
      (anchor) => anchor.getAttribute('href') || ''
    );

    function normalizeText(value) {
      return String(value || '')
        .replace(/\s+/g, ' ')
        .trim();
    }

    function isElementVisible(element) {
      if (!(element instanceof HTMLElement || element instanceof SVGElement)) {
        return false;
      }

      if (element.closest('[hidden], [aria-hidden="true"]')) {
        return false;
      }

      const style = window.getComputedStyle(element);
      if (style.display === 'none' || style.visibility === 'hidden') {
        return false;
      }

      return element.getClientRects().length > 0;
    }

    function describeElement(element) {
      const tag = element.tagName.toLowerCase();
      const id = element.id ? `#${element.id}` : '';
      const classes = Array.from(element.classList || [])
        .slice(0, 3)
        .map((className) => `.${className}`)
        .join('');
      const text = normalizeText(element.textContent).slice(0, 60);
      return `${tag}${id}${classes}${text ? ` "${text}"` : ''}`;
    }

    function referencedText(element, attr) {
      return normalizeText(
        (element.getAttribute(attr) || '')
          .split(/\s+/)
          .map((id) => document.getElementById(id)?.textContent || '')
          .join(' ')
      );
    }

    function labelText(element) {
      const labels = 'labels' in element ? Array.from(element.labels || []) : [];
      return normalizeText(labels.map((label) => label.textContent || '').join(' '));
    }

    function accessibleName(element) {
      const ariaLabel = normalizeText(element.getAttribute('aria-label'));
      if (ariaLabel) return ariaLabel;

      const labelledBy = referencedText(element, 'aria-labelledby');
      if (labelledBy) return labelledBy;

      const label = labelText(element);
      if (label) return label;

      const title = normalizeText(element.getAttribute('title'));
      if (title) return title;

      if (element instanceof HTMLInputElement) {
        const type = element.type.toLowerCase();
        if (['button', 'submit', 'reset'].includes(type)) {
          const value = normalizeText(element.value);
          if (value) return value;
        }
        const placeholder = normalizeText(element.placeholder);
        if (placeholder) return placeholder;
      }

      const descendantImageAlt = normalizeText(
        Array.from(element.querySelectorAll('img[alt]'))
          .map((image) => image.getAttribute('alt') || '')
          .join(' ')
      );
      if (descendantImageAlt) return descendantImageAlt;

      const svgTitle = normalizeText(
        Array.from(element.querySelectorAll('svg title'))
          .map((titleElement) => titleElement.textContent || '')
          .join(' ')
      );
      if (svgTitle) return svgTitle;

      return normalizeText(element.textContent);
    }

    function inspectAccessibility() {
      const controls = Array.from(
        document.querySelectorAll(
          [
            'button',
            'a[href]',
            'input:not([type="hidden"])',
            'select',
            'textarea',
            '[role="button"]',
            '[role="link"]',
            '[role="menuitem"]',
            '[role="tab"]',
            '[role="checkbox"]',
            '[role="radio"]',
            '[role="switch"]',
            '[role="combobox"]',
          ].join(',')
        )
      );

      return {
        mainContentCount: document.querySelectorAll('main#main-content').length,
        skipLinkCount: document.querySelectorAll('a[href="#main-content"]').length,
        missingImageAlts: Array.from(document.querySelectorAll('img:not([alt])'))
          .filter(isElementVisible)
          .map(describeElement)
          .slice(0, 20),
        unnamedControls: controls
          .filter((element) => isElementVisible(element))
          .filter((element) => !accessibleName(element))
          .map(describeElement)
          .slice(0, 20),
      };
    }

    function inspectLayout() {
      const doc = document.documentElement;
      const body = document.body;
      const viewportWidth = Math.round(window.visualViewport?.width || doc.clientWidth || window.innerWidth);
      const scrollWidth = Math.max(doc.scrollWidth || 0, body?.scrollWidth || 0);
      const fixedElements = new WeakSet();

      function isInsideFixedElement(element) {
        for (let current = element; current && current !== body; current = current.parentElement) {
          if (fixedElements.has(current)) {
            return true;
          }
          const isFixed = getComputedStyle(current).position === 'fixed';
          if (isFixed) {
            fixedElements.add(current);
            return true;
          }
        }
        return false;
      }

      function isInsideHorizontalOverflowContainer(element) {
        const containedOverflowValues = new Set(['auto', 'scroll', 'hidden', 'clip']);
        for (
          let current = element.parentElement;
          current && current !== body;
          current = current.parentElement
        ) {
          const style = getComputedStyle(current);
          if (!containedOverflowValues.has(style.overflowX)) {
            continue;
          }

          const rect = current.getBoundingClientRect();
          if (rect.left >= -1 && rect.right <= viewportWidth + 1) {
            return true;
          }
        }
        return false;
      }

      const offenders = Array.from(document.querySelectorAll('body *'))
        .filter((element) => !isInsideFixedElement(element))
        .filter((element) => !isInsideHorizontalOverflowContainer(element))
        .map((element) => {
          const rect = element.getBoundingClientRect();
          return { element, rect };
        })
        .filter(({ element, rect }) => {
          if (rect.width <= 0 || rect.height <= 0) {
            return false;
          }
          if (!isElementVisible(element)) {
            return false;
          }
          return rect.left < -1 || rect.right > viewportWidth + 1;
        })
        .map(({ element, rect }) => ({
          element: describeElement(element),
          left: Math.round(rect.left),
          right: Math.round(rect.right),
          width: Math.round(rect.width),
          overflow: Math.ceil(Math.max(0, rect.right - viewportWidth, -rect.left)),
        }))
        .sort((a, b) => b.overflow - a.overflow)
        .slice(0, 10);
      const contentOverflow = offenders.reduce(
        (maxOverflow, offender) => Math.max(maxOverflow, offender.overflow),
        0
      );

      return {
        viewportWidth,
        scrollWidth,
        documentHorizontalOverflow: Math.max(0, scrollWidth - viewportWidth),
        horizontalOverflow: contentOverflow,
        offenders,
      };
    }

    return {
      title: document.title,
      h1: document.querySelector('h1')?.textContent?.trim() || '',
      canonical: document.querySelector('link[rel="canonical"]')?.getAttribute('href') || '',
      ogUrl: document.querySelector('meta[property="og:url"]')?.getAttribute('content') || '',
      jsonLdTypes: Array.from(document.querySelectorAll('script[type="application/ld+json"]'))
        .flatMap((script) => {
          try {
            const payload = JSON.parse(script.textContent || '{}');
            const entries = Array.isArray(payload) ? payload : [payload];
            return entries.flatMap((entry) => entry?.['@type'] || []);
          } catch {
            return [];
          }
        }),
      runtimeConfig: window.__G5_NEXTJS25_CONFIG__ || null,
      headerHrefs,
      selectorMatches: selectors.map((selector) => ({
        selector,
        count: document.querySelectorAll(selector).length,
      })),
      longLinks: anchors
        .filter((href) =>
          /\/boards\/|\/shop\/products\/|\/shop\/categories\/|\/shop\/products\?[^#]*it_type[1-5]=1/.test(
            href
          )
        )
        .slice(0, 20),
      accessibility: inspectAccessibility(),
      layout: inspectLayout(),
    };
  }, expectedSelectors);

  return {
    check,
    status: response?.status() || 0,
    finalUrl: page.url(),
    apiUrls: unique(apiUrls),
    consoleErrors,
    pageErrors,
    failedRequests,
    badResponses,
    actual,
    viewport: activeViewport.name,
  };
}

function assertPage(result) {
  const { check, status, apiUrls, actual } = result;
  const path = normalizePath(check.path);
  const expectedPath = check.expectedFinalPath ? normalizePath(check.expectedFinalPath) : path;
  const expectedUrl = `${appUrl}${expectedPath === '/' ? '' : expectedPath}`;
  const sameSeoUrl = check.allowSeoQueryStripping
    ? sameUrlAllowingQueryStripping
    : sameUrlWithoutTrailingSlash;

  if (status !== 200) {
    fail(`${check.label} returned HTTP ${status}`, result);
  }

  if (check.expectedTitleIncludes && !actual.title.includes(check.expectedTitleIncludes)) {
    fail(`${check.label} title does not include ${check.expectedTitleIncludes}`, {
      actual: actual.title,
      expectedTitleIncludes: check.expectedTitleIncludes,
    });
  }

  if (check.expectedH1 && actual.h1 !== check.expectedH1) {
    fail(`${check.label} h1 mismatch`, {
      actual: actual.h1,
      expected: check.expectedH1,
    });
  }

  for (const type of check.expectedJsonLdTypes || []) {
    if (!actual.jsonLdTypes.includes(type)) {
      fail(`${check.label} missing JSON-LD type ${type}`, {
        actual: actual.jsonLdTypes,
        expected: check.expectedJsonLdTypes,
      });
    }
  }

  for (const match of actual.selectorMatches || []) {
    if (match.count < 1) {
      fail(`${check.label} missing expected selector ${match.selector}`, {
        selectorMatches: actual.selectorMatches,
        finalUrl: result.finalUrl,
      });
    }
  }

  for (const part of check.forbiddenFinalPathParts || []) {
    if (result.finalUrl.includes(part)) {
      fail(`${check.label} navigated to forbidden final URL`, {
        finalUrl: result.finalUrl,
        forbidden: part,
      });
    }
  }

  if (actual.accessibility?.mainContentCount !== 1) {
    fail(`${check.label} must render one main#main-content landmark`, {
      accessibility: actual.accessibility,
      finalUrl: result.finalUrl,
    });
  }

  if ((actual.accessibility?.skipLinkCount || 0) < 1) {
    fail(`${check.label} must render a skip link to #main-content`, {
      accessibility: actual.accessibility,
      finalUrl: result.finalUrl,
    });
  }

  if ((actual.accessibility?.missingImageAlts || []).length > 0) {
    fail(`${check.label} has images without alt attributes`, {
      missingImageAlts: actual.accessibility.missingImageAlts,
      finalUrl: result.finalUrl,
    });
  }

  if ((actual.accessibility?.unnamedControls || []).length > 0) {
    fail(`${check.label} has interactive elements without accessible names`, {
      unnamedControls: actual.accessibility.unnamedControls,
      finalUrl: result.finalUrl,
    });
  }

  if (result.viewport === 'mobile' && (actual.layout?.horizontalOverflow || 0) > 1) {
    fail(`${check.label} has page-level horizontal overflow on mobile`, {
      layout: actual.layout,
      finalUrl: result.finalUrl,
    });
  }

  const runtimeApi = trimTrailingSlash(actual.runtimeConfig?.apiBaseUrl || '');
  const resolvedRuntimeApi = runtimeApi
    ? trimTrailingSlash(new URL(runtimeApi, appUrl).toString())
    : '';
  if (resolvedRuntimeApi !== expectedApiUrl) {
    fail(`${check.label} runtime apiBaseUrl is ${runtimeApi || '(empty)'}`, {
      ...result,
      resolvedRuntimeApi,
    });
  }

  const unexpectedApiUrls = apiUrls.filter((url) => !url.startsWith(`${expectedApiUrl}/`));
  if (unexpectedApiUrls.length > 0) {
    fail(`${check.label} used unexpected API origin`, { unexpectedApiUrls, expectedApiUrl });
  }

  for (const part of check.expectedApiParts || []) {
    const calledFromBrowser = apiUrls.some((url) => url.includes(part));
    // Authenticated layouts resolve /auth/me on the Next server from the
    // g5_token cookie, so that request is intentionally outside the browser
    // network log. A successful protected page response confirms that path.
    const resolvedDuringServerRender =
      part === '/auth/me' &&
      (check.forbiddenFinalPathParts || []).includes('/login') &&
      !result.finalUrl.includes('/login');
    if (!calledFromBrowser && !resolvedDuringServerRender) {
      fail(`${check.label} did not call expected API path ${part}`, result);
    }
  }

  for (const part of check.forbiddenApiParts || []) {
    if (apiUrls.some((url) => url.includes(part))) {
      fail(`${check.label} called forbidden API path ${part}`, result);
    }
  }

  if (
    !check.skipSeoUrlCheck &&
    path !== '/' &&
    actual.canonical &&
    !sameSeoUrl(actual.canonical, expectedUrl)
  ) {
    fail(`${check.label} canonical mismatch`, {
      actual: actual.canonical,
      expected: expectedUrl,
    });
  }

  if (
    !check.skipSeoUrlCheck &&
    path !== '/' &&
    actual.ogUrl &&
    !sameSeoUrl(actual.ogUrl, expectedUrl)
  ) {
    fail(`${check.label} og:url mismatch`, {
      actual: actual.ogUrl,
      expected: expectedUrl,
    });
  }

  if (check.checkShortLinks !== false && actual.longLinks.length > 0) {
    fail(`${check.label} still has long internal links`, actual.longLinks);
  }

  for (const href of check.expectedHeaderHrefs || []) {
    if (!actual.headerHrefs.includes(href)) {
      fail(`${check.label} missing expected header href ${href}`, {
        expected: check.expectedHeaderHrefs,
        actual: actual.headerHrefs,
      });
    }
  }

  for (const part of check.forbiddenHeaderHrefParts || []) {
    const matched = actual.headerHrefs.filter((href) => href.includes(part));
    if (matched.length > 0) {
      fail(`${check.label} has forbidden header href ${part}`, {
        forbidden: part,
        matched,
        actual: actual.headerHrefs,
      });
    }
  }

  const runtimeProblems = browserRuntimeProblems(result);

  if (
    runtimeProblems.consoleErrors.length > 0 ||
    runtimeProblems.pageErrors.length > 0 ||
    runtimeProblems.failedRequests.length > 0 ||
    runtimeProblems.badResponses.length > 0
  ) {
    fail(`${check.label} has browser/runtime errors`, {
      ...runtimeProblems,
    });
  }
}

async function runChecks(browser, checks, options = {}) {
  let context = null;

  async function openContext() {
    const nextContext = await browser.newContext({
      viewport: activeViewport.viewport,
      isMobile: activeViewport.isMobile,
      hasTouch: activeViewport.hasTouch,
      serviceWorkers: 'block',
    });
    await nextContext.setExtraHTTPHeaders({ 'Cache-Control': 'no-cache', Pragma: 'no-cache' });

    if (options.authenticated) {
      const didAuthenticate = await authenticateContext(nextContext, options.credentials);
      if (!didAuthenticate) {
        await nextContext.close();
        return null;
      }
    }

    return nextContext;
  }

  try {
    context = await openContext();
    if (!context) {
      return {
        results: [],
        skipped: true,
      };
    }

    let page = await context.newPage();
    const results = [];
    for (const check of checks) {
      let result = await inspectPage(page, check);
      for (
        let attempt = 1;
        attempt <= browserRuntimeRetries && isRetryableHydrationResult(result);
        attempt += 1
      ) {
        console.warn(
          `[check-local-browser] retrying ${check.label} after hydration runtime error (${attempt}/${browserRuntimeRetries})`
        );
        await context.close();
        context = await openContext();
        if (!context) {
          return {
            results: [],
            skipped: true,
          };
        }
        page = await context.newPage();
        result = await inspectPage(page, check);
      }
      assertPage(result);
      results.push({
        label: check.label,
        path: check.path,
        viewport: result.viewport,
        status: result.status,
        apiCalls: result.apiUrls.length,
        title: result.actual.title,
      });
    }

    return { results, skipped: false };
  } finally {
    await context?.close();
  }
}

const browser = await chromium.launch({ headless: true });

try {
  const results = [];
  const guest = await runChecks(browser, filterSkippedChecks(smokePaths));
  results.push(...guest.results);

  const authenticated = await runChecks(
    browser,
    filterSkippedChecks(authSmokePaths).map((check) => ({ ...check, skipSeoUrlCheck: true })),
    {
      authenticated: true,
      credentials: {
        id: authId,
        password: authPassword,
        label: 'authenticated',
        idEnv: 'LOCAL_SMOKE_LOGIN_ID',
        passwordEnv: 'LOCAL_SMOKE_LOGIN_PASSWORD',
      },
    }
  );
  if (authenticated.skipped) {
    if (requireAuth) {
      fail(
        'authenticated checks require LOCAL_SMOKE_LOGIN_ID and LOCAL_SMOKE_LOGIN_PASSWORD'
      );
    }
    console.log(
      '[check-local-browser] authenticated checks skipped (set LOCAL_SMOKE_LOGIN_ID and LOCAL_SMOKE_LOGIN_PASSWORD)'
    );
  } else {
    results.push(...authenticated.results);
  }

  const adminAuthenticated = await runChecks(
    browser,
    filterSkippedChecks(adminAuthSmokePaths).map((check) => ({ ...check, skipSeoUrlCheck: true })),
    {
      authenticated: true,
      credentials: {
        id: adminAuthId,
        password: adminAuthPassword,
        label: 'admin authenticated',
        idEnv: 'LOCAL_SMOKE_ADMIN_LOGIN_ID',
        passwordEnv: 'LOCAL_SMOKE_ADMIN_LOGIN_PASSWORD',
      },
    }
  );
  if (adminAuthenticated.skipped) {
    if (requireAdminAuth) {
      fail(
        'admin authenticated checks require LOCAL_SMOKE_ADMIN_LOGIN_ID and LOCAL_SMOKE_ADMIN_LOGIN_PASSWORD'
      );
    }
    console.log(
      '[check-local-browser] admin authenticated checks skipped (set LOCAL_SMOKE_ADMIN_LOGIN_ID and LOCAL_SMOKE_ADMIN_LOGIN_PASSWORD)'
    );
  } else {
    results.push(...adminAuthenticated.results);
  }

  console.table(results);
  console.log(`[check-local-browser] app=${appUrl}`);
  console.log(`[check-local-browser] api=${expectedApiUrl}`);
  console.log(
    `[check-local-browser] viewport=${activeViewport.name} ${activeViewport.viewport.width}x${activeViewport.viewport.height}`
  );
} finally {
  await browser.close();
}
