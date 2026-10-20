# 통합 검색 설계

작성일: 2026-10-21 · [계획](../../01-plan/features/unified-search.plan.md) · [PRD](../../01-plan/features/unified-search.prd.md)

## 구성과 데이터 흐름

`site_search` Django 앱이 원본 Post/ShopProduct/ContentPage의 FK를 가진 SearchDocument를 관리한다. 제목·본문을 기존 `docs_search.tokenizer`로 분석한 뒤 SearchPosting에 term/field/frequency를 저장한다. SearchDocument에도 토큰 문자열을 저장해 PostgreSQL의 `simple` SearchVector와 GIN 표현식 인덱스를 사용한다. 제목과 본문 색인을 분리하여 읽을 수 없는 본문이 제목 검색에 영향을 주지 않게 한다.

조회는 원본의 현재 공개/열람 조건을 적용한 문서 queryset → DB 후보 검색 → 최대 200개 후보 BM25 → 제한된 보정 → 응답 순서다. 클릭 토큰은 검색어 원문 없이 query hash·문서 PK를 서명한다. 클릭 저장 직전 공개/열람 조건을 다시 확인한다.

## 데이터 모델

- SearchDocument: kind(post/product/page), 원본 FK 하나(체크 제약), title, title_tokens, body_tokens, fingerprint, tokenizer, indexed_at. 원본 삭제 시 CASCADE.
- SearchPosting: document FK, field(title/body), term, frequency. 문서/field/term 유일 제약 및 term/field/document B-tree 인덱스.
- SearchIndexState: kind PK, tokenizer, ready. 재색인 전 ready=False; 모두 처리한 뒤 True. 형태소 분석기 변경 때 재색인 요구.
- SearchClickDaily: query_hash, document FK, day, count. 일별 유일 제약. 원문 질문·사용자·IP 미저장.

## 일관성과 권한

- 일반 save는 동기 signal로 검색 문서와 토큰을 원자적으로 갱신하고 delete는 FK CASCADE로 반영한다. 외부 atomic 블록에서는 원문과 색인이 함께 rollback된다. 자동 커밋 환경에서 원문 저장 후 색인 실패가 발생하면 명령으로 복구한다. 내용과 무관한 조회수·주문수 갱신에는 재색인 생략. bulk_create/update/import는 `rebuild_search_index` 필수.
- 검색 가능 게시판과 readable_post_queryset으로 제목 후보 제한. 비밀글 본문은 항상 제외. 포인트 유료 본문은 작성자·이미 결제한 회원·전체 관리자만 사용한다. 포인트 조회는 Exists 상관 서브쿼리로 처리한다.
- 판매/카테고리 상태, ContentPage.co_use, 매뉴얼 그룹은 매 요청 원본 테이블을 조회한다.
- 인기어 보정은 공개 집계의 최근 상위 50개만 사용하고 제목에서만 확인한다. 관련도에 최대 5%, 동일 질문 클릭은 최대 10% 보정한다.
- 권한별 결과·본문 후보 점수는 공유 캐시에 저장하지 않는다. 클릭은 15분 만료 서명·권한 재검사·사용자/주소 HMAC 일별 중복 제한·요청 속도 제한·DNT/봇 제외를 적용한다.

## API와 호환성

- GET `/api/v1/search/unified`: q(2~200), type(all/post/product/document), page, limit(1~50), bo_table. `data.results`는 type/id/title/url/snippet/score/click_token 및 상품 가격을 제공. meta는 engine, total, candidate_limit, truncated, pagination.
- 색인 미준비: 503 `search_index_not_ready`, 필요한 종류 안내. 기존 `/search`와 상품 검색은 기존 검색으로 동작한다.
- POST `/api/v1/search/click`: `{token}` → `{recorded}`. 외부 URL로 리다이렉트하지 않는다.
- 기존 `/search` 그룹 응답은 그대로 유지한다. 기본 제목/본문 검색에 준비된 색인을 사용하며 작성자 필드 검색은 호환 경로로 처리한다.
- 상품 검색 기본값은 관련도 우선, 가격 등 명시 정렬은 유지한다.
- 사이트 검색 기본 화면은 통합 API를 사용하고, bo_table/sfl 지정 때 기존 그룹 화면을 유지한다.

## 검증

격리된 SQLite 테스트 DB에서 원본 생성·수정·삭제·rollback·bulk 재색인, 한국어 질문 15개 이상 Top3 평가, 관련도/보정 상한, 인증별 비밀글·포인트·레벨·공개 상태 변경, 클릭 위조·만료·중복·DNT, 페이지 경계·후보 상한을 검증한다. 기존 게시판/상품 검색과 docs_search 회귀 테스트도 수행한다. PostgreSQL 엔진은 실제 테스트 DB가 있으면 동일 테스트를 실행하고 GIN index EXPLAIN을 확인한다. 없으면 실행 여부를 보고서에 명시한다.
