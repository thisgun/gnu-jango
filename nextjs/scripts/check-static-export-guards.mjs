import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const ROOT = process.cwd();
const APP_DIR = join(ROOT, 'src/app');
const NEXT_CONFIG = join(ROOT, 'next.config.ts');
const BUILD_NEXT = join(ROOT, 'scripts/build-next.mjs');
const SERVER_RUNTIME_MARKER = '@g5-server-runtime-only';
const SERVER_DYNAMIC_TOKENS = [
  'cookies(',
  'headers(',
  'NextResponse.redirect',
  'redirect(',
  'permanentRedirect(',
];

function fail(message) {
  console.error(`[check-static-export-guards] ${message}`);
  process.exit(1);
}

function read(path) {
  return readFileSync(path, 'utf8');
}

function walk(dir) {
  const entries = readdirSync(dir, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...walk(path));
      continue;
    }
    if (entry.isFile() && /\.(ts|tsx)$/.test(entry.name)) {
      files.push(path);
    }
  }

  return files;
}

function rel(path) {
  return relative(ROOT, path).replace(/\\/g, '/');
}

for (const [label, path] of [
  ['app directory', APP_DIR],
  ['next config', NEXT_CONFIG],
  ['build script', BUILD_NEXT],
]) {
  if (!existsSync(path)) {
    fail(`${label} is missing`);
  }
  if (label === 'app directory' && !statSync(path).isDirectory()) {
    fail(`${label} is not a directory`);
  }
}

const nextConfig = read(NEXT_CONFIG);
for (const token of [
  "const STATIC_EXPORT = process.env.G5_NEXT_RUNTIME !== 'server'",
  "output: 'export'",
  'unoptimized: STATIC_EXPORT',
  'const serverRuntimeConfig: NextConfig = STATIC_EXPORT',
  'async headers()',
  'async redirects()',
  'async rewrites()',
]) {
  if (!nextConfig.includes(token)) {
    fail(`next.config.ts is missing static export guard token ${token}`);
  }
}

const buildNext = read(BUILD_NEXT);
for (const token of [
  'SERVER_RUNTIME_ONLY_RE',
  'collectServerRuntimeOnlyFiles',
  '.g5-static-disabled',
]) {
  if (!buildNext.includes(token)) {
    fail(`build-next.mjs is missing server runtime exclusion token ${token}`);
  }
}

const violations = [];
for (const file of walk(APP_DIR)) {
  const source = read(file);
  const isRouteHandler = /\/route\.ts$/.test(rel(file));
  const isServerRuntimeOnly = source.includes(SERVER_RUNTIME_MARKER);
  const usesForceDynamic = /export\s+const\s+dynamic\s*=\s*["']force-dynamic["']/.test(source);
  const usesRequestState = /\brequest\.(cookies|headers|nextUrl|url|formData|json|text|arrayBuffer|blob)\b/.test(source);
  const usesDynamicServerApi = SERVER_DYNAMIC_TOKENS.some((token) => source.includes(token));

  if (isRouteHandler && (usesForceDynamic || usesRequestState || usesDynamicServerApi) && !isServerRuntimeOnly) {
    violations.push(
      `${rel(file)} uses runtime-only route behavior without ${SERVER_RUNTIME_MARKER}`,
    );
  }
}

if (violations.length > 0) {
  for (const violation of violations) {
    console.error(`[check-static-export-guards] ${violation}`);
  }
  fail('static export guard violations found');
}

console.log('[check-static-export-guards] static export route guards passed');
