import { expect, test } from '@playwright/test';

const loginId = process.env.E2E_LOGIN_ID || '';
const loginPassword = process.env.E2E_LOGIN_PASSWORD || '';

test('마이페이지에서 최근 주문과 위시리스트를 바로 확인한다', async ({ page }) => {
  test.skip(!loginId || !loginPassword, 'Set E2E_LOGIN_ID and E2E_LOGIN_PASSWORD.');

  const login = await page.context().request.post('/api/v1/auth/login', {
    data: { mb_id: loginId, password: loginPassword },
  });
  expect(login.ok()).toBeTruthy();

  await page.goto('/mypage', { waitUntil: 'domcontentloaded' });

  const memberDetails = page.locator('details.collapse').filter({
    has: page.getByText('회원 상세 정보', { exact: true }),
  });
  await expect(memberDetails).toBeVisible();
  const couponLink = page.getByRole('link', { name: /\d+장/ });
  await expect(couponLink).toHaveAttribute('href', '/mypage/coupons');
  await memberDetails.click();
  await expect(memberDetails.getByText('최근 접속', { exact: true })).toBeVisible();
  await expect(memberDetails.getByText('가입일', { exact: true })).toBeVisible();
  await expect(memberDetails.getByText('주소', { exact: true })).toBeVisible();

  const orderSection = page.locator('section[aria-labelledby="recent-orders-title"]');
  const wishlistSection = page.locator('section[aria-labelledby="recent-wishlist-title"]');
  await expect(orderSection.getByRole('heading', { name: '최근 주문내역' })).toBeVisible();
  await expect(wishlistSection.getByRole('heading', { name: '최근 위시리스트' })).toBeVisible();
  await expect(
    orderSection
      .locator('table')
      .or(orderSection.getByText('주문 내역이 없습니다.', { exact: true })),
  ).toBeVisible();
  await expect(
    wishlistSection
      .locator('ul')
      .or(wishlistSection.getByText('보관 내역이 없습니다.', { exact: true })),
  ).toBeVisible();
  expect(await orderSection.locator('tbody tr').count()).toBeLessThanOrEqual(5);
  expect(await wishlistSection.locator('li').count()).toBeLessThanOrEqual(8);
  await expect(page.getByRole('link', { name: '주문 내역 더보기' })).toHaveAttribute(
    'href',
    '/mypage/orders',
  );
  await expect(page.getByRole('link', { name: '위시리스트 더보기' })).toHaveAttribute(
    'href',
    '/mypage/wishlist',
  );
});
