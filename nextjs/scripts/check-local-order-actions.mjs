import { chromium } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const appUrl = trimTrailingSlash(process.env.LOCAL_APP_URL || 'http://127.0.0.20');
const expectedApiUrl = trimTrailingSlash(
  process.env.LOCAL_EXPECTED_API_URL || 'http://127.0.0.9/api/v1'
);

const smokeMemberId = process.env.LOCAL_SMOKE_LOGIN_ID || 'nextjs_smoke';
const smokeMemberPassword =
  process.env.LOCAL_SMOKE_LOGIN_PASSWORD || 'NextjsSmoke123!';
const smokeProductId = process.env.LOCAL_SMOKE_SHOP_PRODUCT_ID || '1446772772';
const smokeMarker = process.env.LOCAL_SMOKE_ORDER_MARKER || 'nextjs-local-order-smoke';
const smokeRunId = `${Date.now()}`;
const sendCouponSubject =
  process.env.LOCAL_SMOKE_SEND_COUPON_SUBJECT || 'nextjs-local-send-coupon-smoke 1000';
const orderCouponSubject =
  process.env.LOCAL_SMOKE_ORDER_COUPON_SUBJECT || 'nextjs-local-order-coupon-smoke 2000';
const itemCouponSubject =
  process.env.LOCAL_SMOKE_ITEM_COUPON_SUBJECT || 'nextjs-local-item-coupon-smoke 1500';
const categoryCouponSubject =
  process.env.LOCAL_SMOKE_CATEGORY_COUPON_SUBJECT || 'nextjs-local-category-coupon-smoke 1200';
const itemPaymentCouponSubject =
  process.env.LOCAL_SMOKE_ITEM_PAYMENT_COUPON_SUBJECT ||
  'nextjs-local-item-payment-coupon-smoke 1400';
const categoryPaymentCouponSubject =
  process.env.LOCAL_SMOKE_CATEGORY_PAYMENT_COUPON_SUBJECT ||
  'nextjs-local-category-payment-coupon-smoke 1100';
const orderPointMarker =
  process.env.LOCAL_SMOKE_ORDER_POINT_MARKER || `${smokeMarker}-order-point`;
const smokeCrossSiteOrigin =
  process.env.LOCAL_SMOKE_CROSS_SITE_ORIGIN || 'https://nextjs.thisgun.net';

const STATUS_ORDERED = '\uC8FC\uBB38';
const STATUS_PAID = '\uC785\uAE08';
const STATUS_SHIPPING = '\uBC30\uC1A1';
const STATUS_CANCELLED = '\uCDE8\uC18C';
const SETTLE_BANK = '\uBB34\uD1B5\uC7A5\uC785\uAE08';
const SETTLE_CARD = '\uC2E0\uC6A9\uCE74\uB4DC';

function trimTrailingSlash(value) {
  return String(value).replace(/\/+$/, '');
}

function fail(message, details = undefined) {
  const error = new Error(message);
  error.details = details;
  throw error;
}

function printFailure(error, prefix = 'check-local-order-actions') {
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
      LOCAL_SMOKE_LOGIN_ID: smokeMemberId,
      LOCAL_SMOKE_LOGIN_PASSWORD: smokeMemberPassword,
      LOCAL_SMOKE_LOGIN_EMAIL:
        process.env.LOCAL_SMOKE_LOGIN_EMAIL || `${smokeMemberId}@example.test`,
      LOCAL_SMOKE_LOGIN_NAME: process.env.LOCAL_SMOKE_LOGIN_NAME || 'Nextjs Smoke',
      LOCAL_SMOKE_LOGIN_NICK: process.env.LOCAL_SMOKE_LOGIN_NICK || 'NextjsSmoke',
      LOCAL_SMOKE_ORDER_MARKER: smokeMarker,
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

function createCookieJar() {
  const cookies = new Map();

  return {
    header() {
      return Array.from(cookies.entries())
        .map(([name, value]) => `${name}=${value}`)
        .join('; ');
    },
    store(headers) {
      const values =
        typeof headers.getSetCookie === 'function'
          ? headers.getSetCookie()
          : headers.get('set-cookie')
            ? [headers.get('set-cookie')]
            : [];

      for (const value of values) {
        for (const part of String(value).split(/,(?=[^;=]+=[^;]+)/)) {
          const cookie = part.trim().split(';')[0] || '';
          const separator = cookie.indexOf('=');
          if (separator > 0) {
            cookies.set(cookie.slice(0, separator), cookie.slice(separator + 1));
          }
        }
      }
    },
  };
}

async function fetchApi(path, options = {}) {
  const { cookieJar, ...fetchOptions } = options;
  const cookieHeader = cookieJar?.header?.();
  const response = await fetch(`${expectedApiUrl}${path}`, {
    ...fetchOptions,
    headers: {
      Accept: 'application/json',
      ...(fetchOptions.body ? { 'Content-Type': 'application/json' } : {}),
      ...(cookieHeader ? { Cookie: cookieHeader } : {}),
      ...(fetchOptions.headers || {}),
    },
  });
  cookieJar?.store?.(response.headers);

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
  if (!response.ok || (response.status !== 204 && payload && payload.success === false)) {
    fail(`API request failed: ${path}`, {
      status: response.status,
      message: payload?.message || response.statusText,
      payload,
    });
  }
  return payload;
}

async function apiFailure(path, options = {}, expectedStatus = 400) {
  const { response, payload } = await fetchApi(path, options);
  if (response.status !== expectedStatus || payload?.success !== false) {
    fail(`API request should have failed: ${path}`, {
      expectedStatus,
      status: response.status,
      message: payload?.message || response.statusText,
      payload,
    });
  }
  return payload;
}

async function currentCartRows(token, query = '') {
  const payload = await apiJson(`/shop/cart${query}`, {
    headers: authHeaders(token),
  });
  return payload.data?.items || [];
}

async function currentGuestCartRows(cookieJar, query = '') {
  const payload = await apiJson(`/shop/cart${query}`, {
    cookieJar,
  });
  return payload.data?.items || [];
}

async function login() {
  const payload = await apiJson('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ mb_id: smokeMemberId, mb_password: smokeMemberPassword }),
  });
  const token = payload.data?.token;
  const refreshToken = payload.data?.refresh_token;
  if (!token) {
    fail('smoke member login did not return a token');
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
    fail('smoke product was not returned by the API', payload);
  }
  if (String(product.it_soldout) === '1' || Number(product.it_stock_qty || 0) <= 0) {
    fail('smoke product is not available for order checks', product);
  }
  return product;
}

function firstUsableOption(product) {
  const option = (product.options || []).find(
    (item) =>
      Number(item.io_type) === 0 &&
      Number(item.io_use ?? 1) === 1 &&
      Number(item.io_stock_qty ?? 0) > 0
  );
  if (!option) return null;
  return {
    ioId: String(option.io_id),
  };
}

async function cleanupCart(token) {
  await apiOk('/shop/cart', {
    method: 'DELETE',
    headers: authHeaders(token),
  });
}

function cartAddBody(product, option, qty, extra = {}) {
  return option
    ? {
        it_id: product.it_id,
        options: [{ io_id: option.ioId, ct_qty: qty }],
        ...extra,
      }
    : {
        it_id: product.it_id,
        ct_qty: qty,
        ...extra,
      };
}

function cartIdsFromAddPayload(payload) {
  const data = payload?.data || {};
  return [
    data.ct_id,
    ...((data.items || []).map((item) => item.ct_id)),
  ]
    .filter((id) => id !== undefined && id !== null && String(id) !== '')
    .map((id) => String(id));
}

function cleanupOrders(orderId = '', includeGuests = false) {
  const args = orderId ? [`--order-id=${orderId}`] : [];
  if (includeGuests) {
    args.push('--include-guests');
  }
  return runPhp('cleanup_nextjs_smoke_orders.php', {}, args);
}

function markSmokeOrderPaid(orderId, args = []) {
  return runPhp('mark_nextjs_smoke_order_paid.php', {}, [`--order-id=${orderId}`, ...args]);
}

function setSmokeStock(product, option, stock) {
  const args = [`--product-id=${product.it_id}`, `--stock=${stock}`];
  if (option?.ioId) {
    args.push(`--io-id=${option.ioId}`, '--io-type=0');
  }
  return runPhp('set_nextjs_smoke_product_stock.php', {}, args);
}

function seedSendCouponZone() {
  return runPhp('seed_nextjs_smoke_coupon_zone.php', {
    LOCAL_SMOKE_COUPON_SUBJECT: sendCouponSubject,
    LOCAL_SMOKE_COUPON_PRICE: '1000',
    LOCAL_SMOKE_COUPON_MINIMUM: '0',
    LOCAL_SMOKE_COUPON_METHOD: '3',
  });
}

function cleanupSendCoupons() {
  return runPhp('cleanup_nextjs_smoke_coupons.php', {
    LOCAL_SMOKE_COUPON_LOGIN_ID: smokeMemberId,
    LOCAL_SMOKE_COUPON_SUBJECT: sendCouponSubject,
  });
}

function seedOrderCouponZone(price = 2000) {
  return runPhp('seed_nextjs_smoke_coupon_zone.php', {
    LOCAL_SMOKE_COUPON_SUBJECT: orderCouponSubject,
    LOCAL_SMOKE_COUPON_PRICE: String(price),
    LOCAL_SMOKE_COUPON_MINIMUM: '0',
    LOCAL_SMOKE_COUPON_METHOD: '2',
  });
}

function cleanupOrderCoupons() {
  return runPhp('cleanup_nextjs_smoke_coupons.php', {
    LOCAL_SMOKE_COUPON_LOGIN_ID: smokeMemberId,
    LOCAL_SMOKE_COUPON_SUBJECT: orderCouponSubject,
  });
}

function seedCartCouponZone(subject, method, target, price) {
  return runPhp('seed_nextjs_smoke_coupon_zone.php', {
    LOCAL_SMOKE_COUPON_SUBJECT: subject,
    LOCAL_SMOKE_COUPON_PRICE: String(price),
    LOCAL_SMOKE_COUPON_MINIMUM: '0',
    LOCAL_SMOKE_COUPON_METHOD: String(method),
    LOCAL_SMOKE_COUPON_TARGET: target,
  });
}

function cleanupCartCoupon(subject) {
  return runPhp('cleanup_nextjs_smoke_coupons.php', {
    LOCAL_SMOKE_COUPON_LOGIN_ID: smokeMemberId,
    LOCAL_SMOKE_COUPON_SUBJECT: subject,
  });
}

function seedOrderPoints() {
  return runPhp('seed_nextjs_smoke_points.php', {
    LOCAL_SMOKE_POINT_LOGIN_ID: smokeMemberId,
    LOCAL_SMOKE_POINT_MARKER: orderPointMarker,
    LOCAL_SMOKE_POINT_EARN: '10000',
    LOCAL_SMOKE_POINT_USE: '1000',
  });
}

function cleanupOrderPoints() {
  return runPhp('cleanup_nextjs_smoke_points.php', {
    LOCAL_SMOKE_POINT_LOGIN_ID: smokeMemberId,
    LOCAL_SMOKE_POINT_MARKER: orderPointMarker,
  });
}

async function setupCartForOrder(token, product) {
  await cleanupCart(token);

  const option = firstUsableOption(product);
  const body = cartAddBody(product, option, 1);

  await apiJson('/shop/cart', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(body),
  });

  const cart = await apiJson('/shop/cart', {
    headers: authHeaders(token),
  });
  const rows = cart.data?.items || [];
  const row = rows.find((item) => String(item.it_id) === product.it_id);
  if (!row) {
    fail('order setup cart item did not persist through the API', rows);
  }

  return {
    ctId: String(row.ct_id),
    option: option?.ioId || '',
  };
}

async function verifyCrossSiteGuestCookiePolicy(product) {
  const option = firstUsableOption(product);
  const cookieJar = createCookieJar();
  const { response, payload } = await fetchApi('/shop/cart', {
    method: 'POST',
    cookieJar,
    headers: {
      Origin: smokeCrossSiteOrigin,
      'X-Forwarded-Proto': 'https',
    },
    body: JSON.stringify(cartAddBody(product, option, 1)),
  });

  try {
    if (!response.ok || !payload?.success) {
      fail('cross-site guest cart cookie setup failed', {
        status: response.status,
        payload,
      });
    }

    const setCookie = response.headers.get('set-cookie') || '';
    if (!/SameSite=None/i.test(setCookie) || !/(^|;\s*)Secure(?:;|$)/i.test(setCookie)) {
      fail('cross-site guest cookie did not use SameSite=None; Secure', {
        origin: smokeCrossSiteOrigin,
        setCookie,
      });
    }

    return {
      crossSiteGuestCookie: 'SameSite=None; Secure',
      crossSiteOrigin: smokeCrossSiteOrigin,
    };
  } finally {
    await apiOk('/shop/cart', {
      method: 'DELETE',
      cookieJar,
    }).catch(() => null);
  }
}

async function verifyOrderStockRevalidation(token, product) {
  await cleanupCart(token);

  const option = firstUsableOption(product);
  let stockSnapshot = null;
  try {
    const directAdd = await apiJson('/shop/cart', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(cartAddBody(product, option, 1, { direct: true })),
    });
    const directCtIds = cartIdsFromAddPayload(directAdd);
    if (directCtIds.length === 0) {
      fail('stock revalidation setup did not return direct cart row ids', directAdd);
    }

    stockSnapshot = setSmokeStock(product, option, 0);
    const failure = await apiFailure('/shop/orders', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        ct_ids: directCtIds.join(','),
        od_name: 'NextjsSmoke',
        od_tel: '02-000-0000',
        od_hp: '010-1234-5678',
        od_email: `${smokeMemberId}@example.test`,
        od_zip: '12345',
        od_addr1: 'Next.js smoke address',
        od_addr2: 'Stock revalidation',
        od_memo: `${smokeMarker} stock-revalidation ${smokeRunId}`,
        od_settle_case: SETTLE_CARD,
      }),
    });

    const message = String(failure?.message || '');
    if (!message.includes('재고수량')) {
      fail('stock revalidation failure did not return a stock shortage message', failure);
    }

    return {
      stockRevalidation: option ? 'option' : 'product',
      stockFailureStatus: 400,
    };
  } finally {
    if (stockSnapshot) {
      setSmokeStock(product, option, Number(stockSnapshot.previous_stock || 0));
    }
    await cleanupCart(token);
  }
}

async function verifyDirectBuyScope(token, product) {
  await cleanupCart(token);

  const option = firstUsableOption(product);
  await apiJson('/shop/cart', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(cartAddBody(product, option, 1)),
  });

  const visibleBeforeDirect = await currentCartRows(token);
  const normalRow = visibleBeforeDirect.find((row) => String(row.it_id) === product.it_id);
  if (!normalRow) {
    fail('direct-buy setup did not create a normal cart row', visibleBeforeDirect);
  }

  const directAdd = await apiJson('/shop/cart', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(cartAddBody(product, option, 1, { direct: true })),
  });
  const directCtIds = cartIdsFromAddPayload(directAdd);
  if (directCtIds.length === 0) {
    fail('direct cart add did not return cart row ids', directAdd);
  }

  const visibleAfterDirect = await currentCartRows(token);
  if (visibleAfterDirect.some((row) => directCtIds.includes(String(row.ct_id)))) {
    fail('direct cart rows leaked into the normal cart response', {
      directCtIds,
      visibleAfterDirect,
    });
  }
  if (!visibleAfterDirect.some((row) => String(row.ct_id) === String(normalRow.ct_id))) {
    fail('normal cart row disappeared after direct cart add', {
      normalRow,
      visibleAfterDirect,
    });
  }

  const directRows = await currentCartRows(
    token,
    `?ct_ids=${encodeURIComponent(directCtIds.join(','))}`
  );
  if (directRows.length !== directCtIds.length) {
    fail('direct cart query did not return exactly the direct rows', {
      directCtIds,
      directRows,
    });
  }

  const orderPayload = await apiJson('/shop/orders', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({
      ct_ids: directCtIds.join(','),
      od_name: 'NextjsSmoke',
      od_tel: '02-000-0000',
      od_hp: '010-1234-5678',
      od_email: `${smokeMemberId}@example.test`,
      od_zip: '12345',
      od_addr1: 'Next.js smoke address',
      od_addr2: 'Direct buy scope',
      od_memo: `${smokeMarker} direct ${smokeRunId}`,
      od_settle_case: '무통장',
      od_bank_account: 'smoke-bank',
      od_deposit_name: 'NextjsSmoke',
    }),
  });
  const orderId = String(orderPayload.data?.od_id || orderPayload.data?.order?.od_id || '');
  if (!/^[0-9]{8,20}$/.test(orderId)) {
    fail('direct-buy scoped order did not return a valid order id', orderPayload);
  }

  const detail = await apiJson(`/shop/orders/${orderId}`, {
    headers: authHeaders(token),
  });
  const orderedItems = detail.data?.items || [];
  const unexpectedItems = orderedItems.filter(
    (item) => !directCtIds.includes(String(item.ct_id))
  );
  if (orderedItems.length !== directCtIds.length || unexpectedItems.length > 0) {
    fail('direct-buy scoped order included non-direct cart rows', {
      directCtIds,
      orderedItems,
    });
  }

  const remainingRows = await currentCartRows(token);
  if (!remainingRows.some((row) => String(row.ct_id) === String(normalRow.ct_id))) {
    fail('normal cart row was consumed by a direct-buy scoped order', {
      normalRow,
      remainingRows,
    });
  }

  return {
    directOrderId: orderId,
    directRows: directCtIds.length,
    normalCartPreserved: true,
  };
}

async function verifyGuestOrderLookup(product) {
  const option = firstUsableOption(product);
  const guestCartJar = createCookieJar();
  let orderId = '';

  try {
    const directAdd = await apiJson('/shop/cart', {
      method: 'POST',
      cookieJar: guestCartJar,
      body: JSON.stringify(cartAddBody(product, option, 1, { direct: true })),
    });
    const directCtIds = cartIdsFromAddPayload(directAdd);
    if (directCtIds.length === 0) {
      fail('guest direct cart add did not return cart row ids', directAdd);
    }

    const guestPassword = 'abc123';
    const orderPayload = await apiJson('/shop/orders', {
      method: 'POST',
      cookieJar: guestCartJar,
      body: JSON.stringify({
        ct_ids: directCtIds.join(','),
        od_name: 'GuestSmoke',
        od_tel: '02-000-0000',
        od_hp: '010-1234-5678',
        od_email: 'guest-smoke@example.test',
        od_zip: '12345',
        od_addr1: 'Next.js guest smoke address',
        od_addr2: 'Guest order lookup',
        od_memo: `${smokeMarker} guest ${smokeRunId}`,
        od_settle_case: SETTLE_BANK,
        od_bank_account: 'smoke-bank',
        od_deposit_name: 'GuestSmoke',
        od_pwd: guestPassword,
      }),
    });

    orderId = String(orderPayload.data?.od_id || orderPayload.data?.order?.od_id || '');
    const createdUid = String(orderPayload.data?.uid || orderPayload.data?.order?.uid || '');
    if (!/^[0-9]{8,20}$/.test(orderId) || createdUid.length !== 64) {
      fail('guest order did not return a valid order id and uid', orderPayload);
    }

    await apiFailure(
      '/shop/orders/lookup',
      {
        method: 'POST',
        cookieJar: createCookieJar(),
        body: JSON.stringify({
          od_id: orderId,
          od_pwd: 'wrong123',
        }),
      },
      404
    );

    const lookupJar = createCookieJar();
    const lookupPayload = await apiJson('/shop/orders/lookup', {
      method: 'POST',
      cookieJar: lookupJar,
      body: JSON.stringify({
        od_id: orderId,
        od_pwd: guestPassword,
      }),
    });
    const lookupUid = String(lookupPayload.data?.uid || '');
    const redirectUrl = String(lookupPayload.data?.redirect_url || '');
    if (lookupUid !== createdUid || !redirectUrl.includes(`uid=${encodeURIComponent(lookupUid)}`)) {
      fail('guest order lookup did not return the expected uid redirect', {
        createdUid,
        lookupPayload,
      });
    }

    const detail = await apiJson(
      `/shop/orders/${orderId}?uid=${encodeURIComponent(lookupUid)}`,
      {
        cookieJar: createCookieJar(),
      }
    );
    const order = detail.data || {};
    if (String(order.od_id || '') !== orderId || String(order.mb_id || '') !== '') {
      fail('guest order uid detail did not return the expected guest order', order);
    }
    if (!String(order.od_memo || '').includes(smokeMarker)) {
      fail('guest order detail is missing the smoke cleanup marker', order);
    }
    if (order.can_cancel !== true || String(order.cancel_block_reason || '') !== '') {
      fail('guest order detail did not expose YoungCart guest cancel availability', {
        can_cancel: order.can_cancel,
        cancel_block_reason: order.cancel_block_reason,
      });
    }

    await apiFailure(
      `/shop/orders/${orderId}`,
      {
        method: 'PATCH',
        cookieJar: createCookieJar(),
        body: JSON.stringify({
          uid: 'wrong-guest-order-uid',
          reason: 'guest order wrong uid cancel smoke',
        }),
      },
      404
    );

    await apiJson(`/shop/orders/${orderId}`, {
      method: 'PATCH',
      cookieJar: createCookieJar(),
      body: JSON.stringify({
        uid: lookupUid,
        reason: 'guest order cancel smoke',
      }),
    });

    const cancelledDetail = await apiJson(
      `/shop/orders/${orderId}?uid=${encodeURIComponent(lookupUid)}`,
      {
        cookieJar: createCookieJar(),
      }
    );
    const cancelled = cancelledDetail.data || {};
    const notCancelled = (cancelled.items || []).filter(
      (item) => String(item.ct_status || '') !== STATUS_CANCELLED
    );
    if (
      String(cancelled.od_status || '') !== STATUS_CANCELLED ||
      cancelled.can_cancel !== false ||
      notCancelled.length > 0 ||
      Number(cancelled.od_cancel_price || 0) !== Number(cancelled.od_cart_price || 0)
    ) {
      fail('guest order cancel did not persist YoungCart cancellation state', {
        cancelled,
        notCancelled,
      });
    }

    return {
      guestOrderId: orderId,
      guestUidLength: lookupUid.length,
      guestRows: directCtIds.length,
      guestCancelled: true,
    };
  } catch (error) {
    if (orderId) {
      cleanupOrders(orderId, true);
    }
    throw error;
  }
}

async function verifyGuestPaymentPrepareCancel(product) {
  const option = firstUsableOption(product);
  const guestJar = createCookieJar();
  let orderId = '';

  try {
    await apiJson('/shop/cart', {
      method: 'POST',
      cookieJar: guestJar,
      body: JSON.stringify(cartAddBody(product, option, 1)),
    });
    const normalRows = await currentGuestCartRows(guestJar);
    const normalRow = normalRows.find((row) => String(row.it_id) === product.it_id);
    if (!normalRow) {
      fail('guest payment setup did not create a normal cart row', normalRows);
    }

    const directAdd = await apiJson('/shop/cart', {
      method: 'POST',
      cookieJar: guestJar,
      body: JSON.stringify(cartAddBody(product, option, 1, { direct: true })),
    });
    const directCtIds = cartIdsFromAddPayload(directAdd);
    if (directCtIds.length === 0) {
      fail('guest payment prepare setup did not return direct cart ids', directAdd);
    }

    const prepared = await apiJson('/shop/payment/prepare', {
      method: 'POST',
      cookieJar: guestJar,
      body: JSON.stringify({
        ct_ids: directCtIds.join(','),
        od_name: 'GuestSmoke',
        od_tel: '02-000-0000',
        od_hp: '010-1234-5678',
        od_email: 'guest-payment-smoke@example.test',
        od_zip: '12345',
        od_addr1: 'Next.js guest smoke address',
        od_addr2: 'Guest payment prepare cancel',
        od_memo: `${smokeMarker} guest-payment ${smokeRunId}`,
        od_settle_case: SETTLE_CARD,
        od_pwd: 'abc123',
      }),
    });

    orderId = String(prepared.data?.order_id || '');
    const uid = String(prepared.data?.uid || '');
    const amount = Number(prepared.data?.amount || 0);
    if (!/^[0-9]{8,20}$/.test(orderId) || uid.length !== 64 || amount <= 0) {
      fail('guest payment prepare did not return a valid order id, uid, and amount', prepared);
    }

    await apiFailure(
      '/shop/payment/cancel',
      {
        method: 'POST',
        cookieJar: createCookieJar(),
        body: JSON.stringify({
          order_id: orderId,
          reason: 'untrusted guest cancel smoke',
        }),
      },
      404
    );

    const detail = await apiJson(
      `/shop/orders/${orderId}?uid=${encodeURIComponent(uid)}`,
      {
        cookieJar: createCookieJar(),
      }
    );
    const order = detail.data || {};
    if (String(order.od_id || '') !== orderId || String(order.od_status || '') === '') {
      fail('guest prepared payment order detail was not visible with uid', order);
    }

    const cancelled = await apiJson('/shop/payment/cancel', {
      method: 'POST',
      cookieJar: guestJar,
      body: JSON.stringify({
        order_id: orderId,
        reason: 'guest payment prepare cancel smoke',
      }),
    });
    if (String(cancelled.data?.status || '') !== STATUS_CANCELLED) {
      fail('guest payment cancel did not return cancelled status', cancelled);
    }

    const restoredDirectRows = await currentGuestCartRows(
      guestJar,
      `?ct_ids=${encodeURIComponent(directCtIds.join(','))}`
    );
    if (restoredDirectRows.length !== directCtIds.length) {
      fail('guest payment cancel did not restore direct-buy rows', {
        directCtIds,
        restoredDirectRows,
      });
    }

    const visibleRows = await currentGuestCartRows(guestJar);
    if (!visibleRows.some((row) => String(row.ct_id) === String(normalRow.ct_id))) {
      fail('guest payment cancel consumed the normal cart row', {
        normalRow,
        visibleRows,
      });
    }

    await apiOk('/shop/cart', {
      method: 'DELETE',
      cookieJar: guestJar,
    });

    return {
      guestPreparedOrderId: orderId,
      guestPreparedRows: directCtIds.length,
      guestPaymentCancelled: true,
    };
  } catch (error) {
    if (orderId) {
      cleanupOrders(orderId, true);
    }
    throw error;
  }
}

async function verifyPreparedPaymentRestore(token, product) {
  await cleanupCart(token);

  const option = firstUsableOption(product);
  await apiJson('/shop/cart', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(cartAddBody(product, option, 1)),
  });
  const normalRows = await currentCartRows(token);
  const normalRow = normalRows.find((row) => String(row.it_id) === product.it_id);
  if (!normalRow) {
    fail('prepared payment restore setup did not create a normal cart row', normalRows);
  }

  const directAdd = await apiJson('/shop/cart', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(cartAddBody(product, option, 1, { direct: true })),
  });
  const directCtIds = cartIdsFromAddPayload(directAdd);
  if (directCtIds.length === 0) {
    fail('prepared payment restore setup did not return direct cart ids', directAdd);
  }

  const orderBody = {
    ct_ids: directCtIds.join(','),
    od_name: 'NextjsSmoke',
    od_tel: '02-000-0000',
    od_hp: '010-1234-5678',
    od_email: `${smokeMemberId}@example.test`,
    od_zip: '12345',
    od_addr1: 'Next.js smoke address',
    od_addr2: 'Prepared payment restore',
    od_memo: `${smokeMarker} prepared ${smokeRunId}`,
    od_settle_case: '신용카드',
  };

  const prepared = await apiJson('/shop/payment/prepare', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(orderBody),
  });
  const preparedOrderId = String(prepared.data?.order_id || '');
  if (!/^[0-9]{8,20}$/.test(preparedOrderId)) {
    fail('payment prepare did not return a valid order id', prepared);
  }

  await apiJson('/shop/payment/cancel', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({
      order_id: preparedOrderId,
      reason: 'smoke KCP cancel restore',
    }),
  });

  const cancelledRows = await currentCartRows(
    token,
    `?ct_ids=${encodeURIComponent(directCtIds.join(','))}`
  );
  if (cancelledRows.length !== directCtIds.length) {
    fail('payment cancel did not restore direct-buy cart rows', {
      directCtIds,
      cancelledRows,
    });
  }

  await cleanupCart(token);
  await apiJson('/shop/cart', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(cartAddBody(product, option, 1)),
  });
  const refreshNormalRows = await currentCartRows(token);
  const refreshNormalRow = refreshNormalRows.find((row) => String(row.it_id) === product.it_id);
  if (!refreshNormalRow) {
    fail('prepared payment refresh setup did not create a normal cart row', refreshNormalRows);
  }
  const directRefreshAdd = await apiJson('/shop/cart', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(cartAddBody(product, option, 1, { direct: true })),
  });
  const refreshCtIds = cartIdsFromAddPayload(directRefreshAdd);
  if (refreshCtIds.length === 0) {
    fail('prepared payment refresh setup did not return direct cart ids', directRefreshAdd);
  }

  const refreshPrepared = await apiJson('/shop/payment/prepare', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({
      ...orderBody,
      ct_ids: refreshCtIds.join(','),
      od_memo: `${smokeMarker} prepared-refresh ${smokeRunId}`,
    }),
  });
  const refreshOrderId = String(refreshPrepared.data?.order_id || '');
  if (!/^[0-9]{8,20}$/.test(refreshOrderId)) {
    fail('refresh payment prepare did not return a valid order id', refreshPrepared);
  }

  const restoredByRead = await currentCartRows(
    token,
    `?ct_ids=${encodeURIComponent(refreshCtIds.join(','))}`
  );
  if (restoredByRead.length !== refreshCtIds.length) {
    fail('direct-buy ct_ids read did not restore pending prepared rows', {
      refreshCtIds,
      restoredByRead,
    });
  }

  const visibleNormalRows = await currentCartRows(token);
  if (!visibleNormalRows.some((row) => String(row.ct_id) === String(refreshNormalRow.ct_id))) {
    fail('prepared payment restore consumed the normal cart row', {
      normalRow: refreshNormalRow,
      visibleNormalRows,
    });
  }

  await cleanupCart(token);
  const kcpDirectAdd = await apiJson('/shop/cart', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(cartAddBody(product, option, 1, { direct: true })),
  });
  const kcpCtIds = cartIdsFromAddPayload(kcpDirectAdd);
  if (kcpCtIds.length === 0) {
    fail('KCP confirm setup did not return direct cart ids', kcpDirectAdd);
  }

  const kcpPrepared = await apiJson('/shop/payment/prepare', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({
      ...orderBody,
      ct_ids: kcpCtIds.join(','),
      od_memo: `${smokeMarker} kcp-confirm ${smokeRunId}`,
    }),
  });
  const kcpOrderId = String(kcpPrepared.data?.order_id || '');
  const kcpAmount = Number(kcpPrepared.data?.amount || 0);
  if (!/^[0-9]{8,20}$/.test(kcpOrderId) || kcpAmount <= 0) {
    fail('KCP payment prepare did not return a valid order/amount', kcpPrepared);
  }

  const preparedPgService = String(kcpPrepared.data?.pg_service || '').toLowerCase();
  if (preparedPgService !== 'kcp') {
    await apiJson('/shop/payment/cancel', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        order_id: kcpOrderId,
        reason: `smoke PG confirm skipped for ${preparedPgService || 'unknown'} config`,
      }),
    });

    return {
      preparedOrderId,
      refreshOrderId,
      kcpOrderId,
      restoredDirectRows: directCtIds.length + refreshCtIds.length,
      pgConfirmSkipped: preparedPgService || 'unknown',
    };
  }

  const confirmed = await apiJson('/shop/payment/confirm', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({
      pg_service: 'kcp',
      order_id: kcpOrderId,
      amount: kcpAmount,
      res_cd: '0000',
      res_msg: 'smoke approval',
      enc_info: 'smoke-enc-info',
      enc_data: 'smoke-enc-data',
      tran_cd: '00100000',
      site_cd: 'T0000',
      tno: `SMOKEKCP${smokeRunId.slice(-8)}`,
    }),
  });
  if (confirmed.data?.status !== STATUS_PAID) {
    fail('KCP confirm did not finalize the order status', confirmed);
  }

  const kcpDetail = await apiJson(`/shop/orders/${kcpOrderId}`, {
    headers: authHeaders(token),
  });
  const kcpItems = kcpDetail.data?.items || [];
  if (
    kcpItems.length !== kcpCtIds.length ||
    kcpItems.some((item) => !kcpCtIds.includes(String(item.ct_id)))
  ) {
    fail('KCP confirm included unexpected cart rows', {
      kcpCtIds,
      kcpItems,
    });
  }
  if (String(kcpDetail.data?.od_status || '') !== STATUS_PAID) {
    fail('KCP confirmed order detail did not persist YoungCart paid status', kcpDetail.data);
  }
  if (kcpItems.some((item) => String(item.ct_status || '') !== STATUS_PAID)) {
    fail('KCP confirmed cart rows did not inherit YoungCart paid status', {
      expectedStatus: STATUS_PAID,
      kcpItems,
    });
  }

  return {
    preparedOrderId,
    refreshOrderId,
    kcpOrderId,
    restoredDirectRows: directCtIds.length + refreshCtIds.length,
  };
}

async function verifySendCouponPrepare(token, product) {
  await cleanupCart(token);
  cleanupSendCoupons();

  const zone = seedSendCouponZone();
  const download = await apiJson('/shop/coupons/download', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({ cz_id: zone.cz_id }),
  });
  const cpId = String(download.data?.cp_id || '');
  if (!cpId) {
    fail('shipping coupon download did not return a coupon id', download);
  }

  const option = firstUsableOption(product);
  await apiJson('/shop/cart', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(cartAddBody(product, option, 1)),
  });

  const cart = await apiJson('/shop/cart', {
    headers: authHeaders(token),
  });
  const cartTotal = Number(cart.data?.total_price || 0);
  if (cartTotal <= 0) {
    fail('shipping coupon prepare setup did not produce a positive cart total', cart);
  }

  const quote = await apiJson('/shop/shipping/quote', {
    headers: authHeaders(token),
  });
  const shippingTotal = Number(quote.data?.total || 0);
  const expectedDiscount = Math.min(1000, Math.max(0, shippingTotal));

  const prepared = await apiJson('/shop/payment/prepare', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({
      od_name: 'NextjsSmoke',
      od_tel: '02-000-0000',
      od_hp: '010-1234-5678',
      od_email: `${smokeMemberId}@example.test`,
      od_zip: '12345',
      od_addr1: 'Next.js smoke address',
      od_addr2: 'Shipping coupon prepare',
      od_memo: `${smokeMarker} send-coupon ${smokeRunId}`,
      od_settle_case: SETTLE_CARD,
      cp_id_send: cpId,
    }),
  });

  const orderId = String(prepared.data?.order_id || '');
  const amount = Number(prepared.data?.amount || 0);
  const expectedAmount = cartTotal + shippingTotal - expectedDiscount;
  if (!/^[0-9]{8,20}$/.test(orderId) || amount !== expectedAmount) {
    fail('shipping coupon prepare amount did not match YoungCart-style totals', {
      orderId,
      amount,
      expectedAmount,
      cartTotal,
      shippingTotal,
      expectedDiscount,
      prepared: prepared.data,
    });
  }

  await apiJson('/shop/payment/cancel', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify({
      order_id: orderId,
      reason: 'smoke shipping coupon prepare restore',
    }),
  });

  return {
    sendCouponOrderId: orderId,
    sendCouponDiscount: expectedDiscount,
    sendCouponAmount: amount,
  };
}

async function verifyOrderCouponPointDirect(token, product) {
  await cleanupCart(token);
  cleanupOrderCoupons();
  cleanupOrderPoints();
  seedOrderPoints();

  const option = firstUsableOption(product);
  let orderId = '';
  let cpId = '';

  try {
    const directAdd = await apiJson('/shop/cart', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(cartAddBody(product, option, 1, { direct: true })),
    });
    const directCtIds = cartIdsFromAddPayload(directAdd);
    if (directCtIds.length === 0) {
      fail('order coupon/point setup did not return direct cart row ids', directAdd);
    }

    const directRows = await currentCartRows(
      token,
      `?ct_ids=${encodeURIComponent(directCtIds.join(','))}`
    );
    const cartTotal = directRows.reduce((sum, row) => sum + Number(row.line_total || 0), 0);
    if (cartTotal <= 0) {
      fail('order coupon/point setup did not produce a positive cart total', directRows);
    }

    const orderCouponPrice = Math.max(1, Math.min(2000, Math.floor(cartTotal / 3)));
    const pointUse = Math.max(
      1,
      Math.min(1500, Math.floor((cartTotal - orderCouponPrice) / 2))
    );
    if (pointUse <= 0 || cartTotal - orderCouponPrice <= 0) {
      fail('order coupon/point setup product total is too small for a point-use assertion', {
        cartTotal,
        orderCouponPrice,
        pointUse,
      });
    }

    const zone = seedOrderCouponZone(orderCouponPrice);
    const download = await apiJson('/shop/coupons/download', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ cz_id: zone.cz_id }),
    });
    cpId = String(download.data?.cp_id || '');
    if (!cpId) {
      fail('order coupon download did not return a coupon id', download);
    }

    const quote = await apiJson(
      `/shop/shipping/quote?ct_ids=${encodeURIComponent(directCtIds.join(','))}`,
      {
        headers: authHeaders(token),
      }
    );
    const shippingTotal = Number(quote.data?.total || 0);
    const expectedOrderCoupon = Math.min(orderCouponPrice, cartTotal);
    const expectedPoint = Math.min(pointUse, 9000, Math.max(0, cartTotal - expectedOrderCoupon));
    const expectedReceipt = Math.max(
      0,
      cartTotal + shippingTotal - expectedOrderCoupon - expectedPoint
    );
    if (expectedPoint <= 0) {
      fail('order coupon/point setup did not produce a positive expected point use', {
        cartTotal,
        orderCouponPrice,
        pointUse,
        expectedOrderCoupon,
        expectedPoint,
      });
    }

    const orderPayload = await apiJson('/shop/orders', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        ct_ids: directCtIds.join(','),
        od_name: 'NextjsSmoke',
        od_tel: '02-000-0000',
        od_hp: '010-1234-5678',
        od_email: `${smokeMemberId}@example.test`,
        od_zip: '12345',
        od_addr1: 'Next.js smoke address',
        od_addr2: 'Order coupon point direct',
        od_memo: `${smokeMarker} order-coupon-point ${smokeRunId}`,
        od_settle_case: SETTLE_BANK,
        od_bank_account: 'smoke-bank',
        od_deposit_name: 'NextjsSmoke',
        cp_id: cpId,
        point_use: pointUse,
      }),
    });
    orderId = String(orderPayload.data?.od_id || orderPayload.data?.order?.od_id || '');
    if (!/^[0-9]{8,20}$/.test(orderId)) {
      fail('order coupon/point direct order did not return a valid order id', orderPayload);
    }

    const detail = await apiJson(`/shop/orders/${orderId}`, {
      headers: authHeaders(token),
    });
    const order = detail.data || {};
    const actualShippingTotal =
      Number(order.od_send_cost || 0) + Number(order.od_send_cost2 || 0);
    const amountFields = {
      od_cart_price: Number(order.od_cart_price || 0),
      od_cart_coupon: Number(order.od_cart_coupon || 0),
      od_coupon: Number(order.od_coupon || 0),
      od_receipt_point: Number(order.od_receipt_point || 0),
      od_send_total: actualShippingTotal,
      od_receipt_price: Number(order.od_receipt_price || 0),
      od_misu: Number(order.od_misu || 0),
    };
    const expectedFields = {
      od_cart_price: cartTotal,
      od_cart_coupon: 0,
      od_coupon: expectedOrderCoupon,
      od_receipt_point: expectedPoint,
      od_send_total: shippingTotal,
      od_receipt_price: 0,
      od_misu: expectedReceipt,
    };
    for (const [field, expected] of Object.entries(expectedFields)) {
      if (amountFields[field] !== expected) {
        fail('order coupon/point direct order amount field mismatch', {
          field,
          expected,
          actual: amountFields[field],
          amountFields,
          expectedFields,
          order,
        });
      }
    }
    if (String(order.od_status || '') !== STATUS_ORDERED) {
      fail('order coupon/point direct order did not keep bank orders in ordered/deposit-waiting status', order);
    }
    const wrongCartStatusItems = (order.items || []).filter(
      (item) => String(item.ct_status || '') !== STATUS_ORDERED
    );
    if (wrongCartStatusItems.length > 0) {
      fail('order coupon/point cart rows did not inherit the YoungCart order status', {
        expectedStatus: STATUS_ORDERED,
        wrongCartStatusItems,
        orderItems: order.items,
      });
    }
    const itemIds = (order.items || []).map((item) => String(item.ct_id));
    if (
      itemIds.length !== directCtIds.length ||
      itemIds.some((ctId) => !directCtIds.includes(ctId))
    ) {
      fail('order coupon/point direct order included unexpected cart rows', {
        directCtIds,
        itemIds,
        orderItems: order.items,
      });
    }

    await apiJson(`/shop/orders/${orderId}`, {
      method: 'PATCH',
      headers: authHeaders(token),
      body: JSON.stringify({
        reason: 'smoke order coupon point restore',
      }),
    });
    const cancelledDetail = await apiJson(`/shop/orders/${orderId}`, {
      headers: authHeaders(token),
    });
    const cancelled = cancelledDetail.data || {};
    const cancelledZeroFields = [
      'od_receipt_price',
      'od_receipt_point',
      'od_misu',
      'od_send_cost',
      'od_send_cost2',
      'od_cart_coupon',
      'od_coupon',
      'od_send_coupon',
    ];
    const nonZeroCancelledFields = cancelledZeroFields.filter(
      (field) => Number(cancelled[field] || 0) !== 0
    );
    if (
      String(cancelled.od_status || '') !== STATUS_CANCELLED ||
      nonZeroCancelledFields.length > 0 ||
      Number(cancelled.od_cancel_price || 0) !== cartTotal
    ) {
      fail('order coupon/point cancel did not restore YoungCart amount fields', {
        nonZeroCancelledFields,
        cancelled,
        cartTotal,
      });
    }

    const coupons = await apiJson('/shop/coupons/mine', {
      headers: authHeaders(token),
    });
    if (!(coupons.data || []).some((coupon) => String(coupon.cp_id || '') === cpId)) {
      fail('order coupon was not reusable after order cancellation', {
        cpId,
        coupons: coupons.data,
      });
    }

    return {
      orderCouponPointOrderId: orderId,
      orderCouponDiscount: expectedOrderCoupon,
      orderPointUse: expectedPoint,
      orderShippingTotal: shippingTotal,
      orderReceiptPrice: expectedReceipt,
      orderCouponReusableAfterCancel: true,
    };
  } catch (error) {
    if (orderId) {
      cleanupOrders(orderId);
    }
    throw error;
  } finally {
    await cleanupCart(token).catch(() => null);
  }
}

async function verifyPaidOrderDirectCancelGuard(token, product) {
  await cleanupCart(token);

  const option = firstUsableOption(product);
  let orderId = '';

  try {
    const directAdd = await apiJson('/shop/cart', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(cartAddBody(product, option, 1, { direct: true })),
    });
    const directCtIds = cartIdsFromAddPayload(directAdd);
    if (directCtIds.length === 0) {
      fail('paid cancel guard setup did not return direct cart row ids', directAdd);
    }

    const orderPayload = await apiJson('/shop/orders', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        ct_ids: directCtIds.join(','),
        od_name: 'NextjsSmoke',
        od_tel: '02-000-0000',
        od_hp: '010-1234-5678',
        od_email: `${smokeMemberId}@example.test`,
        od_zip: '12345',
        od_addr1: 'Next.js smoke address',
        od_addr2: 'Paid cancel guard',
        od_memo: `${smokeMarker} paid-cancel-guard ${smokeRunId}`,
        od_settle_case: SETTLE_BANK,
        od_bank_account: 'smoke-bank',
        od_deposit_name: 'NextjsSmoke',
      }),
    });
    orderId = String(orderPayload.data?.od_id || orderPayload.data?.order?.od_id || '');
    if (!/^[0-9]{8,20}$/.test(orderId)) {
      fail('paid cancel guard order did not return a valid order id', orderPayload);
    }

    const marked = markSmokeOrderPaid(orderId);
    if (String(marked.status || '') !== STATUS_PAID || Number(marked.paid_amount || 0) <= 0) {
      fail('paid cancel guard helper did not mark the order as paid', marked);
    }

    const detail = await apiJson(`/shop/orders/${orderId}`, {
      headers: authHeaders(token),
    });
    const order = detail.data || {};
    if (String(order.od_status || '') !== STATUS_PAID) {
      fail('paid cancel guard order detail did not expose paid status', order);
    }
    if (order.can_cancel !== false || !String(order.cancel_block_reason || '')) {
      fail('paid cancel guard detail did not block customer cancellation', {
        can_cancel: order.can_cancel,
        cancel_block_reason: order.cancel_block_reason,
        order,
      });
    }
    const wrongCartStatusItems = (order.items || []).filter(
      (item) => String(item.ct_status || '') !== STATUS_PAID
    );
    if (wrongCartStatusItems.length > 0) {
      fail('paid cancel guard cart rows did not keep paid status', {
        expectedStatus: STATUS_PAID,
        wrongCartStatusItems,
        orderItems: order.items,
      });
    }

    await apiFailure(
      `/shop/orders/${orderId}`,
      {
        method: 'PATCH',
        headers: authHeaders(token),
        body: JSON.stringify({
          reason: 'smoke paid cancel guard',
        }),
      },
      400
    );

    const afterFailure = await apiJson(`/shop/orders/${orderId}`, {
      headers: authHeaders(token),
    });
    if (String(afterFailure.data?.od_status || '') !== STATUS_PAID) {
      fail('paid cancel guard direct PATCH changed the paid order status', afterFailure.data);
    }

    return {
      paidCancelGuardOrderId: orderId,
      paidCancelGuardBlocked: true,
      paidCancelGuardAmount: Number(marked.paid_amount || 0),
    };
  } catch (error) {
    if (orderId) {
      cleanupOrders(orderId);
    }
    throw error;
  } finally {
    await cleanupCart(token).catch(() => null);
  }
}

async function verifyReceiptAndDeliveryLinks(token, product) {
  await cleanupCart(token);

  const option = firstUsableOption(product);
  let orderId = '';

  try {
    const directAdd = await apiJson('/shop/cart', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(cartAddBody(product, option, 1, { direct: true })),
    });
    const directCtIds = cartIdsFromAddPayload(directAdd);
    if (directCtIds.length === 0) {
      fail('receipt/delivery setup did not return direct cart row ids', directAdd);
    }

    const orderPayload = await apiJson('/shop/orders', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        ct_ids: directCtIds.join(','),
        od_name: 'NextjsSmoke',
        od_tel: '02-000-0000',
        od_hp: '010-1234-5678',
        od_email: `${smokeMemberId}@example.test`,
        od_zip: '12345',
        od_addr1: 'Next.js smoke address',
        od_addr2: 'Receipt delivery links',
        od_memo: `${smokeMarker} receipt-delivery ${smokeRunId}`,
        od_settle_case: SETTLE_BANK,
        od_bank_account: 'smoke-bank',
        od_deposit_name: 'NextjsSmoke',
      }),
    });
    orderId = String(orderPayload.data?.od_id || orderPayload.data?.order?.od_id || '');
    if (!/^[0-9]{8,20}$/.test(orderId)) {
      fail('receipt/delivery order did not return a valid order id', orderPayload);
    }

    const marked = markSmokeOrderPaid(orderId, [
      '--status=shipping',
      '--with-toss-receipt',
      '--with-delivery',
    ]);
    if (
      String(marked.status || '') !== STATUS_SHIPPING ||
      !String(marked.tno || '') ||
      !String(marked.invoice || '') ||
      Number(marked.paid_amount || 0) <= 0
    ) {
      fail('receipt/delivery helper did not mark the order with receipt and delivery metadata', marked);
    }

    const detail = await apiJson(`/shop/orders/${orderId}`, {
      headers: authHeaders(token),
    });
    const order = detail.data || {};
    if (String(order.od_status || '') !== STATUS_SHIPPING) {
      fail('receipt/delivery detail did not expose shipping status', order);
    }
    if (order.can_cancel !== false || !String(order.cancel_block_reason || '')) {
      fail('receipt/delivery detail did not block customer cancellation', {
        can_cancel: order.can_cancel,
        cancel_block_reason: order.cancel_block_reason,
        order,
      });
    }

    const receiptUrl = String(order.receipt_url || order.od_payment_receipt_url || '');
    if (
      !receiptUrl.includes('dashboard.tosspayments.com/receipt/redirection') ||
      !receiptUrl.includes(encodeURIComponent(String(marked.tno)))
    ) {
      fail('receipt/delivery detail did not expose the expected Toss receipt URL', {
        receiptUrl,
        marked,
        order,
      });
    }
    if (
      String(order.od_payment_app_value || '') !== String(marked.app_no || '') ||
      !String(order.od_payment_app_label || '')
    ) {
      fail('receipt/delivery detail did not expose the YoungCart approval number fields', {
        marked,
        order,
      });
    }

    const deliveryInquiryUrl = String(
      order.delivery_inquiry_url || order.od_delivery_inquiry_url || ''
    );
    if (
      String(order.od_delivery_company || '') !== String(marked.delivery_company || '') ||
      String(order.od_invoice || '') !== String(marked.invoice || '') ||
      !String(order.od_invoice_time || '') ||
      !deliveryInquiryUrl
    ) {
      fail('receipt/delivery detail did not expose invoice and delivery inquiry fields', {
        deliveryInquiryUrl,
        marked,
        order,
      });
    }

    const wrongCartStatusItems = (order.items || []).filter(
      (item) => String(item.ct_status || '') !== STATUS_SHIPPING
    );
    if (wrongCartStatusItems.length > 0) {
      fail('receipt/delivery cart rows did not inherit shipping status', {
        expectedStatus: STATUS_SHIPPING,
        wrongCartStatusItems,
        orderItems: order.items,
      });
    }

    return {
      receiptDeliveryOrderId: orderId,
      receiptUrlExposed: true,
      deliveryInquiryExposed: true,
      deliveryStatus: STATUS_SHIPPING,
    };
  } catch (error) {
    if (orderId) {
      cleanupOrders(orderId);
    }
    throw error;
  } finally {
    await cleanupCart(token).catch(() => null);
  }
}

async function verifyCashReceiptLink(token, product) {
  await cleanupCart(token);

  const option = firstUsableOption(product);
  let orderId = '';

  try {
    const directAdd = await apiJson('/shop/cart', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(cartAddBody(product, option, 1, { direct: true })),
    });
    const directCtIds = cartIdsFromAddPayload(directAdd);
    if (directCtIds.length === 0) {
      fail('cash receipt setup did not return direct cart row ids', directAdd);
    }

    const orderPayload = await apiJson('/shop/orders', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        ct_ids: directCtIds.join(','),
        od_name: 'NextjsSmoke',
        od_tel: '02-000-0000',
        od_hp: '010-1234-5678',
        od_email: `${smokeMemberId}@example.test`,
        od_zip: '12345',
        od_addr1: 'Next.js smoke address',
        od_addr2: 'Cash receipt link',
        od_memo: `${smokeMarker} cash-receipt ${smokeRunId}`,
        od_settle_case: SETTLE_BANK,
        od_bank_account: 'smoke-bank',
        od_deposit_name: 'NextjsSmoke',
        od_cash_request: true,
      }),
    });
    orderId = String(orderPayload.data?.od_id || orderPayload.data?.order?.od_id || '');
    if (!/^[0-9]{8,20}$/.test(orderId)) {
      fail('cash receipt order did not return a valid order id', orderPayload);
    }

    const marked = markSmokeOrderPaid(orderId, ['--with-toss-cash-receipt']);
    if (
      String(marked.status || '') !== STATUS_PAID ||
      !String(marked.cash_no || '') ||
      !String(marked.cash_receipt_url || '') ||
      Number(marked.paid_amount || 0) <= 0
    ) {
      fail('cash receipt helper did not mark the order with issued cash receipt metadata', marked);
    }

    const detail = await apiJson(`/shop/orders/${orderId}`, {
      headers: authHeaders(token),
    });
    const order = detail.data || {};
    const cashReceiptUrl = String(order.cash_receipt_url || order.od_cash_receipt_url || '');
    const issueUrl = String(order.cash_receipt_issue_url || order.od_cash_receipt_issue_url || '');

    if (String(order.od_status || '') !== STATUS_PAID) {
      fail('cash receipt detail did not expose paid status', order);
    }
    if (
      Number(order.od_cash || 0) !== 1 ||
      String(order.od_cash_no || '') !== String(marked.cash_no || '') ||
      !String(order.od_cash_info || '').includes(String(marked.cash_no || ''))
    ) {
      fail('cash receipt detail did not expose issued cash receipt fields', {
        marked,
        order,
      });
    }
    if (cashReceiptUrl !== String(marked.cash_receipt_url || '')) {
      fail('cash receipt detail did not expose the expected issued receipt URL', {
        expected: marked.cash_receipt_url,
        actual: cashReceiptUrl,
        order,
      });
    }
    if (issueUrl) {
      fail('cash receipt detail exposed an issue URL even though a cash receipt was already issued', {
        issueUrl,
        order,
      });
    }
    if (order.can_cancel !== false || !String(order.cancel_block_reason || '')) {
      fail('cash receipt paid detail did not block customer cancellation', {
        can_cancel: order.can_cancel,
        cancel_block_reason: order.cancel_block_reason,
        order,
      });
    }

    return {
      cashReceiptOrderId: orderId,
      cashReceiptUrlExposed: true,
      cashReceiptNo: String(marked.cash_no || ''),
    };
  } catch (error) {
    if (orderId) {
      cleanupOrders(orderId);
    }
    throw error;
  } finally {
    await cleanupCart(token).catch(() => null);
  }
}

async function verifyCartRowCouponDirect(token, product, config) {
  await cleanupCart(token);
  cleanupCartCoupon(config.subject);

  const option = firstUsableOption(product);
  let orderId = '';
  let cpId = '';

  try {
    const directAdd = await apiJson('/shop/cart', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(cartAddBody(product, option, 1, { direct: true })),
    });
    const directCtIds = cartIdsFromAddPayload(directAdd);
    if (directCtIds.length === 0) {
      fail(`${config.label} cart coupon setup did not return direct cart row ids`, directAdd);
    }
    const ctId = directCtIds[0];

    const directRows = await currentCartRows(
      token,
      `?ct_ids=${encodeURIComponent(directCtIds.join(','))}`
    );
    const row = directRows.find((item) => String(item.ct_id) === String(ctId));
    if (!row) {
      fail(`${config.label} cart coupon setup could not read the direct cart row`, {
        ctId,
        directRows,
      });
    }
    const cartTotal = directRows.reduce((sum, item) => sum + Number(item.line_total || 0), 0);
    const rowTotal = Number(row.line_total || 0);
    if (cartTotal <= 0 || rowTotal <= 0) {
      fail(`${config.label} cart coupon setup did not produce a positive row total`, {
        cartTotal,
        row,
      });
    }

    const couponPrice = Math.max(1, Math.min(config.price, Math.floor(rowTotal / 3)));
    const zone = seedCartCouponZone(config.subject, config.method, config.target, couponPrice);
    const download = await apiJson('/shop/coupons/download', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ cz_id: zone.cz_id }),
    });
    cpId = String(download.data?.cp_id || '');
    if (!cpId) {
      fail(`${config.label} cart coupon download did not return a coupon id`, download);
    }

    const applicable = await apiJson(
      `/shop/coupons/applicable?ct_id=${encodeURIComponent(ctId)}`,
      {
        headers: authHeaders(token),
      }
    );
    const match = (applicable.data || []).find((coupon) => String(coupon.cp_id) === cpId);
    if (!match || Number(match.discount || 0) !== couponPrice) {
      fail(`${config.label} cart coupon applicable API did not expose the expected coupon`, {
        cpId,
        couponPrice,
        applicable: applicable.data,
      });
    }

    const applied = await apiJson('/shop/coupons/apply-to-cart', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ ct_id: Number(ctId), cp_id: cpId }),
    });
    if (Number(applied.data?.discount || 0) !== couponPrice) {
      fail(`${config.label} cart coupon apply did not return the expected discount`, applied);
    }

    const couponRows = await currentCartRows(
      token,
      `?ct_ids=${encodeURIComponent(directCtIds.join(','))}`
    );
    const couponRow = couponRows.find((item) => String(item.ct_id) === String(ctId));
    if (
      !couponRow ||
      String(couponRow.cp_id || '') !== cpId ||
      Number(couponRow.cp_price || 0) !== couponPrice
    ) {
      fail(`${config.label} cart coupon was not persisted on the cart row`, {
        cpId,
        couponPrice,
        couponRows,
      });
    }

    const quote = await apiJson(
      `/shop/shipping/quote?ct_ids=${encodeURIComponent(directCtIds.join(','))}`,
      {
        headers: authHeaders(token),
      }
    );
    const shippingTotal = Number(quote.data?.total || 0);
    const expectedReceipt = Math.max(0, cartTotal + shippingTotal - couponPrice);

    const orderPayload = await apiJson('/shop/orders', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        ct_ids: directCtIds.join(','),
        od_name: 'NextjsSmoke',
        od_tel: '02-000-0000',
        od_hp: '010-1234-5678',
        od_email: `${smokeMemberId}@example.test`,
        od_zip: '12345',
        od_addr1: 'Next.js smoke address',
        od_addr2: `${config.label} cart coupon direct`,
        od_memo: `${smokeMarker} ${config.key}-cart-coupon ${smokeRunId}`,
        od_settle_case: SETTLE_BANK,
        od_bank_account: 'smoke-bank',
        od_deposit_name: 'NextjsSmoke',
      }),
    });
    orderId = String(orderPayload.data?.od_id || orderPayload.data?.order?.od_id || '');
    if (!/^[0-9]{8,20}$/.test(orderId)) {
      fail(`${config.label} cart coupon direct order did not return a valid order id`, orderPayload);
    }

    const detail = await apiJson(`/shop/orders/${orderId}`, {
      headers: authHeaders(token),
    });
    const order = detail.data || {};
    const actualShippingTotal =
      Number(order.od_send_cost || 0) + Number(order.od_send_cost2 || 0);
    const amountFields = {
      od_cart_price: Number(order.od_cart_price || 0),
      od_cart_coupon: Number(order.od_cart_coupon || 0),
      od_coupon: Number(order.od_coupon || 0),
      od_receipt_point: Number(order.od_receipt_point || 0),
      od_send_total: actualShippingTotal,
      od_receipt_price: Number(order.od_receipt_price || 0),
      od_misu: Number(order.od_misu || 0),
    };
    const expectedFields = {
      od_cart_price: cartTotal,
      od_cart_coupon: couponPrice,
      od_coupon: 0,
      od_receipt_point: 0,
      od_send_total: shippingTotal,
      od_receipt_price: 0,
      od_misu: expectedReceipt,
    };
    for (const [field, expected] of Object.entries(expectedFields)) {
      if (amountFields[field] !== expected) {
        fail(`${config.label} cart coupon order amount field mismatch`, {
          field,
          expected,
          actual: amountFields[field],
          amountFields,
          expectedFields,
          order,
        });
      }
    }

    const usedListing = await apiJson('/shop/coupons', {
      headers: authHeaders(token),
    });
    const usedCoupon = (usedListing.data || []).find((coupon) => String(coupon.cp_id || '') === cpId);
    if (!usedCoupon || String(usedCoupon.cp_used || '') === '') {
      fail(`${config.label} cart coupon was not marked used immediately after order`, {
        cpId,
        coupons: usedListing.data,
      });
    }

    await apiJson(`/shop/orders/${orderId}`, {
      method: 'PATCH',
      headers: authHeaders(token),
      body: JSON.stringify({
        reason: `smoke ${config.key} cart coupon restore`,
      }),
    });
    const cancelledDetail = await apiJson(`/shop/orders/${orderId}`, {
      headers: authHeaders(token),
    });
    const cancelled = cancelledDetail.data || {};
    if (
      String(cancelled.od_status || '') !== STATUS_CANCELLED ||
      Number(cancelled.od_cart_coupon || 0) !== 0 ||
      Number(cancelled.od_receipt_price || 0) !== 0 ||
      Number(cancelled.od_cancel_price || 0) !== cartTotal
    ) {
      fail(`${config.label} cart coupon cancel did not restore YoungCart fields`, {
        cartTotal,
        cancelled,
      });
    }

    const restoredListing = await apiJson('/shop/coupons', {
      headers: authHeaders(token),
    });
    const restoredCoupon = (restoredListing.data || []).find(
      (coupon) => String(coupon.cp_id || '') === cpId
    );
    if (!restoredCoupon || String(restoredCoupon.cp_used || '') !== '') {
      fail(`${config.label} cart coupon was not restored after cancellation`, {
        cpId,
        coupons: restoredListing.data,
      });
    }

    return {
      [`${config.key}CartCouponOrderId`]: orderId,
      [`${config.key}CartCouponDiscount`]: couponPrice,
      [`${config.key}CartCouponReceipt`]: expectedReceipt,
      [`${config.key}CartCouponReusableAfterCancel`]: true,
    };
  } catch (error) {
    if (orderId) {
      cleanupOrders(orderId);
    }
    throw error;
  } finally {
    await cleanupCart(token).catch(() => null);
  }
}

async function verifyCartRowCouponPaymentPrepareCancel(token, product, config) {
  await cleanupCart(token);
  cleanupCartCoupon(config.subject);

  const option = firstUsableOption(product);
  let orderId = '';
  let cpId = '';

  try {
    const directAdd = await apiJson('/shop/cart', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(cartAddBody(product, option, 1, { direct: true })),
    });
    const directCtIds = cartIdsFromAddPayload(directAdd);
    if (directCtIds.length === 0) {
      fail(`${config.label} payment cart coupon setup did not return direct cart row ids`, directAdd);
    }
    const ctId = directCtIds[0];

    const directRows = await currentCartRows(
      token,
      `?ct_ids=${encodeURIComponent(directCtIds.join(','))}`
    );
    const row = directRows.find((item) => String(item.ct_id) === String(ctId));
    const cartTotal = directRows.reduce((sum, item) => sum + Number(item.line_total || 0), 0);
    const rowTotal = Number(row?.line_total || 0);
    if (!row || cartTotal <= 0 || rowTotal <= 0) {
      fail(`${config.label} payment cart coupon setup did not produce a positive row total`, {
        ctId,
        cartTotal,
        directRows,
      });
    }

    const couponPrice = Math.max(1, Math.min(config.price, Math.floor(rowTotal / 3)));
    const zone = seedCartCouponZone(config.subject, config.method, config.target, couponPrice);
    const download = await apiJson('/shop/coupons/download', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ cz_id: zone.cz_id }),
    });
    cpId = String(download.data?.cp_id || '');
    if (!cpId) {
      fail(`${config.label} payment cart coupon download did not return a coupon id`, download);
    }

    const applicable = await apiJson(
      `/shop/coupons/applicable?ct_id=${encodeURIComponent(ctId)}`,
      { headers: authHeaders(token) }
    );
    const match = (applicable.data || []).find((coupon) => String(coupon.cp_id) === cpId);
    if (!match || Number(match.discount || 0) !== couponPrice) {
      fail(`${config.label} payment applicable API did not expose the expected cart coupon`, {
        cpId,
        couponPrice,
        applicable: applicable.data,
      });
    }

    await apiJson('/shop/coupons/apply-to-cart', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ ct_id: Number(ctId), cp_id: cpId }),
    });

    const couponRows = await currentCartRows(
      token,
      `?ct_ids=${encodeURIComponent(directCtIds.join(','))}`
    );
    const couponRow = couponRows.find((item) => String(item.ct_id) === String(ctId));
    if (
      !couponRow ||
      String(couponRow.cp_id || '') !== cpId ||
      Number(couponRow.cp_price || 0) !== couponPrice
    ) {
      fail(`${config.label} payment cart coupon was not persisted before prepare`, {
        cpId,
        couponPrice,
        couponRows,
      });
    }

    const quote = await apiJson(
      `/shop/shipping/quote?ct_ids=${encodeURIComponent(directCtIds.join(','))}`,
      { headers: authHeaders(token) }
    );
    const shippingTotal = Number(quote.data?.total || 0);
    const expectedReceipt = Math.max(0, cartTotal + shippingTotal - couponPrice);

    const prepared = await apiJson('/shop/payment/prepare', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        ct_ids: directCtIds.join(','),
        od_name: 'NextjsSmoke',
        od_tel: '02-000-0000',
        od_hp: '010-1234-5678',
        od_email: `${smokeMemberId}@example.test`,
        od_zip: '12345',
        od_addr1: 'Next.js smoke address',
        od_addr2: `${config.label} payment cart coupon`,
        od_memo: `${smokeMarker} ${config.key}-payment-cart-coupon ${smokeRunId}`,
        od_settle_case: SETTLE_CARD,
      }),
    });
    orderId = String(prepared.data?.order_id || '');
    const amount = Number(prepared.data?.amount || 0);
    if (!/^[0-9]{8,20}$/.test(orderId) || amount !== expectedReceipt) {
      fail(`${config.label} payment prepare did not return the expected cart coupon amount`, {
        orderId,
        amount,
        expectedReceipt,
        prepared: prepared.data,
      });
    }

    const preparedDetail = await apiJson(`/shop/orders/${orderId}`, {
      headers: authHeaders(token),
    });
    const preparedOrder = preparedDetail.data || {};
    const preparedShippingTotal =
      Number(preparedOrder.od_send_cost || 0) + Number(preparedOrder.od_send_cost2 || 0);
    if (
      Number(preparedOrder.od_cart_price || 0) !== cartTotal ||
      Number(preparedOrder.od_cart_coupon || 0) !== couponPrice ||
      Number(preparedOrder.od_receipt_price || 0) !== expectedReceipt ||
      preparedShippingTotal !== shippingTotal
    ) {
      fail(`${config.label} prepared payment order did not persist cart coupon totals`, {
        cartTotal,
        couponPrice,
        shippingTotal,
        expectedReceipt,
        preparedOrder,
      });
    }

    const listingBeforeCancel = await apiJson('/shop/coupons', {
      headers: authHeaders(token),
    });
    const couponBeforeCancel = (listingBeforeCancel.data || []).find(
      (coupon) => String(coupon.cp_id || '') === cpId
    );
    if (!couponBeforeCancel || String(couponBeforeCancel.cp_used || '') !== '') {
      fail(`${config.label} cart coupon was marked used before PG confirmation`, {
        cpId,
        coupons: listingBeforeCancel.data,
      });
    }

    const cancelled = await apiJson('/shop/payment/cancel', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        order_id: orderId,
        reason: `smoke ${config.key} payment cart coupon restore`,
      }),
    });
    if (String(cancelled.data?.status || '') !== STATUS_CANCELLED) {
      fail(`${config.label} payment cart coupon cancel did not return cancelled status`, cancelled);
    }

    const cancelledDetail = await apiJson(`/shop/orders/${orderId}`, {
      headers: authHeaders(token),
    });
    const cancelledOrder = cancelledDetail.data || {};
    const cancelledZeroFields = [
      'od_receipt_price',
      'od_receipt_point',
      'od_misu',
      'od_send_cost',
      'od_send_cost2',
      'od_cart_coupon',
      'od_coupon',
      'od_send_coupon',
    ];
    const nonZeroCancelledFields = cancelledZeroFields.filter(
      (field) => Number(cancelledOrder[field] || 0) !== 0
    );
    if (
      String(cancelledOrder.od_status || '') !== STATUS_CANCELLED ||
      nonZeroCancelledFields.length > 0 ||
      Number(cancelledOrder.od_cancel_price || 0) !== cartTotal
    ) {
      fail(`${config.label} payment cart coupon cancel did not reset YoungCart amount fields`, {
        nonZeroCancelledFields,
        cartTotal,
        cancelledOrder,
      });
    }

    const restoredRows = await currentCartRows(
      token,
      `?ct_ids=${encodeURIComponent(directCtIds.join(','))}`
    );
    const restoredRow = restoredRows.find((item) => String(item.ct_id) === String(ctId));
    if (
      !restoredRow ||
      String(restoredRow.cp_id || '') !== cpId ||
      Number(restoredRow.cp_price || 0) !== couponPrice
    ) {
      fail(`${config.label} payment cancel did not restore the coupon-bound direct cart row`, {
        cpId,
        couponPrice,
        restoredRows,
      });
    }

    const listingAfterCancel = await apiJson('/shop/coupons', {
      headers: authHeaders(token),
    });
    const couponAfterCancel = (listingAfterCancel.data || []).find(
      (coupon) => String(coupon.cp_id || '') === cpId
    );
    if (!couponAfterCancel || String(couponAfterCancel.cp_used || '') !== '') {
      fail(`${config.label} cart coupon was not available after payment cancellation`, {
        cpId,
        coupons: listingAfterCancel.data,
      });
    }

    return {
      [`${config.key}PaymentCouponOrderId`]: orderId,
      [`${config.key}PaymentCouponDiscount`]: couponPrice,
      [`${config.key}PaymentCouponAmount`]: expectedReceipt,
      [`${config.key}PaymentCouponCartRestored`]: true,
    };
  } catch (error) {
    if (orderId) {
      cleanupOrders(orderId);
    }
    throw error;
  } finally {
    await cleanupCart(token).catch(() => null);
  }
}

async function fillOrderForm(page) {
  const form = page.locator('form').last();
  await form.waitFor({ state: 'visible', timeout: 10000 });

  const sections = form.locator('section');
  const sectionCount = await sections.count();
  if (sectionCount < 4) {
    const bodyText = await page.locator('body').innerText({ timeout: 3000 }).catch(() => '');
    fail('order form did not render the expected sections', {
      url: page.url(),
      sectionCount,
      body: bodyText.slice(0, 1200),
    });
  }

  const ordererSection = sections.nth(1);
  const ordererInputs = ordererSection.locator('input');
  const ordererInputCount = await ordererInputs.count();
  if (ordererInputCount < 8) {
    fail('orderer section did not render the expected inputs', {
      url: page.url(),
      sectionCount,
      ordererInputCount,
      ordererText: await ordererSection.innerText({ timeout: 3000 }).catch(() => ''),
    });
  }

  await ordererInputs.nth(0).fill('NextjsSmoke');
  await ordererInputs.nth(1).fill('02-000-0000');
  await ordererInputs.nth(2).fill('010-1234-5678');
  await ordererInputs.nth(3).fill('12345');
  await ordererInputs.nth(4).fill('Next.js smoke address');
  await ordererInputs.nth(5).fill('Order browser flow');
  await ordererInputs.nth(6).fill(smokeMarker);
  await ordererInputs.nth(7).fill(`${smokeMemberId}@example.test`);

  const recipientSection = sections.nth(2);
  await recipientSection.locator('textarea').first().fill(`${smokeMarker} ${smokeRunId}`);

  const paymentSection = sections.nth(3);
  const bankSelect = paymentSection.locator('select').first();
  if ((await bankSelect.count()) === 0) {
    fail('bank account selector was not rendered on the order page');
  }
  const firstBankValue = await bankSelect.evaluate((select) => {
    const option = Array.from(select.options).find((item) => item.value);
    return option?.value || '';
  });
  if (!firstBankValue) {
    fail('local payment config has no bank account for bank transfer orders');
  }
  await bankSelect.selectOption(firstBankValue);
  await paymentSection.locator('input[type="text"]').first().fill('NextjsSmoke');

  const agreementSection = sections.last();
  await agreementSection.locator('input[type="checkbox"]').first().check();
}

function orderIdFromPageUrl(page) {
  return new URL(page.url()).pathname.split('/').filter(Boolean).pop() || '';
}

function expectedYoungCartOrderTotal(order) {
  return Math.max(
    0,
    Number(order?.od_cart_price || 0) +
      Number(order?.od_send_cost || 0) +
      Number(order?.od_send_cost2 || 0) -
      Number(order?.od_cart_coupon || 0) -
      Number(order?.od_coupon || 0) -
      Number(order?.od_send_coupon || 0) -
      Number(order?.od_cancel_price || 0)
  );
}

function assertYoungCartOrderTotals(order, label) {
  const expectedTotal = expectedYoungCartOrderTotal(order);
  const expectedReceiptTotal =
    Number(order?.od_receipt_price || 0) + Number(order?.od_receipt_point || 0);
  const expectedMisu = Math.max(0, expectedTotal - expectedReceiptTotal);

  if (Number(order?.od_total_price || 0) !== expectedTotal) {
    fail(`${label} did not expose the YoungCart total price formula`, {
      expectedTotal,
      actual: Number(order?.od_total_price || 0),
      order,
    });
  }
  if (Number(order?.od_receipt_total || 0) !== expectedReceiptTotal) {
    fail(`${label} did not expose the YoungCart receipt total`, {
      expectedReceiptTotal,
      actual: Number(order?.od_receipt_total || 0),
      order,
    });
  }
  if (Number(order?.od_misu_price || 0) !== expectedMisu) {
    fail(`${label} did not expose the YoungCart unpaid amount`, {
      expectedMisu,
      actual: Number(order?.od_misu_price || 0),
      order,
    });
  }
}

function assertYoungCartOrderListRow(row, detailOrder, label) {
  const expectedListPrice =
    Number(detailOrder?.od_cart_price || 0) +
    Number(detailOrder?.od_send_cost || 0) +
    Number(detailOrder?.od_send_cost2 || 0);
  const expectedItemCount = Number(
    detailOrder?.od_cart_count || detailOrder?.items?.length || 0
  );

  if (Number(row?.od_list_price ?? row?.od_order_price ?? 0) !== expectedListPrice) {
    fail(`${label} did not expose the YoungCart order list amount`, {
      expectedListPrice,
      row,
      detailOrder,
    });
  }
  if (Number(row?.od_receipt_price || 0) !== Number(detailOrder?.od_receipt_price || 0)) {
    fail(`${label} did not expose the YoungCart paid amount`, {
      row,
      detailOrder,
    });
  }
  if (Number(row?.od_misu || 0) !== Number(detailOrder?.od_misu || 0)) {
    fail(`${label} did not expose the YoungCart unpaid amount`, {
      row,
      detailOrder,
    });
  }
  if (Number(row?.od_cart_count || row?.item_count || 0) !== expectedItemCount) {
    fail(`${label} did not expose the YoungCart cart count`, {
      expectedItemCount,
      row,
      detailOrder,
    });
  }
}

async function createOrderInBrowser(page, token, product) {
  await page.goto(`${appUrl}/shop/order`, { waitUntil: 'networkidle' });
  await page.getByText(product.it_name, { exact: false }).first().waitFor({
    state: 'visible',
    timeout: 10000,
  });
  if (!new URL(page.url()).pathname.startsWith('/shop/order')) {
    const bodyText = await page.locator('body').innerText({ timeout: 3000 }).catch(() => '');
    fail('order page redirected before the order form was usable', {
      url: page.url(),
      body: bodyText.slice(0, 1200),
    });
  }
  await fillOrderForm(page);

  const observedResponses = [];
  const recordResponse = (response) => {
    const request = response.request();
    if (request.method() === 'POST' && response.url().includes('/shop/')) {
      observedResponses.push({
        status: response.status(),
        url: response.url(),
      });
    }
  };
  page.on('response', recordResponse);

  let orderResponse = null;
  try {
    [orderResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().replace(/\/+$/, '').endsWith('/shop/orders') &&
          response.request().method() === 'POST'
      ),
      page.locator('form button[type="submit"]').last().click(),
    ]);
  } catch (error) {
    const invalidFields = await page.evaluate(() =>
      Array.from(document.querySelectorAll('form input, form select, form textarea'))
        .filter((element) => 'checkValidity' in element && !element.checkValidity())
        .map((element) => ({
          tag: element.tagName.toLowerCase(),
          name: element.getAttribute('name') || '',
          id: element.id || '',
          type: element.getAttribute('type') || '',
          value: 'value' in element ? String(element.value || '') : '',
          message: 'validationMessage' in element ? element.validationMessage : '',
        }))
    );
    const bodyText = await page.locator('body').innerText({ timeout: 3000 }).catch(() => '');
    fail('order create did not post to /shop/orders before timeout', {
      message: error.message,
      url: page.url(),
      observedResponses,
      invalidFields,
      body: bodyText.slice(0, 1600),
    });
  } finally {
    page.off('response', recordResponse);
  }

  await assertOkResponse(orderResponse, 'order create');
  await page.waitForURL(new RegExp('/shop/orders/[0-9]+$'), { timeout: 10000 });

  const orderId = orderIdFromPageUrl(page);
  if (!/^[0-9]{8,20}$/.test(orderId)) {
    fail('order create did not navigate to an order detail URL', { url: page.url() });
  }

  const detail = await apiJson(`/shop/orders/${orderId}`, {
    headers: authHeaders(token),
  });
  const order = detail.data;
  if (order?.mb_id !== smokeMemberId || order?.od_status !== STATUS_ORDERED) {
    fail('created order detail did not persist expected member/status', order);
  }
  if (!String(order?.od_memo || '').includes(smokeMarker)) {
    fail('created order is missing the smoke cleanup marker', order);
  }
  const taxTotal =
    Number(order?.od_tax_mny || 0) +
    Number(order?.od_vat_mny || 0) +
    Number(order?.od_free_mny || 0);
  const expectedTaxBase =
    Number(order?.od_receipt_price || 0) + Number(order?.od_misu || 0);
  if (taxTotal !== expectedTaxBase) {
    fail('created order did not persist YoungCart tax amount fields', {
      taxTotal,
      expectedTaxBase,
      receiptPrice: Number(order?.od_receipt_price || 0),
      misu: Number(order?.od_misu || 0),
      order,
    });
  }
  assertYoungCartOrderTotals(order, 'created order detail');
  const item = (order.items || []).find((row) => String(row.it_id) === product.it_id);
  if (!item || item.ct_status !== STATUS_ORDERED) {
    fail('created order items did not inherit the YoungCart order status', {
      expectedStatus: STATUS_ORDERED,
      orderItems: order.items,
    });
  }
  if (order.can_cancel !== true || String(order.cancel_block_reason || '') !== '') {
    fail('created order detail did not expose YoungCart customer cancel availability', order);
  }
  const list = await apiJson('/shop/orders?per_page=50', {
    headers: authHeaders(token),
  });
  const listRow = (list.data || []).find((row) => String(row.od_id) === String(orderId));
  if (!listRow) {
    fail('created order did not appear in the YoungCart order list API', list.data);
  }
  assertYoungCartOrderListRow(listRow, order, 'created order list row');

  return orderId;
}

async function cancelOrderInBrowser(page, token, orderId) {
  const beforeCancel = await apiJson(`/shop/orders/${orderId}`, {
    headers: authHeaders(token),
  });
  if (beforeCancel.data?.can_cancel !== true) {
    fail('cancellable order API did not expose can_cancel=true before browser cancellation', beforeCancel.data);
  }

  await page.goto(`${appUrl}/shop/orders/${orderId}`, { waitUntil: 'networkidle' });
  const statusSectionButtons = page.locator('section').first().locator('button');
  if ((await statusSectionButtons.count()) < 2) {
    fail('order detail did not render a cancel button for a cancellable order', {
      orderId,
      url: page.url(),
    });
  }

  const observedResponses = [];
  const recordResponse = (response) => {
    const request = response.request();
    if (request.method() === 'PATCH' && response.url().includes('/shop/orders')) {
      observedResponses.push({
        status: response.status(),
        url: response.url(),
      });
    }
  };
  const handleDialog = async (dialog) => {
    if (dialog.type() === 'prompt') {
      await dialog.accept('Nextjs smoke cancel');
      return;
    }
    await dialog.accept();
  };
  page.on('response', recordResponse);
  page.on('dialog', handleDialog);

  let cancelResponse = null;
  try {
    [cancelResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().includes(`/shop/orders/${orderId}`) &&
          response.request().method() === 'PATCH'
      ),
      statusSectionButtons.last().click(),
    ]);
  } catch (error) {
    const buttonTexts = await statusSectionButtons
      .evaluateAll((buttons) => buttons.map((button) => button.textContent?.trim() || ''))
      .catch(() => []);
    const bodyText = await page.locator('body').innerText({ timeout: 3000 }).catch(() => '');
    fail('order cancel did not patch the order before timeout', {
      message: error.message,
      orderId,
      url: page.url(),
      observedResponses,
      buttonTexts,
      body: bodyText.slice(0, 1600),
    });
  } finally {
    page.off('dialog', handleDialog);
    page.off('response', recordResponse);
  }
  await assertOkResponse(cancelResponse, 'order cancel');

  const detail = await apiJson(`/shop/orders/${orderId}`, {
    headers: authHeaders(token),
  });
  const order = detail.data;
  if (order?.od_status !== STATUS_CANCELLED) {
    fail('order cancel did not persist the cancelled order status', order);
  }
  if (order?.can_cancel !== false || !String(order?.cancel_block_reason || '').trim()) {
    fail('cancelled order detail did not expose a non-cancellable state', order);
  }
  const cancelledZeroFields = [
    'od_receipt_price',
    'od_receipt_point',
    'od_misu',
    'od_send_cost',
    'od_send_cost2',
    'od_cart_coupon',
    'od_coupon',
    'od_send_coupon',
  ];
  const nonZeroCancelledFields = cancelledZeroFields.filter(
    (field) => Number(order?.[field] || 0) !== 0
  );
  if (nonZeroCancelledFields.length > 0) {
    fail('order cancel did not reset YoungCart cancellation amount fields', {
      fields: nonZeroCancelledFields,
      order,
    });
  }
  if (Number(order?.od_cancel_price || 0) !== Number(order?.od_cart_price || 0)) {
    fail('order cancel did not persist YoungCart cancellation price', order);
  }
  assertYoungCartOrderTotals(order, 'cancelled order detail');
  const notCancelled = (order.items || []).filter(
    (item) => item.ct_status !== STATUS_CANCELLED
  );
  if (notCancelled.length > 0) {
    fail('order cancel did not persist cancelled item statuses', notCancelled);
  }
  const stockUseRows = (order.items || []).filter(
    (item) => Number(item.ct_stock_use ?? 0) !== 0
  );
  if (stockUseRows.length > 0) {
    fail('order cancel did not clear cart stock-use flags', stockUseRows);
  }

  return {
    orderId,
    cancelled: true,
  };
}

let browser = null;
let credentials = null;
let exitCode = 0;
let createdOrderId = '';
let createdDirectOrderId = '';
let createdGuestOrderId = '';
let createdGuestPreparedOrderId = '';
let preparedCancelOrderId = '';
let preparedRefreshOrderId = '';
let preparedKcpOrderId = '';
let sendCouponOrderId = '';
let orderCouponPointOrderId = '';
let paidCancelGuardOrderId = '';
let receiptDeliveryOrderId = '';
let cashReceiptOrderId = '';
let productCartCouponOrderId = '';
let categoryCartCouponOrderId = '';
let productPaymentCouponOrderId = '';
let categoryPaymentCouponOrderId = '';

try {
  runPhp('seed_nextjs_smoke_user.php');
  cleanupOrders();
  credentials = await login();
  const product = await getProduct();
  await cleanupCart(credentials.token);
  const crossSiteCookieResult = await verifyCrossSiteGuestCookiePolicy(product);
  const stockRevalidationResult = await verifyOrderStockRevalidation(credentials.token, product);
  const directScopeResult = await verifyDirectBuyScope(credentials.token, product);
  createdDirectOrderId = directScopeResult.directOrderId;
  const guestLookupResult = await verifyGuestOrderLookup(product);
  createdGuestOrderId = guestLookupResult.guestOrderId;
  const guestPaymentResult = await verifyGuestPaymentPrepareCancel(product);
  createdGuestPreparedOrderId = guestPaymentResult.guestPreparedOrderId;
  const preparedRestoreResult = await verifyPreparedPaymentRestore(credentials.token, product);
  preparedCancelOrderId = preparedRestoreResult.preparedOrderId;
  preparedRefreshOrderId = preparedRestoreResult.refreshOrderId;
  preparedKcpOrderId = preparedRestoreResult.kcpOrderId;
  const sendCouponResult = await verifySendCouponPrepare(credentials.token, product);
  sendCouponOrderId = sendCouponResult.sendCouponOrderId;
  const orderCouponPointResult = await verifyOrderCouponPointDirect(credentials.token, product);
  orderCouponPointOrderId = orderCouponPointResult.orderCouponPointOrderId;
  const paidCancelGuardResult = await verifyPaidOrderDirectCancelGuard(credentials.token, product);
  paidCancelGuardOrderId = paidCancelGuardResult.paidCancelGuardOrderId;
  const receiptDeliveryResult = await verifyReceiptAndDeliveryLinks(credentials.token, product);
  receiptDeliveryOrderId = receiptDeliveryResult.receiptDeliveryOrderId;
  const cashReceiptResult = await verifyCashReceiptLink(credentials.token, product);
  cashReceiptOrderId = cashReceiptResult.cashReceiptOrderId;
  const productCartCouponResult = await verifyCartRowCouponDirect(credentials.token, product, {
    key: 'product',
    label: 'product',
    subject: itemCouponSubject,
    method: 0,
    target: String(product.it_id || ''),
    price: 1500,
  });
  productCartCouponOrderId = productCartCouponResult.productCartCouponOrderId;
  const categoryTarget = String(product.ca_id || product.category?.ca_id || '');
  if (!categoryTarget) {
    fail('smoke product has no category id for category coupon checks', product);
  }
  const categoryCartCouponResult = await verifyCartRowCouponDirect(credentials.token, product, {
    key: 'category',
    label: 'category',
    subject: categoryCouponSubject,
    method: 1,
    target: categoryTarget,
    price: 1200,
  });
  categoryCartCouponOrderId = categoryCartCouponResult.categoryCartCouponOrderId;
  const productPaymentCouponResult = await verifyCartRowCouponPaymentPrepareCancel(
    credentials.token,
    product,
    {
      key: 'product',
      label: 'product',
      subject: itemPaymentCouponSubject,
      method: 0,
      target: String(product.it_id || ''),
      price: 1400,
    }
  );
  productPaymentCouponOrderId = productPaymentCouponResult.productPaymentCouponOrderId;
  const categoryPaymentCouponResult = await verifyCartRowCouponPaymentPrepareCancel(
    credentials.token,
    product,
    {
      key: 'category',
      label: 'category',
      subject: categoryPaymentCouponSubject,
      method: 1,
      target: categoryTarget,
      price: 1100,
    }
  );
  categoryPaymentCouponOrderId = categoryPaymentCouponResult.categoryPaymentCouponOrderId;
  await cleanupCart(credentials.token);
  const setup = await setupCartForOrder(credentials.token, product);

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
  createdOrderId = await createOrderInBrowser(page, credentials.token, product);
  const cancelResult = await cancelOrderInBrowser(page, credentials.token, createdOrderId);
  await context.close();

  console.table([
    { productId: product.it_id, ...crossSiteCookieResult },
    { productId: product.it_id, ...stockRevalidationResult },
    { productId: product.it_id, ...directScopeResult },
    { productId: product.it_id, ...guestLookupResult },
    { productId: product.it_id, ...guestPaymentResult },
    { productId: product.it_id, ...preparedRestoreResult },
    { productId: product.it_id, ...sendCouponResult },
    { productId: product.it_id, ...orderCouponPointResult },
    { productId: product.it_id, ...paidCancelGuardResult },
    { productId: product.it_id, ...receiptDeliveryResult },
    { productId: product.it_id, ...cashReceiptResult },
    { productId: product.it_id, ...productCartCouponResult },
    { productId: product.it_id, ...categoryCartCouponResult },
    { productId: product.it_id, ...productPaymentCouponResult },
    { productId: product.it_id, ...categoryPaymentCouponResult },
    { productId: product.it_id, cartId: setup.ctId, ...cancelResult },
  ]);
  console.log(`[check-local-order-actions] app=${appUrl}`);
  console.log(`[check-local-order-actions] api=${expectedApiUrl}`);
} catch (error) {
  printFailure(error);
  exitCode = 1;
} finally {
  if (browser) {
    await browser.close();
  }
  if (credentials?.token) {
    try {
      cleanupOrders(createdDirectOrderId);
      cleanupOrders(createdGuestOrderId, true);
      cleanupOrders(createdGuestPreparedOrderId, true);
      cleanupOrders(preparedCancelOrderId);
      cleanupOrders(preparedRefreshOrderId);
      cleanupOrders(preparedKcpOrderId);
      cleanupOrders(sendCouponOrderId);
      cleanupOrders(orderCouponPointOrderId);
      cleanupOrders(paidCancelGuardOrderId);
      cleanupOrders(receiptDeliveryOrderId);
      cleanupOrders(cashReceiptOrderId);
      cleanupOrders(productCartCouponOrderId);
      cleanupOrders(categoryCartCouponOrderId);
      cleanupOrders(productPaymentCouponOrderId);
      cleanupOrders(categoryPaymentCouponOrderId);
      cleanupOrders(createdOrderId);
      cleanupOrders();
      cleanupSendCoupons();
      cleanupOrderCoupons();
      cleanupCartCoupon(itemCouponSubject);
      cleanupCartCoupon(categoryCouponSubject);
      cleanupCartCoupon(itemPaymentCouponSubject);
      cleanupCartCoupon(categoryPaymentCouponSubject);
      cleanupOrderPoints();
      await cleanupCart(credentials.token);
    } catch (error) {
      printFailure(error, 'check-local-order-actions cleanup');
      exitCode = 1;
    }
  }
  try {
    runPhp('seed_nextjs_smoke_user.php');
  } catch (error) {
    printFailure(error, 'check-local-order-actions reset');
    exitCode = 1;
  }
}

process.exit(exitCode);
