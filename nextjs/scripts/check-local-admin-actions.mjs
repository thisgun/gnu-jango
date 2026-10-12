import { chromium } from '@playwright/test';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const appUrl = trimTrailingSlash(process.env.LOCAL_APP_URL || 'http://127.0.0.20');
const expectedApiUrl = trimTrailingSlash(
  process.env.LOCAL_EXPECTED_API_URL || 'http://127.0.0.9/api/v1'
);

const adminId = process.env.LOCAL_SMOKE_ADMIN_LOGIN_ID || 'nextjs_admin_smoke';
const adminPassword =
  process.env.LOCAL_SMOKE_ADMIN_LOGIN_PASSWORD || 'NextjsAdminSmoke123!';
const trackingNumber = `SMOKE-${Date.now()}`;
const smokeCategoryId = process.env.LOCAL_SMOKE_ADMIN_CATEGORY_ID || 'nxtsmoke9';
const smokeCategoryName = 'Next.js admin action category';
const smokeCategoryNameUpdated = 'Next.js admin action category updated';
const smokeProductId = process.env.LOCAL_SMOKE_ADMIN_PRODUCT_ID || 'nxt-smoke-product';
const smokeProductName = 'Next.js admin action product';
const smokeProductNameUpdated = 'Next.js admin action product updated';
const smokeBoardId = process.env.LOCAL_SMOKE_ADMIN_BOARD_ID || 'nxt_smoke_board';
const smokeBoardSubject = 'Next.js admin action board';
const smokeBoardSubjectUpdated = 'Next.js admin action board updated';
const smokeMemberId = process.env.LOCAL_SMOKE_LOGIN_ID || 'nextjs_smoke';
const smokeMemberPassword = process.env.LOCAL_SMOKE_LOGIN_PASSWORD || 'NextjsSmoke123!';
const smokeMemberNickUpdated = 'NextjsSmokeMutated';
const smokeMemberNameUpdated = 'Nextjs Smoke Mutated';
const smokeMemberEmailUpdated = `${smokeMemberId}+admin-action@example.test`;

function trimTrailingSlash(value) {
  return String(value).replace(/\/+$/, '');
}

function fail(message, details = undefined) {
  console.error(`[check-local-admin-actions] ${message}`);
  if (details) {
    console.error(JSON.stringify(details, null, 2));
  }
  process.exit(1);
}

function runSeed(script, env = {}, args = []) {
  const scriptPath = fileURLToPath(new URL(`../../scripts/${script}`, import.meta.url));
  const result = spawnSync('php', [scriptPath, '--json', ...args], {
    env: {
      ...process.env,
      LOCAL_SMOKE_ADMIN_LOGIN_ID: adminId,
      LOCAL_SMOKE_ADMIN_LOGIN_PASSWORD: adminPassword,
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
    // handled below
  }

  return { response, payload };
}

async function apiJson(path, options = {}) {
  const { response, payload } = await fetchApi(path, options);

  if (!response.ok || !payload?.success) {
    fail(`API request failed: ${path}`, {
      status: response.status,
      message: payload?.message || response.statusText,
    });
  }

  return payload;
}

async function expectApiMissing(path, options = {}, label = path) {
  const { response, payload } = await fetchApi(path, options);
  if (response.status !== 404 || payload?.success) {
    fail(`${label} still exists`, {
      status: response.status,
      payload,
    });
  }
}

async function login() {
  const payload = await apiJson('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ mb_id: adminId, mb_password: adminPassword }),
  });
  const token = payload.data?.token;
  const refreshToken = payload.data?.refresh_token;
  if (!token) {
    fail('admin login did not return a token');
  }
  return { token, refreshToken };
}

function authHeaders(token) {
  return { Authorization: `Bearer ${token}` };
}

async function verifyOrderActions(page, token, orderId) {
  await page.goto(`${appUrl}/admin/shop/orders/${orderId}`, {
    waitUntil: 'networkidle',
  });
  await expectVisibleText(page, `주문 상세 - ${orderId}`);

  await page.locator('#tracking').fill(trackingNumber);
  await page.locator('button[role="combobox"]').click();
  await page.getByRole('option', { name: '배송' }).click();

  const [statusResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/admin/shop/orders/${orderId}`) &&
        response.request().method() === 'PATCH'
    ),
    page.getByRole('button', { name: '상태 변경' }).click(),
  ]);
  await assertJsonResponse(statusResponse, 'order status update');
  await expectVisibleText(page, '배송');

  const patched = await apiJson(`/admin/shop/orders/${orderId}`, {
    headers: authHeaders(token),
  });
  if (
    patched.data?.od_status !== '배송' ||
    patched.data?.od_invoice !== trackingNumber ||
    patched.data?.items?.[0]?.ct_status !== '배송'
  ) {
    fail('order status update did not persist through the API', patched.data);
  }

  page.once('dialog', (dialog) => dialog.accept());
  const [cancelResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/admin/shop/orders/${orderId}/cancel`) &&
        response.request().method() === 'PATCH'
    ),
    page.getByRole('button', { name: '취소/환불' }).click(),
  ]);
  await assertJsonResponse(cancelResponse, 'order cancel');
  await expectVisibleText(page, '취소');

  const cancelled = await apiJson(`/admin/shop/orders/${orderId}`, {
    headers: authHeaders(token),
  });
  if (
    cancelled.data?.od_status !== '취소' ||
    cancelled.data?.items?.[0]?.ct_status !== '취소'
  ) {
    fail('order cancel did not persist through the API', cancelled.data);
  }

  return {
    orderId,
    statusUpdated: patched.data.od_status,
    cancelled: cancelled.data.od_status,
  };
}

async function verifyQaAnswerAction(page, token, qaId) {
  const answerSubject = `RE: Next.js admin smoke ${Date.now()}`;
  const answerContent = `Answered by local admin action smoke at ${new Date().toISOString()}.`;

  await page.goto(`${appUrl}/admin/qas/${qaId}`, {
    waitUntil: 'networkidle',
  });
  await expectVisibleText(page, '답변 등록');

  await page.locator('#answer_subject').fill(answerSubject);
  await page.locator('#answer_content').fill(answerContent);

  const [answerResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/qas/${qaId}/answer`) &&
        response.request().method() === 'POST'
    ),
    page.getByRole('button', { name: '답변 저장' }).click(),
  ]);
  await assertJsonResponse(answerResponse, 'Q&A answer');
  await expectVisibleText(page, '답변완료');

  const answered = await apiJson(`/qas/${qaId}`, {
    headers: authHeaders(token),
  });
  if (
    answered.data?.qa_status !== 1 ||
    answered.data?.answer?.qa_subject !== answerSubject ||
    answered.data?.answer?.qa_content !== answerContent
  ) {
    fail('Q&A answer did not persist through the API', answered.data);
  }

  return {
    qaId,
    status: answered.data.qa_status,
    answerSubject: answered.data.answer.qa_subject,
  };
}

async function verifyCatalogActions(page, token) {
  await cleanupCatalogSmoke(token);

  await page.goto(`${appUrl}/admin/shop/categories`, {
    waitUntil: 'networkidle',
  });
  await page.getByRole('button', { name: '분류 추가', exact: true }).click();
  await page.locator('#ca_id').fill(smokeCategoryId);
  await page.locator('#ca_name').fill(smokeCategoryName);
  await page.locator('#ca_order').fill('88');

  const [categoryCreateResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes('/admin/shop/categories') &&
        response.request().method() === 'POST'
    ),
    page.getByRole('button', { name: '추가', exact: true }).click(),
  ]);
  await assertJsonResponse(categoryCreateResponse, 'category create');
  await expectVisibleText(page, smokeCategoryId);

  const createdCategory = await apiJson(`/admin/shop/categories/${smokeCategoryId}`, {
    headers: authHeaders(token),
  });
  if (createdCategory.data?.ca_name !== smokeCategoryName) {
    fail('category create did not persist through the API', createdCategory.data);
  }

  await categoryRow(page, smokeCategoryId).locator('button[title="수정"]').click();
  await page.locator('#ca_name').fill(smokeCategoryNameUpdated);

  const [categoryUpdateResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/admin/shop/categories/${smokeCategoryId}`) &&
        response.request().method() === 'PATCH'
    ),
    page.getByRole('button', { name: '수정', exact: true }).click(),
  ]);
  await assertJsonResponse(categoryUpdateResponse, 'category update');
  await expectVisibleText(page, smokeCategoryNameUpdated);

  const updatedCategory = await apiJson(`/admin/shop/categories/${smokeCategoryId}`, {
    headers: authHeaders(token),
  });
  if (updatedCategory.data?.ca_name !== smokeCategoryNameUpdated) {
    fail('category update did not persist through the API', updatedCategory.data);
  }

  await page.goto(`${appUrl}/admin/shop/products/new`, {
    waitUntil: 'networkidle',
  });
  await expectVisibleText(page, '상품 등록');
  await page.locator('#it_id').fill(smokeProductId);
  await page.locator('#it_name').fill(smokeProductName);
  await page.locator('button[role="combobox"]').first().click();
  await page.getByRole('option', { name: smokeCategoryNameUpdated }).click();
  await page.locator('#it_basic_price').fill('12345');
  await page.locator('#it_cust_price').fill('23456');
  await page.locator('#it_point').fill('120');
  await page.locator('#it_stock_qty').fill('17');
  await page.locator('#it_content').fill('Local admin action smoke product detail.');
  await page.locator('#it_explan').fill('Local admin action smoke product summary.');

  const [productCreateResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes('/admin/shop/products') &&
        response.request().method() === 'POST'
    ),
    page.getByRole('button', { name: '저장' }).click(),
  ]);
  const productCreatePayload = await assertJsonResponse(productCreateResponse, 'product create');
  if (productCreatePayload.data?.it_id !== smokeProductId) {
    fail('product create returned an unexpected product id', productCreatePayload.data);
  }

  const createdProduct = await apiJson(`/admin/shop/products/${smokeProductId}`, {
    headers: authHeaders(token),
  });
  if (
    createdProduct.data?.it_name !== smokeProductName ||
    createdProduct.data?.ca_id !== smokeCategoryId ||
    createdProduct.data?.it_basic_price !== 12345
  ) {
    fail('product create did not persist through the API', createdProduct.data);
  }

  await page.goto(`${appUrl}/admin/shop/products/${smokeProductId}`, {
    waitUntil: 'networkidle',
  });
  await expectVisibleText(page, `상품 수정 - ${smokeProductId}`);
  await page.locator('#it_name').fill(smokeProductNameUpdated);
  await page.locator('#it_stock_qty').fill('23');

  const [productUpdateResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/admin/shop/products/${smokeProductId}`) &&
        response.request().method() === 'PATCH'
    ),
    page.getByRole('button', { name: '저장' }).click(),
  ]);
  await assertJsonResponse(productUpdateResponse, 'product update');

  const updatedProduct = await apiJson(`/admin/shop/products/${smokeProductId}`, {
    headers: authHeaders(token),
  });
  if (
    updatedProduct.data?.it_name !== smokeProductNameUpdated ||
    updatedProduct.data?.it_stock_qty !== 23
  ) {
    fail('product update did not persist through the API', updatedProduct.data);
  }

  await page.goto(`${appUrl}/admin/shop/products?stx=${encodeURIComponent(smokeProductId)}`, {
    waitUntil: 'networkidle',
  });
  await expectVisibleText(page, smokeProductId);
  page.once('dialog', (dialog) => dialog.accept());
  const [productDeleteResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/admin/shop/products/${smokeProductId}`) &&
        response.request().method() === 'DELETE'
    ),
    page.locator('tr', { hasText: smokeProductId }).first().locator('button').last().click(),
  ]);
  await assertJsonResponse(productDeleteResponse, 'product delete');
  await expectApiMissing(
    `/admin/shop/products/${smokeProductId}`,
    { headers: authHeaders(token) },
    'deleted product'
  );

  await page.goto(`${appUrl}/admin/shop/categories`, {
    waitUntil: 'networkidle',
  });
  await expectVisibleText(page, smokeCategoryId);
  page.once('dialog', (dialog) => dialog.accept());
  const [categoryDeleteResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/admin/shop/categories/${smokeCategoryId}`) &&
        response.request().method() === 'DELETE'
    ),
    categoryRow(page, smokeCategoryId).locator('button[title="삭제"]').click(),
  ]);
  await assertJsonResponse(categoryDeleteResponse, 'category delete');
  await expectApiMissing(
    `/admin/shop/categories/${smokeCategoryId}`,
    { headers: authHeaders(token) },
    'deleted category'
  );

  return {
    productId: smokeProductId,
    productUpdated: smokeProductNameUpdated,
    categoryId: smokeCategoryId,
    categoryDeleted: true,
  };
}

async function verifyBoardActions(page, token) {
  await cleanupBoardSmoke(token);

  await page.goto(`${appUrl}/admin/boards`, {
    waitUntil: 'networkidle',
  });
  await page.getByRole('button', { name: '새 게시판', exact: true }).click();
  await page.locator('#bo_table').fill(smokeBoardId);
  await page.locator('#bo_subject').fill(smokeBoardSubject);

  const [boardCreateResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes('/admin/boards') &&
        response.request().method() === 'POST'
    ),
    page.getByRole('button', { name: '생성', exact: true }).click(),
  ]);
  await assertJsonResponse(boardCreateResponse, 'board create');
  await expectVisibleText(page, smokeBoardId);

  const createdBoard = await apiJson(`/admin/boards/${smokeBoardId}`, {
    headers: authHeaders(token),
  });
  if (createdBoard.data?.bo_subject !== smokeBoardSubject) {
    fail('board create did not persist through the API', createdBoard.data);
  }

  await page.goto(`${appUrl}/admin/boards/${smokeBoardId}`, {
    waitUntil: 'networkidle',
  });
  await expectVisibleText(page, `게시판 설정 - ${smokeBoardId}`);
  await page.locator('#bo_subject').fill(smokeBoardSubjectUpdated);
  await page.locator('#bo_category_list').fill('alpha,beta');
  await page.locator('#bo_page_rows').fill('9');

  const [boardUpdateResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/admin/boards/${smokeBoardId}`) &&
        response.request().method() === 'PATCH'
    ),
    page.getByRole('button', { name: '저장' }).click(),
  ]);
  await assertJsonResponse(boardUpdateResponse, 'board update');

  const updatedBoard = await apiJson(`/admin/boards/${smokeBoardId}`, {
    headers: authHeaders(token),
  });
  if (
    updatedBoard.data?.bo_subject !== smokeBoardSubjectUpdated ||
    updatedBoard.data?.bo_category_list !== 'alpha,beta' ||
    updatedBoard.data?.bo_page_rows !== 9
  ) {
    fail('board update did not persist through the API', updatedBoard.data);
  }

  await page.goto(`${appUrl}/admin/boards`, {
    waitUntil: 'networkidle',
  });
  await expectVisibleText(page, smokeBoardId);
  page.once('dialog', (dialog) => dialog.accept());
  const [boardDeleteResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/admin/boards/${smokeBoardId}`) &&
        response.request().method() === 'DELETE'
    ),
    page.locator('tr', { hasText: smokeBoardId }).first().locator('button').last().click(),
  ]);
  await assertJsonResponse(boardDeleteResponse, 'board delete');
  await expectApiMissing(
    `/admin/boards/${smokeBoardId}`,
    { headers: authHeaders(token) },
    'deleted board'
  );

  return {
    boardId: smokeBoardId,
    boardUpdated: smokeBoardSubjectUpdated,
    boardDeleted: true,
  };
}

async function verifyMemberActions(page, token, memberId) {
  await page.goto(`${appUrl}/admin/members/${memberId}`, {
    waitUntil: 'networkidle',
  });
  await expectVisibleText(page, `회원 수정 - ${memberId}`);

  await page.locator('#mb_nick').fill(smokeMemberNickUpdated);
  await page.locator('#mb_name').fill(smokeMemberNameUpdated);
  await page.locator('#mb_email').fill(smokeMemberEmailUpdated);
  await page.locator('#mb_level').fill('3');
  await page.locator('#mb_point').fill('321');
  await page.locator('#mb_hp').fill('010-1111-2222');
  await page.locator('#mb_tel').fill('02-111-2222');

  const [memberUpdateResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/admin/members/${memberId}`) &&
        response.request().method() === 'PATCH'
    ),
    page.getByRole('button', { name: '저장' }).click(),
  ]);
  await assertJsonResponse(memberUpdateResponse, 'member update');

  const updatedMember = await apiJson(`/admin/members/${memberId}`, {
    headers: authHeaders(token),
  });
  if (
    updatedMember.data?.mb_nick !== smokeMemberNickUpdated ||
    updatedMember.data?.mb_name !== smokeMemberNameUpdated ||
    updatedMember.data?.mb_email !== smokeMemberEmailUpdated ||
    updatedMember.data?.mb_level !== 3 ||
    updatedMember.data?.mb_point !== 321
  ) {
    fail('member update did not persist through the API', updatedMember.data);
  }

  page.once('dialog', (dialog) => dialog.accept());
  const [banResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/admin/members/${memberId}/ban`) &&
        response.request().method() === 'PATCH'
    ),
    page.getByRole('button', { name: '차단' }).click(),
  ]);
  await assertJsonResponse(banResponse, 'member ban');

  const bannedMember = await apiJson(`/admin/members/${memberId}`, {
    headers: authHeaders(token),
  });
  if (!bannedMember.data?.mb_intercept_date) {
    fail('member ban did not persist through the API', bannedMember.data);
  }

  await page.goto(`${appUrl}/admin/members/${memberId}`, {
    waitUntil: 'networkidle',
  });
  page.once('dialog', (dialog) => dialog.accept());
  const [leaveResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().includes(`/admin/members/${memberId}/leave`) &&
        response.request().method() === 'PATCH'
    ),
    page.getByRole('button', { name: '탈퇴처리' }).click(),
  ]);
  await assertJsonResponse(leaveResponse, 'member leave');

  const leftMember = await apiJson(`/admin/members/${memberId}`, {
    headers: authHeaders(token),
  });
  if (!leftMember.data?.mb_leave_date) {
    fail('member leave did not persist through the API', leftMember.data);
  }

  return {
    memberId,
    memberUpdated: updatedMember.data.mb_nick,
    memberBanned: Boolean(bannedMember.data.mb_intercept_date),
    memberLeft: Boolean(leftMember.data.mb_leave_date),
  };
}

function categoryRow(page, categoryId) {
  return page.locator('div.rounded-md').filter({ hasText: `(${categoryId})` }).first();
}

async function cleanupCatalogSmoke(token) {
  const headers = authHeaders(token);

  const product = await fetchApi(`/admin/shop/products/${smokeProductId}`, { headers });
  if (product.response.ok && product.payload?.success) {
    const productName = String(product.payload.data?.it_name || '');
    if (!productName.includes(smokeProductName)) {
      fail('refusing to delete an existing non-smoke product', product.payload.data);
    }
    await apiJson(`/admin/shop/products/${smokeProductId}`, {
      method: 'DELETE',
      headers,
    });
  } else if (product.response.status !== 404) {
    fail('failed to inspect existing smoke product before cleanup', {
      status: product.response.status,
      payload: product.payload,
    });
  }

  const category = await fetchApi(`/admin/shop/categories/${smokeCategoryId}`, { headers });
  if (category.response.ok && category.payload?.success) {
    const categoryName = String(category.payload.data?.ca_name || '');
    if (!categoryName.includes(smokeCategoryName)) {
      fail('refusing to delete an existing non-smoke category', category.payload.data);
    }
    await apiJson(`/admin/shop/categories/${smokeCategoryId}`, {
      method: 'DELETE',
      headers,
    });
  } else if (category.response.status !== 404) {
    fail('failed to inspect existing smoke category before cleanup', {
      status: category.response.status,
      payload: category.payload,
    });
  }
}

async function cleanupBoardSmoke(token) {
  const headers = authHeaders(token);
  const board = await fetchApi(`/admin/boards/${smokeBoardId}`, { headers });
  if (board.response.ok && board.payload?.success) {
    const subject = String(board.payload.data?.bo_subject || '');
    if (!subject.includes(smokeBoardSubject)) {
      fail('refusing to delete an existing non-smoke board', board.payload.data);
    }
    await apiJson(`/admin/boards/${smokeBoardId}`, {
      method: 'DELETE',
      headers,
    });
  } else if (board.response.status !== 404) {
    fail('failed to inspect existing smoke board before cleanup', {
      status: board.response.status,
      payload: board.payload,
    });
  }
}

async function expectVisibleText(page, text) {
  try {
    await page.getByText(text, { exact: false }).first().waitFor({
      state: 'visible',
      timeout: 10000,
    });
  } catch {
    fail(`expected visible text was not found: ${text}`, {
      url: page.url(),
    });
  }
}

async function assertJsonResponse(response, label) {
  let payload = null;
  try {
    payload = await response.json();
  } catch {
    fail(`${label} response was not JSON`, {
      status: response.status(),
      url: response.url(),
    });
  }
  if (!response.ok() || !payload?.success) {
    fail(`${label} response failed`, {
      status: response.status(),
      url: response.url(),
      payload,
    });
  }
  return payload;
}

runSeed('seed_nextjs_smoke_user.php', {
  LOCAL_SMOKE_ADMIN_LOGIN_ID: adminId,
  LOCAL_SMOKE_ADMIN_LOGIN_PASSWORD: adminPassword,
}, ['--admin']);
const seededMember = runSeed('seed_nextjs_smoke_user.php', {
  LOCAL_SMOKE_LOGIN_ID: smokeMemberId,
  LOCAL_SMOKE_LOGIN_PASSWORD: smokeMemberPassword,
});
const seededOrder = runSeed('seed_nextjs_smoke_order.php');
const seededQa = runSeed('seed_nextjs_smoke_qa.php');

const credentials = await login();
const browser = await chromium.launch({ headless: true });

try {
  const context = await browser.newContext({
    viewport: { width: 1366, height: 900 },
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
  const results = [];
  results.push(await verifyOrderActions(page, credentials.token, seededOrder.id));
  results.push(await verifyQaAnswerAction(page, credentials.token, seededQa.id));
  results.push(await verifyCatalogActions(page, credentials.token));
  results.push(await verifyBoardActions(page, credentials.token));
  results.push(await verifyMemberActions(page, credentials.token, seededMember.id));
  await context.close();

  console.table(results);
  console.log(`[check-local-admin-actions] app=${appUrl}`);
  console.log(`[check-local-admin-actions] api=${expectedApiUrl}`);
} finally {
  await browser.close();
  await cleanupCatalogSmoke(credentials.token);
  await cleanupBoardSmoke(credentials.token);
  runSeed('seed_nextjs_smoke_user.php', {
    LOCAL_SMOKE_LOGIN_ID: smokeMemberId,
    LOCAL_SMOKE_LOGIN_PASSWORD: smokeMemberPassword,
  });
  runSeed('seed_nextjs_smoke_order.php');
  runSeed('seed_nextjs_smoke_qa.php');
}
