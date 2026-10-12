const appUrl = trimTrailingSlash(process.env.LIVE_APP_URL || 'https://nextjs.thisgun.net');
const apiUrl = trimTrailingSlash(process.env.LIVE_EXPECTED_API_URL || `${appUrl}/api/v1`);
const adminId = process.env.LIVE_SMOKE_ADMIN_LOGIN_ID || '';
const adminPassword = process.env.LIVE_SMOKE_ADMIN_LOGIN_PASSWORD || '';
const seedEnabled = process.env.LIVE_SMOKE_YOUNGCART_SEED === '1';
const smokeProductId = process.env.LIVE_SMOKE_SHOP_PRODUCT_ID || '1446772772';
const smokeCategoryId = process.env.LIVE_SMOKE_SHOP_CATEGORY_ID || '2010101010';
const smokeCategoryName =
  process.env.LIVE_SMOKE_SHOP_CATEGORY_NAME || 'Next.js YoungCart smoke category';
const smokeProductName =
  process.env.LIVE_SMOKE_SHOP_PRODUCT_NAME || 'Next.js YoungCart smoke product';
const smokeProductPrice = positiveInt(process.env.LIVE_SMOKE_SHOP_PRODUCT_PRICE, 12345);
const smokeProductStock = positiveInt(process.env.LIVE_SMOKE_SHOP_PRODUCT_STOCK, 100);
const checks = [];
const cookieJar = new Map();

function trimTrailingSlash(value) {
  return String(value || '').replace(/\/+$/, '');
}

function positiveInt(value, fallback) {
  const number = Number.parseInt(String(value || ''), 10);
  return Number.isFinite(number) && number > 0 ? number : fallback;
}

function appAbsoluteUrl(path) {
  return `${appUrl}${path.startsWith('/') ? path : `/${path}`}`;
}

function apiAbsoluteUrl(path) {
  return `${apiUrl}${path.startsWith('/') ? path : `/${path}`}`;
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

function setCookieHeaders(headers) {
  if (typeof headers.getSetCookie === 'function') {
    return headers.getSetCookie();
  }

  const value = headers.get('set-cookie');
  return value ? [value] : [];
}

function rememberCookies(headers) {
  for (const cookie of setCookieHeaders(headers)) {
    const pair = String(cookie).split(';', 1)[0] || '';
    const index = pair.indexOf('=');
    if (index <= 0) continue;

    const name = pair.slice(0, index).trim();
    const value = pair.slice(index + 1);
    if (value === '') {
      cookieJar.delete(name);
    } else {
      cookieJar.set(name, value);
    }
  }
}

function cookieHeader() {
  return Array.from(cookieJar.entries())
    .map(([name, value]) => `${name}=${value}`)
    .join('; ');
}

async function fetchJson(path, options = {}) {
  const headers = {
    Accept: 'application/json',
    ...(options.body ? { 'Content-Type': 'application/json' } : {}),
    ...(options.cookieJar ? { Cookie: cookieHeader() } : {}),
    ...(options.headers || {}),
  };

  const response = await fetch(apiAbsoluteUrl(path), {
    method: options.method || 'GET',
    headers,
    body: options.body,
    redirect: 'manual',
  });
  if (options.cookieJar) {
    rememberCookies(response.headers);
  }

  let payload = null;
  const text = await response.text();
  try {
    payload = text ? JSON.parse(text) : null;
  } catch {
    payload = null;
  }

  return { response, payload, text };
}

async function apiJson(path, options = {}) {
  const { response, payload, text } = await fetchJson(path, options);
  if (!response.ok || !payload?.success) {
    throw new Error(
      `API request failed: ${path} HTTP ${response.status} ${
        payload?.message || text.slice(0, 120)
      }`
    );
  }
  return payload;
}

async function fetchPage(path) {
  const response = await fetch(appAbsoluteUrl(path), { redirect: 'follow' });
  const text = await response.text();
  return { response, text };
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

async function adminLogin() {
  if (!adminId || !adminPassword) {
    return '';
  }

  const payload = await apiJson('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ mb_id: adminId, mb_password: adminPassword }),
  });
  return payload.data?.token || '';
}

function adminHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

async function ensureLiveSmokeCategory(token, categoryId) {
  const prefixes = [];
  for (let length = 2; length <= categoryId.length; length += 2) {
    prefixes.push(categoryId.slice(0, length));
  }

  for (const [index, id] of prefixes.entries()) {
    const existing = await fetchJson(`/admin/shop/categories/${encodeURIComponent(id)}`, {
      headers: adminHeaders(token),
    });
    if (existing.response.ok && existing.payload?.success) {
      continue;
    }
    if (existing.response.status !== 404) {
      throw new Error(`Failed to inspect category ${id}: HTTP ${existing.response.status}`);
    }

    await apiJson('/shop/admin/categories', {
      method: 'POST',
      headers: adminHeaders(token),
      body: JSON.stringify({
        ca_id: id,
        ca_name: `${smokeCategoryName} ${id}`,
        ca_order: 900 + index,
        ca_use: 1,
      }),
    });
  }
}

async function ensureLiveSmokeProduct(token) {
  const detail = await fetchJson(`/shop/products/${encodeURIComponent(smokeProductId)}`);
  if (detail.response.ok && detail.payload?.success) {
    const product = detail.payload.data || {};
    if (
      String(product.it_id) === smokeProductId &&
      String(product.it_soldout) !== '1' &&
      Number(product.it_stock_qty || 0) > 0
    ) {
      return product;
    }
  }

  const adminProduct = await fetchJson(
    `/admin/shop/products/${encodeURIComponent(smokeProductId)}`,
    { headers: adminHeaders(token) }
  );

  if (adminProduct.response.ok && adminProduct.payload?.success) {
    const product = adminProduct.payload.data || {};
    const isSmokeProduct = String(product.it_name || '').includes('Next.js YoungCart smoke');
    if (!isSmokeProduct && process.env.LIVE_SMOKE_YOUNGCART_FORCE_PATCH !== '1') {
      throw new Error(
        `Product ${smokeProductId} exists but is not a smoke product; refusing to patch it`
      );
    }

    await apiJson(`/shop/admin/products/${encodeURIComponent(smokeProductId)}`, {
      method: 'PATCH',
      headers: adminHeaders(token),
      body: JSON.stringify({
        ca_id: smokeCategoryId,
        it_name: smokeProductName,
        it_basic: 'Live YoungCart compatibility smoke product.',
        it_explan: 'Live YoungCart compatibility smoke product.',
        it_price: smokeProductPrice,
        it_stock_qty: smokeProductStock,
        it_soldout: 0,
        it_use: 1,
        it_type1: 1,
      }),
    });
  } else if (adminProduct.response.status === 404) {
    await apiJson('/shop/admin/products', {
      method: 'POST',
      headers: adminHeaders(token),
      body: JSON.stringify({
        it_id: smokeProductId,
        ca_id: smokeCategoryId,
        it_name: smokeProductName,
        it_basic: 'Live YoungCart compatibility smoke product.',
        it_price: smokeProductPrice,
        it_stock_qty: smokeProductStock,
        it_use: 1,
        it_soldout: 0,
        it_type1: 1,
      }),
    });
  } else {
    throw new Error(`Failed to inspect product ${smokeProductId}: HTTP ${adminProduct.response.status}`);
  }

  return (await apiJson(`/shop/products/${encodeURIComponent(smokeProductId)}`)).data;
}

async function prepareSmokeData() {
  const productDetail = await fetchJson(`/shop/products/${encodeURIComponent(smokeProductId)}`);
  if (productDetail.response.ok && productDetail.payload?.success) {
    return productDetail.payload.data;
  }

  if (!seedEnabled) {
    record(
      'youngcart data',
      'smoke product available',
      false,
      `HTTP ${productDetail.response.status}`,
      'create or migrate at least one live YoungCart product, or run with LIVE_SMOKE_YOUNGCART_SEED=1 and LIVE_SMOKE_ADMIN_LOGIN_ID/PASSWORD'
    );
    return null;
  }

  const token = await adminLogin();
  if (!token) {
    record(
      'youngcart data',
      'admin seed login',
      false,
      'missing admin token',
      'set LIVE_SMOKE_ADMIN_LOGIN_ID and LIVE_SMOKE_ADMIN_LOGIN_PASSWORD when LIVE_SMOKE_YOUNGCART_SEED=1'
    );
    return null;
  }

  await ensureLiveSmokeCategory(token, smokeCategoryId);
  const product = await ensureLiveSmokeProduct(token);
  record(
    'youngcart data',
    'seed smoke catalog',
    Boolean(product?.it_id),
    product?.it_id ? `product=${product.it_id} category=${product.ca_id}` : 'missing product',
    'shop/admin category and product seed must create a public product'
  );
  return product;
}

async function checkPublicPages(product) {
  const pagePaths = [
    '/shop/',
    `/shop/${encodeURIComponent(product.it_id)}`,
    `/shop/list-${encodeURIComponent(product.ca_id || smokeCategoryId)}`,
    '/shop/cart',
    '/shop/order',
    '/shop/orders',
    '/shop/couponzone',
    '/shop/reviews',
    '/shop/qas',
    `/shop/search?q=${encodeURIComponent(product.it_name || product.it_id)}`,
  ];

  for (const path of pagePaths) {
    const { response, text } = await fetchPage(path);
    const contentType = header(response.headers, 'content-type');
    record(
      'youngcart page',
      `${path} html shell`,
      response.ok && contentType.includes('text/html') && isNextStaticShellResponse(response.headers, text),
      `HTTP ${response.status} content-type=${contentType || '(missing)'}`,
      `${path} must render through the Next.js YoungCart shell`
    );
  }
}

async function checkCatalogApi(product) {
  const list = await apiJson('/shop/products?per_page=8');
  const items = Array.isArray(list.data) ? list.data : [];
  record(
    'youngcart api',
    'product list has items',
    items.length > 0,
    `items=${items.length}`,
    'live YoungCart catalog must not be empty'
  );
  record(
    'youngcart api',
    'smoke product detail',
    String(product?.it_id || '') === smokeProductId &&
      String(product?.it_soldout || '0') !== '1' &&
      Number(product?.it_stock_qty || 0) > 0,
    `product=${product?.it_id || '(missing)'} stock=${product?.it_stock_qty ?? '(missing)'}`,
    'smoke product must be public, in stock, and not sold out'
  );

  const policy = await apiJson('/shop/policy');
  record(
    'youngcart api',
    'shop policy',
    Array.isArray(policy.data?.shipping_rules) &&
      Number.isFinite(Number(policy.data?.base_shipping_cost)),
    `rules=${policy.data?.shipping_rules?.length ?? 0} base=${policy.data?.base_shipping_cost ?? '(missing)'}`,
    'shop policy must expose YoungCart shipping configuration'
  );

  const categories = await apiJson('/shop/categories');
  record(
    'youngcart api',
    'category list',
    Array.isArray(categories.data),
    `categories=${Array.isArray(categories.data) ? categories.data.length : '(not array)'}`,
    'shop categories endpoint must return a list'
  );

  for (const endpoint of [
    `/shop/reviews?it_id=${encodeURIComponent(product.it_id)}`,
    `/shop/reviews/qna?it_id=${encodeURIComponent(product.it_id)}`,
  ]) {
    const payload = await apiJson(endpoint);
    record(
      'youngcart api',
      endpoint,
      Array.isArray(payload.data),
      `items=${Array.isArray(payload.data) ? payload.data.length : '(not array)'}`,
      `${endpoint} must return a YoungCart-compatible list`
    );
  }
}

async function checkGuestCartFlow(product) {
  const before = await apiJson('/shop/cart', { cookieJar: true });
  record(
    'youngcart cart',
    'guest cart readable',
    Array.isArray(before.data?.items),
    `items=${before.data?.items?.length ?? '(missing)'}`,
    'guest cart must be readable without login'
  );

  const added = await apiJson('/shop/cart', {
    method: 'POST',
    cookieJar: true,
    body: JSON.stringify({
      it_id: product.it_id,
      ct_qty: 1,
    }),
  });
  const createdIds = [
    added.data?.ct_id,
    ...((added.data?.items || []).map((item) => item.ct_id)),
  ]
    .filter((id) => id !== undefined && id !== null && String(id) !== '')
    .map(String);

  record(
    'youngcart cart',
    'guest cart add',
    createdIds.length > 0,
    `ct_ids=${createdIds.join(',') || '(missing)'}`,
    'guest cart add must create at least one cart row'
  );

  const cart = await apiJson('/shop/cart', { cookieJar: true });
  const rows = cart.data?.items || [];
  record(
    'youngcart cart',
    'guest cart persists',
    rows.some((item) => String(item.it_id) === String(product.it_id)),
    `items=${rows.length}`,
    'guest cart must persist through the PHP session cookie'
  );

  const quote = await fetchJson('/shop/shipping/quote', { cookieJar: true });
  record(
    'youngcart cart',
    'guest shipping quote',
    quote.response.ok && quote.payload?.success !== false,
    `HTTP ${quote.response.status}`,
    'shipping quote must work for a guest cart with items'
  );

  await fetchJson('/shop/cart', {
    method: 'DELETE',
    cookieJar: true,
  });

  const afterCleanup = await apiJson('/shop/cart', { cookieJar: true });
  record(
    'youngcart cart',
    'guest cart cleanup',
    (afterCleanup.data?.items || []).length === 0,
    `items=${afterCleanup.data?.items?.length ?? '(missing)'}`,
    'guest cart cleanup must leave the smoke session cart empty'
  );
}

try {
  const product = await prepareSmokeData();
  if (product) {
    await checkCatalogApi(product);
    await checkGuestCartFlow(product);
    await checkPublicPages(product);
  }
} catch (error) {
  record('youngcart core', 'unexpected error', false, error.message);
}

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
  console.error(`[check-live-youngcart-core-flow] ${failures.length} issue(s) found for ${appUrl}`);
  for (const failure of failures) {
    console.error(`- [${failure.area}] ${failure.name}: ${failure.detail}`);
    if (failure.hint) {
      console.error(`  hint: ${failure.hint}`);
    }
  }
  process.exit(1);
}

console.log(
  `[check-live-youngcart-core-flow] live YoungCart catalog/cart/page flow passed for ${appUrl}`
);
