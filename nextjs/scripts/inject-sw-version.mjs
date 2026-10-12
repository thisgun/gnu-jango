/**
 * Build 후 out/sw.js 의 CACHE_VERSION 라인을 실제 buildId 로 치환.
 *
 * 두 상태 모두 처리:
 *   1) 첫 빌드: const CACHE_VERSION = '__SW_CACHE_VERSION__';
 *   2) 재빌드: const CACHE_VERSION = '<이전 BUILD_ID>';
 * 정규식으로 라인 자체를 갈아끼워 매 빌드마다 새 BUILD_ID 가 박힘.
 */
import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, statSync, writeFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';

const ROOT = process.cwd();
const SW_TEMPLATE_PATH = join(ROOT, 'public', 'sw.js');
const STATIC_EXPORT_DIR = process.env.G5_NEXT_DIST_DIR?.trim() || 'out';
const OUT_DIR = join(ROOT, STATIC_EXPORT_DIR);
const OUT_SW_PATH = join(OUT_DIR, 'sw.js');
const BUILD_DIR = process.env.G5_NEXT_DIST_DIR?.trim() || '.next';
const BUILD_ID_PATHS = [join(ROOT, BUILD_DIR, 'BUILD_ID'), join(ROOT, '.next', 'BUILD_ID')];
const BUILD_ID_PATH = BUILD_ID_PATHS.find((path) => existsSync(path));
const OUT_STATIC_PATH = join(OUT_DIR, '_next', 'static');

if (!BUILD_ID_PATH) {
  console.warn('[inject-sw-version] .next/BUILD_ID not found — did you run `next build`?');
  process.exit(0);
}
if (!existsSync(SW_TEMPLATE_PATH)) {
  console.warn('[inject-sw-version] public/sw.js not found — skipping.');
  process.exit(0);
}
if (!existsSync(OUT_SW_PATH)) {
  console.warn('[inject-sw-version] out/sw.js not found — skipping static export service worker.');
  process.exit(0);
}

const buildId = readFileSync(BUILD_ID_PATH, 'utf8').trim();
const sw = readFileSync(SW_TEMPLATE_PATH, 'utf8');

function collectFiles(dir) {
  if (!existsSync(dir)) return [];

  return readdirSync(dir, { withFileTypes: true })
    .flatMap((entry) => {
      const path = join(dir, entry.name);
      return entry.isDirectory() ? collectFiles(path) : [path];
    })
    .sort();
}

function cacheVersionForExport() {
  const hash = createHash('sha256');
  const files = [
    ...collectFiles(OUT_STATIC_PATH),
    join(OUT_DIR, 'manifest.webmanifest'),
    join(OUT_DIR, 'manifest.json'),
    join(OUT_DIR, 'favicon.ico'),
  ].filter((path) => existsSync(path) && statSync(path).isFile());

  hash.update(`build:${buildId}\n`);
  for (const file of files) {
    hash.update(`${file.slice(ROOT.length + 1)}\0`);
    hash.update(readFileSync(file));
    hash.update('\0');
  }

  return `static-${hash.digest('hex').slice(0, 16)}`;
}

const PATTERN = /const CACHE_VERSION = ['"][^'"]+['"];/;
if (!PATTERN.test(sw)) {
  console.warn('[inject-sw-version] CACHE_VERSION line not found in sw.js — manual edit?');
  process.exit(0);
}

const cacheVersion = process.env.G5_SW_CACHE_VERSION?.trim() || cacheVersionForExport();
const next = sw.replace(PATTERN, `const CACHE_VERSION = '${cacheVersion}';`);
if (next === sw) {
  console.log(`[inject-sw-version] sw.js template already at CACHE_VERSION=${cacheVersion}`);
  process.exit(0);
}

writeFileSync(OUT_SW_PATH, next, 'utf8');
console.log(`[inject-sw-version] ${STATIC_EXPORT_DIR}/sw.js CACHE_NAME = gnuboard-${cacheVersion} (BUILD_ID=${buildId})`);
