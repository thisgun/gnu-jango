process.env.RUNTIME_CHECK_TARGET ||= 'live';
process.env.RUNTIME_CHECK_LABEL ||= 'check-live-youngcart-legacy-routes';
process.env.LIVE_APP_URL ||=
  process.env.NEXT_PUBLIC_APP_URL || process.env.LOCAL_APP_URL || 'https://nextjs.thisgun.net';

await import('./check-local-youngcart-legacy-routes.mjs');
