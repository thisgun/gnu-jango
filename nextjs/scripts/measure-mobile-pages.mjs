/** Repeatable cold-browser mobile lab measurement; no sign-in or data mutations. */
import { chromium } from '@playwright/test';
import { writeFileSync } from 'node:fs';

const baseUrl = process.argv[2] || 'http://127.0.0.1:8081';
const runs = Number(process.argv[3] || 3);
const output = process.argv[4];
if (!Number.isInteger(runs) || runs < 1 || runs > 10) throw new Error('Runs must be 1–10.');

const browser = await chromium.launch({ headless: true });
const results = [];
try {
  for (const pathname of ['/', '/shop']) {
    // Warm the backend separately; every measured browser context still starts empty.
    await fetch(new URL(pathname, baseUrl));
    for (let run = 1; run <= runs; run++) {
      const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, deviceScaleFactor: 1 });
      const page = await context.newPage();
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      const cdp = await context.newCDPSession(page);
      await cdp.send('Network.enable');
      await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: 200000, uploadThroughput: 100000, connectionType: 'cellular4g' });
      await cdp.send('Emulation.setCPUThrottlingRate', { rate: 4 });
      await page.addInitScript(() => {
        window.__lab = { lcp: null, contentReadyMs: null };
        new PerformanceObserver(list => {
          const entry = list.getEntries().at(-1);
          window.__lab.lcp = { ms: Math.round(entry.startTime), tag: entry.element?.tagName, url: entry.url };
        }).observe({ type: 'largest-contentful-paint', buffered: true });
        const observer = new MutationObserver(() => {
          const selector = location.pathname === '/' ? '.solune-latest-row' : '.shop-home-page article.sct_li a[href]';
          if (document.querySelector(selector)) {
            window.__lab.contentReadyMs = Math.round(performance.now());
            observer.disconnect();
          }
        });
        observer.observe(document, { childList: true, subtree: true });
      });
      const response = await page.goto(new URL(pathname, baseUrl).href, { waitUntil: 'load', timeout: 60000 });
      await page.waitForTimeout(8000);
      const metrics = await page.evaluate(() => {
        const resources = performance.getEntriesByType('resource');
        const totalKB = rows => Math.round(rows.reduce((n, row) => n + row.transferSize, 0) / 1024);
        const scripts = resources.filter(row => row.initiatorType === 'script');
        const fonts = resources.filter(row => /\.woff2?(\?|$)/.test(row.name));
        const css = resources.filter(row => /\.css(\?|$)/.test(row.name));
        const api = resources.filter(row => ['fetch', 'xmlhttprequest'].includes(row.initiatorType) && new URL(row.name).pathname.startsWith('/api/v1/')).map(row => ({ path: new URL(row.name).pathname, startMs: Math.round(row.startTime), durationMs: Math.round(row.duration), bytes: row.transferSize }));
        return {
          ttfbMs: Math.round(performance.getEntriesByType('navigation')[0].responseStart),
          fcpMs: Math.round(performance.getEntriesByName('first-contentful-paint')[0]?.startTime || 0),
          ...window.__lab,
          resourceCount: resources.length, transferKB: totalKB(resources),
          jsCount: scripts.length, jsTransferKB: totalKB(scripts),
          fontCount: fonts.length, fontTransferKB: totalKB(fonts), cssTransferKB: totalKB(css),
          apiCount: api.length, apiCompleteMs: Math.max(0, ...api.map(row => row.startMs + row.durationMs)), api,
          horizontalOverflow: document.documentElement.scrollWidth > innerWidth + 1,
        };
      });
      const result = { pathname, run, status: response.status(), ...metrics, errors };
      results.push(result);
      console.log(JSON.stringify(result));
      await context.close();
    }
  }
} finally {
  await browser.close();
}
const report = { baseUrl, condition: '390px; 1.6Mbps; 150ms added latency; 4x CPU; anonymous; fresh browser cache; warm backend', results };
if (output) writeFileSync(output, JSON.stringify(report, null, 2));
