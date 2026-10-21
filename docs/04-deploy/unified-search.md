# 통합 검색 운영 안내

작성일: 2026-10-21

## 처음 반영할 때

이 작업은 DB마다 한 번 필요하다. 데모와 핸드북 Supabase DB는 별개이므로 각각 실행한다. 배포를 승인한 뒤, 새 코드를 가진 별도 관리 환경에서 **마이그레이션 → 재색인 → 새 웹 버전 배포/Reload** 순서로 진행한다. 기존 웹 버전이 실행 중일 때 새 검색 테이블을 먼저 추가할 수 있다. 기존 SQLite 파일을 새 DB로 이동할 필요는 없다.

```bash
python manage.py migrate
python manage.py rebuild_search_index
```

### 핸드북에 상세 가이드 추가하기

핸드북의 새 책 **「검색 운영 · 통합 검색 가이드」**는 `hb_search` 게시판의 10개 장으로 구성된다. 처음 사용하는 사람의 검색 방법, 색인 개념, 최초 설치, Vercel·PythonAnywhere 적용, 한국어 분석과 pg_trgm, 열람 권한, 순위·클릭 집계, API, 문제 해결, 품질·속도 점검을 설명한다.

해당 핸드북 DB를 사용하는 관리 환경에서 다음 순서로 실행한다.

```bash
python manage.py migrate
python manage.py ensure_handbook_samples
python manage.py rebuild_search_index
```

기본 `ensure_handbook_samples`는 빠진 책·장을 추가하며 기존에 직접 편집한 본문과 게시판 설정을 보존한다. 새 책을 추가하는 데 `--refresh`는 필요하지 않다. `--refresh`는 기존 샘플 제목에 해당하는 본문을 덮어쓰므로 별도 의도 없이 사용하지 않는다. 매뉴얼 그룹을 다른 그룹으로 직접 지정한 사이트에서는 이 명령이 그 선택을 바꾸지 않으므로 새 책의 노출 위치를 별도로 확인한다.

가이드 원본은 `gnu_jango/config/handbook_search_content.py`, 목차 등록은 `gnu_jango/config/handbook_samples.py`이다. 사이트는 DB의 글을 읽으므로 소스 배포만으로 새 책이 생성되지는 않는다. 실행 뒤 핸드북 목차에 새 책과 10개 장이 보이는지, 본문·코드 예시·이전/다음 장 이동이 정상인지 확인한다.

PythonAnywhere에서는 먼저 `workon gnu-jango`, `cd ~/gnu-jango`를 실행한다. 검색을 위해 새로운 패키지를 설치할 필요가 없다. 명령이 끝나면 Web 탭에서 Reload한다. Vercel에서는 웹 요청 안에서 전체 재색인을 실행하지 말고, 해당 DB로 연결한 로컬 관리 환경에서 명령을 실행한다. DB 비밀번호는 명령행·Git·채팅에 넣지 않는다.

상태 확인:

```bash
python manage.py shell -c "from gnu_jango.site_search.models import SearchIndexState; print(list(SearchIndexState.objects.values('kind','ready','tokenizer')))"
```

post/product/page 세 종류가 ready=True이면 통합 검색을 사용할 수 있다. 미준비 상태에서는 새 API가 503 `search_index_not_ready`를 반환한다. 화면에서 기존 게시판 검색으로 이동할 수 있으며, 기존 게시판·상품 API는 문자열 검색으로 계속 동작한다.

## 자료 변경과 재색인

이미 운영 중인 사이트에 세대 색인을 추가할 때는 **migrate → 새 웹 버전 배포/Reload → rebuild_search_index** 순서를 사용한다. 새 버전은 최초 세대가 없으면 호환 색인으로 검색한다. 구 버전 요청이 끝난 뒤 재색인하면 새 저장 절차가 활성/준비 중 세대 모두를 갱신한다. 새 설치를 오프라인으로 준비하는 경우에는 위의 최초 설치 순서를 사용할 수 있다.

일반 ORM `save()`는 동기 signal로 검색 문서와 토큰을 원자적으로 갱신하고, ORM `delete()`는 FK CASCADE로 색인을 지운다. 외부 `transaction.atomic()` 안의 저장은 원문과 색인이 함께 rollback된다. 자동 커밋 상태에서는 원문 저장 직후 색인 갱신이 실행되므로, 색인 갱신 오류가 발생한 경우 원문을 확인하고 재색인한다.

`bulk_create`, `bulk_update`, `QuerySet.update`, SQL import는 저장 signal을 거치지 않는다. 공개 여부·열람 등급·카테고리 상태는 요청마다 원본을 확인하지만, 본문이나 제목을 대량 수정한 경우 반드시 재색인한다.

```bash
python manage.py rebuild_search_index --kind post
python manage.py rebuild_search_index --kind product
python manage.py rebuild_search_index --kind page
```

재색인은 기본 25건씩 원본 ID를 읽고 각 문서를 짧은 트랜잭션으로 새 세대에 저장한다. `--batch-size 10`처럼 1~200 범위로 조절할 수 있다. 완료되면 종류별 활성 세대 포인터를 원자적으로 전환한다. 기존 활성 색인이 있으면 작업·실패 중에도 계속 사용한다. 최초 준비 전에는 503을 반환한다. 일반 저장은 활성 세대와 준비 중인 세대를 함께 갱신하고 삭제는 CASCADE로 반영한다.

동일 종류의 재색인은 동시에 실행하지 않는다. 강제 종료된 작업의 소유권은 마지막 진행 갱신으로부터 30분 뒤 다시 확보할 수 있다. 정상 완료·오류 처리 때 쓰지 않는 세대는 작은 묶음으로 정리한다. 기존 문서 식별자와 클릭 FK는 유지한다. 호환 색인도 보존하므로 평상시 색인 공간은 이전보다 늘고 재색인 중에는 새 세대 공간도 추가로 필요하다. 무료 호스팅에서는 여유 공간을 먼저 확인한다. `bulk_update`·직접 SQL을 재색인과 동시에 실행하지 말고, 가져오기가 끝난 뒤 재색인한다.

Kiwi가 없으면 내장 2-gram을 사용한다. 분석기를 설치하려면 `python -m pip install -r requirements-docs-morphology.txt`를 실행한 후 전체 재색인한다. 분석기 설치·제거에 따라 준비 상태의 tokenizer 값이 달라지며, 불일치 상태에서는 새 API를 제공하지 않는다.

## PostgreSQL 선택 설정

기본 마이그레이션은 제목/본문 토큰 필드에 `SearchVector(config='simple')` 표현식 GIN 인덱스 두 개를 만든다. 별도 확장이 필요하지 않다. 토큰은 hex로 인코딩해 상품 코드의 구두점이나 한국어 형태소가 PostgreSQL 기본 파서 때문에 다시 분리되지 않게 한다. PostgreSQL에는 중복 B-tree posting을 저장하지 않는다.

추가로 제목 오타 검색을 사용하려면:

```bash
python manage.py configure_search_postgres
```

이 명령은 **연결된 DB**에 pg_trgm 확장과 lower(title) GIN 인덱스를 만든다. 확장 설치 권한이 필요하다. 성공한 뒤 `G5_SEARCH_TRIGRAM=True`를 설정하고 서버를 다시 시작한다. 정확한 토큰 검색 결과가 0건일 때만 유사 제목을 찾는다. SQLite에서는 이 설정을 사용하지 않는다. pg_bigm/외부 검색 서버는 이번 구현에 포함하지 않는다.

## 랭킹과 개인정보

DB가 후보를 찾고 최대 200건만 BM25로 다시 정렬한다. 제목 토큰은 4배 가중한다. 관리자가 허용한 공개 인기어 최근 7일 상위 50개는 최대 5%, 동일 질문의 최근 30일 클릭은 최대 10% 보정한다. 검색어와 관계없는 문서를 클릭 수만으로 추가하지 않는다. 점수와 후보는 현재 열람 권한 안에서만 계산한다.

공개 인기 검색어는 기본적으로 비어 있다. 운영자가 `G5_SEARCH_PUBLIC_KEYWORDS=배송비,회원가입,테마`처럼 공개해도 되는 단어를 명시해야 한다. 이 목록 안에서만 최근 집계를 제공하며 기본 최소 횟수는 `G5_SEARCH_PUBLIC_MIN_COUNT=5`이다. 단순히 많이 입력됐다는 이유로 개인의 질문을 공개하지 않는다. 이메일·URL·긴 숫자·비밀번호 관련 표현 등으로 보이는 검색어, DNT 요청, 실패·제한된 검색 요청은 방문·검색 통계 기록에서 제외한다. 이는 완전한 개인정보 판별기가 아니므로 자유로운 질문을 허용 목록에 자동으로 추가하지 않는다. 기존 정상 검색 통계에는 검색어 원문이 남을 수 있으며 별도 로그 보관 정책을 적용한다.

클릭 요청은 15분 유효 서명 토큰이 필요하다. 기록 전에 현재 공개/열람 권한을 확인한다. 동일 질문·문서·방문자의 일별 중복은 HMAC 캐시 키로 제한한다. 집계 테이블에는 질문의 HMAC·문서 FK·날짜·횟수만 저장한다. 봇과 DNT 요청은 제외한다. 다중 worker에서 중복 제한과 속도 제한을 공유하려면 기존 프로젝트의 공유 Django cache를 사용한다. LocMemCache에서는 worker별로만 제한된다.

```bash
python manage.py cleanup_search_clicks --days 90
python manage.py cleanup_search_clicks --days 90 --dry-run --json
```

`run_scheduled_jobs`에 90일 클릭 정리를 포함했다. 기존 Vercel cron 또는 시스템 예약 작업이 이 명령을 실행하면 함께 정리된다. 서버를 켜는 것만으로 예약 실행이 생기는 것은 아니다. 위의 `--dry-run`으로 삭제 예정 수를 먼저 볼 수 있다. `G5_SEARCH_CLICK_LOG_ENABLED=False`는 새 클릭 수집을 끈다. `G5_SEARCH_ENABLED=False`는 기존 API를 문자열 검색으로 돌린다.

## API·성능 범위

- `/api/v1/search/unified`: q 2~200자, type all/post/product/document, limit 1~50, page, bo_table.
- `/api/v1/search/click`: POST JSON `{ "token": "결과의 click_token" }`.
- 결과는 일반 텍스트 요약, 현재 열람 가능한 자료의 링크, 상품 가격을 포함한다. 전체 본문을 응답하지 않는다.
- 질문은 최대 24토큰, 제목 256토큰, 본문 4096토큰을 색인한다. 토큰화 입력은 최대 65,536자다. 더 긴 글의 뒷부분은 검색되지 않을 수 있다.
- `meta.total`은 권한을 통과한 전체 적중 수다. `truncated=True`이면 상위 후보 200건만 페이지로 제공한다. 질문을 구체화하거나 종류/게시판을 지정하면 후보를 좁힐 수 있다.
- 존재하지 않는 페이지는 마지막 유효 페이지로 보정한다. 화면은 서버의 `meta.current_page`를 사용한다. 원문은 전체 후보가 아닌 현재 페이지의 결과만 조회하며 문서당 최대 65,536자만 요약 처리에 가져온다. 결과 반환 직전에 권한을 다시 확인한다.
- 기존 문자열 검색의 임의 영문 중간 문자열 일치는 토큰 검색에서 보장하지 않는다. 작성자·분류 필드 등 호환 경로는 기존 방식이다.
- 최초 색인이나 대규모 재색인은 DB 쓰기·디스크를 사용한다. 무료 PythonAnywhere에서는 `du -sh`와 할당량을 확인하고 필요할 때 재색인한다. 100,000건 등 운영 규모의 p95는 실제 PostgreSQL 데이터로 따로 측정해야 한다.

## 검증 명령

```bash
python manage.py test gnu_jango.site_search gnu_jango.core.test_search_preview gnu_jango.core.test_shop_board_search
```

실제 PostgreSQL 테스트 DB로 실행하면 GIN 인덱스의 실행 계획 검증도 수행된다. SQLite에서는 해당 테스트가 명시적으로 skip된다. [Django 전문 검색](https://docs.djangoproject.com/en/6.1/ref/contrib/postgres/search/)과 [PostgreSQL pg_trgm](https://www.postgresql.org/docs/current/pgtrgm.html)을 참조한다.
