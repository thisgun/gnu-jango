# handbook(매뉴얼) 테마 Vercel 데모 추가하기

기존 데모(`gnu-jango-demo`)는 그대로 두고, **같은 저장소로 Vercel 프로젝트를 하나 더** 만들어 handbook 테마를
따로 보여 주는 방법입니다. 두 사이트는 코드가 같고, 프로젝트 · 데이터베이스 · 환경 변수가 따로입니다.

| | 기존 데모 | handbook 데모 |
|---|---|---|
| Vercel 프로젝트 | `gnu-jango-demo` | 새로 만듦(예: `gnu-jango-handbook`) |
| Supabase | 기존 프로젝트 | **새 프로젝트**(DB를 같이 쓰면 데모 게시판에 매뉴얼이 섞인다) |
| 시작 테마 | `nextjs_default`(기본값) | `G5_DEFAULT_THEME=handbook` |
| 배포 | `main`에 push하면 자동 | 같은 `main` push로 함께 자동 배포 |

`G5_DEFAULT_THEME` · `G5_DEFAULT_DOCS_GROUP` 은 설정 `cf_theme` · `cf_docs_group` 의 **기본값**일 뿐이라, 새 DB에
행을 먼저 쓰지 않아도 첫 화면부터 handbook 으로 뜹니다. 관리자에서 저장한 값이 있으면 그 값이 우선합니다.

## 1. Supabase 새 프로젝트

[deployment-profiles.md](deployment-profiles.md) 2-1과 같습니다. 리전은 Vercel 함수와 같은 쪽(`ap-northeast-2`)으로 하고,
Transaction pooler 주소(6543), Storage 버킷, S3 액세스 키를 새로 발급합니다. 열람만 하는 데모라도 `check_deploy_profile` 이
업로드 저장소(S3)를 요구하므로 버킷은 만들어 둡니다. 무료 플랜의 활성 프로젝트 수 제한에 걸리면 기존 데모를 일시정지해야 할 수 있습니다.

## 2. Vercel 새 프로젝트

1. **Add New → Project** 에서 같은 GitHub 저장소를 Import 합니다. Root Directory는 저장소 루트, Production Branch는 `main`.
2. 환경 변수는 [`deploy/env/vercel-supabase.env.example`](../../deploy/env/vercel-supabase.env.example) 를 따르되
   **새 Supabase의 값**을 넣고, 아래 두 줄을 더합니다(`SECRET_KEY` · `CRON_SECRET` 은 기존 데모와 다른 값으로 새로 만듭니다).
   ```text
   G5_DEFAULT_THEME=handbook
   G5_DEFAULT_DOCS_GROUP=manual
   ```
3. `vercel.json` 은 같은 파일을 쓰므로 리전(`icn1`)과 크론이 그대로 적용됩니다.

## 3. 데이터베이스 초기화 (로컬에서 한 번)

새 Supabase의 연결 문자열을 그 셸에만 설정하고(저장소에 쓰지 않습니다) 같은 환경 변수로 실행합니다.

```bash
export DATABASE_URL='postgresql://postgres.<새-프로젝트-ref>:<비밀번호>@<풀러-호스트>:6543/postgres?sslmode=require'
export DB_DISABLE_SERVER_SIDE_CURSORS=True
python manage.py migrate
python manage.py createcachetable
python manage.py createsuperuser
python manage.py ensure_handbook_samples      # 빠진 샘플 책·장을 추가 (기존에 편집한 본문 보존)
python manage.py check_deploy_profile --profile vercel
```

실제 매뉴얼은 관리자에서 게시판 그룹 `manual`(또는 `G5_DEFAULT_DOCS_GROUP` 에 적은 그룹)에 만들면 됩니다.
게시판 하나가 책, 게시판 분류가 부, 글이 장입니다. 샘플은 그룹 `manual` · 게시판 `hb_*` 만 건드립니다.
배포 후 빠진 샘플 책과 장을 추가하려면 관리자 › 샘플 데이터에서 **매뉴얼 콘텐츠 추가·보강**을 누릅니다.

## 4. 확인

- 첫 화면 HTML에 `data-g5-theme-source="handbook"` 가 있고, 개발자 도구 콘솔에 404 · 스타일 거부 오류가 없어야 합니다.
- `/api/v1/settings` 의 `theme_settings.docs.group` 이 `manual` 이어야 합니다.
- 응답 헤더 `X-Vercel-Id` 의 두 번째 값이 `icn1` 이어야 합니다.

## 5. 실시간 알림 안내

실시간 알림 안내는 다음 위치에 포함됩니다. 샘플 원본은 `gnu_jango/config/handbook_notification_content.py`입니다.

- **개발자 안내서 → 알림과 연동 → 실시간 알림과 WebSocket**: 이벤트별 동작, API·접속권, 보안, 재접속, 관리자 공지와 Expo 푸시 준비 범위.
- **서버에 올리기 → 실시간 알림 → 실시간 알림 설정과 운영**: 선택 패키지, 환경 변수, Uvicorn·알림 작업자, Docker, 대기열·장애 대응.
- **서버에 올리기 → 실시간 알림 → Vercel에서 Redis와 작업자 연결**: 현재 데모 상태, TCP/TLS Redis, ASGI·Daemons 도입 절차와 베타 한도.

기존 매뉴얼에는 `ensure_handbook_samples`의 일반 실행으로 빠진 장을 추가할 수 있습니다. `--refresh`는 기존 샘플 제목의 본문까지 바꾸므로,
새 장만 추가할 때는 사용하지 않습니다. 공개 핸드북 반영 시에는 대상 장의 중복·권한·백업과 검색 색인 반영을 함께 확인하세요.

## 6. 매뉴얼 질문 검색

핸드북 검색 창은 `/api/v1/docs/ask?q=질문`으로 문단을 찾습니다. 검색은 서버 안에서 실행되므로 Vercel 사이트에서도 외부 API 키나
추가 데이터베이스가 필요하지 않습니다. 첫 요청은 매뉴얼 문단 색인을 만들 수 있고, 따뜻한 인스턴스는 메모리 색인을 재사용합니다.
매뉴얼 글을 저장하거나 삭제하면 다음 검색부터 색인을 갱신합니다.

Vercel은 파일 쓰기와 함수 번들 크기를 아끼기 위해 기본 2-gram 토크나이저를 씁니다. 로컬에서 한국어 형태소 검색이 꼭 필요하고
서버 용량이 충분한 경우에만 `requirements-docs-morphology.txt`의 Kiwi를 추가하세요. Python 3.11에서 측정한 설치는 Python 패키지와
모델을 합쳐 약 213 MB였고 첫 분석기 로드에 약 2.7초가 걸렸습니다. 이 선택 패키지는 Vercel에 설치하지 않습니다.

로컬 Ollama 답변은 선택 기능입니다. Django 서버에 `G5_DOCS_LLM_BASE_URL`, `G5_DOCS_LLM_MODEL`을 설정하고 필요하면
`G5_DOCS_LLM_TIMEOUT`(초, 기본 20)을 지정하면 켜집니다. 브라우저가 모델 주소를 바꿀 수 없고, 답변 요청에는 요청자가 읽을 수
있는 검색 문단만 포함됩니다. 주소가 비어 있으면 문장 답변 기능은 꺼지고 문단 검색만 동작합니다. 이 데모 프로젝트에는 해당 값을
등록하지 마세요.

질문 검색 품질과 따뜻한 요청 시간을 샘플 매뉴얼로 확인할 때는 격리 DB에 샘플을 준비한 뒤 다음을 실행합니다.

```bash
python manage.py ensure_handbook_samples
python manage.py evaluate_handbook_search
```

평가 명령은 27개 한국어 질문(그중 9개는 장 제목 단어를 쓰지 않은 바꿔 말한 질문)의 hit@1/hit@3을 표로 출력하고
hit@3 80% 미만이면 실패합니다.

### 이미 배포한 샘플 글 고치기

`ensure_handbook_samples`를 다시 실행하면 빠진 책·장만 추가합니다. 기존 장의 본문, 책 이름·순서·접근 권한, 선택한
매뉴얼 그룹(`cf_docs_group`)은 그대로 둡니다. 샘플 문구의 오류(예: 설치 명령의 Python 버전)를 이미 배포한 DB에도
반영하려면 `--refresh`를 붙입니다. 샘플 장 제목을 가진 글의 본문을 현재 샘플 내용으로 다시 쓰므로, 그런 장을 직접
고쳐 썼다면 그 내용은 덮어써집니다. 제목이 샘플과 다른 장은 건드리지 않습니다.

```bash
python manage.py ensure_handbook_samples --refresh
```

## 통합 검색과 검색 운영 가이드

게시글·상품·내용관리 문서·매뉴얼을 함께 찾는 `/search`는 위의 매뉴얼 질문 검색과 별도 기능입니다. 처음 적용할 때는 해당 사이트 DB에 검색 마이그레이션과 전체 재색인이 필요합니다. 상세 절차는 [통합 검색 운영 안내](unified-search.md)를 따릅니다.

```bash
python manage.py migrate
python manage.py ensure_handbook_samples
python manage.py rebuild_search_index
```

`ensure_handbook_samples`는 **「검색 운영 · 통합 검색 가이드」** 책(`hb_search`)과 10개 장을 추가합니다. 사용법, 설치, 호스팅별 적용, 한국어 검색, 열람 권한, 순위·클릭 기록, API 연결, 문제 해결과 품질 점검을 설명합니다. 새 책을 추가할 때 `--refresh`를 붙이지 않습니다. 소스 파일만 배포하면 DB에 새 책이 생성되지 않으므로 위 명령을 해당 핸드북 DB에서 실행해야 합니다.

## 쇼핑몰 알림·반품·배송조회·정기구독 안내

`ensure_handbook_samples`는 **「쇼핑몰 운영 · 알림·반품·배송조회·정기구독」** 책(`hb_commerce`)과 9개 장을 추가합니다.
샘플 원본은 `gnu_jango/config/handbook_commerce_content.py`입니다.

- **먼저 읽기**: 새 기능의 기본값과 켜는 곳, 새 관리자 메뉴, 고객 화면 변화, 역할 프리셋 권한.
- **고객 알림**: 가격 인하·재입고 알림, 장바구니 알림 메일(정보통신망법 제50조 규칙, 발송 시간, Vercel 크론 주의).
- **주문 이후**: 반품·교환 신청 처리(주문 화면에서 직접 처리하면 신청이 자동으로 닫히는 것 포함), Delivery Tracker 배송조회.
- **정기구독**: 토스페이먼츠 자동결제 켜는 순서, 결제 회차·실패·확인 필요 처리.
- **개발·운영용**: 예약 작업(`send_shop_alerts` · `track_shipments` · `charge_shop_subscriptions`), 마이그레이션
  `shop.0039`~`0042` · `users.0016`, 배포 순서, 주문 목록 쿼리 수와 Django 7 대비.

기존 책의 「장바구니와 주문 흐름」「배송과 주문 상태 관리」「결제 설정과 테스트」「회원가입과 로그인」 장 끝에는 이 책으로 가는
‘함께 보기’ 링크를 한 번만 덧붙이고 본문은 그대로 둡니다. 이미 배포한 핸드북 DB에 반영하려면 그 DB에서 다음을 실행합니다
(`--refresh`는 붙이지 않습니다).

```bash
python manage.py ensure_handbook_samples
python manage.py rebuild_search_index
```

## 주의

- 두 프로젝트가 같은 `main` 을 보므로 push 한 번에 **둘 다** 배포됩니다. 한쪽만 배포하려면 프로젝트의 Ignored Build Step 을 쓰세요.
- 테마 출력은 저장소에 커밋된 파일 그대로 올라갑니다(Vercel이 `nextjs/` 를 빌드하지 않습니다). 테마를 다시 빌드했다면
  `templates/theme/<이름>` 과 `templates/theme_static/<이름>` 을 함께 커밋해야 합니다.
  `core/test_theme_static_complete.py` 가 첫 화면의 CSS · JS가 모두 있고 git이 무시하지 않는지 검사합니다.
- Vercel Hobby 는 비상업 용도입니다.
