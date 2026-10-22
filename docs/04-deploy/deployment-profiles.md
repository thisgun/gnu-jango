# 배포 프로필: Vercel + Supabase · VPS · 분리형

하나의 코드베이스를 환경 변수만 바꿔 세 가지 방식으로 배포합니다. 새 변수를 하나도 설정하지 않으면
지금과 똑같이 동작합니다(로컬 미디어, 프로세스별 locmem 캐시, 개발 환경의 SQLite).

| 프로필 | `DEPLOY_PROFILE` | 용도 | DB | 업로드 파일 | 캐시 | 예약 작업 |
|--------|------------------|------|----|-------------|------|-----------|
| 1. Vercel + Supabase | `vercel` | 무료 데모 | Supabase Postgres(`DATABASE_URL`) | Supabase Storage(S3 호환) | DB(`CACHE_URL=db://`) | Vercel Cron 또는 Supabase pg_cron → `/api/internal/cron` |
| 2. VPS | `vps` | 운영 | Postgres 또는 SQLite | 로컬 디스크(nginx가 `/media/` 서빙) | redis 또는 DB | 시스템 cron → `manage.py run_scheduled_jobs` |
| 3. 분리형 | `split` | 운영 | (API 서버 = VPS와 동일) | 로컬 디스크 | redis 또는 DB | 시스템 cron |

환경 변수 템플릿(값은 모두 자리표시자):

- [`deploy/env/vercel-supabase.env.example`](../../deploy/env/vercel-supabase.env.example)
- [`deploy/env/vps.env.example`](../../deploy/env/vps.env.example)
- [`deploy/env/split-api.env.example`](../../deploy/env/split-api.env.example) + 프런트엔드는
  [`nextjs/.env.production.local.example`](../../nextjs/.env.production.local.example)

설정 해석 코드는 `example/settings/deploy.py`(순수 함수), 점검은 `gnu_jango/core/deploy_profile.py`,
예약 작업은 `gnu_jango/core/scheduled_jobs.py`에 있습니다.

같은 저장소로 테마만 다른 두 번째 데모(handbook)를 따로 두려면 [handbook-demo.md](handbook-demo.md) 를 보세요.

## 1. 환경 변수 스위치

### 데이터베이스

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `DATABASE_URL` | (없음) | 설정하면 `DB_ENGINE`/`DB_*`보다 우선합니다. development/production 모두 같은 함수로 해석합니다. |
| `DB_CONN_MAX_AGE` | 개발 `0` / 운영 `600` | 커넥션 재사용 시간(초). 서버리스 + 트랜잭션 풀러는 `0`. 0보다 크면 `CONN_HEALTH_CHECKS`도 켜서 끊어진 커넥션을 재사용하지 않습니다. |
| `DB_SSL_REQUIRE` | 개발 `False` / 운영 `True` | Postgres에만 `sslmode=require`를 붙입니다(SQLite·MySQL에는 붙이지 않음). 같은 호스트의 compose Postgres는 `False`. |
| `DB_DISABLE_SERVER_SIDE_CURSORS` | `False` | Supabase 트랜잭션 풀러(6543)·PgBouncer 뒤에서는 `True`(`.iterator()` 쿼리 보호). |

예전 production 설정은 `DATABASE_URL`이 있으면 항상 `ssl_require=True`로 연결했기 때문에 TLS가 없는 compose
Postgres에는 쓸 수 없었습니다. 이제 `DB_SSL_REQUIRE=False`로 끌 수 있고, `.env` 파일의 `DATABASE_URL`도
개발 설정과 똑같이 읽습니다.

### 업로드 파일(미디어)

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `MEDIA_STORAGE` | `local` | `local` = `MEDIA_ROOT`의 `FileSystemStorage`, `s3` = django-storages `S3Storage`. |
| `MEDIA_ROOT` | 개발 `<프로젝트>/media` / 운영 `""` | 로컬 저장 경로. 운영 설정은 예전부터 비어 있어 업로드가 작업 디렉터리에 저장되었고, 기존 설치가 파일을 잃지 않도록 그 기본값을 유지합니다. 운영에서는 반드시 절대 경로로 지정하세요(compose는 `/app/media`, 비어 있으면 `check_deploy_profile` 실패). |
| `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | | `s3`일 때 필수. 빠지면 부팅 시 `ImproperlyConfigured`가 누락 변수 목록을 알려 줍니다. |
| `S3_ENDPOINT_URL` | | Supabase: `https://<project-ref>.storage.supabase.co/storage/v1/s3` (AWS S3면 비움). |
| `S3_LOCATION` | | 버킷 안의 키 접두어(선택). |
| `S3_PUBLIC_BASE_URL` | | 공개 버킷 URL. 지정하면 서명 없는 URL을 만들고 `MEDIA_URL`도 이 값이 됩니다. 비우면 비공개 버킷으로 보고 만료되는 서명 URL을 씁니다(`S3_QUERYSTRING_EXPIRE`, 기본 3600초). |
| `S3_CUSTOM_DOMAIN` | | CDN 도메인을 쓸 때(`S3_PUBLIC_BASE_URL` 대신). |

S3 옵션 기본값: ACL 없음(`default_acl=None`), 덮어쓰기 금지(`file_overwrite=False`, 로컬 저장소와 동일),
path-style 주소(`S3_ADDRESSING_STYLE`로 변경 가능), SigV4. boto3 1.36 이상은 업로드마다 CRC 체크섬을 기본으로
보내는데 일부 S3 호환 서비스가 이를 거부하므로 `AWS_REQUEST_CHECKSUM_CALCULATION=when_required`,
`AWS_RESPONSE_CHECKSUM_VALIDATION=when_required`를 함께 설정합니다(botocore가 직접 읽음). 운영 전에 실제 버킷으로
업로드를 한 번 시험하세요.

### 캐시

| `CACHE_URL` | 결과 |
|-------------|------|
| 비움 / `locmem://` | Django 기본 `LocMemCache`(현재와 동일, 프로세스별). |
| `db://` 또는 `db://테이블명` | `DatabaseCache`, 기본 테이블 `gnu_jango_cache`. 최초 1회 `python manage.py createcachetable` 필요(멱등). |
| `redis://...` / `rediss://...` | Django 내장 `RedisCache`(`redis` 패키지는 이미 requirements에 있음). |
| `dummy://` | `DummyCache`(테스트용). |

`CACHE_KEY_PREFIX`로 여러 사이트가 같은 redis를 쓸 때 키를 나눕니다. locmem 캐시는 프로세스마다 따로
세므로 gunicorn 워커가 여러 개이거나 서버리스이면 DRF 스로틀(로그인 10/min 등)·재발송 쿨다운·메뉴 캐시
무효화가 인스턴스마다 따로 동작합니다. 그래서 Vercel은 `db://`(또는 redis), VPS 다중 워커는 redis를 권장합니다.

### 그 밖의 변수

| 변수 | 설명 |
|------|------|
| `SECRET_KEY` | 운영에서는 필수입니다. 이 저장소에 공개된 자리표시 값(`unsafe-`로 시작하는 개발 기본값, `deploy/env/*.example`의 `<generate: ...>`)이면 운영 설정이 시작을 거부합니다. |
| `DEPLOY_PROFILE` | `vps` / `vercel` / `split`. `check_deploy_profile`, `check_release_readiness`가 읽습니다. |
| `CRON_SECRET` | `/api/internal/cron`의 Bearer 토큰. 비어 있거나 16자 미만이면 엔드포인트가 404입니다. |
| `CSRF_TRUSTED_ORIGINS` | 다른 도메인의 프런트엔드가 CSRF 쿠키로 POST할 때(분리형 direct 모드). |
| `SPLIT_AUTH_MODE` | 분리형 점검용: `proxy`(기본, 권장) 또는 `direct`. |
| `GUNICORN_WORKERS` / `WEB_CONCURRENCY` | VPS 점검에서 locmem 캐시 경고 판단에 씁니다(Dockerfile 기본 3). |

### SMS (아이코드)

쇼핑몰 설정 → SMS 설정의 사용 여부·전송유형·관리자 휴대폰번호·문구는 관리자 화면에서 저장하지만 아이코드
인증 정보는 환경 변수로만 받습니다. 관리자 화면에는 등록됨/미등록과 테스트 발송 버튼만 보입니다.

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `G5_ICODE_TOKEN_KEY` | (없음) | 아이코드 사이트의 토큰키관리에서 만든 토큰키. 설정하면 토큰(JSON) 방식으로 SMS·LMS를 보냅니다(권장). |
| `G5_ICODE_JSON_SERVER`, `G5_ICODE_JSON_PORT` | `211.172.232.124`, `9201` | 토큰 방식 접속 주소. 영카트 `extend/sms5.extend.php`와 같은 값이며 보통 바꾸지 않습니다. |
| `G5_ICODE_ID`, `G5_ICODE_PASSWORD`, `G5_ICODE_SERVER`, `G5_ICODE_PORT` | 포트 `7295` | 구버전 아이디·비밀번호 방식(SMS 80바이트만). 토큰키가 없을 때만 씁니다. |
| `G5_SMS_PROVIDER` | (없음) | 비우거나 `icode`면 발송, `disabled`면 이 서버에서 모든 문자를 막습니다. 미리보기 설정은 항상 `disabled`입니다. |
| `G5_SMS_RECIPIENT_HOURLY_LIMIT` | `5` | 한 번호가 한 시간에 받을 수 있는 문자 수(관리자 휴대폰 `de_sms_hp`는 제외). `0`이면 제한 없음. |
| `G5_SMS_HOURLY_LIMIT` | `300` | 사이트 전체가 한 시간에 보낼 수 있는 문자 수. `0`이면 제한 없음. |
| `G5_SMS_BREAKER_SECONDS` | `300` | 아이코드 접속·응답 시간 초과나 소켓 오류 뒤 이 시간 동안 모든 발송을 건너뜁니다(주문·결제가 매번 기다리지 않도록). |

> **경고 — 스테이징·운영 데이터 복사본은 반드시 `G5_SMS_PROVIDER=disabled`로 두세요.** `migrate_gnuboard5`로
> 운영 DB를 가져오면 `cf_sms_use`(아이코드 사용)와 문구 설정도 함께 들어옵니다. 여기에 아이코드 인증 정보까지
> 있으면 테스트 주문·상태 변경·송장 등록이 **실제 고객에게 문자를 보냅니다.** 운영 서버만 발송을 켜세요.

- 문자는 주문·가입·결제 요청 안에서(커밋 직후) 바로 보냅니다. 접속 2초·응답 3초로 짧게 기다리고, 실패하면
  위 차단 시간 동안 건너뛰므로 아이코드가 멈춰도 결제 화면이 오래 걸리지 않습니다. 발송 한도와 차단 상태는
  캐시에 저장되므로 여러 인스턴스가 함께 지키려면 공유 캐시(`CACHE_URL=db://` 또는 `redis://`)가 필요합니다.
- 송장 일괄등록은 화면의 "배송안내 문자 발송"을 체크했을 때만 문자를 보냅니다.
- 두 방식 모두 HTTP가 아닌 TCP 소켓으로 아이코드 서버에 접속합니다. 나가는 연결이 HTTP 프록시 허용 목록으로
  제한된 호스팅(예: PythonAnywhere 무료 계정)에서는 발송할 수 없습니다. VPS·Vercel 함수는 바깥 TCP 연결이 됩니다.
- 회신번호는 쇼핑몰 고객센터 전화번호이며 아이코드에 발신번호로 등록되어 있어야 합니다. 서버 IP가 바뀌는
  서버리스 환경에서는 아이코드의 허용 IP 설정도 확인하세요.
- 설정 후 `python manage.py send_test_sms 010-0000-0000 --confirm`(또는 쇼핑몰 설정의 테스트 발송)으로 한 건을
  보내 확인합니다. `--confirm` 없이 실행하면 보내지 않고 보낼 내용만 보여 줍니다.

## 2. 프로필 1 — Vercel + Supabase (무료 데모)

Django 전체가 하나의 Vercel Python 함수(Fluid compute)로 실행됩니다. Vercel은 `manage.py`를 찾아
`DJANGO_SETTINGS_MODULE`(`example.settings`)과 `WSGI_APPLICATION`(`example.wsgi.application`)으로 진입점을
결정하므로 별도 진입 파일은 필요 없습니다. Python 버전은 `.python-version`(3.12)을 따릅니다.

### 2-1. Supabase

1. 프로젝트를 만들고 리전을 고릅니다(예: `ap-northeast-2`).
2. **Connect → Transaction pooler** 연결 문자열을 복사합니다(Supavisor, IPv4, 포트 6543).
   ```text
   postgresql://postgres.<project-ref>:<db-password>@<pooler-host>:6543/postgres?sslmode=require
   ```
   - 직접 연결(`db.<ref>.supabase.co:5432`)은 IPv4 애드온이 없으면 IPv6 전용이고 인스턴스마다 연결을 엽니다.
     서버리스에는 트랜잭션 풀러를 쓰세요. 트랜잭션 모드는 prepared statement·서버 사이드 커서를 지원하지
     않으므로 `DB_CONN_MAX_AGE=0`, `DB_DISABLE_SERVER_SIDE_CURSORS=True`를 함께 설정합니다
     (psycopg2는 prepared statement를 쓰지 않습니다).
   - `migrate`처럼 긴 작업을 로컬에서 실행할 때는 세션 풀러(같은 풀러 호스트의 5432)를 써도 됩니다.
3. **Storage**에서 버킷(예: `media`)을 만들고, 게시판 이미지를 공개 URL로 보여 주려면 Public bucket으로 설정합니다.
   공개 URL 형식: `https://<project-ref>.supabase.co/storage/v1/object/public/<bucket>/<key>` → `S3_PUBLIC_BASE_URL`.
4. **Storage → S3 Configuration**에서 S3 프로토콜 연결을 켜고 Access key를 발급합니다.
   엔드포인트 `https://<project-ref>.storage.supabase.co/storage/v1/s3`, 리전은 프로젝트 리전입니다.
   Supabase는 path-style 주소(`forcePathStyle`)를 요구하며 기본 설정이 이미 path-style입니다.

### 2-2. Vercel

1. 저장소를 Import 하고 **Root Directory는 저장소 루트**로 둡니다(프레임워크: Django 자동 감지).
2. `deploy/env/vercel-supabase.env.example`의 변수를 Project → Settings → Environment Variables에 입력합니다.
   `ENVIRONMENT=Production`이면 `example/settings/__init__.py`가 production 설정을 불러옵니다.
   `*.vercel.app` 배포 호스트(`VERCEL_URL`, `VERCEL_BRANCH_URL`, `VERCEL_PROJECT_PRODUCTION_URL`)는
   `VERCEL=1`일 때 `ALLOWED_HOSTS`에 자동으로 추가되므로 `ALLOWED_HOSTS`에는 커스텀 도메인만 적습니다.
   빌드 시에도 설정을 불러오므로 Production·Preview 모두에 입력하세요.
3. 루트 `vercel.json`이 하는 일:
   - `regions: ["icn1"]`: 함수를 서울에서 실행해 Supabase(`ap-northeast-2`)와 같은 리전에 둡니다. 지정하지 않으면
     Vercel 기본값인 미국 동부(`iad1`)에서 실행되어 쿼리마다 태평양을 왕복합니다(측정: 쿼리 1개 API 1.5초,
     8개 API 2.8초). Supabase를 다른 리전에 만들었다면 가장 가까운 Vercel 리전으로 바꾸세요. Hobby는 리전 1개만
     지정할 수 있습니다. 응답 헤더 `X-Vercel-Id: icn1::icn1::...`의 두 번째 값이 실제 함수 리전입니다.
   - `functions["example/wsgi.py"]`: `maxDuration` 60초, `excludeFiles`로 `nextjs/`, `docs/`, `node_modules/`,
     `.tmp-nextjs-runtime/`, 테스트(`tests.py`, `test_*.py`, `test/`), `scripts/`, `build/`, `dist/`, `media/`,
     `*.sqlite3`, 로그를 함수 번들에서 뺍니다(Python 함수 번들 한도 500MB, 자동 tree-shaking 없음).
     `gnu_jango/templates/`(테마·`theme_static` 포함)는 런타임에 Django가 직접 읽으므로 번들에 남깁니다.
   - `crons`: `/api/internal/cron`을 매일 `0 18 * * *`(UTC, 한국 시간 03시)에 호출합니다.
4. 정적 파일: `STATIC_ROOT`가 있으므로 Vercel이 빌드 중 `collectstatic`을 자동 실행하고 CDN에서 `/static/`을
   서빙합니다. WhiteNoise `CompressedManifestStaticFilesStorage`는 Vercel이 지원하는 백엔드이며, 정적 파일
   저장소는 S3로 바꾸지 않습니다(`MEDIA_STORAGE`는 업로드 전용).
5. 첫 배포 전 또는 후에 로컬에서 같은 환경 변수로 DB를 초기화합니다.
   ```bash
   pip install -r requirements.txt
   python manage.py migrate
   python manage.py createcachetable
   python manage.py createsuperuser
   python manage.py check_deploy_profile --profile vercel
   ```

Vercel Python 함수는 `requirements.txt`에서 런타임 패키지를 설치합니다. 루트 `pyproject.toml`은 개발 도구 설정만 담고 있어 `.vercelignore`에서 제외하며, Python 버전은 `.python-version`의 3.12를 따릅니다. `django-heroku`는 `psycopg2`를 소스 빌드하려 하므로 공통 의존성에서 뺐습니다. 구형 Heroku dyno에서만 필요하면 `pip install django-heroku==0.3.1`로 추가하세요. `DYNO`가 설정됐는데 패키지가 없으면 설정 시작 시 설치 안내 오류가 발생합니다.

### 2-3. 읽기 전용 파일시스템 점검 결과

Vercel 함수에서는 번들 디렉터리에 쓸 수 없습니다(`/tmp`만 임시로 가능). 런타임 쓰기 경로를 점검한 결과:

| 위치 | 상태 |
|------|------|
| 업로드(`default_storage`, `FileField`) | `MEDIA_STORAGE=s3`로 해결. 앱 코드는 모두 storage API를 사용합니다. |
| 회원 아이콘·이미지 썸네일(`utils/users.py`, `templatetags/widgets.py`) | `FieldFile.path`(원격 저장소에서 `NotImplementedError`) 대신 `.name`과 파일 객체를 쓰도록 수정. |
| sorl-thumbnail | 썸네일 파일은 기본 저장소(S3), 메타데이터는 캐시 + DB(`thumbnail_kvstore`). |
| 로그 | 기본은 콘솔. `LOG_TO_FILE=True`인데 디렉터리를 만들 수 없으면 부팅 실패 대신 콘솔로 돌아갑니다. Vercel 점검은 `LOG_TO_FILE=True`를 실패로 봅니다. |
| 세션 | DB 세션(기본). 파일 세션이면 점검 실패. |
| 캐시 | `CACHE_URL=db://` 또는 redis. FileBasedCache는 점검 실패. |
| Celery | 워커가 없으므로 `CELERY_TASK_ALWAYS_EAGER=True`(요청 안에서 실행). |
| `/data/...` 레거시 자산 폴백 | `MEDIA_ROOT/data`와 `LEGACY_GNUBOARD5_SOURCE_ROOTS`를 읽기만 합니다. S3 프로필에서는 해당 파일을 버킷에 올리고 URL을 바꿔야 보입니다. |
| 관리 명령 `nextjs_smoke` 등 | 로컬/VPS 전용(미디어 디렉터리에 테스트 파일 작성). Vercel에서 실행하지 않습니다. |
| `gnu_jango/utils/logging.py`, `utils/file_upload.py` | 파일을 쓰지만 어디서도 호출하지 않는 오래된 코드입니다. |

### 2-4. 무료 플랜 제약(작성 시점 기준, 가격 페이지에서 다시 확인하세요)

- Supabase Free: DB 500MB, Storage 1GB, 일주일 동안 활동이 없으면 프로젝트가 일시 중지(대시보드에서 재개).
- Vercel Hobby: **비상업적 개인 용도만 허용**. Cron은 하루 1회만 가능하고, 지정한 시(hour) 안의 임의 시각에 실행됩니다.
  쇼핑몰 실결제 운영에는 Pro 플랜 또는 VPS 프로필을 쓰세요.
- 저장소 루트의 레거시 `api/v1/shop/products.php`는 Vercel의 `/api` 디렉터리 규칙과 이름이 겹칩니다.
  VPS 배포 스크립트가 쓰는 파일이라 지우지 않고, 루트 `.vercelignore`(`/api/`)로 Vercel 업로드에서만 뺍니다.
  그래도 배포 후 `/api/v1/...`가 Django로 라우팅되는지 한 번 확인하세요.

## 3. 프로필 2 — VPS (운영)

### Docker compose

`docker-compose.yml`의 `web`은 `DEPLOY_PROFILE=vps`, `CACHE_URL=redis://redis:6379/1`(compose의 redis 서비스),
`MEDIA_STORAGE=local`을 기본값으로 받습니다. `.env`에 `deploy/env/vps.env.example` 값을 채운 뒤:

```bash
docker compose up -d --build
docker compose exec web python manage.py check_deploy_profile
```

- `SECRET_KEY`는 기본값이 없습니다. `.env`에 넣지 않으면 compose가 시작 전에 멈춥니다.
- 컨테이너는 root가 아닌 `app` 사용자(uid 10001)로 실행되고, `/app/media`와 `/app/logs`에만 씁니다.
  `web`에는 8000번 포트 상태 점검(healthcheck)이 붙어 있습니다.
- root로 실행되던 예전 이미지에서 만든 `media` 볼륨은 소유자가 root라 업로드가 실패합니다. 한 번만 소유자를 바꾸세요:
  `docker compose run --rm --user root web chown -R app:app /app/media`
- 이미지를 `docker run`으로 직접 쓸 때 `MEDIA_ROOT` 기본값은 `/app/media`입니다. 호스트 폴더를 연결(bind mount)한다면
  그 폴더의 소유자를 uid 10001로 바꿔 두세요(`sudo chown -R 10001:10001 <폴더>`).

### gunicorn + nginx 직접 설치

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createcachetable   # CACHE_URL=db:// 일 때만
gunicorn example.wsgi:application --workers 3 --bind 127.0.0.1:8000
```

nginx는 `/static/`(또는 WhiteNoise에 맡김)과 `/media/` → `MEDIA_ROOT`를 직접 서빙합니다. SQLite도 가능하지만
DB 파일을 영구 디스크에 두고 백업하세요(`DATABASE_URL=sqlite:////srv/gnu_jango/data/db.sqlite3`).

## 4. 프로필 3 — 분리형 (Vercel 프런트 + VPS API)

- **프런트엔드**: `nextjs/`를 Root Directory로 하는 별도 Vercel 프로젝트입니다. 기존 `nextjs/vercel.json`(보안 헤더)은
  그대로 쓰며, 저장소 루트의 `vercel.json`은 이 프로젝트에 영향을 주지 않습니다. 환경 변수는
  `nextjs/.env.production.local.example`과 `nextjs/README.md`를 따릅니다.
- **API**: VPS 프로필과 같고 `deploy/env/split-api.env.example`을 씁니다. 인증 방식은
  `nextjs/README.md`의 "Cross-Domain Authentication"을 따릅니다.
  - `SPLIT_AUTH_MODE=proxy`(권장): 브라우저는 프런트 도메인만 호출하고 Next.js가 `/api/v1`을 서버에서 전달합니다.
    프런트에 `G5_NEXT_RUNTIME=server`, `G5_API_INTERNAL_URL=https://<api>/api/v1`, `NEXT_PUBLIC_API_URL` 미설정.
    API에는 CORS가 필요 없습니다.
  - `SPLIT_AUTH_MODE=direct`: `CORS_ALLOWED_ORIGINS=https://<front>`, `CORS_ALLOW_CREDENTIALS=True`,
    `CSRF_TRUSTED_ORIGINS=https://<front>`. `g5_refresh` 쿠키가 `SameSite=Lax`라 새로고침 시 세션이 유지되지
    않으므로 점검은 경고를 냅니다.

## 5. 예약 작업

| 작업 | 내용 |
|------|------|
| `expire_pending_payment_orders` | 결제가 끝나지 않은 오래된 주문 자동 취소 |
| `expire_pending_email_members` | 메일 인증 기한이 지난 가입 대기 회원 처리 |
| `expire_toss_vbank_orders` | 입금 기한이 지난 Toss 가상계좌 주문 취소 |
| `cleanup_admin_privacy` | 보존 기간이 지난 방문 로그·검색어 삭제 |

```bash
python manage.py run_scheduled_jobs              # 모두 적용(--apply)
python manage.py run_scheduled_jobs --dry-run    # 변경 없이 확인
python manage.py run_scheduled_jobs --job cleanup_admin_privacy --json
```

작업마다 실패를 격리합니다(하나가 실패해도 나머지는 실행). 하나라도 실패하면 종료 코드가 0이 아닙니다.
같은 실행이 겹치면 캐시 락으로 건너뜁니다(공유 캐시에서만 프로세스 간 유효). 각 작업은 행 잠금으로
멱등하게 동작하므로 cron이 같은 실행을 두 번 보내도 안전합니다.

HTTP 엔드포인트 `GET`/`POST /api/internal/cron`은 같은 작업을 실행합니다.

- `CRON_SECRET`이 비어 있거나 16자 미만이면 404, `Authorization: Bearer <CRON_SECRET>`이 맞지 않으면 401(상수 시간 비교).
- 응답은 `api_response` 봉투에 작업별 결과(`status`, `duration_ms`, 건수 요약, `error`)를 담고, 실패가 있으면 500.
  개별 주문·회원 ID 샘플은 응답에서 뺍니다. `Cache-Control: no-store`. `?dry_run=1`로 점검 실행.

### 프로필별 설정

- **Vercel Cron**: 루트 `vercel.json`의 `crons`. Vercel이 `CRON_SECRET` 환경 변수를 자동으로
  `Authorization: Bearer` 헤더로 보냅니다. Hobby는 하루 1회만 허용되므로 기본값은 매일입니다. 유료 플랜이면
  미결제 주문을 빨리 정리하도록 매시간으로 바꾸세요: `"schedule": "0 * * * *"`. cron은 리다이렉트를 따라가지
  않으므로 경로는 정확히 `/api/internal/cron`(끝 슬래시 없음)이어야 합니다.
- **Supabase pg_cron**(Hobby의 하루 1회 제한을 피하고 싶을 때): Database → Extensions에서 `pg_cron`, `pg_net`을
  켜고, 비밀값은 Vault에 저장합니다.
  ```sql
  select vault.create_secret('<CRON_SECRET 값>', 'gnu_jango_cron_secret');

  select cron.schedule(
    'gnu-jango-scheduled-jobs',
    '0 * * * *',
    $$
    select net.http_get(
      url := 'https://<your-app>/api/internal/cron',
      headers := jsonb_build_object(
        'Authorization',
        'Bearer ' || (select decrypted_secret from vault.decrypted_secrets where name = 'gnu_jango_cron_secret')
      ),
      timeout_milliseconds := 60000
    );
    $$
  );
  ```
  이 경우 `vercel.json`의 `crons`는 지워도 됩니다(둘 다 두어도 멱등이라 안전).
- **VPS 시스템 cron**:
  ```cron
  # crontab -e  (매시 5분)
  5 * * * * cd /srv/gnu_jango && /srv/gnu_jango/.venv/bin/python manage.py run_scheduled_jobs >> /var/log/gnu_jango/cron.log 2>&1
  # Docker compose
  5 * * * * cd /srv/gnu_jango && docker compose exec -T web python manage.py run_scheduled_jobs
  ```

## 6. 배포 준비도 점검

```bash
python manage.py check_deploy_profile                 # DEPLOY_PROFILE 사용
python manage.py check_deploy_profile --profile vercel --strict --json
python manage.py check_release_readiness              # DEPLOY_PROFILE이 있으면 같은 점검을 포함
```

| 프로필 | 점검 항목 |
|--------|-----------|
| 공통 | `DEBUG` 꺼짐, 운영용 `SECRET_KEY`(50자 이상, 개발 기본값 아님), `ALLOWED_HOSTS` |
| vercel | Postgres `DATABASE_URL`(풀러 6543이면 서버 사이드 커서 끔·`CONN_MAX_AGE=0`, `sslmode`), `MEDIA_STORAGE=s3`, 공유 캐시(db 캐시면 테이블 존재), `CRON_SECRET` 16자 이상, 디스크 쓰기 없음(파일 로그·파일 세션·파일 캐시), Celery eager |
| vps | DB(SQLite면 안내), 로컬 미디어면 절대 경로 `MEDIA_ROOT`, 워커가 2개 이상인데 locmem 캐시면 경고, `STATIC_ROOT` |
| split | vps 항목 + 교차 도메인 인증(proxy/direct), Secure 쿠키, `CORS_ALLOW_ALL_ORIGINS`+자격 증명 조합 금지 |

## 7. 프로필 간 데이터 이전

### Postgres ↔ Postgres (VPS ↔ Supabase)

```bash
# 원본에서 덤프 (custom 형식)
pg_dump --format=custom --no-owner --no-privileges "$SOURCE_DATABASE_URL" -f gnu_jango.dump
# 대상에 복원 (Supabase는 세션 풀러 5432 또는 직접 연결 사용, 트랜잭션 풀러는 피함)
pg_restore --no-owner --no-privileges --clean --if-exists -d "$TARGET_DATABASE_URL" gnu_jango.dump
DATABASE_URL="$TARGET_DATABASE_URL" python manage.py migrate
DATABASE_URL="$TARGET_DATABASE_URL" python manage.py createcachetable
```

### SQLite → Postgres

```bash
python manage.py dumpdata --natural-foreign --natural-primary \
  --exclude contenttypes --exclude auth.permission --exclude sessions --exclude admin.logentry \
  -o gnu_jango.json
DATABASE_URL="$TARGET_DATABASE_URL" python manage.py migrate
DATABASE_URL="$TARGET_DATABASE_URL" python manage.py loaddata gnu_jango.json
```

### 미디어 파일

로컬 `MEDIA_ROOT` ↔ Supabase Storage는 S3 호환 도구로 동기화합니다(키 경로는 그대로 유지, `S3_LOCATION`을
쓰면 그 접두어 아래로).

```bash
AWS_ACCESS_KEY_ID=<s3-access-key-id> AWS_SECRET_ACCESS_KEY=<s3-secret-access-key> \
aws s3 sync ./media "s3://<bucket>/" \
  --endpoint-url "https://<project-ref>.storage.supabase.co/storage/v1/s3" --region <project-region>
# 반대 방향은 원본/대상을 바꿉니다. rclone(S3 provider=Other, force_path_style=true)도 사용할 수 있습니다.
```

이전 후 `python manage.py thumbnail cleanup`으로 이전 저장소를 가리키는 썸네일 메타데이터를 정리하세요.

## 8. 운영자가 할 일

- `pip install -r requirements.txt`: `django-storages[s3]`, `boto3`가 추가되었고 `psycopg2`는
  `psycopg2-binary`(같은 모듈·버전, 컴파일러 불필요)로 바뀌었습니다. 설치·테스트 후 범위 지정된 버전을 고정하세요.
- `CACHE_URL=db://`이면 대상 DB마다 `python manage.py createcachetable`.
- 기존 운영 설치는 `MEDIA_ROOT`가 비어 업로드가 작업 디렉터리(compose는 볼륨이 아닌 `/app/<경로>`)에 저장되었습니다.
  `MEDIA_ROOT`를 지정하기 전에 해당 파일을 새 경로로 옮기세요.
- Supabase 버킷 생성·공개 여부 결정, S3 Access key 발급, Vercel 환경 변수 입력.
- 배포 후 `check_deploy_profile`과 `/api/internal/cron?dry_run=1`(Bearer 헤더 포함)로 확인.

## CI/CD (GitHub Actions)

- **CI** (`.github/workflows/ci.yml`): PR과 `main` push마다 PostgreSQL 16으로 Django 테스트를 병렬 실행하고(커버리지 하한 65%), Next.js 타입 검사·빌드를 돌립니다. Docker 이미지도 빌드해(push 없이) root가 아닌 사용자로 뜨는지, gunicorn이 8000번에서 응답하는지 확인합니다. **공개 저장소에서만** 실행되고, 비공개 저장소에서는 작업이 건너뜁니다.
- **CodeQL** (`.github/workflows/codeql.yml`, 공개 저장소에서만): PR, `main` push, 매주 월요일에 Python과 JavaScript/TypeScript 코드를 정적 분석합니다. 결과는 Security → Code scanning에 나옵니다.
- **CD** (`.github/workflows/cd.yml`, 공개 저장소에서만):
  - `main`에서 CI가 통과하면 Docker 이미지를 `ghcr.io/<owner>/<repo>:main`과 `:sha-<커밋>`으로 올립니다. VPS에서는 `docker pull` 후 재시작하면 됩니다.
  - `v1.2.3` 같은 태그를 push하면 `:1.2.3`·`:latest` 이미지와 GitHub Release를 만듭니다.
  - Vercel 자동 배포(선택): 저장소 변수 `VERCEL_DEPLOY=true`와 비밀값 `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`를 넣으면 CI 통과 후 프로덕션으로 배포합니다. 설정하지 않으면 이 단계는 건너뜁니다.
- 비밀값은 저장소 Settings → Secrets and variables → Actions에 넣고, 포크에서 온 PR에는 전달되지 않습니다.
