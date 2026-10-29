# AI 의미 검색 (1단계) 운영 안내

작성일: 2026-10-29

매뉴얼(핸드북) 장과 판매 중인 상품을 **임베딩 벡터**로 저장해 두고, 기존 단어 검색 결과에 "뜻이 가까운" 결과를 더해 준다. 예를 들어 "환불 받는 방법"으로 검색하면 본문에 "환불"이라는 단어가 없어도 "주문 취소와 반품 처리" 장을 찾고, "운동화"로 검색하면 "남성 런닝화" 상품을 찾는다.

**기본값은 꺼짐이다.** 아래 설정이 없으면 사이트는 이 기능이 없을 때와 똑같이 동작한다. 모델이 없는 Vercel 데모·핸드북 사이트는 아무 것도 바꿀 필요가 없다.

관련 문서: [통합 검색 운영 안내](unified-search.md), [검색 신뢰성 운영 가이드](search-reliability.md).

## 무엇이 바뀌나

| 화면/API | 의미 검색이 켜졌을 때 |
| --- | --- |
| 통합 검색 `GET /api/v1/search/unified` | `type=all`·`product`·`document`에서 상품·매뉴얼 장을 의미 기준으로 추가한다. `type=post`(일반 게시글)는 그대로다. |
| 상품 검색 `GET /api/v1/shop/products?q=` | 이름·설명·코드·요약 전체 검색일 때만 의미 검색 상품을 추가한다. 한 항목만 고른 검색(`qname=1` 등)은 기존 문자열 검색 그대로다. |
| 매뉴얼 질문 `GET /api/v1/docs/ask` | 근거 문단 후보에 의미가 가까운 장을 추가한다. `answer=1` 답변 모델도 이 근거를 받는다. |

API 응답 형태(필드)는 바뀌지 않는다. 결과 목록과 `meta.total`이 달라지고, 의미 검색 결과가 섞인 응답의 `score`는 BM25 점수 대신 순위 결합 점수(대략 0.01~0.04)가 된다. `score`는 같은 응답 안의 순서 비교에만 쓴다.

## 설정

| 환경 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `G5_AI_SEMANTIC_SEARCH` | `False` | 의미 검색 사용. 아래 주소·모델도 있어야 켜진다. |
| `G5_AI_BASE_URL` | (비어 있음) | OpenAI 호환 API 주소. 예: `http://127.0.0.1:11434/v1`. 비어 있으면 꺼짐. `http`/`https`만 허용하며 주소 안의 계정·비밀번호·쿼리 문자열은 거부한다. |
| `G5_AI_EMBEDDING_MODEL` | (비어 있음) | 임베딩 모델. 권장 `bge-m3`(한국어 포함 다국어, 1024차원). |
| `G5_AI_EMBEDDING_DIMENSIONS` | `1024` | 모델의 벡터 차원. 응답 차원이 다르면 오류로 처리한다. |
| `G5_AI_API_KEY` | (비어 있음) | 클라우드 제공자용 키. `Authorization: Bearer`로만 보내며 로그·오류 화면에 남기지 않는다. `https` 주소(또는 이 서버 자신)에만 보내고, 리디렉션은 따라가지 않는다. 로컬 Ollama는 필요 없다. |
| `G5_AI_TIMEOUT` | `30` | 색인(임베딩 생성) 요청 한 번의 제한 시간(초). 처음 모델을 불러올 때 오래 걸릴 수 있다. |
| `G5_AI_QUERY_TIMEOUT` | `3` | 검색할 때 질문 임베딩을 기다리는 최대 시간(초). 넘으면 단어 검색 결과만 보여 준다. |
| `G5_AI_SEMANTIC_MIN_SIMILARITY` | `0.5` | 이 코사인 유사도 미만인 이웃은 결과에 넣지 않는다. |
| `G5_AI_EMBEDDING_BATCH_SIZE` | `16` | 한 요청에 보내는 글 수. |
| `G5_AI_EMBEDDING_MAX_CHARS` | `3000` | 장·상품 하나에서 보내는 최대 글자 수(앞부분). |
| `G5_AI_SIMILAR_PRODUCTS` | `G5_AI_SEMANTIC_SEARCH` 값 | 상품 상세의 "비슷한 상품"(2단계, 아래 참고). 따로 끄거나 켤 수 있다. |
| `G5_AI_SIMILAR_MIN_SIMILARITY` | `0.65` | 이 유사도 미만인 상품은 "비슷한 상품"에 넣지 않는다. 상품끼리 비교하면 검색보다 점수가 높게 나와 하한이 더 높다. |

`G5_AI_SEMANTIC_MIN_SIMILARITY`는 사이트 글에 맞춰 조정한다. bge-m3로 시험한 값(아래 점검 결과)에서 관련 있는 짧은 질문은 0.55~0.69, 관련 없는 글은 0.28~0.43이었다. 0.45로 낮추면 "랩탑 → 노트북"(0.47)도 잡히지만 엉뚱한 결과가 섞일 가능성도 커진다.

매뉴얼 질문의 답변 모델(`G5_DOCS_LLM_*`)은 별도 설정이다. 이 PC의 로컬 채팅 모델은 `gemma4:e4b`를 쓴다.

```env
G5_AI_SEMANTIC_SEARCH=True
G5_AI_BASE_URL=http://127.0.0.1:11434/v1
G5_AI_EMBEDDING_MODEL=bge-m3
G5_AI_EMBEDDING_DIMENSIONS=1024

# (선택) 매뉴얼 답변 생성 — 같은 Ollama의 채팅 모델
G5_DOCS_LLM_BASE_URL=http://127.0.0.1:11434/v1
G5_DOCS_LLM_MODEL=gemma4:e4b
```

## Ollama 준비 (로컬 개발)

```bash
ollama pull bge-m3
ollama serve            # 이미 실행 중이면 생략
curl http://127.0.0.1:11434/v1/embeddings -H "Content-Type: application/json" \
  -d '{"model":"bge-m3","input":["노트북"]}'
```

`OLLAMA_HOST`를 바꿔 다른 포트에서 실행 중이면 `G5_AI_BASE_URL`도 그 포트로 맞춘다(예: `http://127.0.0.1:11468/v1`). Ollama는 쓰지 않는 모델을 몇 분 뒤 메모리에서 내리므로, 그 뒤 첫 검색은 `G5_AI_QUERY_TIMEOUT`을 넘겨 단어 검색으로 답할 수 있다. 계속 쓰는 서버라면 `OLLAMA_KEEP_ALIVE=-1` 등으로 모델을 올려 둔다.

## 처음 반영할 때

```bash
python manage.py migrate          # ai.0001: 테이블(+PostgreSQL이면 pgvector 확장·HNSW 인덱스)
python manage.py build_embeddings # 매뉴얼 장과 판매 상품 임베딩 생성
```

### 저장 방식과 마이그레이션

- **PostgreSQL + pgvector**: 마이그레이션이 `CREATE EXTENSION IF NOT EXISTS vector`를 실행하고, `embedding` 열을 `vector` 형식으로 만들며, 1024차원용 부분 HNSW 인덱스(`ai_embedding_hnsw_1024`, 코사인)를 추가한다. 검색은 DB 안에서 가장 가까운 벡터를 찾는다.
- **SQLite·MySQL**: 같은 숫자를 float32 바이트로 저장하고 파이썬에서 코사인 유사도를 계산한다. 확장이 필요 없다. 상품·장이 수천 개 수준이면 충분히 빠르다(프로세스마다 한 번 읽어 메모리에 둔다).
- **pgvector가 없는 PostgreSQL**(예: 기존 `postgres:16-alpine` Docker 이미지, 확장 생성 권한이 없는 계정): 마이그레이션은 실패하지 않고 경고만 남긴 뒤 바이트 열로 만든다. 동작은 SQLite와 같다. 나중에 pgvector를 설치했다면 다음 명령으로 열을 바꾸고 다시 만든다.

```bash
python manage.py configure_ai_postgres   # 확장 생성, 열을 vector로 변경(저장된 임베딩 삭제), HNSW 인덱스
python manage.py build_embeddings
```

각 프로세스는 열 형식을 처음 한 번 확인해 기억하므로, 이 명령 뒤에는 웹·작업자 프로세스를 다시 시작한 다음 `build_embeddings`를 실행한다.

1024가 아닌 차원의 모델을 PostgreSQL에서 쓰면 인덱스 없이 정확 탐색한다. 필요하면 차원 수만 바꿔 인덱스를 직접 추가한다.

```sql
CREATE INDEX IF NOT EXISTS ai_embedding_hnsw_768 ON ai_embedding
USING hnsw ((embedding::vector(768)) vector_cosine_ops) WHERE dimensions = 768;
```

### Supabase (데모·핸드북 DB)

Vercel은 `migrate`를 실행하지 않는다. **병합 전에** 각 Supabase DB(데모, 핸드북)에 다음을 적용한다.

1. Supabase 대시보드 → Database → Extensions에서 `vector`를 켠다(또는 SQL 편집기에서 `create extension if not exists vector with schema extensions;`). 그러면 마이그레이션의 `CREATE EXTENSION IF NOT EXISTS`는 아무 일도 하지 않는다. 켜지 않아도 `postgres` 역할로 마이그레이션하면 확장이 만들어진다.
2. 관리 환경에서 `python manage.py migrate ai` (`showmigrations ai`로 먼저 확인).
3. 데모 사이트는 모델이 없으므로 `G5_AI_*`를 설정하지 않는다. 테이블만 비어 있는 채로 있다.

### CI

`.github/workflows/ci.yml`의 django 작업은 `pgvector/pgvector:0.8.7-pg16` 이미지를 쓴다. PostgreSQL 전용 테스트(`gnu_jango/ai/test_pgvector.py`)가 확장·열 형식·HNSW 인덱스 사용을 확인한다. SQLite에서는 이 테스트를 건너뛴다.

## 임베딩 갱신: `build_embeddings`

```bash
python manage.py build_embeddings                 # 매뉴얼+상품, 바뀐 것만
python manage.py build_embeddings --kind docs     # docs | products | all
python manage.py build_embeddings --limit 200     # 이번 실행에서 최대 200개만 (나머지는 deferred)
python manage.py build_embeddings --rebuild       # 내용이 같아도 전부 다시
python manage.py build_embeddings --dry-run       # 엔드포인트를 부르지 않고 할 일만 센다
python manage.py build_embeddings --json
```

- 대상: 매뉴얼 그룹(`cf_docs_group`, 없으면 `G5_DEFAULT_DOCS_GROUP`)에서 "전체 검색 사용"이 켜진 게시판의 원글(답글 제외), 그리고 판매 중(`it_use=1`, 사용 중인 분류)인 상품. 상품은 이름·브랜드/제조사/모델·분류명·요약·설명(태그 제거)을 보낸다.
- **비밀글과 판매 중지 상품은 보내지 않는다.** 이미 저장된 것이 비밀글·판매 중지·삭제가 되면 다음 실행에서 지운다(`pruned`).
- 모델 이름·차원·본문으로 해시를 만들어 바뀐 행만 다시 보낸다. 모델을 바꾸면 전체가 다시 만들어진다.
- 열람 권한은 저장 시점이 아니라 **검색할 때** 현재 게시판 설정과 질문한 사람의 권한으로 다시 검사한다.

### 주기 실행

글 저장 요청 안에서는 임베딩을 만들지 않는다(검색 요청은 질문 임베딩 한 번만 부른다). 대신 정기 작업으로 갱신한다.

- `G5_AI_SEMANTIC_SEARCH=True`이고 `G5_AI_BASE_URL`이 있으면 `run_scheduled_jobs` 목록(`gnu_jango/core/scheduled_jobs.py`)에 `build_embeddings --json --limit 200`이 15분 간격으로 추가된다. `BACKGROUND_JOBS_ENABLED=True`인 서버는 Celery Beat 항목 `maintenance-build_embeddings`로, 서버리스는 `/api/internal/cron`으로 실행된다. 설정을 바꾼 뒤에는 웹·Beat 프로세스를 다시 시작한다.
- cron만 쓰는 서버라면: `*/15 * * * * cd /srv/gnu-jango && python manage.py build_embeddings --limit 200 --json`

## 하이브리드 검색 방식

1. 기존 단어 검색(PostgreSQL FTS 또는 역색인, BM25)으로 결과 순서를 만든다.
2. 질문을 임베딩해(5분 캐시) 종류별로 가까운 이웃을 찾는다. 유사도가 `G5_AI_SEMANTIC_MIN_SIMILARITY` 이상인 것만 남긴다.
3. 이웃을 **단어 검색과 같은 권한·판매·종류 필터**에 다시 통과시킨다. 통합 검색은 `visible_documents`(게시판 목록·열람 권한, 판매 상품, 결과 종류, `bo_table`)와 본문 열람 권한을, 상품 검색은 분류 필터까지 적용된 판매 상품 쿼리셋을, 매뉴얼 질문은 비밀글을 뺀 열람 가능 장 목록을 쓴다. 손님은 읽을 수 없는 장을 의미 검색으로도 받지 못한다.
4. 두 순위를 **Reciprocal Rank Fusion**(`1/(60+순위)`의 합)으로 합친다. 두 쪽 모두에서 찾은 결과가 가장 위로 오고, 의미로만 찾은 결과는 그 아래에 섞인다. 의미로만 찾은 매뉴얼 장은 질문과 글자가 가장 많이 겹치는 문단을 근거로 보여 준다.
5. 가까운 이웃이 하나도 없으면 단어 검색 결과를 그대로 돌려준다.

## 비슷한 상품 (2단계)

상품 상세 API(`GET /api/v1/shop/products/{it_id}`)의 `similar_items`에 임베딩이 가장 가까운 판매 중 상품을 최대 4개 넣고, 상세 화면은 "관련 상품" 아래에 **비슷한 상품**으로 보여 준다.

- 그 상품에 저장된 벡터로 이웃을 찾으므로 **페이지를 열 때 임베딩 엔드포인트를 부르지 않는다**. Ollama가 꺼져 있어도 이미 만든 임베딩으로 동작한다.
- 상품 자신, 관리자가 지정한 관련 상품, 판매 중지·숨김 분류 상품은 빠진다. `build_embeddings`를 아직 돌리지 않은(또는 다른 모델로 만든) 상품은 비어 있고, 화면은 섹션을 그리지 않는다.
- 하한 `G5_AI_SIMILAR_MIN_SIMILARITY`(0.65): 2026-10-29 로컬 데이터(bge-m3)에서 같은 계열 상품은 0.72~0.98, 관계없는 상품은 0.48~0.60이었다. 상품 설명이 짧거나 비슷한 틀을 쓰는 쇼핑몰이면 올리고, 추천이 너무 적으면 내린다.
- 벡터 조회 오류는 경고 로그(`gnu_jango.ai.recommend`)만 남기고 빈 목록으로 응답한다.

## 장애 시 동작

엔드포인트 오류·시간 초과·잘못된 응답·벡터 조회 오류는 모두 경고 로그(`gnu_jango.ai.search`, 오류 종류만 기록)를 남기고 **단어 검색 결과로 응답**한다. 500 오류는 나지 않는다. 한 번 실패하면 30초 동안 엔드포인트를 부르지 않아, 꺼진 모델이 모든 검색에 대기 시간을 더하지 않는다. `build_embeddings`는 실패하면 오류 이유를 출력하고 끝나며, 이미 끝난 묶음은 저장된 채로 남는다.

## 상태 확인

- 관리자 → **AI 의미 검색 임베딩**(최고관리자, 의미 검색이 켜졌을 때 메뉴에 표시; 주소 `/admin/ai/embedding/`): 저장된 행(종류·대상 ID·게시판·모델·차원·갱신 시각)을 읽기 전용으로 보여 주고, 위쪽에 사용 여부·모델·종류별 개수를 표시한다.
- `python manage.py check_search_health --json`: 의미 검색이 켜져 있으면 `embeddings` 항목에 종류·모델별 개수와 마지막 갱신 시각이 들어간다.

## 비용·개인정보

- 색인할 때 매뉴얼 장과 상품의 본문(앞 3000자), 검색할 때 **사용자가 입력한 검색어**가 설정한 엔드포인트로 전송된다. 로컬 Ollama면 이 서버 밖으로 나가지 않는다. 클라우드 제공자를 쓰면 그 제공자의 데이터 보관·학습 정책을 확인하고 개인정보 처리방침에 반영한다.
- 비밀글·판매 중지 상품은 보내지 않지만, 회원 등급으로 제한한 매뉴얼 장은 보낸다(검색 결과에서만 권한으로 거른다). 이런 장을 외부로 보내면 안 된다면 클라우드 엔드포인트를 쓰지 않는다.
- 클라우드 요금은 대략 "색인할 글자 수(처음 1회 + 바뀐 글) + 검색 횟수"에 비례한다. 질문 임베딩은 5분 캐시하며 바뀌지 않은 글은 다시 보내지 않는다.

## 수동 점검 결과 (2026-10-29, 로컬 Ollama 0.40.12 + bge-m3, SQLite)

새 DB에 상품 5개(+판매 중지 1개)와 매뉴얼 장 3개를 만들고 `build_embeddings`를 실행했다(8개 생성, 두 번째 실행은 0개 생성·8개 unchanged).

| 질문 | 단어 검색 | 하이브리드 검색 | 유사도 |
| --- | --- | --- | --- |
| 운동화 | 결과 없음 | 남성 런닝화 | 0.566 |
| 환불 받는 방법 | 결과 없음 | 매뉴얼 "주문 취소와 반품 처리" (통합 검색·매뉴얼 질문 모두) | 0.686 |
| 보온병 | 스테인리스 텀블러 | 같음 | 0.545 |
| 랩탑 | 결과 없음 | 결과 없음(0.466 < 0.5) | 0.466 |

엔드포인트를 꺼진 포트로 바꾸면 같은 질문에 200 응답과 단어 검색 결과가 오고 경고 로그만 남았다.
