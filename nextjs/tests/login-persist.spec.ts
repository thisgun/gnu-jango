import { test, expect } from '@playwright/test';

const loginId = process.env.LOCAL_SMOKE_LOGIN_ID || process.env.E2E_LOGIN_ID || '';
const loginPassword = process.env.LOCAL_SMOKE_LOGIN_PASSWORD || process.env.E2E_LOGIN_PASSWORD || '';

test('로그인 후 페이지 이동해도 로그인 유지', async ({ page }) => {
  test.skip(!loginId || !loginPassword, 'Set LOCAL_SMOKE_LOGIN_ID and LOCAL_SMOKE_LOGIN_PASSWORD to run login e2e.');

  await page.goto('/login', { waitUntil: 'networkidle' });
  await page.fill('input[name="mb_id"]', loginId);
  await page.fill('input[name="mb_password"]', loginPassword);
  await page.click('button[type="submit"]');
  await page.waitForURL('/', { timeout: 5000 });

  const avatar = page.locator('header button .rounded-full, header .rounded-full');
  await expect(avatar.first()).toBeVisible({ timeout: 3000 });

  await page.goto('/boards', { waitUntil: 'networkidle' });

  const loginBtn = page.locator('header a:has-text("로그인")');
  const loginBtnCount = await loginBtn.count();
  expect(loginBtnCount).toBe(0);
});
