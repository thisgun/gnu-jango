import { test, expect } from '@playwright/test';

const postPath = process.env.LOCAL_SMOKE_POST_PATH || '/free/6';

test(`게시글 상세 페이지 (${postPath}) 로드 확인`, async ({ page }) => {
  const errors: string[] = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', err => errors.push(err.message));

  const response = await page.goto(postPath, { waitUntil: 'networkidle' });
  const status = response?.status() ?? 0;
  console.log(`  → HTTP ${status}`);

  if (errors.length > 0) {
    console.log(`  → 에러 ${errors.length}개:`);
    errors.forEach(e => console.log(`    ${e.substring(0, 150)}`));
  }

  // 500이 아닌지 확인
  expect(status).not.toBe(500);

  // 404가 아닌지 확인 (게시글이 존재해야 함)
  expect(status).not.toBe(404);

  // 게시글 제목이 보이는지
  const title = page.locator('h1');
  const titleText = await title.textContent();
  console.log(`  → 제목: ${titleText}`);
  expect(titleText).toBeTruthy();

  // 본문 영역
  const content = page.locator('.prose');
  await expect(content).toBeVisible();

  if (process.env.UI_SMOKE_WRITE_SCREENSHOTS === '1') {
    await page.screenshot({ path: 'tests/post-detail.png', fullPage: true });
    console.log('  → 스크린샷: tests/post-detail.png');
  }
});
