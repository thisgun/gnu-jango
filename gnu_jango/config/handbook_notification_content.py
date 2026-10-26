"""Beginner-facing notification guides; keep deployment support distinct from enabled features."""


NOTIFICATION_GUIDES = {
    "실시간 알림과 WebSocket": {
        "intro": "새 댓글이나 쪽지가 왔을 때 화면 위 알림 벨의 숫자가 바뀌는 기능을 설명합니다. 먼저 이 장에서 동작을 이해한 다음, 서버에 올리기의 ‘실시간 알림 설정과 운영’을 따라 설정하세요. 알림을 DB에 저장하는 기능과 브라우저에 즉시 알려 주는 기능은 각각 확인해야 합니다.",
        "sections": [
            {"heading": "폴링과 WebSocket을 쉽게 이해하기", "paragraphs": [
                "폴링은 브라우저가 일정 간격으로 ‘새 알림이 있나요?’라고 서버에 묻는 방식입니다. 이 프로젝트의 알림함 주소는 {{GET /api/v1/notifications}}입니다. 연결 환경이 단순하고, WebSocket이 없어도 사용할 수 있습니다.",
                "WebSocket은 로그인한 브라우저와 서버 사이에 통신 연결을 열어 두는 방식입니다. 서버가 변경 사실을 알려 주면 브라우저가 기다리지 않고 알림함을 다시 읽습니다. 여러 웹 서버 사이에 이 신호를 전달하는 통로로 Redis를 사용하고, Django Channels가 회원별 연결을 관리합니다."
            ]},
            {"heading": "어떤 일이 생기면 알림을 만드나요?", "bullets": [
                "댓글: 새 댓글이 달리면 원글 작성자에게 알립니다. 답댓글이면 부모 댓글 작성자도 대상이며, 같은 회원은 한 번만 포함합니다. 자신이 쓴 댓글로 자신에게 알림을 보내지는 않습니다.",
                "쪽지: 받은 쪽지의 수신자에게 알립니다. 보낸 편지함의 복사본이나 자신에게 보낸 쪽지를 별도 알림으로 중복 생성하지 않습니다.",
                "주문: 회원 주문의 상태가 실제로 바뀌면 주문한 회원에게 알립니다. 주문 생성이나 배송 메모만 수정한 경우는 이 상태 변경 알림의 대상이 아닙니다. 비회원 주문에는 회원 알림함이 없습니다.",
                "관리자 공지: 권한이 있는 관리자가 지정한 회원들에게 공지 알림을 발송할 수 있습니다. 발송 방법은 아래 관리자 공지 절차를 읽으세요.",
                "과거 자료 가져오기와 샘플 생성은 자동 알림을 억제합니다. 샘플 글을 많이 추가했는데 알림 벨이 늘어나지 않는 것은 정상입니다."
            ]},
            {"heading": "알림은 어떤 순서로 도착하나요?", "steps": [
                "댓글·쪽지·주문 변경을 먼저 DB에 저장합니다. 원래 작업이 취소되면 해당 자동 알림 콜백도 취소됩니다.",
                "원본 저장이 확정되면 DB 대기 작업을 기록하고, 회원 알림함에 저장을 시도합니다. 정상일 때는 WSGI 환경에서도 REST로 곧바로 조회할 수 있습니다.",
                "별도 알림 작업자가 대기 중인 변경 신호를 Redis 채널 계층으로 보냅니다.",
                "연결된 회원의 브라우저가 {{notifications.changed}} 신호를 받습니다.",
                "브라우저가 자신의 REST 알림함을 다시 읽고 목록과 읽지 않은 개수를 갱신합니다. 알림 기록의 기준은 DB입니다."
            ], "note": "원본 커밋과 첫 대기 작업 기록 사이에 프로세스가 종료되면 이벤트를 잃을 수 있는 짧은 구간이 있습니다. 모든 이벤트의 무손실 전달이나 정확히 한 번 전달을 보장하는 구조로 설명하면 안 됩니다. 저장된 대기 작업은 재시도·중복 방지 기능으로 복구합니다."},
            {"heading": "개인정보와 비밀글은 어떻게 보호하나요?", "paragraphs": [
                "WebSocket에는 글 본문·쪽지 내용·주문 개인정보를 넣지 않고 ‘변경됐다’는 신호만 보냅니다. 자동 댓글·쪽지 알림에도 본문과 원글 제목을 복사하지 않습니다. 알림 링크를 열 때는 원래 페이지의 권한 검사를 다시 받습니다.",
                "회원은 자신의 연결 그룹에만 들어갑니다. 브라우저가 다른 회원 번호나 그룹을 지정해서 구독할 수 없습니다. 로그인 상태와 토큰 폐기 여부를 연결 중에도 다시 확인합니다.",
                "접속을 허용할 사이트 주소는 서버의 Origin 허용 목록으로 제한합니다. 브라우저에서 Origin 검사를 끄거나 전체 허용으로 바꾸는 방법으로 연결 오류를 해결하지 마세요."
            ]},
            {"heading": "개발자가 연결할 API와 메시지", "steps": [
                "기존 방식으로 먼저 로그인합니다. JWT 또는 Django 로그인 세션이 필요합니다.",
                "{{POST /api/v1/notifications/ticket}}으로 접속권을 요청합니다. 쿠키·세션 인증이면 기존 CSRF 검사도 통과해야 합니다. 회원당 분당 30회 제한이 있습니다.",
                "응답의 {{data.enabled}}가 {{false}}이면 WebSocket이 꺼진 환경입니다. REST 폴링으로 계속 조회합니다.",
                "켜진 환경이면 응답의 {{websocket_url}}에 연결하고, 5초 안에 첫 메시지로 authenticate와 ticket을 보냅니다. 접속권은 기본 30초 동안 유효하고 한 번만 사용할 수 있습니다.",
                "ready를 받은 뒤 변경 신호가 오면 REST 알림함을 재조회합니다. ping에는 pong으로 응답합니다. 읽음 처리와 삭제도 기존 HTTP API를 사용합니다."
            ], "code": 'POST /api/v1/notifications/ticket\n\n첫 메시지:\n{"type":"authenticate","ticket":"HTTP에서 받은 일회용 접속권"}\n\n서버 응답:\n{"type":"ready","version":1}\n\n변경 알림:\n{"type":"notifications.changed","version":1}\n\n유지 확인:\n{"type":"ping"}\n{"type":"pong"}', "note": "JWT나 접속권을 WebSocket 주소의 쿼리 문자열에 붙이지 않습니다. 쿼리 문자열이 있거나 임의 그룹을 지정하는 요청은 거부됩니다. 직접 연동하기 전 기존 nextjs/src/services/notification-stream.ts를 참고하세요."},
            {"heading": "연결이 끊기거나 여러 탭을 열면요?", "paragraphs": [
                "브라우저는 끊어진 연결을 점차 간격을 늘려 다시 시도합니다. 접속 직후·재접속·탭으로 복귀·인터넷 연결 복구 시 REST로 상태를 맞춥니다. 정상 연결 중에도 5분마다, 연결 실패 중에는 60초마다 재조회합니다.",
                "다른 탭에서 모두 읽음이나 전체 삭제를 하면 변경 신호를 통해 다른 연결도 새 상태를 읽습니다. 짧은 시간에 여러 신호가 오면 200ms 동안 합쳐 불필요한 재조회를 줄입니다.",
                "로그아웃하거나 탭을 숨기면 연결과 예약 요청을 정리합니다. 연결 자체는 기본 약 5분 후 새 접속권으로 갱신하며, 호스팅의 함수 실행 제한 때문에 더 일찍 끊어질 수도 있습니다. 끊김 자체보다 재접속 후 목록이 맞는지를 확인하세요."
            ]},
            {"heading": "관리자 공지 알림을 보내는 방법", "steps": [
                "알림 추가 권한이 있는 관리자 계정으로 로그인하고 {{/admin/core/notification/announce/}}을 엽니다.",
                "제목과 내용, 필요하면 {{/bbs/notice/1}} 같은 사이트 내부 이동 경로를 입력합니다.",
                "회원 아이디 지정·활성 스태프·활성 회원 전체 중 대상을 고릅니다. 한 번에 최대 500명입니다.",
                "발송 확인을 체크하고 보냅니다. 먼저 승인된 테스트 회원 한 명으로 확인하세요.",
                "수신자의 알림함과 관리자 발송 기록을 확인합니다. WebSocket이 꺼져 있으면 REST 재조회나 새로고침으로 확인합니다."
            ], "note": "같은 제출 요청은 DB 기록으로 중복 방지합니다. 화면을 새로 열어 다시 보내면 새 공지가 됩니다. 알림 공지는 이메일·문자·휴대전화 OS 푸시 발송을 뜻하지 않습니다."},
            {"heading": "Expo 앱과 FCM·APNs는 어디까지 되어 있나요?", "paragraphs": [
                "현재 저장소에는 Expo·React Native 앱과 FCM/APNs 전송 연동이 없습니다. 구현된 것은 로그인한 웹 화면의 알림함과 선택 가능한 WebSocket 전송입니다. 이 기능만으로 앱이 닫힌 휴대전화에 OS 알림이 뜨지는 않습니다.",
                "앱을 추가할 때는 알림 수신 동의, 회원별·기기별 토큰 등록 API, 로그인·로그아웃 시 토큰 연결과 해제, 만료 토큰 정리, FCM/APNs 또는 Expo 전송 자격 증명과 발송 작업을 별도로 준비합니다.",
                "푸시에는 민감한 본문을 넣지 않는 정책과 앱에서 링크를 열 때의 권한 검사도 필요합니다. 발송 재시도와 중복 알림 정책, Android·iOS 실제 기기에서 앱이 켜진 상태와 종료된 상태를 각각 확인한 뒤 제공하세요."
            ]}
        ]
    },
    "실시간 알림 설정과 운영": {
        "intro": "운영자가 WebSocket 알림을 켜고 유지하는 순서입니다. 명령은 manage.py가 있는 저장소 루트에서 실행합니다. 이미 쓰는 DB와 Redis가 있어도 웹 서버 실행 방식·연결 주소·상시 작업자를 함께 준비해야 합니다. Vercel은 다음 장 ‘Vercel에서 Redis와 작업자 연결’을 함께 읽으세요.",
        "sections": [
            {"heading": "설치 전 준비물과 역할", "bullets": [
                "DB: 회원 알림과 재시도 작업을 보관합니다. 웹 서버와 작업자는 같은 대상 DB를 사용해야 합니다.",
                "ASGI 서버: WebSocket 연결을 받습니다. example/asgi.py가 있어도 기존 WSGI 실행 명령을 자동으로 바꾸지는 않습니다.",
                "Django Channels와 channels-redis: 회원별 소켓 연결과 서버 사이의 변경 신호를 관리합니다.",
                "Redis: TCP 또는 TLS 연결을 제공해야 합니다. HTTPS REST API 주소만 제공하는 연결 방식은 이 Channels 설정에 사용할 수 없습니다.",
                "전용 알림 작업자: DB 대기 작업을 처리하는 process_notifications입니다. Celery worker와 별도 프로세스입니다.",
                "운영 도메인의 HTTPS/WSS와 정확한 Origin 허용 목록, 장애 로그를 볼 권한이 필요합니다."
            ]},
            {"heading": "먼저 DB와 선택 패키지를 준비합니다", "steps": [
                "적용할 사이트의 DB 주소와 기존 백업을 확인합니다. 로컬·미리보기·운영 환경을 구분합니다.",
                "기본 requirements가 설치된 환경에 requirements-realtime.txt의 선택 패키지를 추가합니다.",
                "해당 DB를 가리키는 환경에서 migrate를 실행합니다. core.0013은 읽지 않은 알림 인덱스, core.0014는 중복 방지 키·대기열·공지 기록입니다.",
                "Django check로 설정을 확인하고, 웹과 작업자에 동일한 DB·SECRET_KEY·알림 설정을 준비합니다."
            ], "code": "python -m pip install -r requirements-realtime.txt\npython manage.py migrate\npython manage.py check", "note": "기본 설치에 선택 패키지를 더하는 순서입니다. 공개 데모와 핸드북 DB에는 2026-10-22 알림 마이그레이션을 적용했지만, 새로 설치한 사이트는 자신의 DB 적용 여부를 따로 확인해야 합니다."},
            {"heading": "환경 변수를 한 항목씩 이해하기", "bullets": [
                "{{NOTIFICATION_EVENTS_ENABLED=True}}: 새 댓글·쪽지·주문 변경의 알림 생성을 켭니다. 과거 자료를 가져올 때의 억제 기능과 함께 사용합니다.",
                "{{NOTIFICATION_WS_ENABLED=True}}: 소켓 전송을 켭니다. 기본값은 False이며 ASGI·Redis·작업자를 모두 준비한 뒤 변경합니다.",
                "{{NOTIFICATION_REDIS_URL}}: 알림용 Redis 연결 주소입니다. 운영에서는 제공자가 발급한 rediss:// TLS 연결을 사용하고 비밀번호를 비밀 저장소에 보관합니다.",
                "{{NOTIFICATION_WS_ORIGINS}}: 브라우저 주소창의 사이트 주소입니다. https://example.com처럼 스킴과 호스트를 적고 포트가 있으면 포함합니다. 여러 개면 쉼표로 구분합니다. 경로와 와일드카드는 넣지 않습니다.",
                "{{NOTIFICATION_WS_URL}}: 같은 도메인이면 /ws/notifications/, 분리형이면 wss://알림서버/ws/notifications/ 같은 전체 주소입니다.",
                "일반 페이지 캐시의 CACHE_URL, 메일 Celery의 CELERY_BROKER_URL과 알림 Redis 주소는 서로 다른 설정입니다. 하나를 바꿔도 나머지가 자동으로 연결되지는 않습니다."
            ], "code": "NOTIFICATION_EVENTS_ENABLED=True\nNOTIFICATION_WS_ENABLED=True\nNOTIFICATION_REDIS_URL=rediss://<사용자>:<비밀번호>@<Redis호스트>:<포트>/0\nNOTIFICATION_WS_ORIGINS=https://example.com\nNOTIFICATION_WS_URL=/ws/notifications/", "note": "예제의 꺾쇠 값은 실제 비밀 저장소에서 바꿉니다. 연결 주소를 채팅·Git·화면 캡처에 남기지 마세요. 같은 앱의 HTTP·ASGI·작업자는 같은 SECRET_KEY를 써야 일회용 접속권의 키 공간이 일치합니다."},
            {"heading": "로컬에서 두 프로세스로 실행하기", "paragraphs": [
                "먼저 별도 개발 DB와 Redis를 준비하고, 두 터미널에 같은 환경 변수를 설정합니다. 기존 8081 서버를 덮어쓰지 않도록 예제는 8001 포트를 사용합니다. 브라우저가 HTTP API와 소켓 모두 같은 앱·DB를 보도록 맞추세요.",
                "로컬 Origin은 예를 들어 http://127.0.0.1:3000이고 소켓 주소는 ws://127.0.0.1:8001/ws/notifications/입니다. 운영 HTTPS 주소의 wss://와 로컬 ws://를 구분합니다."
            ], "code": "# 터미널 1: ASGI 웹 서버\npython -m uvicorn example.asgi:application --host 127.0.0.1 --port 8001 --lifespan off --ws-max-size 1024 --ws-max-queue 8\n\n# 터미널 2: 같은 설정으로 실행하는 알림 작업자\npython manage.py process_notifications --apply --watch --interval 1", "note": "기본 Django runserver의 WSGI 실행만으로는 소켓을 제공하지 않습니다. Next.js 3000을 사용하면 API 프록시 대상도 8001의 /api/v1로 맞춥니다. 정적 파일 서빙은 기존 개발·운영 설정을 따로 준비하세요."},
            {"heading": "Docker VPS에서 실행하기", "paragraphs": [
                "기존 VPS의 .env·DB·메일 설정을 준비하고 NOTIFICATION_WS_ORIGINS를 실제 HTTPS 사이트 주소로 지정합니다. Compose 내부 Redis 예제는 redis://redis:6379/2입니다. Redis를 외부 인터넷에 공개할 필요는 없습니다.",
                "아래 추가 Compose 파일은 선택 패키지를 설치하고 웹을 Uvicorn으로 실행하며 notification-worker도 시작합니다. 기본 Compose 파일만 실행하면 기존 WSGI 구성입니다."
            ], "code": "docker compose --profile realtime -f docker-compose.yml -f docker-compose.realtime.yml up -d --build\ndocker compose --profile realtime -f docker-compose.yml -f docker-compose.realtime.yml exec web python manage.py check", "note": "HTTPS 역방향 프록시의 /ws/notifications/도 ASGI로 전달해야 합니다. WebSocket Upgrade 헤더와 읽기 제한 시간을 설정하고, 상세 예제는 저장소 docs/04-deploy/realtime-notifications.md를 참고하세요."},
            {"heading": "Celery와 Redis를 이미 쓰면 무엇을 재사용하나요?", "paragraphs": [
                "기존 Redis의 연결·명령 지원·용량·접근 정책이 맞으면 공유할 수 있습니다. Compose 예제는 Celery broker와 결과에 /0, 일반 캐시에 /1, 알림에 /2를 사용합니다. 이것은 한 Redis 서버 안의 논리 DB 번호입니다.",
                "일부 관리형 Redis나 Redis Cluster는 DB 0만 지원합니다. /1이나 /2를 그대로 복사하지 말고 제공자 지원 범위를 확인한 뒤 별도 인스턴스나 충돌하지 않는 키 공간을 구성하세요. 프로젝트 간 운영·Preview 분리도 유지합니다.",
                "Celery worker를 켜는 것만으로 알림 작업자가 시작되지는 않습니다. 기존 Celery 작업이 알림을 만드는 경우에는 그 프로세스에도 같은 선택 패키지와 알림 설정이 필요합니다."
            ]},
            {"heading": "켜진 것을 실제로 확인하는 순서", "steps": [
                "허가된 테스트 회원 두 명으로 서로 다른 브라우저에 로그인합니다. WebSocket 전송을 켠 서버에서는 개발자 도구 Network에서 /ws/notifications/ 연결과 ready 메시지를 확인합니다.",
                "한 회원의 글에 다른 회원이 댓글을 작성하고, 원글 작성자의 벨과 알림함이 즉시 갱신되는지 봅니다. 본인이 쓴 댓글에는 자기 알림이 없어야 합니다.",
                "쪽지 수신·시험용 주문 상태 변경·관리자 공지를 각각 확인합니다. 다른 회원의 알림이나 민감한 본문이 나오면 중단하고 권한 설정을 점검합니다.",
                "두 탭에서 모두 읽음·전체 삭제를 확인하고, 인터넷을 끊었다 다시 연결하거나 탭을 숨겼다 열어 목록이 맞춰지는지 확인합니다.",
                "운영 서비스를 중단시키는 대신 별도 검증 환경에서 Redis 장애와 복구를 확인합니다. 저장된 DB 알림은 REST로 읽히고, 복구 후 대기 작업이 처리되어야 합니다."
            ]},
            {"heading": "대기열을 확인하고 실패 작업을 재시도하기", "paragraphs": [
                "기본 명령은 읽기 전용 상태 확인입니다. pending은 재시도 대기까지 포함한 미완료 수, due는 지금 처리할 수 있는 수입니다. --apply를 붙이면 실제로 처리합니다.",
                "실패 작업은 5초부터 최대 1시간까지 간격을 늘려 재시도합니다. 실패 작업을 삭제해서 수치를 낮추지 마세요. 완료한 대기열 기록만 7일 뒤 정리되며, 회원 알림과 공지 중복 방지 기록의 보존 정책은 별도입니다.",
                "로그에서 notification_event_enqueue_failed, notification_work_retry, notification_channel_failed 같은 이름과 오류 종류를 확인합니다. 유휴 연결이 반복해서 끊기면 Redis의 블로킹 읽기 제한을 임의로 1초 등으로 줄이지 않았는지도 확인합니다."
            ], "code": "python manage.py process_notifications --json\npython manage.py process_notifications --apply --limit 50 --json"},
            {"heading": "자주 생기는 문제를 구분하기", "bullets": [
                "접속권 응답 enabled=false: 소켓 기능이 꺼진 환경입니다. REST 조회로 알림이 보이는지 먼저 확인합니다.",
                "접속권 401 또는 403: 로그인·토큰·CSRF 설정과 실제 요청 도메인을 확인합니다.",
                "접속권 503 또는 연결 종료 1013: Redis 연결·선택 패키지·서버 로그를 확인합니다. 비밀 주소를 그대로 오류 보고서에 붙이지 않습니다.",
                "연결 404 또는 HTTP 응답만 보임: WSGI 실행 여부와 ASGI 진입점, /ws 경로의 프록시·배포 라우팅을 확인합니다.",
                "알림함에는 있는데 즉시 갱신 안 됨: 알림 작업자 실행 여부, due 수치, Redis 설정과 Origin을 확인합니다.",
                "소켓 종료 4401: 만료·재사용·폐기된 접속권 또는 로그인 상태입니다. 기존 접속권을 재사용하지 말고 새로 로그인하거나 발급받습니다.",
                "실시간을 잠시 중단하려면 NOTIFICATION_WS_ENABLED=False로 변경하고 웹과 작업자를 다시 배포합니다. 저장된 알림은 REST에서 계속 조회할 수 있습니다."
            ]}
        ]
    },
    "Vercel에서 Redis와 작업자 연결": {
        "intro": "Vercel에서 웹 요청과 상시 작업자를 함께 운영하는 방법입니다. 2026-10-22 기준 공식 문서를 참고한 도입 가이드이며, 이 글을 추가하는 작업에서 Redis나 Daemons를 실제로 활성화하지는 않습니다. 먼저 현재 사이트의 설정과 비용 한도를 확인하세요.",
        "sections": [
            {"heading": "현재 공개 데모는 어디까지 적용됐나요?", "bullets": [
                "알림 DB·자동 생성·관리자 공지·재시도 대기열과 두 테마의 알림 벨이 반영되어 있습니다.",
                "현재 데모와 핸드북은 example/wsgi.py를 사용하는 배포이며 NOTIFICATION_WS_ENABLED=False입니다. 접속권을 요청해도 실시간 연결이 켜져 있다는 뜻은 아닙니다.",
                "확인한 배포용 설정은 DB 캐시, CELERY_TASK_ALWAYS_EAGER=True이며 알림용 Redis는 미설정입니다. Celery 작업은 별도 큐 작업자 대신 요청 안에서 실행됩니다.",
                "메일 Celery worker와 알림 전용 작업자를 상시 실행하려면 아래 배포 구성을 추가해야 합니다. 운영자가 이후 설정을 바꿨다면 실제 환경 변수와 Logs를 기준으로 판단하세요."
            ]},
            {"heading": "Vercel에서도 Celery를 실행할 수 있나요?", "paragraphs": [
                "가능합니다. 2026-10-15 공개 베타로 나온 Vercel Daemons는 컨테이너 형태의 Celery worker 같은 상시 프로세스를 실행합니다. 웹 요청을 처리하는 Functions와 같은 프로젝트에 추가하고, 별도 인스턴스 수를 지정합니다.",
                "Celery 전용 Vercel Queues 연동도 공식 예제가 있지만 기존 Redis broker를 그대로 쓰는 구성과는 다른 방식입니다. 이 프로젝트의 설정을 유지하는 도입안은 외부 Redis와 Daemons를 연결하는 방식입니다.",
                "Daemons에는 메일용 celery -A example worker와 알림용 process_notifications 작업자를 각각 구성할 수 있습니다. 웹 서버는 기존 Functions에서 운영합니다."
            ]},
            {"heading": "Redis 연결부터 준비합니다", "steps": [
                "Vercel Marketplace 또는 관리형 제공자에서 Redis를 준비하고, 서버용 TCP/TLS 연결 주소와 인증 정보를 확인합니다. REST 토큰·HTTPS 엔드포인트만으로 Channels를 연결하지 않습니다.",
                "제공자가 channels-redis의 필요한 명령과 블로킹 읽기, Celery broker를 사용할 경우 해당 동작도 지원하는지 확인합니다. Redis라는 제품명만으로 호환성을 판단하지 않습니다.",
                "알림용 NOTIFICATION_REDIS_URL, 필요하면 캐시용 CACHE_URL과 Celery broker·결과 주소를 각각 설정합니다. Redis가 논리 DB 0만 지원하면 Compose 예제의 /1, /2를 그대로 복사하지 않습니다.",
                "HTTP·ASGI·작업자가 같은 프로젝트의 DB·SECRET_KEY·알림 Redis를 보도록 준비합니다. 현재 DB 캐시는 유지하고 알림용 Redis만 추가하는 구성도 가능합니다.",
                "데모·핸드북·Preview의 DB와 비밀을 혼용하지 않습니다. 현재 Preview 설정은 소켓을 강제로 끄므로 운영 Redis를 재사용해서 시험하지 마세요."
            ]},
            {"heading": "웹 함수를 ASGI로 준비합니다", "steps": [
                "별도 검증 환경에서 example/asgi.py를 Python ASGI 진입점으로 연결하고 /ws/notifications/와 기존 HTTP·정적 파일 라우팅을 함께 확인합니다.",
                "Vercel 설치 과정에 requirements-realtime.txt의 패키지가 실제로 포함되도록 구성합니다. 파일을 저장소에 추가하는 것만으로 기본 requirements 설치 목록이 바뀌지는 않습니다.",
                "Fluid compute와 현재 Python WebSocket 지원 조건, 함수 최대 실행 시간을 확인합니다. 연결은 함수 수명에 따라 끊어질 수 있으므로 새 접속권과 재접속을 확인합니다.",
                "NOTIFICATION_WS_ORIGINS에는 실제 브라우저 도메인, NOTIFICATION_WS_URL에는 실제 소켓 경로를 넣습니다. 로그에 URL 쿼리로 인증 값을 남기지 않습니다.",
                "웹·Redis·알림 작업자를 모두 준비한 뒤 NOTIFICATION_WS_ENABLED를 켜고 새 Production 배포를 만듭니다. 현재 WSGI 배포에서 플래그만 먼저 바꾸면 안 됩니다."
            ]},
            {"heading": "상시 작업자를 Daemons로 나눕니다", "paragraphs": [
                "알림용 Dockerfile에는 기본·실시간 선택 의존성과 앱 코드를 포함하고 작업 디렉터리와 환경을 맞춥니다. 메일 작업자를 함께 운영한다면 두 프로세스를 각각 Daemon으로 정의해 상태를 구분합니다.",
                "루트 vercel.json 등의 daemons 항목에 Dockerfile 위치·실행 명령·인스턴스를 지정하는 것이 공식 방식입니다. 현재 저장소의 vercel.json에는 이 항목이 없습니다. 기존 Docker Compose 설정을 Vercel이 자동으로 실행하는 것은 아닙니다.",
                "아래는 역할별 시작 명령입니다. 완성된 Vercel 배포 설정 예제가 아니므로 Dockerfile의 빌드 범위, 환경 변수, 종료·재시작, DB 연결 수를 별도로 확인해야 합니다. Vercel Daemon의 command는 이미지의 ENTRYPOINT와 CMD를 바꾸므로 기존 진입 스크립트가 자동으로 실행된다고 가정하지 마세요."
            ], "code": "# 알림용 Daemon의 시작 명령\npython manage.py process_notifications --apply --watch --interval 1\n\n# 메일용 Celery Daemon의 시작 명령\ncelery -A example worker --loglevel=INFO", "note": "Celery worker를 실제로 사용하려면 연결 가능한 broker를 준비한 뒤 CELERY_TASK_ALWAYS_EAGER=False로 전환합니다. True이면 작업자를 띄워도 웹의 메일 작업은 계속 요청 안에서 실행됩니다. 마이그레이션은 별도 배포 준비 단계에서 한 번 적용하세요."},
            {"heading": "무료 한도와 베타 제약을 먼저 확인합니다", "paragraphs": [
                "2026-10-22 확인한 Daemons 문서에서는 Hobby도 지원하며 팀 전체 월 Active CPU 10시간 한도가 있습니다. 한도를 넘으면 다음 달 UTC 기준 초기화 또는 요금제 업그레이드까지 Daemon이 중지됩니다. 대기 시간과 실제 CPU 사용 시간은 다릅니다.",
                "Pro·Enterprise는 CPU와 메모리 사용량 과금이 적용되고 Redis 제공자의 요금·한도도 따로 봐야 합니다. 무료 기능이 있다는 이유로 메일 대량 발송이나 초 단위 DB 폴링의 비용이 항상 없다고 가정하지 마세요.",
                "Daemons 베타는 Production에서만 실행되며 Preview·자동 확장·영구 로컬 저장소·외부 HTTP/TCP 수신을 지원하지 않습니다. 앱 DB와 파일은 기존 PostgreSQL·Storage에 보관하고 인스턴스 수를 명시합니다. 변경 후 공식 한도 문서를 다시 확인하세요."
            ]},
            {"heading": "배포한 뒤 어디를 확인하나요?", "steps": [
                "Vercel에서 웹 배포가 Ready인지 확인하고, Daemon Logs에서 알림 작업자가 반복 재시작하거나 DB·Redis 연결 오류를 내지 않는지 봅니다.",
                "작업자와 같은 설정으로 process_notifications --json을 실행하거나 읽기 전용 관리자 대기 작업 화면에서 pending·due가 쌓이는지 확인합니다.",
                "승인된 시험 계정으로 댓글·쪽지·주문 상태·관리자 공지를 확인합니다. 웹 소켓의 ready 이후 변경 신호와 REST 재조회가 이어져야 합니다.",
                "별도 검증 환경에서 Redis 복구·재접속·프로세스 종료와 재시도를 확인합니다. Preview에 Daemon이 없다는 점을 고려해 로컬 컨테이너 또는 분리된 시험 환경을 사용합니다.",
                "운영 한도 경고와 작업자 정지, 미완료 수 증가를 감시합니다. 소켓이 꺼져 있어도 DB 알림을 조회할 수 있는 REST 경로를 유지합니다."
            ]},
            {"heading": "확인한 공식 자료와 저장소 안내", "paragraphs": [
                "Vercel Redis 연결: https://vercel.com/docs/redis",
                "Daemons 개요·설정: https://vercel.com/docs/daemons",
                "Daemons 베타 한도·요금: https://vercel.com/docs/daemons/limits",
                "Python ASGI와 WebSocket: https://vercel.com/docs/functions/websockets",
                "Celery와 Vercel Queues의 별도 연동 예제: https://vercel.com/templates/python/python-celery-starter",
                "이 프로젝트의 전체 실행·API·장애 대응 안내: docs/04-deploy/realtime-notifications.md. 모바일 OS 푸시 준비는 개발자 안내서의 ‘실시간 알림과 WebSocket’ 장을 함께 읽으세요."
            ]}
        ]
    },
}
