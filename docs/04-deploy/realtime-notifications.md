# 실시간 알림: 설정·실행·운영 가이드

## 1. 무엇이 바뀌나요?

기존 `/api/v1/notifications` 알림함을 그대로 사용합니다. 이제 새 댓글, 수신 쪽지, 회원 주문의 상태 변경도 이 알림함에 저장됩니다.
활성화된 ASGI 서버는 Redis를 통해 로그인한 회원의 알림 벨을 즉시 갱신합니다.

WebSocket으로 개인정보나 본문을 직접 보내지 않습니다. 개인 그룹에 `notifications.changed` 신호를 보내고,
브라우저가 기존 REST API로 자신의 읽지 않은 알림과 개수를 다시 조회합니다. 연결이 끊긴 동안의 알림도 DB에 남습니다.
이 설계는 Redis 메시지 유실·중복·순서 변경 후에도 알림함 전체를 다시 맞춥니다.

자동 댓글/쪽지 알림에는 본문과 원글 제목을 복사하지 않습니다. 비밀글이나 접근 권한이 바뀐 글의 내용이 알림으로 유출되지 않게 하기 위한 동작입니다.
알림 링크를 열 때 원래 페이지의 권한 검사가 다시 적용됩니다.

## 2. 기본 동작과 필요한 환경

| 환경 | 기본 동작 | 실시간 전송을 켜려면 |
|---|---|---|
| Django WSGI / 무료 PythonAnywhere | DB 알림 + REST 폴링 | 이 가이드는 기존 WSGI 웹 앱을 유지합니다. 별도 ASGI 호스팅 구성이 필요합니다. |
| VPS / Docker | 기본은 WSGI와 REST | 선택 requirements, ASGI 실행, Redis와 Origin 설정 |
| 현재 Vercel 프로젝트 | `example/wsgi.py`, REST | ASGI 진입점/라우팅·의존성·Redis·Fluid compute를 별도 배포에서 준비 |
| Preview | 실시간 전송 강제 비활성 | 운영 Redis에 연결하지 않습니다. 별도 검증 환경이 필요합니다. |

Celery 워커는 필수 조건이 아닙니다. 웹 요청은 DB에 전송 작업을 저장하고, 별도의 알림 작업자가 Channels로 Redis 신호를 전달합니다.
**실시간 전송에는 아래의 `process_notifications --apply --watch` 작업자가 필요합니다.** 기존 일일 예약 작업만으로는 즉시 전달되지 않습니다.
기존 Celery가 알림을 생성하는 경우 해당 워커에도 같은 Channels 패키지와 Redis 설정이 필요합니다.
기존 Redis 인스턴스를 공유할 수 있으나 예제에서는 broker=0, cache=1, 알림=2로 DB 번호를 구분합니다.
Redis Cluster처럼 DB 0만 지원하는 서비스에서는 `/0`과 별도 접근 정책/키 공간을 사용하세요.

## 3. 설치와 환경 변수

기존 설치에 선택 의존성만 추가합니다. PythonAnywhere 용량 절약용 설치에는 추가하지 않아도 됩니다.

```bash
python -m pip install -r requirements-realtime.txt
```

DB를 먼저 백업하고, 배포 대상 환경이 올바른지 확인한 뒤 해당 환경에서 마이그레이션합니다.

```bash
python manage.py migrate
```

이 변경의 `core.0013_notification_unread_index`는 읽지 않은 알림 조회 인덱스입니다. 알림 데이터는 삭제하지 않습니다.
`core.0014_notification_delivery`는 중복 방지 키, 생성/전달 재시도 대기열, 공지 발송 기록을 추가합니다.
코드 배포 전에 두 마이그레이션을 적용하세요. 운영 DB에는 이 작업 중 적용하지 않았습니다.
같이 남아 있는 검색 작업의 `site_search.0005`~`0007`은 [검색 배포 가이드](search-reliability.md)의 준비·순서도 확인하세요.
이번 구현 중 실제 로컬 DB나 운영 DB에는 마이그레이션을 실행하지 않았습니다.

| 변수 | 기본값 | 설명 |
|---|---|---|
| `NOTIFICATION_EVENTS_ENABLED` | `True` | 댓글·쪽지·주문 자동 알림 생성. 과거 자료를 가져올 때는 `False` 권장. |
| `NOTIFICATION_WS_ENABLED` | `False` | WebSocket 전송 활성화. ASGI 서버에서만 켭니다. |
| `NOTIFICATION_REDIS_URL` | 빈 값 | 활성화 시 필수. `redis://` 또는 `rediss://` TCP 연결. REST 전용 Redis 서비스 주소는 사용할 수 없습니다. |
| `NOTIFICATION_WS_ORIGINS` | 빈 목록 | 접속을 허용할 브라우저 Origin. 스킴·호스트·포트까지 지정하고 쉼표로 구분합니다. 경로/와일드카드는 금지합니다. |
| `NOTIFICATION_WS_URL` | `/ws/notifications/` | 브라우저가 연결할 주소. 프런트엔드/백엔드가 분리되어 있으면 완전한 `wss://` 주소를 지정합니다. |

서버의 `ALLOWED_HOSTS`, 별도 도메인의 `CSRF_TRUSTED_ORIGINS`와 CORS도 기존 배포 가이드에 맞게 설정해야 합니다.
여기서 Origin은 브라우저의 주소창에 표시된 사이트 주소입니다. Redis 서버 주소가 아닙니다.
소켓용 `notifications` 캐시는 Redis를 사용하며 일반 검색/페이지 캐시와 독립적입니다.
키 공간은 `SECRET_KEY`의 해시로 분리되므로 같은 앱의 HTTP·ASGI·워커는 동일한 키와 설정을 사용해야 합니다.

### 로컬 Windows 예제

이미 실행 중인 8081 서버는 유지하고, 사용할 DB를 명시한 별도 PowerShell에서 실행하세요.
Redis 자체는 별도로 실행 중이어야 합니다. 예제의 DB 경로나 Redis 포트를 실제 환경에 맞추세요.

```powershell
$env:ENVIRONMENT = 'Development'
$env:DATABASE_URL = 'sqlite:///E:/gnu-jango/local-notes/realtime-demo.sqlite3'
$env:NOTIFICATION_WS_ENABLED = 'True'
$env:NOTIFICATION_REDIS_URL = 'redis://127.0.0.1:6379/2'
$env:NOTIFICATION_WS_ORIGINS = 'http://127.0.0.1:8001,http://127.0.0.1:3000'
$env:NOTIFICATION_WS_URL = 'ws://127.0.0.1:8001/ws/notifications/'
python manage.py migrate
python manage.py check
python -m uvicorn example.asgi:application --host 127.0.0.1 --port 8001 --lifespan off --ws-max-size 1024 --ws-max-queue 8
```

같은 DB·SECRET_KEY·Redis·알림 설정을 사용하는 **다른 터미널**에서 작업자를 실행합니다.

```bash
python manage.py process_notifications --apply --watch --interval 1
```

기본 1초 간격으로 최대 50개 작업을 처리합니다. 실패하면 5초부터 최대 1시간까지 간격을 늘려 다시 시도합니다.
Redis 장애는 한 묶음에서 한 번만 시도하여 작업자가 반복해서 오래 멈추지 않게 합니다.
VPS에서는 systemd나 프로세스 관리자로 재시작을 설정하세요. SQLite를 사용하면 작업자는 한 개만 실행하는 것을 권장합니다.
PostgreSQL에서는 행 잠금과 중복 방지 키로 여러 작업자의 중복 처리를 막습니다.

한 번만 처리하거나 상태를 읽을 수도 있습니다.

```bash
python manage.py process_notifications --json
python manage.py process_notifications --apply --limit 50 --json
```

`pending`은 재시도 대기까지 포함한 미완료 수, `due`는 지금 실행 가능한 수입니다. `completed`, `failed`, `skipped`는 이번 실행의 처리 결과입니다.
완료된 대기열 기록만 7일 뒤 정리하고, 실패/미완료 작업과 공지 중복 방지 기록은 지우지 않습니다.
읽기 모드가 기본이므로 `--apply` 없이 실행하면 변경하지 않습니다. 작업자는 유휴 상태에서는 최대 1분에 한 번만 상태를 기록합니다.

`python manage.py runserver` 기본 WSGI 서버로는 이 기능을 켤 수 없습니다. 이 예제는 Uvicorn을 사용합니다.
Uvicorn 개발 서버의 정적 파일 제공은 기존 수집/서빙 설정에 따라 별도로 준비해야 합니다.
Next.js 3000을 함께 사용하면 프런트엔드의 기존 API 프록시 대상도 같은 ASGI 서버의 `/api/v1`로 맞추세요.
WebSocket 주소만 바꾸고 API가 다른 DB를 보는 상태로 두면 접속권과 알림이 일치하지 않습니다.

### Docker VPS

`deploy/env/vps.env.example`의 기본 서버 설정을 준비하고 `.env` 또는 비밀 저장소에 다음 항목을 추가합니다.
운영에서는 HTTPS/WSS와 외부에 노출하지 않는 Redis를 사용합니다.

```dotenv
NOTIFICATION_WS_ORIGINS=https://example.com
NOTIFICATION_WS_URL=/ws/notifications/
NOTIFICATION_REDIS_URL=redis://redis:6379/2
```

```bash
docker compose --profile realtime -f docker-compose.yml -f docker-compose.realtime.yml up -d --build
docker compose --profile realtime -f docker-compose.yml -f docker-compose.realtime.yml exec web python manage.py check
```

추가 Compose 파일은 선택 패키지를 설치하고 웹 서버를 Uvicorn으로 실행합니다. `realtime` 프로필은 전용 `notification-worker`도 실행합니다.
기본 Compose 파일은 그대로 WSGI로 실행됩니다. 프로필을 빼면 알림 작업자는 시작되지 않으니 명령을 그대로 사용하세요.
역방향 프록시는 `/ws/notifications/`를 ASGI 서버로 보내며 Upgrade 헤더와 충분한 읽기 제한 시간이 필요합니다.

```nginx
location /ws/notifications/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 90s;
}
```

이 설정을 기존 사이트의 HTTPS `server` 블록에 통합합니다. 프록시에서 동시 연결 수와 연결 요청 빈도도 제한하세요.
공개 Redis 포트를 열지 말고 관리형 Redis의 비밀번호/TLS 또는 내부 네트워크를 적용하세요.

## 4. 관리자 공지 보내기

1. 관리자 로그인 후 메뉴의 **공지 알림 발송**을 엽니다.
2. 직접 주소는 `/admin/core/notification/announce/`입니다.
3. 제목, 내용, 필요 시 `/bbs/notice/1` 같은 내부 경로를 입력합니다.
4. 아이디 지정, 활성 스태프, 활성 회원 전체 중 수신 대상을 고릅니다.
5. 발송 확인 체크 후 **공지 보내기**를 누릅니다. 한 번에 최대 500명까지 보낼 수 있습니다.
6. 알림 목록과 관리자 이력을 확인합니다. 보내기 화면은 한 시간 동안 유효하며, 같은 요청 ID는 DB에서 한 번만 처리합니다.

`core.add_notification` 권한이 필요합니다. 비활성 회원과 존재하지 않는 아이디는 발송 대상이 아닙니다.
기존 `/admin/core/notification/add/`에서도 한 사람에게 알림을 만들 수 있고, 저장하면 같은 실시간 전달 경로를 사용합니다.
발송 화면을 새로 열고 다시 보내면 별도 공지가 됩니다. 대량 발송/예약 발송/캠페인 취소는 이번 범위에 포함하지 않습니다.
공지 중복 방지는 캐시 초기화와 서버 수에 영향을 받지 않습니다. 같은 요청 ID로 내용/수신자를 바꾸면 거부합니다.
API 요청 제한에는 기본 캐시를 사용하므로 여러 서버에서는 여전히 공유 Redis 또는 DatabaseCache가 필요합니다.
관리자 모델 목록의 `Notification announcements`와 `Notification works`에서 발송 기록·대기 작업을 읽을 수 있습니다.

## 5. API와 WebSocket 계약

### HTTP 접속권

`POST /api/v1/notifications/ticket`

- 인증: 기존 JWT Bearer, HttpOnly JWT 쿠키, 또는 Django 세션. 쿠키·세션 요청은 기존 CSRF 검사를 통과해야 합니다.
- 로그인 회원별 분당 30회 요청 제한.
- 꺼진 환경: 기존 응답 봉투의 `data`에 `{ "enabled": false }`.
- 켜진 환경: `data`에 `enabled`, `ticket`, `expires_in: 30`, `websocket_url`.
- Redis 장애: 503 `realtime_unavailable`. 개인 응답은 `private, no-store`.
- 접속권은 랜덤한 불투명 값입니다. Redis에서 한 번만 소비하며 재사용은 거부합니다.

### 소켓

주소: `/ws/notifications/`. 쿼리 문자열과 임의 사용자/그룹 지정은 받지 않습니다.
허용 목록에 없는 Origin이나 Origin이 없는 요청은 거부합니다.

```json
{"type":"authenticate","ticket":"HTTP에서 받은 일회용 값"}
```

5초 안에 첫 프레임으로 보내면, 본인의 그룹에 가입한 후 다음 응답을 받습니다.

```json
{"type":"ready","version":1}
```

알림 변경 신호는 다음과 같습니다. 수신 후 REST 알림함을 다시 조회합니다.

```json
{"type":"notifications.changed","version":1}
```

서버의 `{"type":"ping"}`에는 `{"type":"pong"}`으로 응답합니다.
연결은 약 5분 후 새 접속권으로 갱신하고, 계정/토큰 상태는 약 25초마다 및 변경 신호 전달 전에 확인합니다.
첫 인증 외의 명령·바이너리·1,024자를 넘는 프레임은 거부합니다. 메시지로 읽음 처리나 다른 계정 구독을 할 수 없습니다.

| 종료 코드 | 의미 |
|---|---|
| 4400 | 잘못된 형식·금지된 요청 |
| 4401 | 인증 실패·만료·폐기·재사용 접속권 |
| 4000 | 연결 갱신 시간 도달·활동 없음 |
| 1013 | 일시적인 연결 계층 장애 |

브라우저 구현은 지수 백오프와 임의 지연으로 재접속합니다. 접속 직후/재접속/탭 복귀/온라인 복귀에 재조회하고,
짧은 시간에 여러 신호가 오면 200ms로 합칩니다. 숨겨진 탭은 연결과 폴링을 쉬고, 로그아웃 시 연결과 예약 작업을 정리합니다.
연결 중에도 5분마다, 연결 실패 중에는 60초마다 REST로 맞춥니다. 다른 탭에서 모두 읽음/전체 삭제한 결과도 신호로 반영합니다.
접속권 HTTP 요청은 CSRF·토큰 갱신 대기를 포함하여 8초 뒤 취소하고 재시도합니다. 공유 CSRF 요청 자체는 10초, 토큰 갱신 요청은 15초의 제한을 둡니다.
기본 테마의 커뮤니티/쇼핑몰과 핸드북 헤더에 알림 벨을 표시합니다.

## 6. Vercel과 모바일

최신 [Vercel WebSockets 문서](https://vercel.com/docs/functions/websockets)는 Fluid compute 환경의 Python ASGI 및 Django Channels를 지원한다고 안내합니다.
단, 현재 저장소의 `vercel.json`은 `example/wsgi.py`를 가리킵니다. 플래그 하나로 현재 배포가 ASGI로 바뀌지는 않습니다.

Vercel에서 활성화하려면 별도 배포에서 다음을 준비하세요.

1. Python ASGI 진입점과 `/ws/notifications/` 라우팅을 준비하고 기존 HTTP/정적 파일 라우팅을 보존합니다.
2. Vercel은 기본 requirements를 직접 읽으므로 선택 파일을 올리는 것만으로 설치되지 않습니다.
   선택 패키지를 해당 빌드의 설치 목록에 포함시키고 번들 크기를 확인합니다.
3. 외부에서 접속 가능한 **TCP Redis**와 TLS를 준비합니다. REST API 전용 Redis URL은 Channels에 연결할 수 없습니다.
4. HTTP와 ASGI 함수가 같은 DB·접속권 Redis·SECRET_KEY를 사용하도록 설정합니다.
5. 함수의 최대 실행 시간에 따라 소켓이 더 일찍 종료될 수 있으므로 재연결/재동기화를 실제 배포에서 확인합니다.
6. 그 뒤에 `NOTIFICATION_WS_ENABLED=True`를 적용합니다. 이 작업에서는 기존 두 프로젝트의 진입점/환경 변수를 바꾸지 않았습니다.

또한 같은 DB와 Redis를 사용하는 별도 알림 작업자를 준비해야 합니다. Vercel의 짧은 HTTP 요청 안에서 `--watch`를 실행하면 안 됩니다.
현재 `/api/internal/cron`의 예약 작업에는 실패 복구용 단발 처리가 포함되지만, 일일 스케줄은 실시간 작업자를 대체하지 않습니다.

저장소에 Expo/React Native 앱이 없어 FCM/APNs를 연결하지 않았습니다.
모바일 앱을 추가하면 기기별 토큰 등록·로그아웃 시 해제·푸시 수신 동의·실패 토큰 정리·FCM/APNs 또는 Expo 전송 자격 증명을 별도로 구현해야 합니다.
WebSocket은 앱이 닫혀 있을 때 OS 알림을 대신하지 않습니다.

## 7. 반영 후 직접 확인할 항목

로컬 회귀 검사:

```bash
python -m pip install -r requirements-dev.txt
python manage.py test gnu_jango.core.test_notification_reliability gnu_jango.core.test_notification_transport gnu_jango.core.test_notification_concurrency
cd nextjs
npm run test:notifications
```

실제 전송 검사는 별도 테스트 Redis `127.0.0.1:6399/2`를 준비하고 `NOTIFICATION_TEST_REDIS_URL=redis://127.0.0.1:6399/2`를 설정해야 실행됩니다.
각 검사에는 독립 키 공간을 사용하며 Redis 전체 초기화는 하지 않습니다. PostgreSQL 동시성 검사는 SQLite에서 건너뜁니다.
운영 DB 설정으로 테스트 명령을 실행하지 말고, Django 테스트용 DB를 만들 수 있는 격리 설정을 사용하세요.
실제 테마 화면 검사 두 개는 별도 로컬 fixture 서버와 `notification-browser` 테스트 계정을 준비한 뒤 `NOTIFICATION_UI_BASE_URL`을 지정할 때만 실행합니다.
지정하지 않으면 브라우저의 복구 동작 검사 8개를 실행하고 실제 테마 화면 검사 2개는 건너뜁니다.

1. 서로 다른 두 회원으로 로그인합니다. 각 브라우저에서 자신의 접속권을 발급받고 연결합니다.
2. 한 회원의 글에 다른 회원 또는 비회원이 댓글을 쓰면 글 작성자에게 알림이 오는지 확인합니다. 본인 댓글·수정에는 새 알림이 없어야 합니다.
3. 답댓글은 원글/부모댓글 작성자를 중복 제거해 알리고 본문은 노출하지 않는지 확인합니다.
4. 쪽지는 수신자에게만, 주문 상태 변경은 주문한 회원에게만 오는지 확인합니다.
5. 공지를 지정 회원에게 보내고 일반 회원은 공지 발송 화면에 접근하지 못하는지 확인합니다.
6. 두 탭을 열고 모두 읽음을 실행했을 때 다른 탭도 갱신되는지 확인합니다.
7. Redis 중단 중에도 댓글·주문 DB 저장과 REST 알림함이 동작하는지 확인합니다. 복구 후 재접속으로 맞춰져야 합니다.
8. 만료/재사용 접속권, 허용하지 않은 Origin, 다른 회원 식별자를 보낸 요청을 거부하는지 확인합니다.
9. 로그인 세션 폐기/비밀번호 변경/비활성화 후 소켓이 닫히는지 확인합니다.

## 8. 운영상 알아둘 한계

- Channels는 알림 원문을 보관하는 영속 큐가 아닙니다. Redis 장애·용량 제한 중 신호가 유실되어도 REST가 저장된 DB 알림을 복구합니다.
- 일반 모델 `save()`를 대상으로 합니다. 사용자 정의 `QuerySet.update`, `bulk_create` 및 직접 SQL 변경은 자동 알림을 만들지 않습니다.
  기존 주문 상태 변경 경로는 `save`를 사용합니다. 새로운 일괄 처리 경로를 추가하면 이 규칙도 함께 확인하세요.
- 댓글·쪽지·주문 자동 알림 생성은 원본 저장 커밋 뒤 실행합니다. 알림 DB 저장이 실패해도 원본 커밋은 유지하고, 이미 저장된 대기열에서 재시도합니다.
  정상 시에는 요청 중에 알림함 DB 생성까지 시도하여 WSGI 전용 환경에서도 바로 조회할 수 있습니다. 요청 중 Redis 전송은 하지 않습니다.
- 원본 커밋 직후 프로세스가 종료되거나 대기열 자체에 기록하지 못하면, 해당 이벤트의 영속 보관까지 보장할 수 없습니다.
  이 경우 `notification_event_enqueue_failed`를 오류로 기록합니다. 원본 트랜잭션과 하나로 묶인 완전한 transactional outbox는 아닙니다.
- 데이터 가져오기와 샘플 생성에는 요청별 자동 알림 억제를 적용했습니다. 동시 실행 중인 일반 회원 요청은 영향을 받지 않습니다.
- 오류 로그는 `notification_event_enqueue_failed`, `notification_hint_enqueue_failed`, `notification_work_retry`, `notification_ticket_failed`, `notification_connect_failed`, `notification_channel_failed`와 오류 종류로 찾을 수 있습니다.
- Redis 읽기 제한은 Channels의 정상적인 5초 블로킹 읽기보다 긴 10초입니다. 이를 1초 등으로 줄이면 유휴 연결이 끊길 수 있습니다.
- 실시간을 끄려면 `NOTIFICATION_WS_ENABLED=False`로 바꾸고 웹/워커를 재시작합니다. 알림 기록과 REST 조회는 유지됩니다.
- 알림 저장량은 사용량에 따라 증가합니다. 운영 보존 기간/삭제 정책은 서비스 정책에 맞춰 따로 정하세요.

구현 근거: [Channels 보안](https://channels.readthedocs.io/en/stable/topics/security.html),
[Redis 채널 계층](https://channels.readthedocs.io/en/stable/topics/channel_layers.html).
