import {
  chmodSync,
  copyFileSync,
  cpSync,
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from 'node:fs';
import { dirname, extname, join, relative, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const nextRoot = resolve(scriptDir, '..');
const repoRoot = resolve(nextRoot, '..');
const deployBaseRoot = join(nextRoot, '.deploy');
const deployPackageName = 'nextjs25-live';
const archiveName = `${deployPackageName}.tar.gz`;
const archiveChecksumFileName = `${archiveName}.sha256`;
const archiveManifestFileName = `${deployPackageName}.archive.json`;
const deployRoot = join(deployBaseRoot, deployPackageName);
const archivePath = join(deployBaseRoot, archiveName);
const uploadRoot = join(deployRoot, 'upload');
const nginxRoot = join(deployRoot, 'nginx');
const rootPatchRoot = join(deployRoot, 'root-patch');
const rmRetryOptions = { force: true, maxRetries: 20, retryDelay: 250 };
const themeSource = join(repoRoot, 'theme', 'nextjs25');
const themeTarget = join(uploadRoot, 'theme', 'nextjs25');
const apiSource = join(repoRoot, 'api');
const apiTarget = join(uploadRoot, 'api');
const docsNginxRoot = join(repoRoot, 'docs', 'nginx');
const checksumFileName = 'CHECKSUMS.sha256';
const excludedApiPackagePatterns = ['.env', '.env.*'];
const liveDefaultWebRoot = process.env.LIVE_DEPLOY_WEB_ROOT || '/home/nextjs/www/study-gnuboard';
const forbiddenLiveStaticPatterns = [
  'content="http://127.0.0.20',
  'href="http://127.0.0.20',
  'appBaseUrl":"http://127.0.0.20',
  'apiBaseUrl":"http://127.0.0.9',
  'g5BaseUrl":"http://127.0.0.9',
];
const liveStaticTextExtensions = new Set([
  '.css',
  '.html',
  '.js',
  '.json',
  '.txt',
  '.webmanifest',
  '.xml',
]);
const packageTextExtensions = new Set([
  ...liveStaticTextExtensions,
  '.conf',
  '.example',
  '.md',
  '.php',
  '.sh',
  '.sql',
]);
const packageTextFileNames = new Set(['.htaccess']);
const liveDefaultNginxConf = process.env.LIVE_DEPLOY_NGINX_CONF || '/etc/nginx/nginx.conf';
const liveDefaultSiteConf =
  process.env.LIVE_DEPLOY_NGINX_SITE_CONF || '/etc/nginx/sites-enabled/nextjs.thisgun.net';
const liveDefaultNginxSnippetsDir =
  process.env.LIVE_DEPLOY_NGINX_SNIPPETS_DIR || '/etc/nginx/snippets';

const requiredThemeFiles = [
  'index.php',
  'route.php',
  'theme.config.php',
  'bridge/app-shell.php',
  'app/index.html',
  'app/manifest.webmanifest',
  'app/robots.txt',
  'app/sitemap.xml',
  'app/sitemap-posts.xml',
  'app/sw.js',
  'app/_next',
];

const requiredApiFiles = [
  'index.php',
  'lib/Response.php',
  'v1/settings.php',
  'v1/shop/router.php',
  'v1/shop/common.php',
  'v1/shop/products.php',
  'v1/shop/reviews.php',
  'v1/shop/policy.php',
  'v1/shop/shipping.php',
  'social/popup.php',
];

const rootPatchFiles = [
  'common.php',
  'plugin/social/includes/functions.php',
  'extend/dday.extend.php',
  'extend/nextjs25-social.extend.php',
];

const nginxSnippets = [
  {
    source: 'nextjs25-security-map.conf',
    target: 'g5-nextjs25-security-map.conf',
    installScope: 'nginx http block',
  },
  {
    source: 'nextjs25-security-headers.conf',
    target: 'g5-nextjs25-security-headers.conf',
    installScope: 'frontend and static locations',
  },
  {
    source: 'nextjs25-api-security-headers.conf',
    target: 'g5-nextjs25-api-security-headers.conf',
    installScope: 'exact /api/index.php PHP-FPM location',
  },
  {
    source: 'nextjs25-theme-locations.conf',
    target: 'g5-nextjs25-theme-locations.conf',
    installScope: 'nextjs.thisgun.net server block',
  },
];

const sourceSnapshotPrefixes = [
  'api/',
  'docs/nginx/',
  'nextjs/public/',
  'nextjs/src/',
  'theme/nextjs25/',
];

const sourceSnapshotFiles = new Set([
  'nextjs/.env.production.example',
  'nextjs/components.json',
  'nextjs/next.config.ts',
  'nextjs/package-lock.json',
  'nextjs/package.json',
  'nextjs/postcss.config.mjs',
  'nextjs/scripts/build-next.mjs',
  'nextjs/scripts/inject-sw-version.mjs',
  'nextjs/scripts/package-live-deploy.mjs',
  'nextjs/scripts/sync-static-theme.mjs',
  'nextjs/scripts/write-apache-static-headers.mjs',
  'nextjs/tsconfig.json',
  ...rootPatchFiles,
]);

const serverInstallScript = `#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
WEB_ROOT="\${WEB_ROOT:-}"
NGINX_SNIPPETS_DIR="\${NGINX_SNIPPETS_DIR:-/etc/nginx/snippets}"
DRY_RUN="\${DRY_RUN:-0}"
SKIP_NGINX_INSTALL="\${SKIP_NGINX_INSTALL:-0}"
SKIP_NGINX_TEST="\${SKIP_NGINX_TEST:-0}"
SKIP_NGINX_RELOAD="\${SKIP_NGINX_RELOAD:-0}"
SKIP_API_INSTALL="\${SKIP_API_INSTALL:-0}"
SKIP_ROOT_PATCH_INSTALL="\${SKIP_ROOT_PATCH_INSTALL:-0}"
NGINX_TEST_COMMAND="\${NGINX_TEST_COMMAND:-nginx -t}"
NGINX_RELOAD_COMMAND="\${NGINX_RELOAD_COMMAND:-systemctl reload nginx}"
BACKUP_ROOT="\${BACKUP_ROOT:-}"
SUPPRESS_MANUAL_CHECKS="\${SUPPRESS_MANUAL_CHECKS:-0}"

log() {
  printf '[server-install] %s\\n' "$*"
}

die() {
  printf '[server-install] ERROR: %s\\n' "$*" >&2
  exit 1
}

run() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '[server-install] dry-run:'
    printf ' %q' "$@"
    printf '\\n'
  else
    "$@"
  fi
}

run_shell() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '[server-install] dry-run: %s\\n' "$*"
  else
    sh -c "$*"
  fi
}

[ -n "$WEB_ROOT" ] || die "Set WEB_ROOT to the live Gnuboard document root."
[ -d "$PACKAGE_DIR/upload/theme/nextjs25" ] || die "Package theme directory is missing."
[ -d "$PACKAGE_DIR/upload/api" ] || die "Package API directory is missing."
[ -d "$PACKAGE_DIR/nginx" ] || die "Package nginx directory is missing."
[ -f "$WEB_ROOT/common.php" ] || die "WEB_ROOT does not look like a Gnuboard root: $WEB_ROOT"
[ -d "$WEB_ROOT/theme" ] || die "WEB_ROOT/theme is missing: $WEB_ROOT/theme"

if [ -f "$PACKAGE_DIR/CHECKSUMS.sha256" ]; then
  if command -v sha256sum >/dev/null 2>&1; then
    log "Verifying package checksums"
    CHECKSUM_OUTPUT=""
    TMP_BASE="$(printenv TMPDIR 2>/dev/null || true)"
    [ -n "$TMP_BASE" ] || TMP_BASE="/tmp"
    if CHECKSUM_OUTPUT="$(mktemp "$TMP_BASE/g5-nextjs25-checksums.XXXXXX" 2>/dev/null)"; then
      :
    else
      CHECKSUM_OUTPUT="$PACKAGE_DIR/.g5-nextjs25-checksums.$$"
    fi
    if (cd "$PACKAGE_DIR" && sha256sum -c CHECKSUMS.sha256 >"$CHECKSUM_OUTPUT" 2>&1); then
      rm -f "$CHECKSUM_OUTPUT"
      log "Package checksums passed"
    else
      die "Package checksum verification failed; see $CHECKSUM_OUTPUT"
    fi
  else
    log "sha256sum is not available; skipping package checksum verification."
  fi
fi

THEME_SOURCE="$PACKAGE_DIR/upload/theme/nextjs25"
THEME_TARGET="$WEB_ROOT/theme/nextjs25"
API_SOURCE="$PACKAGE_DIR/upload/api"
API_TARGET="$WEB_ROOT/api"
ROOT_PATCH_SOURCE="$PACKAGE_DIR/root-patch"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
TMP_TARGET="$WEB_ROOT/theme/.nextjs25.deploy.$TIMESTAMP"
BACKUP_PARENT="$WEB_ROOT/theme"
API_TMP_TARGET="$WEB_ROOT/.api.nextjs25.deploy.$TIMESTAMP"
API_BACKUP_PARENT="$WEB_ROOT"

if [ -n "$BACKUP_ROOT" ]; then
  BACKUP_PARENT="$BACKUP_ROOT"
  API_BACKUP_PARENT="$BACKUP_ROOT"
  run mkdir -p "$BACKUP_PARENT"
fi

BACKUP_TARGET="$BACKUP_PARENT/nextjs25.backup.$TIMESTAMP"
API_BACKUP_TARGET="$API_BACKUP_PARENT/api.backup.$TIMESTAMP"
ROOT_PATCH_BACKUP_TARGET="$API_BACKUP_PARENT/root-patch.backup.$TIMESTAMP"

log "Package: $PACKAGE_DIR"
log "Web root: $WEB_ROOT"
log "Theme source: $THEME_SOURCE"
log "Theme target: $THEME_TARGET"
log "API source: $API_SOURCE"
log "API target: $API_TARGET"
log "Root patch source: $ROOT_PATCH_SOURCE"
log "Nginx snippets: $NGINX_SNIPPETS_DIR"

if [ "$DRY_RUN" != "1" ] && [ "$SKIP_NGINX_INSTALL" != "1" ]; then
  if [ -d "$NGINX_SNIPPETS_DIR" ]; then
    [ -w "$NGINX_SNIPPETS_DIR" ] || die "NGINX_SNIPPETS_DIR is not writable before install: $NGINX_SNIPPETS_DIR"
  else
    SNIPPETS_PARENT="$(dirname "$NGINX_SNIPPETS_DIR")"
    [ -d "$SNIPPETS_PARENT" ] || die "Parent directory for NGINX_SNIPPETS_DIR is missing: $SNIPPETS_PARENT"
    [ -w "$SNIPPETS_PARENT" ] || die "Cannot create NGINX_SNIPPETS_DIR; parent is not writable: $SNIPPETS_PARENT"
  fi
fi

run rm -rf "$TMP_TARGET"
run mkdir -p "$TMP_TARGET"
run cp -a "$THEME_SOURCE/." "$TMP_TARGET/"

if [ "$DRY_RUN" != "1" ]; then
  [ -f "$TMP_TARGET/route.php" ] || die "Staged theme route.php is missing."
  [ -f "$TMP_TARGET/bridge/app-shell.php" ] || die "Staged theme bridge/app-shell.php is missing."
  [ -f "$TMP_TARGET/app/index.html" ] || die "Staged theme app/index.html is missing."
fi

if [ -d "$THEME_TARGET" ]; then
  log "Backing up current theme to $BACKUP_TARGET"
  run mv "$THEME_TARGET" "$BACKUP_TARGET"
else
  log "No existing theme/nextjs25 directory found."
fi

run mv "$TMP_TARGET" "$THEME_TARGET"

if [ "$SKIP_API_INSTALL" = "1" ]; then
  log "Skipping API install because SKIP_API_INSTALL=1."
else
  run rm -rf "$API_TMP_TARGET"
  run mkdir -p "$API_TMP_TARGET"
  run cp -a "$API_SOURCE/." "$API_TMP_TARGET/"

  if [ "$DRY_RUN" != "1" ]; then
    [ -f "$API_TMP_TARGET/index.php" ] || die "Staged API index.php is missing."
    [ -f "$API_TMP_TARGET/v1/shop/router.php" ] || die "Staged shop router is missing."
    [ -f "$API_TMP_TARGET/v1/shop/reviews.php" ] || die "Staged review API is missing."
  fi

  if [ -d "$API_TARGET" ]; then
    log "Backing up current API to $API_BACKUP_TARGET"
    run mv "$API_TARGET" "$API_BACKUP_TARGET"
  else
    log "No existing api directory found."
  fi

  run mv "$API_TMP_TARGET" "$API_TARGET"
fi

if [ "$SKIP_ROOT_PATCH_INSTALL" = "1" ]; then
  log "Skipping root patch install because SKIP_ROOT_PATCH_INSTALL=1."
elif [ -d "$ROOT_PATCH_SOURCE" ]; then
  log "Installing root patch files with backup at $ROOT_PATCH_BACKUP_TARGET"
  find "$ROOT_PATCH_SOURCE" -type f | while IFS= read -r source_file; do
    rel_path="\${source_file#$ROOT_PATCH_SOURCE/}"
    target_file="$WEB_ROOT/$rel_path"
    backup_file="$ROOT_PATCH_BACKUP_TARGET/$rel_path"

    run mkdir -p "$(dirname "$target_file")"
    if [ -f "$target_file" ]; then
      run mkdir -p "$(dirname "$backup_file")"
      run cp -a "$target_file" "$backup_file"
    fi

    run cp -a "$source_file" "$target_file"
  done
else
  log "No root patch directory found; skipping root patch install."
fi

if [ "$SKIP_NGINX_INSTALL" = "1" ]; then
  log "Skipping nginx snippet install because SKIP_NGINX_INSTALL=1."
else
  run mkdir -p "$NGINX_SNIPPETS_DIR"
  for file in "$PACKAGE_DIR"/nginx/*.conf; do
    [ -f "$file" ] || continue
    run cp -f "$file" "$NGINX_SNIPPETS_DIR/$(basename "$file")"
  done
fi

if [ "$SKIP_NGINX_TEST" != "1" ]; then
  run_shell "$NGINX_TEST_COMMAND"
fi

if [ "$SKIP_NGINX_RELOAD" != "1" ]; then
  run_shell "$NGINX_RELOAD_COMMAND"
else
  log "Skipping nginx reload because SKIP_NGINX_RELOAD=1."
fi

if [ "$SUPPRESS_MANUAL_CHECKS" != "1" ]; then
cat <<'MSG'

Manual checks still required:
- nginx.conf http {} includes /etc/nginx/snippets/g5-nextjs25-security-map.conf.
- nextjs.thisgun.net server {} includes /etc/nginx/snippets/g5-nextjs25-theme-locations.conf before generic Gnuboard locations.
- SERVER-NGINX-PLAN.sh has been used to add exact /theme/nextjs25/route.php and /api/index.php PHP-FPM locations.
- Gnuboard active theme is nextjs25. Use SERVER-ACTIVATE-THEME.sh if needed.
- From the repository, run npm run check:live-deployment and npm run check:live-runtime.

MSG
fi

log "Install step finished. Roll back theme files with SERVER-ROLLBACK.sh and ROLLBACK_THEME=$BACKUP_TARGET if needed."
if [ "$SKIP_API_INSTALL" != "1" ]; then
  log "Roll back API files with SERVER-ROLLBACK.sh and ROLLBACK_API=$API_BACKUP_TARGET if needed."
fi
`;

const serverRollbackScript = `#!/usr/bin/env bash
set -euo pipefail

WEB_ROOT="\${WEB_ROOT:-}"
ROLLBACK_THEME="\${ROLLBACK_THEME:-}"
ROLLBACK_API="\${ROLLBACK_API:-}"
DRY_RUN="\${DRY_RUN:-0}"
SKIP_NGINX_TEST="\${SKIP_NGINX_TEST:-0}"
SKIP_NGINX_RELOAD="\${SKIP_NGINX_RELOAD:-0}"
NGINX_TEST_COMMAND="\${NGINX_TEST_COMMAND:-nginx -t}"
NGINX_RELOAD_COMMAND="\${NGINX_RELOAD_COMMAND:-systemctl reload nginx}"

log() {
  printf '[server-rollback] %s\\n' "$*"
}

die() {
  printf '[server-rollback] ERROR: %s\\n' "$*" >&2
  exit 1
}

run() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '[server-rollback] dry-run:'
    printf ' %q' "$@"
    printf '\\n'
  else
    "$@"
  fi
}

run_shell() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '[server-rollback] dry-run: %s\\n' "$*"
  else
    sh -c "$*"
  fi
}

[ -n "$WEB_ROOT" ] || die "Set WEB_ROOT to the live Gnuboard document root."
[ -n "$ROLLBACK_THEME" ] || die "Set ROLLBACK_THEME to a nextjs25.backup.* directory."
[ -f "$WEB_ROOT/common.php" ] || die "WEB_ROOT does not look like a Gnuboard root: $WEB_ROOT"
[ -d "$ROLLBACK_THEME" ] || die "ROLLBACK_THEME directory is missing: $ROLLBACK_THEME"
[ -f "$ROLLBACK_THEME/route.php" ] || die "ROLLBACK_THEME does not look like theme/nextjs25."
if [ -n "$ROLLBACK_API" ]; then
  [ -d "$ROLLBACK_API" ] || die "ROLLBACK_API directory is missing: $ROLLBACK_API"
  [ -f "$ROLLBACK_API/index.php" ] || die "ROLLBACK_API does not look like api."
fi

THEME_TARGET="$WEB_ROOT/theme/nextjs25"
API_TARGET="$WEB_ROOT/api"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
CURRENT_BACKUP="$WEB_ROOT/theme/nextjs25.rollback-current.$TIMESTAMP"
CURRENT_API_BACKUP="$WEB_ROOT/api.rollback-current.$TIMESTAMP"

if [ -d "$THEME_TARGET" ]; then
  log "Saving current theme to $CURRENT_BACKUP"
  run mv "$THEME_TARGET" "$CURRENT_BACKUP"
fi

log "Restoring copy of $ROLLBACK_THEME to $THEME_TARGET"
run mkdir -p "$THEME_TARGET"
run cp -a "$ROLLBACK_THEME/." "$THEME_TARGET/"

if [ -n "$ROLLBACK_API" ]; then
  if [ -d "$API_TARGET" ]; then
    log "Saving current API to $CURRENT_API_BACKUP"
    run mv "$API_TARGET" "$CURRENT_API_BACKUP"
  fi

  log "Restoring copy of $ROLLBACK_API to $API_TARGET"
  run mkdir -p "$API_TARGET"
  run cp -a "$ROLLBACK_API/." "$API_TARGET/"
fi

if [ "$SKIP_NGINX_TEST" != "1" ]; then
  run_shell "$NGINX_TEST_COMMAND"
fi

if [ "$SKIP_NGINX_RELOAD" != "1" ]; then
  run_shell "$NGINX_RELOAD_COMMAND"
else
  log "Skipping nginx reload because SKIP_NGINX_RELOAD=1."
fi

log "Rollback source backup directories were preserved for repeatable recovery."
log "Rollback step finished. Re-run live checks from the repository."
`;

const serverActivateThemeScript = `#!/usr/bin/env bash
set -euo pipefail

WEB_ROOT="\${WEB_ROOT:-}"
THEME="\${THEME:-nextjs25}"
APPLY="\${APPLY:-0}"
PHP_BIN="\${PHP_BIN:-php}"
PHP_WEB_ROOT="\${PHP_WEB_ROOT:-}"

if [ -z "$PHP_WEB_ROOT" ]; then
  PHP_WEB_ROOT="$WEB_ROOT"
  if [[ "$PHP_BIN" == *.exe && "$WEB_ROOT" =~ ^/mnt/([A-Za-z])/(.*)$ ]]; then
    PHP_WEB_ROOT="\${BASH_REMATCH[1]^^}:/\${BASH_REMATCH[2]}"
  fi
fi

log() {
  printf '[server-activate-theme] %s\\n' "$*"
}

die() {
  printf '[server-activate-theme] ERROR: %s\\n' "$*" >&2
  exit 1
}

[ -n "$WEB_ROOT" ] || die "Set WEB_ROOT to the live Gnuboard document root."
[ -f "$WEB_ROOT/common.php" ] || die "WEB_ROOT does not look like a Gnuboard root: $WEB_ROOT"

if [[ ! "$THEME" =~ ^[A-Za-z0-9_-]+$ ]]; then
  die "THEME may contain only letters, numbers, underscores, and hyphens."
fi

if [ ! -d "$WEB_ROOT/theme/$THEME" ]; then
  if [ "$APPLY" = "1" ]; then
    die "Theme directory is missing: $WEB_ROOT/theme/$THEME"
  fi
  log "Theme directory is missing, but APPLY=0; continuing as a first-deploy dry-run."
elif [ ! -f "$WEB_ROOT/theme/$THEME/theme.config.php" ]; then
  if [ "$APPLY" = "1" ]; then
    die "Theme config is missing: $WEB_ROOT/theme/$THEME/theme.config.php"
  fi
  log "Theme config is missing, but APPLY=0; continuing as a first-deploy dry-run."
fi

if ! command -v "$PHP_BIN" >/dev/null 2>&1; then
  die "PHP_BIN command is required to update Gnuboard config: $PHP_BIN"
fi

if [ "$APPLY" = "1" ]; then
  log "APPLY=1, updating Gnuboard active theme if needed."
else
  log "Dry-run mode. Set APPLY=1 to update Gnuboard active theme."
fi

WEB_ROOT="$WEB_ROOT" PHP_WEB_ROOT="$PHP_WEB_ROOT" THEME="$THEME" APPLY="$APPLY" "$PHP_BIN" -d display_errors=stderr <<'PHP'
<?php
$webRoot = getenv('PHP_WEB_ROOT') ?: (getenv('WEB_ROOT') ?: '');
$theme = getenv('THEME') ?: 'nextjs25';
$apply = getenv('APPLY') === '1';

if (!preg_match('/^[A-Za-z0-9_-]+$/', $theme)) {
    fwrite(STDERR, "[server-activate-theme] ERROR: Invalid theme name.\\n");
    exit(1);
}

if (!chdir($webRoot)) {
    fwrite(STDERR, "[server-activate-theme] ERROR: Cannot enter WEB_ROOT.\\n");
    exit(1);
}

$_SERVER['SERVER_NAME'] = $_SERVER['SERVER_NAME'] ?? 'localhost';
$_SERVER['HTTP_HOST'] = $_SERVER['HTTP_HOST'] ?? $_SERVER['SERVER_NAME'];
$_SERVER['SERVER_PORT'] = $_SERVER['SERVER_PORT'] ?? '80';
$_SERVER['REQUEST_URI'] = $_SERVER['REQUEST_URI'] ?? '/';
$_SERVER['REQUEST_METHOD'] = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$_SERVER['REMOTE_ADDR'] = $_SERVER['REMOTE_ADDR'] ?? '127.0.0.1';

ob_start();
include './common.php';
ob_end_clean();

global $g5, $config;

if (empty($g5['config_table'])) {
    fwrite(STDERR, "[server-activate-theme] ERROR: Gnuboard config table is unavailable.\\n");
    exit(1);
}

$current = isset($config['cf_theme']) ? (string) $config['cf_theme'] : '';
echo '[server-activate-theme] current theme: ' . ($current !== '' ? $current : '(none)') . PHP_EOL;
echo '[server-activate-theme] target theme: ' . $theme . PHP_EOL;

if ($current === $theme) {
    echo "[server-activate-theme] active theme already matches target.\\n";
    exit(0);
}

if (!$apply) {
    echo "[server-activate-theme] dry-run: would update cf_theme to '{$theme}'.\\n";
    exit(0);
}

$escaped = function_exists('sql_real_escape_string')
    ? sql_real_escape_string($theme)
    : sql_escape_string($theme);

sql_query(" update {$g5['config_table']} set cf_theme = '{$escaped}' ");

$row = sql_fetch(" select cf_theme from {$g5['config_table']} limit 1 ");
$after = isset($row['cf_theme']) ? (string) $row['cf_theme'] : '';

if ($after !== $theme) {
    fwrite(STDERR, "[server-activate-theme] ERROR: Theme update did not persist. Current value: {$after}\\n");
    exit(1);
}

echo "[server-activate-theme] updated cf_theme to '{$theme}'.\\n";
PHP
`;

const serverNginxPlanScript = `#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
SITE_CONF="\${SITE_CONF:-/etc/nginx/sites-enabled/nextjs.thisgun.net}"
NGINX_CONF="\${NGINX_CONF:-/etc/nginx/nginx.conf}"
NGINX_SNIPPETS_DIR="\${NGINX_SNIPPETS_DIR:-/etc/nginx/snippets}"
WRITE_SITE_SNIPPET="\${WRITE_SITE_SNIPPET:-1}"
SITE_SNIPPET_NAME="\${SITE_SNIPPET_NAME:-g5-nextjs25-exact-php-locations.conf}"
SITE_SNIPPET_FILE="\${SITE_SNIPPET_FILE:-$PACKAGE_DIR/nginx/$SITE_SNIPPET_NAME}"

log() {
  printf '[server-nginx-plan] %s\\n' "$*"
}

warn() {
  printf '[server-nginx-plan] WARN: %s\\n' "$*" >&2
}

die() {
  printf '[server-nginx-plan] ERROR: %s\\n' "$*" >&2
  exit 1
}

status_marker() {
  label="$1"
  file="$2"
  marker="$3"

  if [ ! -r "$file" ]; then
    printf '  %-48s %s\\n' "$label" "unreadable: $file"
    return
  fi

  if grep -Fq "$marker" "$file"; then
    printf '  %-48s present\\n' "$label"
  else
    printf '  %-48s missing\\n' "$label"
  fi
}

status_marker_any() {
  label="$1"
  marker="$2"
  shift 2

  checked="0"
  for file in "$@"; do
    if [ ! -r "$file" ]; then
      continue
    fi

    checked="1"
    if grep -Fq "$marker" "$file"; then
      printf '  %-48s present\\n' "$label"
      return
    fi
  done

  if [ "$checked" = "0" ]; then
    printf '  %-48s unreadable\\n' "$label"
  else
    printf '  %-48s missing\\n' "$label"
  fi
}

print_php_location() {
  path="$1"
  header_snippet="$2"

  printf 'location = %s {\\n' "$path"
  printf '    include snippets/fastcgi-php.conf;\\n'
  printf '    %s\\n' "$fastcgi_pass_line"
  printf '    %s\\n' "$script_filename_line"
  if [ -n "$fastcgi_buffers_line" ]; then
    printf '    %s\\n' "$fastcgi_buffers_line"
  fi
  if [ -n "$fastcgi_buffer_size_line" ]; then
    printf '    %s\\n' "$fastcgi_buffer_size_line"
  fi
  printf '    include %s/%s;\\n' "$NGINX_SNIPPETS_DIR" "$header_snippet"
  printf '}\\n'
}

print_exact_php_locations() {
  print_php_location "/theme/nextjs25/route.php" "g5-nextjs25-security-headers.conf"
  printf '\\n'
  print_php_location "/api/index.php" "g5-nextjs25-api-security-headers.conf"
}

write_site_snippet() {
  if [ "$WRITE_SITE_SNIPPET" != "1" ]; then
    return
  fi

  mkdir -p "$(dirname "$SITE_SNIPPET_FILE")"
  {
    printf '#\\n'
    printf '# Site-specific exact PHP locations for the G5 Next.js 25 theme.\\n'
    printf '# Generated by SERVER-NGINX-PLAN.sh from %s.\\n' "$SITE_CONF"
    printf '# Copy to %s/%s and include inside the nextjs.thisgun.net server block.\\n' "$NGINX_SNIPPETS_DIR" "$SITE_SNIPPET_NAME"
    printf '#\\n\\n'
    print_exact_php_locations
  } > "$SITE_SNIPPET_FILE"

  log "Wrote generated nginx site snippet: $SITE_SNIPPET_FILE"
}

[ -r "$SITE_CONF" ] || die "SITE_CONF is not readable: $SITE_CONF"

fastcgi_pass_line="$(awk '/^[[:space:]]*fastcgi_pass[[:space:]]/ { sub(/^[[:space:]]+/, ""); print; exit }' "$SITE_CONF")"
script_filename_line="$(awk '/^[[:space:]]*fastcgi_param[[:space:]]+SCRIPT_FILENAME[[:space:]]/ { sub(/^[[:space:]]+/, ""); print; exit }' "$SITE_CONF")"
fastcgi_buffers_line="$(awk '/^[[:space:]]*fastcgi_buffers[[:space:]]/ { sub(/^[[:space:]]+/, ""); print; exit }' "$SITE_CONF")"
fastcgi_buffer_size_line="$(awk '/^[[:space:]]*fastcgi_buffer_size[[:space:]]/ { sub(/^[[:space:]]+/, ""); print; exit }' "$SITE_CONF")"

[ -n "$fastcgi_pass_line" ] || die "Could not detect fastcgi_pass from $SITE_CONF"

if [ -z "$script_filename_line" ]; then
  script_filename_line='fastcgi_param SCRIPT_FILENAME $realpath_root$fastcgi_script_name;'
  warn "SCRIPT_FILENAME fastcgi_param not found; using default: $script_filename_line"
fi

log "Site config: $SITE_CONF"
log "Nginx config: $NGINX_CONF"
log "Snippets dir: $NGINX_SNIPPETS_DIR"
log "Detected PHP-FPM: $fastcgi_pass_line"

write_site_snippet

printf '\\nCurrent include status:\\n'
status_marker "http security map include" "$NGINX_CONF" "g5-nextjs25-security-map.conf"
status_marker "theme route locations include" "$SITE_CONF" "g5-nextjs25-theme-locations.conf"
status_marker "exact PHP locations include" "$SITE_CONF" "$SITE_SNIPPET_NAME"
status_marker_any "frontend route.php exact PHP location" "location = /theme/nextjs25/route.php" "$SITE_CONF" "$NGINX_SNIPPETS_DIR/$SITE_SNIPPET_NAME" "$SITE_SNIPPET_FILE"
status_marker_any "API index exact PHP location" "location = /api/index.php" "$SITE_CONF" "$NGINX_SNIPPETS_DIR/$SITE_SNIPPET_NAME" "$SITE_SNIPPET_FILE"

cat <<PLAN

Copy snippets as root:

  install -d "$NGINX_SNIPPETS_DIR"
  cp -f nginx/*.conf "$NGINX_SNIPPETS_DIR"/

Add once inside nginx.conf http {}:

  include $NGINX_SNIPPETS_DIR/g5-nextjs25-security-map.conf;

Add inside the nextjs.thisgun.net server {} block before the generic location /:

  include $NGINX_SNIPPETS_DIR/g5-nextjs25-theme-locations.conf;
  include $NGINX_SNIPPETS_DIR/$SITE_SNIPPET_NAME;

The generated $SITE_SNIPPET_NAME contains:

PLAN

print_exact_php_locations

cat <<PLAN

Then run:

  nginx -t
  systemctl reload nginx
  WEB_ROOT=/path/to/gnuboard bash SERVER-ACTIVATE-THEME.sh
  WEB_ROOT=/path/to/gnuboard APPLY=1 bash SERVER-ACTIVATE-THEME.sh
  WEB_ROOT=/path/to/gnuboard bash SERVER-VERIFY.sh

PLAN
`;

const serverRootApplyScript = `#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
WEB_ROOT="\${WEB_ROOT:-}"
NGINX_CONF="\${NGINX_CONF:-/etc/nginx/nginx.conf}"
SITE_CONF="\${SITE_CONF:-/etc/nginx/sites-enabled/nextjs.thisgun.net}"
NGINX_SNIPPETS_DIR="\${NGINX_SNIPPETS_DIR:-/etc/nginx/snippets}"
DRY_RUN="\${DRY_RUN:-1}"
THEME="\${THEME:-nextjs25}"
PHP_BIN="\${PHP_BIN:-php}"
PHP_WEB_ROOT="\${PHP_WEB_ROOT:-}"
SKIP_NGINX_TEST="\${SKIP_NGINX_TEST:-0}"
SKIP_NGINX_RELOAD="\${SKIP_NGINX_RELOAD:-0}"
SKIP_NGINX_DUMP="\${SKIP_NGINX_DUMP:-0}"
SKIP_PHP_THEME_CHECK="\${SKIP_PHP_THEME_CHECK:-0}"
SKIP_NGINX_PLAN="\${SKIP_NGINX_PLAN:-0}"
SKIP_NGINX_INSTALL="\${SKIP_NGINX_INSTALL:-0}"
SKIP_API_INSTALL="\${SKIP_API_INSTALL:-0}"
SKIP_ROOT_PATCH_INSTALL="\${SKIP_ROOT_PATCH_INSTALL:-0}"
NGINX_TEST_COMMAND="\${NGINX_TEST_COMMAND:-nginx -t}"
NGINX_RELOAD_COMMAND="\${NGINX_RELOAD_COMMAND:-systemctl reload nginx}"
ACTIVATE_THEME="\${ACTIVATE_THEME:-}"
RUN_VERIFY="\${RUN_VERIFY:-}"
RESTORE_CONFIG_ON_TEST_FAIL="\${RESTORE_CONFIG_ON_TEST_FAIL:-1}"

if [ -z "$ACTIVATE_THEME" ]; then
  if [ "$DRY_RUN" = "1" ]; then
    ACTIVATE_THEME="0"
  else
    ACTIVATE_THEME="1"
  fi
fi

if [ -z "$RUN_VERIFY" ]; then
  if [ "$DRY_RUN" = "1" ]; then
    RUN_VERIFY="0"
  else
    RUN_VERIFY="1"
  fi
fi

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
CONFIG_BACKUP_DIR="\${CONFIG_BACKUP_DIR:-$PACKAGE_DIR/backups/nginx-$TIMESTAMP}"
NGINX_CONF_BACKUP=""
SITE_CONF_BACKUP=""

log() {
  printf '[server-root-apply] %s\\n' "$*"
}

die() {
  printf '[server-root-apply] ERROR: %s\\n' "$*" >&2
  exit 1
}

run() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '[server-root-apply] dry-run:'
    printf ' %q' "$@"
    printf '\\n'
  else
    "$@"
  fi
}

run_shell() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '[server-root-apply] dry-run: %s\\n' "$*"
  else
    sh -c "$*"
  fi
}

resolve_file() {
  path="$1"
  if command -v readlink >/dev/null 2>&1; then
    readlink -f "$path" 2>/dev/null || printf '%s\\n' "$path"
  else
    printf '%s\\n' "$path"
  fi
}

backup_config() {
  file="$1"
  label="$2"
  backup="$CONFIG_BACKUP_DIR/$label"

  if [ "$DRY_RUN" = "1" ]; then
    log "Would back up $file to $backup"
    return
  fi

  mkdir -p "$CONFIG_BACKUP_DIR"
  cp -a "$file" "$backup"

  if [ "$label" = "nginx.conf" ]; then
    NGINX_CONF_BACKUP="$backup"
  else
    SITE_CONF_BACKUP="$backup"
  fi

  log "Backed up $file to $backup"
}

restore_config_backups() {
  if [ "$RESTORE_CONFIG_ON_TEST_FAIL" != "1" ]; then
    return
  fi

  if [ -n "$NGINX_CONF_BACKUP" ] && [ -f "$NGINX_CONF_BACKUP" ]; then
    cp -a "$NGINX_CONF_BACKUP" "$NGINX_CONF_REAL"
    log "Restored nginx config from $NGINX_CONF_BACKUP"
  fi

  if [ -n "$SITE_CONF_BACKUP" ] && [ -f "$SITE_CONF_BACKUP" ]; then
    cp -a "$SITE_CONF_BACKUP" "$SITE_CONF_REAL"
    log "Restored site config from $SITE_CONF_BACKUP"
  fi
}

ensure_http_include() {
  include_line="include $NGINX_SNIPPETS_DIR/g5-nextjs25-security-map.conf;"

  if grep -Fq "$include_line" "$NGINX_CONF_REAL"; then
    log "nginx http include already present: $include_line"
    return
  fi

  if [ "$DRY_RUN" = "1" ]; then
    log "Would add nginx http include after the http { line: $include_line"
    return
  fi

  backup_config "$NGINX_CONF_REAL" "nginx.conf"
  tmp_file="$(mktemp)"

  if ! awk -v inc="$include_line" '
    !done && $0 ~ /^[[:space:]]*http[[:space:]]*\\{/ {
      print
      match($0, /^[[:space:]]*/)
      print substr($0, RSTART, RLENGTH) "    " inc
      done = 1
      next
    }
    { print }
    END { if (!done) exit 42 }
  ' "$NGINX_CONF_REAL" > "$tmp_file"; then
    rm -f "$tmp_file"
    die "Could not find an http { block in $NGINX_CONF_REAL"
  fi

  cat "$tmp_file" > "$NGINX_CONF_REAL"
  rm -f "$tmp_file"
  log "Added nginx http include: $include_line"
}

ensure_site_includes() {
  theme_include="include $NGINX_SNIPPETS_DIR/g5-nextjs25-theme-locations.conf;"
  exact_include="include $NGINX_SNIPPETS_DIR/g5-nextjs25-exact-php-locations.conf;"
  need_theme="0"
  need_exact="0"

  grep -Fq "$theme_include" "$SITE_CONF_REAL" || need_theme="1"
  grep -Fq "$exact_include" "$SITE_CONF_REAL" || need_exact="1"

  if [ "$need_theme" = "0" ] && [ "$need_exact" = "0" ]; then
    log "site server includes already present."
    return
  fi

  if [ "$DRY_RUN" = "1" ]; then
    if [ "$need_theme" = "1" ]; then
      log "Would add site include before the generic location / block: $theme_include"
    fi
    if [ "$need_exact" = "1" ]; then
      log "Would add site include before the generic location / block: $exact_include"
    fi
    return
  fi

  backup_config "$SITE_CONF_REAL" "nextjs.thisgun.net.conf"
  tmp_file="$(mktemp)"

  if ! awk -v inc1="$theme_include" -v inc2="$exact_include" -v need1="$need_theme" -v need2="$need_exact" '
    !done && $0 ~ /^[[:space:]]*location[[:space:]]+\\/[[:space:]]*\\{/ {
      match($0, /^[[:space:]]*/)
      indent = substr($0, RSTART, RLENGTH)
      if (need1 == "1") print indent inc1
      if (need2 == "1") print indent inc2
      done = 1
    }
    { print }
    END { if (!done) exit 42 }
  ' "$SITE_CONF_REAL" > "$tmp_file"; then
    rm -f "$tmp_file"
    die "Could not find the generic location / block in $SITE_CONF_REAL"
  fi

  cat "$tmp_file" > "$SITE_CONF_REAL"
  rm -f "$tmp_file"
  log "Added missing site server include(s)."
}

test_nginx() {
  if [ "$SKIP_NGINX_TEST" = "1" ]; then
    log "Skipping nginx test because SKIP_NGINX_TEST=1."
    return
  fi

  if [ "$DRY_RUN" = "1" ]; then
    run_shell "$NGINX_TEST_COMMAND"
    return
  fi

  if sh -c "$NGINX_TEST_COMMAND"; then
    log "nginx syntax test passed."
    return
  fi

  restore_config_backups
  die "nginx syntax test failed. Config backups are in $CONFIG_BACKUP_DIR"
}

[ -n "$WEB_ROOT" ] || die "Set WEB_ROOT to the live Gnuboard document root."
[ -f "$WEB_ROOT/common.php" ] || die "WEB_ROOT does not look like a Gnuboard root: $WEB_ROOT"
[ -f "$PACKAGE_DIR/SERVER-INSTALL.sh" ] || die "SERVER-INSTALL.sh is missing from the package."
[ -f "$PACKAGE_DIR/SERVER-NGINX-PLAN.sh" ] || die "SERVER-NGINX-PLAN.sh is missing from the package."
[ -f "$PACKAGE_DIR/SERVER-ACTIVATE-THEME.sh" ] || die "SERVER-ACTIVATE-THEME.sh is missing from the package."

NGINX_CONF_REAL="$(resolve_file "$NGINX_CONF")"
SITE_CONF_REAL="$(resolve_file "$SITE_CONF")"

[ -f "$NGINX_CONF_REAL" ] || die "NGINX_CONF is missing: $NGINX_CONF"
[ -f "$SITE_CONF_REAL" ] || die "SITE_CONF is missing: $SITE_CONF"
[ -r "$NGINX_CONF_REAL" ] || die "NGINX_CONF is not readable: $NGINX_CONF_REAL"
[ -r "$SITE_CONF_REAL" ] || die "SITE_CONF is not readable: $SITE_CONF_REAL"

if [ "$DRY_RUN" != "1" ] && [ "$(id -u)" != "0" ]; then
  die "Run this script as root, or use sudo. Set DRY_RUN=1 for a non-root preview."
fi

log "Package: $PACKAGE_DIR"
log "Web root: $WEB_ROOT"
log "Nginx config: $NGINX_CONF_REAL"
log "Site config: $SITE_CONF_REAL"
log "Snippets dir: $NGINX_SNIPPETS_DIR"
log "Mode: $([ "$DRY_RUN" = "1" ] && printf 'dry-run' || printf 'apply')"

if [ "$SKIP_NGINX_PLAN" != "1" ]; then
  NGINX_CONF="$NGINX_CONF_REAL" \\
    SITE_CONF="$SITE_CONF_REAL" \\
    NGINX_SNIPPETS_DIR="$NGINX_SNIPPETS_DIR" \\
    WRITE_SITE_SNIPPET=1 \\
    bash "$PACKAGE_DIR/SERVER-NGINX-PLAN.sh"
fi

WEB_ROOT="$WEB_ROOT" \\
  NGINX_SNIPPETS_DIR="$NGINX_SNIPPETS_DIR" \\
  DRY_RUN="$DRY_RUN" \\
  SKIP_NGINX_INSTALL="$SKIP_NGINX_INSTALL" \\
  SKIP_API_INSTALL="$SKIP_API_INSTALL" \\
  SKIP_ROOT_PATCH_INSTALL="$SKIP_ROOT_PATCH_INSTALL" \\
  SKIP_NGINX_TEST=1 \\
  SKIP_NGINX_RELOAD=1 \\
  SUPPRESS_MANUAL_CHECKS=1 \\
  bash "$PACKAGE_DIR/SERVER-INSTALL.sh"

ensure_http_include
ensure_site_includes
test_nginx

if [ "$SKIP_NGINX_RELOAD" = "1" ]; then
  log "Skipping nginx reload because SKIP_NGINX_RELOAD=1."
else
  run_shell "$NGINX_RELOAD_COMMAND"
fi

WEB_ROOT="$WEB_ROOT" \\
  PHP_BIN="$PHP_BIN" \\
  PHP_WEB_ROOT="$PHP_WEB_ROOT" \\
  THEME="$THEME" \\
  APPLY="$ACTIVATE_THEME" \\
  bash "$PACKAGE_DIR/SERVER-ACTIVATE-THEME.sh"

if [ "$RUN_VERIFY" = "1" ]; then
  WEB_ROOT="$WEB_ROOT" \\
    NGINX_SNIPPETS_DIR="$NGINX_SNIPPETS_DIR" \\
    NGINX_TEST_COMMAND="$NGINX_TEST_COMMAND" \\
    SKIP_NGINX_TEST="$SKIP_NGINX_TEST" \\
    SKIP_NGINX_DUMP="$SKIP_NGINX_DUMP" \\
    SKIP_PHP_THEME_CHECK="$SKIP_PHP_THEME_CHECK" \\
    PHP_BIN="$PHP_BIN" \\
    PHP_WEB_ROOT="$PHP_WEB_ROOT" \\
    bash "$PACKAGE_DIR/SERVER-VERIFY.sh"
else
  log "Skipping server verify because RUN_VERIFY=$RUN_VERIFY."
fi

log "Root apply flow finished."
`;

const serverRootCommandsScript = `#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_WEB_ROOT=${bashLiteral(liveDefaultWebRoot)}
DEFAULT_NGINX_CONF=${bashLiteral(liveDefaultNginxConf)}
DEFAULT_SITE_CONF=${bashLiteral(liveDefaultSiteConf)}
DEFAULT_NGINX_SNIPPETS_DIR=${bashLiteral(liveDefaultNginxSnippetsDir)}

WEB_ROOT="\${WEB_ROOT:-$DEFAULT_WEB_ROOT}"
NGINX_CONF="\${NGINX_CONF:-$DEFAULT_NGINX_CONF}"
SITE_CONF="\${SITE_CONF:-$DEFAULT_SITE_CONF}"
NGINX_SNIPPETS_DIR="\${NGINX_SNIPPETS_DIR:-$DEFAULT_NGINX_SNIPPETS_DIR}"
THEME="\${THEME:-nextjs25}"
PHP_BIN="\${PHP_BIN:-php}"
PHP_WEB_ROOT="\${PHP_WEB_ROOT:-}"
SKIP_NGINX_PLAN="\${SKIP_NGINX_PLAN:-0}"
SKIP_NGINX_INSTALL="\${SKIP_NGINX_INSTALL:-0}"
SKIP_NGINX_TEST="\${SKIP_NGINX_TEST:-0}"
SKIP_NGINX_DUMP="\${SKIP_NGINX_DUMP:-0}"
SKIP_PHP_THEME_CHECK="\${SKIP_PHP_THEME_CHECK:-0}"
NGINX_TEST_COMMAND="\${NGINX_TEST_COMMAND:-nginx -t}"
NGINX_RELOAD_COMMAND="\${NGINX_RELOAD_COMMAND:-systemctl reload nginx}"
MODE="\${1:-dry-run}"

usage() {
  cat <<'USAGE'
Usage:
  bash SERVER-ROOT-COMMANDS.sh status
  sudo bash SERVER-ROOT-COMMANDS.sh dry-run
  sudo bash SERVER-ROOT-COMMANDS.sh apply
  sudo bash SERVER-ROOT-COMMANDS.sh verify
  sudo env CONFIRM_APPLY=nextjs25 bash SERVER-ROOT-COMMANDS.sh apply-and-verify
  bash SERVER-ROOT-COMMANDS.sh print-dry-run
  bash SERVER-ROOT-COMMANDS.sh print-apply
  bash SERVER-ROOT-COMMANDS.sh print-verify
  bash SERVER-ROOT-COMMANDS.sh print-apply-and-verify

Environment overrides:
  WEB_ROOT, NGINX_CONF, SITE_CONF, NGINX_SNIPPETS_DIR, PHP_BIN, PHP_WEB_ROOT,
  CONFIRM_APPLY

The generated live defaults target nextjs.thisgun.net. Use dry-run first and
only run apply after the output looks correct.
USAGE
}

print_command() {
  local dry_run="$1"
  local activate_theme="$2"
  local run_verify="$3"
  local skip_reload="$4"

  printf 'cd '
  printf '%q' "$PACKAGE_DIR"
  printf '\\n'
  printf 'sudo env'
  printf ' WEB_ROOT=%q' "$WEB_ROOT"
  printf ' NGINX_CONF=%q' "$NGINX_CONF"
  printf ' SITE_CONF=%q' "$SITE_CONF"
  printf ' NGINX_SNIPPETS_DIR=%q' "$NGINX_SNIPPETS_DIR"
  printf ' THEME=%q' "$THEME"
  printf ' DRY_RUN=%q' "$dry_run"
  printf ' SKIP_NGINX_RELOAD=%q' "$skip_reload"
  printf ' ACTIVATE_THEME=%q' "$activate_theme"
  printf ' RUN_VERIFY=%q' "$run_verify"
  printf ' bash SERVER-ROOT-APPLY.sh\\n'
}

print_verify_command() {
  printf 'cd '
  printf '%q' "$PACKAGE_DIR"
  printf '\\n'
  printf 'sudo env'
  printf ' WEB_ROOT=%q' "$WEB_ROOT"
  printf ' NGINX_SNIPPETS_DIR=%q' "$NGINX_SNIPPETS_DIR"
  printf ' PHP_BIN=%q' "$PHP_BIN"
  if [ -n "$PHP_WEB_ROOT" ]; then
    printf ' PHP_WEB_ROOT=%q' "$PHP_WEB_ROOT"
  fi
  printf ' bash SERVER-ROOT-COMMANDS.sh verify\\n'
}

print_apply_and_verify_command() {
  printf 'cd '
  printf '%q' "$PACKAGE_DIR"
  printf '\\n'
  printf 'sudo env'
  printf ' WEB_ROOT=%q' "$WEB_ROOT"
  printf ' NGINX_CONF=%q' "$NGINX_CONF"
  printf ' SITE_CONF=%q' "$SITE_CONF"
  printf ' NGINX_SNIPPETS_DIR=%q' "$NGINX_SNIPPETS_DIR"
  printf ' THEME=%q' "$THEME"
  printf ' CONFIRM_APPLY=%q' "$THEME"
  printf ' PHP_BIN=%q' "$PHP_BIN"
  if [ -n "$PHP_WEB_ROOT" ]; then
    printf ' PHP_WEB_ROOT=%q' "$PHP_WEB_ROOT"
  fi
  printf ' bash SERVER-ROOT-COMMANDS.sh apply-and-verify\\n'
}

case "$MODE" in
  -h|--help|help)
    usage
    exit 0
    ;;
  status)
    [ -f "$PACKAGE_DIR/SERVER-NGINX-PLAN.sh" ] || {
      printf '[server-root-commands] ERROR: SERVER-NGINX-PLAN.sh is missing from %s\\n' "$PACKAGE_DIR" >&2
      exit 1
    }
    [ -f "$PACKAGE_DIR/SERVER-ACTIVATE-THEME.sh" ] || {
      printf '[server-root-commands] ERROR: SERVER-ACTIVATE-THEME.sh is missing from %s\\n' "$PACKAGE_DIR" >&2
      exit 1
    }
    printf '[server-root-commands] package: %s\\n' "$PACKAGE_DIR"
    printf '[server-root-commands] mode: status\\n'
    printf '[server-root-commands] web root: %s\\n' "$WEB_ROOT"
    printf '[server-root-commands] nginx conf: %s\\n' "$NGINX_CONF"
    printf '[server-root-commands] site conf: %s\\n' "$SITE_CONF"
    NGINX_CONF="$NGINX_CONF" \\
      SITE_CONF="$SITE_CONF" \\
      NGINX_SNIPPETS_DIR="$NGINX_SNIPPETS_DIR" \\
      WRITE_SITE_SNIPPET="0" \\
      bash "$PACKAGE_DIR/SERVER-NGINX-PLAN.sh"
    WEB_ROOT="$WEB_ROOT" \\
      PHP_BIN="$PHP_BIN" \\
      PHP_WEB_ROOT="$PHP_WEB_ROOT" \\
      THEME="$THEME" \\
      APPLY="0" \\
      bash "$PACKAGE_DIR/SERVER-ACTIVATE-THEME.sh"
    exit 0
    ;;
  dry-run|preview)
    DRY_RUN="1"
    ACTIVATE_THEME="\${ACTIVATE_THEME:-0}"
    RUN_VERIFY="\${RUN_VERIFY:-0}"
    SKIP_NGINX_RELOAD="\${SKIP_NGINX_RELOAD:-1}"
    ;;
  apply)
    DRY_RUN="0"
    ACTIVATE_THEME="\${ACTIVATE_THEME:-1}"
    RUN_VERIFY="\${RUN_VERIFY:-1}"
    SKIP_NGINX_RELOAD="\${SKIP_NGINX_RELOAD:-0}"
    ;;
  apply-and-verify|apply-verify|finalize)
    if [ "\${CONFIRM_APPLY:-}" != "$THEME" ]; then
      printf '[server-root-commands] ERROR: apply-and-verify requires CONFIRM_APPLY=%s after reviewing dry-run output.\\n' "$THEME" >&2
      exit 1
    fi
    if [ "$(id -u)" != "0" ]; then
      printf '[server-root-commands] ERROR: apply-and-verify mode must run as root. Use sudo env CONFIRM_APPLY=%s bash SERVER-ROOT-COMMANDS.sh apply-and-verify\\n' "$THEME" >&2
      exit 1
    fi
    printf '[server-root-commands] package: %s\\n' "$PACKAGE_DIR"
    printf '[server-root-commands] mode: apply-and-verify\\n'
    printf '[server-root-commands] web root: %s\\n' "$WEB_ROOT"
    printf '[server-root-commands] nginx conf: %s\\n' "$NGINX_CONF"
    printf '[server-root-commands] site conf: %s\\n' "$SITE_CONF"
    WEB_ROOT="$WEB_ROOT" \\
      NGINX_CONF="$NGINX_CONF" \\
      SITE_CONF="$SITE_CONF" \\
      NGINX_SNIPPETS_DIR="$NGINX_SNIPPETS_DIR" \\
      THEME="$THEME" \\
      PHP_BIN="$PHP_BIN" \\
      PHP_WEB_ROOT="$PHP_WEB_ROOT" \\
      SKIP_NGINX_PLAN="$SKIP_NGINX_PLAN" \\
      SKIP_NGINX_INSTALL="$SKIP_NGINX_INSTALL" \\
      SKIP_NGINX_TEST="$SKIP_NGINX_TEST" \\
      SKIP_NGINX_DUMP="$SKIP_NGINX_DUMP" \\
      SKIP_PHP_THEME_CHECK="$SKIP_PHP_THEME_CHECK" \\
      NGINX_TEST_COMMAND="$NGINX_TEST_COMMAND" \\
      NGINX_RELOAD_COMMAND="$NGINX_RELOAD_COMMAND" \\
      ACTIVATE_THEME="1" \\
      RUN_VERIFY="0" \\
      SKIP_NGINX_RELOAD="\${SKIP_NGINX_RELOAD:-0}" \\
      bash "$PACKAGE_DIR/SERVER-ROOT-COMMANDS.sh" apply
    WEB_ROOT="$WEB_ROOT" \\
      NGINX_CONF="$NGINX_CONF" \\
      SITE_CONF="$SITE_CONF" \\
      NGINX_SNIPPETS_DIR="$NGINX_SNIPPETS_DIR" \\
      THEME="$THEME" \\
      PHP_BIN="$PHP_BIN" \\
      PHP_WEB_ROOT="$PHP_WEB_ROOT" \\
      NGINX_TEST_COMMAND="$NGINX_TEST_COMMAND" \\
      SKIP_NGINX_TEST="$SKIP_NGINX_TEST" \\
      SKIP_NGINX_DUMP="$SKIP_NGINX_DUMP" \\
      SKIP_PHP_THEME_CHECK="$SKIP_PHP_THEME_CHECK" \\
      bash "$PACKAGE_DIR/SERVER-ROOT-COMMANDS.sh" verify
    exit 0
    ;;
  verify)
    [ -f "$PACKAGE_DIR/SERVER-VERIFY.sh" ] || {
      printf '[server-root-commands] ERROR: SERVER-VERIFY.sh is missing from %s\\n' "$PACKAGE_DIR" >&2
      exit 1
    }
    [ -f "$WEB_ROOT/common.php" ] || {
      printf '[server-root-commands] ERROR: WEB_ROOT does not look like a Gnuboard root: %s\\n' "$WEB_ROOT" >&2
      exit 1
    }
    if [ "$(id -u)" != "0" ]; then
      printf '[server-root-commands] ERROR: verify mode should run as root for nginx -t and nginx -T access. Use sudo bash SERVER-ROOT-COMMANDS.sh verify\\n' >&2
      exit 1
    fi
    printf '[server-root-commands] package: %s\\n' "$PACKAGE_DIR"
    printf '[server-root-commands] mode: verify\\n'
    printf '[server-root-commands] web root: %s\\n' "$WEB_ROOT"
    printf '[server-root-commands] nginx conf: %s\\n' "$NGINX_CONF"
    printf '[server-root-commands] site conf: %s\\n' "$SITE_CONF"
    NGINX_CONF="$NGINX_CONF" \\
      SITE_CONF="$SITE_CONF" \\
      NGINX_SNIPPETS_DIR="$NGINX_SNIPPETS_DIR" \\
      WRITE_SITE_SNIPPET="0" \\
      bash "$PACKAGE_DIR/SERVER-NGINX-PLAN.sh"
    WEB_ROOT="$WEB_ROOT" \\
      NGINX_SNIPPETS_DIR="$NGINX_SNIPPETS_DIR" \\
      NGINX_TEST_COMMAND="$NGINX_TEST_COMMAND" \\
      SKIP_NGINX_TEST="$SKIP_NGINX_TEST" \\
      SKIP_NGINX_DUMP="$SKIP_NGINX_DUMP" \\
      SKIP_PHP_THEME_CHECK="$SKIP_PHP_THEME_CHECK" \\
      PHP_BIN="$PHP_BIN" \\
      PHP_WEB_ROOT="$PHP_WEB_ROOT" \\
      bash "$PACKAGE_DIR/SERVER-VERIFY.sh"
    exit 0
    ;;
  print-dry-run|print-preview)
    print_command "1" "\${ACTIVATE_THEME:-0}" "\${RUN_VERIFY:-0}" "\${SKIP_NGINX_RELOAD:-1}"
    exit 0
    ;;
  print-apply)
    print_command "0" "\${ACTIVATE_THEME:-1}" "\${RUN_VERIFY:-1}" "\${SKIP_NGINX_RELOAD:-0}"
    exit 0
    ;;
  print-verify)
    print_verify_command
    exit 0
    ;;
  print-apply-and-verify|print-finalize)
    print_apply_and_verify_command
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

[ -f "$PACKAGE_DIR/SERVER-ROOT-APPLY.sh" ] || {
  printf '[server-root-commands] ERROR: SERVER-ROOT-APPLY.sh is missing from %s\\n' "$PACKAGE_DIR" >&2
  exit 1
}

[ -f "$WEB_ROOT/common.php" ] || {
  printf '[server-root-commands] ERROR: WEB_ROOT does not look like a Gnuboard root: %s\\n' "$WEB_ROOT" >&2
  exit 1
}

if [ "$DRY_RUN" != "1" ] && [ "$(id -u)" != "0" ]; then
  printf '[server-root-commands] ERROR: apply mode must run as root. Use sudo bash SERVER-ROOT-COMMANDS.sh apply\\n' >&2
  exit 1
fi

printf '[server-root-commands] package: %s\\n' "$PACKAGE_DIR"
printf '[server-root-commands] mode: %s\\n' "$MODE"
printf '[server-root-commands] web root: %s\\n' "$WEB_ROOT"
printf '[server-root-commands] nginx conf: %s\\n' "$NGINX_CONF"
printf '[server-root-commands] site conf: %s\\n' "$SITE_CONF"

WEB_ROOT="$WEB_ROOT" \\
  NGINX_CONF="$NGINX_CONF" \\
  SITE_CONF="$SITE_CONF" \\
  NGINX_SNIPPETS_DIR="$NGINX_SNIPPETS_DIR" \\
  THEME="$THEME" \\
  PHP_BIN="$PHP_BIN" \\
  PHP_WEB_ROOT="$PHP_WEB_ROOT" \\
  DRY_RUN="$DRY_RUN" \\
  SKIP_NGINX_PLAN="$SKIP_NGINX_PLAN" \\
  SKIP_NGINX_INSTALL="$SKIP_NGINX_INSTALL" \\
  SKIP_NGINX_TEST="$SKIP_NGINX_TEST" \\
  SKIP_NGINX_RELOAD="$SKIP_NGINX_RELOAD" \\
  SKIP_NGINX_DUMP="$SKIP_NGINX_DUMP" \\
  SKIP_PHP_THEME_CHECK="$SKIP_PHP_THEME_CHECK" \\
  NGINX_TEST_COMMAND="$NGINX_TEST_COMMAND" \\
  NGINX_RELOAD_COMMAND="$NGINX_RELOAD_COMMAND" \\
  ACTIVATE_THEME="$ACTIVATE_THEME" \\
  RUN_VERIFY="$RUN_VERIFY" \\
  bash "$PACKAGE_DIR/SERVER-ROOT-APPLY.sh"
`;

const serverVerifyScript = `#!/usr/bin/env bash
set -euo pipefail

PACKAGE_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
WEB_ROOT="\${WEB_ROOT:-}"
NGINX_SNIPPETS_DIR="\${NGINX_SNIPPETS_DIR:-/etc/nginx/snippets}"
NGINX_DUMP_COMMAND="\${NGINX_DUMP_COMMAND:-nginx -T}"
SKIP_NGINX_DUMP="\${SKIP_NGINX_DUMP:-0}"
SKIP_NGINX_TEST="\${SKIP_NGINX_TEST:-0}"
NGINX_TEST_COMMAND="\${NGINX_TEST_COMMAND:-nginx -t}"
SKIP_PHP_THEME_CHECK="\${SKIP_PHP_THEME_CHECK:-0}"
PHP_BIN="\${PHP_BIN:-php}"
PHP_WEB_ROOT="\${PHP_WEB_ROOT:-}"

if [ -z "$PHP_WEB_ROOT" ]; then
  PHP_WEB_ROOT="$WEB_ROOT"
  if [[ "$PHP_BIN" == *.exe && "$WEB_ROOT" =~ ^/mnt/([A-Za-z])/(.*)$ ]]; then
    PHP_WEB_ROOT="\${BASH_REMATCH[1]^^}:/\${BASH_REMATCH[2]}"
  fi
fi

failures=0
warnings=0
CONFIG_DUMP=""

log() {
  printf '[server-verify] %s\\n' "$*"
}

ok() {
  printf '[server-verify] ok: %s\\n' "$*"
}

warn() {
  warnings=$((warnings + 1))
  printf '[server-verify] warn: %s\\n' "$*" >&2
}

fail() {
  failures=$((failures + 1))
  printf '[server-verify] fail: %s\\n' "$*" >&2
}

make_temp_output() {
  local label="$1"
  local tmp_base=""
  tmp_base="$(printenv TMPDIR 2>/dev/null || true)"
  [ -n "$tmp_base" ] || tmp_base="/tmp"

  if mktemp "$tmp_base/g5-nextjs25-$label.XXXXXX" 2>/dev/null; then
    return 0
  fi

  mktemp "$PACKAGE_DIR/.g5-nextjs25-$label.XXXXXX"
}

check_file() {
  if [ -f "$1" ]; then
    ok "$2"
  else
    fail "$2 missing: $1"
  fi
}

check_dir() {
  if [ -d "$1" ]; then
    ok "$2"
  else
    fail "$2 missing: $1"
  fi
}

check_contains() {
  if [ -f "$1" ] && grep -Fq "$2" "$1"; then
    ok "$3"
  else
    fail "$3 missing marker: $2"
  fi
}

check_loaded_config() {
  if [ -z "$CONFIG_DUMP" ]; then
    warn "Skipping loaded nginx config check for $1 because nginx -T output is unavailable."
    return
  fi

  if grep -Fq "$1" "$CONFIG_DUMP"; then
    ok "$2"
  else
    fail "$2 not found in loaded nginx config: $1"
  fi
}

[ -n "$WEB_ROOT" ] || {
  fail "Set WEB_ROOT to the live Gnuboard document root."
  printf '[server-verify] summary: %s failure(s), %s warning(s)\\n' "$failures" "$warnings"
  exit 1
}

log "Web root: $WEB_ROOT"
log "Nginx snippets: $NGINX_SNIPPETS_DIR"

if [ -f "$PACKAGE_DIR/CHECKSUMS.sha256" ]; then
  if command -v sha256sum >/dev/null 2>&1; then
    CHECKSUM_OUTPUT=""
    TMP_BASE="$(printenv TMPDIR 2>/dev/null || true)"
    [ -n "$TMP_BASE" ] || TMP_BASE="/tmp"
    if CHECKSUM_OUTPUT="$(mktemp "$TMP_BASE/g5-nextjs25-checksums.XXXXXX" 2>/dev/null)"; then
      :
    else
      CHECKSUM_OUTPUT="$PACKAGE_DIR/.g5-nextjs25-checksums.$$"
    fi
    if (cd "$PACKAGE_DIR" && sha256sum -c CHECKSUMS.sha256 >"$CHECKSUM_OUTPUT" 2>&1); then
      rm -f "$CHECKSUM_OUTPUT"
      ok "package checksums"
    else
      fail "package checksum verification failed; see $CHECKSUM_OUTPUT"
    fi
  else
    warn "sha256sum command not found; skipping package checksum verification"
  fi
else
  warn "CHECKSUMS.sha256 is missing from package"
fi

check_file "$WEB_ROOT/common.php" "Gnuboard common.php"
check_dir "$WEB_ROOT/api" "Next.js API bridge directory"
check_file "$WEB_ROOT/api/index.php" "Next.js API front controller"
check_file "$WEB_ROOT/api/v1/settings.php" "Next.js settings API"
check_file "$WEB_ROOT/api/v1/shop/router.php" "Youngcart shop API router"
check_file "$WEB_ROOT/api/v1/shop/products.php" "Youngcart products API"
check_file "$WEB_ROOT/api/v1/shop/reviews.php" "Youngcart reviews API"
check_file "$WEB_ROOT/api/v1/shop/policy.php" "Youngcart policy API"
check_file "$WEB_ROOT/api/v1/shop/shipping.php" "Youngcart shipping API"
check_file "$WEB_ROOT/api/social/_bridge_common.php" "Next.js social bridge common"
check_file "$WEB_ROOT/plugin/social/includes/functions.php" "Gnuboard social plugin functions"
check_file "$WEB_ROOT/extend/nextjs25-social.extend.php" "Next.js social extend loader"
check_contains "$WEB_ROOT/plugin/social/includes/functions.php" "social_login_linked_provider_before_member_check" "social linked provider hook"
check_contains "$WEB_ROOT/plugin/social/includes/functions.php" "social_login_existing_member_before_link_prompt" "social existing member hook"
check_dir "$WEB_ROOT/theme" "Gnuboard theme directory"
check_dir "$WEB_ROOT/theme/nextjs25" "Next.js 25 theme directory"
check_file "$WEB_ROOT/theme/nextjs25/route.php" "Next.js 25 route bridge"
check_file "$WEB_ROOT/theme/nextjs25/bridge/app-shell.php" "Next.js 25 app shell bridge"
check_file "$WEB_ROOT/theme/nextjs25/app/index.html" "Next.js 25 static index"
check_file "$WEB_ROOT/theme/nextjs25/app/manifest.webmanifest" "Next.js 25 manifest"
check_file "$WEB_ROOT/theme/nextjs25/app/robots.txt" "Next.js 25 robots"
check_file "$WEB_ROOT/theme/nextjs25/app/sitemap.xml" "Next.js 25 sitemap"
check_file "$WEB_ROOT/theme/nextjs25/app/sitemap-posts.xml" "Next.js 25 posts sitemap"
check_file "$WEB_ROOT/theme/nextjs25/app/sw.js" "Next.js 25 service worker"
check_dir "$WEB_ROOT/theme/nextjs25/app/_next" "Next.js runtime chunks"
check_contains "$WEB_ROOT/theme/nextjs25/bridge/app-shell.php" "window.__G5_NEXTJS25_CONFIG__" "runtime config injector"

check_file "$NGINX_SNIPPETS_DIR/g5-nextjs25-security-map.conf" "nginx security map snippet"
check_file "$NGINX_SNIPPETS_DIR/g5-nextjs25-security-headers.conf" "nginx frontend security snippet"
check_file "$NGINX_SNIPPETS_DIR/g5-nextjs25-api-security-headers.conf" "nginx API security snippet"
check_file "$NGINX_SNIPPETS_DIR/g5-nextjs25-theme-locations.conf" "nginx theme locations snippet"

if [ "$SKIP_NGINX_TEST" != "1" ]; then
  NGINX_TEST_OUTPUT="$(make_temp_output nginx-test)"
  if sh -c "$NGINX_TEST_COMMAND" >"$NGINX_TEST_OUTPUT" 2>&1; then
    rm -f "$NGINX_TEST_OUTPUT"
    ok "nginx syntax test"
  else
    fail "nginx syntax test failed; see $NGINX_TEST_OUTPUT"
  fi
fi

if [ "$SKIP_NGINX_DUMP" != "1" ]; then
  CONFIG_DUMP="$(make_temp_output nginx-dump)"
  NGINX_DUMP_ERROR="$(make_temp_output nginx-dump-err)"
  if sh -c "$NGINX_DUMP_COMMAND" >"$CONFIG_DUMP" 2>"$NGINX_DUMP_ERROR"; then
    rm -f "$NGINX_DUMP_ERROR"
    ok "nginx loaded config dump"
  else
    warn "nginx config dump failed; see $NGINX_DUMP_ERROR"
    rm -f "$CONFIG_DUMP"
    CONFIG_DUMP=""
  fi
fi

check_loaded_config "g5-nextjs25-security-map.conf" "loaded security map include"
check_loaded_config "g5-nextjs25-theme-locations.conf" "loaded theme locations include"
check_loaded_config "g5-nextjs25-api-security-headers.conf" "loaded API security include"
check_loaded_config "location = /theme/nextjs25/route.php" "loaded exact route.php PHP location"
check_loaded_config "location = /api/index.php" "loaded exact API index PHP location"

if [ "$SKIP_PHP_THEME_CHECK" != "1" ]; then
  if command -v "$PHP_BIN" >/dev/null 2>&1; then
    active_theme="$(WEB_ROOT="$WEB_ROOT" PHP_WEB_ROOT="$PHP_WEB_ROOT" "$PHP_BIN" -d display_errors=stderr <<'PHP'
<?php
ob_start();
$webRoot = getenv('PHP_WEB_ROOT') ?: (getenv('WEB_ROOT') ?: '');
if (!chdir($webRoot)) {
    fwrite(STDERR, "[server-verify] ERROR: Cannot enter WEB_ROOT.\\n");
    exit(1);
}
$_SERVER['SERVER_NAME'] = $_SERVER['SERVER_NAME'] ?? 'localhost';
$_SERVER['HTTP_HOST'] = $_SERVER['HTTP_HOST'] ?? $_SERVER['SERVER_NAME'];
$_SERVER['SERVER_PORT'] = $_SERVER['SERVER_PORT'] ?? '80';
$_SERVER['REQUEST_URI'] = $_SERVER['REQUEST_URI'] ?? '/';
$_SERVER['REQUEST_METHOD'] = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$_SERVER['REMOTE_ADDR'] = $_SERVER['REMOTE_ADDR'] ?? '127.0.0.1';
include './common.php';
ob_end_clean();
global $config;
echo isset($config['cf_theme']) ? $config['cf_theme'] : '';
PHP
)"
    if [ "$active_theme" = "nextjs25" ]; then
      ok "Gnuboard active theme is nextjs25"
    else
      fail "Gnuboard active theme is '$active_theme', expected 'nextjs25'"
    fi
  else
    warn "PHP_BIN command not found; skipping active theme check: $PHP_BIN"
  fi
fi

if [ -n "$CONFIG_DUMP" ]; then
  rm -f "$CONFIG_DUMP"
fi

printf '[server-verify] summary: %s failure(s), %s warning(s)\\n' "$failures" "$warnings"

if [ "$failures" -gt 0 ]; then
  exit 1
fi
`;

function fail(message) {
  console.error(`[package-live-deploy] ${message}`);
  process.exit(1);
}

function assertExists(path, label) {
  if (!existsSync(path)) {
    fail(`Missing ${label}: ${path}`);
  }
}

function countFiles(dir) {
  let total = 0;

  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const entryPath = join(dir, entry.name);

    if (entry.isDirectory()) {
      total += countFiles(entryPath);
      continue;
    }

    if (entry.isFile()) {
      total += 1;
    }
  }

  return total;
}

function collectFiles(dir, baseDir = dir) {
  const files = [];

  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const entryPath = join(dir, entry.name);

    if (entry.isDirectory()) {
      files.push(...collectFiles(entryPath, baseDir));
      continue;
    }

    if (entry.isFile()) {
      const relativePath = relative(baseDir, entryPath).replaceAll('\\', '/');
      if (relativePath !== checksumFileName) {
        files.push({ absolutePath: entryPath, relativePath });
      }
    }
  }

  return files.sort((a, b) => a.relativePath.localeCompare(b.relativePath));
}

function assertNoForbiddenLiveStaticOrigins(dir) {
  const matches = [];

  for (const file of collectFiles(dir)) {
    if (!liveStaticTextExtensions.has(extname(file.relativePath))) {
      continue;
    }

    const content = readFileSync(file.absolutePath, 'utf8');
    const pattern = forbiddenLiveStaticPatterns.find((candidate) => content.includes(candidate));
    if (pattern) {
      matches.push(`${file.relativePath}: ${pattern}`);
    }
  }

  if (matches.length > 0) {
    fail(
      [
        'Live package contains local development origins in static theme files.',
        'Set NEXT_PUBLIC_APP_URL, NEXT_PUBLIC_API_URL, and NEXT_PUBLIC_G5_URL to live HTTPS values before npm run build:theme.',
        `First match(es): ${matches.slice(0, 5).join('; ')}`,
      ].join(' ')
    );
  }
}

function shouldCopyApiEntry(source) {
  const relativePath = relative(apiSource, source).replaceAll('\\', '/');
  if (relativePath === '') {
    return true;
  }

  return !relativePath.split('/').some((part) => part === '.env' || part.startsWith('.env.'));
}

function sha256File(path) {
  return createHash('sha256').update(readFileSync(path)).digest('hex');
}

function collectArchiveFiles(dir, baseDir = deployBaseRoot) {
  const files = [];

  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const entryPath = join(dir, entry.name);

    if (entry.isDirectory()) {
      files.push(...collectArchiveFiles(entryPath, baseDir));
      continue;
    }

    if (entry.isFile()) {
      files.push({
        absolutePath: entryPath,
        archivePath: relative(baseDir, entryPath).replaceAll('\\', '/'),
      });
    }
  }

  return files.sort((a, b) => a.archivePath.localeCompare(b.archivePath));
}

function shouldNormalizePackageTextFile(relativePath) {
  const normalized = relativePath.replaceAll('\\', '/');
  const fileName = normalized.split('/').pop() || '';

  return (
    packageTextFileNames.has(fileName) ||
    packageTextExtensions.has(extname(fileName).toLowerCase())
  );
}

function normalizePackageLineEndings(dir) {
  let normalizedCount = 0;

  for (const file of collectFiles(dir)) {
    if (!shouldNormalizePackageTextFile(file.relativePath)) {
      continue;
    }

    const buffer = readFileSync(file.absolutePath);
    if (buffer.includes(0x00)) {
      continue;
    }

    const content = buffer.toString('utf8');
    const normalized = content.replace(/\r\n?/g, '\n');
    if (normalized === content) {
      continue;
    }

    writeFileSync(file.absolutePath, normalized);
    normalizedCount += 1;
  }

  return normalizedCount;
}

function splitTarPath(path) {
  const normalized = String(path).replaceAll('\\', '/');

  if (Buffer.byteLength(normalized) <= 100) {
    return { name: normalized, prefix: '' };
  }

  const parts = normalized.split('/');
  for (let i = parts.length - 1; i > 0; i -= 1) {
    const prefix = parts.slice(0, i).join('/');
    const name = parts.slice(i).join('/');
    if (Buffer.byteLength(prefix) <= 155 && Buffer.byteLength(name) <= 100) {
      return { name, prefix };
    }
  }

  fail(`Archive path is too long for ustar header: ${normalized}`);
}

function writeTarString(header, value, offset, length) {
  const bytes = Buffer.from(String(value), 'utf8');
  if (bytes.length > length) {
    fail(`Archive header field is too long: ${value}`);
  }
  bytes.copy(header, offset);
}

function writeTarOctal(header, value, offset, length) {
  const octal = Math.trunc(value).toString(8);
  const text = `${octal.padStart(length - 1, '0')}\0`;
  writeTarString(header, text, offset, length);
}

function createTarHeader(file, stats) {
  const header = Buffer.alloc(512, 0);
  const { name, prefix } = splitTarPath(file.archivePath);
  const mode = stats.mode & 0o777;

  writeTarString(header, name, 0, 100);
  writeTarOctal(header, mode || 0o644, 100, 8);
  writeTarOctal(header, 0, 108, 8);
  writeTarOctal(header, 0, 116, 8);
  writeTarOctal(header, stats.size, 124, 12);
  writeTarOctal(header, Math.floor(stats.mtimeMs / 1000), 136, 12);
  header.fill(0x20, 148, 156);
  writeTarString(header, '0', 156, 1);
  writeTarString(header, 'ustar\0', 257, 6);
  writeTarString(header, '00', 263, 2);
  writeTarString(header, 'nextjs', 265, 32);
  writeTarString(header, 'nextjs', 297, 32);
  writeTarString(header, prefix, 345, 155);

  let checksum = 0;
  for (const byte of header) {
    checksum += byte;
  }

  const checksumText = checksum.toString(8).padStart(6, '0');
  writeTarString(header, checksumText, 148, 6);
  header[154] = 0;
  header[155] = 0x20;

  return header;
}

function createTarGzArchive() {
  const chunks = [];

  for (const file of collectArchiveFiles(deployRoot)) {
    const stats = statSync(file.absolutePath);
    if (!stats.isFile()) {
      continue;
    }

    const contents = readFileSync(file.absolutePath);
    chunks.push(createTarHeader(file, stats), contents);

    const remainder = contents.length % 512;
    if (remainder !== 0) {
      chunks.push(Buffer.alloc(512 - remainder, 0));
    }
  }

  chunks.push(Buffer.alloc(1024, 0));
  writeFileSync(archivePath, gzipSync(Buffer.concat(chunks), { level: 9 }));
}

function normalizeRepoPath(path) {
  return String(path || '').trim().replaceAll('\\', '/');
}

function repoAbsolutePath(repoPath) {
  return join(repoRoot, ...repoPath.split('/').filter(Boolean));
}

function isExcludedSourceSnapshotPath(file) {
  if (!file.startsWith('api/')) {
    return false;
  }

  return file.split('/').some((part) => part === '.env' || part.startsWith('.env.'));
}

function collectSourceSnapshotFiles(dir) {
  const files = [];

  if (!existsSync(dir)) {
    return files;
  }

  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const entryPath = join(dir, entry.name);

    if (entry.isDirectory()) {
      files.push(...collectSourceSnapshotFiles(entryPath));
      continue;
    }

    if (entry.isFile()) {
      const file = normalizeRepoPath(relative(repoRoot, entryPath));
      if (!isExcludedSourceSnapshotPath(file)) {
        files.push(file);
      }
    }
  }

  return files;
}

function createSourceSnapshot() {
  const sourceFiles = new Set();

  for (const prefix of sourceSnapshotPrefixes) {
    for (const file of collectSourceSnapshotFiles(repoAbsolutePath(prefix))) {
      sourceFiles.add(file);
    }
  }

  for (const file of sourceSnapshotFiles) {
    if (!isExcludedSourceSnapshotPath(file) && existsSync(repoAbsolutePath(file))) {
      sourceFiles.add(file);
    }
  }

  const files = Array.from(sourceFiles).sort((a, b) => a.localeCompare(b));
  const digest = createHash('sha256');

  for (const file of files) {
    digest.update(`${sha256File(repoAbsolutePath(file))}  ${file}\n`, 'utf8');
  }

  return {
    version: 1,
    algorithm: 'sha256',
    digest: digest.digest('hex'),
    fileCount: files.length,
  };
}

function writeChecksumFile() {
  const files = collectFiles(deployRoot);
  const contents = files
    .map((file) => `${sha256File(file.absolutePath)}  ${file.relativePath}`)
    .join('\n');

  writeFileSync(join(deployRoot, checksumFileName), `${contents}\n`);

  return files.length;
}

function createDeployArchive() {
  rmSync(archivePath, rmRetryOptions);
  rmSync(join(deployBaseRoot, archiveChecksumFileName), rmRetryOptions);
  rmSync(join(deployBaseRoot, archiveManifestFileName), rmRetryOptions);
  const tarPath = archivePath.replace(/\.gz$/, '');
  rmSync(tarPath, rmRetryOptions);
  createTarGzArchive();

  const stats = statSync(archivePath);
  const sha256 = sha256File(archivePath);
  const archiveChecksumPath = join(deployBaseRoot, archiveChecksumFileName);
  const archiveManifestPath = join(deployBaseRoot, archiveManifestFileName);
  const archiveManifest = {
    archive: archiveName,
    checksumFile: archiveChecksumFileName,
    packageDirectory: deployPackageName,
    bytes: stats.size,
    sha256,
    generatedAt,
    gitBranch,
    gitCommit,
    sourceSnapshot,
  };

  writeFileSync(archiveChecksumPath, `${sha256}  ${archiveName}\n`);
  writeFileSync(archiveManifestPath, `${JSON.stringify(archiveManifest, null, 2)}\n`);

  return {
    bytes: stats.size,
    checksumFile: archiveChecksumFileName,
    manifestFile: archiveManifestFileName,
    name: archiveName,
    path: archivePath,
    sha256,
  };
}

function tryGit(args) {
  try {
    return execFileSync('git', args, {
      cwd: repoRoot,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'ignore'],
    }).trim();
  } catch {
    return null;
  }
}

function bashLiteral(value) {
  return `'${String(value).replaceAll("'", "'\\''")}'`;
}

function getThemeBuildSummary() {
  const indexPath = join(themeSource, 'app', 'index.html');
  const appShellPath = join(themeSource, 'bridge', 'app-shell.php');
  const stats = statSync(indexPath);
  const appShell = readFileSync(appShellPath, 'utf8');
  const configMarker = 'window.__G5_NEXTJS25_CONFIG__';

  return {
    indexHtmlBytes: stats.size,
    indexHtmlModifiedAt: stats.mtime.toISOString(),
    hasRuntimeConfigMarker: appShell.includes(configMarker),
  };
}

for (const file of requiredThemeFiles) {
  assertExists(join(themeSource, file), `theme file ${file}`);
}

for (const file of requiredApiFiles) {
  assertExists(join(apiSource, file), `API file ${file}`);
}

for (const file of rootPatchFiles) {
  assertExists(join(repoRoot, file), `root patch file ${file}`);
}

for (const snippet of nginxSnippets) {
  assertExists(join(docsNginxRoot, snippet.source), `nginx snippet ${snippet.source}`);
}

const themeSummary = getThemeBuildSummary();

if (!themeSummary.hasRuntimeConfigMarker) {
  fail(
    'theme/nextjs25/bridge/app-shell.php does not contain window.__G5_NEXTJS25_CONFIG__. Restore the Next.js 25 bridge before packaging.',
  );
}

rmSync(deployRoot, { recursive: true, ...rmRetryOptions });
mkdirSync(themeTarget, { recursive: true });
mkdirSync(apiTarget, { recursive: true });
mkdirSync(nginxRoot, { recursive: true });
mkdirSync(rootPatchRoot, { recursive: true });

cpSync(themeSource, themeTarget, { recursive: true });
cpSync(apiSource, apiTarget, { recursive: true, filter: shouldCopyApiEntry });

assertNoForbiddenLiveStaticOrigins(join(themeTarget, 'app'));

for (const file of rootPatchFiles) {
  const target = join(rootPatchRoot, file);
  mkdirSync(dirname(target), { recursive: true });
  copyFileSync(join(repoRoot, file), target);
}

for (const snippet of nginxSnippets) {
  copyFileSync(join(docsNginxRoot, snippet.source), join(nginxRoot, snippet.target));
}

const gitCommit = tryGit(['rev-parse', '--short', 'HEAD']);
const gitBranch = tryGit(['branch', '--show-current']);
const generatedAt = new Date().toISOString();
const themeFileCount = countFiles(themeTarget);
const apiFileCount = countFiles(apiTarget);
const rootPatchFileCount = countFiles(rootPatchRoot);
const sourceSnapshot = createSourceSnapshot();

const manifest = {
  name: 'g5-nextjs25-live-deploy',
  generatedAt,
  gitBranch,
  gitCommit,
  sourceSnapshot,
  uploadRoot: 'upload',
  themeTarget: 'upload/theme/nextjs25',
  apiTarget: 'upload/api',
  excludedApiPackagePatterns,
  rootPatchTarget: 'root-patch',
  nginxTarget: 'nginx',
  checksumFile: checksumFileName,
  archive: {
    file: `../${archiveName}`,
    checksumFile: `../${archiveChecksumFileName}`,
    manifestFile: `../${archiveManifestFileName}`,
  },
  themeFileCount,
  apiFileCount,
  rootPatchFileCount,
  themeBuild: themeSummary,
  nginxSnippets: nginxSnippets.map((snippet) => ({
    file: snippet.target,
    source: `docs/nginx/${snippet.source}`,
    installScope: snippet.installScope,
  })),
  serverScripts: [
    'SERVER-INSTALL.sh',
    'SERVER-ROLLBACK.sh',
    'SERVER-ACTIVATE-THEME.sh',
    'SERVER-NGINX-PLAN.sh',
    'SERVER-ROOT-APPLY.sh',
    'SERVER-ROOT-COMMANDS.sh',
    'SERVER-VERIFY.sh',
  ],
  verifyCommands: [
    'npm run check:live-root-handoff',
    'npm run check:live-deployment',
    'npm run check:live-runtime',
    'npm run check:release:live:nginx',
  ],
};

const readme = `# G5 Next.js 25 Live Deploy Package

Generated at: ${generatedAt}
Source branch: ${gitBranch ?? 'unknown'}
Source commit: ${gitCommit ?? 'unknown'}
Source snapshot: ${sourceSnapshot.digest} (${sourceSnapshot.fileCount} files)

This package contains the repository artifacts required to move the live
nextjs.thisgun.net frontend from the legacy Gnuboard theme to theme/nextjs25.

The generated archive sits next to this directory as ${archiveName}. Verify it
before unpacking:

\`\`\`bash
cd ..
sha256sum -c ${archiveChecksumFileName}
tar -xzf ${archiveName}
cd ${deployPackageName}
\`\`\`

## Contents

- upload/theme/nextjs25
  - Static Next.js export and Gnuboard theme bridge files.
  - Deploy over the web root path theme/nextjs25 after taking a server backup.
- upload/api
  - Repository PHP API front controller, libraries, and v1 handlers used by the
    Next.js theme.
  - Deploy over the web root path api after taking a server backup.
- root-patch
  - Minimal Gnuboard root-level bridge files required by the Next.js API.
  - Includes social login hook points and the extend loader for Next.js social
    OAuth callbacks. Deploy over the web root after taking a server backup.
- nginx/g5-nextjs25-security-map.conf
  - Include once inside nginx.conf http {}.
- nginx/g5-nextjs25-security-headers.conf
  - Include only in frontend/static locations.
- nginx/g5-nextjs25-api-security-headers.conf
  - Include inside the /api/ PHP-FPM location.
- nginx/g5-nextjs25-theme-locations.conf
  - Include inside the nextjs.thisgun.net server {} block before generic
    Gnuboard locations.
- nginx/g5-nextjs25-exact-php-locations.conf
  - Generated by SERVER-NGINX-PLAN.sh from the live site config.
  - Include inside the nextjs.thisgun.net server {} block so /theme/nextjs25/route.php
    and /api/index.php use separate frontend/API header snippets.
- CHECKSUMS.sha256
  - SHA-256 hashes for the package contents. SERVER-INSTALL.sh and
    SERVER-VERIFY.sh check this when sha256sum is available.
- ../${archiveName}
  - Tarball containing this package directory for upload.
- ../${archiveChecksumFileName}
  - SHA-256 checksum for the tarball.
- ../${archiveManifestFileName}
  - Machine-readable tarball size and SHA-256 metadata.
- SERVER-INSTALL.sh
  - Server-side helper for placing theme files, API files, root patch files, and
    nginx snippets with timestamped backups. Set SKIP_NGINX_INSTALL=1 when the
    SSH user can update web-root files but cannot write nginx snippets.
  - Set SKIP_API_INSTALL=1 only when you intentionally want to leave the live
    PHP API untouched.
  - Set SKIP_ROOT_PATCH_INSTALL=1 only when you intentionally want to leave the
    Gnuboard root-level hook files untouched.
- SERVER-ROLLBACK.sh
  - Server-side helper for restoring timestamped theme and optional API
    backups. It preserves the rollback source directories so recovery can be
    repeated if needed.
- SERVER-ACTIVATE-THEME.sh
  - Server-side helper for reading or updating Gnuboard cf_theme. It defaults
    to dry-run and only updates the database when APPLY=1 is set.
- SERVER-NGINX-PLAN.sh
  - Server-side helper for printing the site-specific nginx include and exact
    PHP location plan. It detects the live fastcgi_pass line from the current
    nextjs.thisgun.net site config.
- SERVER-ROOT-APPLY.sh
  - Root-side dry-run/apply helper that generates the exact PHP snippet, places
    theme and nginx files, inserts nginx includes with config backups, tests and
    reloads nginx, activates the theme, and runs server verification.
- SERVER-ROOT-COMMANDS.sh
  - Sudo-friendly wrapper around SERVER-ROOT-APPLY.sh with live defaults for
    nextjs.thisgun.net. Use status first, then dry-run, then apply-and-verify.
- SERVER-VERIFY.sh
  - Server-side preflight/postflight checker for theme files, nginx snippets,
    loaded nginx includes, nginx syntax, and the active Gnuboard theme.

## Install Order

1. Put this package directory on the live server.
2. Check package integrity:

   \`\`\`bash
   sha256sum -c CHECKSUMS.sha256
   \`\`\`

3. Preview the full root-side apply flow:

   \`\`\`bash
   bash SERVER-ROOT-COMMANDS.sh status
   sudo bash SERVER-ROOT-COMMANDS.sh dry-run
   \`\`\`

4. Apply the full root-side flow after the preview looks correct:

   \`\`\`bash
   sudo env CONFIRM_APPLY=nextjs25 bash SERVER-ROOT-COMMANDS.sh apply-and-verify
   \`\`\`

   The root helper backs up nginx configs under
   backups/nginx-YYYYMMDD-HHMMSS, inserts the required includes, runs nginx -t,
   reloads nginx, activates the nextjs25 theme, and verifies the result.

5. If you prefer separate apply and verify commands, run:

   \`\`\`bash
   sudo bash SERVER-ROOT-COMMANDS.sh apply
   sudo bash SERVER-ROOT-COMMANDS.sh verify
   \`\`\`

   If the live web root differs from ${liveDefaultWebRoot}, pass it explicitly:

   \`\`\`bash
   sudo env WEB_ROOT=/path/to/gnuboard bash SERVER-ROOT-COMMANDS.sh dry-run
   sudo env WEB_ROOT=/path/to/gnuboard CONFIRM_APPLY=nextjs25 bash SERVER-ROOT-COMMANDS.sh apply-and-verify
   \`\`\`

## Manual Install Order

Use these steps only if you do not want SERVER-ROOT-APPLY.sh to edit nginx
configs for you.

1. Dry-run the file placement:

   \`\`\`bash
   sudo env WEB_ROOT=/path/to/gnuboard DRY_RUN=1 bash SERVER-INSTALL.sh
   \`\`\`

2. Apply the file placement:

   \`\`\`bash
   sudo env WEB_ROOT=/path/to/gnuboard bash SERVER-INSTALL.sh
   \`\`\`

   For a non-root web-root-only install, skip nginx writes and keep the theme
   inactive until the nginx include step is ready:

   \`\`\`bash
   WEB_ROOT=/path/to/gnuboard SKIP_NGINX_INSTALL=1 SKIP_NGINX_TEST=1 SKIP_NGINX_RELOAD=1 bash SERVER-INSTALL.sh
   \`\`\`

   The installer also applies root-patch files such as
   plugin/social/includes/functions.php and extend/nextjs25-social.extend.php.
   These are required for Next.js social OAuth callbacks.

3. Include /etc/nginx/snippets/g5-nextjs25-security-map.conf inside the nginx
   http {} block.
4. In the nextjs.thisgun.net server {} block, include
   /etc/nginx/snippets/g5-nextjs25-theme-locations.conf before generic
   Gnuboard rewrite or PHP locations.
5. Print the site-specific nginx PHP location plan:

   \`\`\`bash
   bash SERVER-NGINX-PLAN.sh
   \`\`\`

   This writes nginx/g5-nextjs25-exact-php-locations.conf using the live
   fastcgi_pass value. Copy it with the other nginx/*.conf files and include it
   in the nextjs.thisgun.net server {} block next to
   g5-nextjs25-theme-locations.conf.
6. Check the active Gnuboard theme:

   \`\`\`bash
   sudo env WEB_ROOT=/path/to/gnuboard bash SERVER-ACTIVATE-THEME.sh
   \`\`\`

   Apply the theme only after the dry-run output looks correct:

   \`\`\`bash
   sudo env WEB_ROOT=/path/to/gnuboard APPLY=1 bash SERVER-ACTIVATE-THEME.sh
   \`\`\`

   If PHP CLI is not on PATH, set PHP_BIN=/path/to/php for
   SERVER-ACTIVATE-THEME.sh and SERVER-VERIFY.sh. If that PHP binary needs a
   different filesystem path than the shell, set PHP_WEB_ROOT as well.

7. Run nginx -t and reload nginx again after changing server config includes.
8. Verify the server-side state:

   \`\`\`bash
   sudo env WEB_ROOT=/path/to/gnuboard bash SERVER-VERIFY.sh
   \`\`\`

If theme or API files need to roll back, use the backup paths printed by
SERVER-INSTALL.sh:

\`\`\`bash
sudo env WEB_ROOT=/path/to/gnuboard \\
  ROLLBACK_THEME=/path/to/nextjs25.backup.YYYYMMDD-HHMMSS \\
  ROLLBACK_API=/path/to/api.backup.YYYYMMDD-HHMMSS \\
  bash SERVER-ROLLBACK.sh
\`\`\`

## Verify

From the repository nextjs directory:

\`\`\`powershell
npm run check:live-root-handoff
npm run check:live-deployment
npm run check:live-runtime
\`\`\`

Before the root nginx apply, check:live-root-handoff should pass with only a
passwordless sudo warning, verify that SERVER-ROOT-APPLY.sh completes in
non-root dry-run mode, and print the exact root apply commands. After the root
nginx apply, run the strict final gate:

\`\`\`powershell
npm run check:release:live:nginx
\`\`\`

The live deployment is not complete while check:release:live:nginx fails, or
while the live checks report that the root page renders theme/basic, public
root assets return HTML, long Next.js URLs do not redirect to legacy short URLs,
or API/frontend security headers are mixed.
`;

writeFileSync(join(deployRoot, 'manifest.json'), `${JSON.stringify(manifest, null, 2)}\n`);
writeFileSync(join(deployRoot, 'README-LIVE-DEPLOY.md'), readme);
const installScriptPath = join(deployRoot, 'SERVER-INSTALL.sh');
const rollbackScriptPath = join(deployRoot, 'SERVER-ROLLBACK.sh');
const activateThemeScriptPath = join(deployRoot, 'SERVER-ACTIVATE-THEME.sh');
const nginxPlanScriptPath = join(deployRoot, 'SERVER-NGINX-PLAN.sh');
const rootApplyScriptPath = join(deployRoot, 'SERVER-ROOT-APPLY.sh');
const rootCommandsScriptPath = join(deployRoot, 'SERVER-ROOT-COMMANDS.sh');
const verifyScriptPath = join(deployRoot, 'SERVER-VERIFY.sh');
writeFileSync(installScriptPath, serverInstallScript);
writeFileSync(rollbackScriptPath, serverRollbackScript);
writeFileSync(activateThemeScriptPath, serverActivateThemeScript);
writeFileSync(nginxPlanScriptPath, serverNginxPlanScript);
writeFileSync(rootApplyScriptPath, serverRootApplyScript);
writeFileSync(rootCommandsScriptPath, serverRootCommandsScript);
writeFileSync(verifyScriptPath, serverVerifyScript);
chmodSync(installScriptPath, 0o755);
chmodSync(rollbackScriptPath, 0o755);
chmodSync(activateThemeScriptPath, 0o755);
chmodSync(nginxPlanScriptPath, 0o755);
chmodSync(rootApplyScriptPath, 0o755);
chmodSync(rootCommandsScriptPath, 0o755);
chmodSync(verifyScriptPath, 0o755);
const normalizedLineEndingFileCount = normalizePackageLineEndings(deployRoot);
const checksumFileCount = writeChecksumFile();
const archiveSummary = createDeployArchive();

console.log(`[package-live-deploy] wrote ${deployRoot}`);
console.log(`[package-live-deploy] theme files: ${themeFileCount}`);
console.log(`[package-live-deploy] API files: ${apiFileCount}`);
console.log(`[package-live-deploy] nginx snippets: ${nginxSnippets.length}`);
console.log(`[package-live-deploy] normalized line endings: ${normalizedLineEndingFileCount}`);
console.log(`[package-live-deploy] checksum entries: ${checksumFileCount}`);
console.log(
  `[package-live-deploy] archive: ${relative(repoRoot, archivePath).replaceAll('\\', '/')}`,
);
console.log(`[package-live-deploy] archive sha256: ${archiveSummary.sha256}`);
console.log(
  `[package-live-deploy] package root: ${relative(repoRoot, deployRoot).replaceAll('\\', '/')}`,
);
