import { test, expect } from '@playwright/test';

test('헤더 메뉴가 DB에서 로드되어 표시되는지 확인', async ({ page }) => {
  await page.goto('/', { waitUntil: 'networkidle' });

  // 메뉴 항목들이 헤더에 보이는지 확인
  const header = page.locator('header');

  // 메뉴가 로드될 때까지 대기
  await page.waitForTimeout(1000);

  const headerText = await header.textContent();
  console.log(`  → 헤더 텍스트: ${headerText?.substring(0, 200)}`);

  // 그누보드5 메뉴 테이블에서 가져온 메뉴가 보이는지
  const hasMenu = headerText?.includes('쇼핑몰') || headerText?.includes('SIR') || headerText?.includes('스킨');
  console.log(`  → DB 메뉴 로드: ${hasMenu ? '성공' : '실패'}`);
  expect(hasMenu).toBeTruthy();

  if (process.env.UI_SMOKE_WRITE_SCREENSHOTS === '1') {
    await page.screenshot({ path: 'tests/header-menu.png' });
  }
});
