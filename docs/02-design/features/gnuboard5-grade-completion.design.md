# gnuboard5-grade-completion - Design Document

> Version: 1.0.0 | Date: 2026-06-16 | Status: Draft
> Level: Starter | Plan: docs/01-plan/features/gnuboard5-grade-completion.plan.md

> 2026-10-07 경로 갱신: 소스는 `nextjs/`로 변경했습니다. 아래 `nextjs25` 테마 경로는 기존 산출물이며 새 기본 테마 목표는 [Next.js Default 플랜](../../01-plan/features/nextjs-default-theme.plan.md)을 따릅니다.

---

## 1. Overview
`gnu_jango`는 Django가 서버, DRF가 API, Next.js가 프론트엔드, Django admin이 운영 콘솔을 담당하는 구조로 완성한다. `C:\xampp824\www\gnuboard5_3`의 PHP API와 Next.js 앱은 기능/응답/운영 흐름의 기준으로 삼되, 대상 프로젝트에는 Django 방식으로 재구성한다.

## 2. Target Architecture

```text
Browser
  |
  |-- /admin/ -------------------- Django admin custom UI
  |
  |-- /api/v1/... ---------------- DRF compatibility API
  |
  |-- / -------------------------- Django theme or legacy Django views
  |
  |-- Vercel Next.js app --------- nextjs, talks to Django API

gnu_jango/
  api/
    response.py                  Common JSON response helpers
    status.py                    API health/status endpoints
    v1_urls.py                   /api/v1 routing
    views.py                     Existing API views reused/extended
  templates/
    theme/nextjs25/              Django-renderable Next.js/theme output
    theme_static/nextjs25/       Next.js static output for Django
    admin/                       Custom responsive admin templates
```

## 3. API Design

### 3.1 Routing
The Django project keeps existing `/api/...` routes and adds `/api/v1/...` compatibility routes.

| Route | Purpose | Initial Implementation |
|-------|---------|------------------------|
| `/api/v1/status` | Health and capability summary | New DRF view |
| `/api/v1/config` | Site configuration | Wrap existing `gnu_config` |
| `/api/v1/menus` | Menu tree | Wrap existing `menu_api` |
| `/api/v1/boards` | Board list | New list endpoint |
| `/api/v1/boards/<id>/posts` | Posts in board | Wrap existing `BoardListAPIView` semantics |
| `/api/v1/posts` | Global post list/create | Reuse `PostViewSet` |
| `/api/v1/posts/<id>` | Post detail | Reuse `PostAPIView` |
| `/api/v1/posts/<id>/comments` | Comment write/list target | Reuse/extend comment view |

### 3.2 Response Shape
New v1 endpoints should return a predictable envelope for new code:

```json
{
  "ok": true,
  "data": {},
  "meta": {},
  "errors": []
}
```

Compatibility wrappers may preserve legacy fields when Next.js already depends on them.

### 3.3 API Completion Phases
1. Foundation: status, response helpers, v1 URLs.
2. Core board: config, menus, boards, posts, comments.
3. Member features: auth, profile, scraps, memos, notifications.
4. File features: upload, post files, thumbnails, media permissions.
5. Shop features: categories, products, cart, orders, payment callbacks.
6. External flows: social login, certification callbacks.

## 4. Next.js Design

### 4.1 Project Layout
Copy the reference Next.js project into `nextjs/`.

```text
nextjs/
  src/
  public/
  scripts/
  package.json
  next.config.ts
  vercel.json
  .env.example
```

### 4.2 Environments

| Environment | API Base |
|-------------|----------|
| Local Next dev | `http://127.0.0.1:8000/api/v1` |
| Vercel preview/production | `NEXT_PUBLIC_API_BASE_URL` |
| Django theme static output | Relative or configured Django API base |

### 4.3 Theme Sync
Add or adapt scripts so `npm run build:theme` syncs to:

```text
gnu_jango/templates/theme/nextjs25
gnu_jango/templates/theme_static/nextjs25
```

The theme sync must avoid copying `node_modules`, `.next/cache`, test artifacts, and local deployment output.

## 5. Admin UI Design

### 5.1 Goals
`/admin/` should feel like an operations dashboard, not an unstyled default admin. It must be usable on desktop and mobile.

### 5.2 Layout
- Sticky top bar with site title, quick links, account actions.
- Responsive side navigation that collapses on narrow screens.
- Dashboard cards for core operational counts.
- Admin list pages keep Django's native behavior but receive improved spacing, tables, filters, and action bars.
- Admin form pages get clearer fieldsets and sticky submit area where Django allows it.

### 5.3 Styling
Use scoped custom CSS under `static/admin_next/` so Django admin functionality remains intact. Keep colors restrained and operational: neutral surfaces, blue/green accents, clear warning/error states.

## 6. Implementation Order
1. Create plan/design documents and PDCA tracking.
2. Copy `C:\xampp824\www\gnuboard5_3\nextjs` to `nextjs` excluding generated/dependency folders.
3. Add Next.js local/Vercel environment examples and Django theme sync notes/scripts.
4. Add DRF v1 foundation: response helpers, status endpoint, URL include.
5. Add basic v1 board/menu/config/post compatibility routes.
6. Add admin CSS/JS and template improvements.
7. Run Django checks and HTTP smoke tests.
8. Run Next.js install/build checks when dependencies are available.

## 7. Verification
- `python manage.py check`
- `Invoke-WebRequest http://127.0.0.1:8000/api/v1/status`
- `Invoke-WebRequest http://127.0.0.1:8000/admin/`
- `cd nextjs && npm run build`
- Visual smoke test for admin desktop/mobile after CSS changes.

## 8. Open Gaps
The complete 그누보드5-grade finish requires additional passes beyond the foundation:
- Full auth/session/JWT parity.
- File upload and media permission parity.
- Shop/order/payment endpoint parity.
- Search, reports, notifications, memo, scrap feature parity.
- Data migration from PHP/MySQL source if production data is required.
