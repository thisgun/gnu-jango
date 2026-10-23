# GNU Jango

GNU Jango는 그누보드5·영카트의 게시판, 회원, 쇼핑몰 기능을 Django와 Django REST Framework로 옮기는 프로젝트입니다. Django가 관리 화면과 REST API를 제공하고, `nextjs/`의 Next.js 프런트엔드는 Django 테마로 빌드하거나 독립 Node 서버로 실행할 수 있습니다.

## 주요 기능

- 그누보드5 게시판·회원과 영카트 쇼핑몰 도메인을 Django 모델과 관리 화면으로 제공합니다.
- 그누보드5 비밀번호 해시를 호환하고, `migrate_gnuboard5` 명령으로 기존 데이터베이스의 데이터를 가져올 수 있습니다.
- `/api/v1/`에서 프런트엔드용 REST API를 제공하며, JWT 기반 인증과 기존 그누보드 회원 호환 기능을 포함합니다.
- Django 관리자에서 테마를 선택하고(`/admin/theme/`), 데모용 샘플 콘텐츠를 추가·삭제할 수 있습니다(`/admin/sample-data/`).
- Next.js 프런트엔드는 커뮤니티·쇼핑몰 테마와 매뉴얼 테마를 제공하며, 정적 테마 빌드와 독립 서버 실행을 지원합니다.

## 데모

- 커뮤니티·쇼핑몰 테마: [gnu-jango-demo.vercel.app](https://gnu-jango-demo.vercel.app/)
- 매뉴얼 테마: [gnu-jango-handbook.vercel.app](https://gnu-jango-handbook.vercel.app/)
- PythonAnywhere 데모: [thisgun.pythonanywhere.com](https://thisgun.pythonanywhere.com/)

## 현재 구성

| 구분 | 구성 |
|---|---|
| 백엔드 | Python 3.12 (`.python-version`, CI와 Docker 기준), Django 6.1.2, Django REST Framework |
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

### 주요 Django 앱

| 앱 | 역할 |
|---|---|
| `bbs` | 게시판·게시글·댓글 |
| `users` | 회원과 그누보드 호환 인증 |
| `shop` | 영카트 쇼핑몰 |
| `config` | 그누보드 환경설정 |
| `api` | `/api/v1/` REST API와 인증·쇼핑몰 API |
| `core` | 공통 기능, 배포 점검, 예약 작업 |

## Django 로컬 실행

Python 3.12를 사용합니다. Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS 또는 Linux:

```bash
python3.12 -m venv .venv
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

린트·테스트 도구(ruff, selenium, tox 등)가 필요하면 개발 의존성도 설치합니다. 운영 서버에는 설치하지 않아도 됩니다.

```bash
python -m pip install -r requirements-dev.txt
```

## 기존 그누보드 데이터 가져오기

`migrate_gnuboard5`는 원본 그누보드의 `data/dbconfig.php`를 읽어 MySQL 데이터를 Django 데이터베이스로 가져옵니다. 기본 실행은 가져올 항목과 건수를 확인하는 점검 모드이며, 실제 쓰기는 `--apply`를 지정해야 합니다.

```powershell
python manage.py migrate_gnuboard5 --source-root "<그누보드5 설치 경로>"
python manage.py migrate_gnuboard5 --source-root "<그누보드5 설치 경로>" --apply
```

`<그누보드5 설치 경로>`는 `data/dbconfig.php`가 들어 있는 그누보드 폴더입니다(예: Windows XAMPP는 `C:\xampp\htdocs\gnuboard5`, Linux는 `/var/www/gnuboard5`). 실제 DB에 적용하기 전에 대상 DB를 백업하고, 점검 모드 출력으로 가져올 테이블과 행 수를 확인하세요.

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

Vercel 프런트엔드와 별도 Django API 서버를 함께 사용하는 프록시·크로스도메인 인증 설정은 [Next.js 안내](nextjs/README.md)의 **Cross-Domain Authentication** 절을 참고하세요.

## 테마 빌드와 관리자 설정

`nextjs/`에서 빌드하면 Django가 사용하는 테마 파일을 함께 갱신합니다.

```bash
cd nextjs
npm run build:theme                 # nextjs_default
npm run build:theme:handbook         # handbook
```

산출물은 `gnu_jango/templates/theme/`와 `gnu_jango/templates/theme_static/`에 저장됩니다. Django 관리자에서 `/admin/theme/`으로 테마를 선택하고, `/admin/sample-data/`에서 샘플 콘텐츠를 추가하거나 삭제할 수 있습니다. 테마 설치·복구 절차는 [테마 배포 안내](docs/04-deploy/nextjs-default-theme.md)에 있습니다.

프런트엔드 소스 폴더는 `nextjs/`, 새 기본 테마 산출물은 `nextjs_default`입니다. 기존 사이트 설정과 주소의 호환성을 위해 `nextjs25` 이름이 일부 저장값·URL·배포 자료에 남아 있으며, 새 빌드가 사용하는 소스 폴더와는 구분됩니다. 테마 전환의 배경과 호환 규칙은 [테마 플랜](docs/01-plan/features/nextjs-default-theme.plan.md)과 [PRD](docs/01-plan/features/nextjs-default-theme.prd.md)를 참고하세요.

## 배포 방식

| 방식 | 구성 | 안내 |
|---|---|---|
| Vercel + Supabase | Django Python 함수, Supabase PostgreSQL·Storage, 공유 캐시와 Vercel Cron | [배포 프로필](docs/04-deploy/deployment-profiles.md), [환경변수 예시](deploy/env/vercel-supabase.env.example) |
| VPS | Docker Compose의 Django, PostgreSQL, Redis, Celery 작업자·Beat; 또는 기존 운영 서버 구성 | [배포 프로필](docs/04-deploy/deployment-profiles.md), [환경변수 예시](deploy/env/vps.env.example) |
| 분리형 | VPS의 Django API와 별도 Node 기반 Next.js 프런트엔드 | [배포 프로필](docs/04-deploy/deployment-profiles.md), [환경변수 예시](deploy/env/split-api.env.example) |
| PythonAnywhere | Django와 저장소에 포함된 빌드 테마를 사용하는 가벼운 데모 | [아래 설치·업데이트 안내](#pythonanywhere에-데모-올리기) |

### PythonAnywhere에 데모 올리기

이 절차는 **새 PythonAnywhere 계정에 GNU Jango 데모를 올리는 방법**입니다. PythonAnywhere의 Web 앱은 Django WSGI 서버로 실행합니다. Next.js 개발 서버를 PythonAnywhere에서 실행하지 않아도 됩니다. 저장소의 `gnu_jango/templates/theme/`와 `gnu_jango/templates/theme_static/`에 포함된 빌드 결과를 Django가 제공합니다.

PythonAnywhere 무료 계정의 현재 공개 한도는 CPU 100초, 디스크 512 MiB, 웹 앱 1개(작업자 1개, 한 달 만료)입니다. 패키지가 많은 프로젝트라 디스크 한도를 넘을 수 있고, 만료 전에 대시보드에서 웹 앱을 갱신해야 할 수 있습니다. 요금제와 한도는 바뀔 수 있으므로 [PythonAnywhere 무료 계정 안내](https://help.pythonanywhere.com/pages/FreeAccountsFeatures/)를 먼저 확인하세요. 무료 계정은 학습과 데모용으로만 사용하고, 실제 결제나 민감한 회원 정보를 처리하는 운영 사이트로 쓰지 마세요.

#### 1. 저장소 복제 및 가상환경 준비

PythonAnywhere 대시보드의 **Consoles → Bash**에서 다음 명령을 실행합니다. PythonAnywhere의 웹 앱과 가상환경은 같은 Python 버전을 사용해야 합니다. 이 프로젝트 기준은 Python 3.12입니다.

```bash
cd ~
git clone https://github.com/thisgun/gnu-jango.git
cd ~/gnu-jango
mkvirtualenv --python=python3.12 gnu-jango
workon gnu-jango
python -m pip install --upgrade pip
python -m pip install -r requirements-pythonanywhere.txt
```

PythonAnywhere는 `MEDIA_STORAGE=local`을 사용하므로 S3 전용 `boto3`와 `django-storages`를 설치하지 않습니다. Vercel은 자동 빌드 호환성을 위해 루트의 `requirements.txt`를 계속 사용합니다. 패키지 설치가 디스크 한도나 빌드 오류로 실패하면 무작정 패키지를 빼지 말고 Bash 콘솔의 오류와 사용량을 확인하세요. 현재 무료 계정 용량으로 설치가 끝나지 않는다면 더 큰 용량을 제공하는 실행 환경이 필요합니다.

#### 2. 운영 설정 파일 만들기

프로젝트 루트의 `.env` 파일을 PythonAnywhere **Files** 화면에서 만들거나 편집합니다. `<username>`은 PythonAnywhere 계정 이름으로 바꾸고, `SECRET_KEY`에는 아래 명령이 출력한 값을 넣습니다. `.env`를 GitHub에 올리면 안 됩니다.

```bash
cd ~/gnu-jango
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

데모용으로는 PythonAnywhere 디스크에 저장하는 SQLite를 사용할 수 있습니다. `.env`에 다음 값을 넣습니다.

```dotenv
ENVIRONMENT=Production
DEBUG=False
SECRET_KEY=여기에_새로_생성한_비밀키
ALLOWED_HOSTS=<username>.pythonanywhere.com
CSRF_TRUSTED_ORIGINS=https://<username>.pythonanywhere.com
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=/home/<username>/gnu-jango/db.sqlite3
MEDIA_STORAGE=local
MEDIA_ROOT=/home/<username>/gnu-jango/media
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
```

`EMAIL_BACKEND` 줄을 빼면 운영 설정이 SMTP 메일 서버(`EMAIL_HOST`)를 요구해 Django가 시작하지 않습니다. 위 값은 메일을 보내지 않고 로그(Web 탭의 **Server log**)에만 남깁니다. 실제로 메일을 보내려면 이 줄 대신 `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL`을 설정하세요. 무료 계정은 바깥 연결이 제한되므로 외부 SMTP가 막힐 수 있습니다.

`SECRET_KEY`를 저장소의 예시 값 그대로 두지 마세요. 데이터베이스와 업로드 파일은 PythonAnywhere 계정의 디스크에 저장되므로, 중요한 데이터의 백업과 외부 미디어 저장소가 필요한 운영 서비스에는 적합하지 않습니다.

#### 3. PythonAnywhere Web 앱 연결

대시보드에서 **Web → Add a new web app → Manual configuration → Python 3.12**를 선택합니다. 이 저장소의 `manage.py`가 있는 폴더가 프로젝트 루트입니다. Web 설정에서 **Source code**와 **Working directory**를 `/home/<username>/gnu-jango`로 지정하고, **Virtualenv**에는 `gnu-jango`를 입력합니다.

Web 탭의 Code 영역에서 PythonAnywhere가 만든 **WSGI configuration file**을 열어 Django 부분을 다음처럼 설정합니다. 저장소의 `example/wsgi.py`가 아니라 Web 탭에 연결된 WSGI 파일을 편집해야 합니다.

```python
import os
import sys

path = "/home/<username>/gnu-jango"
if path not in sys.path:
    sys.path.insert(0, path)

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "example.settings")
os.environ.setdefault("ENVIRONMENT", "Production")

from django.core.wsgi import get_wsgi_application

application = get_wsgi_application()
```

#### 4. 데이터베이스와 데모 콘텐츠 준비

Bash 콘솔에서 가상환경을 켜고 프로젝트의 데이터베이스 테이블과 정적 파일을 준비합니다.

```bash
workon gnu-jango
cd ~/gnu-jango
mkdir -p media
python manage.py check
python manage.py migrate
python manage.py collectstatic --noinput
```

관리자 계정은 `python manage.py createsuperuser`로 만들 수 있습니다. 게시판·상품 샘플을 원하면 `python manage.py ensure_demo_samples --apply`, 매뉴얼 책과 장을 원하면 `python manage.py ensure_handbook_samples`를 실행하세요. 샘플 명령은 이미 있는 샘플을 중복으로 만들지 않도록 설계되어 있습니다.

#### 5. 정적 파일 연결 후 접속 확인

Web 탭의 **Static files**에 다음 매핑을 추가합니다. `<username>`은 실제 계정 이름으로 바꾸고 저장한 뒤 **Reload**를 누릅니다.

| URL | Directory |
|---|---|
| `/static/` | `/home/<username>/gnu-jango/staticfiles` |
| `/media/` | `/home/<username>/gnu-jango/media` |

`MEDIA_STORAGE=local`로 설정한 데모에서만 `/media/` 매핑을 추가하세요. `https://<username>.pythonanywhere.com/`과 `/admin/`을 열어 확인합니다. CSS가 빠지면 `collectstatic` 실행 여부와 Web 탭의 `/static/` 경로를 확인하세요. 오류 원인은 Web 탭의 **Error log**에서 확인할 수 있습니다. Django의 WSGI·가상환경·정적 파일 설정은 [기존 Django 프로젝트 배포 안내](https://help.pythonanywhere.com/pages/DeployExistingDjangoProject/), [가상환경 안내](https://help.pythonanywhere.com/pages/VirtualEnvForWebsites/), [정적 파일 안내](https://help.pythonanywhere.com/pages/DjangoStaticFiles/)를 참고하세요.

Next.js 테마의 `/_next/static/` 파일은 Django가 저장소의 빌드 디렉터리에서 직접 제공합니다. `collectstatic`은 관리자 화면과 일반 Django 정적 파일만 모으도록 구성되어 있어 테마 파일을 다시 복제하지 않습니다. 이전 버전에서 정적 파일 용량이 커졌다면 저장소를 갱신한 뒤 한 번만 다음 명령으로 전용 `staticfiles` 폴더를 정리하세요. 이 명령은 `STATIC_ROOT`의 기존 파일을 지우고 다시 모으므로, 해당 폴더에 수동 파일을 따로 저장하지 않았는지 먼저 확인하세요. `media/` 파일에는 영향을 주지 않습니다.

```bash
python manage.py collectstatic --clear --noinput
```

#### 코드 업데이트하기

새 버전을 배포할 때는 Bash 콘솔에서 저장소를 갱신하고, 마이그레이션과 정적 파일을 적용한 뒤 Web 탭에서 Reload를 누릅니다. `requirements-pythonanywhere.txt` 또는 `requirements-base.txt`가 바뀐 경우에만 `python -m pip install -r requirements-pythonanywhere.txt`를 실행합니다. 루트 `requirements.txt`의 S3 패키지만 바뀌었다면 PythonAnywhere 가상환경은 갱신할 필요가 없습니다.

```bash
workon gnu-jango
cd ~/gnu-jango
git pull --ff-only origin main
python manage.py migrate
python manage.py collectstatic --noinput
```

샘플 매뉴얼의 새 장을 반영하려면 `python manage.py ensure_handbook_samples`도 실행합니다. 이미 있는 샘플 장의 고쳐진 문구까지 반영하려면 `--refresh`를 붙이세요(샘플 장 제목을 가진 글의 본문을 다시 씁니다). 테마 소스를 바꾼 경우에는 로컬에서 테마를 빌드하고 생성 결과 두 폴더를 함께 Git에 올려야 합니다. PythonAnywhere에서는 Next.js `npm run dev`가 아니라 Django Web 앱을 실행합니다.

무료 계정의 웹 앱은 한 달 뒤 멈춥니다. 만료 전에 Web 탭의 연장 버튼을 눌러야 하며, 사이트를 주기적으로 호출하는 것만으로는 연장되지 않습니다.

화면을 보며 따라 하고 싶다면 [GNU Jango 핸드북](https://gnu-jango-handbook.vercel.app/)의 **개발과 배포 → 서버에 올리기 → PythonAnywhere에 올리기** 장을 참고하세요.

### Docker Compose

Docker Compose는 `.env`의 `SECRET_KEY`를 요구하고, 웹 컨테이너 시작 때 마이그레이션을 적용합니다. 로컬 컨테이너를 실행하려면 비밀값을 설정한 뒤 다음 명령을 사용합니다.

```bash
docker compose up --build
```

### Vercel 참고 사항

Vercel 프로젝트는 저장소 루트를 기준으로 설정합니다. 테마 빌드 결과를 바꿨다면 두 테마 디렉터리의 산출물을 함께 커밋해야 합니다. 별도 handbook 데모처럼 같은 브랜치에 연결된 Vercel 프로젝트가 여러 개면 `main` 푸시가 모두 배포를 시작합니다. handbook 프로젝트의 테마 기본값과 DB 준비는 [handbook 데모 안내](docs/04-deploy/handbook-demo.md)를 참고하세요.

### 공통 운영 점검

어느 배포 방식이든 운영 배포 전에 환경 변수 예시의 자리표시자를 실제 설정으로 바꾸고, 프로필 점검을 실행합니다.

```bash
python manage.py check_deploy_profile --profile vps
python manage.py check_release_readiness
```

Vercel을 점검할 때는 프로필을 `vercel`로 바꾸세요. 지원 프로필은 `vps`, `vercel`, `split`입니다. PG·소셜 로그인·본인인증 연동은 각 공급자의 테스트 키와 callback 설정이 있어야 동작합니다. 비밀 키를 Git에 넣지 말고 `.env.example`과 `deploy/env/`의 예시를 참고하세요.

전체 운영 점검에는 엄격한 프로덕션 기준을 적용할 수 있습니다.

```bash
python manage.py check_release_readiness --strict-production
```

원본 그누보드 이미지·첨부파일을 복구한 경우 `.env`의 `LEGACY_GNUBOARD5_SOURCE_ROOTS`에 원본 루트 경로를 지정하고 자산을 동기화한 뒤 누락 여부를 확인합니다.

```bash
python manage.py sync_gnuboard_assets --apply
python manage.py audit_gnuboard_assets --fail-on-unserved
```

PG·소셜 로그인·본인인증의 운영 키와 callback 설정은 별도 점검 명령으로 확인할 수 있습니다.

```bash
python manage.py audit_external_integrations --fail-on-missing
```

`--strict-production`은 운영 배포에 필요한 설정과 자산의 누락을 찾아 알립니다. PG·소셜 로그인·본인인증 항목은 실제 공급자 키와 callback 설정을 준비한 뒤 외부 연동 점검도 실행하세요.

## 통합 검색

사이트 검색(`/search`)에서 게시글·상품·문서와 매뉴얼을 함께 찾을 수 있습니다. 한국어 형태소 분석기 Kiwi가 설치되어 있으면 재사용하고, 없으면 내장 한글 2-gram 분석기로 동작합니다. PostgreSQL은 GIN 전문 검색 인덱스를, SQLite는 토큰 역색인을 사용하므로 별도 검색 서버나 Celery worker가 필요하지 않습니다.

업데이트 뒤 **각 사이트가 사용하는 DB**에 마이그레이션과 최초 재색인을 실행하세요.

```bash
python manage.py migrate
python manage.py rebuild_search_index
```

일반 저장·삭제는 색인을 자동 갱신합니다. 대량 import, `bulk_create`, `QuerySet.update`, Kiwi 설치·제거 뒤에는 재색인이 필요합니다. 한 종류만 다시 만들려면 `--kind post`, `--kind product`, `--kind page`를 사용합니다. 최초 재색인 전에는 통합 검색에 준비 안내와 기존 게시판 검색 링크가 표시되며, 기존 게시판·상품 검색 API는 계속 동작합니다.

PostgreSQL에서 영문 오타 등 유사한 제목도 찾으려면 DB 확장 설치 권한이 있는 계정으로 아래 명령을 실행하고 `G5_SEARCH_TRIGRAM=True`를 설정합니다. 기본 검색에는 이 확장이 필요하지 않습니다.

```bash
python manage.py configure_search_postgres
```

통합 API는 `GET /api/v1/search/unified?q=입금확인&type=all`입니다. `type`은 `all`, `post`, `product`, `document`를 지원합니다. 기존의 특정 게시판·작성자 검색은 유지됩니다. 검색 결과의 관련도 보정에는 최근 인기어와 일별 클릭 집계를 사용하며, 클릭 집계에는 질문 원문·사용자 ID·IP를 저장하지 않습니다. `G5_SEARCH_CLICK_LOG_ENABLED=False`로 클릭 수집을 끌 수 있고, 오래된 집계는 `python manage.py cleanup_search_clicks --days 90`으로 정리합니다.

전체 운영 절차와 성능·검색 범위의 제한은 [통합 검색 운영 안내](docs/04-deploy/unified-search.md), 요구사항은 [PRD](docs/01-plan/features/unified-search.prd.md), 구현 계획은 [계획서](docs/01-plan/features/unified-search.plan.md)를 참고하세요.

## 실시간 알림

댓글·수신 쪽지·회원 주문 상태 변경과 관리자 공지를 기존 알림함에 저장합니다.
관리자는 **공지 알림 발송** 메뉴(`/admin/core/notification/announce/`)에서 수신자를 선택해 보낼 수 있습니다.

Channels + Redis 전송은 선택 기능입니다. `requirements-realtime.txt` 설치, ASGI 서버,
`NOTIFICATION_WS_ENABLED`·Redis 주소·허용 Origin 설정이 필요하며 기본값은 꺼짐입니다.
실시간 전달에는 같은 설정의 `python manage.py process_notifications --apply --watch` 작업자가 필요합니다.
비활성 환경과 장애 중에는 REST 폴링을 유지합니다. 기존 WSGI Vercel/PythonAnywhere 설정은 그대로 사용할 수 있습니다.

설치·Docker 실행·인증 규격·Vercel 전환 조건은 [실시간 알림 가이드](docs/04-deploy/realtime-notifications.md)를 참고하세요.

## 백그라운드 작업

`BACKGROUND_JOBS_ENABLED=True`이면 메일·SMS·서버 결제 웹훅·이미지 변환을 DB 대기열에 저장하고 Celery 작업자가 처리합니다. Beat가 정기 유지보수 명령과 대기 작업 전달을 예약합니다. 기존 설치의 기본값은 `False`이며 Redis 없이 개발할 수 있습니다. 새 모드는 마이그레이션과 작업자·Beat 준비 후 켜세요. Docker Compose는 기본으로 새 모드를 사용합니다.

```bash
docker compose up -d --build web worker media-worker beat
docker compose logs -f worker media-worker beat
```

Docker Compose를 사용하지 않을 때는 웹과 같은 DB·스토리지·발송 설정을 적용하고 다음 프로세스를 각각 실행합니다. Beat는 하나만 실행합니다.

```bash
celery -A example worker -l INFO -Q celery,maintenance,communications,payments --concurrency=2
celery -A example worker -l INFO -Q media --concurrency=1 --hostname=media@%h
celery -A example beat -l INFO
```

관리자 **운영 → 백그라운드 작업 / 실패 큐**에서 최종 실패와 시도 횟수를 확인할 수 있습니다. Flower는 `FLOWER_BASIC_AUTH`를 별도로 설정한 뒤 `docker compose --profile monitoring up -d --build flower`로 실행하며 기본 주소는 `http://127.0.0.1:5555/`입니다.

재시도·타임아웃·실패 작업 재처리·이미지 처리 중 표시·Vercel 외부 작업자 구성은 [백그라운드 작업 운영 가이드](docs/04-deploy/background-jobs.md)를 참고하세요. 새 모드로 전환한 뒤에는 기존 cron 예약을 끄세요. 기존 `python manage.py run_scheduled_jobs`는 수동 점검과 이전 배포 구성을 위한 명령으로 유지합니다.

## 개발 점검

GitHub의 `main` 브랜치는 관리자도 직접 푸시할 수 없도록 보호됩니다. 변경사항은 PR로 올리고 `django`, `nextjs`, `theme-bundles`, `docker` 점검이 모두 통과한 뒤 병합하세요. PR의 기준 브랜치가 최신 상태여야 합니다.

백엔드 테스트:

```bash
python manage.py test gnu_jango --parallel auto
```

병렬 실행 중 테스트가 실패하면 실패한 테스트 대신 `cannot pickle 'traceback' object`만 보일 수 있습니다. 그럴 때는 `--parallel` 없이 다시 실행해 실패 내용을 확인하세요(시간은 더 걸립니다).

```bash
python manage.py test gnu_jango
```

프런트엔드 점검:

```bash
cd nextjs
npm run typecheck
npm run check:vercel-env:template
npm run check:theme-sync
```

개발용 게시글·회원 데이터가 필요하면 Faker 기반 관리 명령을 사용할 수 있습니다. 게시글을 만들기 전에 대상 게시판이 있어야 합니다.

```bash
python manage.py seed-posts --number=20 --bo_table=free
python manage.py seed-posts --number=20 --board_id=1
python manage.py seed-users --number=10
```

이 명령은 임의의 테스트 데이터를 현재 설정된 데이터베이스에 기록합니다. 운영 데이터베이스에서는 실행하지 마세요.

## 라이선스

라이선스와 포함된 제3자 구성요소 고지는 [LICENSE](LICENSE)와 [NOTICE](NOTICE)를 참고하세요.
