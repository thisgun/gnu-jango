# GNU Jango

GNU Jango는 그누보드5·영카트의 게시판, 회원, 쇼핑몰 기능을 Django와 Django REST Framework로 옮기는 프로젝트입니다. Django가 관리 화면과 REST API를 제공하고, `nextjs/`의 Next.js 프런트엔드는 Django 테마로 빌드하거나 독립 Node 서버로 실행할 수 있습니다.

## 데모

- 커뮤니티·쇼핑몰 테마: [gnu-jango-demo.vercel.app](https://gnu-jango-demo.vercel.app/)
- 매뉴얼 테마: [gnu-jango-handbook.vercel.app](https://gnu-jango-handbook.vercel.app/)

## 현재 구성

| 구분 | 구성 |
|---|---|
| 백엔드 | Python 3.13 (`.python-version`), Django 6.1.2, Django REST Framework |
| 프런트엔드 | Next.js 16.3.8, React 19.2.7 (`nextjs/`) |
| 관리자 | django-unfold, 테마 설정(`/admin/theme/`), 샘플 데이터(`/admin/sample-data/`) |
| 개발 DB | SQLite |
| 운영 배포 | Vercel + Supabase, Docker Compose 기반 VPS, 프런트엔드·API 분리형 |
| 작업 처리 | Celery·Redis 또는 배포 환경의 예약 작업 |

기본 Next.js 테마는 커뮤니티·쇼핑몰용 `nextjs_default`이며, 문서 사이트용 `handbook` 테마도 포함합니다. Vercel은 Django 앱을 실행하고, 테마 HTML과 정적 자산은 저장소에 포함된 빌드 결과를 사용합니다.

## 저장소 구조

```text
example/                 Django 설정, URL, WSGI 진입점
gnu_jango/               Django 앱, 관리자 화면, 템플릿, 테마 산출물
nextjs/                  Next.js 프런트엔드 소스와 빌드 도구
deploy/env/              Vercel, VPS, 분리형 배포 환경변수 예시
docs/04-deploy/          배포 및 테마 운영 안내
requirements.txt         Django 런타임 의존성
requirements-dev.txt     개발 도구 의존성
```

## Django 로컬 실행

Python 3.13을 사용합니다. Windows PowerShell:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS 또는 Linux:

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

`.env`에 개발용 `SECRET_KEY`를 설정합니다. 아래 명령으로 키를 생성한 뒤 값을 `.env`에 직접 입력하세요. `.env`와 운영 비밀값은 저장소에 커밋하지 않습니다.

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

데이터베이스를 초기화하고 관리자를 만든 뒤 서버를 실행합니다.

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
```

- 사이트: <http://127.0.0.1:8000/>
- Django 관리자: <http://127.0.0.1:8000/admin/>
- API: <http://127.0.0.1:8000/api/v1/>

기본 개발 설정은 SQLite와 `DEBUG=True`를 사용합니다. 실제 운영 환경에는 적용하지 마세요.

## Next.js 프런트엔드 실행

Django 서버와 별도 터미널에서 실행합니다.

```powershell
Set-Location nextjs
npm ci
Copy-Item .env.example .env.local
```

`.env.local`에서 API 주소를 로컬 Django 서버에 맞춥니다. 권장 프록시 모드에서는 `G5_API_INTERNAL_URL`을 `http://127.0.0.1:8000/api/v1`로 설정하고 `NEXT_PUBLIC_API_URL`은 비워 둡니다. 프런트엔드 개발 서버를 시작합니다.

```powershell
$env:G5_NEXT_RUNTIME = 'server'
npm run dev
```

프런트엔드는 <http://localhost:3000/>에서 확인할 수 있습니다. 환경 변수, 인증 방식, 서버 모드와 정적 테마 빌드의 자세한 절차는 [Next.js 안내](nextjs/README.md)를 참고하세요.

## 테마 빌드와 관리자 설정

`nextjs/`에서 빌드하면 Django가 사용하는 테마 파일을 함께 갱신합니다.

```bash
cd nextjs
npm run build:theme                 # nextjs_default
npm run build:theme:handbook         # handbook
```

산출물은 `gnu_jango/templates/theme/`와 `gnu_jango/templates/theme_static/`에 저장됩니다. Django 관리자에서 `/admin/theme/`으로 테마를 선택하고, `/admin/sample-data/`에서 샘플 콘텐츠를 추가하거나 삭제할 수 있습니다. 테마 설치·복구 절차는 [테마 배포 안내](docs/04-deploy/nextjs-default-theme.md)에 있습니다.

## 배포 방식

| 방식 | 구성 | 안내 |
|---|---|---|
| Vercel + Supabase | Django Python 함수, Supabase PostgreSQL·Storage, 공유 캐시와 Vercel Cron | [배포 프로필](docs/04-deploy/deployment-profiles.md), [환경변수 예시](deploy/env/vercel-supabase.env.example) |
| VPS | Docker Compose의 Django, PostgreSQL, Redis, Celery worker; 또는 기존 운영 서버 구성 | [배포 프로필](docs/04-deploy/deployment-profiles.md), [환경변수 예시](deploy/env/vps.env.example) |
| 분리형 | VPS의 Django API와 별도 Node 기반 Next.js 프런트엔드 | [배포 프로필](docs/04-deploy/deployment-profiles.md), [환경변수 예시](deploy/env/split-api.env.example) |

Docker Compose는 `.env`의 `SECRET_KEY`를 요구하고, 웹 컨테이너 시작 때 마이그레이션을 적용합니다. 로컬 컨테이너를 실행하려면 비밀값을 설정한 뒤 다음 명령을 사용합니다.

```bash
docker compose up --build
```

Vercel 프로젝트는 저장소 루트를 기준으로 설정합니다. 테마 빌드 결과를 바꿨다면 두 테마 디렉터리의 산출물을 함께 커밋해야 합니다. 별도 handbook 데모처럼 같은 브랜치에 연결된 Vercel 프로젝트가 여러 개면 `main` 푸시가 모두 배포를 시작합니다. handbook 프로젝트의 테마 기본값과 DB 준비는 [handbook 데모 안내](docs/04-deploy/handbook-demo.md)를 참고하세요.

운영 배포 전에 환경 변수 예시의 자리표시자를 실제 설정으로 바꾸고, 프로필 점검을 실행합니다.

```bash
python manage.py check_deploy_profile --profile vps
python manage.py check_release_readiness
```

Vercel을 점검할 때는 프로필을 `vercel`로 바꾸세요. 지원 프로필은 `vps`, `vercel`, `split`입니다. PG·소셜 로그인·본인인증 연동은 각 공급자의 테스트 키와 callback 설정이 있어야 동작합니다. 비밀 키를 Git에 넣지 말고 `.env.example`과 `deploy/env/`의 예시를 참고하세요.

## 개발 점검

백엔드 테스트:

```bash
python manage.py test gnu_jango --parallel auto
```

프런트엔드 점검:

```bash
cd nextjs
npm run typecheck
npm run check:vercel-env:template
npm run check:theme-sync
```

## 라이선스

라이선스와 포함된 제3자 구성요소 고지는 [LICENSE](LICENSE)와 [NOTICE](NOTICE)를 참고하세요.
