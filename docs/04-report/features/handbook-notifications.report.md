# 핸드북 실시간 알림 안내 추가

## 요청과 반영 범위

2026-10-22 공개 핸드북의 알맞은 위치에 Channels·Redis 실시간 알림 설명을 추가했다.
기존 `manual` 그룹과 책을 유지하고 아래 장만 추가했다.

| 책 / 부 | 장 | 공개 주소 |
|---|---|---|
| 개발자 안내서 / 알림과 연동 | 실시간 알림과 WebSocket | https://gnu-jango-handbook.vercel.app/bbs/hb_dev/50 |
| 서버에 올리기 / 실시간 알림 | 실시간 알림 설정과 운영 | https://gnu-jango-handbook.vercel.app/bbs/hb_deploy/51 |
| 서버에 올리기 / 실시간 알림 | Vercel에서 Redis와 작업자 연결 | https://gnu-jango-handbook.vercel.app/bbs/hb_deploy/52 |

## 설명한 내용

- 댓글·쪽지·회원 주문 상태·관리자 공지의 대상과 중복 제외 규칙.
- DB 알림함, 전용 작업자, Redis, Channels, 브라우저 REST 재조회의 역할.
- 접속권·첫 인증 메시지·Origin·CSRF·비공개 본문 보호·재접속과 폴링 복구.
- 선택 패키지, DB 준비, 환경 변수, 로컬 ASGI·Docker 실행, 대기열 조회·재시도·장애 대응.
- 현재 Vercel의 WSGI·DB 캐시·Celery eager·WebSocket 비활성 상태와 별도 활성화 절차.
- Vercel Daemons 공개 베타와 Redis 연결, 메일 Celery 및 알림 작업자의 구분, 무료 한도와 Preview 제약.
- Expo 앱과 FCM/APNs가 현재 없다는 사실과 추후 동의·기기 토큰·발송·실제 기기 확인 준비 사항.

본문 원본은 `gnu_jango/config/handbook_notification_content.py`, 목차 등록은 `handbook_samples.py`에 있다.
기존 배포 문서에도 새 장의 위치와 Daemons 안내, 적용된 DB 마이그레이션 상태를 갱신했다.

## 공개 반영과 확인

대상 DB·매뉴얼 그룹·공개 책·동일 제목 중복을 먼저 조회했다. 저장소 밖에 기존 장과 분류의 백업을 남기고,
트랜잭션 안에서 새 장 3개와 필요한 분류만 추가했다. 기존 49개 장의 제목·본문·순서·분류·작성일 필드가 그대로인지 확인했다.
총 장 수는 52개다. 전체 `--refresh`는 실행하지 않았다.

공개 상세 API의 본문 SHA-256과 원본 일치를 확인했다. 글 주소·목록·통합 검색·질문 검색을 포함한 15개 HTTP 확인이 통과했고,
실제 브라우저에서도 세 장의 본문·목차를 확인했다. 브라우저 콘솔 오류는 없었다.
기존 핸드북 검색 정답표 12문항도 모두 Top 3 정답을 유지했고 요청 오류는 없었다. 소규모 조회이며 부하 시험은 아니다.

두 정적 테마는 고정된 52장 빌드 DB와 package-lock에 맞춘 별도 의존성 설치에서 재생성했다.
기본 테마 610개·핸드북 612개 현재 파일의 동기화 검사가 통과했고, 작업 폴더로 복사한 파일 해시도 일치했다.
실행 중인 3000·8081 서버의 의존성을 교체하지 않았으며, 직접 실행한 빌드용 8000 API는 종료했다.
기능 단위 테스트는 추가하거나 실행하지 않았다.

이번 변경은 문서와 공개 매뉴얼 데이터 반영이다. Redis·Daemons·WebSocket·모바일 푸시를 활성화한 작업은 아니다.
공개 콘텐츠 반영일은 2026-10-22이며, 저장소 변경의 후속 커밋·푸시 요청일은 2026-10-23이다. 기능 활성화 배포는 이번 문서 작업 범위에 포함하지 않는다.
기존 사용자 파일 `docs/handoff/`, `nextjs/AGENTS.md`, `nextjs/CLAUDE.md`는 보존했다.
백업과 공개 확인 기록은 저장소 밖 `E:/gnu-jango/local-notes/handbook-notifications-20261022/`에 보관했다.
