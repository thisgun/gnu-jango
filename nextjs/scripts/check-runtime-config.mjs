import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import vm from 'node:vm';
import * as ts from 'typescript';

const repoRoot = process.cwd();
const packageJsonPath = join(repoRoot, 'package.json');
const vercelJsonPath = join(repoRoot, 'vercel.json');
const sourcePath = join(repoRoot, 'src/lib/config.ts');
const nextConfigPath = join(repoRoot, 'next.config.ts');
const apiClientPath = join(repoRoot, 'src/lib/api.ts');
const authServerPath = join(repoRoot, 'src/lib/auth-server.ts');
const authStorePath = join(repoRoot, 'src/store/auth.ts');
const authProviderPath = join(repoRoot, 'src/components/providers/AuthProvider.tsx');
const shareButtonsPath = join(repoRoot, 'src/components/ShareButtons.tsx');
const adminLayoutPath = join(repoRoot, 'src/app/admin/layout.tsx');
const orderDataActionsPath = join(repoRoot, 'src/app/shop/order/orderDataActions.ts');
const legacyShopActionPath = join(repoRoot, 'src/app/shop/_legacy-action.ts');
const sanitizePath = join(repoRoot, 'src/lib/sanitize.ts');
const serviceWorkerPath = join(repoRoot, 'public/sw.js');
const apacheHeaderWriterPath = join(repoRoot, 'scripts/write-apache-static-headers.mjs');
const nginxSecurityMapPath = join(repoRoot, '..', 'docs/nginx/nextjs25-security-map.conf');
const checkSourceFileSizePath = join(repoRoot, 'scripts/check-source-file-size.mjs');
const packageLiveDeployPath = join(repoRoot, 'scripts/package-live-deploy.mjs');
const checkReleaseLivePath = join(repoRoot, 'scripts/check-release-live.mjs');
const checkLiveYoungcartLegacyRoutesPath = join(
  repoRoot,
  'scripts/check-live-youngcart-legacy-routes.mjs'
);
const checkLocalYoungcartLegacyRoutesPath = join(
  repoRoot,
  'scripts/check-local-youngcart-legacy-routes.mjs'
);
const djangoApiUrlsPath = join(repoRoot, '..', 'gnu_jango/api/v1_urls.py');
const djangoAuthPath = join(repoRoot, '..', 'gnu_jango/api/v1_auth.py');
const djangoAuthSessionsPath = join(repoRoot, '..', 'gnu_jango/api/auth_sessions.py');
const djangoBoardPath = join(repoRoot, '..', 'gnu_jango/api/v1_board.py');
const djangoCommunityPath = join(repoRoot, '..', 'gnu_jango/api/v1_community.py');
const djangoCommunityMemosPath = join(repoRoot, '..', 'gnu_jango/api/community_memos.py');
const djangoViewsPath = join(repoRoot, '..', 'gnu_jango/api/v1_views.py');
const djangoResponsePath = join(repoRoot, '..', 'gnu_jango/api/response.py');
const djangoSessionAuthPath = join(repoRoot, '..', 'gnu_jango/api/authentication.py');
const djangoBaseSettingsPath = join(repoRoot, '..', 'example/settings/base.py');
const djangoDevelopmentSettingsPath = join(repoRoot, '..', 'example/settings/development.py');

function fail(message) {
  console.error(`[check-runtime-config] ${message}`);
  process.exit(1);
}

function loadConfigModule({ env = {}, windowValue } = {}) {
  const source = readFileSync(sourcePath, 'utf8');
  const output = ts.transpileModule(source, {
    compilerOptions: {
      esModuleInterop: true,
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
    fileName: sourcePath,
    reportDiagnostics: true,
  });

  const diagnostics = output.diagnostics ?? [];
  if (diagnostics.length > 0) {
    fail(`failed to transpile config.ts: ${diagnostics.map((item) => item.messageText).join('; ')}`);
  }

  const module = { exports: {} };
  const sandbox = {
    module,
    exports: module.exports,
    process: {
      env: {
        NODE_ENV: 'production',
        ...env,
      },
    },
    URL,
  };

  if (windowValue) {
    sandbox.window = windowValue;
  }

  vm.runInNewContext(output.outputText, sandbox, {
    filename: sourcePath,
  });

  return module.exports;
}

function expectEqual(name, actual, expected) {
  if (actual !== expected) {
    fail(`${name} produced ${actual}, expected ${expected}`);
  }
}

const vercelConfig = loadConfigModule({
  env: {
    NEXT_PUBLIC_API_URL: 'https://thisgun4.gnuboard.net/gnuboard5/api/v1',
    NEXT_PUBLIC_G5_URL: 'https://thisgun4.gnuboard.net/gnuboard5',
    NEXT_PUBLIC_APP_URL: 'https://gnuboard5-nextjs25-theme.vercel.app',
  },
});

expectEqual(
  'Vercel g5BasePathForRuntime',
  vercelConfig.g5BasePathForRuntime(),
  ''
);
expectEqual(
  'Vercel g5PathForRuntime(/free/write)',
  vercelConfig.g5PathForRuntime('/free/write'),
  '/free/write'
);
expectEqual(
  'Vercel apiUrl(/captcha)',
  vercelConfig.apiUrl('/captcha?t=123'),
  'https://thisgun4.gnuboard.net/gnuboard5/api/v1/captcha?t=123'
);
expectEqual(
  'Vercel apiUrl(/captcha/audio)',
  vercelConfig.apiUrl('/captcha/audio?t=123'),
  'https://thisgun4.gnuboard.net/gnuboard5/api/v1/captcha/audio?t=123'
);

const vercelBrowserConfig = loadConfigModule({
  env: {
    NEXT_PUBLIC_API_URL: 'https://thisgun4.gnuboard.net/gnuboard5/api/v1',
    NEXT_PUBLIC_G5_URL: 'https://thisgun4.gnuboard.net/gnuboard5',
    NEXT_PUBLIC_APP_URL: 'https://gnuboard5-nextjs25-theme.vercel.app',
  },
  windowValue: {
    location: {
      origin: 'https://gnuboard5-nextjs25-theme.vercel.app',
      pathname: '/gallery/%EC%8F%98%EB%A6%AC%EC%97%BC',
    },
    __G5_NEXTJS25_CONFIG__: {
      apiBaseUrl: 'https://thisgun4.gnuboard.net/gnuboard5/api/v1',
      g5BaseUrl: 'https://thisgun4.gnuboard.net/gnuboard5',
      appBaseUrl: 'https://gnuboard5-nextjs25-theme.vercel.app',
    },
  },
});

expectEqual(
  'Vercel browser g5BasePathForRuntime',
  vercelBrowserConfig.g5BasePathForRuntime(),
  ''
);
expectEqual(
  'Vercel browser g5PathForRuntime(/gallery)',
  vercelBrowserConfig.g5PathForRuntime('/gallery'),
  '/gallery'
);

const themeConfig = loadConfigModule({
  env: {
    NEXT_PUBLIC_API_URL: 'https://thisgun4.gnuboard.net/gnuboard5/api/v1',
    NEXT_PUBLIC_G5_URL: 'https://thisgun4.gnuboard.net/gnuboard5',
    NEXT_PUBLIC_APP_URL: 'https://gnuboard5-nextjs25-theme.vercel.app',
  },
  windowValue: {
    location: {
      origin: 'https://thisgun4.gnuboard.net',
      pathname: '/gnuboard5/free',
    },
    __G5_NEXTJS25_CONFIG__: {
      apiBaseUrl: 'https://thisgun4.gnuboard.net/gnuboard5/api/v1',
      g5BaseUrl: 'https://thisgun4.gnuboard.net/gnuboard5',
      appBaseUrl: 'https://thisgun4.gnuboard.net/gnuboard5',
    },
  },
});

expectEqual(
  'theme g5BasePathForRuntime',
  themeConfig.g5BasePathForRuntime(),
  '/gnuboard5'
);
expectEqual(
  'theme g5PathForRuntime(/free/write)',
  themeConfig.g5PathForRuntime('/free/write'),
  '/gnuboard5/free/write'
);
expectEqual(
  'theme apiUrl(/captcha)',
  themeConfig.apiUrl('/captcha?t=123'),
  'https://thisgun4.gnuboard.net/gnuboard5/api/v1/captcha?t=123'
);
expectEqual(
  'theme apiUrl(/captcha/audio)',
  themeConfig.apiUrl('/captcha/audio?t=123'),
  'https://thisgun4.gnuboard.net/gnuboard5/api/v1/captcha/audio?t=123'
);

const packageJsonSource = readFileSync(packageJsonPath, 'utf8');
const vercelJsonSource = readFileSync(vercelJsonPath, 'utf8');
const nextConfigSource = readFileSync(nextConfigPath, 'utf8');
const apiClientSource = readFileSync(apiClientPath, 'utf8');
const authServerSource = readFileSync(authServerPath, 'utf8');
const authStoreSource = readFileSync(authStorePath, 'utf8');
const authProviderSource = readFileSync(authProviderPath, 'utf8');
const shareButtonsSource = readFileSync(shareButtonsPath, 'utf8');
const adminLayoutSource = readFileSync(adminLayoutPath, 'utf8');
const orderDataActionsSource = readFileSync(orderDataActionsPath, 'utf8');
const legacyShopActionSource = readFileSync(legacyShopActionPath, 'utf8');
const sanitizeSource = readFileSync(sanitizePath, 'utf8');
const serviceWorkerSource = readFileSync(serviceWorkerPath, 'utf8');
const apacheHeaderWriterSource = readFileSync(apacheHeaderWriterPath, 'utf8');
const nginxSecurityMapSource = readFileSync(nginxSecurityMapPath, 'utf8');
const checkSourceFileSizeSource = readFileSync(checkSourceFileSizePath, 'utf8');
const packageLiveDeploySource = readFileSync(packageLiveDeployPath, 'utf8');
const checkReleaseLiveSource = readFileSync(checkReleaseLivePath, 'utf8');
const checkLiveYoungcartLegacyRoutesSource = readFileSync(checkLiveYoungcartLegacyRoutesPath, 'utf8');
const checkLocalYoungcartLegacyRoutesSource = readFileSync(
  checkLocalYoungcartLegacyRoutesPath,
  'utf8'
);
const djangoApiUrlsSource = readFileSync(djangoApiUrlsPath, 'utf8');
const djangoAuthSource = readFileSync(djangoAuthPath, 'utf8');
const djangoAuthSessionsSource = readFileSync(djangoAuthSessionsPath, 'utf8');
const djangoBoardSource = readFileSync(djangoBoardPath, 'utf8');
const djangoCommunitySource =
  readFileSync(djangoCommunityPath, 'utf8') +
  readFileSync(djangoCommunityMemosPath, 'utf8');
const djangoViewsSource = readFileSync(djangoViewsPath, 'utf8');
const djangoResponseSource = readFileSync(djangoResponsePath, 'utf8');
const djangoSessionAuthSource = readFileSync(djangoSessionAuthPath, 'utf8');
const djangoBaseSettingsSource = readFileSync(djangoBaseSettingsPath, 'utf8');
const djangoDevelopmentSettingsSource = readFileSync(djangoDevelopmentSettingsPath, 'utf8');

for (const [label, source] of [
  ['next.config.ts', nextConfigSource],
  ['write-apache-static-headers.mjs', apacheHeaderWriterSource],
  ['vercel.json', vercelJsonSource],
]) {
  if (source.includes("script-src 'self' 'unsafe-inline' 'unsafe-eval'")) {
    fail(`${label} must not enable unsafe-eval unconditionally in the production CSP`);
  }
  if (label === 'vercel.json' && source.includes("'unsafe-eval'")) {
    fail('vercel.json must not ship unsafe-eval in the static-export CSP');
  }
  if (label !== 'vercel.json' && !source.includes('NEXT_CSP_ALLOW_UNSAFE_EVAL')) {
    fail(`${label} must make unsafe-eval an explicit environment opt-in`);
  }
}

if (!nextConfigSource.includes('const pgScriptSources = pgFrameSources')) {
  fail('next.config.ts must include PG SDK hosts in script-src, not only frame-src');
}

if (!apacheHeaderWriterSource.includes('const PG_SCRIPT_SOURCES = PG_FRAME_SOURCES')) {
  fail('write-apache-static-headers.mjs must include PG SDK hosts in script-src, not only frame-src');
}

for (const [label, source] of [
  ['vercel.json', vercelJsonSource],
  ['docs/nginx/nextjs25-security-map.conf', nginxSecurityMapSource],
]) {
  const scriptSrc = source.match(/script-src [^;"]+/)?.[0] ?? '';
  for (const token of [
    'https://testpay.kcp.co.kr',
    'https://*.kcp.co.kr',
    'https://stdpay.inicis.com',
    'https://*.inicis.com',
    'https://web.nicepay.co.kr',
    'https://*.nicepay.co.kr',
  ]) {
    if (!scriptSrc.includes(token)) {
      fail(`${label} script-src is missing PG SDK host ${token}`);
    }
  }
  if (/(^|\s)https:(\s|$)/.test(scriptSrc)) {
    fail(`${label} script-src must not use the https: wildcard for PG SDKs`);
  }
  if (scriptSrc.includes("'unsafe-eval'")) {
    fail(`${label} script-src must not enable unsafe-eval by default`);
  }
}

for (const token of [
  'function isCacheableStaticAsset',
  "url.pathname.startsWith('/_next/static/')",
  'CACHEABLE_PUBLIC_ASSET_RE',
  "if (!isCacheableStaticAsset(url)) return;",
  "response.type === 'basic'",
]) {
  if (!serviceWorkerSource.includes(token)) {
    fail(`public/sw.js is missing restricted static cache token ${token}`);
  }
}

for (const token of [
  'const userAllowedTags',
  'const userAllowedAttributes',
  'export function sanitizeContentHtml',
  'export function sanitizeCommerceHtml',
  'export function sanitizeUserHtml',
  'export function sanitizeInlineHtml',
]) {
  if (!sanitizeSource.includes(token)) {
    fail(`src/lib/sanitize.ts is missing trust-level sanitizer token ${token}`);
  }
}

for (const token of [
  'const API_DIR = join(ROOT, "..", "api")',
  'const MAX_PHP_LINES',
  'const WARN_PHP_LINES',
  'const PHP_EXTENSIONS',
]) {
  if (!checkSourceFileSizeSource.includes(token)) {
    fail(`check-source-file-size.mjs is missing PHP size guard token ${token}`);
  }
}

if (!nextConfigSource.includes("NEXT_IMAGE_ALLOW_LOCAL_HOSTS === '1'")) {
  fail('next.config.ts must keep localhost/127 image optimization behind an explicit opt-in');
}

if (!apiClientSource.includes('body: body !== undefined ? JSON.stringify(body) : undefined')) {
  fail('api.ts must preserve falsy JSON request bodies such as false, 0, and empty strings');
}

if (!apiClientSource.includes('shouldPersistClientAuthCookies')) {
  fail('api.ts must avoid JS-readable auth cookie persistence for same-origin API deployments');
}

if (apiClientSource.includes('setCookie(TOKEN_COOKIE, legacy)')) {
  fail('api.ts must not migrate legacy localStorage auth tokens back into JS-readable cookies');
}

if (apiClientSource.includes('if (!this.refreshToken) return null;')) {
  fail('api.ts refreshAccessToken must support HttpOnly refresh cookies without a JS-readable refresh token');
}

if (!apiClientSource.includes("this.refreshToken || (this.canAttemptCookieRefresh() && this.hasAuthHint())")) {
  fail('api.ts must retry 401 responses when HttpOnly cookie refresh is possible');
}

for (const token of [
  "const AUTH_HINT_COOKIE = 'g5_auth_hint'",
  'hasAuthHint(): boolean',
]) {
  if (!apiClientSource.includes(token)) {
    fail(`api.ts is missing auth hint support token ${token}`);
  }
}

if (!authServerSource.includes("cache: 'no-store'")) {
  fail('auth-server.ts must not cache per-user /auth/me responses');
}

for (const token of [
  'path("status", v1_views.status_view',
  'path("auth/login", v1_auth.login_view',
  'path("auth/register", v1_auth.register_view',
  'path("auth/me", v1_auth.me_view',
  'path("auth/refresh", v1_auth.refresh_view',
  'path("auth/logout", v1_auth.logout_view',
  'path("settings", v1_community.settings_view',
  'path("menus", v1_views.menus_view',
  'path("boards", v1_board.board_list_view',
  'path("boards/<str:bo_table>/posts", v1_board.board_posts_view',
  'path("boards/<str:bo_table>/<int:wr_id>/files", v1_board.post_files_view',
  'path("posts/<str:bo_table>/<int:wr_id>", v1_board.post_detail_view',
  'path("comments/<str:bo_table>/<int:item_id>", v1_board.comment_view',
  'path("scraps", v1_community.scraps_view',
  'path("memos", v1_community.memos_view',
  'path("upload", v1_board.editor_upload_view',
]) {
  if (!djangoApiUrlsSource.includes(token)) {
    fail(`Django v1 API urls are missing route token ${token}`);
  }
}

for (const token of [
  'response.set_cookie("g5_token", token, httponly=True',
  '"g5_refresh"',
  '"g5_auth_hint"',
  'httponly=False',
  'request.COOKIES.get("g5_token")',
  'request.COOKIES.get("g5_refresh")',
  'JWTAuthentication()',
  'issue_refresh_token(user, request, login_at=',
  '_clear_auth_cookies(response)',
]) {
  if (!djangoAuthSource.includes(token)) {
    fail(`Django auth API is missing HttpOnly cookie/token support token ${token}`);
  }
}

for (const token of [
  'def issue_refresh_token(user, request=None, login_at=None):',
  'refresh["tv"] = token_version_for_user(user)',
  'refresh["sid"] = refresh["jti"]',
]) {
  if (!djangoAuthSessionsSource.includes(token)) {
    fail('Django auth session helper is missing token-version/session support token ' + token);
  }
}

for (const token of [
  '@authentication_classes([JWTAuthentication, BasicAuthentication])',
  'def _can_manage_post(user, post):',
  'def _is_board_admin(user, board):',
  'board.bo_write_level',
  'board.bo_comment_level',
  'board.bo_upload_level',
  'board.bo_upload_size',
  'board.bo_upload_count',
  'EDITOR_UPLOAD_EXTENSIONS',
  'default_storage.save(os.path.join("uploads", "editor", unique_name), uploaded_file)',
  'MAX_EDITOR_UPLOAD_SIZE = 10 * 1024 * 1024',
]) {
  if (!djangoBoardSource.includes(token)) {
    fail(`Django board API is missing Gnuboard-grade permission/upload token ${token}`);
  }
}

for (const token of [
  'def settings_view(request):',
  'def recent_view(request):',
  'def search_view(request):',
  'def member_me_view(request):',
  'def scraps_view(request):',
  'Post_scrap.objects.get_or_create',
  'def memos_view(request):',
  'User_Memo.objects.create',
  'def notifications_view(request):',
  'def password_reset_view(request):',
]) {
  if (!djangoCommunitySource.includes(token)) {
    fail(`Django community API is missing route/feature token ${token}`);
  }
}

for (const token of [
  '"status": "ok"',
  '"auth": True',
  '"uploads": True',
  '"theme": "nextjs_default"',
]) {
  if (!djangoViewsSource.includes(token)) {
    fail(`Django status/config API is missing capability token ${token}`);
  }
}

for (const token of [
  '"DEFAULT_AUTHENTICATION_CLASSES"',
  '"gnu_jango.api.authentication.SessionJWTAuthentication"',
  '"gnu_jango.api.authentication.CsrfExemptSessionAuthentication"',
  'CORS_ALLOW_CREDENTIALS',
  'CORS_ALLOW_ALL_ORIGINS',
]) {
  if (!djangoBaseSettingsSource.includes(token) && !djangoDevelopmentSettingsSource.includes(token)) {
    fail(`Django settings are missing API runtime security token ${token}`);
  }
}

for (const token of ['class SessionJWTAuthentication(JWTAuthentication):', 'token_version != current_version']) {
  if (!djangoSessionAuthSource.includes(token)) {
    fail('Django SessionJWTAuthentication is missing token-revocation guard ' + token);
  }
}

for (const token of [
  'class CsrfExemptSessionAuthentication(SessionAuthentication):',
  'def enforce_csrf(self, request):',
]) {
  if (!djangoSessionAuthSource.includes(token)) {
    fail(`Django API session authentication is missing security contract token ${token}`);
  }
}

for (const token of [
  '"success": ok',
  '"ok": ok',
  '"data": data',
  '"errors": errors if errors is not None else {}',
  '"errors": details if isinstance(details, dict) else {code: message}',
]) {
  if (!djangoResponseSource.includes(token)) {
    fail(`Django API response envelope is missing token ${token}`);
  }
}

if (!packageJsonSource.includes('"check:live-social-redirects": "node scripts/check-live-social-redirects.mjs"')) {
  fail('package.json must expose the live social redirect smoke check');
}

if (!checkReleaseLiveSource.includes("'check:live-social-redirects'")) {
  fail('check-release-live.mjs must include the live social redirect smoke check');
}

if (
  !packageJsonSource.includes(
    '"check:live-youngcart-legacy-routes": "node scripts/check-live-youngcart-legacy-routes.mjs"'
  )
) {
  fail('package.json must route the live YoungCart legacy smoke check through its live wrapper');
}

for (const token of [
  "process.env.RUNTIME_CHECK_TARGET ||= 'live'",
  "process.env.RUNTIME_CHECK_LABEL ||= 'check-live-youngcart-legacy-routes'",
  "await import('./check-local-youngcart-legacy-routes.mjs')",
]) {
  if (!checkLiveYoungcartLegacyRoutesSource.includes(token)) {
    fail(`check-live-youngcart-legacy-routes.mjs is missing live wrapper token ${token}`);
  }
}

for (const token of [
  'const runtimeTarget =',
  "runtimeTarget === 'live'",
  'LIVE_SMOKE_YOUNGCART_LEGACY_REDIRECTS',
  'LIVE_SMOKE_YOUNGCART_ORIGINAL_PHP_PASSTHROUGHS',
]) {
  if (!checkLocalYoungcartLegacyRoutesSource.includes(token)) {
    fail(`check-local-youngcart-legacy-routes.mjs is missing live target token ${token}`);
  }
}

for (const token of [
  "const excludedApiPackagePatterns = ['.env', '.env.*']",
  'function shouldCopyApiEntry',
  "part === '.env' || part.startsWith('.env.')",
  'cpSync(apiSource, apiTarget, { recursive: true, filter: shouldCopyApiEntry })',
]) {
  if (!packageLiveDeploySource.includes(token)) {
    fail(`package-live-deploy.mjs is missing API environment file exclusion token ${token}`);
  }
}

if (authStoreSource.includes('let token = api.getToken()')) {
  fail('auth store initialization must not require a JS-readable access token before /auth/me');
}

if (!authStoreSource.includes("api.post('/auth/logout', refresh ? { refresh_token: refresh } : {})")) {
  fail('auth store logout must call /auth/logout even when refresh is only present as an HttpOnly cookie');
}

if (!authProviderSource.includes('api.hasAuthHint()')) {
  fail('AuthProvider must skip guest-only /auth/me initialization when no auth hint cookie exists');
}

const safeSharePopupCount = shareButtonsSource.match(/width=600,height=400,noopener,noreferrer/g)?.length ?? 0;
if (safeSharePopupCount < 3) {
  fail('ShareButtons external popups must use noopener,noreferrer');
}

if (adminLayoutSource.includes('const token = api.getToken()')) {
  fail('admin layout must not redirect before trying /auth/me with HttpOnly cookies');
}

if (!adminLayoutSource.includes('api.hasAuthHint()')) {
  fail('admin layout must use the non-sensitive auth hint before probing /auth/me on guest pages');
}

if (orderDataActionsSource.includes('api.getToken()')) {
  fail('order initial data loading must not hide member data behind JS-readable token checks');
}

if (!orderDataActionsSource.includes('const shouldLoadMember = hasCartItems && api.hasAuthHint();')) {
  fail('order initial data loading must avoid guest-only /auth/me calls while preserving HttpOnly auth sessions');
}

for (const token of [
  'function legacyRedirectPath',
  'function legacyRedirectUrl',
  'function legacyFallbackPath',
  'target.origin !== request.nextUrl.origin',
  'fallback.origin === request.nextUrl.origin',
  'const redirect = legacyRedirectPath(request, envelope.data?.redirect || fallbackRedirect, fallbackRedirect);',
]) {
  if (!legacyShopActionSource.includes(token)) {
    fail(`shop legacy action bridge is missing same-origin redirect guard token ${token}`);
  }
}

for (const token of ["credentials: 'include'", "credentials: options?.credentials ?? 'include'"]) {
  if (!apiClientSource.includes(token)) {
    fail(`API client must keep cookie-backed Django sessions available with ${token}`);
  }
}

for (const token of [
  'function sameOriginNotificationPath',
  'url.origin !== self.location.origin',
  'sameOriginNotificationPath(event.notification.data?.url)',
]) {
  if (!serviceWorkerSource.includes(token)) {
    fail(`public/sw.js is missing notification URL hardening token ${token}`);
  }
}

console.log('[check-runtime-config] runtime base path guards passed');
