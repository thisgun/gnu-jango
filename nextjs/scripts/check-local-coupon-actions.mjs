import { chromium } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const appUrl = trimTrailingSlash(process.env.LOCAL_APP_URL || 'http://127.0.0.20');
const expectedApiUrl = trimTrailingSlash(
  process.env.LOCAL_EXPECTED_API_URL || 'http://127.0.0.9/api/v1'
);

const smokeMemberId = process.env.LOCAL_SMOKE_COUPON_LOGIN_ID || 'nextjs_coupon_smoke';
const smokeMemberPassword =
  process.env.LOCAL_SMOKE_COUPON_LOGIN_PASSWORD || 'NextjsCouponSmoke123!';
const smokeProductId = process.env.LOCAL_SMOKE_SHOP_PRODUCT_ID || '1446772772';
const couponSubject = process.env.LOCAL_SMOKE_COUPON_SUBJECT || 'nextjs-local-coupon-smoke 3000';

function trimTrailingSlash(value) {
  return String(value).replace(/\/+$/, '');
}

function fail(message, details = undefined) {
  const error = new Error(message);
  error.details = details;
  throw error;
}

function printFailure(error, prefix = 'check-local-coupon-actions') {
  console.error(`[${prefix}] ${error.message}`);
  if (error.details) {
    console.error(JSON.stringify(error.details, null, 2));
  }
}

function runPhp(script, env = {}, args = []) {
  const scriptPath = fileURLToPath(new URL(`../../scripts/${script}`, import.meta.url));
  const result = spawnSync('php', [scriptPath, '--json', ...args], {
    env: {
      ...process.env,
      ...env,
    },
    encoding: 'utf8',
    windowsHide: true,
  });

  if (result.error) {
    fail(`failed to run ${script}: ${result.error.message}`);
  }

  if (result.status !== 0) {
    fail(`${script} failed`, {
      status: result.status,
      stderr: result.stderr.trim(),
      stdout: result.stdout.trim(),
    });
  }

  try {
    const payload = JSON.parse(result.stdout.trim());
    if (!payload?.success) {
      fail(`${script} did not return success`, payload);
    }
    return payload;
  } catch {
    fail(`${script} returned invalid JSON`, {
      stdout: result.stdout.trim(),
      stderr: result.stderr.trim(),
    });
  }
}

function seedSmokeMember() {
  return runPhp('seed_nextjs_smoke_user.php', {
    LOCAL_SMOKE_LOGIN_ID: smokeMemberId,
    LOCAL_SMOKE_LOGIN_PASSWORD: smokeMemberPassword,
    LOCAL_SMOKE_LOGIN_EMAIL: `${smokeMemberId}@example.test`,
    LOCAL_SMOKE_LOGIN_NAME:
      process.env.LOCAL_SMOKE_COUPON_LOGIN_NAME || 'Nextjs Coupon Smoke',
    LOCAL_SMOKE_LOGIN_NICK:
      process.env.LOCAL_SMOKE_COUPON_LOGIN_NICK || 'NextjsCouponSmoke',
  });
}

function seedCouponZone() {
  return runPhp('seed_nextjs_smoke_coupon_zone.php', {
    LOCAL_SMOKE_COUPON_SUBJECT: couponSubject,
  });
}

function cleanupCoupons(extraEnv = {}, args = []) {
  return runPhp(
    'cleanup_nextjs_smoke_coupons.php',
    {
      LOCAL_SMOKE_COUPON_LOGIN_ID: smokeMemberId,
      LOCAL_SMOKE_COUPON_SUBJECT: couponSubject,
      ...extraEnv,
    },
    args
  );
}

async function fetchApi(path, options = {}) {
  const response = await fetch(`${expectedApiUrl}${path}`, {
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });

  let payload = null;
  try {
    payload = await response.json();
  } catch {
    // no JSON body, e.g. 204
  }

  return { response, payload };
}

async function apiJson(path, options = {}) {
  const { response, payload } = await fetchApi(path, options);

  if (!response.ok || !payload?.success) {
    fail(`API request failed: ${path}`, {
      status: response.status,
      message: payload?.message || response.statusText,
      payload,
    });
  }

  return payload;
}

async function apiOk(path, options = {}) {
  const { response, payload } = await fetchApi(path, options);
  if (!response.ok || (response.status !== 204 && payload?.success === false)) {
    fail(`API request failed: ${path}`, {
      status: response.status,
      message: payload?.message || response.statusText,
      payload,
    });
  }
  return payload;
}

async function login() {
  const payload = await apiJson('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ mb_id: smokeMemberId, mb_password: smokeMemberPassword }),
  });
  const token = payload.data?.token;
  const refreshToken = payload.data?.refresh_token;
  if (!token) {
    fail('coupon smoke member login did not return a token');
  }
  return { token, refreshToken };
}

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

async function assertOkResponse(response, label) {
  if (!response.ok()) {
    let body = '';
    try {
      body = await response.text();
    } catch {
      // Body may be unavailable after navigation; status and URL still identify the failure.
    }
    fail(`${label} response failed`, {
      status: response.status(),
      url: response.url(),
      body,
    });
  }
}

async function getProduct() {
  const payload = await apiJson(`/shop/products/${encodeURIComponent(smokeProductId)}`);
  const product = payload.data;
  if (!product?.it_id) {
    fail('coupon smoke product was not returned by the API', payload);
  }
  if (String(product.it_soldout) === '1' || Number(product.it_stock_qty || 0) <= 0) {
    fail('coupon smoke product is not available for checkout', product);
  }
  return product;
}

async function setupCart(token, product) {
  await apiOk('/shop/cart', {
    method: 'DELETE',
    headers: authHeaders(token),
  });
  const option = (product.options || []).find(
    (item) =>
      Number(item.io_type) === 0 &&
      Number(item.io_use ?? 1) === 1 &&
      Number(item.io_stock_qty ?? 0) > 0
  );
  const body = option
    ? { it_id: product.it_id, options: [{ io_id: String(option.io_id), ct_qty: 1 }] }
    : { it_id: product.it_id, ct_qty: 1 };
  await apiJson('/shop/cart', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });
}

async function cleanupCart(token) {
  await apiOk('/shop/cart', {
    method: 'DELETE',
    headers: authHeaders(token),
  });
}

async function waitForResponseAfterAction(page, label, predicate, action) {
  try {
    const [response] = await Promise.all([
      page.waitForResponse(predicate),
      action(),
    ]);
    return response;
  } catch (error) {
    const runtime = await page
      .evaluate(() => ({
        href: window.location.href,
        pathname: window.location.pathname,
        runtimeConfig: window.__G5_NEXTJS25_CONFIG__ || null,
        text: document.body?.innerText?.slice(0, 2000) || '',
      }))
      .catch(() => null);
    fail(`${label} API response was not observed`, {
      error: error instanceof Error ? error.message : String(error),
      runtime,
    });
  }
}

async function verifyZoneApi(token, czId, downloaded) {
  const payload = await apiJson('/shop/coupons/zone', {
    headers: authHeaders(token),
  });
  const zone = (payload.data || []).find((item) => Number(item.cz_id) === Number(czId));
  if (!zone || zone.cz_subject !== couponSubject || !!zone.downloaded !== downloaded) {
    fail('coupon zone API did not expose expected download state', {
      expected: { czId, couponSubject, downloaded },
      zones: payload.data,
    });
  }
  return zone;
}

async function verifyCouponIssued(token, cpId) {
  const payload = await apiJson('/shop/coupons', {
    headers: authHeaders(token),
  });
  const coupon = (payload.data || []).find((item) => item.cp_id === cpId);
  if (
    !coupon ||
    coupon.cp_subject !== couponSubject ||
    coupon.cp_used !== '' ||
    Number(coupon.cp_price) !== 3000
  ) {
    fail('issued coupon did not appear in my coupon API', {
      cpId,
      couponSubject,
      coupons: payload.data,
    });
  }
  return coupon;
}

async function verifyBrowserDownloadAndMypage(page, token, czId) {
  const authReady = page
    .waitForResponse(
      (response) =>
        response.url().includes('/auth/me') &&
        response.request().method() === 'GET' &&
        response.status() === 200,
      { timeout: 10000 }
    )
    .catch(() => null);

  await page.goto(`${appUrl}/shop/couponzone`, { waitUntil: 'networkidle' });
  await authReady;
  await page.getByText(couponSubject, { exact: false }).first().waitFor({
    state: 'visible',
    timeout: 10000,
  });

  const card = page.locator('div.flex.overflow-hidden').filter({ hasText: couponSubject }).first();
  const downloadResponse = await waitForResponseAfterAction(
    page,
    'coupon download',
    (response) =>
      response.url().replace(/\/+$/, '').endsWith('/shop/coupons/download') &&
      response.request().method() === 'POST',
    () => card.locator('button').last().click()
  );
  await assertOkResponse(downloadResponse, 'coupon download');
  const downloadPayload = await downloadResponse.json();
  const cpId = String(downloadPayload?.data?.cp_id || '');
  if (!cpId || Number(downloadPayload?.data?.cz_id) !== Number(czId)) {
    fail('coupon download did not return the expected coupon identifiers', downloadPayload);
  }

  await verifyZoneApi(token, czId, true);
  await verifyCouponIssued(token, cpId);

  await page.goto(`${appUrl}/mypage/coupons`, { waitUntil: 'networkidle' });
  await page.getByText(couponSubject, { exact: false }).first().waitFor({
    state: 'visible',
    timeout: 10000,
  });
  const body = await page.locator('body').innerText({ timeout: 10000 });
  if (!body.includes(couponSubject) || !body.includes('3,000')) {
    fail('mypage coupon page did not render the downloaded coupon', {
      couponSubject,
      body: body.slice(0, 2000),
    });
  }

  return { cpId };
}

async function verifyCheckoutCouponSelection(page, token, product, cpId) {
  await page.goto(`${appUrl}/shop/order`, { waitUntil: 'networkidle' });
  await page.getByText(product.it_name, { exact: false }).first().waitFor({
    state: 'visible',
    timeout: 10000,
  });

  const couponSelect = page.getByLabel('주문 쿠폰');
  await couponSelect.locator(`option[value="${cpId}"]`).waitFor({
    state: 'attached',
    timeout: 10000,
  });
  await couponSelect.selectOption(cpId);
  if ((await couponSelect.inputValue()) !== cpId) {
    fail('checkout did not select the downloaded order coupon', {
      cpId,
      selected: await couponSelect.inputValue(),
    });
  }

  const cart = await apiJson('/shop/cart', {
    headers: authHeaders(token),
  });
  const expectedDiscount = Math.min(3000, Number(cart.data?.total_price || 0));
  const body = await page.locator('body').innerText({ timeout: 10000 });
  const discountText = `-${expectedDiscount.toLocaleString('ko-KR')}`;
  if (
    expectedDiscount <= 0 ||
    !body.includes('쿠폰 할인') ||
    !body.includes(discountText)
  ) {
    fail('checkout coupon selection did not update the displayed discount', {
      cpId,
      expectedDiscount,
      body: body.slice(0, 2500),
    });
  }

  return { cpId, displayedDiscount: expectedDiscount };
}

let browser = null;
let credentials = null;
let exitCode = 0;
let seededZone = null;

try {
  seedSmokeMember();
  cleanupCoupons();
  seededZone = seedCouponZone();
  credentials = await login();
  await verifyZoneApi(credentials.token, seededZone.cz_id, false);
  const product = await getProduct();
  await setupCart(credentials.token, product);

  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1366, height: 900 },
    serviceWorkers: 'block',
  });
  await context.addInitScript((token) => {
    window.localStorage.setItem('g5_token', token);
  }, credentials.token);
  await context.addCookies([
    {
      name: 'g5_token',
      value: credentials.token,
      url: appUrl,
      sameSite: 'Lax',
    },
    ...(credentials.refreshToken
      ? [
          {
            name: 'g5_refresh',
            value: credentials.refreshToken,
            url: appUrl,
            sameSite: 'Lax',
          },
        ]
      : []),
  ]);

  const page = await context.newPage();
  const result = await verifyBrowserDownloadAndMypage(page, credentials.token, seededZone.cz_id);
  const checkoutResult = await verifyCheckoutCouponSelection(
    page,
    credentials.token,
    product,
    result.cpId
  );
  await context.close();

  console.table([
    {
      czId: seededZone.cz_id,
      cpId: result.cpId,
      subject: couponSubject,
      checkoutDiscount: checkoutResult.displayedDiscount,
    },
  ]);
  console.log(`[check-local-coupon-actions] app=${appUrl}`);
  console.log(`[check-local-coupon-actions] api=${expectedApiUrl}`);
} catch (error) {
  printFailure(error);
  exitCode = 1;
} finally {
  if (browser) {
    await browser.close();
  }
  try {
    cleanupCoupons();
  } catch (error) {
    printFailure(error, 'check-local-coupon-actions cleanup');
    exitCode = 1;
  }
  if (credentials?.token) {
    try {
      await cleanupCart(credentials.token);
    } catch (error) {
      printFailure(error, 'check-local-coupon-actions cart cleanup');
      exitCode = 1;
    }
  }
  try {
    seedSmokeMember();
  } catch (error) {
    printFailure(error, 'check-local-coupon-actions reset');
    exitCode = 1;
  }
}

process.exit(exitCode);
