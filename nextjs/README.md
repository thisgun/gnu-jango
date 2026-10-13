# Gnuboard5 Next.js Frontend

This app is the Next.js frontend used by the Gnuboard5 theme export.

The source directory was renamed from `nextjs25/` to `nextjs/` on 2026-10-07.
`npm run build:theme` exports the Django theme to
`gnu_jango/templates/theme/nextjs_default/` and its assets to
`gnu_jango/templates/theme_static/nextjs_default/`.
See the [implementation plan](../docs/01-plan/features/nextjs-default-theme.plan.md)
and [PRD](../docs/01-plan/features/nextjs-default-theme.prd.md). The
[deployment and recovery guide](../docs/04-deploy/nextjs-default-theme.md)
covers Django static export and independent Node server modes.

## Local Development

```powershell
$env:G5_NEXT_RUNTIME = 'server'
npm install
npm run dev
```

The default Next.js dev URL is `http://localhost:3000`. Use server mode in
development to exercise rewrites and dynamic routes. `build:theme` explicitly
uses static export mode for the Django theme, even if the shell still has
`G5_NEXT_RUNTIME=server` set. The static build runs in a temporary copy of the
Next.js project because Next 15 uses `.next` internally during export. The
completed export is copied to `out`, leaving the `.next` directory used by an
active Node server untouched. Service worker and static-header post-build steps
run against the isolated export before it is published.

## Production Node Server

```powershell
npm run build:server
npm run start:server
```

These commands set `G5_NEXT_RUNTIME=server` and use `.next-server-build` for
both build and start, leaving the active `.next` directory untouched. Set
`G5_NEXT_DIST_DIR` before both commands only when using a custom build folder.

## Environment Files

Use `.env.example` as the shared reference.

- `NEXT_PUBLIC_API_URL`: optional browser API URL for static export/direct API mode. Leave **unset** for the recommended Node proxy mode so the browser uses the relative `/api/v1` path.
- `G5_NEXT_RUNTIME`: set to `server` for the Next.js Node server and same-origin API proxy. The Django theme export always builds in static mode independently.
- `G5_API_INTERNAL_URL`: server-only API URL that backs the `/api/v1` and `/api/g5` Next.js rewrites and direct SSR/RSC fetches.
- `NEXT_PUBLIC_G5_URL`: original Gnuboard site URL for legacy links and assets.
- `NEXT_PUBLIC_APP_URL`: public app URL used for metadata, RSS, and canonical links.
- `NEXT_PUBLIC_GALLERY_BOARDS`: comma-separated board IDs rendered with gallery UI.

Local dev usually uses `nextjs/.env.local`:

```env
NEXT_PUBLIC_API_URL=http://127.0.0.9/api/v1
G5_API_INTERNAL_URL=http://127.0.0.9/api/v1
NEXT_PUBLIC_G5_URL=http://127.0.0.9
NEXT_PUBLIC_APP_URL=http://localhost:3000
NEXT_PUBLIC_GALLERY_BOARDS=n_gallery,gallery
```

The tracked `.env.production.example` file documents the required production
variables. Copy it to an ignored `.env.production.local` file for a local
production build, or set the values in the Vercel project environment:

```env
G5_NEXT_RUNTIME=server
G5_API_INTERNAL_URL=https://your-django-api.example.com/api/v1
NEXT_PUBLIC_G5_URL=https://your-django-api.example.com
NEXT_PUBLIC_APP_URL=https://your-vercel-app.example.com
NEXT_PUBLIC_AUTH_MODE=g5-jwt
NEXT_PUBLIC_GALLERY_BOARDS=n_gallery,gallery
```

For local static theme builds, copy `nextjs/.env.production.local.example` to
`nextjs/.env.production.local`. That file is ignored by git and is loaded by
`npm run build:theme` without exposing deployment values in the repository.

```powershell
Copy-Item .env.production.local.example .env.production.local
npm run build:theme
npm run check:local-runtime
```

Expected local runtime:

- frontend: `http://127.0.0.20`
- API: `http://127.0.0.9/api/v1`
- live: `https://<your-domain>` (set `NEXT_PUBLIC_APP_URL`)

## Cross-Domain Authentication (Vercel ↔ separate API server)

When the front-end runs on one domain (e.g. Vercel) and the Django API runs on
another, keeping a user logged in needs care, because the auth cookies are
first-party to whatever origin the **browser** actually talks to.

### How auth works
- API requests authenticate with a JWT `Authorization: Bearer` header
  (`rest_framework_simplejwt`); the access/refresh tokens are also returned in
  the login response body.
- Session persistence across reloads relies on the HttpOnly `g5_refresh` cookie
  sent to `POST /api/v1/auth/refresh` (`credentials: include`). That cookie is
  `SameSite=Lax`, so it is **not** sent on cross-site requests.
- The Django admin (`/admin/`) is a *separate* Django session that lives only on
  the API domain. It is not shared with the front-end; you log into it directly
  at `https://<api-domain>/admin/`.
- Browser requests authenticated by the HttpOnly `g5_token` cookie use Django's
  CSRF check. The frontend obtains a masked token from `/auth/csrf` and sends it
  in `X-CSRFToken` for mutations. Bearer-token requests remain usable alongside
  a Django admin session in the same browser; admin session requests continue to
  use DRF's built-in `SessionAuthentication` CSRF enforcement.

### Recommended: Next.js proxy (BFF)
The browser only ever talks to the front-end origin; Next.js forwards
`/api/v1/*` to the API host server-side. The auth cookies therefore stay
first-party to the front-end and the session works across domains with **no
CORS and no `SameSite=None`**.

1. Run the front-end as a Node server (not static export): `G5_NEXT_RUNTIME=server`.
2. Point the proxy/SSR at the API: `G5_API_INTERNAL_URL=https://<api-domain>/api/v1`.
   `next.config.ts` rewrites `/api/v1/:path*` → `G5_API_INTERNAL_URL`.
3. Leave `NEXT_PUBLIC_API_URL` **unset** so the browser bundle falls back to the
   relative `/api/v1` (proxied) path; SSR/RSC still reach the API directly via
   `G5_API_INTERNAL_URL`.
4. On the API server, add the API host to Django `ALLOWED_HOSTS`. CORS is not
   needed — the browser is same-origin with the front-end and the proxy hop is
   server-to-server.

`check:vercel-env` accepts an unset `NEXT_PUBLIC_API_URL` only when
`G5_NEXT_RUNTIME=server`; `check:release:vercel` then builds the configured
runtime instead of forcing a static export. Static export deployments must set
`NEXT_PUBLIC_API_URL` because they have no Next.js server to proxy browser API
requests. In proxy mode the checker also requires `NEXT_PUBLIC_API_URL` to stay
unset so browser API calls use the same-origin proxy.

### Alternative: direct cross-origin
The browser calls the API host directly: set both `NEXT_PUBLIC_API_URL` and
`G5_API_INTERNAL_URL` to
`https://<api-domain>/api/v1`. Then on the API:

- `CORS_ALLOWED_ORIGINS=https://<vercel-app>` and `CORS_ALLOW_CREDENTIALS=True`.

Session persistence then requires the HttpOnly refresh cookie to cross sites,
which means the auth cookies must be `SameSite=None; Secure` (currently
hardcoded `Lax` in `gnu_jango/api/v1_auth.py:_set_auth_cookies`). Because
Safari/Chrome are restricting third-party cookies, the proxy approach above is
the more robust choice.

## Static Theme Export

```powershell
npm run build:theme
npm run package:theme
```

This runs `next build`, exports to `nextjs/out`, and syncs the result into
`gnu_jango/templates/theme/nextjs_default/` and
`gnu_jango/templates/theme_static/nextjs_default/`. The Django renderer injects
the request's API and site URLs at runtime; `_next/static` is served from the
matching `theme_static` directory.

`package:theme` checks that the export is synchronized, then writes an upload
directory and `nextjs/.deploy/nextjs-default-theme.tar.gz`. The archive includes
both Django theme directories, `DEPLOYMENT.md`, a file manifest, and SHA-256
checksums. Its sibling `.sha256` file verifies the archive itself.

`npm run package:live` and `npm run deploy:live:ssh` are for the separate legacy
PHP deployment package under `theme/nextjs25`; they do not deploy this Django
theme export.

## Checks

```powershell
npm run typecheck
npm run check:local-runtime
npm run check:local-browser
npm run check:vercel-env:template
```

`check:local-runtime` verifies that `http://127.0.0.20/` injects
`http://127.0.0.9/api/v1` and that the API sends the expected CORS header for
the local frontend origin.

`check:local-browser` opens the local static theme with Playwright and checks
the main public, board, shop, cart, and guest-protected flows. Site
administration is the Django admin at `/admin/`, so admin pages are not part of
this smoke. To include
authenticated mypage/order/wishlist checks against a disposable local member,
seed it and run the auth gate in one step:

```powershell
npm run check:local-browser:auth:seeded
```

To use your own local test account instead, provide credentials without
committing them:

```powershell
$env:LOCAL_SMOKE_LOGIN_ID="testuser"
$env:LOCAL_SMOKE_LOGIN_PASSWORD="testpassword"
npm run check:local-browser:auth
```

To run the same authenticated coverage at a mobile viewport, run:

```powershell
npm run check:local-browser:all:seeded:mobile
```

## Vercel Deployment Gate

Before deploying to Vercel, configure the project environment variables with
real HTTPS URLs, then run:

```powershell
npm run check:vercel-env
npm run check:release:vercel
```

`check:vercel-env` fails if required URLs are missing, still point at
`example.com`/localhost placeholders, do not use HTTPS, or do not point API
variables at `/api/v1`. For the Node proxy profile, leave `NEXT_PUBLIC_API_URL`
unset and set `G5_NEXT_RUNTIME=server`; static export requires the public API
URL. The gate also checks that `vercel.json` carries the required security
headers.

The `:auth` and `:all` variants fail when the required credentials are missing,
so they are safer gates before release.

## Release Gates

Run the local release gate before pushing a theme build:

```powershell
npm run check:release:local
```

This verifies typecheck, static theme sync, local runtime settings, static and
server-runtime YoungCart legacy routes, legacy short URLs,
authenticated browser smoke paths on desktop and mobile, accessibility
basics, mobile page-level horizontal overflow, and the local API origin. When
frontend source changed and you need to rebuild the static theme output first,
run:

```powershell
npm run check:release:local:build
```

Before a wider release, run the full gate. It also executes the local write
action smokes for auth, boards, shop, order, member, memo, coupon, poll, point,
and post reactions:

```powershell
npm run check:release:local:full
```

The release gate retries a failed sub-check once by default to absorb local
Apache/MySQL hiccups. Set `LOCAL_RELEASE_CHECK_RETRIES=0` when you want strict
single-shot behavior.

For targeted static-only diagnosis, pass `--skip-server-routes` to
`scripts/check-release-local.mjs`. Do not use that shortcut for release
approval.

After deployment, verify the live origin:

```powershell
npm run check:release:live
```

For targeted checks, run:

```powershell
npm run check:live-root-handoff
npm run check:live-nginx-plan
npm run check:live-deployment
npm run check:live-runtime
npm run check:live-browser
npm run check:live-browser:mobile
```

`check:live-deployment` is the faster posture check: it reports whether the
Next.js 25 theme is active, root public assets are routed through the bridge,
long URLs redirect to legacy short URLs, and frontend/API security headers are
split correctly.

`check:live-root-handoff` verifies that the live deploy archive, uploaded
package, package checksums, SSH access, and installed theme files are ready for
the root nginx step. It also runs `SERVER-ROOT-APPLY.sh` in non-root dry-run
mode to catch helper errors before handoff. It exits successfully when the only
remaining issue is that sudo/root must still run the same helper in apply mode.

`check:release:live` runs the live nginx include plan in advisory mode, then
the live deployment/runtime/browser checks. While root nginx work is still
pending, it fails once visible routing checks reach legacy YoungCart PHP
canonical redirects. For a full diagnostic sweep that keeps running after the
first failure, run `node scripts/check-release-live.mjs --continue-on-failure`
or add `--skip-browser` for a faster runtime-only report. Use
`npm run check:release:live:runtime` for the same gate without Playwright browser smoke, or
`npm run check:release:live:desktop` when mobile smoke can be skipped. After
`SERVER-ROOT-APPLY.sh` has been applied with root/sudo access, run
`npm run check:release:live:nginx`; that stricter gate requires the nginx
include plan to report every item as `present`.

The automated live gates do not replace real provider-console checks. Before
calling a production release complete, run one browser login through every
enabled social provider on the live domain and one approval/cancel/mobile return
through every enabled PG merchant test account. Those flows require provider
dashboards and merchant credentials, so they are tracked as external release
gates rather than normal CI scripts.

If this fails on live security headers, apply the frontend and API nginx
snippets in `docs/NGINX-NEXTJS25-SECURITY.md`. The generated
`SERVER-NGINX-PLAN.sh` helper creates a site-specific exact PHP-FPM snippet for
`/theme/nextjs25/route.php` and `/api/index.php` so frontend and API headers do
not inherit or duplicate each other. The deploy package also includes
`SERVER-ROOT-APPLY.sh`, which can preview or apply the full nginx include,
theme install, theme activation, and verification flow with config backups.
For the live host, `SERVER-ROOT-COMMANDS.sh` wraps that helper with the staged
defaults so the root operator can run `dry-run` first and then `apply`.

To assemble the exact theme and nginx files for live handoff, run:

```powershell
npm run package:live
```

This writes an ignored package under `nextjs/.deploy/nextjs25-live` and a
transfer archive at `nextjs/.deploy/nextjs25-live.tar.gz`. The package contains
`upload/theme/nextjs25`, deploy-ready nginx snippet names, a manifest,
`CHECKSUMS.sha256`, archive checksum metadata, and a live install checklist. It
also includes server-side install/rollback/verify helpers for placing theme
files, checking package integrity, printing the site-specific nginx PHP-FPM
plan, checking nginx snippets/includes, inserting nginx includes with backups,
and dry-running or applying the active Gnuboard theme change. The package also
includes a `SERVER-ROOT-COMMANDS.sh` wrapper for the final root handoff. The
theme helper supports `PHP_BIN=/path/to/php` when PHP CLI is not on `PATH`, and
`PHP_WEB_ROOT` when PHP needs a different filesystem path than the shell. The
command fails when the static app output or the Next.js 25 PHP bridge is
incomplete.

Before handing the package to a root-capable operator, run:

```powershell
npm run check:live-root-handoff
```

When SSH access is available, the same archive can be uploaded and executed
with a safe dry-run first:

```powershell
$env:LIVE_DEPLOY_HOST="your-domain.example"
$env:LIVE_DEPLOY_USER="deploy"
$env:LIVE_DEPLOY_WEB_ROOT="/path/to/gnuboard"
$env:LIVE_DEPLOY_SUDO="none"
npm run deploy:live:ssh
```

Use `LIVE_DEPLOY_SUDO=none` for dry-runs with an SSH account that cannot run
passwordless sudo. Apply mode may still need sudo or equivalent permissions for
nginx snippet installation and reload. The SSH deploy dry-run uses
`SERVER-ROOT-APPLY.sh` by default, so it also shows the nginx include edits that
would be made before apply. Set `LIVE_DEPLOY_ROOT_APPLY=0` to use the older
split helper flow.

When the SSH user can write the Gnuboard web root but cannot edit nginx, use
`LIVE_DEPLOY_THEME_ONLY=1`. In this mode apply installs only
`theme/nextjs25`, skips nginx snippet install/test/reload, and does not activate
the theme unless `LIVE_DEPLOY_ACTIVATE_THEME=1` is also set. Full live checks
still require the root-side nginx include step.

Set `LIVE_DEPLOY_APPLY=1` only after the dry-run output is correct. In apply
mode the SSH deploy checks non-interactive root/sudo access before packaging or
uploading, then reruns the root helper in dry-run mode before applying. It then
generates the exact PHP-FPM snippet, installs theme and nginx files, inserts
nginx includes with backups, runs `nginx -t`, reloads nginx, activates
`cf_theme=nextjs25`, and executes the server verify helper.

## Deployment Notes

Do not put `127.0.0.x` or `localhost` in production environment variables.
Live builds must use HTTPS URLs reachable from the server or hosting platform.
