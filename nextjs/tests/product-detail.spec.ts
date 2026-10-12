import { test, expect } from '@playwright/test';

const productId = process.env.LOCAL_SMOKE_SHOP_PRODUCT_ID || '1446772772';
const productPath = process.env.LOCAL_SMOKE_PRODUCT_PATH || `/shop/${productId}`;
const productName = process.env.LOCAL_SMOKE_PRODUCT_NAME || 'TH-블락체크 셔츠-그레이2';

test('상품 상세 페이지 로드 확인', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  const response = await page.goto(productPath, { waitUntil: 'networkidle' });
  await page.waitForTimeout(3000);

  const status = response?.status() ?? 0;
  const text = await page.textContent('body');
  console.log(`  → HTTP ${status}`);
  console.log(`  → 상품명 포함: ${text?.includes(productName) ? '있음' : '없음'}`);
  console.log(`  → 에러메시지: ${text?.includes('상품을 찾을 수 없습니다') ? '있음' : '없음'}`);

  if (errors.length) {
    console.log(`  → 콘솔 에러 ${errors.length}개:`);
    errors.forEach(e => console.log(`    ${e.substring(0, 200)}`));
  }

  expect(status).not.toBe(500);
  expect(status).not.toBe(404);

  await expect(page.locator('h1').first()).toContainText(productName);

  if (process.env.UI_SMOKE_WRITE_SCREENSHOTS === '1') {
    await page.screenshot({ path: 'tests/product-detail.png', fullPage: true });
  }
});
