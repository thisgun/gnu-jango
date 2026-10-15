"""Beginner-friendly Korean articles used by the handbook demo manual."""

from html import escape
import re


# The marker lets ensure_handbook_samples refresh old demo text without replacing
# a chapter that an administrator has edited.
LEGACY_SAMPLE_MARKER = "이 장은 예시를 위한 샘플 글입니다."
_INLINE_CODE = re.compile(r"\{\{(.+?)\}\}")


GUIDES = {
    "이 안내서가 하는 일": {
        "intro": "처음 GNU Jango 매뉴얼을 보는 분을 위한 안내입니다. 사이트를 설치하고 글을 써 보는 운영자부터 코드를 수정하는 개발자까지 필요한 부분부터 골라 읽을 수 있습니다.",
        "sections": [
            {"heading": "이 사이트는 무엇인가요?", "paragraphs": [
                "GNU Jango는 그누보드5와 영카트에서 사용하던 게시판·회원·쇼핑몰 기능을 Django 백엔드와 Next.js 화면으로 제공하는 프로젝트입니다. Django는 데이터 저장, 권한 확인, 관리자 화면, API를 맡고 Next.js는 방문자가 보는 웹 화면을 맡습니다.",
                "이 매뉴얼 사이트도 별도의 문서 프로그램을 쓰지 않습니다. 게시판에 쓴 글을 책과 장처럼 보여 줍니다. 그래서 운영자는 익숙한 게시판 관리 방식으로 매뉴얼을 추가할 수 있습니다."
            ]},
            {"heading": "책·부·장은 어떻게 만들어지나요?", "bullets": [
                "매뉴얼 그룹 하나가 책들을 모아 둔 책장입니다. 이 사이트에서는 그룹 ID가 {{manual}}입니다.",
                "그룹 안의 게시판 하나가 책 한 권입니다. 예를 들어 {{hb_start}} 게시판이 처음 따라하기 책입니다.",
                "게시판 분류 하나가 책의 부입니다. {{시작 전}}, {{따라하기}} 같은 분류를 둡니다.",
                "게시글 하나가 한 장입니다. 제목이 장 제목이고 본문이 읽을 내용입니다."
            ]},
            {"heading": "어디서부터 읽으면 좋을까요?", "steps": [
                "프로그램 설치가 처음이면 왼쪽의 {{처음 따라하기}} 책을 위에서부터 읽습니다.",
                "화면이나 API 코드를 고치려면 {{개발자 안내서}}를 읽습니다.",
                "인터넷에 서비스를 올리려면 {{서버에 올리기}} 책을 읽고, 배포 전에 운영 점검 장을 확인합니다.",
                "모르는 용어는 부록에서 찾고, 화면 위 검색 버튼이나 {{Ctrl+K}}로 제목을 검색합니다."
            ], "note": "이곳의 내용은 설명용 데모입니다. 실제 서비스를 운영할 때는 사이트 관리자에게 받은 계정과 서버 설정을 사용하세요."}
        ]
    },
    "필요한 것": {
        "intro": "매뉴얼을 읽기만 한다면 별도 프로그램을 설치할 필요가 없습니다. 직접 실행해 보려면 아래 도구와 기본 개념을 준비하세요.",
        "sections": [
            {"heading": "처음 실행할 때 필요한 도구", "bullets": [
                "Git: 프로젝트 파일을 내려받고 변경 내역을 관리합니다.",
                "Python 3.13: Django 서버와 관리 명령을 실행합니다. 프로젝트 루트의 {{.python-version}}을 기준으로 버전을 맞춥니다.",
                "Node.js와 npm: {{nextjs/}} 폴더의 웹 화면을 실행하고 테마 파일을 만듭니다. 설치 버전은 저장소의 CI 설정과 Next.js 안내를 확인하세요.",
                "코드 편집기와 터미널: VS Code와 Windows PowerShell을 사용할 수 있습니다."
            ]},
            {"heading": "각 도구가 왜 필요한가요?", "paragraphs": [
                "Python과 Django는 회원·게시글·상품을 저장하는 서버입니다. Node.js는 Next.js 개발 서버와 빌드 도구를 실행합니다. 둘은 역할이 다르므로 로컬에서 프런트엔드까지 실행할 때는 보통 터미널 두 개를 사용합니다.",
                "처음에는 SQLite가 로컬 데이터베이스로 사용되므로 별도의 PostgreSQL 서버가 필요하지 않습니다. 운영 서버는 Vercel과 Supabase 또는 VPS처럼 별도 운영 환경을 사용합니다."
            ]},
            {"heading": "시작 전 확인", "steps": [
                "터미널에서 {{python --version}}을 실행해 Python 버전을 확인합니다.",
                "{{node --version}}과 {{npm --version}}으로 Node.js와 npm이 설치됐는지 확인합니다.",
                "저장소 루트에서 {{manage.py}}, {{requirements.txt}}, {{nextjs/package.json}} 파일이 보이는지 확인합니다."
            ], "code": "python --version\nnode --version\nnpm --version", "note": "프로젝트를 둘러보는 것과 결제·메일·실제 회원 데이터가 있는 운영 환경을 만드는 것은 다릅니다. 처음에는 로컬 SQLite와 데모 데이터만 사용하세요."}
        ]
    },
    "설치하기": {
        "intro": "아래 순서는 Windows PowerShell 기준입니다. 명령은 한 줄씩 실행하고, 오류가 나오면 다음 단계로 넘어가기 전에 오류 메시지를 읽습니다.",
        "sections": [
            {"heading": "1. Python 가상환경 만들기", "paragraphs": [
                "가상환경은 이 프로젝트가 사용하는 Python 패키지를 다른 프로젝트와 분리하는 폴더입니다. 저장소 루트에서 아래 명령을 실행합니다."
            ], "code": "py -3.13 -m venv .venv\n.\\.venv\\Scripts\\Activate.ps1\npython -m pip install -r requirements.txt"},
            {"heading": "2. 환경 설정과 데이터베이스 준비", "paragraphs": [
                "{{.env.example}}을 복사해 {{.env}}를 만듭니다. {{.env}}는 컴퓨터에만 보관하는 설정 파일이므로 Git에 올리면 안 됩니다. 개발용 {{SECRET_KEY}}는 아래 명령으로 새 값을 만든 뒤 {{.env}}에 직접 넣습니다.",
                "그 다음 데이터베이스 구조를 만들고 관리자 계정을 생성합니다. 관리자 계정은 로컬 사이트에서 게시판과 매뉴얼을 관리할 때 사용합니다."
            ], "code": "Copy-Item .env.example .env\npython -c \"from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())\"\npython manage.py migrate\npython manage.py createsuperuser"},
            {"heading": "3. 설치가 끝났는지 확인", "steps": [
                "개발 서버를 시작합니다: {{python manage.py runserver 127.0.0.1:8000}}.",
                "브라우저에서 {{http://127.0.0.1:8000/admin/}}을 열고 방금 만든 관리자 계정으로 로그인합니다.",
                "로그인 화면이 열리면 Django가 실행된 것입니다. 관리자 비밀번호를 잊었다면 새 슈퍼유저를 만들거나 개발 데이터베이스를 초기화하세요."
            ], "note": "PowerShell이 가상환경 활성화 스크립트를 차단하면 현재 사용자에 한해 실행 정책을 확인하거나 명령 프롬프트에서 {{.venv\\Scripts\\activate.bat}}을 사용하세요. 알 수 없는 정책을 무작정 낮추지는 마세요."}
        ]
    },
    "첫 화면 열기": {
        "intro": "이 프로젝트는 Django와 Next.js를 각각 실행할 수 있습니다. 처음에는 Django만 켜서 관리자와 기본 사이트를 확인하고, 프런트엔드 개발이 필요할 때 Next.js를 추가로 실행합니다.",
        "sections": [
            {"heading": "Django 사이트 열기", "steps": [
                "저장소 루트에서 가상환경이 켜져 있는지 확인합니다.",
                "{{python manage.py runserver 127.0.0.1:8000}}을 실행합니다. 터미널 창을 닫으면 서버도 멈춥니다.",
                "{{http://127.0.0.1:8000/}}은 공개 사이트, {{http://127.0.0.1:8000/admin/}}은 관리자입니다."
            ], "code": "python manage.py runserver 127.0.0.1:8000"},
            {"heading": "핸드북 테마와 샘플 책 표시하기", "paragraphs": [
                "사이트가 다른 테마를 보여 주면 관리자에서 테마 설정으로 이동해 {{Handbook (매뉴얼)}}을 선택합니다. 핸드북 테마 화면 설정에서 매뉴얼 게시판 그룹으로 {{manual}}을 선택해야 책 목록을 찾을 수 있습니다.",
                "샘플 책이 아직 없다면 개발 데이터베이스에서 {{python manage.py ensure_handbook_samples}}를 한 번 실행합니다. 이 명령은 그룹 {{manual}}과 {{hb_*}} 샘플 게시판을 만들고, 매뉴얼 그룹 설정도 지정합니다."
            ], "code": "python manage.py ensure_handbook_samples"},
            {"heading": "Next.js 화면도 실행하기", "paragraphs": [
                "독립 Next.js 프런트엔드는 별도 터미널에서 실행합니다. {{nextjs/.env.example}}을 복사해 {{nextjs/.env.local}}을 만들고 Django API 주소를 설정하세요. 개발 중에는 이 서버가 {{http://localhost:3000/}}에서 열립니다."
            ], "code": "Set-Location nextjs\nnpm ci\nCopy-Item .env.example .env.local\n$env:G5_NEXT_RUNTIME = 'server'\nnpm run dev", "note": "포트 8000은 Django, 포트 3000은 Next.js입니다. 주소가 열리지 않으면 두 서버가 모두 실행 중인지, 터미널에 오류가 없는지 먼저 확인하세요."}
        ]
    },
    "글 써 보기": {
        "intro": "매뉴얼 장은 게시글로 작성합니다. 따라서 게시판 관리 화면을 이미 사용할 줄 안다면 새로운 문서 도구를 배울 필요 없이 매뉴얼을 만들 수 있습니다.",
        "sections": [
            {"heading": "먼저 샘플 매뉴얼을 준비합니다", "paragraphs": [
                "개발 서버에서 {{python manage.py ensure_handbook_samples}}를 실행하면 네 권의 샘플 책과 기본 장이 만들어집니다. 명령을 다시 실행해도 기존 장을 중복 생성하지 않습니다."
            ], "code": "python manage.py ensure_handbook_samples"},
            {"heading": "새 책과 장을 추가하는 순서", "steps": [
                "관리자에 로그인하고 게시판 그룹에서 매뉴얼 그룹을 확인합니다. 화면 설정의 매뉴얼 그룹 값도 같은 그룹 ID를 가리켜야 합니다.",
                "그룹 안에 게시판을 하나 만듭니다. 게시판 하나가 책 한 권입니다. 예를 들어 제목을 {{처음 따라하기 · 내 사이트 운영}}처럼 쓰면 안내 문구와 책 이름으로 나뉩니다.",
                "게시판의 분류 목록에 {{준비}}, {{따라하기}}, {{문제 해결}}을 순서대로 입력합니다. 분류가 매뉴얼의 부 제목으로 나타납니다.",
                "게시판에서 새 글을 작성합니다. 글 제목은 장 제목, 글 본문은 장 내용입니다. 글의 분류를 지정하면 해당 부 아래에 표시됩니다.",
                "저장한 뒤 핸드북 화면에서 책을 열어 제목, 목차, 이전·다음 장 순서가 맞는지 확인합니다."
            ]},
            {"heading": "초보자가 따라 하기 쉬운 글 형식", "bullets": [
                "먼저 이 장에서 무엇을 할 수 있는지 한두 문장으로 설명합니다.",
                "필요한 계정·프로그램·권한을 작업 전에 적습니다.",
                "한 단계에 한 가지 행동만 쓰고, 클릭할 메뉴와 입력할 값을 정확히 적습니다.",
                "명령어는 복사 가능한 코드 상자에 넣고, 실행 위치와 기대 결과를 설명합니다.",
                "마지막에는 완료 확인 방법과 자주 발생하는 오류의 해결 순서를 적습니다."
            ], "note": "샘플 매뉴얼 삭제 명령은 개발용 샘플 그룹과 게시글을 삭제합니다. 실제 사이트에서는 신중히 사용하고, 일반 매뉴얼은 관리자에서 직접 편집하세요."}
        ]
    },
    "이름과 색 바꾸기": {
        "intro": "사이트 이름과 매뉴얼 책장은 데이터 설정으로 바꾸고, 색상과 글꼴 같은 화면 디자인은 테마 CSS에서 바꿉니다. 두 설정은 위치가 다릅니다.",
        "sections": [
            {"heading": "사이트 이름과 매뉴얼 그룹", "paragraphs": [
                "관리자에서 사이트 환경설정의 사이트 제목을 바꾸면 브라우저 제목이나 기본 사이트 정보에 반영됩니다. 핸드북 테마 설정에서는 사용할 게시판 그룹, 책별 안내 문구, 사이드바 표시 내용을 조정합니다.",
                "새 데이터베이스에서 첫 실행 기본값을 정할 때는 {{G5_DEFAULT_THEME=handbook}}과 {{G5_DEFAULT_DOCS_GROUP=manual}}을 사용합니다. 관리자에 저장된 설정이 있으면 저장된 값이 기본값보다 우선합니다."
            ]},
            {"heading": "테마 색상을 바꾸는 위치", "paragraphs": [
                "핸드북 색상은 {{nextjs/themes/handbook/theme.tokens.css}}와 다크 모드 파일 {{theme.dark.css}}에서 관리합니다. 공통 디자인은 {{theme.css}}와 {{theme.pages.css}} 등으로 나뉩니다.",
                "먼저 색상 토큰을 바꾸면 여러 화면의 같은 색 역할이 함께 바뀝니다. 특정 페이지 CSS에 색을 직접 반복해서 넣으면 나중에 전체 색을 바꾸기 어려워집니다."
            ], "steps": [
                "원하는 색이 로고·강조 버튼·배경 중 어떤 역할인지 정합니다.",
                "{{theme.tokens.css}}에서 해당 역할의 색상 변수를 찾습니다.",
                "라이트 모드와 다크 모드에서 글자와 배경의 대비를 각각 확인합니다.",
                "테마를 빌드한 뒤 화면 크기와 다크 모드를 바꾸어 확인합니다."
            ], "code": "cd nextjs\nnpm run build:theme:handbook\nnpm run check:theme-sync:handbook"},
            {"heading": "주의할 점", "bullets": [
                "테마 색을 바꿔도 게시판 글이나 상품 데이터는 바뀌지 않습니다.",
                "운영 환경에서는 파일을 수정해도 새 빌드와 배포가 끝나기 전까지 방문자에게 보이지 않을 수 있습니다.",
                "색만 바꾸는 작업에서는 새 비밀키나 데이터베이스 설정을 만들 필요가 없습니다."
            ]}
        ]
    },
    "개발 환경": {
        "intro": "개발 환경은 코드를 바꾸고 결과를 바로 확인하는 개인용 실행 공간입니다. 실제 방문자가 사용하는 운영 사이트와 데이터베이스를 혼동하지 않는 것이 가장 중요합니다.",
        "sections": [
            {"heading": "두 서버의 역할", "bullets": [
                "Django 서버({{127.0.0.1:8000}}): 관리자, 데이터베이스, API를 제공합니다.",
                "Next.js 서버({{localhost:3000}}): 화면을 빠르게 다시 그려 주는 프런트엔드 개발 서버입니다.",
                "SQLite: 처음 설치했을 때 사용하는 로컬 개발 데이터베이스입니다. 별도 서버 없이 파일로 저장됩니다."
            ]},
            {"heading": "안전한 개발 순서", "steps": [
                "저장소를 내려받고 Python 가상환경을 활성화합니다.",
                "Django 의존성을 설치하고 {{.env}}에 개발용 설정만 둡니다.",
                "마이그레이션을 적용한 뒤 Django를 실행합니다.",
                "프런트엔드 작업을 할 때만 두 번째 터미널에서 {{npm ci}}와 {{npm run dev}}를 실행합니다.",
                "수정한 화면과 API를 로컬에서 확인하고, 승인된 경우에만 Git에 커밋합니다."
            ]},
            {"heading": "운영 데이터와 섞이지 않게 하기", "paragraphs": [
                "운영 데이터베이스 주소 {{DATABASE_URL}}, Storage 키, 결제 키를 로컬 {{.env}}에 복사하지 마세요. 개발용 SQLite와 샘플 게시판으로 화면을 확인할 수 있습니다.",
                "Django 서버에 연결할 수 없다는 오류가 나면 Next.js의 {{G5_API_INTERNAL_URL}}이 실행 중인 Django 주소를 가리키는지 확인합니다. 같은 컴퓨터에서는 보통 {{http://127.0.0.1:8000/api/v1}}입니다."
            ], "note": "운영 서버 환경 변수와 로컬 환경 변수는 파일을 분리해 관리하세요. {{.env}}, {{.env.local}} 파일은 저장소에 올리지 않습니다."}
        ]
    },
    "폴더 구조": {
        "intro": "처음에는 폴더가 많아 보여도 자주 수정하는 위치는 몇 군데뿐입니다. 파일을 찾을 때는 이 표를 길잡이로 사용하세요.",
        "sections": [
            {"heading": "어떤 폴더에서 무엇을 하나요?", "bullets": [
                "{{example/}}: Django 프로젝트의 설정, URL, 실행 진입점이 있습니다.",
                "{{gnu_jango/bbs/}}와 {{gnu_jango/users/}}: 게시판과 회원 기능을 담당합니다.",
                "{{gnu_jango/shop/}}: 상품, 장바구니, 주문과 결제 설정 같은 쇼핑몰 기능이 있습니다.",
                "{{gnu_jango/api/}}: Next.js 화면이 사용하는 REST API를 담당합니다.",
                "{{gnu_jango/templates/}}: Django 관리자 화면, 서버 페이지, 테마 산출물이 있습니다.",
                "{{nextjs/src/app/}}: URL에 대응하는 Next.js 페이지와 화면 구성 요소가 있습니다.",
                "{{nextjs/themes/handbook/}}: 매뉴얼 전용 레이아웃, 검색, 목차, 색상 파일이 있습니다.",
                "{{docs/}}: 구현 계획, 운영 방법, 배포 설명이 있습니다."
            ]},
            {"heading": "파일을 고치는 간단한 예", "steps": [
                "장 본문이나 샘플 책을 바꾸려면 {{gnu_jango/config/handbook_samples.py}}를 찾습니다.",
                "핸드북 목차나 화면 동작을 바꾸려면 {{nextjs/themes/handbook/}}에서 관련 구성 요소를 찾습니다.",
                "게시글 데이터를 API로 가져오는 일반 서비스 코드는 {{nextjs/src/services/}}에서 찾습니다.",
                "바꾼 파일이 Python 코드인지 Next.js 화면인지 구분한 뒤 알맞은 점검 명령을 실행합니다."
            ], "note": "빌드 결과물인 {{gnu_jango/templates/theme/handbook/}}과 {{gnu_jango/templates/theme_static/handbook/}}은 소스 테마를 빌드해 생성합니다. 가능한 한 소스 파일을 수정한 뒤 빌드하세요."}
        ]
    },
    "서버 컴포넌트와 클라이언트 컴포넌트": {
        "intro": "Next.js 화면은 서버에서 먼저 준비할 수도 있고 브라우저에서 직접 움직이게 할 수도 있습니다. 어느 쪽을 선택하느냐에 따라 데이터와 상호작용을 다루는 방법이 달라집니다.",
        "sections": [
            {"heading": "서버 컴포넌트란?", "paragraphs": [
                "서버 컴포넌트는 웹 서버가 데이터를 읽고 HTML을 만들어 브라우저로 보냅니다. API 주소나 비밀이 아닌 서버 전용 설정을 브라우저에 노출하지 않고 데이터를 가져올 수 있어, 페이지 내용과 첫 화면을 만드는 데 적합합니다.",
                "이 프로젝트에서는 게시판 목록이나 게시글 상세처럼 서버에서 불러와 화면에 보여 주는 데이터가 대표적인 예입니다."
            ], "bullets": [
                "장점: 첫 화면에 내용을 바로 포함하기 쉽고, 서버 전용 API 주소를 사용할 수 있습니다.",
                "주의: 브라우저에서만 쓸 수 있는 localStorage나 클릭 상태를 직접 다루면 안 됩니다."
            ]},
            {"heading": "클라이언트 컴포넌트란?", "paragraphs": [
                "클라이언트 컴포넌트는 브라우저에서 클릭, 입력, 열기·닫기 같은 동작을 처리합니다. 파일 맨 위에 {{use client}}를 적으면 그 파일과 필요한 의존성이 브라우저 코드가 됩니다."
            ], "bullets": [
                "검색창이 키보드 단축키로 열리고 입력할 때 결과가 바뀌는 동작",
                "모바일에서 책 목차 서랍을 열고 닫는 동작",
                "화면의 다크 모드 선택을 브라우저에 기억하는 동작"
            ]},
            {"heading": "어떤 것을 선택해야 하나요?", "steps": [
                "화면에 보여 줄 데이터를 서버에서 안전하게 가져올 수 있으면 서버 컴포넌트로 시작합니다.",
                "사용자의 클릭이나 키 입력에 따라 화면이 바뀌어야 할 때만 작은 클라이언트 컴포넌트를 추가합니다.",
                "데이터를 불러오는 서버 코드와 버튼 상태를 다루는 브라우저 코드를 한 파일에 모두 넣지 말고 역할을 나눕니다."
            ], "note": "{{use client}}를 페이지 전체에 붙이면 브라우저로 보내는 코드가 커질 수 있습니다. 상호작용이 필요한 작은 부분에만 사용하세요."}
        ]
    },
    "슬롯 끼우기": {
        "intro": "테마 슬롯은 공통 사이트 틀은 유지하면서 특정 화면만 테마에 맞게 바꾸는 연결 지점입니다. 쉽게 말해 빈 액자에 테마별 그림을 끼우는 구조입니다.",
        "sections": [
            {"heading": "슬롯이 필요한 이유", "paragraphs": [
                "같은 게시판 데이터와 로그인 기능을 쓰더라도 기본 테마와 핸드북 테마의 화면은 다를 수 있습니다. 공통 기능을 복사해서 테마마다 따로 고치면 한쪽 수정이 다른 쪽에 빠지기 쉽습니다.",
                "슬롯은 공통 앱이 화면의 위치를 마련하고 선택된 테마가 그 위치에 자기 구성 요소를 제공합니다."
            ], "bullets": [
                "{{LayoutShell}}: 사이트 전체 상단·사이드바·바닥글 틀",
                "{{HomePage}}: 첫 화면의 본문",
                "{{BoardViewHeader}}: 게시글 상단에 붙는 테마 전용 안내",
                "테마별 연결 설정: {{nextjs/themes/handbook/components.tsx}}와 {{theme.config.ts}}"
            ]},
            {"heading": "새 슬롯을 바꿀 때 확인할 것", "steps": [
                "공통 페이지가 슬롯에 어떤 속성(props)을 전달하는지 확인합니다.",
                "테마 구성 요소가 같은 속성 이름과 자료형을 받는지 확인합니다.",
                "기본 테마에도 기존 동작이 남아 있는지 확인합니다.",
                "핸드북 테마와 기본 테마를 각각 빌드해 의도한 화면만 바뀌었는지 비교합니다."
            ]},
            {"heading": "수정 원칙", "paragraphs": [
                "슬롯은 화면을 바꾸는 지점이지 데이터 권한을 우회하는 통로가 아닙니다. 게시글을 수정하거나 로그인 권한을 확인하는 작업은 Django API를 통해야 합니다.",
                "새 슬롯이 꼭 필요한지 먼저 확인하고, 한 테마 안에서만 쓰는 작은 요소라면 해당 테마 폴더에 두는 편이 단순합니다."
            ]}
        ]
    },
    "스타일 바꾸기": {
        "intro": "색상이나 간격을 바꾸고 싶을 때는 먼저 전역 색상 토큰을 찾습니다. 화면마다 색을 직접 붙여 넣기보다 같은 역할의 색을 한곳에서 관리하면 유지보수가 쉽습니다.",
        "sections": [
            {"heading": "핸드북 스타일 파일", "bullets": [
                "{{theme.tokens.css}}: 밝은 화면의 색상과 공통 디자인 토큰",
                "{{theme.dark.css}}: 다크 모드에서 사용할 색상 토큰",
                "{{theme.shell.css}}: 상단·사이드바·전체 레이아웃",
                "{{theme.booknav.css}}: 책 선택과 목차",
                "{{theme.pages.css}}와 {{theme.list.css}}: 문서 본문과 목록",
                "{{theme.css}}: 위 스타일 파일을 묶는 진입점"
            ]},
            {"heading": "토큰을 바꾸는 순서", "steps": [
                "바꾸려는 요소가 배경, 본문 글자, 링크, 강조색 중 무엇인지 정합니다.",
                "{{theme.tokens.css}}에서 해당 역할 이름의 CSS 변수를 찾습니다.",
                "핸드북 전용 파일을 수정하고 기본 테마 파일을 실수로 바꾸지 않았는지 확인합니다.",
                "테마 빌드와 동기화 점검을 실행하고 밝은 화면과 어두운 화면을 모두 확인합니다."
            ], "code": "cd nextjs\nnpm run build:theme:handbook\nnpm run check:theme-sync:handbook"},
            {"heading": "읽기 편한 대비 확인", "paragraphs": [
                "배경과 글자 색이 비슷하면 글을 읽기 어렵습니다. 본문 글자, 링크, 비활성 버튼, 현재 목차 항목을 각각 확인하세요.",
                "색만으로 상태를 구분하지 말고 글자나 아이콘도 함께 사용합니다. 예를 들어 현재 장은 색과 굵기 또는 표시 아이콘을 같이 사용하면 더 알아보기 쉽습니다."
            ], "note": "CSS가 빌드 결과물 폴더에서만 바뀌면 다음 빌드에서 덮어써집니다. 소스인 {{nextjs/themes/handbook/}}를 수정하세요."}
        ]
    },
    "API 부르기": {
        "intro": "API는 화면과 Django 서버가 데이터를 주고받는 약속입니다. 브라우저 화면은 데이터베이스에 직접 접속하지 않고 Django API에 필요한 내용을 요청합니다.",
        "sections": [
            {"heading": "먼저 브라우저에서 응답을 확인합니다", "paragraphs": [
                "로컬 Django 서버가 실행 중일 때 {{/api/v1/settings}}을 열면 사이트 설정 JSON을 볼 수 있습니다. 매뉴얼 책 목록은 그룹 이름을 지정해 요청합니다."
            ], "code": "http://127.0.0.1:8000/api/v1/settings\nhttp://127.0.0.1:8000/api/v1/boards?group=manual\nhttp://127.0.0.1:8000/api/v1/boards/hb_start/posts?per_page=100"},
            {"heading": "응답을 읽는 법", "paragraphs": [
                "API 응답은 보통 {{success}} 또는 {{ok}} 상태와 {{data}} 내용을 담습니다. 게시판 목록 요청의 {{data}}는 책이 될 게시판 배열입니다. 게시글 요청의 {{data}}는 각 장의 제목·분류·작성일 같은 목록입니다.",
                "장 본문은 게시글 상세 API에서 가져옵니다. 예를 들어 {{/api/v1/posts/hb_start/6}}은 게시판 {{hb_start}}의 6번 글을 요청합니다. 실제 글 번호는 데이터베이스마다 다를 수 있습니다."
            ]},
            {"heading": "Next.js 코드에서 API를 사용합니다", "paragraphs": [
                "프로젝트의 게시판 조회 함수는 {{nextjs/src/services/boards.ts}}에 있습니다. 화면에서 이 함수를 사용하면 URL 조립과 응답 형식 확인을 공통으로 처리할 수 있습니다.",
                "API 오류가 나면 빈 화면으로 감추기 전에 HTTP 상태 코드, JSON의 메시지, Django 터미널 로그를 확인합니다. 운영 환경에서는 비밀 키나 개인정보가 포함된 전체 응답을 공개하지 마세요."
            ], "steps": [
                "Django 서버가 실행 중인지 확인합니다.",
                "요청 URL에 게시판 이름과 그룹 ID가 맞는지 확인합니다.",
                "응답이 200인지 확인하고 {{data}}에 데이터가 있는지 살펴봅니다.",
                "화면 서비스 함수가 API 오류를 어떻게 처리하는지 확인합니다."
            ], "note": "브라우저 자바스크립트에 데이터베이스 비밀번호나 Storage 비밀 키를 넣으면 안 됩니다. 서버 API를 통해 필요한 데이터만 요청하세요."}
        ]
    },
    "게시판 데이터": {
        "intro": "핸드북은 새로운 문서 데이터베이스를 만들지 않고 기존 게시판 데이터 구조를 사용합니다. 게시판을 책처럼 설정하면 그 게시판의 글이 목차와 본문이 됩니다.",
        "sections": [
            {"heading": "데이터가 책으로 바뀌는 규칙", "bullets": [
                "그룹 ID: 어느 게시판들을 매뉴얼로 보여 줄지 정합니다. 값은 {{cf_docs_group}} 설정에 저장됩니다.",
                "게시판 그룹 안의 게시판: 매뉴얼 한 권입니다. 게시판 제목을 {{안내 문구 · 책 이름}}으로 정하면 카드에 안내 문구와 이름이 나뉘어 표시됩니다.",
                "게시판 분류: 책 안의 부입니다. 게시판의 분류 목록에 적은 순서대로 표시됩니다.",
                "게시판 글: 장입니다. {{wr_num}} 순서가 책을 읽는 순서를 결정합니다."
            ]},
            {"heading": "새 장이 안 보일 때 확인할 것", "steps": [
                "게시판이 화면 설정에서 선택한 매뉴얼 그룹 안에 있는지 확인합니다.",
                "게시판 읽기 권한이 공개 매뉴얼에 맞는지 확인합니다.",
                "글이 비밀글이 아닌지, 게시판의 글 읽기 권한이 방문자에게 허용되는지 확인합니다.",
                "글의 분류가 게시판 분류 목록과 일치하는지 확인합니다.",
                "게시판 목록 API와 게시글 상세 API에서 해당 글이 보이는지 확인합니다."
            ]},
            {"heading": "정렬을 바꾸고 싶다면", "paragraphs": [
                "책 순서는 게시판 관리자에서 정한 출력 순서 {{bo_order}}를 사용합니다. 부 순서는 게시판 분류 설정의 순서를 사용합니다. 장 순서는 게시판 글의 번호 정렬 기준을 따릅니다.",
                "장 제목을 바꾸거나 새 글을 추가할 때 이전·다음 장 순서도 같이 확인하세요. 이미 공유된 장 주소를 바꾸면 외부 링크가 달라질 수 있습니다."
            ]}
        ]
    },
    "서버 요구사항": {
        "intro": "서비스를 인터넷에 공개하려면 Django 앱을 실행할 서버, 영구 데이터베이스, 정적 파일과 업로드 파일을 저장할 장소가 필요합니다. 무료 데모와 실제 운영 사이트의 요구 수준은 다릅니다.",
        "sections": [
            {"heading": "이 프로젝트가 사용하는 구성", "bullets": [
                "애플리케이션: Python 3.13과 Django. 배포 프로필에 맞는 Python 실행 환경이 필요합니다.",
                "데이터베이스: 로컬 개발은 SQLite, 운영은 보통 PostgreSQL을 사용합니다.",
                "업로드 파일: VPS는 디스크를 쓸 수 있지만, 서버리스 환경은 Supabase Storage 같은 외부 저장소를 사용합니다.",
                "캐시와 예약 작업: 프로필에 따라 데이터베이스 캐시, Redis, Celery worker 또는 Vercel Cron을 사용합니다.",
                "웹 주소: HTTPS 도메인, 허용 호스트, CSRF 신뢰 주소가 올바르게 설정되어야 합니다."
            ]},
            {"heading": "배포 방식을 고릅니다", "paragraphs": [
                "Vercel과 Supabase 조합은 데모나 작은 서비스에 적합한 서버리스 구성입니다. Vercel이 Django 함수를 실행하고 Supabase가 PostgreSQL과 파일 저장소를 제공합니다.",
                "VPS는 운영자가 서버와 업데이트를 관리하는 방식입니다. Docker Compose를 쓰면 Django, PostgreSQL, Redis와 작업 worker를 함께 구성할 수 있습니다. Next.js를 별도 서버에서 실행하는 분리형 구성도 있습니다."
            ]},
            {"heading": "배포 전에 확인하세요", "steps": [
                "저장소의 {{docs/04-deploy/deployment-profiles.md}}에서 사용할 프로필과 필요한 환경 변수를 확인합니다.",
                "운영용 도메인과 HTTPS 인증서를 준비합니다.",
                "데이터베이스와 업로드 파일을 백업하고 복구 방법을 확인합니다.",
                "실제 결제·소셜 로그인·본인인증을 쓸 경우 공급자 테스트 키와 callback 주소를 준비합니다."
            ], "note": "운영 서버에 개발용 SQLite 파일만 복사하면 여러 서버의 데이터가 공유되지 않고 백업도 어렵습니다. 공개 서비스에서는 운영 DB와 파일 저장소를 별도로 준비하세요."}
        ]
    },
    "환경 변수": {
        "intro": "환경 변수는 비밀번호나 서버 주소처럼 코드마다 다르게 설정할 값을 코드 바깥에 보관하는 방법입니다. 로컬은 {{.env}}, Vercel은 프로젝트의 Environment Variables 화면에 저장합니다.",
        "sections": [
            {"heading": "먼저 알아야 할 값", "bullets": [
                "{{SECRET_KEY}}: Django 세션과 서명에 사용하는 비밀 키입니다. 외부에 공개하지 않습니다.",
                "{{DATABASE_URL}}: Django가 접속할 PostgreSQL 주소입니다. 비밀번호가 들어 있으므로 비밀로 취급합니다.",
                "{{DEPLOY_PROFILE}}: 사용할 운영 방식입니다. 이 사이트는 Vercel에서 {{vercel}}을 사용합니다.",
                "{{G5_DEFAULT_THEME}}: 새 설정이 없을 때 시작할 테마입니다. 매뉴얼 사이트는 {{handbook}}을 사용합니다.",
                "{{G5_DEFAULT_DOCS_GROUP}}: 매뉴얼로 읽을 게시판 그룹 ID입니다. 샘플은 {{manual}}을 사용합니다.",
                "{{MEDIA_STORAGE}}, {{S3_*}}, {{CACHE_URL}}, {{CRON_SECRET}}: 파일 저장소·캐시·예약 작업에 필요한 값입니다. 자세한 필수 여부는 배포 프로필 문서를 따릅니다."
            ]},
            {"heading": "Vercel에 넣는 순서", "steps": [
                "Vercel에서 {{gnu-jango-handbook}} 프로젝트를 선택합니다.",
                "Settings → Environment Variables를 엽니다.",
                "저장소의 {{deploy/env/vercel-supabase.env.example}}을 보고 실제 프로젝트의 값을 한 개씩 등록합니다.",
                "Production과 Preview 중 값이 필요한 환경을 선택합니다.",
                "변수를 저장한 다음 새 배포를 만들어 반영합니다."
            ]},
            {"heading": "비밀을 안전하게 보관하기", "paragraphs": [
                "비밀 값은 GitHub, 채팅, 화면 캡처, 공개 로그에 붙여 넣지 않습니다. {{.env}}와 {{.env.local}}은 저장소의 무시 목록에 있어야 합니다.",
                "비밀이 실수로 공개되었다면 파일에서 지우는 것만으로 끝나지 않습니다. 해당 공급자에서 키를 폐기하고 새 키를 발급한 뒤 서버 값을 바꿉니다."
            ], "note": "환경 변수를 변경해도 이미 실행 중인 함수에 즉시 반영되지 않을 수 있습니다. 새 배포가 끝난 뒤 사이트 설정 API와 배포 로그에서 확인하세요."}
        ]
    },
    "빌드하기": {
        "intro": "핸드북 테마 빌드는 Next.js 소스와 스타일을 Django가 제공할 테마 파일로 만드는 작업입니다. 소스 코드를 수정한 뒤 아래 명령으로 새 산출물을 생성합니다.",
        "sections": [
            {"heading": "개발 준비", "steps": [
                "저장소 루트에서 {{nextjs}} 폴더로 이동합니다.",
                "{{npm ci}}를 실행해 lock 파일과 같은 버전의 패키지를 설치합니다.",
                "빌드 전에 TypeScript 오류나 누락된 이미지가 없는지 확인합니다."
            ], "code": "cd nextjs\nnpm ci"},
            {"heading": "핸드북 테마 만들기", "paragraphs": [
                "{{npm run build:theme:handbook}}은 Next.js 빌드 스크립트를 실행하고 Django 테마 경로에 산출물을 동기화합니다. 기본 커뮤니티 테마를 만들 때 쓰는 {{npm run build:theme}}과 명령이 다릅니다."
            ], "code": "npm run build:theme:handbook\nnpm run check:theme-sync:handbook"},
            {"heading": "성공 여부 확인", "steps": [
                "명령이 오류 없이 끝났는지 확인합니다.",
                "Git 변경 목록에 {{gnu_jango/templates/theme/handbook/}}과 {{gnu_jango/templates/theme_static/handbook/}} 아래 파일이 생겼는지 확인합니다.",
                "Django를 실행해 핸드북 화면에서 스타일과 이미지가 보이는지 확인합니다.",
                "빌드 산출물을 갱신했다면 두 테마 디렉터리를 함께 버전 관리에 포함합니다."
            ], "note": "{{npm run build}}는 Node 서버용 Next.js 빌드이며, Django가 서빙하는 핸드북 테마 산출물을 갱신하는 명령과 목적이 다릅니다."}
        ]
    },
    "정적 파일 올리기": {
        "intro": "화면은 HTML만으로 완성되지 않습니다. CSS는 색과 배치를 정하고 JavaScript는 메뉴와 검색을 움직이며 이미지는 화면에 그림을 보여 줍니다. 이 파일들을 정적 파일이라고 부릅니다.",
        "sections": [
            {"heading": "두 산출물 폴더를 함께 확인합니다", "bullets": [
                "{{gnu_jango/templates/theme/handbook/}}: Django 테마가 쓰는 HTML·라우팅 파일",
                "{{gnu_jango/templates/theme_static/handbook/}}: CSS, JavaScript, 이미지, 글꼴"
            ]},
            {"heading": "Vercel 배포에 반영하는 법", "steps": [
                "테마 소스를 수정합니다.",
                "{{cd nextjs}}로 이동해 {{npm run build:theme:handbook}}을 실행합니다.",
                "{{npm run check:theme-sync:handbook}}으로 필요한 정적 파일이 동기화되었는지 확인합니다.",
                "두 산출물 폴더의 변경을 함께 커밋해 저장소에 올립니다.",
                "Vercel 배포가 끝난 뒤 새로고침하고 브라우저 개발자 도구의 Network 탭에서 CSS·JavaScript 요청이 200인지 확인합니다."
            ]},
            {"heading": "스타일이 안 나오거나 그림이 깨질 때", "bullets": [
                "테마 폴더만 커밋하고 정적 파일 폴더를 빠뜨렸는지 확인합니다.",
                "요청 주소가 이전 빌드의 해시 파일을 가리키는지 확인하고 페이지를 강력 새로고침합니다.",
                "배포 산출물에 파일이 포함됐는지 확인하고, Vercel 배포 로그에 빌드 실패가 없는지 확인합니다."
            ], "note": "정적 파일 URL에는 빌드 해시가 들어갈 수 있습니다. 파일 하나만 수동으로 교체하지 말고 테마 전체를 같은 빌드 결과로 맞추세요."}
        ]
    },
    "자주 만나는 오류": {
        "intro": "문제가 생기면 여러 설정을 한꺼번에 바꾸기보다 화면 주소와 서버 로그를 기준으로 원인을 한 단계씩 좁힙니다.",
        "sections": [
            {"heading": "책 목록이 보이지 않습니다", "bullets": [
                "핸드북 테마 설정이 실제 게시판 그룹 ID를 가리키는지 확인합니다. 샘플 그룹은 {{manual}}입니다.",
                "그 그룹 안에 게시판이 있는지 확인합니다. 샘플 책은 {{hb_start}}, {{hb_dev}}, {{hb_deploy}}, {{hb_ref}}입니다.",
                "새 데이터베이스라면 {{python manage.py ensure_handbook_samples}}을 실행했는지 확인합니다."
            ]},
            {"heading": "장 주소가 404를 보여 줍니다", "bullets": [
                "해당 게시글이 삭제되지 않았는지 확인합니다.",
                "게시판 읽기 권한이 방문자에게 허용되는지 확인합니다.",
                "{{/api/v1/boards/hb_start/posts}} 목록과 {{/api/v1/posts/hb_start/장번호}} 상세 API를 각각 확인합니다.",
                "게시글 분류가 책의 분류 설정과 맞는지 확인합니다."
            ]},
            {"heading": "CSS나 이미지가 없습니다", "bullets": [
                "핸드북 테마와 정적 파일을 모두 빌드했는지 확인합니다.",
                "{{gnu_jango/templates/theme_static/handbook/}}이 저장소와 배포 결과에 들어갔는지 확인합니다.",
                "브라우저 개발자 도구의 Network 탭에서 실패한 파일 URL과 상태 코드를 확인합니다."
            ]},
            {"heading": "바꾼 글이 바로 보이지 않습니다", "paragraphs": [
                "Next.js는 게시판과 장 목록을 잠시 캐시할 수 있습니다. 저장한 뒤 30초 정도 기다렸다가 강력 새로고침하고, 그래도 다르면 해당 글의 상세 API 응답이 새 내용인지 확인합니다.",
                "API 응답도 바뀌지 않았다면 다른 데이터베이스를 보고 있거나 저장이 되지 않은 것입니다. API 응답은 바뀌었는데 화면만 오래되면 브라우저 캐시와 Vercel 함수 로그를 확인하세요."
            ]},
            {"heading": "500 오류가 발생합니다", "steps": [
                "화면에 보이는 시간과 요청 주소를 기록합니다. 비밀번호나 토큰은 기록하지 않습니다.",
                "Vercel Function Logs 또는 로컬 Django 터미널에서 같은 시간의 오류를 찾습니다.",
                "환경 변수 누락, 데이터베이스 연결, 마이그레이션 상태 순으로 확인합니다.",
                "필요하면 {{python manage.py check_deploy_profile --profile vercel}}을 실행해 설정을 점검합니다."
            ], "code": "python manage.py check_deploy_profile --profile vercel"}
        ]
    },
    "용어 사전": {
        "intro": "처음 볼 때 헷갈리는 단어를 쉬운 말로 정리했습니다. 코드나 오류 메시지에 같은 단어가 나오면 이 장을 참고하세요.",
        "sections": [
            {"heading": "사이트와 데이터", "bullets": [
                "Django: 데이터와 권한을 관리하고 API를 제공하는 Python 웹 프레임워크입니다.",
                "Next.js: 방문자 화면을 만드는 React 프레임워크입니다.",
                "API: 화면과 서버가 데이터를 주고받는 주소와 규칙입니다.",
                "게시판 그룹: 여러 게시판을 하나로 묶는 폴더 같은 구조입니다.",
                "마이그레이션: Python 모델 변경을 데이터베이스 표 구조에 적용하는 기록과 명령입니다.",
                "정적 파일: CSS, JavaScript, 이미지, 글꼴처럼 서버에서 파일 그대로 내려주는 자료입니다."
            ]},
            {"heading": "배포와 보안", "bullets": [
                "환경 변수: 비밀 키나 서버별 값을 코드 바깥에 저장하는 설정입니다.",
                "Vercel: Next.js와 Python 함수를 배포하고 실행하는 호스팅 서비스입니다.",
                "Supabase: 이 프로젝트에서 PostgreSQL 데이터베이스와 Storage를 제공하는 서비스입니다.",
                "Storage: 사용자가 올린 이미지나 첨부파일을 보관하는 저장 공간입니다.",
                "캐시: 같은 내용을 반복 계산하지 않도록 잠시 보관하는 복사본입니다."
            ]},
            {"heading": "이 매뉴얼에서 쓰는 말", "bullets": [
                "책: 매뉴얼 그룹에 속한 게시판 하나입니다.",
                "부: 게시판의 한 분류입니다.",
                "장: 게시판의 글 하나입니다.",
                "테마: 공통 기능과 데이터를 어떤 디자인으로 보여 줄지 정한 화면 묶음입니다."
            ]}
        ]
    },
    "단축키": {
        "intro": "단축키를 쓰면 마우스로 메뉴를 찾지 않아도 원하는 문서를 빠르게 찾을 수 있습니다.",
        "sections": [
            {"heading": "문서 검색", "bullets": [
                "{{Ctrl+K}}: 문서 검색창을 엽니다. Mac에서는 {{⌘K}}를 사용할 수 있습니다.",
                "검색창에 책 이름, 부 이름, 장 제목을 입력합니다. 검색어를 지우면 현재 책의 목차를 다시 볼 수 있습니다.",
                "{{Esc}}: 검색창이나 열려 있는 서랍을 닫습니다."
            ]},
            {"heading": "검색 결과를 잘 찾는 방법", "steps": [
                "정확한 장 제목을 알고 있으면 제목 중 기억나는 단어를 입력합니다.",
                "주제를 모를 때는 {{설치}}, {{로그인}}, {{정적 파일}}처럼 짧은 핵심 단어를 검색합니다.",
                "결과에 책과 부 이름이 함께 표시되면 맞는 위치인지 확인하고 장을 엽니다."
            ]},
            {"heading": "키보드로 계속 읽기", "paragraphs": [
                "검색 결과를 열면 책 목차에서 현재 장을 확인할 수 있습니다. 장 아래쪽의 이전 장과 다음 장 링크를 사용하면 순서대로 읽기 편합니다.",
                "모바일 화면에서는 메뉴 버튼으로 목차를 열고 원하는 장을 고릅니다. 장을 선택하면 목차가 닫히고 본문으로 이동합니다."
            ], "note": "브라우저나 입력창에 따라 같은 단축키를 다른 기능이 먼저 사용할 수 있습니다. 검색창이 열리지 않으면 화면 위의 문서 검색 버튼을 눌러 보세요."}
        ]
    },
    "변경 기록": {
        "intro": "매뉴얼과 프로그램은 계속 바뀝니다. 여기서는 어떤 내용을 기준으로 읽어야 하는지, 설명을 수정할 때 무엇을 남겨야 하는지 안내합니다.",
        "sections": [
            {"heading": "현재 내용의 기준", "paragraphs": [
                "핸드북은 현재 저장소의 Django 설정, Next.js 테마, 배포 안내를 기준으로 작성됩니다. 화면의 버튼 이름이나 환경 변수는 새 버전에서 바뀔 수 있으므로 날짜가 오래된 안내는 실제 설정 화면과 함께 확인하세요.",
                "운영 사이트의 매뉴얼 글은 데이터베이스에 저장되고, 샘플 콘텐츠의 원본은 {{gnu_jango/config/handbook_content.py}}에 있습니다."
            ]},
            {"heading": "새 설명을 추가할 때", "steps": [
                "어떤 사용자와 어떤 작업을 위한 설명인지 첫 문단에 씁니다.",
                "준비물과 필요한 권한을 먼저 적습니다.",
                "실제 메뉴명과 명령을 한 단계씩 적습니다.",
                "실행 후 눈으로 확인할 수 있는 결과를 적습니다.",
                "자주 생기는 오류와 해결 순서를 추가합니다.",
                "화면이나 환경 변수가 바뀐 경우 변경된 날짜와 영향을 받는 책·장을 함께 기록합니다."
            ]},
            {"heading": "샘플 콘텐츠를 갱신하는 법", "paragraphs": [
                "개발 데이터베이스에서 {{python manage.py ensure_handbook_samples}}를 실행하면 샘플 책이 준비됩니다. 이 명령은 기존에 직접 작성한 본문은 건드리지 않고, 예전의 공통 안내 문구가 남아 있는 샘플 본문만 새 설명으로 갱신합니다.",
                "저장소의 변경 내역은 Git에서 확인할 수 있습니다. 예를 들어 {{git log --oneline -- gnu_jango/config/handbook_content.py}}는 샘플 매뉴얼 내용과 생성 규칙의 변경 기록을 보여 줍니다."
            ], "code": "python manage.py ensure_handbook_samples\ngit log --oneline -- gnu_jango/config/handbook_content.py"}
        ]
    }
}


def _inline_text(value):
    """Escape article text and render {{inline code}} without trusting user HTML."""
    chunks = _INLINE_CODE.split(value)
    return "".join(
        f"<code>{escape(chunk)}</code>" if index % 2 else escape(chunk)
        for index, chunk in enumerate(chunks)
    )


def _render_section(section):
    parts = [f"<h2>{escape(section['heading'])}</h2>"]
    parts.extend(f"<p>{_inline_text(text)}</p>" for text in section.get("paragraphs", ()))
    for key, tag in (("bullets", "ul"), ("steps", "ol")):
        items = section.get(key, ())
        if items:
            parts.append(f"<{tag}>" + "".join(f"<li>{_inline_text(item)}</li>" for item in items) + f"</{tag}>")
    if section.get("code"):
        parts.append(f"<pre><code>{escape(section['code'].rstrip())}</code></pre>")
    if section.get("note"):
        parts.append(f"<p><strong>참고:</strong> {_inline_text(section['note'])}</p>")
    return "".join(parts)


def chapter_body(title):
    """Render a beginner-friendly handbook article as escaped HTML."""
    guide = GUIDES.get(title)
    if guide is None:
        return f"<p>{escape(title)} 장의 설명을 준비하고 있습니다.</p>"
    parts = [f"<p>{_inline_text(guide['intro'])}</p>"]
    parts.extend(_render_section(section) for section in guide["sections"])
    return "".join(parts)
