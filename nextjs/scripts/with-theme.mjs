// 테마를 골라 다른 명령을 실행한다:  node scripts/with-theme.mjs <theme-name> -- <command> [args...]
// 예) node scripts/with-theme.mjs handbook -- npm run build:theme
//
// 기본 테마(nextjs_default)가 아니면 빌드 ID 를 테마별로 따로 준다. _next/static 의 파일 이름은 내용
// 해시라 겹쳐도 같은 파일이지만, 빌드 ID 폴더(_buildManifest.js)는 이름이 같으면 내용이 달라 부딪친다.
import { spawnSync } from 'node:child_process';
import { DEFAULT_THEME_NAME, resolveThemePair } from './theme-pair.mjs';

function fail(message) {
  console.error(`[with-theme] ${message}`);
  console.error('Usage: node scripts/with-theme.mjs <theme-name> -- <command> [args...]');
  process.exit(1);
}

const args = process.argv.slice(2);
const separator = args.indexOf('--');
const themeName = args[0];
const command = separator >= 0 ? args[separator + 1] : undefined;
const commandArgs = separator >= 0 ? args.slice(separator + 2) : [];
if (!themeName || themeName === '--' || !command) fail('A theme name and a command are required.');

let pair;
try {
  pair = resolveThemePair({ G5_THEME_NAME: themeName });
} catch (error) {
  fail(error instanceof Error ? error.message : String(error));
}

const env = {
  ...process.env,
  G5_THEME_SOURCE: pair.source,
  G5_THEME_NAME: pair.theme,
};
if (pair.theme !== DEFAULT_THEME_NAME) {
  env.G5_NEXT_BUILD_ID ??= `g5-${pair.theme}-static`;
}

console.log(`[with-theme] source=${pair.source} theme=${pair.theme}`);
const result = spawnSync(command, commandArgs, { env, shell: process.platform === 'win32', stdio: 'inherit' });
if (result.error) fail(result.error.message);
process.exit(result.status ?? 1);
