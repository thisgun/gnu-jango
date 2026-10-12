process.env.RUNTIME_CHECK_LABEL ||= 'check-live-runtime';
process.env.LOCAL_APP_URL ||= 'https://nextjs.thisgun.net';
process.env.LOCAL_EXPECTED_API_URL ||= 'https://nextjs.thisgun.net/api/v1';
process.env.LOCAL_REPO_API_URL ||= process.env.LOCAL_EXPECTED_API_URL;
process.env.RUNTIME_REQUIRE_EXPECTED_API_SECURITY_HEADERS ||= '1';
process.env.RUNTIME_EXPECTED_API_REFERRER_POLICIES ||= 'no-referrer,strict-origin-when-cross-origin';
process.env.LOCAL_SMOKE_RSS_ALLOW_DISABLED ||= '1';

await import('./check-local-runtime.mjs');
