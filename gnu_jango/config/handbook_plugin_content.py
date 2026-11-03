"""Handbook chapters for the plugin system added in November 2026: installing and switching plugins,
the 출석체크 example plugin, writing a plugin, hooks and theme slots. The developer reference is
docs/04-deploy/plugins.md; keep the two in step."""

PLUGIN_BOOK_TABLE = "hb_plugins"
PLUGIN_BOOK_TITLE = "확장 기능 · 플러그인과 출석체크"

# Existing sample chapters that should point readers at this book. Like the other books' links, the
# seed command appends a small link block once and never rewrites the rest of the chapter.
PLUGIN_LINK_TITLES = (
    "폴더 구조",
    "슬롯 끼우기",
    "환경 변수",
)
PLUGIN_LINK_MARKER = "<!-- plugin-guide-link -->"
PLUGIN_LINK_HTML = (
    '<p><strong>함께 보기:</strong> '
    '<a href="/bbs/hb_plugins">플러그인과 출석체크</a></p>'
)

PLUGIN_BOOK_PARTS = (
    ("먼저 읽기", ("플러그인 한눈에 보기",)),
    ("운영자용", ("플러그인 설치하고 켜고 끄기", "출석체크 플러그인 운영하기", "주문 알림 플러그인 운영하기")),
    ("개발자용", ("플러그인 만들기", "hook으로 코어 동작에 끼어들기", "테마 슬롯에 위젯 넣기")),
)

PLUGIN_GUIDES = {
    "플러그인 한눈에 보기": {
        "intro": (
            "플러그인은 코어(gnu_jango 폴더)를 고치지 않고 사이트에 기능을 더하는 방법입니다. 플러그인 하나는 보통의 "
            "Django 앱이고, {{G5_PLUGINS}} 환경 변수에 적은 것만 설치됩니다. 함께 들어 있는 예제는 출석체크입니다."
        ),
        "sections": [
            {
                "heading": "플러그인이 할 수 있는 일",
                "bullets": [
                    "자기 화면과 API 주소를 가집니다. 화면은 {{/plugins/<slug>/}}, API는 {{/api/v1/plugins/<slug>/}} 아래에 연결됩니다.",
                    "관리자 사이드바 맨 아래 ‘플러그인’ 그룹에 메뉴를 더합니다.",
                    "매일·매시간 도는 예약 작업을 등록합니다. 사이트의 다른 예약 작업과 함께 실행됩니다.",
                    "관리자 ‘플러그인 관리’ 화면에 설정 입력 칸을 만듭니다. 값을 바꿀 때 다시 배포할 필요가 없습니다.",
                    "hook으로 로그인·주문 같은 코어의 일을 전달받거나, 출석 포인트 같은 값을 바꿉니다.",
                    "기본 테마 홈 화면의 정해진 자리(슬롯)에 작은 위젯 상자를 넣습니다.",
                ],
            },
            {
                "heading": "설치와 켜고 끄기는 다른 일입니다",
                "paragraphs": [
                    "설치는 서버를 관리하는 사람이 합니다. {{G5_PLUGINS}}에 플러그인을 적어 배포하고 {{python manage.py migrate}}로 "
                    "플러그인 테이블을 만듭니다.",
                    "설치한 다음의 켜고 끄기와 설정 변경은 관리자 화면에서 합니다. 슈퍼유저가 {{/admin/plugins/}}에서 바꾸면 "
                    "다시 배포하지 않아도 곧바로 반영됩니다.",
                ],
                "note": "플러그인을 설치하지 않으면 사이트는 이전과 똑같이 동작합니다.",
            },
            {
                "heading": "어떤 장을 읽으면 되나요?",
                "bullets": [
                    "운영자: ‘플러그인 설치하고 켜고 끄기’ 다음 ‘출석체크 플러그인 운영하기’를 읽습니다.",
                    "개발자: ‘플러그인 만들기’, ‘hook으로 코어 동작에 끼어들기’, ‘테마 슬롯에 위젯 넣기’를 차례로 읽습니다. "
                    "저장소의 {{docs/04-deploy/plugins.md}}에 같은 내용이 개발자용 참고 문서로 있습니다.",
                ],
                "note": "플러그인은 코어와 같은 권한으로 실행되는 Python 코드입니다. 직접 만들었거나 믿을 수 있는 코드만 설치하세요.",
            },
        ],
    },
    "플러그인 설치하고 켜고 끄기": {
        "intro": (
            "출석체크 예제 플러그인을 설치하고, 관리자 화면에서 켜고 끄고, 설정을 바꾸는 순서입니다. 명령은 manage.py가 "
            "있는 저장소 루트에서 실행합니다."
        ),
        "sections": [
            {
                "heading": "설치하기",
                "steps": [
                    "{{.env}} 또는 배포 환경 변수에 {{G5_PLUGINS=gnu_plugins.attendance}}를 추가합니다. 여러 개는 쉼표로 나눕니다.",
                    "사이트를 다시 배포하거나 서버를 다시 시작합니다.",
                    "{{python manage.py migrate}}로 플러그인 테이블을 만듭니다. 배포한 DB마다 한 번씩 필요합니다.",
                    "{{python manage.py check}}로 플러그인 선언을 확인합니다. 선언이 잘못되면 여기서 오류 메시지와 함께 멈춥니다.",
                    "관리자에 로그인해 사이드바 ‘플러그인 › 플러그인 관리’에 출석체크가 ‘켜짐’으로 보이는지 확인합니다.",
                ],
                "code": "G5_PLUGINS=gnu_plugins.attendance\n\npython manage.py migrate\npython manage.py check",
                "note": (
                    "migrate 전에는 출석 API와 출석 기록 화면이 쓸 테이블이 없습니다. 배포 직후 migrate를 먼저 실행하세요. "
                    "Vercel처럼 실행 중에 패키지를 설치할 수 없는 곳에서는 플러그인 코드를 저장소에 두거나 requirements.txt에 넣어 배포합니다."
                ),
            },
            {
                "heading": "관리자 화면에서 켜고 끄기",
                "steps": [
                    "슈퍼유저 계정으로 관리자에 로그인합니다. 이 화면은 슈퍼유저에게만 보입니다.",
                    "사이드바 ‘플러그인 › 플러그인 관리’({{/admin/plugins/}})를 엽니다.",
                    "플러그인마다 ‘켜짐’ 또는 ‘꺼짐’이 표시됩니다. ‘끄기’나 ‘켜기’를 누르면 곧바로 바뀝니다.",
                ],
                "paragraphs": [
                    "설치한 플러그인은 켜진 상태로 시작합니다. 상태는 사이트 설정 테이블에 {{plugin.<slug>.enabled}}라는 이름으로 "
                    "저장되어 다른 설정처럼 변경 이력에 남습니다.",
                ],
            },
            {
                "heading": "끈 플러그인은 어떻게 되나요?",
                "bullets": [
                    "플러그인의 화면과 API 주소가 404를 돌려줍니다.",
                    "hook 리스너가 실행되지 않습니다. 예를 들어 방문해도 자동 출석이 되지 않습니다.",
                    "예약 작업이 실행되지 않고 ‘skipped’로 기록됩니다. 실패로 세지 않으므로 경고가 생기지 않습니다.",
                    "홈 화면의 위젯 상자와 사이드바 ‘플러그인’ 그룹의 링크가 사라집니다.",
                    "쌓인 기록은 지워지지 않습니다. 관리자 ‘모든 애플리케이션’ 목록에서 계속 볼 수 있고, 다시 켜면 이어서 동작합니다.",
                ],
            },
            {
                "heading": "설정 바꾸기",
                "steps": [
                    "‘플러그인 관리’ 화면의 플러그인 상자에서 설정 칸을 고칩니다. 켜고 끄는 값은 체크박스, 숫자는 숫자 칸입니다.",
                    "‘설정 저장’을 누릅니다. 숫자 칸에 숫자가 아닌 값이 있으면 아무것도 저장하지 않고 어느 칸인지 알려 줍니다.",
                    "칸 아래에 ‘관리자 저장값’ 또는 ‘기본값’이 표시되어 지금 어떤 값을 쓰는지 알 수 있습니다.",
                ],
                "paragraphs": [
                    "값은 관리자 저장값 → Django settings → 같은 이름의 환경 변수 → 플러그인 기본값 순서로 정해집니다. 서버 관리자가 "
                    "환경 변수로 사이트 기본값을 정해 두고, 운영자가 필요할 때 관리자 화면에서 바꾸는 식으로 함께 쓸 수 있습니다.",
                ],
            },
            {
                "heading": "플러그인을 완전히 없애기",
                "steps": [
                    "테이블까지 지우려면 먼저 {{python manage.py migrate attendance zero}}를 실행합니다. 출석 기록이 모두 지워지므로 필요하면 DB를 백업합니다.",
                    "{{G5_PLUGINS}}에서 플러그인을 지우고 다시 배포합니다.",
                ],
                "note": "1단계를 건너뛰면 테이블과 출석 기록은 DB에 그대로 남습니다. 회원에게 준 포인트는 어느 경우에도 포인트 내역에 남습니다.",
            },
        ],
    },
    "출석체크 플러그인 운영하기": {
        "intro": (
            "출석체크는 로그인한 회원이 하루 한 번 출석하고 포인트를 받는 예제 플러그인입니다. 회원에게 보이는 화면, 포인트 "
            "규칙, 설정, 기록 확인과 개근 보너스 작업을 설명합니다."
        ),
        "sections": [
            {
                "heading": "회원에게 보이는 것",
                "bullets": [
                    "기본 테마 커뮤니티 홈의 오른쪽, 로그인 상자 바로 아래에 ‘출석체크’ 상자가 나타납니다.",
                    "로그인하지 않은 방문자에게는 받을 포인트와 ‘로그인’ 버튼이 보입니다.",
                    "로그인한 회원에게는 연속 출석일, 이번 달 출석일과 ‘출석하기’ 버튼이 보입니다.",
                    "출석하면 상자가 ‘오늘 출석을 마쳤어요.’로 바뀝니다. 출석은 하루에 한 번만 됩니다.",
                ],
                "note": "이 상자는 기본 테마(nextjs_default) 홈에만 있습니다. 이 매뉴얼 사이트가 쓰는 핸드북 테마에는 이 자리가 없습니다.",
            },
            {
                "heading": "포인트 규칙",
                "bullets": [
                    "출석할 때마다 출석 포인트(기본 10)를 줍니다.",
                    "연속 출석 기준 일수(기본 7)의 배수가 되는 날, 즉 7일째·14일째·21일째에는 연속 출석 보너스(기본 50)를 더 줍니다. 하루라도 빠지면 연속 출석은 1일부터 다시 셉니다.",
                    "한 달 동안 하루도 빠짐없이 출석한 활성 회원에게는 다음 달에 개근 보너스(기본 300)를 한 번 줍니다.",
                    "포인트는 사이트 포인트 내역에 ‘2026-11-03 출석체크’, ‘2026-10 개근 보너스’처럼 남고, 같은 날이나 같은 달에 두 번 지급되지 않습니다.",
                    "관리자 기본환경설정의 ‘포인트 사용’이 꺼져 있으면 출석만 기록하고 포인트는 주지 않습니다.",
                    "날짜는 사이트 시간대(한국 사이트라면 한국 시간 자정) 기준으로 바뀝니다.",
                ],
            },
            {
                "heading": "설정 항목",
                "paragraphs": ["관리자 ‘플러그인 › 플러그인 관리’의 출석체크 상자에서 바꿉니다."],
                "bullets": [
                    "출석 포인트({{ATTENDANCE_POINT}}): 기본 10",
                    "연속 출석 기준 일수({{ATTENDANCE_STREAK_DAYS}}): 기본 7. 0이면 연속 출석 보너스가 없습니다.",
                    "연속 출석 보너스({{ATTENDANCE_STREAK_BONUS}}): 기본 50",
                    "개근 보너스({{ATTENDANCE_MONTHLY_BONUS}}): 기본 300",
                    "방문하면 자동 출석({{ATTENDANCE_AUTO_CHECK_IN}}): 기본 꺼짐. 켜면 회원이 로그인하거나, 로그인한 상태로 사이트를 열 때 버튼을 누르지 않아도 출석됩니다.",
                ],
            },
            {
                "heading": "출석 기록 보기",
                "paragraphs": [
                    "관리자 사이드바 ‘플러그인 › 출석체크 기록’에서 회원별 출석일, 연속 출석일, 그날 지급한 포인트를 봅니다. "
                    "기록은 읽기 전용입니다. 이 메뉴는 슈퍼유저와 출석체크 기록 보기 권한이 있는 직원에게만 보입니다.",
                ],
            },
            {
                "heading": "개근 보너스 예약 작업",
                "paragraphs": [
                    "개근 보너스는 매일 한 번 도는 예약 작업 {{attendance_monthly_bonus}}가 줍니다. 사이트에 이미 설정한 예약 작업 "
                    "실행 방식(크론, Celery Beat)과 함께 실행되므로 따로 등록할 필요가 없습니다.",
                    "작업은 최근에 끝난 3개월을 매번 다시 확인합니다. 작업이 며칠 멈췄거나 그동안 포인트 사용이 꺼져 있었어도, 3개월 "
                    "안이면 나중에 지급합니다. 이미 받은 보너스는 다시 주지 않습니다.",
                ],
                "code": (
                    "python manage.py attendance_monthly_bonus                          # 지급 대상만 세기\n"
                    "python manage.py attendance_monthly_bonus --apply                  # 최근 3개월 지급\n"
                    "python manage.py attendance_monthly_bonus --month 2026-10 --apply  # 한 달만 지급"
                ),
            },
            {
                "heading": "자주 묻는 질문",
                "bullets": [
                    "홈에 출석체크 상자가 보이지 않아요: {{G5_PLUGINS}}에 넣고 배포했는지, ‘플러그인 관리’에서 켜져 있는지, 사이트가 기본 테마인지 확인합니다.",
                    "출석했는데 포인트가 늘지 않아요: 기본환경설정의 ‘포인트 사용’과 출석 포인트 값이 0이 아닌지 확인합니다.",
                    "회원이 출석 버튼을 여러 번 눌렀어요: 하루 한 번만 기록되고 포인트도 한 번만 지급됩니다.",
                    "출석 API를 너무 자주 부르면 429 응답이 옵니다: 회원 한 명이 분당 60번까지 부를 수 있습니다.",
                ],
            },
        ],
    },
    "주문 알림 플러그인 운영하기": {
        "intro": (
            "주문 알림은 새 주문, 결제 완료, 취소·반품을 디스코드·슬랙·텔레그램 채널로 바로 알려 주는 플러그인입니다. 채널 "
            "연결, 보낼 알림 고르기, 보내기 실패와 재발송, 기록 확인을 설명합니다."
        ),
        "sections": [
            {
                "heading": "채널 연결하기",
                "paragraphs": [
                    "알림을 받을 주소는 관리자 화면이 아니라 배포 환경 변수에만 넣습니다. 웹후크 주소나 봇 토큰을 아는 사람은 누구나 "
                    "그 채널에 글을 올릴 수 있으므로 화면과 DB에 남기지 않습니다. 여러 채널을 넣으면 모두에게 보냅니다.",
                ],
                "bullets": [
                    "디스코드: 채널 설정 › 연동 › 웹후크에서 만든 주소를 {{ORDER_NOTIFY_DISCORD_WEBHOOK_URL}}에 넣습니다.",
                    "슬랙: Incoming Webhooks로 만든 https://hooks.slack.com/services/… 주소를 {{ORDER_NOTIFY_SLACK_WEBHOOK_URL}}에 넣습니다.",
                    "텔레그램: BotFather로 만든 봇 토큰을 {{ORDER_NOTIFY_TELEGRAM_BOT_TOKEN}}에, 봇을 초대한 채팅방 ID를 {{ORDER_NOTIFY_TELEGRAM_CHAT_ID}}에 넣습니다. 둘 다 있어야 보냅니다.",
                ],
                "code": (
                    "# .env 또는 배포 환경 변수\n"
                    "G5_PLUGINS=gnu_plugins.attendance,gnu_plugins.order_notify\n"
                    "ORDER_NOTIFY_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/…\n\n"
                    "python manage.py migrate            # 알림 기록 테이블 만들기\n"
                    "python manage.py order_notify_test  # 설정한 채널마다 테스트 알림 보내기"
                ),
                "note": "서비스 주소가 아닌 값(오타, 다른 도메인, http://)은 무시하고 보내지 않습니다. 어느 값이 잘못됐는지는 order_notify_test가 알려 줍니다.",
            },
            {
                "heading": "알림 내용",
                "bullets": [
                    "첫 줄에 무슨 일인지와 주문번호가 나옵니다. 예: ‘🛒 새 주문 · 2026110312345’, ‘💳 결제 완료 · …’, ‘↩️ 취소·반품 · …’.",
                    "둘째 줄에 결제 금액, 결제 수단, 주문자 이름이 나옵니다. 이름은 기본으로 ‘홍*동’처럼 가운데를 가립니다.",
                    "취소·반품과 상태 변경은 ‘입금 → 취소’처럼 바뀐 상태를 함께 보여 줍니다.",
                    "첫 상품 이름(여러 개면 ‘외 N건’)과, 사이트 주소({{SOCIAL_APP_BASE_URL}})가 설정되어 있으면 관리자 주문 화면 링크가 붙습니다.",
                    "주소, 연락처, 이메일은 보내지 않습니다.",
                ],
            },
            {
                "heading": "보낼 알림 고르기",
                "paragraphs": ["관리자 ‘플러그인 › 플러그인 관리’의 주문 알림 상자에서 바꿉니다."],
                "bullets": [
                    "새 주문 알림({{ORDER_NOTIFY_PLACED}}): 기본 켜짐. 주문이 만들어지면 보냅니다.",
                    "결제 완료 알림({{ORDER_NOTIFY_PAID}}): 기본 켜짐. 카드 결제가 끝나거나 무통장 입금을 확인하면 보냅니다.",
                    "취소·반품 알림({{ORDER_NOTIFY_CANCELLED}}): 기본 켜짐. 고객·관리자 취소, 결제 기한 만료, 반품 때 보냅니다.",
                    "그 밖의 상태 변경 알림({{ORDER_NOTIFY_OTHER_STATUS}}): 기본 꺼짐. 켜면 준비·배송·완료로 바꿀 때도 보냅니다.",
                    "주문자 이름 전체 표시({{ORDER_NOTIFY_FULL_NAME}}): 기본 꺼짐. 켜면 이름을 가리지 않습니다.",
                ],
                "note": "카드 주문은 ‘새 주문’과 ‘결제 완료’가 거의 동시에 옵니다. 결제된 주문만 받으려면 새 주문 알림을 끄세요.",
            },
            {
                "heading": "보내기 실패와 재발송",
                "bullets": [
                    "알림은 주문이 저장된 직후 보냅니다. 채널이 3초 안에 답하지 않거나 일시 오류(429, 5xx)를 돌려주면 ‘보낼 예정’으로 남습니다.",
                    "5분마다 도는 예약 작업 {{order_notify_retry}}가 남은 알림을 다시 보냅니다. 한 알림은 24시간 안에 최대 5번까지 시도합니다.",
                    "한 채널이 응답하지 않으면 그 뒤 5분 동안은 주문 처리 중에 그 채널을 기다리지 않고 바로 예약 작업에 맡깁니다. 채널이 멈춰도 주문 화면이 느려지지 않습니다.",
                    "웹후크를 지웠거나 채팅방 ID가 틀린 경우(그 밖의 4xx)는 다시 보내도 소용이 없어 바로 ‘실패’로 남깁니다.",
                    "알림이 실패해도 주문, 결제, 취소는 그대로 처리됩니다.",
                    "같은 주문의 같은 알림은 채널마다 한 번만 보냅니다.",
                ],
            },
            {
                "heading": "알림 기록 보기",
                "paragraphs": [
                    "관리자 사이드바 ‘플러그인 › 주문 알림 기록’에서 주문번호, 알림 종류, 채널, 상태, 시도 횟수와 마지막 오류를 "
                    "봅니다. 실패한 알림을 고르고 ‘선택한 알림 다시 보내기’를 실행하면 바로 다시 보냅니다. 이미 보낸 알림은 건너뜁니다.",
                ],
            },
            {
                "heading": "자주 묻는 질문",
                "bullets": [
                    "알림이 오지 않아요: {{order_notify_test}}로 채널 설정부터 확인하고, ‘플러그인 관리’에서 주문 알림이 켜져 있는지 봅니다.",
                    "‘마지막 오류’에 HTTP 404가 있어요: 디스코드·슬랙에서 웹후크가 지워졌습니다. 새로 만든 주소로 환경 변수를 바꾸고 다시 배포합니다.",
                    "‘마지막 오류’에 HTTP 403이나 400이 있어요(텔레그램): 봇이 채팅방에 들어 있는지, 채팅방 ID가 맞는지 확인합니다.",
                ],
            },
        ],
    },
    "플러그인 만들기": {
        "intro": (
            "새 플러그인은 출석체크 예제 폴더를 복사해서 시작하는 것이 가장 쉽습니다. 이 장은 폴더 구성, 코어에 무엇을 "
            "연결할지 적는 plugin.py, 설정값 읽기와 테스트를 설명합니다."
        ),
        "sections": [
            {
                "heading": "폴더 구성",
                "code": (
                    "gnu_plugins/attendance/\n"
                    "├── plugin.py      # PLUGIN = Plugin(...)  코어가 연결할 것\n"
                    "├── apps.py        # AppConfig. ready()에서 listeners를 import\n"
                    "├── models.py, migrations/, admin.py\n"
                    "├── listeners.py   # hook 리스너\n"
                    "├── widgets.py     # 테마 슬롯 위젯\n"
                    "├── api.py, api_urls.py\n"
                    "├── management/commands/attendance_monthly_bonus.py\n"
                    "└── tests.py"
                ),
            },
            {
                "heading": "새 플러그인 시작하기",
                "steps": [
                    "{{gnu_plugins/attendance/}}를 {{gnu_plugins/<새 이름>/}}으로 복사합니다.",
                    "{{apps.py}}의 {{name}}과 {{label}}, {{plugin.py}}의 {{slug}}와 {{title}}을 새 이름으로 바꾸고 필요 없는 파일을 지웁니다.",
                    "모델을 고친 뒤 복사해 온 migrations 폴더의 파일을 지우고 {{python manage.py makemigrations <label>}}로 새로 만듭니다.",
                    "{{G5_PLUGINS}}에 {{gnu_plugins.<새 이름>}}을 더하고 {{python manage.py check}}와 {{migrate}}를 실행합니다.",
                ],
            },
            {
                "heading": "plugin.py에 적는 것",
                "code": (
                    "from gnu_jango.plugins import AdminLink, Job, Plugin, Setting, Slot\n\n"
                    "PLUGIN = Plugin(\n"
                    "    slug=\"attendance\",\n"
                    "    title=\"출석체크\",\n"
                    "    version=\"1.0.0\",\n"
                    "    api_version=1,\n"
                    "    api_urls=\"gnu_plugins.attendance.api_urls\",\n"
                    "    admin_links=(AdminLink(\"출석체크 기록\", \"admin:attendance_attendance_changelist\",\n"
                    "                           icon=\"event_available\", permission=\"attendance.view_attendance\"),),\n"
                    "    jobs=(Job(\"attendance_monthly_bonus\", (\"--apply\", \"--json\"), (\"--json\",), 86400),),\n"
                    "    settings=(Setting(\"ATTENDANCE_POINT\", \"출석 포인트\", 10, \"출석할 때마다 주는 포인트\"),),\n"
                    "    slots=(Slot(\"home.sidebar\", \"gnu_plugins.attendance.widgets.home_widget\"),),\n"
                    ")"
                ),
                "bullets": [
                    "{{slug}}: 주소와 설정 이름에 쓰입니다. 영문 소문자로 시작하고 소문자·숫자·밑줄로 2~30자, 다른 플러그인과 겹치면 안 됩니다. {{slots}}는 코어가 쓰므로 쓸 수 없습니다.",
                    "{{api_version}}: 반드시 적습니다. 코어의 플러그인 규격 버전(지금 1)과 다르면 사이트가 시작할 때 오류로 멈춥니다. 규격이 바뀐 줄 모르고 잘못 동작하는 일을 막기 위해서입니다.",
                    "{{urls}}와 {{api_urls}}: 각각 {{/plugins/<slug>/}}와 {{/api/v1/plugins/<slug>/}}에 연결됩니다. API의 URL 이름은 {{api_v1:<app_name>:<name>}}입니다.",
                    "{{admin_links}}: 사이드바 ‘플러그인’ 그룹의 메뉴입니다. {{permission}}을 적으면 그 권한이 있는 직원에게만 보입니다.",
                    "{{jobs}}: 예약 작업입니다. 관리 명령 이름, 실제 실행 인자, 점검(dry-run)용 인자, 실행 간격(초) 순서입니다. 코어 작업과 이름이 겹치면 시작할 때 오류가 납니다.",
                    "{{settings}}: ‘플러그인 관리’ 화면의 설정 칸입니다. 기본값이 True/False면 체크박스, 정수면 숫자 칸, 글자면 글자 칸이 됩니다.",
                    "{{slots}}: 테마 슬롯 위젯입니다. ‘테마 슬롯에 위젯 넣기’ 장에서 설명합니다.",
                ],
                "note": "plugin.py는 Django가 설정을 읽는 도중에 읽힙니다. 이 파일에서 모델이나 앱 레지스트리가 필요한 코드를 import하면 사이트가 시작하지 못합니다.",
            },
            {
                "heading": "설정값 읽기와 API 만들기",
                "bullets": [
                    "설정값은 {{gnu_jango.plugins.state.setting(\"attendance\", \"ATTENDANCE_POINT\")}}처럼 읽습니다. 관리자 저장값 → Django settings → 환경 변수 → 기본값 순서로 정해지고 1분 동안 캐시됩니다. 관리자 화면에서 저장하면 캐시가 바로 비워집니다.",
                    "플러그인 API는 코어 API 계약({{openapi/schema.json}})에 넣지 않습니다. 뷰에 {{@extend_schema(exclude=True)}}를 붙입니다.",
                    "응답은 코어와 같은 {{api_response}}·{{api_error}} 형식을 쓰고, 로그인이 필요한 API에는 권한 검사와 요청 횟수 제한을 붙입니다. 출석체크의 {{api.py}}가 예입니다.",
                ],
            },
            {
                "heading": "테스트",
                "paragraphs": [
                    "pytest는 {{gnu_plugins}} 폴더의 테스트도 함께 찾습니다. 출석체크 예제는 {{.env}}와 상관없이 늘 함께 설치되어 "
                    "테스트되므로, 코어의 플러그인 연결 지점이 깨지면 바로 알 수 있습니다.",
                    "새 플러그인은 테스트할 때도 {{G5_PLUGINS}}에 넣어야 설치됩니다.",
                ],
                "code": "G5_PLUGINS=gnu_plugins.<새 이름> python -m pytest gnu_plugins/<새 이름>",
            },
        ],
    },
    "hook으로 코어 동작에 끼어들기": {
        "intro": (
            "hook은 코어가 정해진 순간에 보내는 신호입니다. 플러그인은 신호를 받아 일을 하거나(이벤트), 코어가 넘겨준 값을 "
            "고쳐서 돌려줍니다(값 바꾸기). 그누보드5의 run_event와 run_replace와 같은 역할입니다."
        ),
        "sections": [
            {
                "heading": "리스너 등록하기",
                "code": (
                    "from gnu_jango.plugins import hooks\n\n"
                    "@hooks.on(\"member.visited\")                 # 이벤트: 반환값은 쓰지 않음\n"
                    "def check_in_on_visit(user, **kwargs): ...\n\n"
                    "@hooks.on(\"attendance.point\", priority=20)  # 값 바꾸기: 받은 값을 고쳐서 돌려줌\n"
                    "def double_on_weekends(point, user, streak, day, **kwargs):\n"
                    "    return point * 2 if day.weekday() >= 5 else point"
                ),
                "paragraphs": [
                    "리스너는 {{listeners.py}}에 두고 {{apps.py}}의 {{ready()}}에서 import해 등록합니다.",
                ],
            },
            {
                "heading": "리스너를 쓸 때 지킬 것",
                "bullets": [
                    "{{priority}}가 작은 리스너부터 실행됩니다. 기본값은 10입니다.",
                    "리스너는 하나씩 savepoint 안에서 실행됩니다. 리스너가 오류를 내면 로그만 남기고 다음 리스너로 넘어가며, 그 리스너가 한 DB 작업은 되돌립니다. 값 바꾸기 리스너가 실패하면 직전 값을 그대로 씁니다. 그래서 플러그인 오류가 로그인이나 결제를 깨뜨리지 않습니다.",
                    "리스너는 요청 안에서 바로 실행됩니다. 외부 API 호출처럼 오래 걸리는 일은 백그라운드 작업으로 넘깁니다.",
                    "앞으로 인자가 늘어날 수 있으므로 리스너는 항상 {{**kwargs}}를 받습니다.",
                    "‘플러그인 관리’에서 끈 플러그인의 리스너는 실행되지 않습니다.",
                ],
            },
            {
                "heading": "코어가 보내는 hook",
                "bullets": [
                    "{{member.visited}}(user, request): 비밀번호·소셜 로그인 때와, 로그인한 회원이 사이트를 열 때 옵니다. 하루에도 여러 번 오므로 리스너가 중복을 스스로 막아야 합니다.",
                    "{{shop.order.placed}}(order): 주문이 만들어졌을 때. 체크아웃과 정기구독 결제 주문 모두 해당합니다.",
                    "{{shop.order.status_changed}}(order, old_status, new_status, source): 주문 상태가 바뀔 때. {{source}}는 결제 확정이면 {{payment}}, 관리자가 다음 단계로 옮기면 {{admin}}, 취소·반품이면 {{cancel}}입니다.",
                    "{{shop.order.paid}}(order, source): 주문이 입금 상태가 됐을 때. 같은 변경의 status_changed 바로 뒤에 옵니다.",
                ],
            },
            {
                "heading": "주문 hook을 받을 때 알아 둘 것",
                "paragraphs": [
                    "주문 hook은 변경이 DB에 확정(커밋)된 뒤에 보냅니다. 결제나 취소가 중간에 되돌려지면 아무것도 보내지 않습니다. "
                    "PG사가 같은 결제 확정을 다시 보내도 상태가 바뀌지 않았으면 hook도 다시 오지 않습니다.",
                    "리스너가 받은 {{order}}는 확정된 값이지만, 그 사이 다른 요청이 바꿨을 수 있습니다. 최신 값이 필요하면 "
                    "{{order.refresh_from_db()}}를 부릅니다.",
                ],
            },
            {
                "heading": "출석체크가 보내는 hook",
                "bullets": [
                    "{{attendance.point}}(point, user, streak, day): 값 바꾸기. 출석 포인트를 고칠 수 있습니다. 숫자가 아닌 값을 돌려주면 무시하고, 음수는 0으로 바꿉니다.",
                    "{{attendance.checked_in}}(attendance): 이벤트. 출석이 새로 기록될 때마다 옵니다.",
                ],
                "note": "다른 플러그인도 이처럼 자기 hook을 만들어 보낼 수 있습니다. 이름은 플러그인 slug로 시작하면 겹치지 않습니다.",
            },
        ],
    },
    "테마 슬롯에 위젯 넣기": {
        "intro": (
            "테마 슬롯은 테마 화면에 미리 만들어 둔 자리입니다. 플러그인은 이 자리에 들어갈 위젯을 HTML이 아닌 데이터로 "
            "돌려주고, 테마가 그 데이터를 공통 모양으로 그립니다. 그래서 플러그인을 추가해도 테마를 다시 빌드하지 않습니다."
        ),
        "sections": [
            {
                "heading": "개발자 안내서의 ‘슬롯 끼우기’와 다른 점",
                "paragraphs": [
                    "‘슬롯 끼우기’는 테마가 화면 부품(컴포넌트)을 바꾸는 방법이고, 바꾸면 테마를 다시 빌드합니다. 이 장의 테마 슬롯은 "
                    "플러그인이 서버에서 데이터를 돌려주는 방법이라 빌드가 필요 없습니다.",
                ],
            },
            {
                "heading": "위젯 만들기",
                "code": (
                    "# plugin.py\n"
                    "slots=(Slot(\"home.sidebar\", \"gnu_plugins.attendance.widgets.home_widget\"),),\n\n"
                    "# widgets.py: request를 받아 dict를, 보여 줄 것이 없으면 None을 돌려줌\n"
                    "def home_widget(request):\n"
                    "    return {\n"
                    "        \"title\": \"출석체크\",\n"
                    "        \"body\": \"오늘 출석하면 10포인트를 드려요.\",\n"
                    "        \"stats\": [{\"label\": \"연속 출석\", \"value\": \"3일\"}],\n"
                    "        \"actions\": [{\"label\": \"출석하기\", \"method\": \"POST\",\n"
                    "                     \"url\": \"/api/v1/plugins/attendance/check-in\", \"primary\": True}],\n"
                    "    }"
                ),
            },
            {
                "heading": "위젯에 쓸 수 있는 것",
                "bullets": [
                    "{{title}}과 {{body}}: 제목과 안내 문장. 모두 글자로 다루므로 HTML 태그를 넣어도 그대로 글자로 보입니다.",
                    "{{stats}}: {{label}}과 {{value}}로 된 작은 숫자 목록입니다.",
                    "{{actions}}: 버튼입니다. {{method}}가 {{GET}}이면 링크, {{POST}}이면 API를 부르는 버튼이 됩니다. {{url}}은 {{/}}로 시작하는 사이트 안 경로만 허용하고, POST는 {{/api/v1/}}로 시작하는 주소만 실행합니다. 성공하면 위젯을 다시 불러옵니다.",
                    "그 밖의 필드는 버립니다. 회원마다 내용이 다를 수 있으므로 응답은 캐시하지 않습니다.",
                ],
            },
            {
                "heading": "위젯을 가져오는 API",
                "paragraphs": [
                    "테마는 {{GET /api/v1/plugins/slots?name=home.sidebar}}로 켜진 플러그인들의 위젯을 모아 받습니다. 꺼진 "
                    "플러그인과 오류를 낸 위젯은 빠지고, 나머지는 그대로 보입니다.",
                ],
            },
            {
                "heading": "지금 있는 슬롯과 새 슬롯 만들기",
                "bullets": [
                    "{{home.sidebar}}: 기본 테마(nextjs_default) 커뮤니티 홈의 오른쪽 위젯 영역, 로그인 상자 바로 아래입니다.",
                    "슬롯 이름은 {{home.sidebar}}처럼 점으로 나눈 영문 소문자입니다.",
                    "새 자리가 필요하면 테마에 {{<PluginSlot name=\"...\" />}}를 넣고 테마를 한 번 다시 빌드합니다. 그 뒤로는 그 자리에 위젯을 넣는 플러그인을 추가해도 빌드가 필요 없습니다.",
                ],
            },
        ],
    },
}
