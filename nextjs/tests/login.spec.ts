import { test, expect } from '@playwright/test';

const loginId = process.env.LOCAL_SMOKE_LOGIN_ID || process.env.E2E_LOGIN_ID || '';
const loginPassword = process.env.LOCAL_SMOKE_LOGIN_PASSWORD || process.env.E2E_LOGIN_PASSWORD || '';

test('로그인 테스트', async ({ page }) => {
  test.skip(!loginId || !loginPassword, 'Set LOCAL_SMOKE_LOGIN_ID and LOCAL_SMOKE_LOGIN_PASSWORD to run login e2e.');

  await page.goto('/login', { waitUntil: 'networkidle' });

  await page.fill('input[name="mb_id"]', loginId);
  await page.fill('input[name="mb_password"]', loginPassword);

  await page.click('button[type="submit"]');

  await page.waitForURL('/', { timeout: 5000 });

  const cookies = await page.context().cookies();
  const tokenCookie = cookies.find((cookie) => cookie.name === 'g5_token');
  const refreshCookie = cookies.find((cookie) => cookie.name === 'g5_refresh');
  const authHintCookie = cookies.find((cookie) => cookie.name === 'g5_auth_hint');
  const visibleCookieNames = await page.evaluate(() =>
    document.cookie
      .split(';')
      .map((item) => item.trim().split('=')[0])
      .filter(Boolean)
  );

  expect(tokenCookie?.value).toBeTruthy();
  expect(tokenCookie?.httpOnly).toBe(true);
  expect(refreshCookie?.httpOnly).toBe(true);
  expect(authHintCookie?.value).toBe('1');
  expect(authHintCookie?.httpOnly).toBe(false);
  expect(visibleCookieNames).not.toContain('g5_token');
  expect(visibleCookieNames).not.toContain('g5_refresh');
  expect(visibleCookieNames).toContain('g5_auth_hint');
});
