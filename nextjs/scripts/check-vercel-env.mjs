import { existsSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = fileURLToPath(new URL('..', import.meta.url));
const envProductionPath = join(repoRoot, '.env.production');
const envLocalPath = join(repoRoot, '.env.production.local');
const vercelJsonPath = join(repoRoot, 'vercel.json');

const args = new Set(process.argv.slice(2));
const strict = !args.has('--template');
const allowLocalhost = args.has('--allow-localhost');

const REQUIRED_URLS = [
  {
    name: 'NEXT_PUBLIC_API_URL',
    mustEndWith: '/api/v1',
    description: 'Django API URL exposed to browser/server components',
  },
  {
    name: 'G5_API_INTERNAL_URL',
    mustEndWith: '/api/v1',
    description: 'Django API URL reachable from Vercel server/runtime code',
  },
  {
    name: 'NEXT_PUBLIC_G5_URL',
    description: 'public Django/Gnuboard URL for legacy links and assets',
  },
  {
    name: 'NEXT_PUBLIC_APP_URL',
    description: 'public Vercel/custom-domain app URL',
  },
];

const REQUIRED_VALUES = [
  {
    name: 'NEXT_PUBLIC_AUTH_MODE',
    expected: 'g5-jwt',
    description: 'static/Vercel deployments must use Django JWT auth mode',
  },
];

const PLACEHOLDER_PATTERNS = [
  /example\.com/i,
  /your-/i,
  /localhost/i,
  /127\.0\.0\./,
  /0\.0\.0\.0/,
];

function fail(message, details = {}) {
  console.error(`[check-vercel-env] ${message}`);
  for (const [key, value] of Object.entries(details)) {
    console.error(`  ${key}: ${value}`);
  }
  process.exit(1);
}

function parseEnvFile(path) {
  if (!existsSync(path)) return {};
  const rows = {};
  const text = readFileSync(path, 'utf8');
  for (const line of text.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const match = trimmed.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!match) continue;
    const [, key, rawValue] = match;
    rows[key] = unquoteEnvValue(rawValue.trim());
  }
  return rows;
}

function unquoteEnvValue(value) {
  if (
    (value.startsWith('"') && value.endsWith('"')) ||
    (value.startsWith("'") && value.endsWith("'"))
  ) {
    return value.slice(1, -1);
  }
  return value;
}

function mergedEnv() {
  return {
    ...parseEnvFile(envProductionPath),
    ...parseEnvFile(envLocalPath),
    ...process.env,
  };
}

function isLocalUrl(url) {
  const hostname = url.hostname.toLowerCase();
  return (
    hostname === 'localhost' ||
    hostname === '::1' ||
    hostname.startsWith('127.') ||
    hostname === '0.0.0.0'
  );
}

function containsPlaceholder(value) {
  return PLACEHOLDER_PATTERNS.some((pattern) => pattern.test(value));
}

function assertUrl(env, rule) {
  const value = String(env[rule.name] || '').trim();
  if (!value) {
    fail(`${rule.name} is required`, { usage: rule.description });
  }

  let parsed;
  try {
    parsed = new URL(value);
  } catch {
    fail(`${rule.name} must be an absolute URL`, { value: redactedUrl(value) });
  }

  if (strict && parsed.protocol !== 'https:') {
    if (!(allowLocalhost && parsed.protocol === 'http:' && isLocalUrl(parsed))) {
      fail(`${rule.name} must use HTTPS for Vercel production`, {
        value: redactedUrl(value),
        hint: 'Use --allow-localhost only for local dry-runs.',
      });
    }
  }

  if (strict && containsPlaceholder(value)) {
    fail(`${rule.name} still looks like a placeholder/local URL`, {
      value: redactedUrl(value),
    });
  }

  if (rule.mustEndWith && !parsed.pathname.replace(/\/+$/, '').endsWith(rule.mustEndWith)) {
    fail(`${rule.name} must point at the Django v1 API`, {
      value: redactedUrl(value),
      expected_suffix: rule.mustEndWith,
    });
  }

  return parsed;
}

function assertValue(env, rule) {
  const value = String(env[rule.name] || '').trim();
  if (!value) {
    fail(`${rule.name} is required`, { usage: rule.description });
  }
  if (value !== rule.expected) {
    fail(`${rule.name} must be ${rule.expected}`, {
      current: value,
      usage: rule.description,
    });
  }
}

function redactedUrl(value) {
  try {
    const url = new URL(value);
    url.username = '';
    url.password = '';
    return url.toString();
  } catch {
    return value ? '<invalid-url>' : '<empty>';
  }
}

function assertVercelJson() {
  if (!existsSync(vercelJsonPath)) {
    fail('vercel.json is missing');
  }
  const text = readFileSync(vercelJsonPath, 'utf8');
  let config;
  try {
    config = JSON.parse(text);
  } catch (error) {
    fail('vercel.json is not valid JSON', { error: error.message });
  }

  const headers = JSON.stringify(config.headers || []);
  for (const token of [
    'X-Content-Type-Options',
    'Referrer-Policy',
    'Strict-Transport-Security',
    'Content-Security-Policy',
    "frame-ancestors 'none'",
    'connect-src',
    'frame-src',
  ]) {
    if (!headers.includes(token)) {
      fail(`vercel.json is missing required security header token: ${token}`);
    }
  }
}

const env = mergedEnv();
const parsedUrls = Object.fromEntries(REQUIRED_URLS.map((rule) => [rule.name, assertUrl(env, rule)]));
for (const rule of REQUIRED_VALUES) {
  assertValue(env, rule);
}
assertVercelJson();

if (strict) {
  const apiOrigin = parsedUrls.NEXT_PUBLIC_API_URL.origin;
  const internalApiOrigin = parsedUrls.G5_API_INTERNAL_URL.origin;
  const g5Origin = parsedUrls.NEXT_PUBLIC_G5_URL.origin;
  const appOrigin = parsedUrls.NEXT_PUBLIC_APP_URL.origin;

  if (apiOrigin !== internalApiOrigin) {
    console.warn('[check-vercel-env] NEXT_PUBLIC_API_URL and G5_API_INTERNAL_URL use different origins.');
  }
  if (appOrigin === apiOrigin && !args.has('--allow-same-origin')) {
    console.warn('[check-vercel-env] NEXT_PUBLIC_APP_URL and API origin are the same. This is valid only for same-domain deployments.');
  }
  if (g5Origin !== apiOrigin && !args.has('--allow-split-g5-api')) {
    console.warn('[check-vercel-env] NEXT_PUBLIC_G5_URL and API origin differ. Use this only when assets/legacy links are intentionally split.');
  }
}

console.log(
  `[check-vercel-env] ${strict ? 'strict' : 'template'} Vercel environment check passed`
);
