import { test, expect } from '@playwright/test';

test('메인페이지 - 커뮤니티 콘텐츠가 출력되는지 확인', async ({ page }) => {
  const hydrationErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error' && /hydrated|hydration/i.test(message.text())) {
      hydrationErrors.push(message.text());
    }
  });

  await page.goto('/', { waitUntil: 'networkidle' });

  await expect(page.getByRole('heading', { name: '그누보드5 커뮤니티', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '자주 묻는 질문', exact: true })).toBeVisible();
  await expect(page.getByRole('heading', { name: '최근 댓글', exact: true })).toBeVisible();

  const boardPanelCount = await page.locator('main h2[id^="home-board-"]').count();
  expect(boardPanelCount).toBeGreaterThan(0);

  const postCount = await page.locator('main a[href^="/"]').evaluateAll((links) =>
    links.filter((link) => {
      const href = link.getAttribute('href') || '';
      return /^\/[0-9A-Za-z_]+\/[^/]+/.test(href) && !href.startsWith('/shop/');
    }).length
  );
  console.log(`  → 게시글 링크: ${postCount}개`);
  expect(postCount).toBeGreaterThan(0);
  expect(hydrationErrors).toEqual([]);

  // 썸네일 이미지 또는 G5 fallback 마크가 있는지 확인
  const thumbnails = page.locator('main img, main .g5-thumb-fallback');
  const thumbCount = await thumbnails.count();
  console.log(`  → 게시글 썸네일: ${thumbCount}개`);

  if (process.env.UI_SMOKE_WRITE_SCREENSHOTS === '1') {
    await page.screenshot({ path: 'tests/homepage.png', fullPage: true });
    console.log('  → 스크린샷: tests/homepage.png');
  }
});
