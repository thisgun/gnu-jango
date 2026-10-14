// 어떤 테마 소스(nextjs/themes/<source>)를 어떤 Django 테마 이름(templates/theme/<theme>)으로 내보낼지.
// next.config.ts 와 빌드 · 동기화 · 검사 · 포장 스크립트가 함께 쓴다.
import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const nextRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const repoRoot = resolve(nextRoot, '..');

export const DEFAULT_THEME_SOURCE = 'default';
export const DEFAULT_THEME_NAME = 'nextjs_default';
export const THEME_NAME_RE = /^[a-z][a-z0-9_-]{1,31}$/;
export const REQUIRED_THEME_SOURCE_FILES = ['theme.config.ts', 'components.tsx'];

/** Django 테마 이름 ↔ 테마 소스 폴더. 이름과 폴더가 같으면 적지 않아도 된다. */
const THEME_SOURCES = { [DEFAULT_THEME_NAME]: DEFAULT_THEME_SOURCE, handbook: 'handbook' };

function checked(value, label) {
  const name = String(value ?? '').trim();
  if (!THEME_NAME_RE.test(name)) {
    throw new Error(
      `[theme-pair] Invalid ${label} "${value ?? ''}". Use 2-32 characters: a letter a-z followed by [a-z0-9_-].`
    );
  }
  return name;
}

function sourceForTheme(theme) {
  return THEME_SOURCES[theme] ?? theme;
}

function themeForSource(source) {
  return Object.entries(THEME_SOURCES).find(([, mapped]) => mapped === source)?.[0] ?? source;
}

/** G5_THEME_SOURCE · G5_THEME_NAME 중 주어진 것으로 { source, theme } 를 정한다. 둘 다 없으면 기본 테마. */
export function resolveThemePair(env = process.env) {
  const rawSource = String(env.G5_THEME_SOURCE ?? '').trim();
  const rawTheme = String(env.G5_THEME_NAME ?? '').trim();
  if (rawSource && rawTheme) return { source: checked(rawSource, 'theme source'), theme: checked(rawTheme, 'theme name') };
  if (rawSource) {
    const source = checked(rawSource, 'theme source');
    return { source, theme: themeForSource(source) };
  }
  if (rawTheme) {
    const theme = checked(rawTheme, 'theme name');
    return { source: sourceForTheme(theme), theme };
  }
  return { source: DEFAULT_THEME_SOURCE, theme: DEFAULT_THEME_NAME };
}

export function resolveThemeSourceName() {
  return resolveThemePair().source;
}

export function resolveThemeName() {
  return resolveThemePair().theme;
}

export function themeSourceDir(source = resolveThemeSourceName()) {
  return resolve(nextRoot, 'themes', source);
}

/** 테마 소스 폴더와 필수 파일이 있는지 확인하고 이름을 돌려준다. */
export function assertThemeSource(source = resolveThemeSourceName()) {
  const dir = themeSourceDir(source);
  for (const file of REQUIRED_THEME_SOURCE_FILES) {
    if (!existsSync(resolve(dir, file))) {
      throw new Error(`[theme-pair] Theme source "${source}" is missing themes/${source}/${file}.`);
    }
  }
  return source;
}
