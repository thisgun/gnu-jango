# 검색 권한·복구·상태 점검 운영 가이드

## 검색 규칙

게시판 본문 검색에 비밀글·읽기 등급·읽기 포인트 검사를 공통 적용한다. 작성자/분류 등과 섞어 검색하거나 색인이 꺼진 경우에도 동일하다. 통합 검색은 비밀 본문을 색인하지 않는다. 기존 게시판 검색은 작성자·잠금 해제 세션 등 실제 열람 권한이 있는 사용자의 리터럴 본문 검색을 유지하며, 비밀 본문을 공유 색인에 넣지 않는다.

기존 게시판·상품 API는 한글 한 글자와 ASCII 부분 문자열의 리터럴 검색을 유지한다. 넓은 부분 검색에는 원문 조회 비용이 있다. 통합 검색은 두 글자 이상 ASCII 단어·상품코드 접두를 지원한다(`SKU-12345` → `sku-123`). 임의의 문자열 중간 일치와는 다르다. 한국어 토큰 규칙과 통합 API의 최소 두 글자 조건은 유지한다.

PostgreSQL은 저장 시 계산되는 벡터 열과 GIN 인덱스로 후보를 찾는다. BM25에는 후보별 원래 토큰 길이와 질문에 해당하는 빈도만 전송한다. SQLite는 기존 토큰 역색인과 같은 BM25 계산을 사용한다.

빈도만 전송하는 최적화는 [REGEXP_COUNT를 제공하는 PostgreSQL 15 이상](https://www.postgresql.org/docs/15/functions-matching.html)에서 사용한다. PostgreSQL 14는 저장 벡터와 기존 Python 토큰 집계를 사용한다. 실제 부하 검증 버전은 PostgreSQL 16이며 14 호환 분기의 점수 일치를 16에서 시뮬레이션 검사했다.

## 배포 순서

1. 정확한 DB와 백업을 확인한다. 운영과 Preview를 혼동하지 않는다.
2. 새 코드가 있는 관리 환경에서 대상 DB에 먼저 실행한다.

```bash
python manage.py migrate site_search
```

신규 마이그레이션은 `0005_index_retry`, `0006_stored_vectors`, `0007_vector_indexes`다. 기존 토큰으로 벡터와 인덱스를 만들므로 준비된 색인의 전체 재생성은 필요 없다. 기존 코드도 추가 열이 있는 DB에서 동작한다. 새 코드가 먼저 트래픽을 받으면 누락 열/테이블 오류가 날 수 있으므로 DB 적용 후 배포한다.

큰 PostgreSQL 색인에서는 열 추가/인덱스 교체가 잠금과 디스크를 사용한다. 유지보수 시간에 수행한다. SQLite는 테이블 재작성용 임시 공간과 백업 공간을 확보한다.

코드 롤백 시 추가 열/재시도 테이블은 남겨 둘 수 있다. 기존 표현식 인덱스를 교체하므로 구버전 검색의 실행 계획은 달라질 수 있다. DB 역적용은 트래픽을 중단하고 구버전 코드·백업을 확인한 유지보수 상황에서만 수행한다. 새 코드가 서비스 중일 때 벡터 열을 제거하면 검색이 실패한다.

3. 배포 후 아래 상태 점검과 공개 정답표를 실행한다. 처음 설치해 색인이 미준비 상태라면 `rebuild_search_index`를 먼저 실행한다.

## 색인 실패 재처리

일반 게시글·상품·내용 페이지의 `save()`는 원본과 성공 색인 또는 재시도 식별자를 같은 트랜잭션에 넣는다. 재시도 기록도 저장할 수 없으면 원본을 롤백한다. 외부 트랜잭션의 롤백도 재시도 기록을 함께 취소한다.

작업에는 본문·예외 원문을 넣지 않는다. 종류·원본 ID·시도 횟수·예외 종류·다음 실행 시간만 보관한다. 원본 삭제 시 작업도 지운다.

PostgreSQL 마이그레이션은 새 재시도 테이블에서 PUBLIC 및 존재하는 Supabase `anon`/`authenticated` 역할의 직접 권한을 회수한다. Django의 DB 계정은 유지한다. 이 조치는 새 테이블 범위이며 기존 Supabase 테이블 전체의 권한 감사를 대체하지 않는다.

```bash
# 기본은 조회만 한다.
python manage.py retry_search_index --json
# 현재 실행 가능한 항목 최대 25개를 처리한다.
python manage.py retry_search_index --apply --limit 25 --json
```

실패 항목은 남겨 두고 지수 백오프(최대 한 시간)를 적용하며 비정상 종료한다. 오래된 실행 예정 시각부터 처리해 낮은 PK의 실패 항목이 다른 작업을 계속 막지 않게 한다. 최신 원본을 재조회하고 원본→작업 순서로 잠가 중복 실행을 직렬화한다. 큰 대기열은 여러 번 실행한다. Celery는 필요하지 않다.

## 대량 수정·가져오기 후 감사

`update()`와 `bulk_create()`는 저장 신호를 호출하지 않는다. 해당 작업 뒤에는 원본 지문 감사를 수행한다.

```bash
# 읽기만 한다. 불일치는 비정상 종료 코드로 알린다.
python manage.py audit_search_index --kind post --limit 200 --json
# 검토한 불일치 자료의 재처리를 명시적으로 예약한다.
python manage.py audit_search_index --kind post --limit 200 --enqueue --json
python manage.py retry_search_index --apply --json
```

종류는 `post`, `product`, `page`다. `has_more=true`이면 결과의 `cursor`를 다음 `--after`에 넣는다. 글 PK는 숫자, 상품/페이지 PK는 문자열이다. 한 번에 최대 10,000행이며 큰 자료는 커서를 나눠 모두 검사한다. 원본을 수정·삭제하지 않는다.

## 예약 점검과 로그

기존 `run_scheduled_jobs`/인증된 내부 cron에 재시도 후 상태 점검을 추가했다. 기존 cron 호출 설정이 있으면 다음 실행부터 포함된다. 호출 자체가 실패하면 복구도 실행되지 않으므로 외부 스케줄러의 실행/응답 실패 알림을 설정한다.

```bash
python manage.py run_scheduled_jobs --job retry_search_index --job check_search_health --json
python manage.py check_search_health --query "검색" --max-ms 2000 --audit-limit 25 --json
```

상태 점검은 준비 상태, 토크나이저, 오래된 빌드, 원본/색인 건수, 활성 스냅샷 지문, 대기 작업을 검사한다. 종류별 원본 25개씩 순환 검사하고 캐시에 마지막 PK를 보관한다. `--audit-limit 0`은 원본 지문 스캔과 커서 갱신을 생략한다. 예약 작업 dry-run도 이 모드다. 상태 검사·일반 검색은 운영 캐시를 갱신할 수 있다.

전체 순환에는 종류별 `ceil(행 수 / audit-limit) × 실행 주기`가 걸린다. 캐시 초기화는 커서도 초기화한다. 대량 수정 직후에는 수동으로 전체 커서를 순회한다. 상태 검사 성공이 모든 원본 지문을 방금 검증했다는 뜻은 아니다.

비정상 상태·지연 초과는 종료 코드 1이다. `G5_SEARCH_ENABLED=False`이면 비활성을 표시하고 검사를 생략한다. 같은 DB의 재시도 큐도 사용할 수 없는 장애에서는 원본 저장을 성공 처리하지 않는다.

요청 로그 `search_completed`는 시간·종류·반환 수·후보 제한 여부를, `search_failed`는 예외 종류를 기록한다. 이 로그에 질문·IP·본문·예외 원문은 넣지 않는다. `G5_SEARCH_SLOW_MS`(기본 1000ms) 초과는 WARNING이다. 로그 수집기에서 완료/실패 비율과 지연을 집계하고 알림을 설정한다. `Server-Timing: search;dur=...`는 함수 시간이며 네트워크·전체 콜드 스타트 시간이 아니다.

## 배포 후 자동 검사

`.github/workflows/search-smoke.yml`은 성공한 main CI 이후 실행된다. 뒤처진 CI 커밋은 건너뛰고 두 사이트 `/api/v1/status`의 `deployment_revision`이 검사 커밋과 같아질 때까지 유한 대기한다. 이 값은 Vercel `VERCEL_GIT_COMMIT_SHA`다. 비어 있다면 시스템 환경 변수 노출 설정을 확인한다.

그 후 공개 정답표 20문항을 3회 호출한다. DNT·2초 간격을 사용하고 로그인/클릭 기록/운영 DB 쓰기는 하지 않는다. 오류 또는 전체/종류별 Top-3 80% 미만은 Actions 실패다. 결과 JSON은 14일 보관한다. 측정 위치가 다르므로 한국에서 측정한 기존 지연값을 CI 기준으로 그대로 사용하지 않는다. 실패 알림은 GitHub Actions 알림을 이용한다. 워크플로가 main에 반영되기 전에는 자동 검사가 실행된 것으로 간주하지 않는다.

## 격리 DB의 규모 검사

`benchmark_search`는 `gnu_jango_search_bench_*` 이름의 localhost PostgreSQL DB 또는 `search-benchmark-*` SQLite 파일에서만 동작한다. 원본/색인이 비어 있어야 하고 명시적 실행 옵션이 필요하다.

```bash
# 별도 일회용 DB에 연결하고 migrate한 관리 환경에서만 실행한다.
python manage.py benchmark_search --allow-isolated-db --documents 10000 --concurrency 4 --repeats 3 --max-p95-ms 2000 --output benchmark.json
```

합성 페이지를 커밋해 스레드들이 읽게 하고 완료/예외 시 자기 접두 ID 자료만 지운다. 강제 종료로 자료가 남으면 일회용 DB를 폐기한다. 운영 DB를 빈 상태로 만들기 위해 자료를 삭제하면 안 된다.

합성 접두 질문 100개, 모든 1만 건이 맞는 넓은 질문, 동시 조회와 10회 수정을 검사한다. 정확도·색인 상태·설정한 p95 한도를 모두 만족해야 통과한다. 표본이 작은 관리 함수 측정이며 실제 고객 질문, 여러 웹 서버의 HTTP 부하, 운영 콜드 스타트를 보장하지 않는다.
