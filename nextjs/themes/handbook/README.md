# Handbook 테마

게시판을 **매뉴얼(문서) 사이트**로 보여 주는 Next.js 테마입니다. 기준 프로젝트의 handbook 테마에서 읽는 화면만
옮겼고(관리자 설정 편집기와 쇼핑몰 홈은 제외), Django 데이터와 API 위에서 동작합니다.

| 매뉴얼 | 그누보드 데이터 |
| --- | --- |
| 매뉴얼(책 모음) | 게시판 그룹 하나 — 관리자 › 환경설정의 **매뉴얼 게시판 그룹**(`cf_docs_group`) |
| 책 | 그 그룹의 게시판 하나. 출력 순서(`bo_order`)가 책 순서 |
| 부 | 게시판 분류(`bo_category_list`)의 순서 |
| 장 | 그 게시판의 글. `wr_num`이 작은 글이 앞 장 |
| 책 이름 · 안내 문구 | 게시판 제목이 `안내 · 이름` 꼴이면 앞이 작은 안내, 뒤가 책 이름 |

상단에는 매뉴얼 책장 메뉴가 자동으로 생겨 모든 책에 바로 갈 수 있고, 그 밖의 사이트 메뉴는 관리자 메뉴 설정을 따릅니다.

## 화면

- 상단 바: 브랜드, 매뉴얼 책 바로가기, 문서 검색(Ctrl K, 장·부·책 제목 검색과 질문형 문단 검색), 모든 매뉴얼, 로그인, 다크 모드
- 왼쪽: 지금 읽는 책의 부·장 목차(책 선택기), 모바일에서는 서랍
- 첫 화면: 목적별 시작 경로, 책 카드, 최근 추가한 장
- 글 보기: `04 / 24장`, 이전/다음 장, 오른쪽 "이 문서의 목차"(본문의 h2·h3)
- 글 아래에 게시판 목록을 붙이지 않습니다(`features.listUnderPostView: false`)

## 쓰는 법

```bash
# 격리 DB 에서 샘플 매뉴얼(책 7권, 장 37개)을 만들고 그룹을 지정
python manage.py ensure_handbook_samples
python manage.py ensure_handbook_samples --remove     # 샘플만 지운다
python manage.py evaluate_handbook_search             # 샘플 질문 18개 hit@1/hit@3 와 검색 시간 확인

# 빌드 → templates/theme/handbook, theme_static/handbook 로 동기화
cd nextjs && npm run build:theme:handbook && npm run check:theme-sync:handbook
```

관리자 › 테마 설정에서 **Handbook (매뉴얼)** 을 고르면 바뀝니다(`cf_theme=handbook`). 실제 매뉴얼은 관리자에서
게시판 그룹을 만들고 `cf_docs_group` 에 그 그룹 ID 를 적습니다.

## 질문으로 찾기

배포된 데모에서 샘플 책을 추가하려면 관리자 › **샘플 데이터**에서 **매뉴얼 콘텐츠 추가·보강**을 누릅니다.
현재 샘플은 책 7권과 장 37개이며, 이미 작성된 매뉴얼 본문은 덮어쓰지 않고 빠진 샘플 책과 장만 추가합니다.

문서 검색 창에 두 글자 이상 질문을 입력하면 매뉴얼 본문을 문단 단위로 찾습니다. 결과에는 책·부·장·절, 질문 단어를
강조한 문단, 해당 절로 가는 링크가 표시됩니다. 기본 검색은 Django 안에서만 처리하며 외부 검색 API나 유료 API를 쓰지 않습니다.

Vercel 같은 서버리스 배포에서는 Python 기본 2-gram 토크나이저와 BM25를 사용합니다. 형태소 분석을 더 선호하고 서버 용량이
충분한 VPS에서는 `pip install -r requirements.txt -r requirements-docs-morphology.txt`로 Kiwi를 추가할 수 있습니다.
Kiwi가 설치되어 있지 않거나 로드에 실패하면 검색은 자동으로 2-gram 방식으로 바뀝니다.

선택 사항으로 로컬 Ollama(OpenAI 호환 API)를 연결하면, 먼저 찾은 문단만 근거로 한국어 문장 답변을 덧붙입니다.
`G5_DOCS_LLM_BASE_URL`, `G5_DOCS_LLM_MODEL`, `G5_DOCS_LLM_TIMEOUT`을 Django 서버의 환경 변수로 설정해야 켜집니다.
주소는 브라우저 요청에서 전달받지 않으며 기본값은 꺼짐입니다. Vercel 데모에는 이 설정을 넣지 않습니다.

## 값이 화면에 오는 길

정적 빌드는 한 번 만들어 모든 Django(로컬 · Vercel)가 함께 쓰므로 설치마다 다른 값을 빌드에 넣지 않습니다.
Django 가 활성 테마가 handbook 일 때만 같은 값을 두 길로 내려 줍니다 — 페이지의 런타임 설정
(`window.__G5_NEXTJS25_CONFIG__.themeSettings`)과 `GET /api/v1/settings` 의 `theme_settings`
(`gnu_jango/config/theme_settings.py`). 책 목록과 장 목차는 브라우저가 게시판 API 에서 받습니다.

## 파일

| 파일 | 역할 |
| --- | --- |
| `theme.config.ts` · `components.tsx` | 문구와 슬롯 연결(`LayoutShell`, `HomePage`, `BoardViewHeader`) |
| `layout-shell(.server).tsx` | 상단 바 · 사이드바 · 바닥글 틀 |
| `docs-nav.ts` · `book-nav.ts` · `use-docs-chapters.ts` | 게시판 → 책 · 부 · 장 변환, 주소 → 책 · 장 찾기 |
| `home(-content).tsx` | 첫 화면 |
| `board-view-header.tsx` · `chapter-pager.tsx` · `page-toc.tsx` | 글 보기 머리, 이전/다음 장, 페이지 목차 |
| `doc-search.tsx` · `book-selector.tsx` · `drawer-menu.tsx` · `main-nav.tsx` | 검색, 책 선택, 모바일 서랍, 상단 메뉴 |
| `theme.*.css` | 토큰 · 틀 · 목차 · 검색 · 첫 화면 · 목록 행 · 다크 (`.doc-root` 범위) |

## 디자인 메모

- 팔레트는 indigo-on-slate. 토큰은 `theme.tokens.css`, 다크는 `theme.dark.css`(`data-handbook-theme`).
- 앱의 글 줄(`.solune-blr-*`)은 기본 테마 범위로만 꾸며져 있어 `theme.list.css` 가 문서 모양으로 다시 꾸밉니다.
- 모션 감소 설정을 따릅니다.
