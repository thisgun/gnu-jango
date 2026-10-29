import { test, expect, type APIRequestContext, type Locator, type Page } from '@playwright/test';

/**
 * 쇼핑몰 주문 E2E — Django가 직접 서비스하는 Next.js 정적 테마를 실제 사용자처럼 조작한다.
 *
 *   회원: 로그인 → 상품 2개 장바구니 담기(한 개는 수량 2) → 장바구니 → 주문서 작성 → 무통장입금 →
 *         주문할인 쿠폰 + 포인트 1,000점 → 결제하기 → 주문 상세(번호·상태·금액) → API로 금액·재고·
 *         포인트·쿠폰 확인 → 주문 취소로 재고·포인트·쿠폰이 돌아오는지 확인(그래서 다시 돌려도 된다)
 *   비회원: 상품 담기 → 비회원 주문(주문 비밀번호) → 무통장입금 → 주문 상세 → API 확인
 *
 * 데이터는 `python manage.py seed_e2e_shop` 이 만든다(README 개발 점검 참고). 실제 PG는 쓰지 않는다.
 * E2E_BASE_URL(또는 PLAYWRIGHT_BASE_URL)이 없으면 건너뛴다. PLAYWRIGHT_BASE_URL만 있고 시드 데이터가
 * 없는 서버(예: Next dev 서버)라면 역시 건너뛰고, E2E_BASE_URL을 준 경우에는 실패로 알린다.
 */

const E2E_BASE_URL = process.env.E2E_BASE_URL || '';
const BASE_URL = (E2E_BASE_URL || process.env.PLAYWRIGHT_BASE_URL || '').replace(/\/+$/, '');
const MEMBER_ID = process.env.E2E_MEMBER_ID || 'e2e_buyer';
const MEMBER_PASSWORD = process.env.E2E_MEMBER_PASSWORD || 'e2e-Checkout-Pass-2026';
// seed_e2e_shop 의 상품·쿠폰과 같은 값
const PRODUCT_A = process.env.E2E_PRODUCT_A || 'E2E0000001';
const PRODUCT_B = process.env.E2E_PRODUCT_B || 'E2E0000002';
const COUPON_SUBJECT = 'E2E 주문할인 3,000원';
const POINTS_TO_USE = 1000;
const SHIPPING_FEE = 3000;
const CANCEL_REASON = 'E2E 테스트 주문 취소';

test.skip(!BASE_URL, 'Set E2E_BASE_URL to a Django server seeded with `manage.py seed_e2e_shop`.');
test.use({ baseURL: BASE_URL || undefined, trace: 'retain-on-failure' });

type Product = { it_id: string; it_name: string; it_price: number; it_stock_qty: number };
type Coupon = { cp_id: string; cp_subject: string; cp_price: number; cp_used: string };
type OrderItem = { it_id: string; ct_qty: number; ct_price: number; ct_status: string };
type Order = {
  od_id: string;
  mb_id: string;
  od_status: string;
  od_settle_case: string;
  od_bank_account: string;
  od_cart_price: number;
  od_send_cost: number;
  od_send_cost2: number;
  od_coupon: number;
  od_cart_coupon: number;
  od_send_coupon: number;
  od_receipt_point: number;
  od_receipt_price: number;
  od_misu: number;
  items: OrderItem[];
};

/** 1234567 → "1,234,567" (화면 숫자 표기) */
function digits(amount: number): string {
  return String(amount).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}
const won = (amount: number) => `${digits(amount)}원`;
const points = (amount: number) => `${digits(amount)}점`;

/** 금액 사이에 줄바꿈·요소 경계가 끼어도 맞도록 "라벨 … 금액" 정규식을 만든다. */
function amountAfter(label: string, amount: string): RegExp {
  const escape = (text: string) => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(`${escape(label)}\\s*${escape(amount)}`);
}

async function apiData<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(`/api/v1${path}`);
  expect(response.ok(), `GET /api/v1${path} → ${response.status()}`).toBeTruthy();
  return (await response.json()).data as T;
}

const product = (request: APIRequestContext, itId: string) => apiData<Product>(request, `/shop/products/${itId}`);
const pointBalance = async (request: APIRequestContext) =>
  (await apiData<{ balance: number }>(request, '/shop/points/summary')).balance;

/** window.confirm/prompt: 주문 취소의 취소사유 prompt에는 사유를 넣고 나머지는 확인한다. */
function acceptDialogs(page: Page) {
  page.on('dialog', (dialog) => {
    void (dialog.type() === 'prompt' ? dialog.accept(CANCEL_REASON) : dialog.accept());
  });
}

async function login(page: Page) {
  await page.goto('/login');
  const main = page.getByRole('main');
  await main.getByRole('textbox', { name: '아이디' }).fill(MEMBER_ID);
  await main.getByRole('textbox', { name: '비밀번호' }).fill(MEMBER_PASSWORD);
  await main.getByRole('button', { name: '로그인', exact: true }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/login'));
  await expect(page.getByRole('navigation', { name: '회원 메뉴' }).getByRole('link', { name: '로그인' })).toHaveCount(0);
}

/** 이전 실행이 남긴 장바구니가 있으면 화면의 "비우기"로 비운다. */
async function emptyCart(page: Page) {
  await page.goto('/shop/cart');
  const main = page.getByRole('main');
  const table = main.getByRole('table', { name: '장바구니 상품 목록' });
  const emptyRow = table.getByRole('cell', { name: '장바구니에 담긴 상품이 없습니다.' });
  const clearButton = main.getByRole('button', { name: '비우기' });
  await expect(emptyRow.or(clearButton)).toBeVisible();
  if (await emptyRow.isVisible()) return;
  await clearButton.click();
  await page.getByRole('alertdialog', { name: '장바구니 비우기' }).getByRole('button', { name: '삭제' }).click();
  await expect(emptyRow).toBeVisible();
}

/** 상품 상세에서 수량을 맞추고 "장바구니"를 누른다. */
async function addToCart(page: Page, item: Product, qty: number) {
  await page.goto(`/shop/${item.it_id}`);
  const main = page.getByRole('main');
  await expect(main.getByRole('heading', { level: 1, name: item.it_name })).toBeVisible();
  await expect(main.getByText(`재고: ${item.it_stock_qty}개`)).toBeVisible();
  const quantity = main.getByRole('spinbutton', { name: `${item.it_name} 수량` }).first();
  await expect(quantity).toHaveValue('1');
  for (let n = 1; n < qty; n += 1) {
    await main.getByRole('button', { name: `${item.it_name} 수량 증가` }).first().click();
  }
  await expect(quantity).toHaveValue(String(qty));
  await expect(main.getByText(amountAfter('총 금액', won(item.it_price * qty))).first()).toBeVisible();

  const added = page.waitForResponse((r) => r.url().endsWith('/api/v1/shop/cart') && r.request().method() === 'POST');
  await main.getByRole('button', { name: '장바구니', exact: true }).first().click();
  expect((await added).status()).toBe(201);
  await expect(page.getByRole('region', { name: /Notifications/ })).toContainText('장바구니에 추가되었습니다.');
}

function definition(scope: Locator, term: string): Locator {
  return scope.locator('dt', { hasText: term }).locator('xpath=following-sibling::dd[1]');
}

/** 주문자 정보 — 받으시는 분은 "주문자와 동일" */
async function fillOrderer(main: Locator, fields: { name: string; hp: string; email?: string; guestPassword?: string }) {
  const name = main.getByRole('textbox', { name: /^이름/ });
  await name.fill(fields.name);
  await main.getByRole('textbox', { name: /^휴대폰번호/ }).fill(fields.hp);
  await main.getByRole('textbox', { name: /^우편번호/ }).fill('06236');
  await main.getByRole('textbox', { name: /^기본주소/ }).fill('서울 강남구 테헤란로 152');
  await main.getByRole('textbox', { name: '상세주소' }).fill('E2E타워 101호');
  if (fields.guestPassword) await main.getByLabel(/비회원 주문 비밀번호/).fill(fields.guestPassword);
  if (fields.email) await main.getByRole('textbox', { name: '이메일' }).fill(fields.email);
  await main.getByRole('button', { name: '주문자와 동일' }).click();
  await main.getByRole('textbox', { name: '전하실 말씀' }).fill('E2E 자동 테스트 주문입니다.');
}

/** 무통장입금 선택 → 입금 계좌·입금자명 → 약관 동의 */
async function chooseBankTransfer(main: Locator, depositor: string) {
  const bank = main.getByRole('button', { name: '무통장입금' });
  await bank.click();
  await expect(bank).toHaveAttribute('aria-pressed', 'true');
  const account = main.getByRole('combobox', { name: '입금 계좌' });
  await expect(account.locator('option')).not.toHaveCount(0);
  await account.selectOption({ index: 0 });
  await main.getByRole('textbox', { name: '입금자명' }).fill(depositor);
  await main.getByRole('checkbox', { name: '전체 동의' }).check();
  await expect(main.getByRole('checkbox', { name: '[필수] 이용약관 동의' })).toBeChecked();
  await expect(main.getByRole('checkbox', { name: '[필수] 개인정보 수집 및 이용 동의' })).toBeChecked();
  return (await account.inputValue()).trim();
}

/** "N원 결제하기"를 누르고 생성된 주문번호를 돌려준다(주문 상세로 넘어갈 때까지 기다림). */
async function submitOrder(page: Page, main: Locator, payable: number): Promise<string> {
  const submit = main.getByRole('button', { name: `${won(payable)} 결제하기` });
  await expect(submit).toBeEnabled();
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/api/v1/shop/orders') && r.request().method() === 'POST',
  );
  await submit.click();
  const response = await created;
  expect(response.status(), await response.text()).toBe(201);
  const odId = String((await response.json()).data.od_id);
  expect(odId).toMatch(/^\d{14,}$/);
  // 비회원 주문은 조회용 uid가 붙는다(/shop/orders/<od_id>?uid=...)
  await page.waitForURL((url) => url.pathname.replace(/\/+$/, '') === `/shop/orders/${odId}`);
  await expect(page.getByRole('heading', { level: 1, name: '주문 상세' })).toBeVisible();
  return odId;
}

/** 주문 상세 화면: 주문번호 · 입금확인중(주문) · 무통장 · 입금 안내 금액 · 계좌 */
async function expectPlacedOrderPage(page: Page, odId: string, payable: number, account: string) {
  const main = page.getByRole('main');
  await expect(main.getByText(`주문번호: ${odId}`)).toBeVisible();
  await expect(main.getByText('입금확인중', { exact: true })).toBeVisible();
  await expect(main.getByText('결제방법: 무통장')).toBeVisible();
  await expect(main.getByText(/아래 계좌로/)).toContainText(won(payable));
  await expect(main.getByText(account, { exact: true }).first()).toBeVisible();
  await expect(definition(main, '주문번호')).toHaveText(odId);
  await expect(definition(main, '입금계좌')).toHaveText(account);
}

/** API 주문: 상태 주문 · 무통장 · 미수금 = 상품 + 배송비 − 쿠폰 − 포인트 */
function expectApiOrder(order: Order, expected: { cart: number; coupon: number; points: number; payable: number }) {
  expect(order.od_status).toBe('주문');
  expect(order.od_settle_case).toBe('무통장');
  expect(order.od_cart_price).toBe(expected.cart);
  expect(order.od_send_cost + order.od_send_cost2).toBe(SHIPPING_FEE);
  expect(order.od_coupon + order.od_cart_coupon + order.od_send_coupon).toBe(expected.coupon);
  expect(order.od_receipt_point).toBe(expected.points);
  expect(order.od_receipt_price).toBe(0);
  expect(order.od_misu).toBe(expected.payable);
  expect(order.od_cart_price + order.od_send_cost + order.od_send_cost2 - expected.coupon - expected.points).toBe(
    order.od_misu,
  );
  for (const item of order.items) expect(item.ct_status).toBe('주문');
}

async function requireSeed(request: APIRequestContext) {
  let status = 'unreachable';
  try {
    const response = await request.get(`/api/v1/shop/products/${PRODUCT_A}`);
    if (response.ok()) return;
    status = String(response.status());
  } catch {
    // 서버가 떠 있지 않음 — 아래에서 건너뛰거나 실패로 알린다
  }
  // E2E_BASE_URL을 준 실행(CI)은 시드 누락을 실패로 알린다; PLAYWRIGHT_BASE_URL만 있는 다른 실행은 건너뛴다.
  test.skip(!E2E_BASE_URL, `No seeded E2E product at ${BASE_URL} (run manage.py seed_e2e_shop).`);
  throw new Error(`Seeded product ${PRODUCT_A} at ${BASE_URL}: ${status}; run manage.py seed_e2e_shop.`);
}

test.describe('쇼핑몰 주문 E2E (무통장입금)', () => {
  test.beforeEach(async ({ request }) => {
    await requireSeed(request);
  });

  test('회원: 장바구니 → 주문서 → 쿠폰·포인트 → 무통장 주문 → 주문 상세, 취소로 원복', async ({ page }) => {
    test.setTimeout(120_000);
    acceptDialogs(page);
    const api = page.request; // 로그인 쿠키를 함께 쓴다

    await test.step('로그인', async () => {
      await login(page);
    });

    const productA = await product(api, PRODUCT_A);
    const productB = await product(api, PRODUCT_B);
    const pointsBefore = await pointBalance(api);
    const coupons = await apiData<Coupon[]>(api, '/shop/coupons/mine');
    const coupon = coupons.find((c) => c.cp_subject === COUPON_SUBJECT && !c.cp_used);
    expect(coupon, 'an unused seed coupon (rerun manage.py seed_e2e_shop)').toBeTruthy();
    expect(pointsBefore).toBeGreaterThanOrEqual(POINTS_TO_USE);
    const cart = productA.it_price + productB.it_price * 2;
    const couponDiscount = coupon!.cp_price;
    const payable = cart + SHIPPING_FEE - couponDiscount - POINTS_TO_USE;

    await test.step('장바구니 담기', async () => {
      await emptyCart(page);
      await addToCart(page, productA, 1);
      await addToCart(page, productB, 2);
    });

    await test.step('장바구니 확인 후 주문하기', async () => {
      await page.goto('/shop/cart');
      const main = page.getByRole('main');
      const table = main.getByRole('table', { name: '장바구니 상품 목록' });
      await expect(table.getByRole('link', { name: productA.it_name })).toBeVisible();
      await expect(table.getByRole('link', { name: productB.it_name })).toBeVisible();
      await expect(definition(main, '배송비')).toHaveText(won(SHIPPING_FEE));
      await expect(definition(main, '총계 가격')).toHaveText(won(cart + SHIPPING_FEE));
      await main.getByRole('link', { name: '주문하기' }).click();
      await page.waitForURL('**/shop/order');
      await expect(main.getByRole('heading', { level: 1, name: '주문/결제' })).toBeVisible();
    });

    const main = page.getByRole('main');
    let account = '';
    await test.step('주문서 작성: 주문자·배송지', async () => {
      await expect(main.getByText(productA.it_name).first()).toBeVisible();
      await expect(main.getByText(`총수량 2개 · 판매가 ${won(productB.it_price)}`)).toBeVisible();
      await fillOrderer(main, { name: 'E2E 구매자', hp: '010-1234-5678' });
    });

    await test.step('주문할인 쿠폰과 포인트 적용', async () => {
      await main.getByRole('button', { name: '주문할인 쿠폰적용' }).click();
      const dialog = page.getByRole('dialog', { name: '주문할인 쿠폰' });
      await dialog.getByRole('button', { name: new RegExp(`${COUPON_SUBJECT} 적용`) }).click();
      await expect(dialog).toBeHidden();
      await expect(main.getByText(COUPON_SUBJECT, { exact: true })).toBeVisible();
      await expect(main.getByRole('button', { name: '주문할인 쿠폰 취소' })).toBeVisible();
      await expect(definition(main, '보유 포인트')).toHaveText(points(pointsBefore));
      await main.getByRole('spinbutton', { name: /사용 포인트/ }).fill(String(POINTS_TO_USE));
    });

    await test.step('무통장입금 선택, 결제 금액 확인', async () => {
      account = await chooseBankTransfer(main, 'E2E 구매자');
      expect(account).not.toBe('');
      await expect(main).toContainText(amountAfter('상품 금액', won(cart)));
      await expect(main).toContainText(amountAfter('주문할인', `-${won(couponDiscount)}`));
      await expect(main).toContainText(amountAfter('포인트 사용', `-${won(POINTS_TO_USE)}`));
      await expect(main).toContainText(amountAfter('총 결제금액', won(payable)));
    });

    let odId = '';
    await test.step('결제하기 → 주문 상세', async () => {
      odId = await submitOrder(page, main, payable);
      await expectPlacedOrderPage(page, odId, payable, account);
      await expect(main).toContainText(amountAfter('쿠폰할인', `-${won(couponDiscount)}`));
      await expect(definition(main, '포인트사용')).toHaveText(points(POINTS_TO_USE));
      await expect(main.getByRole('link', { name: productA.it_name })).toBeVisible();
      await expect(main.getByRole('link', { name: productB.it_name })).toBeVisible();
    });

    await test.step('API: 금액·재고·포인트·쿠폰', async () => {
      const order = await apiData<Order>(api, `/shop/orders/${odId}`);
      expect(order.od_id).toBe(odId);
      expect(order.mb_id).toBe(MEMBER_ID);
      expect(order.od_bank_account).toBe(account);
      expectApiOrder(order, { cart, coupon: couponDiscount, points: POINTS_TO_USE, payable });
      expect(order.items.map((i) => [i.it_id, i.ct_qty]).sort()).toEqual([
        [PRODUCT_A, 1],
        [PRODUCT_B, 2],
      ]);
      expect((await product(api, PRODUCT_A)).it_stock_qty).toBe(productA.it_stock_qty - 1);
      expect((await product(api, PRODUCT_B)).it_stock_qty).toBe(productB.it_stock_qty - 2);
      expect(await pointBalance(api)).toBe(pointsBefore - POINTS_TO_USE);
      const used = (await apiData<Coupon[]>(api, '/shop/coupons/mine')).find((c) => c.cp_id === coupon!.cp_id);
      expect(used?.cp_used).toBe('1');
    });

    await test.step('주문 목록에 보인다', async () => {
      await page.goto('/shop/orders');
      await expect(page.getByRole('main').getByText(odId).first()).toBeVisible();
    });

    await test.step('주문 취소 → 재고·포인트·쿠폰 원복', async () => {
      await page.goto(`/shop/orders/${odId}`);
      await expect(main.getByText(`주문번호: ${odId}`)).toBeVisible();
      const cancelled = page.waitForResponse(
        (r) => r.url().includes(`/api/v1/shop/orders/${odId}`) && r.request().method() !== 'GET',
      );
      await main.getByRole('button', { name: '주문 취소' }).click();
      expect((await cancelled).ok()).toBeTruthy();
      await expect(main.getByText('주문취소', { exact: true }).first()).toBeVisible();
      await expect(main.getByRole('button', { name: '주문 취소' })).toHaveCount(0);

      const order = await apiData<Order>(api, `/shop/orders/${odId}`);
      expect(order.od_status).toBe('취소');
      expect((await product(api, PRODUCT_A)).it_stock_qty).toBe(productA.it_stock_qty);
      expect((await product(api, PRODUCT_B)).it_stock_qty).toBe(productB.it_stock_qty);
      expect(await pointBalance(api)).toBe(pointsBefore);
      const restored = (await apiData<Coupon[]>(api, '/shop/coupons/mine')).find((c) => c.cp_id === coupon!.cp_id);
      expect(restored?.cp_used).toBe('');
    });
  });

  test('비회원: 장바구니 → 비회원 주문(무통장) → 주문 상세', async ({ page }) => {
    test.setTimeout(90_000);
    acceptDialogs(page);
    const api = page.request;
    const productB = await product(api, PRODUCT_B);
    const payable = productB.it_price + SHIPPING_FEE;

    await test.step('장바구니 담기', async () => {
      await emptyCart(page);
      await addToCart(page, productB, 1);
      await page.goto('/shop/cart');
      await expect(definition(page.getByRole('main'), '총계 가격')).toHaveText(won(payable));
      await page.getByRole('main').getByRole('link', { name: '주문하기' }).click();
      await page.waitForURL('**/shop/order');
    });

    const main = page.getByRole('main');
    let account = '';
    await test.step('비회원 주문서 작성', async () => {
      await expect(main.getByRole('heading', { level: 1, name: '주문/결제' })).toBeVisible();
      await fillOrderer(main, {
        name: 'E2E 비회원',
        hp: '010-9876-5432',
        email: 'guest@e2e.example.test',
        guestPassword: 'e2e1234',
      });
      // 쿠폰·포인트는 회원 전용
      await expect(main.getByRole('heading', { name: '쿠폰 / 포인트' })).toHaveCount(0);
      account = await chooseBankTransfer(main, 'E2E 비회원');
      await expect(main).toContainText(amountAfter('총 결제금액', won(payable)));
    });

    await test.step('결제하기 → 주문 상세 → API', async () => {
      const odId = await submitOrder(page, main, payable);
      await expectPlacedOrderPage(page, odId, payable, account);
      // 비회원 주문 상세 API는 주문 화면 주소의 uid로 연다
      const uid = new URL(page.url()).searchParams.get('uid') || '';
      expect(uid, 'guest order detail URL carries its uid').not.toBe('');
      const order = await apiData<Order>(api, `/shop/orders/${odId}?uid=${encodeURIComponent(uid)}`);
      expect(order.mb_id).toBe('');
      expectApiOrder(order, { cart: productB.it_price, coupon: 0, points: 0, payable });
      expect(order.items.map((i) => [i.it_id, i.ct_qty])).toEqual([[PRODUCT_B, 1]]);
      expect((await product(api, PRODUCT_B)).it_stock_qty).toBe(productB.it_stock_qty - 1);
    });
  });
});
