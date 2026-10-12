# GNU Jango

**GNU Jango**(`gnu_jango`)는 PHP 기반 게시판·쇼핑몰 솔루션인 **그누보드5(Gnuboard5)·영카트**를
**Django 6 + Django REST Framework**로 포팅한 프로젝트입니다. JWT 기반 REST API,
**Unfold** 관리자 테마, 그리고 별도의 **Next.js 프런트엔드**(`nextjs/`)로 구성됩니다.

## 주요 특징

- 그누보드5 데이터 모델 포팅 — 게시판(`bbs`), 회원(`users`), 환경설정(`config`), 영카트 쇼핑몰(`shop`) 등
- 그누보드5 비밀번호 해시 호환(`GnuboardPBKDF2SHA256` 등) — 기존 회원 DB 그대로 로그인 가능
- `migrate_gnuboard5` 관리 명령으로 기존 MySQL 데이터 이관
- `/api/v1` REST API + JWT(`djangorestframework-simplejwt`) 인증
- django-unfold 기반 관리자 + 커스텀 대시보드·리포트
- Next.js 25 프런트엔드(Vercel 배포 지원) — 크로스도메인 인증 포함

## 기술 스택

| 영역 | 사용 기술 |
|------|-----------|
| 백엔드 | Django 6.0, Django REST Framework, simplejwt |
| 관리자 | django-unfold |
| DB | SQLite(기본 개발) / PostgreSQL(CI·운영) · MySQL(레거시 마이그레이션) |
| 작업 큐 | Celery + Redis |
| 프런트엔드 | Next.js 15.5 (`nextjs/`) |
| 인증 | JWT(Bearer) + 그누보드5 호환 해시 |
| 배포 | Heroku · AWS Lightsail · CentOS/Ubuntu(Apache·nginx) · Vercel(프런트) |

## 프로젝트 구조

```text
gnu_jango/
├── gnu_jango/          # Django 프로젝트
│   ├── core/           # 메뉴·메일·방문로그·검색어·JWT 관리자 등
│   ├── users/          # 회원, 그누보드5 호환 인증
│   ├── config/         # 환경설정 (그누보드5 cf_*)
│   ├── bbs/            # 게시판 / 게시글 / 댓글
│   ├── shop/           # 영카트 쇼핑몰 포팅
│   ├── editor/         # 에디터
│   └── api/            # /api/v1 REST API (JWT)
├── example/settings/   # base / development / production 설정
├── nextjs/             # Next.js 프런트엔드 (별도 README)
└── requirements.txt
```

## 빠른 시작 (로컬)

이 프로젝트는 Python 3.12 이상을 사용합니다. CI는 Python 3.12에서 실행되고 현재 Windows 개발 환경은 Python 3.14를 사용합니다. 아래 명령은 CI와 같은 3.12 환경을 만듭니다. 다른 3.12 이상 버전을 사용할 때는 명령의 버전 번호를 설치된 버전으로 바꾸세요.

Windows PowerShell:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

macOS / Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

`.env`에 개발 환경과 새 비밀 키를 설정합니다. 비밀 키는 다음 명령으로 만들고 출력값을 `SECRET_KEY`에 넣으세요.

```bash
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

```dotenv
ENVIRONMENT=Development
DEBUG=True
SECRET_KEY=위에서_생성한_값
```

가상환경을 활성화한 터미널에서 Django를 준비하고 실행합니다.

```bash
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 127.0.0.1:8000
# 사이트:   http://127.0.0.1:8000/
# 관리자:   http://127.0.0.1:8000/admin/
```

> Windows에서 PowerShell 실행 정책 때문에 가상환경 활성화가 막히면, 명령 프롬프트(cmd)에서 `.venv\Scripts\activate.bat`을 실행하세요.

## 프런트엔드 / 크로스도메인 인증

Next.js 프런트엔드 환경설정과 **Vercel ↔ 별도 API 서버** 로그인 유지(프록시 모드)는
[`nextjs/README.md`](nextjs/README.md)의 *Cross-Domain Authentication* 섹션을 참고하세요.

### Next.js Default 테마 전환

프런트엔드 소스는 저장소 루트의 `nextjs/`에 있습니다. Django 기본 테마 산출물은
`gnu_jango/templates/theme/nextjs_default/`, 정적 자산은
`gnu_jango/templates/theme_static/nextjs_default/`에 생성되며 `nextjs/scripts/sync-static-theme.mjs`가
두 경로를 동기화합니다. `nextjs25`라는 이름은 기존 URL·Django reverse name·저장 설정을 위한 호환 별칭이고,
기존 `theme/nextjs25` 산출물도 이전 화면 복구를 위해 보존합니다. 요구사항과 작업 순서는 아래 문서를 따릅니다.

- [구현 플랜](docs/01-plan/features/nextjs-default-theme.plan.md)
- [제품 요구사항 문서(PRD)](docs/01-plan/features/nextjs-default-theme.prd.md)

## 운영 준비도 체크

운영 배포 전에는 Django, Next.js, 그누보드5 자산, PG·소셜·본인인증 연동 상태를 한 번에 확인합니다.

```bash
python manage.py check_release_readiness
python manage.py check_release_readiness --strict-production
```

`--strict-production`은 누락된 원본 첨부파일, 상품 이미지, 실결제 PG/OAuth/본인인증 설정, Vercel HTTPS 환경값이 남아 있으면 실패해야 정상입니다. 이 프로젝트의 기준 원본은 기본적으로 `C:\xampp824\www\gnuboard5_3`이며, 원본 백업이 여러 곳에 나뉘어 있으면 `.env`에 다음처럼 추가합니다.

```env
LEGACY_GNUBOARD5_SOURCE_ROOTS=C:\xampp824\www\gnuboard5_3,C:\backup\gnuboard5_data
```

원본 `data/file` 및 `data/item` 파일을 복구한 뒤에는 다음 순서로 자산 동기화와 검증을 수행합니다.

```bash
python manage.py sync_gnuboard_assets --apply
python manage.py audit_gnuboard_assets --fail-on-unserved
```

PG·소셜 로그인·본인인증은 `.env.example`의 `SHOP_*`, `SOCIAL_*`, `GNUBOARD_CERT_*` 값을 실제 계약 정보로 채운 뒤 아래 명령으로 확인합니다.

```bash
python manage.py audit_external_integrations --fail-on-missing
```

## 백그라운드 작업 큐

메일 캠페인과 오래 걸리는 운영 작업은 Celery로 실행합니다. 로컬 개발 환경은 기본적으로 eager 모드라 Redis 없이도
`python manage.py runserver`만으로 관리자 메일 테스트가 동작하고, Docker/운영 환경은 Redis와 별도 worker 프로세스를 사용합니다.

```bash
docker compose up --build
docker compose logs -f worker
```

Docker를 쓰지 않는 운영 환경에서는 Django 서버와 별도로 worker를 실행합니다.

```bash
celery -A example worker --loglevel=INFO
```

## 목차

- [윈도우에서 설치방법](#윈도우에서-설치방법)
- [무료호스팅에서 사용방법](#무료호스팅에서-사용방법)
- [Heroku](#heroku)
- [AWS Lightsail](#aws-lightsail)
- [CentOS 7 + Apache](#centos-7--apache)
- [Ubuntu + nginx](#ubuntu--nginx)
- [CentOS 7 + nginx](#centos-7--nginx)
- [Faker 더미 데이터](#faker-더미-데이터)

---

## 윈도우에서 설치방법

PowerShell에서 저장소 루트로 이동한 뒤 [빠른 시작](#빠른-시작-로컬)의 Windows 명령을 실행합니다. Python Launcher가 설치되어 있어야 합니다. `py -3.12 --version`으로 Python 3.12 설치 여부를 확인하세요. 다른 3.12 이상 버전을 쓰려면 가상환경 생성 명령의 `-3.12`를 해당 버전으로 바꿉니다.

가상환경을 활성화하고 `.env`에 `ENVIRONMENT=Development`, `DEBUG=True`, 새로 생성한 `SECRET_KEY`를 설정한 다음, `python manage.py migrate`와 `python manage.py createsuperuser`를 실행합니다. 개발 서버는 `python manage.py runserver 127.0.0.1:8000`으로 시작합니다. 모델 변경을 위한 `makemigrations`는 일반 설치 절차에서 실행하지 않습니다.

## 무료호스팅에서 사용방법

무료호스팅 목록

- pythonanywhere (https://www.pythonanywhere.com/)
- heroku (https://www.heroku.com/)

먼저 pythonanywhere에서 설치를 진행해 보자.

( 참고 url : https://eveningdev.tistory.com/52 )

pythonanywhere에서 Consoles 를 열고
git pull 을 받는다.
지금은 github의 저장소가 public이 아닌 private 상태이니, https 가 아닌 git@github.com주소로 연결한다.

- https://docs.github.com/en/authentication/connecting-to-github-with-ssh/generating-a-new-ssh-key-and-adding-it-to-the-ssh-agent
- https://docs.github.com/en/authentication/connecting-to-github-with-ssh/adding-a-new-ssh-key-to-your-github-account

위의 과정을 통해서 ssh키를 생성하여 github.com 에서 계정의 settings에 SSH and GPG keys 메뉴에서 New SSH key버튼을 눌러서 ssh 키를 등록하면

```
git clone git@github.com:gnuboard/gnu_jango_test.git
```

으로 pull 을 받을수 있다.

clone 이 되었다면 그 다음은 python 가상환경을 구성한다.

```
virtualenv --python=python3.9 venv
source venv/bin/activate
```

이렇게 하면 아래와 같은 경로로 가상환경구성 폴더가 생성된다.

```
/home/계정명/venv
```

source venv/bin/activate 명령어는 가상환경을 적용하는 명령어로 아래와 같이 경로 앞에 가상환경이름이 붙는다.

```
(venv) 01:15 ~ $
```

이제 gnu_jango_test 폴더로 이동하면

```
cd gnu_jango_test
(venv) 01:18 ~/gnu_jango_test (master)$
```

해당 폴더 안에 보면 .env.example 환경변수를 등록하는 파일이 있습니다.
.env.example 파일을 복사하여, 복사한 파일의 이름을 .env 수정하고 SECRET_KEY = 코드에 아무문자열을 10자리 이상 입력합니다.
.env 파일 설정을 하지 않으면 계속 오류로 실행될수 없으니, 반드시 .env 파일부터 설정해야 합니다.

이렇게 경로명이 되어 있는상태에서 ls 명령어로 현재경로에서 requirements.txt 파일이 있는지 확인한다.
requirements.txt 파일은 필요한 package 를 입력한 문서로 아래와 같은 명령어로 필요한 package 를 가상환경폴더에 설치한다.

```
pip install -r requirements.txt
```

package 설치가 완료 되었다면 아래 명령어로 migration 으로 db설치, 슈퍼관리자를 생성한다

```
python manage.py makemigrations
python manage.py migrate
python manage.py createsuperuser
```

슈퍼관리자를 생성시 아이디, 이메일, 비밀번호를 입력한다.

그 다음, bash 창 오른쪽 상단 Web / 파이썬 애니웨어 메인 페이지에서 Web을 버튼을 누른다.

- Add a new web app 클릭
- 수동 설정(manual configuration) 클릭
- 파이썬 최신버전 클릭(현재 기준 3.9)

서버환경을 구성하는 화면이 나오면

Code:
Working directory:
에서 경로는

```
/home/계정명/
```

으로 설정하며

WSGI configuration file: 텍스트 눌르면 해당 파일을 편집하는 창이 나오는데 아래와 같이 수정한다.

```
import os
import sys

path = '/home/계정명/gnu_jango_test'
if path not in sys.path:
    sys.path.append(path)

os.environ['DJANGO_SETTINGS_MODULE'] = 'example.settings'

from django.core.wsgi import get_wsgi_application
from django.contrib.staticfiles.handlers import StaticFilesHandler
application = StaticFilesHandler(get_wsgi_application())
```

그 다음
Virtualenv: 의 가상환경폴더의 경로는 아래와 같이 입력한다.

```
/home/계정명/venv
```

Static files: 는

URL Directory 를

```
/static/        /home/계정명/gnu_jango_test/gnu_jango/templates/
/media/         /home/thisgun/gnu_jango_test/media/
```

으로 설정한다.

위의 과정을 다 했다면 화면 상단의 Reload: 에서
Reload 계정명.pythonanywhere.com 버튼을 클릭하면 reload 가 되면서 서버를 재시작한다.

이제 http://계정명.pythonanywhere.com/ 으로 접속하여 글을 써보자.

## Heroku

### Setup

이 프로젝트에는 `app.json` 파일이 포함되어 있어 GitHub 저장소에서 Heroku 에서 앱을 만들 수 있습니다.

Heroku 에서는 고맙게도 GitHub 저장소가 Public 인 상태와 `app.json` 파일이 있으면,

아래 버튼을 눌러서 Heroku 에 호스팅을 생성할수 있습니다.

heroku.com 에 로그인 되어 있어야 합니다.

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy)

Heroku 에 호스팅을 생성하려면 위의 버튼을 눌러주세요.

## AWS Lightsail

Lightsail 에서 인스턴스를 생성합니다. 플랫폼은 Linux/Unix 으로 앱+OS 는 Django 로 선택합니다.
글을 쓰고 있는 현재 당시의 AWS Lightsail의 Django 는 Bitnami 에서 패키징 했으며, 해당 OS는 ubuntu, python버전은 3.8 이였습니다.

인스턴스를 생성했다면 먼저 aws을 방화벽을 확인합니다.
aws 에서 네트워킹 -> IPv6 네트워킹 에 포트 8000번을 추가합니다.

사용자는 기본사용자인 bitnami 로 실행합니다.

```
cd ~
mkdir projects
cd projects
```

가상환경을 생성하고 활성화합니다.

```
python3 -m venv venv
source venv/bin/activate
```

저장소 및 주요 디렉토리 생성 합니다

```
mkdir repo
cd repo
```

repo폴더 안에 git을 활성화하고 remote 주소를 추가합니다.

```
git init
git remote add origin git@github.com:gnuboard/gnu_jango_test.git
```

해당 폴더 안에 보면 .env.example 환경변수를 등록하는 파일이 있습니다.
.env.example 파일을 복사하여, 복사한 파일의 이름을 .env 수정하고 SECRET_KEY = 코드에 아무문자열을 10자리 이상 입력합니다.
.env 파일 설정을 하지 않으면 계속 오류로 실행될수 없으니, 반드시 .env 파일부터 설정해야 합니다.

아래 명령어로 django 설치와 필요한 패키지를 가상환경에 설치합니다.

```
pip install -r requirements.txt
```

데이터베이스 마이그레이션 합니다.

```
python manage.py makemigrations
python manage.py migrate
```

슈퍼관리자를 생성합니다.

```
python manage.py createsuperuser
```

외부로 연결할수 있게 서버를 실행합니다.

```
python manage.py runserver 0.0.0.0:8000
```

서버아이피:8000 포트로 접속 해봅니다.

```
http://서버퍼블릭아이피:8000
```

접속이 안된다면 aws 에서 네트워킹 -> IPv6 네트워킹 에 포트 8000 이 허용이 되어 있는지 확인합니다.
8000번 없다면 규칙추가 하여 8000번을 추가합니다.

잘 된다면 ctrl + c 버튼을 눌러서 실행을 종료합니다.

이제 uwsgi 로 잘 동작이 되는지 테스트합니다.

uwsgi 설치

```
pip install uwsgi
```

uwsgi 버전을 확인하여 잘 설치가 되었는지 확인합니다.

```
uwsgi --version
```

정적파일 데이터 모으기
해당 경로에 정적파일들이 생성되며 해당 폴더에 755권한을 줍니다.

```
python manage.py collectstatic
chmod 755 ./staticfiles
```

uwsgi 로 테스트해 봅니다.

```
uwsgi --http :8000 --home /home/bitnami/projects/venv/ --chdir /home/bitnami/projects/repo/ --module example.wsgi
```

잘 된다면 ctrl + c 버튼을 눌러서 실행을 종료합니다.

아래부터 사용자는 최고관리자인 root 계정으로 실행해야 합니다.

아래는 apache 와 wsgi 를 설정하는 방법입니다.

root 계정으로 아파치웹서버의 설정을 변경합니다.

```
su root
```

상세조회 명령어를 해서 bitnami 사용자로 생성한 프로젝트 폴더의 소유자와 그룹명이 bitnami bitnami 가 맞는지 확인합니다.

```
ls -al /home/bitnami/projects/repo
```

bitnami bitnami 가 아니라면 chown 명령어로 소유자 권한을 수정합니다.

```
chown -R bitnami:bitnami /home/bitnami/projects/repo
```

/opt/bitnami/apache/conf/vhosts 경로에 apache vhost 설정파일들이 있습니다. 해당 폴더안에 sample-https-vhost.conf.disabled 파일을 수정합니다.

```
vi sample-vhost.conf.disabled
vi /opt/bitnami/apache/conf/vhosts/sample-vhost.conf
```

아래와 같이 수정합니다.

```
<VirtualHost 127.0.0.1:80 _default_:80>
  ServerName 서버퍼블릭아이피

  WSGIDaemonProcess sample python-home=/opt/bitnami/python python-path=/home/bitnami/projects/venv/lib/python3.8/site-packages user=bitnami group=bitnami

  WSGIProcessGroup sample
  Alias /robots.txt /home/bitnami/projects/repo/staticfiles/robots.txt
  Alias /favicon.ico /home/bitnami/projects/repo/staticfiles/favicon.ico
  Alias /static/ /home/bitnami/projects/repo/staticfiles/
  <Directory /home/bitnami/projects/repo/staticfiles>
    Require all granted
  </Directory>
  Alias /media/ /home/bitnami/projects/repo/media/
  <Directory /home/bitnami/projects/repo/media>
    Require all granted
  </Directory>
  WSGIScriptAlias / /home/bitnami/projects/repo/example/wsgi.py
  <Directory /home/bitnami/projects/repo/example>
    <Files wsgi.py>
      Require all granted
    </Files>
  </Directory>
</VirtualHost>
```

저장 후에 해당 파일명 뒤에 .disabled 확장자가 .conf 확장자가 되게 파일명을 수정합니다.

```
mv sample-vhost.conf.disabled sample-vhost.conf
```

이제 아파치웹서버를 시작 또는 재시작합니다.

```
sudo /opt/bitnami/ctlscript.sh restart apache
```

서버아이피로 접속 해봅니다.

```
http://서버퍼블릭아이피
```

일어날수 있는 에러 :

Forbidden
You don't have permission to access this resource.

이렇게 메시지가 나온다면 반드시 apache 에러로그를 확인하여 조치 합니다.

```
vi /opt/bitnami/apache/logs/error_log
```

css 파일을 찾지 못하거나 이미지엑박이 뜨면 static을 지정한 staticfiles 폴더에 755권한을 줍니다.

```
chmod 755 /home/bitnami/projects/repo/staticfiles/
```

끝

## CentOS 7 + Apache

먼저 아래 패키지를 설치합니다.

```
yum install gcc openssl-devel postgresql-devel bzip2-devel libffi-devel epel-release -y
```

yum으로 파이썬3.8 버전 mod_wsgi 패키지와 apache를 설치합니다.

```
yum install epel-release centos-release-scl
yum install httpd httpd-devel rh-python38-mod_wsgi
```

파이썬 3.8 버전을 설치해야되는 이유가 있는데, python 3.9버전 이상부터는 mod_wsgi 수동설치가 너무 어려워서 쉽게 하려고 위에서 yum install rh-python38-mod_wsgi 이렇게 한것입니다.

rh-python38-mod_wsgi 을 설치폴더에서 mod_rh-python38-wsgi.so, 10-rh-python38-wsgi.conf 파일을 apache 폴더에 복사합니다.

```
sudo cp /opt/rh/httpd24/root/usr/lib64/httpd/modules/mod_rh-python38-wsgi.so /lib64/httpd/modules
sudo cp /opt/rh/httpd24/root/etc/httpd/conf.modules.d/10-rh-python38-wsgi.conf /etc/httpd/conf.modules.d
```

sqlite3 설치

sqlite3 --version 명령어를 해서 3.9.0 버전 이상이 아니면 새로 설치합니다.

```
cd /opt/
wget https://www.sqlite.org/2022/sqlite-autoconf-3390000.tar.gz
tar xvfz sqlite-autoconf-3390000.tar.gz
sudo mv sqlite-autoconf-3390000 /opt/sqlite3
cd /opt/sqlite3
./configure --prefix=/usr
make -j 2
sudo make install
```

설치가 잘 되었는지 아래 명령어로 sqlite3 버전이 3.39.0 인지 확인합니다.

```
sqlite3 --version
```

이제 python3.8 버전을 설치해야 합니다.

```
cd /opt/
wget https://www.python.org/ftp/python/3.8.13/Python-3.8.13.tgz
```

압축을 해제 후에 컴파일하고 설치합니다.

```
tar -xvf Python-3.8.13.tgz
cd Python-3.8.13/
./configure --enable-optimizations --enable-loadable-sqlite-extensions
make altinstall
```

python 3.8 실행파일 위치를 찾습니다.

```
which python3.8

/usr/local/bin/python3.8
```

기존의 python 에 심볼릭 링크를 걸면 yum이 안될수도 있으니, 기존의 python은 건들면 안됩니다.
alternatives 명령어로 python3 심볼릭 링크를 생성합니다.

```
alternatives --install /usr/bin/python3 python3 /usr/local/bin/python3.8 1
alternatives --set python3 /usr/local/bin/python3.8 && echo "2" | alternatives --config python
/usr/local/bin/python3.8 -m pip install --upgrade pip
alternatives --install /usr/bin/pip pip /usr/local/bin/pip3.8 1 && alternatives --set pip /usr/local/bin/pip3.8
```

다 했다면 python3 버전이 3.8.3으로 나오는지 확인합니다.

```
python3 --version
```

python --version 했을때 Python 2.7.5 라고 나오는 것은 고치면 안됩니다. 고치면 yum 이 안됩니다.

여기까지 했다면 이제 CENTOS에서 사용자를 추가하여 사이트를 실행합니다. (여기서는 gnu_user로 진행)
sudo useradd -m gnu_user
sudo passwd gnu_user

유저를 gnu_user 로 전환합니다.
su gnu_user

디렉토리를 사용자디렉토리로 이동합니다.

```
cd ~
```

django 프로젝트폴더를 추가합니다.

```
mkdir django
```

django 프로젝트폴더에 755권한을 준 후에 django 폴더로 이동합니다.

```
chmod 755 django
cd django
```

pwd로 프로젝트 디렉토리를 확인합니다. /home/gnu_user/django

```
pwd
```

가상환경 생성 및 진입 합니다.

```
cd /home/gnu_user/django
```

가상환경을 생성하고 활성화합니다.

```
python3 -m venv venv
source venv/bin/activate
```

가상환경으로 절대경로는
source /home/gnu_user/django/venv/bin/activate
가상환경을 활성화 하면 현재경로 앞에 (가상환경이름) 이 붙습니다
(venv) [gnu_user@localhost django]$

가상환경에서 빠져나가려면 deactivate 명령어로 나갈수 있습니다.

저장소 및 주요 디렉토리 생성

```
mkdir repo
cd repo
```

프로젝트를 git 으로 다운받습니다.

```
git init
git remote add origin git@github.com:gnuboard/gnu_jango_test.git
git pull origin master
```

해당 폴더 안에 보면 .env.example 환경변수를 등록하는 파일이 있습니다.
.env.example 파일을 복사하여, 복사한 파일의 이름을 .env 수정하고 SECRET_KEY = 코드에 아무문자열을 10자리 이상 입력합니다.
.env 파일 설정을 하지 않으면 계속 오류로 실행될수 없으니, 반드시 .env 파일부터 설정해야 합니다.

아래 명령어로 django 설치와 필요한 패키지를 가상환경에 설치합니다.

```
pip install -r requirements.txt
```

python 으로 실행되는 sqlite3 버전을 확인합니다.
python -c "import sqlite3 ; print(sqlite3.sqlite_version)"

3.7.17 이라고 뜬다면 옛날 버전이므로 위에서 설치한 sqlite 버전으로 변경합니다.

https://stackoverflow.com/questions/66380006/django-deterministic-true-requires-sqlite-3-8-3-or-higher-upon-running-python
를 참고하여

pip3로 해당패키지를 설치합니다.

```
pip3 install pysqlite3
pip3 install pysqlite3-binary
```

가상환경 venv 폴더에 파이썬3.8 설치경로에서 파일을 수정합니다.

```
vi /home/gnu_user/django/venv/lib/python3.8/site-packages/django/db/backends/sqlite3/base.py
```

# from sqlite3 import dbapi2 as Database # annotation

from pysqlite3 import dbapi2 as Database # import pysqlite3

이후 데이터베이스 마이그레이션 합니다.

```
python manage.py makemigrations
python manage.py migrate
```

정적파일 생성 모이기

```
python manage.py collectstatic
chomod 755 ./staticfiles
```

슈퍼관리자를 생성합니다.

```
python manage.py createsuperuser
```

외부로 연결할수 있게 서버를 실행합니다.
python manage.py runserver 0.0.0.0:8000

서버아이피:8000 포트로 접속 해봅니다.
http://외부서버아이피:8000

잘 된다면 ctrl + c 버튼을 눌러서 실행을 종료합니다.

uwsgi 로 잘 동작이 되는지 테스트합니다.
uwsgi 설치

```
pip install uwsgi
```

uwsgi 버전을 확인하여 잘 설치가 되었는지 확인합니다.

```
uwsgi --version
```

uwsgi 로 테스트해 봅니다.

```
uwsgi --http :8000 --home /home/gnu_user/django/venv/ --chdir /home/gnu_user/django/repo/ --module example.wsgi
```

서버아이피:8000 포트로 접속 해봅니다.
http://49.247.128.231:8000

스타일이 깨지거나 소스보기 해서 css 파일이나 js 파일 엑세스가 404 가 나온다면
staticfiles 폴더에 755 권한을 준 다음에 다시 collectstatic 을 실행합니다.

```
python manage.py collectstatic
chmod 755 ./staticfiles
```

잘 된다면 ctrl + c 버튼을 눌러서 실행을 종료합니다.

이제 root 계정으로 apache 설정을 합니다.

```
su root
```

apache를 설치합니다.

```
yum install httpd
```

apache를 시작프로그램에 등록합니다.

```
systemctl enable httpd
```

apache vhost conf 파일을 추가 및 편집합니다.

```
vi /etc/httpd/conf.d/gnu_user.conf
```

아래 내용을 참고하여 적절하게 편집합니다.

```
<VirtualHost *:80>
    # ServerName 도메인 또는 아이피       아래 예)
    ServerName 서버아이피 또는 서버도메인

    DocumentRoot /home/gnu_user/django/repo

    WSGIDaemonProcess hahahoho python-path=/home/gnu_user/django/venv/lib/python3.8/site-packages user=gnu_user group=gnu_user
    WSGIProcessGroup hahahoho
    WSGIScriptAlias / /home/gnu_user/django/repo/example/wsgi.py process-group=hahahoho

    # WSGIScriptAlias / /home/gnu_user/django/repo/example/wsgi.py
    <Directory /home/gnu_user/django/repo/example>
        <Files wsgi.py>
            AllowOverride none
            Require all granted
        </Files>
    </Directory>

    <Directory /home/gnu_user/django/repo/staticfiles>
        Require all granted
    </Directory>

    <Directory /home/gnu_user/django/repo/media>
        Require all granted
    </Directory>
</VirtualHost>
```

일어날수 있는 에러
Forbidden
You don't have permission to access this resource.

이렇게 메시지가 나온다면 반드시 apache 에러로그를 확인하여 조치 합니다. (거의 대부분이 권한문제입니다.)

```
vi /etc/httpd/logs/error_log
```

또는

```
tail -f /etc/httpd/logs/error_log
```

css 파일을 찾지 못하거나 이미지엑박이 뜨면 static을 지정한 staticfiles 폴더에 755권한을 줍니다.

```
chmod 755 /home/gnu_user/django/repo/staticfiles/
```

끝

## Ubuntu + nginx

apache로 설정하는것 보다 nginx로 설정하는것이 간편합니다.

```
sudo apt-get upgrade python3
python3 --version
apt install python3-pip
pip3 --version
```

아래 url을 참고하면 좋습니다. 아래 코드는 해당 url을 참고했습니다.
https://wikidocs.net/7421

가상환경 설치
sudo apt-get install python3-venv

postgresql 패키지 관련 설치
sudo apt-get install libpq-dev

사용자 생성후에 사용자로 로그인하여 django 폴더를 생성하고 django 폴더로 이동합니다.

```
sudo adduser 사용자이름
su 사용자이름
cd ~
mkdir django
cd django
```

가상환경을 생성하고 활성화한다.

```
python3 -m venv venv
source venv/bin/activate
```

저장소 및 주요 디렉토리 생성

```
mkdir repo run logs ssl
sudo chown 사용자이름:www-data run
```

프로젝트 폴더로 이동하여 프로젝트를 git 으로 다운받습니다.

```
cd repo
git init
git remote add origin git@github.com:gnuboard/gnu_jango_test.git
git pull origin master
```

먼저 requirements.txt 에 적힌 패키지를 설치합니다.

```
pip install -r requirements.txt
```

이후 데이터베이스 마이그레이션 합니다.

```
./manage.py makemigrations
./manage.py migrate
```

정적파일모으기

```
./manage.py collectstatic
```

슈퍼관리자를 생성합니다.

```
./manage.py createsuperuser
```

.env.example 파일을 복사하여 .env 파일로 이름을 바꾸고 .env 파일의 환경변수를 적절히 수정합니다.
SECRET_KEY 와 ALLOWED_HOSTS 반드시 수정해야 합니다.

```
cp .env.example .env
```

외부로 연결할수 있게 서버를 실행합니다.
./manage.py runserver 0.0.0.0:8000

잘 된다면 ctrl + c 버튼을 눌러서 실행을 종료합니다.

uwsgi 로 잘 동작이 되는지 테스트합니다.

uwsgi 설치

```
pip install uwsgi
```

uwsgi 로 테스트해 봅니다.
uwsgi --http :8000 --home /home/사용자이름/django/venv/ --chdir /home/사용자이름/django/repo/ --module example.wsgi

잘 동작된다면 가상환경을 deatviate 명령어로 빠져나옵니다.

시스템 전역 uWSGI 설치

```
sudo apt-get install python3-dev python3-pip python3-setuptools
sudo -H pip3 install --upgrade pip
sudo -H pip3 install wheel
sudo -H pip3 install uwsgi
```

서비스 등록 스크립트 생성

```
vi /etc/systemd/system/uwsgi.service
```

아래 내용으로 수정합니다.

```
[Unit]
Description=uWSGI Emperor service

[Service]
ExecStart=/usr/local/bin/uwsgi --emperor /etc/uwsgi/sites
Restart=on-failure
KillSignal=SIGQUIT
Type=notify
NotifyAccess=all
StandardError=syslog

[Install]
WantedBy=multi-user.target
```

uWSGI 옵션 파일

```
sudo mkdir -p /etc/uwsgi/sites
sudo vi /etc/uwsgi/sites/도메인.ini
```

```
[uwsgi]
uid = 사용자이름
base = /home/사용자이름/django/

home = %(base)/venv
chdir = %(base)/repo
module = example.wsgi:application
env = DJANGO_SETTINGS_MODULE=example.settings

master = true
processes = 5

socket = %(base)/run/uwsgi.sock
logto = %(base)/logs/uwsgi.log
chown-socket = %(uid):www-data
chmod-socket = 660
vacuum = true
```

uWSGI 서비스 등록

```
sudo systemctl start uwsgi
sudo systemctl enable uwsgi
```

uWSGI 서비스 구동 확인

```
sudo systemctl status uwsgi
```

만약 구동 실패시 에러 로그는 /var/log/syslog에서 확인할 수 있다.

파이썬 소스 코드 수정하면 uWSGI를 재기동해야 한다.

```
sudo systemctl restart uwsgi
```

nginx 설치

```
sudo apt-get install nginx
```

nginx conf 설정합니다.

```
vi /etc/nginx/sites-available/도메인.com
```

아래 내용을 참고하여 적절히 수정합니다.

```
upstream django {
    server unix:/home/사용자이름/django/run/uwsgi.sock;
}

server {
    listen 80;
    server_name 도메인;
    charset     utf-8;

    access_log /home/사용자이름/django/logs/access.log;
    error_log /home/사용자이름/django/logs/error.log;

    location = /favicon.ico { access_log off; log_not_found off; }

    location /static/ {
        root /home/사용자이름/django/repo;
        access_log   off;
        expires      30d;
    }

    location / {
        include         /etc/nginx/uwsgi_params;
        uwsgi_pass      django;
    }
}
```

NGINX 설정 문법 검사 및 재시작합니다.

```
sudo nginx -t
sudo systemctl restart nginx
```

## CentOS 7 + nginx

위에서 UBUNTU + nginx + django 로 실행하기 하는 방법과 거의 동일합니다.

## Faker 더미 데이터

게시글 추가하기 명령어

```
python manage.py seed-posts --number=숫자
```

게시글 추가하기 게시판 번호 지정 또는 게시판 bo_table 지정 명령어

```
python manage.py seed-posts --number=숫자 --board_id=숫자
```

또는

```
python manage.py seed-posts --number=숫자 --bo_table=문자
```

게시글 추가하기 카테고리 지정 명령어

```
python manage.py seed-posts --number=숫자 --ca_name=문자
```

유저 추가하기 지정 명령어

```
python manage.py seed-users --number=숫자
```

## 라이선스

GNU Jango는 (주)에스아이알소프트의 그누보드5·영카트(LGPL 2.1)를 옮긴 2차 저작물이므로 같은
**GNU Lesser General Public License 2.1 이상**으로 배포합니다. 전문은 [LICENSE](LICENSE), 원저작자와
포함된 서드파티 구성요소(jQuery, toastr, Font Awesome, TOAST UI Editor, CodeMirror 등)의 라이선스는
[NOTICE](NOTICE)를 보세요. 보안 문제는 공개 이슈 대신 [SECURITY.md](SECURITY.md)의 방법으로 알려 주세요.
