# 플러그인

코어(`gnu_jango/`)를 고치지 않고 기능을 더하는 방법입니다. 플러그인은 보통의 Django 앱이고, `G5_PLUGINS`에 적은 것만 켜집니다. 코어는 플러그인이 선언한 URL·관리자 메뉴·예약 작업을 자동으로 연결하고, 정해진 지점에서 hook을 보냅니다.

예제는 `gnu_plugins/attendance/`(출석체크)입니다. 새 플러그인을 만들 때 이 폴더를 복사해 시작하세요.

## 켜고 끄기

```dotenv
# .env 또는 배포 환경 변수 (쉼표로 여러 개)
G5_PLUGINS=gnu_plugins.attendance
```

```bash
python manage.py migrate        # 플러그인 테이블 만들기
python manage.py check          # 플러그인 선언 확인 (잘못되면 여기서 멈춥니다)
```

- 끌 때는 `G5_PLUGINS`에서 지우고 다시 배포합니다. 테이블과 포인트 기록은 남습니다(지우려면 끄기 전에 `python manage.py migrate attendance zero`).
- Vercel은 실행 중에 패키지를 설치할 수 없으므로, 플러그인 코드는 저장소에 두거나 `requirements.txt`에 넣어 배포합니다.
- 플러그인은 코어와 같은 권한으로 실행되는 Python 코드입니다. 신뢰하는 코드만 설치하세요.
- 테스트(pytest)는 `G5_PLUGINS`를 따로 정하지 않으면 예제 플러그인을 켠 상태로 돕니다. 코어의 연결 지점이 테스트에서 늘 검증되게 하기 위해서입니다.

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
from gnu_jango.plugins import AdminLink, Job, Plugin

PLUGIN = Plugin(
    slug="attendance",                       # URL에 쓰임: 소문자·숫자·_ 2~40자, 플러그인끼리 겹치면 안 됨
    title="출석체크",
    version="1.0.0",
    urls="",                                 # 있으면 /plugins/<slug>/ 아래에 연결
    api_urls="gnu_plugins.attendance.api_urls",   # /api/v1/plugins/<slug>/ 아래에 연결
    admin_links=(AdminLink("출석체크 기록", "admin:attendance_attendance_changelist",
                           icon="event_available", permission="attendance.view_attendance"),),
    jobs=(Job("attendance_monthly_bonus", ("--apply", "--json"), ("--json",), 86400),),
)
```

`plugin.py`는 settings를 읽는 중에(Celery Beat 일정을 만들 때) 읽힙니다. 그래서 모델이나 앱 레지스트리가 필요한 것을 import하면 안 됩니다.

| 항목 | 코어가 하는 일 |
|---|---|
| `urls` | `/plugins/<slug>/`에 include. 테마 페이지보다 먼저 연결됩니다. |
| `api_urls` | `/api/v1/plugins/<slug>/`에 include. URL 이름은 `api_v1:<app_name>:<name>`(예: `api_v1:attendance_api:check-in`). |
| `admin_links` | 관리자 사이드바 맨 아래 **플러그인** 그룹. `permission`이 있으면 그 권한이 있는 직원에게만 보입니다. |
| `jobs` | 예약 작업 등록표(`core.scheduled_jobs.SCHEDULED_JOBS`)에 추가. `run_scheduled_jobs`, `/api/internal/cron`, Celery Beat가 함께 실행합니다. 이름이 겹치면 시작할 때 오류. |

플러그인 API는 코어 API 계약(`openapi/schema.json`)에 넣지 않습니다. 뷰에 `@extend_schema(exclude=True)`를 붙이세요.

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
- 리스너가 예외를 내면 로그만 남기고 건너뜁니다. 값 바꾸기는 직전 값을 그대로 씁니다. 플러그인 오류가 로그인이나 출석 같은 요청을 깨뜨리지 않습니다.
- 앞으로 인자가 늘어날 수 있으니 리스너는 항상 `**kwargs`를 받으세요.
- 리스너는 `AppConfig.ready()`에서 import해 등록합니다. 같은 함수를 다시 등록하면 덮어씁니다.

### 코어가 보내는 hook

| 이름 | 종류 | 인자 | 언제 |
|---|---|---|---|
| `member.visited` | 이벤트 | `user`, `request` | 비밀번호·소셜 로그인, 그리고 로그인한 회원이 페이지를 열 때(`/api/v1/auth/me`). 하루에 여러 번 오므로 리스너는 중복을 스스로 막아야 합니다. |

### 예제 플러그인이 보내는 hook

| 이름 | 종류 | 인자 |
|---|---|---|
| `attendance.point` | 값 바꾸기 | `point`, `user`, `streak`, `day` |
| `attendance.checked_in` | 이벤트 | `attendance` |

주문·결제 hook(`shop.order.paid` 등)은 아직 없습니다. 결제 확정 경로가 여러 곳이라, 한 곳에서 보내도록 정리한 뒤 추가할 예정입니다.

## 출석체크 예제

| 기능 | 내용 |
|---|---|
| 출석 | `POST /api/v1/plugins/attendance/check-in` (로그인 필요). 하루 한 번, 처음이면 201·이미 했으면 200. |
| 조회 | `GET /api/v1/plugins/attendance/me?month=2026-10` 그 달 출석일, 연속 출석일, 규칙 |
| 포인트 | 코어 포인트 원장(`insert_point`)으로 지급, `@attendance` 관계로 같은 날 두 번 주지 않음. 사이트 포인트가 꺼져 있으면 출석만 기록 |
| 연속 보너스 | N일째마다 보너스 |
| 개근 보너스 | 매일 도는 `attendance_monthly_bonus`가 지난달 매일 출석한 회원에게 한 번 지급 |
| 자동 출석 | `ATTENDANCE_AUTO_CHECK_IN=True`이면 `member.visited`를 받아 방문 시 자동 출석 |
| 관리자 | 사이드바 **플러그인 › 출석체크 기록** (읽기 전용) |

설정(Django settings 또는 같은 이름의 환경 변수):

| 이름 | 기본값 |
|---|---|
| `ATTENDANCE_POINT` | 10 |
| `ATTENDANCE_STREAK_DAYS` | 7 (0이면 연속 보너스 없음) |
| `ATTENDANCE_STREAK_BONUS` | 50 |
| `ATTENDANCE_MONTHLY_BONUS` | 300 |
| `ATTENDANCE_AUTO_CHECK_IN` | False |

```bash
python manage.py attendance_monthly_bonus --month 2026-10          # 대상만 세기
python manage.py attendance_monthly_bonus --month 2026-10 --apply  # 지급
```

## 앞으로

- 테마 슬롯: `<PluginSlot name="home.sidebar" />` 자리에 플러그인 위젯을 그리는 API (테마 재빌드 한 번 필요)
- 관리자 플러그인 화면(켜고 끄기), Python entry points 자동 발견
- 주문·결제·글쓰기 hook
