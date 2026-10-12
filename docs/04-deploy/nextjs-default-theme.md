# Next.js 기본 테마 배포 및 복구

이 문서는 `nextjs/`에서 만든 테마를 Django 템플릿 경로 `gnu_jango/templates/theme/nextjs_default/`와 정적 자산 경로 `gnu_jango/templates/theme_static/nextjs_default/`에 반영하는 절차를 설명한다. 독립 Next.js 서버 실행 절차도 함께 기록한다.

2026-10-08에 분리된 로컬 Django 환경에서 패키지 설치·관리자 테마 전환·복구를 확인했다. 외부 운영 서버의 반영과 복구는 실행하지 않았다. 실서비스 배포는 PRD의 제외 범위이며, 로컬 검증을 위해 외부 스테이징 주소를 준비할 필요는 없다.

## 배포 모드

| 모드 | 용도 | 산출물 |
|---|---|---|
| Django 정적 테마 | Django가 HTML·API·자산 URL을 요청 시점에 제공 | `templates/theme/nextjs_default/`, `templates/theme_static/nextjs_default/` |
| 독립 Next.js 서버 | Node 서버가 페이지를 렌더링하고 Django API로 프록시 | Next.js `.next-server-build` 산출물과 Node 프로세스 |
| Vercel 정적 배포 | 정적 데모 또는 별도 공개 프런트엔드 | 정적 export와 `vercel.json` 보안 헤더 |

이 프로젝트의 Django 기본 테마는 **Django 정적 테마** 모드를 사용한다. `nextjs25`는 기존 저장값과 URL 호환 별칭이다. `cf_theme=nextjs25`를 `nextjs_default`로 연결하므로 이전 테마를 되돌릴 때 `nextjs25`를 선택값으로 쓰지 않는다.

## 분리된 로컬 환경에서 재현

기존 패키지와 SQLite DB, Python 가상환경 및 `nextjs/node_modules`가 있는 저장소 루트에서 실행한다. DB에는 공개 게시글과 사용 중인 상품이 각각 하나 이상 있어야 한다.

```powershell
Set-Location E:\gnu-jango\gnu_jango
& .\.venv314\Scripts\python.exe scripts\rehearse_nextjs_theme.py
```

다른 파일을 사용할 때는 `--archive <tar.gz 경로>`와 `--database <SQLite 경로>`를 지정한다. `--port` 기본값 0은 사용하지 않는 루프백 포트를 선택한다.

이 명령은 다음 순서로 진행한다.

1. 아카이브 SHA-256, 매니페스트 및 파일별 체크섬을 확인한다.
2. `.tmp-nextjs-runtime/staging-*`에 Django 소스·SQLite·미디어를 복제한다. 원본 `.env`를 사용하지 않고, 미디어·캐시·메일·세션을 분리한다.
3. 복제 DB에 임시 관리자와 `basic` 선택값을 준비하고 이전 HTML·자산의 한 쌍을 백업한다. 이전 릴리스를 구분하는 마커 두 개와 서비스워커 주석도 준비한다.
4. `DEBUG=False`인 별도 Django 서버에서 관리자 로그인과 기존 홈·게시글·상품·RSS·자산을 확인한다. 이 로컬 서버는 정적 파일과 미디어도 제공하며, 실서비스 WSGI/프록시 구성을 검증하는 서버는 아니다.
5. 이전 해시 자산을 유지하며 새 자산과 HTML을 반영하고 `/admin/theme/`에서 `nextjs_default`를 적용한다. 화면·자산 해시·모바일 가로 넘침을 확인한다.
6. 두 폴더를 같은 백업에서 복원한 뒤 관리자에서 `basic`을 선택한다. 복원된 파일 목록·해시와 서비스워커 파일, 게시글·상품·RSS를 다시 확인한다.
7. 업무 DB 행과 원본 DB의 SHA-256을 비교하고 `REPORT.json`을 저장한다. 별도 서버는 자동 종료한다.

업무 데이터 비교에서는 `cf_theme`, 세션, 방문 로그, SQLite 시퀀스, 조회수(`wr_hit`, `it_hit`), 마지막 로그인 시각을 구분한다. 회원·게시글·상품·주문 등 나머지 행은 동일해야 한다. 원본 DB는 읽기 전용으로 복제하며 전체 파일 해시도 실행 전후 같아야 한다.

현재 Django 공개 설정은 `pwa_enabled=false`다. 검증용 브라우저에서 직접 서비스워커를 등록·갱신해 해당 산출물의 활성화를 확인한다. 자동 PWA 등록이 켜진 상태의 검증을 주장하지 않는다. `basic` 복구는 홈 선택값의 복구이며, 기존 URL 브리지의 게시판·상품 상세는 계속 지원되는 Next 테마 shell을 사용한다.

외부 HTTP 요청은 검증 브라우저에서 차단한다. `nextjs_default` 단계에는 외부 호스트 요청이 없었고, 클래식 테마의 Gravatar 요청만 차단 목록에 남았다. DB 복제본·브라우저 프로필·스크린샷·보고서는 이 Git 제외 폴더에 보관한다. 비밀번호는 보고서에 기록하지 않는다.

최종 통과 기록은 `.tmp-nextjs-runtime/staging-7ra9v9ha/REPORT.json`이다. 설치 전 128개, 설치 후 282개, 복구 후 86개 확인이 통과했고, 세 단계의 처리되지 않은 브라우저 오류는 0건이었다. 테마 파일 2,321개와 이전 마커를 포함한 복구 파일 2,323개를 확인했다. 기존·복구 서비스워커 파일의 SHA-256은 같고 설치한 새 파일의 SHA-256은 달랐다. 업무 데이터와 원본 DB는 보존됐다.

### 운영 설정의 스크립트 정책

테마 아카이브에는 Django 서버 코드가 포함되지 않는다. 별도 설치본에는 현재 저장소의 `gnu_jango/core/views.py`와 `core/middleware.py` 보완을 포함한 Django 코드를 먼저 반영해야 한다. 테마 페이로드는 커밋 `72f22dee`의 패키지와 같으며, 검증 보고서에는 실제 사용한 두 Django 파일의 해시도 기록했다.

- Django가 제공하는 Next HTML은 응답마다 새 nonce를 만들고 export 스크립트 및 런타임 설정에 붙인다. 운영 설정의 일반 화면은 임의의 인라인 스크립트와 eval을 허용하지 않는다. URL에서 가져온 런타임 JSON의 `<`, `>`, `&`도 이스케이프한다. 이 방식은 Django가 HTML을 요청마다 처리하기 때문에 가능하다. [Next.js CSP 안내](https://nextjs.org/docs/app/guides/content-security-policy)
- 설치된 Unfold는 기본 Alpine을 사용한다. 해당 라이브러리의 HTML 표현식 실행에 필요한 eval 권한을 Django 관리자 및 관리자 테마 설정 뷰에만 추가한다. 관리자에 이 권한이 필요한 이유는 [Alpine CSP 안내](https://alpinejs.dev/advanced/csp)에 설명돼 있다.
- 현재 번들의 Zod 4는 `Function("")`을 try/catch로 시험하고, 정책이 차단하면 인터프리터를 사용한다. 검증기는 매니페스트 해시와 정확한 probe 코드를 확인한 경우에만 이 잡힌 CSP 진단을 구분한다. 다른 CSP 위반과 처리되지 않은 오류는 실패로 판정한다.

## Django 정적 테마

### 1. 빌드 환경 준비

`nextjs/`에서 의존성을 설치하고 배포 주소에 맞는 환경 파일을 만든다. `.env.production.local`은 Git에 추가하지 않는다.

```powershell
Set-Location E:\gnu-jango\gnu_jango\nextjs
npm ci
Copy-Item .env.production.local.example .env.production.local
```

`.env.production.local`의 다음 값을 배포 환경에 맞게 지정한다.

| 변수 | 값 |
|---|---|
| `NEXT_PUBLIC_API_URL` | Django API의 공개 HTTPS 주소. `/api/v1`로 끝나야 한다. |
| `G5_API_INTERNAL_URL` | 빌드·서버에서 접근할 수 있는 Django API 주소. `/api/v1`로 끝나야 한다. |
| `NEXT_PUBLIC_G5_URL` | 공개 Gnuboard/Django 주소 |
| `NEXT_PUBLIC_APP_URL` | 공개 Next.js 앱 주소 또는 Django 사이트 주소 |
| `NEXT_PUBLIC_AUTH_MODE` | `g5-jwt` |
| `NEXT_PUBLIC_GALLERY_BOARDS` | 갤러리 레이아웃을 사용할 게시판 ID 목록 |

Django 통합 화면은 요청 시점에 현재 호스트를 기준으로 API·기본 URL 설정과 canonical/OG URL을 보정한다. 그래도 정적 생성 시 사용하는 공개 URL에는 localhost, `127.0.0.x`, `example.com`을 넣지 않는다.

### 2. 빌드하고 동기화 확인

```powershell
npm run build:theme
npm run package:theme
```

`build:theme`는 셸의 `G5_NEXT_RUNTIME` 값과 관계없이 임시 프로젝트 복사본에서 정적 빌드를 수행한다. Next 15는 export 중 내부 작업에 `.next`를 사용하므로, 격리된 복사본에서 빌드해 활성 Node 서버의 `nextjs/.next`를 보존한다. 서비스워커 버전과 Apache 정적 보안 헤더를 생성한 뒤 export를 `nextjs/out`에 반영하고 두 Django 테마 경로로 동기화한다.

```text
gnu_jango/templates/theme/nextjs_default/
gnu_jango/templates/theme_static/nextjs_default/
```

HTML·manifest·서비스워커 등 공개 파일은 첫 번째 경로에, `_next/static`과 `assets`는 두 번째 경로에 둔다. 동기화 검사는 `out`과 두 배포 디렉터리의 파일 목록 및 해시가 일치하는지 확인한다.

`package:theme`은 동기화 확인 후 `nextjs/.deploy/nextjs-default-theme.tar.gz`를 만든다. 압축 파일에는 `upload/theme/nextjs_default/`와 `upload/theme_static/nextjs_default/`의 한 빌드 쌍, 이 배포 안내서 사본(`DEPLOYMENT.md`), `MANIFEST.json`, 파일별 `CHECKSUMS.sha256`가 포함된다. 옆의 `nextjs-default-theme.tar.gz.sha256` 파일은 압축 파일 자체의 SHA-256 값이다. `MANIFEST.json`은 소스 커밋과 패키지에 포함된 테마 파일별 크기·해시를 기록한다.

### 3. 대상 Django에 반영

1. 현재 `TEMPLATES_DIR/theme/nextjs_default`와 `TEMPLATES_DIR/theme_static/nextjs_default`를 같은 릴리스 ID로 백업한다. 기존 테마 선택값(`cf_theme`)도 기록한다.
2. 생성한 `_next/static`·`assets` 파일을 먼저 게시한다. 브라우저 캐시에 남은 이전 HTML이 기존 해시 청크를 참조할 수 있으므로 이전 해시 자산은 배포 직후 삭제하지 않는다.
3. 새 HTML과 공개 파일을 `TEMPLATES_DIR/theme/nextjs_default`에 반영한다. HTML과 자산은 같은 빌드에서 나온 쌍이어야 한다.
4. 운영자 설정에서 테마 선택값을 `nextjs_default`로 바꾼다. 서버 코드의 기본값도 `nextjs_default`지만 기존 DB 값을 일괄 변경할 필요는 없다.
5. 홈, 게시판 직접 주소, 상품 상세, 장바구니, manifest, 서비스워커를 확인한다. 로그인·주문·결제 같은 쓰기 동작은 운영 검증 절차와 테스트 계정이 준비된 경우에만 수행한다.

이 저장소에서는 `settings.TEMPLATES_DIR`이 `gnu_jango/templates`를 가리킨다. 별도 설치본에 복사할 때는 그 설치본의 `TEMPLATES_DIR`을 기준으로 동일한 두 하위 경로를 사용한다. `_next/static` 요청은 Django의 `theme_static/nextjs_default` 자산 경로에서 제공한다.

### 4. 정적 배포 후 확인

브라우저에서 공개 화면을 확인하고 개발자 도구 Network에서 HTML이 참조하는 모든 `_next/static` 파일이 HTTP 200인지 확인한다. 개인 페이지·장바구니·주문·결제 응답에는 공유 캐시가 적용되지 않아야 한다. 배포한 서버에서 확인할 주소는 다음과 같다.

```text
/
/free
/shop/77777
/shop/cart
/manifest.webmanifest
/sw.js
```

저장소에 동기화된 `nextjs/out`에는 `.html` 페이지 1,049개와 같은 수의 `.txt` RSC payload가 있고, 자산을 포함한 전체 파일은 2,321개다. `npm run check:theme-sync`가 `out`과 Django 템플릿·정적 자산의 파일 목록과 해시를 비교한다. 실제 배포 서버의 헤더·도메인·권한 확인은 별도 수행한다.

## 독립 Next.js 서버

Node 서버 모드에서는 정적 export 명령인 `build:theme`을 사용하지 않는다. 다음 명령이 서버 모드와 `.next-server-build` 경로를 빌드와 시작에 함께 설정한다.

```powershell
Set-Location E:\gnu-jango\gnu_jango\nextjs
npm ci
npm run build:server
npm run start:server
```

서버 환경에는 `G5_API_INTERNAL_URL`, `NEXT_PUBLIC_G5_URL`, `NEXT_PUBLIC_APP_URL`을 설정한다. 브라우저가 Next.js 프록시를 통하도록 하려면 `NEXT_PUBLIC_API_URL`을 비워 두고 `G5_API_INTERNAL_URL`에 서버에서 접근 가능한 Django API 주소(`/api/v1` 포함)를 지정한다. 운영 프로세스 관리자와 프록시 설정은 배포 호스트의 기존 운영 방식에 맞춘다.

두 스크립트는 별도 `.next-server-build` 디렉터리를 사용하므로 Django 정적 테마 빌드와 기존 `.next` 프로세스의 청크를 덮어쓰지 않는다. 사용자 지정 경로가 필요하면 빌드와 시작 명령 모두에 같은 `G5_NEXT_DIST_DIR` 값을 전달한다.

Vercel 정적 배포는 프로젝트 환경 변수에 공개 HTTPS 주소를 설정한 뒤 `npm run check:vercel-env`와 `npm run check:release:vercel`로 준비 상태와 정적 빌드를 확인한다. 이 명령은 실제 Vercel 배포를 수행하지 않는다.

## 복구

### Django 정적 테마 복구

1. `cf_theme`를 배포 전에 기록한 이전 값으로 되돌린다. 이전 테마 디렉터리를 백업하지 않았다면 테마 선택만 바꾸어도 복구되지 않는다.
2. 같은 백업 릴리스에서 `TEMPLATES_DIR/theme/nextjs_default`와 `TEMPLATES_DIR/theme_static/nextjs_default`를 함께 복원한다.
3. 이전 서비스워커·manifest와 청크 자산이 일치하는지 확인하고 홈·게시판·쇼핑 주소를 다시 연다.
4. 원인을 제거하고 새 빌드로 재배포할 때까지 새 테마 선택을 보류한다.

데이터베이스 스키마나 사용자 데이터는 이 테마 빌드·복구에 포함되지 않는다. `cf_theme=nextjs25`는 새 테마의 호환 별칭이므로 이전 화면으로 되돌리는 값이 아니다.

### 독립 서버 복구

릴리스별 `.next-server-build` 디렉터리와 환경 변수를 보관하고, 문제 발생 시 직전 서버 빌드와 환경 파일을 다시 활성화한 뒤 Node 프로세스를 재시작한다. Django 정적 테마와 독립 서버를 같은 주소에서 함께 전환하지 말고, 프록시가 가리키는 모드를 한 번에 하나씩 바꾼다.

## 기존 라이브 배포 도구 주의

`npm run package:live`와 `npm run deploy:live:ssh`는 기존 PHP Gnuboard 배포의 `theme/nextjs25` 및 PHP bridge, API·nginx 파일을 대상으로 한다. 이 문서의 Django `nextjs_default` 두 디렉터리를 배포하는 명령이 아니므로 새 Django 테마를 반영할 때 사용하지 않는다.
