"""Repeatable Korean query set for measuring the sample handbook's question search."""

EVALUATION_CASES = (
    ("이 프로젝트는 어떤 사이트를 만들기 위한 건가요", "hb_start", "이 안내서가 하는 일"),
    ("시작하기 전에 설치해야 하는 프로그램과 준비물은 무엇인가요", "hb_start", "필요한 것"),
    ("Windows 개발 환경에서 Python과 Node 버전을 확인하려면", "hb_dev", "개발 환경"),
    ("Django 앱과 Next.js 화면 파일은 각각 어느 폴더에 있나요", "hb_dev", "폴더 구조"),
    ("처음 실행한 뒤 localhost에서 첫 화면을 열고 확인하려면", "hb_start", "첫 화면 열기"),
    ("게시판에 새 글을 작성하는 절차를 알고 싶어요", "hb_start", "글 써 보기"),
    ("사이트 이름이나 로고와 색상을 바꾸는 방법은", "hb_start", "이름과 색 바꾸기"),
    ("Next.js에서 서버 컴포넌트와 클라이언트 컴포넌트를 언제 쓰나요", "hb_dev", "서버 컴포넌트와 클라이언트 컴포넌트"),
    ("새 슬롯을 연결하고 기본 테마까지 확인하는 순서는", "hb_dev", "슬롯 끼우기"),
    ("다크 모드의 배경과 글자 색을 조정하려면 어디를 고치나요", "hb_dev", "스타일 바꾸기"),
    ("Django API에서 게시판 장 데이터를 받아오는 URL을 확인하려면", "hb_dev", "API 부르기"),
    ("매뉴얼의 책과 부와 장은 게시판 데이터에서 각각 무엇인가요", "hb_dev", "게시판 데이터"),
    ("Vercel과 Supabase 운영에 필요한 서버 구성을 알고 싶어요", "hb_deploy", "서버 요구사항"),
    ("DATABASE_URL과 SECRET_KEY를 Vercel에 안전하게 저장하려면", "hb_deploy", "환경 변수"),
    ("Django 테마 빌드와 정적 파일 동기화 명령은 무엇인가요", "hb_deploy", "빌드하기"),
    ("테마 CSS와 이미지 파일을 서버에 올리는 방법", "hb_deploy", "정적 파일 올리기"),
    ("게시판 장이 404이거나 테마 CSS가 깨질 때 먼저 볼 것은", "hb_deploy", "자주 만나는 오류"),
    ("프로젝트에서 자주 사용하는 개발 용어를 찾아보려면", "hb_ref", "용어 사전"),
    # Paraphrases: none of these reuse the words of the expected chapter title, so they measure
    # matching on the chapter body rather than on its (heavily weighted) title.
    ("광고 글이 자동으로 올라오는 걸 막고 싶어요", "hb_member", "스팸과 자동등록방지"),
    ("로그인하지 않은 방문자도 의견을 남기게 하려면", "hb_member", "비회원 글쓰기와 댓글"),
    ("특정 레벨 이상만 게시물을 읽게 제한하려면", "hb_member", "회원 등급과 접근 권한"),
    ("작성자와 운영자만 볼 수 있는 글은 어떻게 쓰나요", "hb_board", "비밀글과 첨부파일 관리"),
    ("새 커뮤니티 공간을 하나 추가하고 싶어요", "hb_board", "게시판 만들기"),
    ("손님이 물건을 담고 계산하기까지 어떤 단계를 거치나요", "hb_shop", "장바구니와 주문 흐름"),
    ("입금 기한이 지난 무통장 주문을 정리하려면", "hb_shop", "가상계좌 운영 점검"),
    ("키보드로 문서 찾기 창을 바로 여는 방법", "hb_ref", "단축키"),
    ("무료 파이썬 호스팅에 데모를 배포하려면", "hb_deploy", "PythonAnywhere에 올리기"),
)
