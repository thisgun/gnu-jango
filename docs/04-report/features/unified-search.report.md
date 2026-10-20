# 통합 검색 고도화 결과

작성일: 2026-10-21

## 구현

- `site_search` 앱, 초기 스키마와 PostgreSQL GIN 마이그레이션 추가.
- Kiwi/한글 2-gram 공통 토큰화와 DB 후보 검색, 최대 200개 문서 BM25 정렬.
- 통합 검색/클릭 API, 제목·본문 권한 분리, 인기어/클릭 제한 보정.
- 기존 게시판·상품 API 색인 연동과 명시 정렬 유지.
- 통합 검색 화면, 자료 종류 필터, 기본/핸드북 테마 산출물 갱신.
- 재색인, 선택 pg_trgm 설치, 클릭 집계 보관기간 정리 명령.
- 검색 결과를 클릭하며 발견한 카테고리 없는 상품의 null 응답 파싱 오류 보완.
- PostgreSQL 검증 중 발견한 방문 기록의 NUL 검색어 저장 오류 보완.

## 검증 결과

| 검증 | 결과 |
|---|---|
| 초기 통합 검색 + 기존 검색 preview/쇼핑몰 검색 | 34개 통과 |
| SQLite 통합 검색 + community API + docs_search 회귀 | 116개 실행, 성공(당시 PostgreSQL 전용 1개 skip) |
| PostgreSQL 16 통합 검색 최종 | 19개 실행, 성공(SQLite 실행 계획 전용 1개 skip) |
| PostgreSQL 입력값 추가 검증 | 1개 통과 |
| SQLite 불용어·과대 토큰·입력 검증 추가 | 2개 통과 |
| 프런트 계약/상품 null/위험 URL/메타데이터 | 3개 통과 |
| TypeScript 및 변경 파일 ESLint | 통과 |
| Python Ruff / Django check / migration drift / diff whitespace | 통과 |
| nextjs_default, handbook 빌드 + 자산 동기화 | 두 테마 통과 |
| 실제 브라우저 | 조사 붙은 질문 → 3종 결과, 상품 필터, 상세 페이지 진입, 클릭 집계, 핸드북 결과·콘솔 오류 없음 |

PostgreSQL 테스트는 기존 서비스와 다른 `127.0.0.1:55439`의 임시 PostgreSQL 16 컨테이너에서 실행했다. GIN 실행 계획 검사는 작은 테스트 자료에서도 인덱스 사용 가능 여부를 확인하기 위해 `enable_seqscan=off`를 사용한다. 실데이터에서 옵티마이저가 선택하는 계획이나 p95를 측정한 결과는 아니다. 한국어 15문항은 합성 fixture의 Top3 목표(80% 이상) 검증이다.

## 반영 절차

새 코드를 사용하는 각 사이트의 관리 환경에서 `migrate`와 `rebuild_search_index`를 먼저 실행한 뒤 새 웹 버전을 배포/Reload한다. 상세 절차는 [운영 안내](../../04-deploy/unified-search.md)에 있다.

## 승인 후 운영 DB 준비 (2026-10-21)

- 사용자가 검색 기능과 가이드의 동시 반영 및 두 Vercel 사이트 배포를 승인했다.
- 기존 두 사이트의 데이터는 저장소 밖 로컬 작업 폴더에 JSON으로 백업했다. 기존 로컬 개발 DB와 8081 서버는 변경하지 않았다.
- 각 Supabase DB에 `site_search.0001_initial`, `0002_postgres_fts`를 적용했다. 다른 대기 마이그레이션은 없었다.
- 데모: 게시글 18건, 상품 6건, 내용관리 문서 0건을 색인했다.
- 핸드북: 기존 본문을 덮어쓰지 않고 `hb_search` 책의 10개 장을 추가했다. 게시글 총 49건을 색인했다.
- 두 DB의 post/product/page 준비 상태는 모두 `ready=True`, `tokenizer=bigram-v1`이다. Kiwi나 pg_trgm은 추가하지 않았다.
- 기본/핸드북 테마는 운영 DB 대신 새 격리 SQLite DB의 고정 날짜 매뉴얼 자료를 사용해 빌드한다.
- 코드 반영은 보호된 main의 PR·필수 CI 절차를 따르고, 배포 완료 뒤 공개 검색 API와 가이드 페이지를 확인한다.

## 남은 운영 확인

- 실제 게시판/상품 질문으로 평가 세트를 확장하고 검색 적중·클릭 품질을 확인한다.
- 자료량별 DB/색인 디스크 사용량과 검색 p95를 측정한다.
- Kiwi를 설치하는 사이트는 설치 후 전체 재색인하고 질문 평가를 다시 실행한다.
- 임시 PostgreSQL 14 폴더 `C:\Users\kagla\AppData\Local\Temp\gnu-jango-unified-search-pg`는 생성 후 사용하지 않았다. 정리 명령은 자동 승인 검토가 `blocked by policy`로 차단했고 추가 이유는 제공하지 않아 남겨 두었다. 실제 검증은 PostgreSQL 16 컨테이너를 사용했다.
