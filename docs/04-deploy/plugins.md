# 플러그인

코어(`gnu_jango/`)를 고치지 않고 기능을 더하는 방법입니다. 플러그인은 보통의 Django 앱이고, `G5_PLUGINS`에 적은 것만 켜집니다. 코어는 플러그인이 선언한 URL·관리자 메뉴·예약 작업을 자동으로 연결하고, 정해진 지점에서 hook을 보냅니다.

예제는 `gnu_plugins/attendance/`(출석체크)입니다. 새 플러그인을 만들 때 이 폴더를 복사해 시작하세요. hook만 쓰는 예는 `gnu_plugins/order_notify/`(주문 알림)입니다. 운영자용 설명은 매뉴얼 사이트의 「확장 기능 · 플러그인과 출석체크」 책(`hb_plugins`)에 있습니다.

## 설치와 켜고 끄기

설치는 배포로, 켜고 끄기와 설정은 관리자 화면에서 합니다.

```dotenv
# 설치: .env 또는 배포 환경 변수 (쉼표로 여러 개)
G5_PLUGINS=gnu_plugins.attendance
```

```bash
python manage.py migrate        # 플러그인 테이블 만들기
python manage.py check          # 플러그인 선언 확인 (잘못되면 여기서 멈춥니다)
```

설치한 플러그인은 켜진 상태로 시작합니다. 관리자 사이드바 **플러그인 › 플러그인 관리**(`/admin/plugins/`, 슈퍼유저만)에서 재배포 없이 끄고 켤 수 있습니다. 끈 플러그인은

- URL·API가 404를 돌려주고,
- hook 리스너가 실행되지 않으며,
- 예약 작업이 실행되지 않고 `skipped`로 기록되며(실패로 세지 않음),
- 사이드바 플러그인 메뉴에서 링크가 빠집니다. 관리자 **모든 애플리케이션** 목록의 모델 화면은 남아 있어 기록은 계속 볼 수 있습니다.

상태는 `Config` 테이블(`plugin.<slug>.enabled`)에 저장되어 변경 이력에 남고, 1분 캐시를 거치지만 이 화면에서 바꾸면 바로 반영됩니다.

- 완전히 없애려면 `G5_PLUGINS`에서 지우고 다시 배포합니다. 테이블과 포인트 기록은 남습니다(지우려면 먼저 `python manage.py migrate attendance zero`).
- Vercel은 실행 중에 패키지를 설치할 수 없으므로, 플러그인 코드는 저장소에 두거나 `requirements.txt`에 넣어 배포합니다.
- GitHub CD(`.github/workflows/cd.yml`)가 마이그레이션하는 사이트(Vercel 데모·매뉴얼)는 Vercel 환경 변수 `G5_PLUGINS`와 같은 값을 GitHub Actions 변수 `PRODUCTION_G5_PLUGINS`(매뉴얼은 `HANDBOOK_G5_PLUGINS`)에도 넣으세요. 빠지면 CD의 migrate가 플러그인 테이블을 만들지 않아, 플러그인 화면이 500을 냅니다. **변수를 먼저 넣고 migrate한 뒤** Vercel의 `G5_PLUGINS`를 바꿉니다.
- 플러그인은 코어와 같은 권한으로 실행되는 Python 코드입니다. 신뢰하는 코드만 설치하세요.
- 테스트(pytest)는 `.env`의 `G5_PLUGINS`와 상관없이 저장소의 플러그인(`gnu_plugins.*`)을 모두 더해서 돕니다. 코어의 연결 지점이 테스트에서 늘 검증되게 하기 위해서입니다.

## 플러그인 구조

```text
gnu_plugins/attendance/
├── plugin.py          # PLUGIN = Plugin(...)  코어가 연결할 것 (모델 import 금지)
├── apps.py            # AppConfig, ready()에서 listeners를 import
├── models.py, migrations/, admin.py
├── listeners.py       # hooks.on(...) 리스너
├── api.py, api_urls.py
├── management/commands/attendance_monthly_bonus.py
└── tests.py
```

### plugin.py

```python
from gnu_jango.plugins import AdminLink, Job, Plugin, Setting

PLUGIN = Plugin(
    slug="attendance",                       # URL에 쓰임: 영문 소문자로 시작, 소문자·숫자·_ 2~30자, 플러그인끼리 겹치면 안 됨
    title="출석체크",
    version="1.0.0",                         # 플러그인 자신의 버전 (표시용)
    api_version=1,                           # 반드시 적음: 이 플러그인이 맞춰 만든 플러그인 규격 버전
    urls="",                                 # 있으면 /plugins/<slug>/ 아래에 연결
    api_urls="gnu_plugins.attendance.api_urls",   # /api/v1/plugins/<slug>/ 아래에 연결
    admin_links=(AdminLink("출석체크 기록", "admin:attendance_attendance_changelist",
                           icon="event_available", permission="attendance.view_attendance"),),
    jobs=(Job("attendance_monthly_bonus", ("--apply", "--json"), ("--json",), 86400),),
    settings=(Setting("ATTENDANCE_POINT", "출석 포인트", 10, "출석할 때마다 주는 포인트"), ...),
)
```

`plugin.py`는 settings를 읽는 중에(Celery Beat 일정을 만들 때) 읽힙니다. 그래서 모델이나 앱 레지스트리가 필요한 것을 import하면 안 됩니다.

`api_version`은 코어의 `gnu_jango.plugins.PLUGIN_API_VERSION`(지금 1)과 같아야 합니다. 적지 않았거나 다르면 시작할 때 오류로 멈춥니다. 코어가 기존 플러그인을 깨는 방식으로 규격을 바꿀 때 이 번호를 올리므로, 맞지 않는 플러그인이 조용히 잘못 동작하는 일을 막습니다.

| 항목 | 코어가 하는 일 |
|---|---|
| `urls` | `/plugins/<slug>/`에 include. 테마 페이지보다 먼저 연결됩니다. |
| `api_urls` | `/api/v1/plugins/<slug>/`에 include. URL 이름은 `api_v1:<app_name>:<name>`(예: `api_v1:attendance_api:check-in`). |
| `admin_links` | 관리자 사이드바 맨 아래 **플러그인** 그룹. `permission`이 있으면 그 권한이 있는 직원에게만 보입니다. |
| `jobs` | 예약 작업 등록표(`core.scheduled_jobs.SCHEDULED_JOBS`)에 추가. `run_scheduled_jobs`, `/api/internal/cron`, Celery Beat가 함께 실행합니다. 이름이 겹치면 시작할 때 오류. |
| `settings` | `/admin/plugins/`에 입력 칸을 만듭니다. 형식은 `default`의 형식(bool은 체크박스, int는 숫자, str은 글자)을 따릅니다. 코드에서는 `gnu_jango.plugins.state.setting(slug, NAME)`으로 읽고, 값은 **관리자 저장값 → Django settings → 같은 이름의 환경 변수 → `default`** 순서로 정해집니다. |

플러그인 API는 코어 API 계약(`openapi/schema.json`)에 넣지 않습니다. 뷰에 `@extend_schema(exclude=True)`를 붙이세요.

Vercel은 Django를 ASGI로 실행합니다. URL을 고르는 단계와 `async def` 뷰·미들웨어는 이벤트 루프에서 돌기 때문에, 그 안에서 DB나
`CACHE_URL=db://` 캐시를 쓰면 `SynchronousOnlyOperation`(500)이 납니다. DB가 필요한 일은 동기 뷰 안에서 하거나 `sync_to_async`로
감싸세요. 켜고 끄기 확인도 같은 이유로 URL을 고를 때가 아니라 뷰가 실행될 때 합니다(`gnu_jango/plugins/routing.py`). 일반 테스트
클라이언트는 WSGI로 요청하므로, Vercel에서 쓸 API는 `django.test.AsyncClient`로도 테스트하세요
(`async_to_sync(AsyncClient().get)(url)`, 예: `gnu_jango/core/test_plugin_admin.py`).

## Hook

그누보드5의 `run_event`/`run_replace`와 같은 역할입니다.

```python
from gnu_jango.plugins import hooks

@hooks.on("member.visited")                 # 이벤트: 반환값은 쓰지 않음
def check_in_on_visit(user, **kwargs): ...

@hooks.on("attendance.point", priority=20)  # 값 바꾸기: 받은 값을 고쳐서 돌려줌
def double_on_weekends(point, user, streak, day, **kwargs):
    return point * 2 if day.weekday() >= 5 else point
```

- 리스너는 `priority`가 작은 것부터 실행됩니다(기본 10).
- 리스너는 하나씩 savepoint(`transaction.atomic()`) 안에서 실행됩니다. 리스너가 예외를 내면 로그만 남기고 건너뛰며, 그 리스너가 한 DB 작업은 되돌립니다. 값 바꾸기는 직전 값을 그대로 씁니다. 그래서 플러그인 오류가 로그인·출석 같은 요청이나, hook을 보낸 쪽의 트랜잭션을 깨뜨리지 않습니다.
- 리스너는 요청 안에서 바로 실행됩니다. 외부 API 호출처럼 오래 걸리는 일은 백그라운드 작업으로 넘기세요.
- 앞으로 인자가 늘어날 수 있으니 리스너는 항상 `**kwargs`를 받으세요.
- 리스너는 `AppConfig.ready()`에서 import해 등록합니다. 같은 함수를 다시 등록하면 덮어씁니다.

### 코어가 보내는 hook

| 이름 | 종류 | 인자 | 언제 |
|---|---|---|---|
| `member.visited` | 이벤트 | `user`, `request` | 비밀번호·소셜 로그인, 그리고 로그인한 회원이 페이지를 열 때(`/api/v1/auth/me`). 하루에 여러 번 오므로 리스너는 중복을 스스로 막아야 합니다. |
| `member.joined` | 이벤트 | `user`, `request` | 회원가입(비밀번호·소셜)이 커밋된 뒤. 메일 인증을 기다리는 회원도 보냅니다 |
| `bbs.post.created` | 이벤트 | `post`, `user`, `request` | 게시판 API로 글·답글을 쓴 뒤(커밋 후). 비회원 글이면 `user`는 `None` |
| `bbs.comment.created` | 이벤트 | `comment`, `user`, `request` | 게시판 API로 댓글·답댓글을 쓴 뒤(커밋 후) |
| `shop.order.placed` | 이벤트 | `order` | 주문이 만들어졌을 때(체크아웃, 정기구독 결제 주문) |
| `shop.order.status_changed` | 이벤트 | `order`, `old_status`, `new_status`, `source` | 주문 상태가 바뀔 때. `source`는 `payment`(PG·가상계좌 결제 확정), `admin`(주문→입금→준비→배송→완료 한 단계), `cancel`(취소·반품: 고객, 관리자, 만료 작업, 결제 실패, 반품) |
| `shop.order.paid` | 이벤트 | `order`, `source` | 주문이 입금 상태가 됐을 때. 같은 변경의 `status_changed` 바로 뒤에 옵니다 |

`member.visited`를 뺀 코어 hook은 **변경이 커밋된 뒤**에 보냅니다(관리자 화면이나 다른 코드로 만든 글·회원에는 오지 않으니, 놓치면 안 되는 일은 예약 작업으로 한 번 더 확인하세요). 주문은 결제나 취소가 롤백되면 아무것도 보내지 않고, 같은 결제 확정이 다시 와도(웹훅 재전송) 상태가 바뀌지 않았으면 보내지 않습니다. 리스너에서 받은 `order`는 커밋된 값이지만, 다른 요청이 그 사이에 바꿨을 수 있으니 필요하면 `refresh_from_db()` 하세요.

### 저장소의 플러그인이 보내는 hook

| 이름 | 종류 | 인자 |
|---|---|---|
| `attendance.point` | 값 바꾸기 | `point`, `user`, `streak`, `day` |
| `attendance.checked_in` | 이벤트 | `attendance` |
| `level_up.promoted` | 이벤트 | `user`, `old_level`, `new_level` (커밋 후) |

## 출석체크 예제

| 기능 | 내용 |
|---|---|
| 출석 | `POST /api/v1/plugins/attendance/check-in` (로그인 필요). 하루 한 번, 처음이면 201·이미 했으면 200. |
| 조회 | `GET /api/v1/plugins/attendance/me?month=2026-10` 그 달 출석일, 연속 출석일, 규칙 |
| 요청 제한 | 두 API 모두 회원당 분당 60회 (넘으면 429) |
| 포인트 | 코어 포인트 원장(`insert_point`)으로 지급, `@attendance` 관계로 같은 날 두 번 주지 않음. 사이트 포인트가 꺼져 있으면 출석만 기록 |
| 연속 보너스 | N일째마다 보너스 |
| 개근 보너스 | 매일 도는 `attendance_monthly_bonus`가 최근 끝난 3개월을 다시 확인해, 매일 출석한 활성 회원에게 달마다 한 번 지급. 작업이 멈췄거나 포인트가 꺼져 있던 달도 3개월 안이면 나중에 지급 |
| 자동 출석 | `ATTENDANCE_AUTO_CHECK_IN=True`이면 `member.visited`를 받아 방문 시 자동 출석. 그날 출석 뒤의 방문은 캐시로 DB 조회 없이 넘어감 |
| 관리자 | 사이드바 **플러그인 › 출석체크 기록** (읽기 전용) |

설정(`/admin/plugins/`에서 바꾸거나, Django settings 또는 같은 이름의 환경 변수로 기본값을 정함):

| 이름 | 기본값 |
|---|---|
| `ATTENDANCE_POINT` | 10 |
| `ATTENDANCE_STREAK_DAYS` | 7 (0이면 연속 보너스 없음) |
| `ATTENDANCE_STREAK_BONUS` | 50 |
| `ATTENDANCE_MONTHLY_BONUS` | 300 |
| `ATTENDANCE_AUTO_CHECK_IN` | False |

```bash
python manage.py attendance_monthly_bonus                          # 최근 3개월 대상만 세기
python manage.py attendance_monthly_bonus --apply                  # 최근 3개월 지급 (예약 작업이 하는 일)
python manage.py attendance_monthly_bonus --month 2026-10 --apply  # 한 달만
```

## 주문 알림

`gnu_plugins/order_notify/`는 `shop.order.*` hook을 받아 새 주문, 결제 완료, 취소·반품을 디스코드·슬랙·텔레그램으로 보냅니다. 코어를 고치지 않고 hook만으로 만든 두 번째 플러그인입니다.

```dotenv
G5_PLUGINS=gnu_plugins.attendance,gnu_plugins.order_notify
# 받을 곳: 비밀값이라 환경 변수에만 둡니다(관리자 화면·Config에 저장하지 않음). 하나 이상
ORDER_NOTIFY_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
ORDER_NOTIFY_SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
ORDER_NOTIFY_TELEGRAM_BOT_TOKEN=123456:ABC...
ORDER_NOTIFY_TELEGRAM_CHAT_ID=-100...
```

```bash
python manage.py migrate
python manage.py order_notify_test            # 채널마다 테스트 알림 (DB에 남기지 않음)
python manage.py order_notify_retry --apply   # 실패한 알림 다시 보내기 + 90일 지난 기록 지우기 (예약 작업)
```

| 항목 | 내용 |
|---|---|
| 보내는 때 | 주문이 커밋된 뒤 같은 요청 안에서 바로. 채널당 타임아웃 3초 |
| 주소 확인 | 디스코드 `https://discord.com/api/webhooks/`, 슬랙 `https://hooks.slack.com/services/`, 텔레그램 토큰·채팅방 형식이 아니면 무시. 리다이렉트를 따라가지 않음 |
| 재시도 | 타임아웃·429·5xx는 `pending`으로 남아 `order_notify_retry`가 3일 안에 최대 5번(한 번에 50건, 오래된 것부터). 그 밖의 4xx는 바로 `failed` |
| 재시도 주기 | Celery Beat에서는 5분마다. HTTP cron(`/api/internal/cron`)은 cron이 부르는 만큼: Vercel 기본 설정(`vercel.json`)은 **하루 한 번**이라 재시도도 하루 한 번입니다. 더 자주 보내려면 Supabase pg_cron 같은 외부 스케줄러로 같은 주소를 5~15분마다 부르세요 |
| 기록 정리 | 보냈거나 실패한 지 90일이 지난 기록은 `order_notify_retry`가 지움(한 번에 5,000건). 대기·보내는 중인 것은 지우지 않음 |
| 멈춘 채널 | 일시 오류가 난 채널은 5분 동안 요청 안에서 보내지 않고 예약 작업에 맡김(채널이 죽어도 주문 요청은 한 번만 3초를 기다림). 이 표시는 캐시에 있어, 공유 캐시(`CACHE_URL`이 `db://`나 Redis)면 모든 서버가 함께 쓰고 프로세스 캐시(비어 있음·`locmem://`)면 프로세스마다 따로 기다림 |
| 중복 | (주문번호, 알림 종류와 상태, 채널)마다 한 번. 보내기 전에 `sending`으로 선점해, 요청·예약 작업·관리자 재발송이 겹쳐도 한 번만 보냄. 10분 넘게 `sending`인 것은 예약 작업이 풀어 줌 |
| 다시 같은 알림 | 같은 주문이 같은 상태로 다시 바뀌어도(입금→주문→입금) 두 번째 알림은 보내지 않음. 기록이 지워지는 90일 뒤에는 다시 보냄 |
| 개인정보 | 주문자 이름은 기본으로 가림(`홍*동`). 이름·상품명은 한 줄로 만들고 마크다운·링크 문자를 뺌. 주소·연락처·이메일은 보내지 않음 |
| 관리자 | 사이드바 **플러그인 › 주문 알림 기록**, 액션 「선택한 알림 다시 보내기」(실패·대기 건만, 한 번에 20건). 기록 삭제는 슈퍼유저만 |

설정(`/admin/plugins/`): `ORDER_NOTIFY_PLACED`(True), `ORDER_NOTIFY_PAID`(True), `ORDER_NOTIFY_CANCELLED`(True), `ORDER_NOTIFY_OTHER_STATUS`(False, 준비·배송·완료), `ORDER_NOTIFY_FULL_NAME`(False).

## 자동 등업

`gnu_plugins/level_up/`은 관리자가 정한 조건을 채운 회원의 레벨(`Profile.user_level`)을 올립니다. 출석체크의 `attendance.checked_in`과 코어의 글·댓글·가입 hook을 받아 쓰는, 플러그인끼리 hook으로 이어지는 예입니다.

| 항목 | 내용 |
|---|---|
| 규칙 | 관리자 **플러그인 › 등업 규칙**(`LevelRule`): 올려 줄 레벨(2~9, 레벨마다 하나)과 보유 포인트·글 수·댓글 수·가입 후 일수·출석 일수. 0이면 그 조건은 쓰지 않음. 모두 채워야 함 |
| 출석 일수 | 출석체크 플러그인이 설치되어 있어야 저장 가능 |
| 바로 확인 | `bbs.post.created`, `bbs.comment.created`, `member.joined`, `attendance.checked_in`, 그날 첫 `member.visited` (`LEVEL_UP_ON_ACTIVITY`) |
| 예약 작업 | 매일 `level_up_sweep`가 가장 높은 규칙보다 낮은 회원 전체를 500명씩 확인 |
| 올리는 레벨 | 채운 규칙 중 가장 높은 레벨로 한 번에. 내리지 않음. 그 사이 레벨이 바뀌었으면(조건부 UPDATE) 건너뜀 |
| 제외 | 직원·슈퍼유저, 비활성(차단), 탈퇴, 메일 미인증, 가입 레벨(`cf_register_level`)보다 낮은 회원, 그리고 이 플러그인이 올려 준 레벨보다 지금 레벨이 낮은 회원(관리자가 일부러 내림) |
| 규칙 편집 | 슈퍼유저만(직원은 보기만). 레벨 2~9는 DB 제약으로도 강제 |
| 비용 | 규칙이 쓰는 조건만 셈. 그날 첫 방문 확인은 공유 캐시(`CACHE_URL`이 `db://`나 Redis)면 회원당 하루 한 번, 프로세스 캐시면 프로세스마다 한 번(결과는 같고 조회만 늘어남) |
| 등업 제외 | **플러그인 › 등업 제외 회원**(`LevelUpHold`)에 넣은 회원은 조건을 채워도 올리지 않음. 지우면 다시 규칙 적용 |
| 한 번에 | `level_up_sweep`는 한 번에 최대 2,000명(`--limit`)을 올리고, 남으면 다음 실행에서 이어감 |
| 알림 | `LEVEL_UP_NOTIFY`이면 코어 알림함에 「축하합니다! 회원 레벨이 N(으)로 올랐습니다.」 |
| 기록 | **플러그인 › 등업 기록**(`LevelChange`, 읽기 전용, 삭제는 슈퍼유저만): 이전·새 레벨과 그때 활동 |

```bash
python manage.py level_up_sweep            # 올라갈 회원 수만 세기
python manage.py level_up_sweep --apply    # 올리기 (예약 작업이 하는 일)
```

## 테마 슬롯

플러그인은 테마의 정해진 자리(슬롯)에 위젯을 넣을 수 있습니다. 테마는 위젯을 **HTML이 아닌 데이터**로 받아 하나의 공통 모양으로 그리므로, 플러그인을 추가해도 테마를 다시 빌드할 필요가 없습니다.

```python
# plugin.py
slots=(Slot("home.sidebar", "gnu_plugins.attendance.widgets.home_widget"),),

# widgets.py: request를 받아 dict(또는 보여 줄 것이 없으면 None)를 돌려줌
def home_widget(request):
    return {
        "title": "출석체크",
        "body": "오늘 출석하면 10포인트를 드려요.",
        "stats": [{"label": "연속 출석", "value": "3일"}],
        "actions": [{"label": "출석하기", "method": "POST", "url": "/api/v1/plugins/attendance/check-in", "primary": True}],
    }
```

- `GET /api/v1/plugins/slots?name=home.sidebar`가 켜진 플러그인들의 위젯을 모아 돌려줍니다(회원마다 다르므로 캐시하지 않음). 꺼진 플러그인과, 예외를 낸 provider의 위젯은 빠집니다.
- 위젯 필드는 `title`, `body`, `stats`, `actions`만 남고 모두 글자로 바뀝니다. `actions`는 `GET`(링크)과 `POST`(API 호출 버튼)만, 그리고 `/`로 시작하는 사이트 안 경로만 허용합니다. 테마는 `POST`를 `/api/v1/`로 시작하는 주소일 때만 실행하고, 성공하면 위젯을 다시 불러옵니다.
- 슬롯 이름은 `home.sidebar`처럼 점으로 나눈 소문자입니다. `slots`는 코어가 쓰므로 플러그인 slug로 쓸 수 없습니다.

| 슬롯 | 위치 |
|---|---|
| `home.sidebar` | 기본 테마(`nextjs_default`) 커뮤니티 홈의 오른쪽 위젯 영역, 로그인 상자 바로 아래 |

새 슬롯 자리를 테마에 만들 때만 `<PluginSlot name="..." />`를 넣고 테마를 한 번 다시 빌드합니다.

## 앞으로

- Python entry points 자동 발견(pip로 설치한 플러그인)
- 글·댓글 내용을 바꾸는(값 바꾸기) hook, 삭제 hook
