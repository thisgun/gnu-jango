# Celery Beat·DB outbox 구현 보고

작성일: 2026-10-24

## 구현

- 기존 9개 유지보수 명령을 `CELERY_BEAT_SCHEDULE`에 등록했다. 실제 명령 구현과 수동 실행 호환 경로를 재사용한다.
- `BackgroundJob` 모델과 `core.0015_backgroundjob` 마이그레이션을 추가했다. 상태·작업명·시도 횟수·실행 임대·다음 처리 시각·최종 실패 코드를 저장한다.
- 요청은 DB 대기열만 기록하고 Beat가 UUID를 Redis로 전달한다. 메시지 유실은 재전달하고 중복 전달은 DB의 조건부 claim으로 건너뛴다. 정기 작업은 활성 키로 겹치는 실행을 막는다.
- 재시도와 jitter, 270/300초 soft/hard timeout, 360초 임대 복구, 최종 실패 큐를 구성했다. 메일·SMS의 접수 여부 불명 건은 자동 재송신하지 않는다.
- 메일 기본 backend와 캠페인 등록, 주문·회원 SMS, 인증 완료한 서버 결제 웹훅을 연결했다. 기존 PG 조회·금액·거래 확인과 결제 상태 변경 로직을 유지한다.
- 이미지 원본을 비공개 outbox에 보관하고 공개 경로에는 작은 임시 이미지를 저장한다. 실제 메타데이터 제거·썸네일 생성은 media 큐에서 수행한다. 요청에 필요한 파일·이미지 검증은 유지한다.
- 최고 관리자용 실패 큐와 재처리 명령, 보관 기간 정리, PostgreSQL RLS/API 역할 권한 제거를 추가했다. 작업 원문은 관리자와 Celery/Flower 인자에 노출하지 않는다.
- 일반 작업자·이미지 작업자·단일 Beat·선택적 Flower의 Docker 구성을 추가했다. Flower는 인증·읽기 전용·localhost 노출을 사용한다. Redis는 AOF 볼륨을 사용한다.
- 사이트마다 Redis broker/result 키를 분리하며, 웹·작업자의 설정 일치와 전환·복구 절차를 문서화했다.

## 확인한 내용

- 변경·신규 Python 파일 31개의 구문 분석 통과.
- `BACKGROUND_JOBS_ENABLED=False`와 `True` 각각 Django 시스템 검사 통과(기존 silenced 항목 1개).
- 기본 Compose + monitoring, realtime overlay + monitoring Compose 구성 검사 통과.
- `git diff --check` 통과.

자동 테스트는 추가하거나 실행하지 않았다. 실제 메일·SMS·PG 호출, DB 마이그레이션 적용, Redis 장애·작업자 강제 종료와 재전달, 이미지 변환의 실행 검증은 수행하지 않았다. Flower 컨테이너도 실제로 기동하지 않았다. 위 정적·설정 검사가 기능·장애 복구 검증을 대신하지는 않는다.

## 운영 반영에 필요한 작업

1. 백업 후 새 마이그레이션을 적용한다.
2. 웹과 같은 DB·공유 미디어·외부 발송 설정을 가진 작업자와 Beat 하나를 준비한다.
3. `BACKGROUND_JOBS_ENABLED=True`를 웹·작업자에 함께 적용하고 일반·이미지 큐를 소비하게 한다.
4. 기존 cron/watch 운영과 중복되지 않게 전환하고 실제 대기열 감소·성공·실패 상태를 확인한다.
5. Flower 인증 정보를 저장소 밖에 설정하고 필요할 때 monitoring 프로필을 실행한다.

기존 설치에서는 기본값 `False`를 유지하며 Docker Compose에서는 새 모드를 기본으로 사용한다. 이번 작업에서 공개 데모·핸드북 설정 변경, 운영 DB 마이그레이션, 상시 작업자 배포는 수행하지 않았다.

## 문서

- [계획·PRD](../../01-plan/features/celery-beat-background-jobs.plan.md)
- [운영·복구 가이드](../../04-deploy/background-jobs.md)
