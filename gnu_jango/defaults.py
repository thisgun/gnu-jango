import os.path
from django.conf import settings
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from datetime import datetime

from pathlib import Path
from gnu_jango.utils.dir import get_list_dir

__GNU__VERSION__ = "0.0.1"

__STATIC_VERSION__ = getattr(settings, "DEFAULTS_STATIC_VERSION", "220920")

PROJECT_BASE_DIR = Path(__file__).resolve().parent

# True 이면 static 경로의 css 또는 js 파일의 끝에 v=수정된 시간이 붙습니다.
IS_STATIC_URL_FILETIME = getattr(settings, "DEFAULTS_IS_STATIC_URL_FILETIME", True)

THUMBNAIL_QUALITY = getattr(settings, "DEFAULTS_THUMBNAIL_QUALITY", 99)

BACKEND = getattr(settings, "DEFAULTS_BACKEND", "")
# BACKEND = getattr(settings, 'DEFAULTS_BACKEND', 'gnu_jango.backends.redisd.RedisBackend')

# 캡챠 사용 여부,  True 면 사용, False 면 사용 안함
IS_USE_CAPTCHA = getattr(settings, "DEFAULTS_IS_USE_CAPTCHA", True)

DB_PREFIX = getattr(settings, "DEFAULTS_DB_PREFIX", "gnu_jango_")

EDITOR_DIR_NAME = getattr(settings, "DEFAULTS_EDITOR_DIR_NAME", "editor")

CF_USE_USER_ICON_CHOICES = (
    ("0", _("미사용")),
    ("1", _("아이콘만 표시")),
    ("2", _("아이콘+이름 표시")),
)

# key, default_value
# 또는
# key, {default_value, type, label, description, choices}
CONFIGS = {
    # "cf_title": ("그누보드5", "str", _("홈페이지제목"), "", {"group": _("기본환경")}),
    # "cf_theme": ("basic", "hidden", _("홈페이지테마"), "", {"group": _("기본환경")}),
    "cf_title": (
        "그누보드5",
        "str",
        _("홈페이지제목"),
    ),
    "cf_theme": (
        getattr(settings, "G5_DEFAULT_THEME", "nextjs_default"),
        "hidden",
        _("홈페이지테마"),
    ),
    "cf_admin": ("", "str", _("최고관리자")),
    "cf_admin_email": (
        "",
        "email",
        _("관리자 메일 주소"),
        _("관리자가 보내고 받는 용도로 사용하는 메일 주소를 입력합니다. (회원가입, 인증메일, 테스트, 회원메일발송 등에서 사용)"),
    ),
    "cf_admin_email_name": (
        "",
        "str",
        _("관리자 메일 발송이름"),
        _("관리자가 보내고 받는 용도로 사용하는 메일의 발송이름을 입력합니다. (회원가입, 인증메일, 테스트, 회원메일발송 등에서 사용)"),
    ),
    "cf_company_name": ("", "str", _("회사명")),
    "cf_company_owner": ("", "str", _("대표자")),
    "cf_company_addr": ("", "str", _("사업장 주소")),
    "cf_company_biz_no": ("", "str", _("사업자등록번호")),
    "cf_company_tel": ("", "str", _("대표 전화번호")),
    "cf_company_tongsin_no": ("", "str", _("통신판매업 신고번호")),
    "cf_company_info_name": ("", "str", _("개인정보관리 책임자")),
    "cf_company_email": ("", "email", _("정보관리책임자 이메일")),
    "de_admin_company_tel": ("", "str", _("쇼핑몰 고객센터 전화번호")),
    "de_bank_use": ("0", "checkbox", _("무통장입금 사용")),
    "de_bank_account": (
        "",
        "text",
        _("무통장입금 계좌 안내"),
        _("은행, 계좌번호, 예금주를 한 줄에 하나씩 입력합니다. 쇼핑몰에 공개됩니다."),
    ),
    "de_card_use": ("1", "checkbox", _("카드 결제 허용")),
    "de_vbank_use": ("1", "checkbox", _("가상계좌 결제 허용")),
    "de_iche_use": ("1", "checkbox", _("실시간계좌이체 허용")),
    "de_hp_use": ("1", "checkbox", _("휴대폰 결제 허용")),
    "de_easy_pay_use": ("1", "checkbox", _("간편결제 허용")),
    "cf_home_boards": (
        "",
        "str",
        _("홈 게시판 순서"),
        _("메인 화면에 표시할 bo_table을 쉼표로 구분해 입력합니다. 예: free,qa,notice"),
    ),
    "cf_home_gallery": (
        "",
        "str",
        _("홈 갤러리 게시판"),
        _("메인 갤러리 영역에 표시할 bo_table을 입력합니다. 비우면 갤러리 스킨 게시판을 찾습니다."),
    ),
    "cf_docs_group": (
        getattr(settings, "G5_DEFAULT_DOCS_GROUP", ""),
        "str",
        _("매뉴얼 게시판 그룹"),
        _("매뉴얼(handbook) 테마가 책으로 보여 줄 게시판 그룹 ID를 입력합니다. 그룹의 게시판 하나가 책 한 권, 게시판 분류가 부, 글이 장입니다."),
    ),
    "cf_use_point": ("1", "checkbox", _("포인트 사용")),
    "cf_point_term": (0, "int", _("포인트 유효기간"), _("기간을 0으로 설정시 포인트 유효기간이 적용되지 않습니다.")),
    "cf_use_copy_log": (1, "int", _("복사, 이동시 로그"), _("체크시 게시물 아래에 누구로 부터 복사, 이동됨 표시")),
    "cf_use_email_certify": (
        "",
        "checkbox",
        _("메일인증 사용"),
        _(
            "메일에 배달된 인증 주소를 클릭하여야 회원으로 인정합니다.<br>( SNS를 이용한 소셜로그인 한 회원은 회원메일인증을 하지 않습니다. 일반회원에게만 해당됩니다.)"
        ),
    ),
    "cf_login_point": (100, "int", _("로그인시 포인트"), _("회원이 로그인시 하루에 한번만 적립")),
    "cf_cut_name": (15, "int", _("이름(닉네임) 표시"), _("해당 숫자 자리만 표시")),
    "cf_nick_modify": (60, "int", _("닉네임 수정"), _("수정하면 해당 일 동안 바꿀 수 없음")),
    "cf_new_skin": ("basic", "choices", _("최근게시물 스킨")),
    "cf_new_rows": (15, "int", _("최근게시물 라인수")),
    "cf_search_skin": ("basic", "choices", _("검색 스킨")),
    "cf_connect_skin": ("basic", "choices", _("접속자 스킨")),
    "cf_faq_skin": ("basic", "choices", _("FAQ 스킨")),
    "cf_read_point": (0, "int", _("글읽기 포인트")),
    "cf_write_point": (0, "int", _("글쓰기 포인트")),
    "cf_comment_point": (0, "int", _("댓글쓰기 포인트")),
    "cf_download_point": (0, "int", _("다운로드 포인트")),
    "cf_write_pages": (10, "int", _("페이지 표시 수")),
    "cf_mobile_pages": (10, "int", _("모바일 페이지 표시 수")),
    "cf_link_target": ("_blank", "choices", _("새창 링크")),
    "cf_bbs_rewrite": (0, "int", _("짧은주소 설정")),
    "cf_delay_sec": (30, "int", _("글쓰기 간격")),
    "cf_filter": (
        "18아,18놈,18새끼,18뇬,18노,18것,18넘,개년,개놈,개뇬,개새,개색끼,개세끼,개세이,개쉐이,개쉑,개쉽,개시키,개자식,개좆,게색기,게색끼,광뇬,뇬,눈깔,뉘미럴,니귀미,니기미,니미,도촬,되질래,뒈져라,뒈진다,디져라,디진다,디질래,병쉰,병신,뻐큐,뻑큐,뽁큐,삐리넷,새꺄,쉬발,쉬밸,쉬팔,쉽알,스패킹,스팽,시벌,시부랄,시부럴,시부리,시불,시브랄,시팍,시팔,시펄,실밸,십8,십쌔,십창,싶알,쌉년,썅놈,쌔끼,쌩쑈,썅,써벌,썩을년,쎄꺄,쎄엑,쓰바,쓰발,쓰벌,쓰팔,씨8,씨댕,씨바,씨발,씨뱅,씨봉알,씨부랄,씨부럴,씨부렁,씨부리,씨불,씨브랄,씨빠,씨빨,씨뽀랄,씨팍,씨팔,씨펄,씹,아가리,아갈이,엄창,접년,잡놈,재랄,저주글,조까,조빠,조쟁이,조지냐,조진다,조질래,존나,존니,좀물,좁년,좃,좆,좇,쥐랄,쥐롤,쥬디,지랄,지럴,지롤,지미랄,쫍빱,凸,퍽큐,뻑큐,빠큐,ㅅㅂㄹㅁ",
        "text",
        _("단어 필터링"),
        _("입력된 단어가 포함된 내용은 게시할 수 없습니다. 단어와 단어 사이는 ,로 구분합니다."),
    ),
    "cf_possible_ip": (
        "",
        "text",
        _("접근가능 IP"),
        _("입력된 IP의 컴퓨터만 접근할 수 있습니다.<br>123.123.+ 도 입력 가능. (엔터로 구분)"),
    ),
    "cf_intercept_ip": (
        "",
        "text",
        _("접근차단 IP"),
        _("입력된 IP의 컴퓨터는 접근할 수 없음.<br>123.123.+ 도 입력 가능. (엔터로 구분)"),
    ),
    "cf_user_skin": ("basic", "choices", _("회원 스킨")),
    "cf_use_homepage": ("0", "checkbox", _("홈페이지 입력 보이기")),
    "cf_req_homepage": ("0", "checkbox", _("홈페이지 입력 필수입력")),
    "cf_use_tel": ("0", "checkbox", _("전화번호 입력 보이기")),
    "cf_req_tel": ("0", "checkbox", _("전화번호 입력 필수입력")),
    "cf_use_hp": ("0", "checkbox", _("휴대폰번호 입력 보이기")),
    "cf_req_hp": ("0", "checkbox", _("휴대폰번호 입력 필수입력")),
    "cf_use_addr": ("0", "checkbox", _("주소 입력 보이기")),
    "cf_req_addr": ("0", "checkbox", _("주소 입력 필수입력")),
    "cf_use_signature": ("0", "checkbox", _("서명 입력 보이기")),
    "cf_req_signature": ("0", "checkbox", _("서명 입력 필수입력")),
    "cf_use_profile": ("0", "checkbox", _("자기소개 입력 보이기")),
    "cf_req_profile": ("0", "checkbox", _("자기소개 입력 필수입력")),
    "cf_register_level": ("2", "choices", _("회원가입시 권한")),
    "cf_register_point": (1000, "int", _("회원가입시 포인트")),
    "cf_icon_level": ("2", "choices", _("회원 아이콘, 이미지 업로드 권한")),
    "cf_use_recommend": ("0", "checkbox", _("추천인제도 사용")),
    "cf_recommend_point": (0, "int", _("추천인 포인트")),
    "cf_leave_day": (0, "int", _("회원탈퇴후 삭제일")),
    "cf_email_use": (1, "int", _("메일발송 사용")),
    "cf_email_wr_super_admin": ("0", "checkbox", _("최고관리자"), _("최고관리자에게 메일을 발송합니다.")),
    "cf_email_wr_group_admin": ("0", "checkbox", _("그룹관리자"), _("그룹관리자에게 메일을 발송합니다.")),
    "cf_email_wr_board_admin": ("0", "checkbox", _("게시판관리자"), _("게시판관리자에게 메일을 발송합니다.")),
    "cf_email_wr_write": ("0", "checkbox", _("원글작성자"), _("게시자님께 메일을 발송합니다.")),
    "cf_email_wr_comment_all": (
        "0",
        "checkbox",
        _("댓글작성자"),
        _("원글에 댓글이 올라오는 경우 댓글 쓴 모든 분들께 메일을 발송합니다."),
    ),
    "cf_email_mb_super_admin": (
        "0",
        "checkbox",
        _("최고관리자 메일발송"),
        _("회원가입시 최고관리자에게 메일을 발송합니다."),
    ),
    "cf_email_mb_user": ("0", "checkbox", _("회원님께 메일발송"), _("회원가입한 회원님께 메일을 발송합니다.")),
    "cf_email_po_super_admin": (
        "0",
        "checkbox",
        _("최고관리자 메일발송"),
        _("최고관리자에게 메일을 발송합니다."),
    ),
    "cf_prohibit_id": (
        "admin,administrator,관리자,운영자,어드민,주인장,webmaster,웹마스터,sysop,시삽,시샵,manager,매니저,메니저,root,루트,su,guest,방문객",
        "text",
        _("아이디,닉네임 금지단어"),
        _("회원아이디, 닉네임으로 사용할 수 없는 단어를 정합니다. 쉼표 (,) 로 구분"),
    ),
    "cf_prohibit_email": (
        "",
        "text",
        _("입력 금지 메일"),
        _("입력 받지 않을 도메인을 지정합니다. 엔터로 구분 ex) hotmail.com"),
    ),
    "cf_memo_del": (180, "int", _("쪽지 삭제"), _("설정일이 지난 쪽지 자동 삭제")),
    "cf_visit_del": (180, "int", _("접속자로그 삭제"), _("설정일이 지난 접속자 로그 자동 삭제")),
    "cf_popular_del": (180, "int", _("인기검색어 삭제"), _("설정일이 지난 인기검색어 자동 삭제")),
    "cf_use_user_icon": (
        "2",
        "choices",
        _("회원아이콘 사용"),
        _("게시물에 게시자 닉네임 대신 아이콘 사용"),
        CF_USE_USER_ICON_CHOICES,
    ),
    "cf_user_icon_size": (5000, "int", _("회원아이콘 용량")),
    "cf_user_icon_width": (22, "int", _("회원아이콘 사이즈 가로")),
    "cf_user_icon_height": (22, "int", _("회원아이콘 사이즈 세로")),
    "cf_user_img_size": (50000, "int", _("회원이미지 용량")),
    "cf_user_img_width": (60, "int", _("회원이미지 사이즈 가로")),
    "cf_user_img_height": (60, "int", _("회원이미지 사이즈 세로")),
    "cf_image_extension": (
        "gif|jpg|jpeg|png|webp",
        "str",
        _("이미지 업로드 확장자"),
        _("게시판 글작성시 이미지 파일 업로드 가능 확장자. | 로 구분"),
    ),
    "cf_movie_extension": (
        "asx|asf|wmv|wma|mpg|mpeg|mov|avi|mp3",
        "str",
        _("동영상 업로드 확장자"),
        _("게시판 글작성시 동영상 파일 업로드 가능 확장자. | 로 구분"),
    ),
    "cf_page_rows": (15, "int", _("한페이지당 라인수"), _("목록(리스트) 한페이지당 라인수")),
    "cf_mobile_page_rows": (15, "int", _("모바일 한페이지당 라인수"), _("모바일 목록 한페이지당 라인수")),
    "cf_visit": ("오늘:1,어제:0,최대:1,전체:1", "hidden", "방문자수를 기록"),
    "cf_max_po_id": ("0", "hidden", "큰 투표번호를 구해야 하는 쿼리를 대체"),
    "cf_stipulation": ("해당 홈페이지에 맞는 회원가입약관을 입력합니다.", "text", _("회원가입약관")),
    "cf_privacy": ("해당 홈페이지에 맞는 개인정보처리방침을 입력합니다.", "text", _("개인정보처리방침")),
    "cf_open_modify": (0, "int", _("정보공개수정"), _("해당 일동안 일 동안 바꿀 수 없음")),
    "cf_memo_send_point": (
        500,
        "int",
        _("쪽지보낼시 차감 포인트"),
        _("양수로 입력하십시오. 0점은 쪽지 보낼시 포인트를 차감하지 않습니다."),
    ),
    "cf_mobile_new_skin": ("basic", "choices", _("모바일 최근게시물 스킨")),
    "cf_mobile_search_skin": ("basic", "choices", _("모바일 검색 스킨")),
    "cf_mobile_connect_skin": ("basic", "choices", _("모바일 접속자 스킨")),
    "cf_mobile_faq_skin": ("basic", "choices", _("모바일 FAQ 스킨")),
    "cf_mobile_user_skin": ("basic", "choices", _("모바일 회원 스킨")),
    "cf_captcha": ("", "choices", _("캡챠 선택")),
    "cf_recaptcha_site_key": ("", "str", _("구글 reCAPTCHA Site key")),
    "cf_recaptcha_secret_key": ("", "str", _("구글 reCAPTCHA Secret key")),
    "cf_captcha_mp3": ("basic", "choices", _("음성캡챠 선택")),
    "cf_editor": (
        "tuieditor",
        "choices",
        _("에디터 선택"),
        "",
        [("", _("사용안함"))] + get_list_dir(EDITOR_DIR_NAME, PROJECT_BASE_DIR),
    ),
    "cf_cert_use": (0, "choices", _("본인확인")),
    "cf_cert_find": (
        0,
        "checkbox",
        _("회원정보찾기"),
        _("휴대폰/아이핀 본인확인을 이용하시다가 간편인증을 이용하시는 경우, 기존 회원은 아이디/비밀번호 찾기에 사용할 수 없을 수 있습니다."),
    ),
    "cf_cert_simple": (
        "",
        "choices",
        _("통합인증(간편인증)"),
        _(
            'KG이니시스의 통합인증(간편인증+전자서명) 서비스에서 전자서명을 제외한 간편인증 서비스 입니다. <a href="https://www.inicis.com/all-auth-service" target="_blank"><u>KG이니시스 통합인증 안내</u></a>'
        ),
    ),
    "cf_cert_hp": (
        "",
        "choices",
        _("휴대폰 본인확인"),
        _("휴대폰 본인확인 provider를 선택합니다. 지원값: kcp, kcp_v2"),
    ),
    "cf_cert_ipin": (
        "",
        "choices",
        _("아이핀 본인확인"),
        _("아이핀 본인확인 provider를 선택합니다. Django/Next.js 브리지에서는 현재 버튼 노출에만 사용합니다."),
    ),
    "cf_cert_kg_cd": ("", "str", _("KG이니시스 간편인증 API KEY")),
    "cf_cert_kg_mid": ("", "str", _("KG이니시스 간편인증 MID")),
    "cf_cert_limit": ("", "int", _("본인확인 이용제한")),
    "cf_cert_req": (
        "0",
        "checkbox",
        _("본인확인 필수"),
        _("회원가입 때 본인확인을 필수로 할지 설정합니다. 필수로 설정하시면 본인확인을 하지 않은 경우 회원가입이 안됩니다."),
    ),
    "cf_social_login_use": ("0", "checkbox", _("소셜로그인사용"), _("체크시 소셜로그인을 사용합니다.")),
    "cf_social_servicelist": (
        "0",
        "checkbox",
        _("소셜로그인설정"),
        _("체크시 해당 서비스사 소셜로그인을 사용합니다."),
    ),
    "cf_payco_clientid": ("", "str", _("페이코 Client ID")),
    "cf_payco_secret": ("", "str", _("페이코 Secret")),
    "cf_facebook_appid": ("", "str", _("페이스북 앱 ID")),
    "cf_facebook_secret": ("", "str", _("페이스북 앱 Secret")),
    "cf_twitter_key": ("", "str", _("트위터 컨슈머 Key")),
    "cf_twitter_secret": ("", "str", _("트위터 컨슈머 Secret")),
    "cf_google_clientid": ("", "str", _("구글 Client ID")),
    "cf_google_secret": ("", "str", _("구글 Client Secret")),
    "cf_naver_clientid": ("", "str", _("네이버 Client ID")),
    "cf_naver_secret": ("", "str", _("네이버 Client Secret")),
    "cf_kakao_rest_key": ("", "str", _("카카오 REST API 키")),
    "cf_kakao_client_secret": ("", "str", _("카카오 Client Secret")),
    "cf_kakao_js_apikey": ("", "str", _("카카오 JavaScript 키")),
}

ADDITIONAL_FIELDS = getattr(settings, "DEFAULTS_ADDITIONAL_FIELDS", {})

SUPERUSER_ONLY = getattr(settings, "DEFAULTS_SUPERUSER_ONLY", True)

DATABASE_PREFIX = getattr(settings, "DEFAULTS_DATABASE_PREFIX", "")

# TEMPLATES_DIR_NAME = getattr(settings, 'DEFAULTS_TEMPLATES_DIR_NAME', 'templates')

USER_SKIN_DIR = getattr(settings, "DEFAULTS_USER_SKIN_DIR", "user")
MOBILE_DIR = getattr(settings, "DEFAULTS_MOBILE_DIR", "mobile")
SKIN_DIR = getattr(settings, "DEFAULTS_SKIN_DIR", "skin")
MOBILE_SKIN_DIR = getattr(settings, "DEFAULTS_MOBILE_DIR", "mobile_skin")
THEME_DIR = getattr(settings, "DEFAULTS_THEME_DIR", "theme")
BBS_FILE_DIR = getattr(settings, "BBS_FILE_DIR", "file")

PROJECT_PATH = getattr(settings, "DEFAULTS_PROJECT_PATH", Path(__file__).resolve().parent)
TEMPLATE_PATH = getattr(
    settings, "DEFAULTS_TEMPLATE_PATH", os.path.join(PROJECT_PATH, "templates/")
)
SKIN_PATH = getattr(settings, "DEFAULTS_SKIN_PATH", os.path.join(TEMPLATE_PATH, SKIN_DIR + "/"))

NICKNAME_LEN = getattr(settings, "DEFAULTS_NICKNAME_LEN", 10)

HOME_URL = reverse_lazy("index")
# 관리자 URL
ADMIN_URL = reverse_lazy("admin:index")
# 로그인 URL (Next.js 화면)
LOGIN_URL = "/login"
# 로그아웃 URL (Next.js 화면은 API로 로그아웃하므로 홈으로 보낸다)
LOGOUT_URL = "/"
# 회원가입 URL (Next.js 화면)
REGISTER_URL = "/register"

SERVER_TIME = datetime.now()
TIME_YMD = SERVER_TIME.strftime("%Y-%m-%d")
TIME_YMDHIS = SERVER_TIME.strftime("%Y-%m-%d %H:%M:%S")

BBS_LINK_COUNT = getattr(settings, "DEFAULTS_BBS_LINK_COUNT", 2)

GNU_IP_DISPLAY = getattr(settings, "DEFAULTS_GNU_IP_DISPLAY", "\\1.♡.\\3.\\4")

# Cookies
COOKIES_DELETE_ON_LOGOUT = [
    "recently_viewed_products",
]

IGNORE_ADMIN_VERSION_CHECK = getattr(settings, "DEFAULTS_IGNORE_ADMIN_VERSION_CHECK", False)

REDIS_CONNECTION_CLASS = getattr(settings, "DEFAULTS_REDIS_CONNECTION_CLASS", None)

# Cache
REDIS_PREFIX = getattr(settings, "DEFAULTS_REDIS_PREFIX", "gnu_jango:")

# Cache ttl 을 1시간으로 고정
CACHE_TIMEOUT = getattr(settings, "DEFAULTS_CACHE_TIMEOUT", 3600)

# Cache 사용여부
USE_CACHE = getattr(settings, "DEFAULTS_USE_CACHE", 1)

# Cache 최신글 rows 지정
BBS_CACHE_ROWS = getattr(settings, "DEFAULTS_BBS_CACHE_ROWS", 10)
