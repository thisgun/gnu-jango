process.env.LOCAL_APP_URL ||= 'https://nextjs.thisgun.net';
process.env.LOCAL_EXPECTED_API_URL ||= 'https://nextjs.thisgun.net/api/v1';
process.env.LOCAL_REPO_API_URL ||= process.env.LOCAL_EXPECTED_API_URL;
process.env.LOCAL_SMOKE_LOGIN_ID ||= process.env.LIVE_SMOKE_LOGIN_ID || process.env.LIVE_SMOKE_ADMIN_LOGIN_ID || '';
process.env.LOCAL_SMOKE_LOGIN_PASSWORD ||=
  process.env.LIVE_SMOKE_LOGIN_PASSWORD || process.env.LIVE_SMOKE_ADMIN_LOGIN_PASSWORD || '';
process.env.LOCAL_SMOKE_ADMIN_LOGIN_ID ||= process.env.LIVE_SMOKE_ADMIN_LOGIN_ID || '';
process.env.LOCAL_SMOKE_ADMIN_LOGIN_PASSWORD ||= process.env.LIVE_SMOKE_ADMIN_LOGIN_PASSWORD || '';
process.env.LOCAL_SMOKE_AUTH_ADMIN_MEMBER_DETAIL_ID ||=
  process.env.LIVE_SMOKE_AUTH_ADMIN_MEMBER_DETAIL_ID || process.env.LIVE_SMOKE_ADMIN_LOGIN_ID || '';

process.env.LOCAL_SMOKE_POST_TITLE ||= '[Test] Long content sample';
process.env.LOCAL_SMOKE_POST_H1 ||= '[Test] Long content sample';
process.env.LOCAL_SMOKE_POST_SEO_PATH ||= '/free/test-long-content-sample/';
process.env.LOCAL_SMOKE_POST_SEO_FINAL_PATH ||= process.env.LOCAL_SMOKE_POST_PATH || '/free/6';
process.env.LOCAL_SMOKE_POST_SEO_TITLE ||= process.env.LOCAL_SMOKE_POST_TITLE;
process.env.LOCAL_SMOKE_POST_SEO_H1 ||= process.env.LOCAL_SMOKE_POST_H1;

process.env.LOCAL_SMOKE_EXPECTED_HEADER_HREFS ??= process.env.LIVE_SMOKE_EXPECTED_HEADER_HREFS || '';
process.env.LOCAL_SMOKE_BROWSER_RUNTIME_RETRIES ??=
  process.env.LIVE_SMOKE_BROWSER_RUNTIME_RETRIES || '2';
process.env.LOCAL_SMOKE_SKIP_LABELS ||=
  'shop product,shop product seo,shop category,shop type,shop largeimage';

await import('./check-local-browser.mjs');
