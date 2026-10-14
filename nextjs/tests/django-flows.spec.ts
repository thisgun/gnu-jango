import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

// Regression flows against the Django-served site (PLAYWRIGHT_BASE_URL, e.g. a runserver on a
// disposable database copy). Each test skips itself unless the data it needs is configured:
//   E2E_LOGIN_ID / E2E_LOGIN_PASSWORD   a member account (level 2+)
//   E2E_PRODUCT_ID                      a simple in-stock product without options
//   E2E_NO_SECRET_BOARD                 a board with secret posts disabled and uploads allowed
//   E2E_POINT_BOARD / E2E_POINT_POST    a post with an attachment on a board whose downloads cost points
// Bank transfer must be configured for the checkout flows. Nothing here uses a real payment.

const loginId = process.env.E2E_LOGIN_ID || process.env.LOCAL_SMOKE_LOGIN_ID || '';
const loginPassword = process.env.E2E_LOGIN_PASSWORD || process.env.LOCAL_SMOKE_LOGIN_PASSWORD || '';
const productId = process.env.E2E_PRODUCT_ID || '';
const noSecretBoard = process.env.E2E_NO_SECRET_BOARD || '';
const pointBoard = process.env.E2E_POINT_BOARD || '';
const pointPost = process.env.E2E_POINT_POST || '';

async function apiData<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(`/api/v1${path}`);
  return (await response.json()).data as T;
}

async function loginByApi(request: APIRequestContext) {
  const response = await request.post('/api/v1/auth/login', { data: { mb_id: loginId, password: loginPassword } });
  expect(response.ok()).toBeTruthy();
}

async function emptyCartThenAdd(request: APIRequestContext, quantity = 1) {
  const cart = await apiData<{ items?: { ct_id: string }[] }>(request, '/shop/cart');
  for (const item of cart.items || []) await request.delete(`/api/v1/shop/cart/${item.ct_id}`);
  const added = await request.post('/api/v1/shop/cart', { data: { it_id: productId, ct_qty: quantity } });
  expect(added.ok()).toBeTruthy();
}

async function openWriteForm(page: Page, boTable: string) {
  await page.goto(`/boards/${encodeURIComponent(boTable)}/write`);
  await expect(page.locator('#wr_subject')).toBeVisible({ timeout: 25000 });
  await page.waitForTimeout(1500);
}

test('a wrong login is explained in Korean', async ({ page }) => {
  await page.goto('/login');
  await page.locator('input[name="mb_id"]').fill('no-such-member');
  await page.locator('input[name="mb_password"]').fill('wrong-password-1');
  await page.getByRole('button', { name: /^로그인/ }).first().click();
  await expect(page.getByText('아이디 또는 비밀번호가 올바르지 않습니다.').first()).toBeVisible();
  await expect(page.getByText('Invalid member ID or password.')).toHaveCount(0);
});

test('a guest can order by bank transfer and look the order up with its password', async ({ page, request }) => {
  test.skip(!productId, 'Set E2E_PRODUCT_ID to run the guest checkout.');
  await page.context().request.post('/api/v1/shop/cart', { data: { it_id: productId, ct_qty: 1 } });
  await page.goto('/shop/order');
  await expect(page.getByRole('button', { name: /결제하기/ })).toBeVisible({ timeout: 25000 });
  await page.getByLabel(/^이름/).first().fill('E2E 비회원');
  await page.getByPlaceholder('010-0000-0000').first().fill('010-7777-8888');
  await page.getByLabel(/우편번호/).first().fill('06236');
  await page.getByLabel(/기본주소/).first().fill('서울 강남구 테헤란로 2');
  await page.getByLabel(/비회원 주문 비밀번호/).fill('e2epass1');
  await page.getByLabel(/전체 동의/).check();
  await page.getByLabel(/입금자명/).fill('E2E 비회원');
  await page.getByRole('button', { name: /결제하기/ }).click();
  await page.waitForURL(/\/shop\/orders\/\d+\?uid=/, { timeout: 20000 });
  const orderId = page.url().match(/orders\/(\d+)/)?.[1] || '';

  const stranger = await request.get(`/api/v1/shop/orders/${orderId}`);
  expect(stranger.status()).toBeGreaterThanOrEqual(400);

  const lookup = await page.context().browser()!.newPage();
  await lookup.goto(`${new URL(page.url()).origin}/shop/orders`);
  await lookup.locator('#guest-order-id').fill(orderId);
  await lookup.locator('#guest-order-password').fill('wrongpass9');
  await lookup.getByRole('button', { name: '주문조회' }).click();
  await expect(lookup.getByText('주문번호 또는 주문 비밀번호가 올바르지 않습니다.').first()).toBeVisible();
  await lookup.locator('#guest-order-password').fill('e2epass1');
  await lookup.getByRole('button', { name: '주문조회' }).click();
  await lookup.waitForURL(new RegExp(`/shop/orders/${orderId}`), { timeout: 15000 });
  await lookup.close();
});

test('points on the checkout are rounded to the shop unit', async ({ page }) => {
  test.skip(!loginId || !loginPassword || !productId, 'Set E2E_LOGIN_ID, E2E_LOGIN_PASSWORD and E2E_PRODUCT_ID.');
  const request = page.context().request;
  await loginByApi(request);
  const policy = await apiData<{ settle_min_point: number; settle_max_point: number; settle_point_unit: number }>(request, '/shop/policy');
  const { balance } = await apiData<{ balance: number }>(request, '/shop/points/summary');
  const unit = Math.max(1, policy.settle_point_unit);
  test.skip(policy.settle_max_point < unit || balance < Math.max(policy.settle_min_point, unit * 2), 'The member needs enough points and the shop a point maximum.');
  await emptyCartThenAdd(request);

  await page.goto('/shop/order');
  await expect(page.getByRole('button', { name: /결제하기/ })).toBeVisible({ timeout: 25000 });
  // coupons and points load after the form; wait for the balance as a buyer would
  await expect(page.locator('.shop-order-point').getByText(`${balance.toLocaleString('ko-KR')}점`, { exact: true }).first()).toBeVisible({ timeout: 15000 });
  const pointInput = page.locator('#order-point-use');
  await pointInput.fill(String(unit + 1));
  await pointInput.blur();
  await expect(pointInput).toHaveValue(String(unit));
});

test('a board without secret posts offers no secret checkbox and a failed upload does not duplicate the post', async ({ page }) => {
  test.skip(!loginId || !loginPassword || !noSecretBoard, 'Set E2E_LOGIN_ID, E2E_LOGIN_PASSWORD and E2E_NO_SECRET_BOARD.');
  const request = page.context().request;
  await loginByApi(request);
  const total = async () =>
    (await (await request.get(`/api/v1/boards/${encodeURIComponent(noSecretBoard)}/posts?per_page=1`)).json()).meta?.total as number;

  await openWriteForm(page, noSecretBoard);
  await expect(page.locator('#wr_secret')).toHaveCount(0);

  const before = await total();
  await page.locator('#wr_subject').fill('E2E 첨부 재시도');
  await page.locator('[contenteditable=true]').first().click();
  await page.keyboard.type('본문');
  await page.locator('input[type=file][aria-label="첨부파일 선택"]').setInputFiles({
    name: 'refused.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('not an allowed extension'),
  });
  await page.getByRole('button', { name: /작성 완료/ }).click();
  await expect(page.getByText(/글은 등록되었지만 첨부파일을 올리지 못했습니다/)).toBeVisible({ timeout: 15000 });

  await page.getByRole('button', { name: '첨부 제거' }).first().click();
  await page.locator('#wr_subject').fill('E2E 첨부 재시도 (수정)');
  await page.getByRole('button', { name: /작성 완료/ }).click();
  await page.waitForURL((url) => !url.pathname.endsWith('/write'), { timeout: 20000 });
  expect((await total()) - before).toBe(1);
});

test('a paid download asks first and charges the points once', async ({ page }) => {
  test.skip(!loginId || !loginPassword || !pointBoard || !pointPost, 'Set E2E_LOGIN_ID, E2E_LOGIN_PASSWORD, E2E_POINT_BOARD and E2E_POINT_POST.');
  const request = page.context().request;
  await loginByApi(request);
  const board = await apiData<{ bo_download_point: number }>(request, `/boards/${encodeURIComponent(pointBoard)}`);
  test.skip(!(board.bo_download_point < 0), 'The board must charge points for downloads.');
  const balance = async () => (await apiData<{ balance: number }>(request, '/shop/points/summary')).balance;

  await page.goto(`/boards/${encodeURIComponent(pointBoard)}/${pointPost}`);
  const link = page.locator('section', { hasText: '첨부파일' }).locator('a').first();
  await expect(link).toBeVisible({ timeout: 25000 });
  const before = await balance();
  const messages: string[] = [];
  page.on('dialog', (dialog) => {
    messages.push(dialog.message());
    void dialog.accept();
  });

  const first = page.waitForEvent('download');
  await link.click();
  await first;
  const afterFirst = await balance();
  const second = page.waitForEvent('download');
  await link.click();
  await second;

  expect(messages[0]).toContain('포인트가 차감');
  // Charged on the first download unless this member already paid for this post earlier.
  expect([before + board.bo_download_point, before]).toContain(afterFirst);
  expect(await balance()).toBe(afterFirst);
});
