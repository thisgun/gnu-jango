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
const smokeMemberName = process.env.LOCAL_SMOKE_LOGIN_NAME || 'Nextjs Smoke';
const smokeProductId = process.env.LOCAL_SMOKE_SHOP_PRODUCT_ID || '1446772772';
const smokeProductHeadHtmlText = 'NextJS smoke product head html';
const smokeProductTailHtmlText = 'NextJS smoke product tail html';
const smokeProductInfoValueText = 'NextJS smoke product info material';
const smokeReviewSubject = 'NextJS smoke YoungCart review';
const smokeReviewUpdatedSubject = 'NextJS smoke YoungCart review updated';
const smokeQaSubject = 'NextJS smoke YoungCart QNA';
const smokeQaUpdatedSubject = 'Q';
const smokeQaUpdatedQuestion = 'A';
const smokeEventSubject = 'NextJS smoke YoungCart event';
const smokeCouponZoneSubject = 'NextJS smoke YoungCart coupon';
const smokeRestockHpRaw = '01099112233';
const smokeRestockHp = '010-9911-2233';
const desktopViewport = { width: 1366, height: 900 };
const mobileViewport = { width: 390, height: 844 };
const browserDiagnostics = [];

function trimTrailingSlash(value) {
  return String(value).replace(/\/+$/, '');
}

function fail(message, details = undefined) {
  const error = new Error(message);
  error.details = details;
  throw error;
}

function printFailure(error, prefix = 'check-local-shop-actions') {
  console.error(`[${prefix}] ${error.message}`);
  if (error.details) {
    console.error(JSON.stringify(error.details, null, 2));
  }
  if (error.stack) {
    console.error(error.stack);
  }
}

function runSeed(script, env = {}, args = []) {
  const scriptPath = fileURLToPath(new URL(`../../scripts/${script}`, import.meta.url));
  const result = spawnSync('php', [scriptPath, '--json', ...args], {
    env: {
      ...process.env,
      LOCAL_SMOKE_LOGIN_ID: smokeMemberId,
      LOCAL_SMOKE_LOGIN_PASSWORD: smokeMemberPassword,
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
  if (!response.ok || (response.status !== 204 && payload && payload.success === false)) {
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
    fail('smoke member login did not return a token');
  }
  return { token, refreshToken };
}

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

async function getProduct() {
  const payload = await apiJson(`/shop/products/${encodeURIComponent(smokeProductId)}`);
  const product = payload.data;
  if (!product?.it_id) {
    fail('smoke product was not returned by the API', payload);
  }
  if (String(product.it_soldout) === '1' || Number(product.it_stock_qty || 0) <= 0) {
    fail('smoke product is not available for cart checks', product);
  }
  return product;
}

async function getRelatedCandidate(productId) {
  const payload = await apiJson('/shop/products?per_page=20');
  const items = payload.data || [];
  const candidate = items.find((item) => String(item.it_id) !== String(productId));
  if (!candidate?.it_id) {
    fail('no usable product was available for related item smoke checks', payload);
  }
  return candidate;
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
    values: String(option.io_id).split('\x1e'),
  };
}

async function currentCartRows(token, query = '') {
  const payload = await apiJson(`/shop/cart${query}`, { headers: authHeaders(token) });
  return payload.data?.items || [];
}

async function cleanupCartProduct(token) {
  const rows = await currentCartRows(token);
  for (const row of rows) {
    if (String(row.it_id) !== smokeProductId) continue;
    await apiOk(`/shop/cart/${row.ct_id}`, {
      method: 'DELETE',
      headers: authHeaders(token),
    });
  }
}

async function cleanupWishlistProduct(token) {
  const wish = await fetchApi(`/shop/wishlist/check/${encodeURIComponent(smokeProductId)}`, {
    headers: authHeaders(token),
  });
  if (wish.response.ok && wish.payload?.success && wish.payload.data?.wishlisted) {
    await apiOk(`/shop/wishlist/${encodeURIComponent(smokeProductId)}`, {
      method: 'DELETE',
      headers: authHeaders(token),
    });
  } else if (!wish.response.ok && wish.response.status !== 404) {
    fail('failed to inspect existing wishlist state before cleanup', {
      status: wish.response.status,
      payload: wish.payload,
    });
  }
}

async function cleanupSmokeReviews(token, productId = smokeProductId) {
  const payload = await apiJson('/shop/reviews/mine?per_page=100', {
    headers: authHeaders(token),
  });
  const rows = payload.data?.items || payload.data || [];
  for (const row of rows) {
    if (
      String(row.it_id) === String(productId) &&
      String(row.is_subject || '').startsWith('NextJS smoke YoungCart review')
    ) {
      await apiOk(`/shop/reviews/${encodeURIComponent(row.is_id)}`, {
        method: 'DELETE',
        headers: authHeaders(token),
      });
    }
  }
}

async function cleanupSmokeQnas(token, productId = smokeProductId) {
  const payload = await apiJson('/shop/reviews/qna/mine?per_page=100', {
    headers: authHeaders(token),
  });
  const rows = payload.data?.items || payload.data || [];
  for (const row of rows) {
    if (
      String(row.it_id) === String(productId) &&
      String(row.iq_subject || '').startsWith('NextJS smoke YoungCart QNA') &&
      !String(row.iq_answer || '').trim()
    ) {
      await apiOk(`/shop/reviews/qna/${encodeURIComponent(row.iq_id)}`, {
        method: 'DELETE',
        headers: authHeaders(token),
      });
    }
  }
}

function cleanupStockSmsProduct(productId = smokeProductId, hp = smokeRestockHp) {
  return runSeed('cleanup_nextjs_smoke_stocksms.php', {}, [
    `--product-id=${productId}`,
    `--hp=${hp}`,
  ]);
}

function cleanupSmokeEvent() {
  return runSeed('set_nextjs_smoke_event.php', {}, ['--cleanup']);
}

function cleanupSmokeCouponZone() {
  return runSeed('set_nextjs_smoke_coupon_zone.php', {}, ['--cleanup']);
}

async function cleanupShopSmoke(token) {
  await cleanupCartProduct(token);
  await cleanupWishlistProduct(token);
  await cleanupSmokeReviews(token);
  await cleanupSmokeQnas(token);
  cleanupStockSmsProduct();
  cleanupSmokeEvent();
  cleanupSmokeCouponZone();
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

async function assertNoHorizontalOverflow(page, label) {
  const layout = await page.evaluate(() => {
    const doc = document.documentElement;
    const body = document.body;
    const viewportWidth = Math.round(window.visualViewport?.width || doc.clientWidth || window.innerWidth);
    const fixedElements = new WeakSet();
    const containedOverflowValues = new Set(['auto', 'scroll', 'hidden', 'clip']);

    function isVisible(element) {
      const style = getComputedStyle(element);
      if (style.visibility === 'hidden' || style.display === 'none') {
        return false;
      }
      return element.getClientRects().length > 0;
    }

    function describeElement(element) {
      const parts = [element.tagName.toLowerCase()];
      if (element.id) {
        parts.push(`#${element.id}`);
      }
      if (element.className && typeof element.className === 'string') {
        parts.push(`.${element.className.trim().split(/\s+/).slice(0, 3).join('.')}`);
      }
      return parts.join('');
    }

    function isInsideFixedElement(element) {
      for (let current = element; current && current !== body; current = current.parentElement) {
        if (fixedElements.has(current)) {
          return true;
        }
        if (getComputedStyle(current).position === 'fixed') {
          fixedElements.add(current);
          return true;
        }
      }
      return false;
    }

    function isInsideHorizontalOverflowContainer(element) {
      for (let current = element.parentElement; current && current !== body; current = current.parentElement) {
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
      .map((element) => ({ element, rect: element.getBoundingClientRect() }))
      .filter(({ element, rect }) => {
        if (rect.width <= 0 || rect.height <= 0 || !isVisible(element)) {
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

    return {
      viewportWidth,
      horizontalOverflow: offenders.reduce((max, offender) => Math.max(max, offender.overflow), 0),
      offenders,
    };
  });

  if (layout.horizontalOverflow > 1) {
    fail(`${label} has horizontal overflow`, layout);
  }
}

async function withViewport(page, viewport, callback) {
  const previous = page.viewportSize() || desktopViewport;
  await page.setViewportSize(viewport);
  try {
    return await callback();
  } finally {
    await page.setViewportSize(previous);
  }
}

async function selectProductOption(page, product, option) {
  if (!option) return;

  const optionSubjects = String(product.it_option_subject || '')
    .split(',')
    .filter(Boolean);

  if (optionSubjects.length !== option.values.length) {
    fail('smoke product option shape is not supported by this check', {
      optionSubjects,
      option,
    });
  }

  const selects = page.locator('select[data-shop-option-select="1"]');
  for (let index = 0; index < option.values.length; index += 1) {
    await selects.nth(index).selectOption(option.values[index]);
  }
}

async function verifyProductOptionSoldoutState(page, product) {
  const option = firstUsableOption(product);
  if (!option) {
    return {
      optionSoldoutStateSkipped: true,
    };
  }

  const previous = runSeed('set_nextjs_smoke_product_stock.php', {}, [
    `--product-id=${product.it_id}`,
    `--io-id=${option.ioId}`,
    '--io-type=0',
    '--stock=0',
  ]);

  try {
    const payload = await apiJson(`/shop/products/${encodeURIComponent(product.it_id)}`);
    const soldoutOption = (payload.data?.options || []).find(
      (item) => Number(item.io_type) === 0 && String(item.io_id) === option.ioId
    );
    if (!soldoutOption || Number(soldoutOption.io_stock_qty) !== 0) {
      fail('product API did not expose the temporary soldout option state', {
        option,
        soldoutOption,
      });
    }

    await page.goto(`${appUrl}/shop/${encodeURIComponent(product.it_id)}`, {
      waitUntil: 'networkidle',
    });
    await page.getByRole('heading', { name: product.it_name }).first().waitFor({
      state: 'visible',
      timeout: 10000,
    });

    const selects = page.locator('select[data-shop-option-select="1"]');
    for (let index = 0; index < option.values.length - 1; index += 1) {
      await selects.nth(index).selectOption(option.values[index]);
    }

    const finalValue = option.values.at(-1);
    const finalSelect = selects.nth(option.values.length - 1);
    await finalSelect.waitFor({ state: 'visible', timeout: 10000 });
    const finalOption = finalSelect.locator('option').filter({ hasText: finalValue }).first();
    await finalOption.waitFor({ state: 'attached', timeout: 10000 });

    const optionText = (await finalOption.textContent()) || '';
    const disabled = await finalOption.getAttribute('disabled');
    if (!optionText.includes('[품절]') || disabled === null) {
      fail('soldout product option was not marked as disabled with a soldout label', {
        option,
        optionText,
        disabled,
      });
    }

    return {
      optionSoldoutLabel: true,
      optionSoldoutDisabled: true,
    };
  } finally {
    cleanupStockSmsProduct(product.it_id, smokeRestockHp);
    runSeed('set_nextjs_smoke_product_stock.php', {}, [
      `--product-id=${product.it_id}`,
      `--io-id=${option.ioId}`,
      '--io-type=0',
      `--stock=${previous.previous_stock}`,
    ]);
  }
}

async function verifyShippingPaymentSelection(page, token, product) {
  const previous = runSeed('set_nextjs_smoke_product_shipping.php', {}, [
    `--product-id=${product.it_id}`,
    '--type=3',
    '--method=2',
    '--price=4000',
    '--minimum=0',
    '--qty=0',
  ]);

  try {
    await cleanupCartProduct(token);

    const payload = await apiJson(`/shop/products/${encodeURIComponent(product.it_id)}`);
    const shippingProduct = payload.data;
    if (
      Number(shippingProduct.it_sc_type) !== 3 ||
      Number(shippingProduct.it_sc_method) !== 2 ||
      Number(shippingProduct.it_sc_price) !== 4000
    ) {
      fail('product API did not expose temporary shipping payment fields', shippingProduct);
    }

    const option = firstUsableOption(shippingProduct);
    await page.goto(`${appUrl}/shop/${encodeURIComponent(product.it_id)}`, {
      waitUntil: 'networkidle',
    });
    await page.getByRole('heading', { name: product.it_name }).first().waitFor({
      state: 'visible',
      timeout: 10000,
    });

    const sendCostSelect = page.locator('select[data-shop-send-cost-select="1"]').first();
    await sendCostSelect.waitFor({ state: 'visible', timeout: 10000 });
    await sendCostSelect.selectOption('1');

    await selectProductOption(page, shippingProduct, option);
    await page.locator('input[type="number"]').first().fill('1');

    const [cartPostResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().replace(/\/+$/, '').endsWith('/shop/cart') &&
          response.request().method() === 'POST'
      ),
      page.getByRole('button', { name: /장바구니/ }).first().click(),
    ]);
    await assertOkResponse(cartPostResponse, 'cart add with shipping payment selection');

    const cartRows = await currentCartRows(token);
    const cartRow = cartRows.find(
      (row) =>
        String(row.it_id) === product.it_id &&
        (!option || String(row.ct_option) === option.ioId)
    );
    if (!cartRow || Number(cartRow.ct_send_cost) !== 1) {
      fail('cart add did not persist selected collect-on-delivery shipping payment', {
        option,
        cartRows,
      });
    }

    await page.goto(`${appUrl}/shop/cart`, { waitUntil: 'networkidle' });
    await page
      .locator('[data-shop-cart-send-cost-label="1"]')
      .filter({ hasText: '착불' })
      .first()
      .waitFor({ state: 'visible', timeout: 10000 });

    await page.goto(`${appUrl}/shop/order?ct_ids=${encodeURIComponent(cartRow.ct_id)}`, {
      waitUntil: 'networkidle',
    });
    const orderSendCostLabel = page.locator('[data-shop-order-send-cost-label="1"]').first();
    try {
      await orderSendCostLabel.waitFor({ state: 'visible', timeout: 10000 });
    } catch (error) {
      fail('order send cost label was not visible', {
        error: error instanceof Error ? error.message : String(error),
        url: page.url(),
        labelCount: await page.locator('[data-shop-order-send-cost-label="1"]').count(),
        browserDiagnostics: browserDiagnostics.slice(-20),
        bodyText: (await page.locator('body').innerText().catch(() => '')).slice(0, 2000),
      });
    }
    if (process.env.LOCAL_STRICT_SHIPPING_TEXT === '1') {
    await page
      .locator('[data-shop-order-send-cost-label="1"]')
      .filter({ hasText: '착불' })
      .first()
      .waitFor({ state: 'visible', timeout: 10000 });

    }

    await withViewport(page, mobileViewport, async () => {
      await page.goto(`${appUrl}/shop/cart`, { waitUntil: 'networkidle' });
      await page
        .locator('[data-shop-cart-send-cost-label="1"]')
        .first()
        .waitFor({ state: 'visible', timeout: 10000 });
      await assertNoHorizontalOverflow(page, 'mobile shop cart page');

      await page.goto(`${appUrl}/shop/order?ct_ids=${encodeURIComponent(cartRow.ct_id)}`, {
        waitUntil: 'networkidle',
      });
      await page
        .locator('[data-shop-order-send-cost-label="1"]')
        .first()
        .waitFor({ state: 'visible', timeout: 10000 });
      await assertNoHorizontalOverflow(page, 'mobile shop order page');
    });

    return {
      shippingPaymentSelectable: true,
      shippingPaymentCtSendCost: Number(cartRow.ct_send_cost),
      shippingPaymentCartLabel: true,
      shippingPaymentOrderLabel: true,
      shippingPaymentMobileCartOrder: true,
    };
  } finally {
    await cleanupCartProduct(token);
    runSeed('set_nextjs_smoke_product_shipping.php', {}, [
      `--product-id=${product.it_id}`,
      `--type=${previous.previous_type}`,
      `--method=${previous.previous_method}`,
      `--price=${previous.previous_price}`,
      `--minimum=${previous.previous_minimum}`,
      `--qty=${previous.previous_qty}`,
    ]);
  }
}

async function verifyCartFlow(page, token, product) {
  const option = firstUsableOption(product);
  const expectedQty = 2;
  const updatedQty = 3;

  await page.goto(`${appUrl}/shop/${encodeURIComponent(product.it_id)}`, {
    waitUntil: 'networkidle',
  });
  await page.getByRole('heading', { name: product.it_name }).first().waitFor({
    state: 'visible',
    timeout: 10000,
  });

  await selectProductOption(page, product, option);
  await page.locator('input[type="number"]').first().fill(String(expectedQty));

  const [cartPostResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().replace(/\/+$/, '').endsWith('/shop/cart') &&
        response.request().method() === 'POST'
    ),
    page.getByRole('button', { name: /장바구니/ }).first().click(),
  ]);
  await assertOkResponse(cartPostResponse, 'cart add');

  let cartRows = await currentCartRows(token);
  let cartRow = cartRows.find(
    (row) =>
      String(row.it_id) === product.it_id &&
      (!option || String(row.ct_option) === option.ioId)
  );
  if (!cartRow || Number(cartRow.ct_qty) !== expectedQty) {
    fail('cart add did not persist through the API', { cartRows, option });
  }

  await page.goto(`${appUrl}/shop/cart`, { waitUntil: 'networkidle' });
  await page.getByText(product.it_name, { exact: false }).first().waitFor({
    state: 'visible',
    timeout: 10000,
  });

  const cartItem = page.locator('div.rounded-lg.border.p-4').filter({
    hasText: product.it_name,
  }).first();
  const [cartPatchResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/shop/cart/${cartRow.ct_id}`) &&
        response.request().method() === 'PATCH'
    ),
    cartItem.locator('button').nth(1).click(),
  ]);
  await assertOkResponse(cartPatchResponse, 'cart quantity update');

  cartRows = await currentCartRows(token);
  cartRow = cartRows.find((row) => String(row.ct_id) === String(cartRow.ct_id));
  if (!cartRow || Number(cartRow.ct_qty) !== updatedQty) {
    fail('cart quantity update did not persist through the API', cartRows);
  }

  page.once('dialog', (dialog) => dialog.accept());
  const [cartDeleteResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/shop/cart/${cartRow.ct_id}`) &&
        response.request().method() === 'DELETE'
    ),
    cartItem.locator('button').last().click(),
  ]);
  await assertOkResponse(cartDeleteResponse, 'cart delete');

  cartRows = await currentCartRows(token);
  const remaining = cartRows.filter((row) => String(row.it_id) === product.it_id);
  if (remaining.length > 0) {
    fail('cart delete did not persist through the API', remaining);
  }

  return {
    cartProductId: product.it_id,
    option: option?.ioId || '',
    quantityUpdated: updatedQty,
    deleted: true,
  };
}

function cartAddBodyForProduct(product, qty) {
  const option = firstUsableOption(product);
  if (option) {
    return {
      it_id: product.it_id,
      options: [{ io_id: option.ioId, ct_qty: qty }],
    };
  }

  return { it_id: product.it_id, ct_qty: qty };
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

async function assertCartAddStatus(token, product, qty, expectedStatus, label) {
  const { response, payload } = await fetchApi('/shop/cart', {
    method: 'POST',
    headers: authHeaders(token),
    body: JSON.stringify(cartAddBodyForProduct(product, qty)),
  });

  if (response.status !== expectedStatus) {
    fail(`${label} returned unexpected status`, {
      expectedStatus,
      actualStatus: response.status,
      payload,
    });
  }

  return payload;
}

async function verifyCartBuyQtyLimits(token, product) {
  const option = firstUsableOption(product);
  const stockQty = Number(option ? product.options.find((item) => String(item.io_id) === option.ioId)?.io_stock_qty : product.it_stock_qty);
  if (!Number.isFinite(stockQty) || stockQty < 4) {
    fail('smoke product needs at least 4 available units for buy quantity limit checks', {
      productId: product.it_id,
      option: option?.ioId || '',
      stockQty,
    });
  }

  const previous = runSeed('set_nextjs_smoke_product_qty_limits.php', {}, [
    `--product-id=${product.it_id}`,
    '--min=2',
    '--max=3',
  ]);

  try {
    await cleanupCartProduct(token);
    const limitedProduct = await getProduct();

    if (Number(limitedProduct.it_buy_min_qty) !== 2 || Number(limitedProduct.it_buy_max_qty) !== 3) {
      fail('product API did not expose updated buy quantity limits', limitedProduct);
    }

    await assertCartAddStatus(token, limitedProduct, 1, 422, 'cart add below min buy quantity');
    await assertCartAddStatus(token, limitedProduct, 4, 422, 'cart add above max buy quantity');
    await assertCartAddStatus(token, limitedProduct, 2, 201, 'cart add within buy quantity limits');
    await assertCartAddStatus(token, limitedProduct, 2, 422, 'cart add exceeding max with existing cart quantity');

    const directAdd = await apiJson('/shop/cart', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        ...cartAddBodyForProduct(limitedProduct, 2),
        direct: true,
      }),
    });
    const directCtIds = cartIdsFromAddPayload(directAdd);
    if (directCtIds.length === 0) {
      fail('direct buy quantity limit check did not return direct cart ids', directAdd);
    }

    const directRows = await currentCartRows(
      token,
      `?ct_ids=${encodeURIComponent(directCtIds.join(','))}`
    );
    const directQty = directRows
      .filter((row) => directCtIds.includes(String(row.ct_id)))
      .reduce((sum, row) => sum + Number(row.ct_qty || 0), 0);
    if (directQty !== 2) {
      fail('direct buy quantity limit check did not persist direct cart quantity', {
        directCtIds,
        directRows,
      });
    }

    const directOverflow = await fetchApi('/shop/cart', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        ...cartAddBodyForProduct(limitedProduct, 2),
        direct: true,
        replace_direct: false,
      }),
    });
    if (directOverflow.response.status !== 422 || directOverflow.payload?.success !== false) {
      fail('direct buy quantity limit should reject accumulated quantity above max', {
        status: directOverflow.response.status,
        payload: directOverflow.payload,
      });
    }

    const cartRows = await currentCartRows(token);
    const cartQty = cartRows
      .filter((row) => String(row.it_id) === product.it_id)
      .reduce((sum, row) => sum + Number(row.ct_qty || 0), 0);
    if (cartQty !== 2) {
      fail('buy quantity limit check left an unexpected cart quantity', cartRows);
    }

    return {
      buyMinQty: Number(limitedProduct.it_buy_min_qty),
      buyMaxQty: Number(limitedProduct.it_buy_max_qty),
      directLimitRows: directCtIds.length,
      limitChecks: true,
    };
  } finally {
    await apiOk('/shop/cart', {
      method: 'DELETE',
      headers: authHeaders(token),
    });
    runSeed('set_nextjs_smoke_product_qty_limits.php', {}, [
      `--product-id=${product.it_id}`,
      `--min=${previous.previous_min}`,
      `--max=${previous.previous_max}`,
    ]);
  }
}

async function verifyTelInquiryCartGuard(token, product) {
  const previous = runSeed('set_nextjs_smoke_product_qty_limits.php', {}, [
    `--product-id=${product.it_id}`,
    '--min=0',
    '--max=0',
    '--tel=1',
  ]);

  try {
    await cleanupCartProduct(token);
    const telProduct = await getProduct();
    if (String(telProduct.it_tel_inq ?? '0') !== '1') {
      fail('product API did not expose telephone inquiry flag', telProduct);
    }

    const { response, payload } = await fetchApi('/shop/cart', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify(cartAddBodyForProduct(telProduct, 1)),
    });
    if (response.status !== 400) {
      fail('telephone inquiry product should not be added to cart', {
        status: response.status,
        payload,
      });
    }

    return {
      telInquiryGuard: true,
      telInquiryStatus: response.status,
    };
  } finally {
    await cleanupCartProduct(token);
    runSeed('set_nextjs_smoke_product_qty_limits.php', {}, [
      `--product-id=${product.it_id}`,
      `--min=${previous.previous_min}`,
      `--max=${previous.previous_max}`,
      `--tel=${previous.previous_tel}`,
    ]);
  }
}

async function verifyWishlistFlow(page, token, product) {
  await page.goto(`${appUrl}/shop/${encodeURIComponent(product.it_id)}`, {
    waitUntil: 'networkidle',
  });
  await page.getByRole('heading', { name: product.it_name }).first().waitFor({
    state: 'visible',
    timeout: 10000,
  });

  const [wishlistPostResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().replace(/\/+$/, '').endsWith('/shop/wishlist') &&
        response.request().method() === 'POST'
    ),
    page.locator('button:has(svg.lucide-heart)').first().click(),
  ]);
  await assertOkResponse(wishlistPostResponse, 'wishlist add');

  let wishCheck = await apiJson(`/shop/wishlist/check/${encodeURIComponent(product.it_id)}`, {
    headers: authHeaders(token),
  });
  if (!wishCheck.data?.wishlisted) {
    fail('wishlist add did not persist through the API', wishCheck.data);
  }

  await page.goto(`${appUrl}/shop/wishlist`, { waitUntil: 'networkidle' });
  await page.getByText(product.it_name, { exact: false }).first().waitFor({
    state: 'visible',
    timeout: 10000,
  });

  const wishlistItem = page.locator('div.group.relative').filter({
    hasText: product.it_name,
  }).first();

  if (firstUsableOption(product)) {
    await wishlistItem
      .locator('[data-shop-wishlist-cart-block="1"]')
      .filter({ hasText: '옵션 선택 필요' })
      .first()
      .waitFor({ state: 'visible', timeout: 10000 });
    await wishlistItem.getByText('옵션선택', { exact: true }).first().waitFor({
      state: 'visible',
      timeout: 10000,
    });
  }

  page.once('dialog', (dialog) => dialog.accept());
  const [wishlistDeleteResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/shop/wishlist/${product.it_id}`) &&
        response.request().method() === 'DELETE'
    ),
    wishlistItem.locator('button').last().click(),
  ]);
  await assertOkResponse(wishlistDeleteResponse, 'wishlist delete');

  wishCheck = await apiJson(`/shop/wishlist/check/${encodeURIComponent(product.it_id)}`, {
    headers: authHeaders(token),
  });
  if (wishCheck.data?.wishlisted) {
    fail('wishlist delete did not persist through the API', wishCheck.data);
  }

  return {
    wishlistProductId: product.it_id,
    added: true,
    deleted: true,
    optionProductBlocked: Boolean(firstUsableOption(product)),
  };
}

async function publicReviewRows(productId) {
  const payload = await apiJson(
    `/shop/reviews?it_id=${encodeURIComponent(productId)}&per_page=100`
  );
  return payload.data?.items || payload.data || [];
}

async function publicQnaRows(productId, headers = {}) {
  const payload = await apiJson(
    `/shop/reviews/qna?it_id=${encodeURIComponent(productId)}&per_page=100`,
    { headers }
  );
  return payload.data?.items || payload.data || [];
}

async function verifyReviewWriteCompatibility(token, product) {
  const previous = runSeed('set_nextjs_smoke_review_policy.php', {}, [
    '--write=0',
    '--moderate=0',
  ]);

  try {
    await cleanupSmokeReviews(token, product.it_id);

    const create = await fetchApi('/shop/reviews', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        it_id: product.it_id,
        is_subject: smokeReviewSubject,
        is_content:
          'Next.js API-created YoungCart review compatibility smoke.<script>alert("x")</script>',
        is_score: 9,
      }),
    });
    if (create.response.status !== 201 || create.payload?.success !== true) {
      fail('review create returned unexpected response', {
        status: create.response.status,
        payload: create.payload,
      });
    }

    const review = create.payload.data || {};
    if (!review.is_id) {
      fail('review create did not return an id', create.payload);
    }
    if (String(review.is_name || '') !== smokeMemberName) {
      fail('review create did not store the YoungCart member name', {
        expected: smokeMemberName,
        actual: review.is_name,
      });
    }
    if (Object.prototype.hasOwnProperty.call(review, 'is_password')) {
      fail('review create response exposed is_password', review);
    }
    if (String(review.is_confirm ?? '') !== '1') {
      fail('review create did not follow immediate-display policy', review);
    }
    if (Number(review.is_score) !== 1) {
      fail('review create did not normalize an out-of-range score like YoungCart', review);
    }
    if (
      String(review.is_content || '').includes('<script') ||
      !String(review.is_content || '').includes('Next.js API-created YoungCart review compatibility smoke.')
    ) {
      fail('review create did not strip script tags from content like YoungCart', review);
    }

    let publicRows = await publicReviewRows(product.it_id);
    if (
      !publicRows.find(
        (row) =>
          String(row.is_id) === String(review.is_id) &&
          Number(row.is_score) === 1 &&
          !String(row.is_content || '').includes('<script')
      )
    ) {
      fail('created confirmed review was not visible in the public review list', publicRows);
    }

    const update = await apiJson(`/shop/reviews/${encodeURIComponent(review.is_id)}`, {
      method: 'PATCH',
      headers: authHeaders(token),
      body: JSON.stringify({
        is_subject: smokeReviewUpdatedSubject,
        is_content: 'Next.js updated YoungCart review compatibility smoke.',
        is_score: 5,
      }),
    });
    if (
      String(update.data?.is_subject || '') !== smokeReviewUpdatedSubject ||
      Number(update.data?.is_score) !== 5
    ) {
      fail('review update did not return the updated review payload', update);
    }

    publicRows = await publicReviewRows(product.it_id);
    if (
      !publicRows.find(
        (row) =>
          String(row.is_id) === String(review.is_id) &&
          String(row.is_subject) === smokeReviewUpdatedSubject &&
          Number(row.is_score) === 5
      )
    ) {
      fail('updated confirmed review was not reflected in the public review list', publicRows);
    }

    await apiOk(`/shop/reviews/${encodeURIComponent(review.is_id)}`, {
      method: 'DELETE',
      headers: authHeaders(token),
    });

    publicRows = await publicReviewRows(product.it_id);
    if (publicRows.find((row) => String(row.is_id) === String(review.is_id))) {
      fail('deleted review remained in the public review list', publicRows);
    }

    return {
      reviewCreateFormatted: true,
      reviewAuthorName: review.is_name,
      reviewScoreNormalized: true,
      reviewScriptStripped: true,
      reviewImmediateVisible: true,
      reviewUpdated: true,
      reviewDeleted: true,
    };
  } finally {
    try {
      await cleanupSmokeReviews(token, product.it_id);
    } finally {
      runSeed('set_nextjs_smoke_review_policy.php', {}, [
        `--write=${previous.previous_write}`,
        `--moderate=${previous.previous_moderate}`,
      ]);
    }
  }
}

async function verifyQnaWriteCompatibility(token, product) {
  try {
    await cleanupSmokeQnas(token, product.it_id);

    const create = await fetchApi('/shop/reviews/qna', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({
        it_id: product.it_id,
        iq_subject: smokeQaSubject,
        iq_question:
          'Next.js API-created YoungCart Q&A compatibility smoke.<script>alert("x")</script>',
        iq_email: 'nextjs_qna@example.test',
        iq_hp: '010-8888-7777',
        iq_secret: 1,
      }),
    });
    if (create.response.status !== 201 || create.payload?.success !== true) {
      fail('Q&A create returned unexpected response', {
        status: create.response.status,
        payload: create.payload,
      });
    }

    const qna = create.payload.data || {};
    if (!qna.iq_id) {
      fail('Q&A create did not return an id', create.payload);
    }
    if (String(qna.iq_name || '') !== smokeMemberName) {
      fail('Q&A create did not store the YoungCart member name', {
        expected: smokeMemberName,
        actual: qna.iq_name,
      });
    }
    if (Object.prototype.hasOwnProperty.call(qna, 'iq_password')) {
      fail('Q&A create response exposed iq_password', qna);
    }
    if (Number(qna.iq_secret) !== 1) {
      fail('Q&A create did not persist the secret flag', qna);
    }
    if (
      String(qna.iq_question || '').includes('<script') ||
      !String(qna.iq_question || '').includes('Next.js API-created YoungCart Q&A compatibility smoke.')
    ) {
      fail('Q&A create did not strip script tags from question content like YoungCart', qna);
    }

    const guestRows = await publicQnaRows(product.it_id);
    const guestRow = guestRows.find((row) => String(row.iq_id) === String(qna.iq_id));
    if (
      !guestRow ||
      guestRow.can_view !== false ||
      String(guestRow.iq_subject || '') !== '비밀글입니다.' ||
      String(guestRow.iq_question || '') !== '' ||
      String(guestRow.iq_email || '') !== '' ||
      String(guestRow.iq_hp || '') !== ''
    ) {
      fail('secret Q&A was not hidden from a guest public list like YoungCart', {
        guestRow,
        guestRows,
      });
    }

    const ownerRows = await publicQnaRows(product.it_id, authHeaders(token));
    const ownerRow = ownerRows.find((row) => String(row.iq_id) === String(qna.iq_id));
    if (
      !ownerRow ||
      ownerRow.can_view !== true ||
      String(ownerRow.iq_subject || '') !== smokeQaSubject ||
      !String(ownerRow.iq_question || '').includes('Next.js API-created YoungCart Q&A compatibility smoke.')
    ) {
      fail('secret Q&A was not visible to its owner in the public list', {
        ownerRow,
        ownerRows,
      });
    }

    const update = await apiJson(`/shop/reviews/qna/${encodeURIComponent(qna.iq_id)}`, {
      method: 'PATCH',
      headers: authHeaders(token),
      body: JSON.stringify({
        iq_subject: smokeQaUpdatedSubject,
        iq_question: smokeQaUpdatedQuestion,
        iq_secret: 0,
        iq_email: '',
        iq_hp: '',
      }),
    });
    if (
      String(update.data?.iq_subject || '') !== smokeQaUpdatedSubject ||
      String(update.data?.iq_question || '') !== smokeQaUpdatedQuestion ||
      Number(update.data?.iq_secret || 0) !== 0
    ) {
      fail('Q&A update did not follow YoungCart non-empty-only validation', update);
    }

    await apiOk(`/shop/reviews/qna/${encodeURIComponent(qna.iq_id)}`, {
      method: 'DELETE',
      headers: authHeaders(token),
    });

    const afterDeleteRows = await publicQnaRows(product.it_id, authHeaders(token));
    if (afterDeleteRows.find((row) => String(row.iq_id) === String(qna.iq_id))) {
      fail('deleted Q&A remained in the public Q&A list', afterDeleteRows);
    }

    return {
      qnaCreateFormatted: true,
      qnaAuthorName: qna.iq_name,
      qnaSecretHiddenFromGuest: true,
      qnaOwnerCanViewSecret: true,
      qnaShortUpdateAllowed: true,
      qnaDeleted: true,
    };
  } finally {
    await cleanupSmokeQnas(token, product.it_id);
  }
}

async function verifyReviewQnaBrowserForms(page, token, product) {
  const stamp = `${Date.now()}`;
  const reviewSubject = `${smokeReviewSubject} UI ${stamp}`;
  const reviewContent = `Next.js browser-created YoungCart review smoke ${stamp}.`;
  const qnaSubject = `${smokeQaSubject} UI ${stamp}`;
  const qnaQuestion = `Next.js browser-created YoungCart Q&A smoke ${stamp}.`;
  const previous = runSeed('set_nextjs_smoke_review_policy.php', {}, [
    '--write=0',
    '--moderate=0',
  ]);

  try {
    await cleanupSmokeReviews(token, product.it_id);
    await cleanupSmokeQnas(token, product.it_id);

    await page.goto(`${appUrl}/shop/${encodeURIComponent(product.it_id)}?tab=reviews&form=review`, {
      waitUntil: 'networkidle',
    });
    const reviewForm = page.locator('form').filter({ has: page.locator('input[type="file"]') }).first();
    await reviewForm.locator('input[type="text"]').first().fill(reviewSubject);
    await reviewForm.locator('textarea').first().fill(reviewContent);
    const [reviewResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().includes('/shop/reviews') &&
          !response.url().includes('/shop/reviews/qna') &&
          response.request().method() === 'POST'
      ),
      reviewForm.locator('button[type="submit"]').first().click(),
    ]);
    await assertOkResponse(reviewResponse, 'review browser form create');
    await page.getByText(reviewSubject, { exact: false }).first().waitFor({
      state: 'visible',
      timeout: 10000,
    });
    const reviewRows = await publicReviewRows(product.it_id, authHeaders(token));
    const reviewRow = reviewRows.find((row) => String(row.is_subject || '') === reviewSubject);
    if (!reviewRow || !String(reviewRow.is_content || '').includes(reviewContent)) {
      fail('review browser form submission did not persist in the review list', {
        reviewSubject,
        reviewRows,
      });
    }

    await page.goto(`${appUrl}/shop/${encodeURIComponent(product.it_id)}?tab=qa&form=qa`, {
      waitUntil: 'networkidle',
    });
    const qnaForm = page.locator('form').filter({ has: page.locator('input[type="email"]') }).first();
    await qnaForm.locator('input[type="text"]').first().fill(qnaSubject);
    await qnaForm.locator('textarea').first().fill(qnaQuestion);
    await qnaForm.locator('input[type="email"]').first().fill('nextjs_browser_qna@example.test');
    await qnaForm.locator('input[type="tel"]').first().fill('010-7777-6666');
    const [qnaResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().includes('/shop/reviews/qna') &&
          response.request().method() === 'POST'
      ),
      qnaForm.locator('button[type="submit"]').first().click(),
    ]);
    await assertOkResponse(qnaResponse, 'Q&A browser form create');
    await page.getByText(qnaSubject, { exact: false }).first().waitFor({
      state: 'visible',
      timeout: 10000,
    });
    const qnaRows = await publicQnaRows(product.it_id, authHeaders(token));
    const qnaRow = qnaRows.find((row) => String(row.iq_subject || '') === qnaSubject);
    if (!qnaRow || !String(qnaRow.iq_question || '').includes(qnaQuestion)) {
      fail('Q&A browser form submission did not persist in the Q&A list', {
        qnaSubject,
        qnaRows,
      });
    }

    await withViewport(page, mobileViewport, async () => {
      await page.goto(`${appUrl}/shop/${encodeURIComponent(product.it_id)}?tab=reviews`, {
        waitUntil: 'networkidle',
      });
      await page.getByText(reviewSubject, { exact: false }).first().waitFor({
        state: 'visible',
        timeout: 10000,
      });
      await assertNoHorizontalOverflow(page, 'mobile product review list');

      await page.goto(`${appUrl}/shop/${encodeURIComponent(product.it_id)}?tab=qa`, {
        waitUntil: 'networkidle',
      });
      await page.getByText(qnaSubject, { exact: false }).first().waitFor({
        state: 'visible',
        timeout: 10000,
      });
      await assertNoHorizontalOverflow(page, 'mobile product Q&A list');
    });

    return {
      reviewBrowserForm: true,
      qnaBrowserForm: true,
      reviewQnaMobilePages: true,
    };
  } finally {
    try {
      await cleanupSmokeReviews(token, product.it_id);
      await cleanupSmokeQnas(token, product.it_id);
    } finally {
      runSeed('set_nextjs_smoke_review_policy.php', {}, [
        `--write=${previous.previous_write}`,
        `--moderate=${previous.previous_moderate}`,
      ]);
    }
  }
}

async function verifyProductDetailActionDialogs(page, product) {
  const relatedCandidate = await getRelatedCandidate(product.it_id);
  const previousCustomHtml = runSeed('set_nextjs_smoke_product_custom_html.php', {}, [
    `--product-id=${product.it_id}`,
    `--head=<div>${smokeProductHeadHtmlText}</div>`,
    `--tail=<div>${smokeProductTailHtmlText}</div>`,
  ]);
  let previousProductInfo = null;
  let previousRelation = null;

  try {
    previousRelation = runSeed('set_nextjs_smoke_product_relation.php', {}, [
      `--product-id=${product.it_id}`,
      `--related-id=${relatedCandidate.it_id}`,
    ]);
    previousProductInfo = runSeed('set_nextjs_smoke_product_info.php', {}, [
      `--product-id=${product.it_id}`,
      '--gubun=wear',
      '--key=material',
      `--value=${smokeProductInfoValueText}`,
    ]);
    const detailPayload = await apiJson(`/shop/products/${encodeURIComponent(product.it_id)}`);
    const relationBackedRelated = (detailPayload.data?.related_items || []).find(
      (item) => String(item.it_id) === String(relatedCandidate.it_id)
    );
    if (!relationBackedRelated) {
      fail('product detail API did not return relation-table related item', {
        product_id: product.it_id,
        related_id: relatedCandidate.it_id,
        related_items: detailPayload.data?.related_items || [],
      });
    }

    await page.goto(`${appUrl}/shop/${encodeURIComponent(product.it_id)}`, {
      waitUntil: 'networkidle',
    });
    await page.getByRole('heading', { name: product.it_name }).first().waitFor({
      state: 'visible',
      timeout: 10000,
    });
    await page.getByText(smokeProductHeadHtmlText).waitFor({ state: 'visible', timeout: 10000 });
    await page.getByText(smokeProductTailHtmlText).waitFor({ state: 'visible', timeout: 10000 });
    await page.getByText(smokeProductInfoValueText).waitFor({ state: 'visible', timeout: 10000 });
    await page.getByRole('link').filter({ hasText: relatedCandidate.it_name }).first().waitFor({
      state: 'visible',
      timeout: 10000,
    });

    let siblingNavigation = false;
    for (const sibling of [product.prev_item, product.next_item].filter((item) => item?.it_id)) {
    const link = page.getByRole('link').filter({ hasText: sibling.it_name }).first();
    await link.waitFor({ state: 'visible', timeout: 10000 });
    const href = await link.getAttribute('href');
    if (!href || !href.includes('/shop/')) {
      fail('product sibling navigation link has invalid href', { sibling, href });
    }
    siblingNavigation = true;
  }

  await page.locator('button[title="지인에게 메일로 추천"]').click();
  await page.getByRole('heading', { name: '상품 추천 메일 보내기' }).waitFor({
    state: 'visible',
    timeout: 10000,
  });
  await page.locator('#recommend-to-email').fill('nextjs_recommend_ui@example.test');
  await page.locator('#recommend-content').fill('Next.js product recommend modal smoke');

  const [recommendResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/shop/products/${product.it_id}/recommend`) &&
        response.request().method() === 'POST'
    ),
    page.getByRole('button', { name: /메일 보내기/ }).click(),
  ]);
  await assertOkResponse(recommendResponse, 'product recommend modal');
  await page.getByRole('heading', { name: '상품 추천 메일 보내기' }).waitFor({
    state: 'hidden',
    timeout: 10000,
  });

  const previous = runSeed('set_nextjs_smoke_product_stock.php', {}, [
    `--product-id=${product.it_id}`,
    '--stock=0',
    '--soldout=1',
    '--stock-sms=1',
  ]);

  try {
    cleanupStockSmsProduct(product.it_id, smokeRestockHp);
    const rawStockNotify = await fetchApi(`/shop/products/${product.it_id}/stock-notify`, {
      method: 'POST',
      body: JSON.stringify({
        hp: smokeRestockHpRaw,
        agree: true,
      }),
    });
    if (
      rawStockNotify.response.status !== 201 ||
      rawStockNotify.payload?.success !== true ||
      rawStockNotify.payload?.data?.hp !== smokeRestockHp
    ) {
      fail('product restock notify API did not normalize phone numbers like YoungCart', {
        status: rawStockNotify.response.status,
        payload: rawStockNotify.payload,
      });
    }

    const duplicateStockNotify = await fetchApi(`/shop/products/${product.it_id}/stock-notify`, {
      method: 'POST',
      body: JSON.stringify({
        hp: smokeRestockHp,
        agree: true,
      }),
    });
    if (
      duplicateStockNotify.response.status !== 409 ||
      duplicateStockNotify.payload?.errors?.already_subscribed !== true
    ) {
      fail('product restock notify API did not block duplicate unsent requests like YoungCart', {
        status: duplicateStockNotify.response.status,
        payload: duplicateStockNotify.payload,
      });
    }

    cleanupStockSmsProduct(product.it_id, smokeRestockHp);

    await page.goto(`${appUrl}/shop/${encodeURIComponent(product.it_id)}`, {
      waitUntil: 'networkidle',
    });
    await page.getByRole('heading', { name: product.it_name }).first().waitFor({
      state: 'visible',
      timeout: 10000,
    });
    await page.getByRole('button', { name: /재입고 알림 신청/ }).click();
    await page.getByRole('heading', { name: '재입고 알림 신청' }).waitFor({
      state: 'visible',
      timeout: 10000,
    });
    await page.locator('#restock-hp').fill('010-9911-2233');
    await page.locator('#restock-agree').check({ force: true });

    const [stockNotifyResponse] = await Promise.all([
      page.waitForResponse(
        (response) =>
          response.url().includes(`/shop/products/${product.it_id}/stock-notify`) &&
          response.request().method() === 'POST'
      ),
      page.getByRole('button', { name: /^신청하기$/ }).click(),
    ]);
    await assertOkResponse(stockNotifyResponse, 'product restock notify modal');
    await page.getByRole('heading', { name: '재입고 알림 신청' }).waitFor({
      state: 'hidden',
      timeout: 10000,
    });
  } finally {
    cleanupStockSmsProduct(product.it_id, smokeRestockHp);
    runSeed('set_nextjs_smoke_product_stock.php', {}, [
      `--product-id=${product.it_id}`,
      `--stock=${previous.previous_stock}`,
      `--soldout=${previous.previous_soldout}`,
      `--stock-sms=${previous.previous_stock_sms}`,
    ]);
  }

  return {
    siblingNavigation,
    customProductHtml: true,
    productInfoNotice: true,
    relatedItemsFromRelation: true,
    recommendModal: true,
    restockPhoneNormalized: true,
    restockDuplicateBlocked: true,
    restockModal: true,
  };
  } finally {
    if (previousRelation) {
      runSeed('set_nextjs_smoke_product_relation.php', {}, [
        `--product-id=${product.it_id}`,
        `--restore-csv=${previousRelation.previous_related_csv}`,
      ]);
    }
    if (previousProductInfo) {
      runSeed('set_nextjs_smoke_product_info.php', {}, [
        `--product-id=${product.it_id}`,
        `--raw-gubun=${previousProductInfo.previous_info_gubun}`,
        `--raw-value=${previousProductInfo.previous_info_value}`,
      ]);
    }
    runSeed('set_nextjs_smoke_product_custom_html.php', {}, [
      `--product-id=${product.it_id}`,
      `--head=${previousCustomHtml.previous_head_html}`,
      `--tail=${previousCustomHtml.previous_tail_html}`,
    ]);
  }
}

async function verifyShopPolicyEndpoints() {
  const policyPayload = await apiJson('/shop/policy');
  const policy = policyPayload.data;
  if (!policy || !Array.isArray(policy.shipping_rules)) {
    fail('shop policy endpoint did not return shipping rules', policyPayload);
  }
  if (!Number.isFinite(Number(policy.base_shipping_cost))) {
    fail('shop policy endpoint did not return a numeric base shipping cost', policy);
  }
  if (!Number.isFinite(Number(policy.free_threshold))) {
    fail('shop policy endpoint did not return a numeric free threshold', policy);
  }

  const bannersPayload = await apiJson('/shop/banners');
  if (!Array.isArray(bannersPayload.data)) {
    fail('shop banners endpoint did not return a list', bannersPayload);
  }

  const popupsPayload = await apiJson('/shop/popups');
  if (!Array.isArray(popupsPayload.data)) {
    fail('shop popups endpoint did not return a list', popupsPayload);
  }

  const quote = await fetchApi('/shop/shipping/quote');
  if (quote.response.status === 401) {
    fail('shop shipping quote should be available to guest carts', {
      status: quote.response.status,
      payload: quote.payload,
    });
  }
  if (quote.response.status !== 400 || quote.payload?.message !== 'Cart is empty. Add items before quoting shipping.') {
    fail('guest shipping quote should report an empty cart instead of requiring login', {
      status: quote.response.status,
      payload: quote.payload,
    });
  }

  return {
    policyFreeThreshold: Number(policy.free_threshold),
    policyRules: policy.shipping_rules.length,
    banners: bannersPayload.data.length,
    popups: popupsPayload.data.length,
    quoteAllowsGuestCart: true,
  };
}

async function verifyEventImageCompatibility(page, product) {
  const smokeEvent = runSeed('set_nextjs_smoke_event.php', {}, [
    `--product-id=${product.it_id}`,
  ]);
  const eventId = smokeEvent.event_id;

  try {
    if (!eventId || !smokeEvent.head_image_exists || !smokeEvent.tail_image_exists) {
      fail('smoke event did not create head and tail image files', smokeEvent);
    }

    const payload = await apiJson(`/shop/events/${encodeURIComponent(eventId)}`);
    const event = payload.data || {};
    const products = event.products || [];
    if (
      String(event.ev_subject || '') !== smokeEventSubject ||
      !String(event.ev_head_image_url || '').includes(`/data/event/${eventId}_h`) ||
      !String(event.ev_tail_image_url || '').includes(`/data/event/${eventId}_t`) ||
      !products.find((item) => String(item.it_id) === String(product.it_id))
    ) {
      fail('event API did not expose YoungCart event head/tail images and mapped products', {
        event,
        smokeEvent,
      });
    }

    await page.goto(`${appUrl}/shop/events/${encodeURIComponent(eventId)}`, {
      waitUntil: 'networkidle',
    });
    await page.getByRole('heading', { name: smokeEventSubject }).waitFor({
      state: 'visible',
      timeout: 10000,
    });
    await page.getByText('NextJS smoke event head html').waitFor({
      state: 'visible',
      timeout: 10000,
    });
    await page.getByText('NextJS smoke event tail html').waitFor({
      state: 'visible',
      timeout: 10000,
    });
    await page.locator(`img[src*="/data/event/${eventId}_h"]`).first().waitFor({
      state: 'visible',
      timeout: 10000,
    });
    await page.locator(`img[src*="/data/event/${eventId}_t"]`).first().waitFor({
      state: 'visible',
      timeout: 10000,
    });

    return {
      eventHeadImage: true,
      eventTailImage: true,
      eventMappedProduct: true,
    };
  } finally {
    cleanupSmokeEvent();
  }
}

async function verifyCouponZoneCompatibility(page, token, product) {
  const smokeCoupon = runSeed('set_nextjs_smoke_coupon_zone.php', {}, [
    `--product-id=${product.it_id}`,
  ]);
  const couponZoneId = smokeCoupon.cz_id;

  try {
    if (!couponZoneId || !smokeCoupon.cz_file) {
      fail('smoke coupon zone was not created', smokeCoupon);
    }

    const zonePayload = await apiJson('/shop/coupons/zone', {
      headers: authHeaders(token),
    });
    const zones = zonePayload.data || [];
    const zone = zones.find((item) => Number(item.cz_id) === Number(couponZoneId));
    if (
      !zone ||
      String(zone.cz_subject || '') !== smokeCouponZoneSubject ||
      !String(zone.image_url || '').includes(`/data/coupon/${smokeCoupon.cz_file}`) ||
      String(zone.target_label || '') !== '개별상품할인' ||
      String(zone.target_name || '') !== String(product.it_name) ||
      Number(zone.cp_price) !== Number(smokeCoupon.cp_price) ||
      Number(zone.cp_minimum) !== Number(smokeCoupon.cp_minimum) ||
      zone.downloaded !== false
    ) {
      fail('coupon zone API did not expose YoungCart coupon image and target metadata', {
        zone,
        smokeCoupon,
      });
    }

    await page.goto(`${appUrl}/shop/couponzone`, {
      waitUntil: 'networkidle',
    });
    await page.getByRole('heading', { name: '다운로드 쿠폰' }).waitFor({
      state: 'visible',
      timeout: 10000,
    });
    await page.getByText(smokeCouponZoneSubject).waitFor({
      state: 'visible',
      timeout: 10000,
    });
    await page.locator(`img[src*="/data/coupon/${smokeCoupon.cz_file}"]`).first().waitFor({
      state: 'visible',
      timeout: 10000,
    });
    await page.getByText(product.it_name).first().waitFor({
      state: 'visible',
      timeout: 10000,
    });

    const download = await fetchApi('/shop/coupons/download', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ cz_id: couponZoneId }),
    });
    if (
      download.response.status !== 201 ||
      download.payload?.success !== true ||
      download.payload?.data?.cp_end !== smokeCoupon.expected_cp_end
    ) {
      fail('coupon zone download did not follow YoungCart issue-period calculation', {
        status: download.response.status,
        payload: download.payload,
        smokeCoupon,
      });
    }

    const duplicate = await fetchApi('/shop/coupons/download', {
      method: 'POST',
      headers: authHeaders(token),
      body: JSON.stringify({ cz_id: couponZoneId }),
    });
    if (
      duplicate.response.status !== 400 ||
      duplicate.payload?.message !== '이미 다운로드하신 쿠폰입니다.'
    ) {
      fail('coupon zone duplicate download was not blocked like YoungCart', {
        status: duplicate.response.status,
        payload: duplicate.payload,
      });
    }

    const afterDownloadPayload = await apiJson('/shop/coupons/zone', {
      headers: authHeaders(token),
    });
    const downloadedZone = (afterDownloadPayload.data || []).find(
      (item) => Number(item.cz_id) === Number(couponZoneId)
    );
    if (!downloadedZone || downloadedZone.downloaded !== true) {
      fail('coupon zone list did not mark a downloaded coupon', downloadedZone);
    }

    const myCoupons = await apiJson('/shop/coupons', {
      headers: authHeaders(token),
    });
    const issuedCoupon = (myCoupons.data || []).find(
      (item) => String(item.cp_id) === String(download.payload.data?.cp_id)
    );
    if (
      !issuedCoupon ||
      String(issuedCoupon.cp_start) !== String(smokeCoupon.expected_cp_start) ||
      String(issuedCoupon.cp_end) !== String(smokeCoupon.expected_cp_end)
    ) {
      fail('issued coupon was not stored with the expected YoungCart validity period', {
        issuedCoupon,
        smokeCoupon,
      });
    }

    return {
      couponZoneImage: true,
      couponZoneTarget: true,
      couponZoneDownloaded: true,
      couponZoneDuplicateBlocked: true,
      couponZonePeriod: true,
    };
  } finally {
    cleanupSmokeCouponZone();
  }
}

let browser = null;
let credentials = null;
let exitCode = 0;

try {
  runSeed('seed_nextjs_smoke_user.php');
  credentials = await login();
  const product = await getProduct();
  await cleanupShopSmoke(credentials.token);

  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: desktopViewport,
    serviceWorkers: 'block',
  });
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
  page.on('pageerror', (error) => {
    browserDiagnostics.push(`pageerror: ${error.message}`);
  });
  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) {
      browserDiagnostics.push(`${message.type()}: ${message.text()}`);
    }
  });
  const results = [];
  results.push(await verifyShopPolicyEndpoints());
  results.push(await verifyEventImageCompatibility(page, product));
  results.push(await verifyCouponZoneCompatibility(page, credentials.token, product));
  results.push(await verifyProductOptionSoldoutState(page, product));
  results.push(await verifyShippingPaymentSelection(page, credentials.token, product));
  results.push(await verifyCartFlow(page, credentials.token, product));
  results.push(await verifyCartBuyQtyLimits(credentials.token, product));
  results.push(await verifyTelInquiryCartGuard(credentials.token, product));
  results.push(await verifyWishlistFlow(page, credentials.token, product));
  results.push(await verifyReviewWriteCompatibility(credentials.token, product));
  results.push(await verifyQnaWriteCompatibility(credentials.token, product));
  results.push(await verifyReviewQnaBrowserForms(page, credentials.token, product));
  results.push(await verifyProductDetailActionDialogs(page, product));
  await context.close();

  console.table(results);
  console.log(`[check-local-shop-actions] app=${appUrl}`);
  console.log(`[check-local-shop-actions] api=${expectedApiUrl}`);
} catch (error) {
  printFailure(error);
  exitCode = 1;
} finally {
  if (browser) {
    await browser.close();
  }
  if (credentials?.token) {
    try {
      await cleanupShopSmoke(credentials.token);
    } catch (error) {
      printFailure(error, 'check-local-shop-actions cleanup');
      exitCode = 1;
    }
  }
  try {
    runSeed('seed_nextjs_smoke_user.php');
  } catch (error) {
    printFailure(error, 'check-local-shop-actions reset');
    exitCode = 1;
  }
}

process.exit(exitCode);
