# Next.js 매뉴얼(handbook) 테마 이식 계획

- 작성: 2026-10-14
- 기준: `C:\xampp824\www\gnuboard5_3\nextjs\themes\handbook` (`http://127.0.0.24/`, 읽기 전용)
- 결정(사용자): ① `nextjs_default` 옆에 **별도 테마로 추가**(관리자 테마 선택으로 전환) ② **읽는 화면 전체** 이식 — 상단바 · 왼쪽 책 사이드바(모바일 서랍) · 홈(책 카드 · 최근 장) · 책 목차 · 장 이동 · 페이지 TOC · 문서 검색 · 다크모드 · 글 보기 머리. 관리자 설정 편집기와 쇼핑몰 홈 슬롯은 제외 ③ 격리 DB 사본에 **샘플 매뉴얼**(책 3~4권, 장 약 20개)을 만들어 확인

## 확인된 사실

- 우리 앱은 Next **15.5** (기준 16.3). `next build`는 webpack이므로 테마 별칭은 webpack과 `turbopack.resolveAlias` 둘 다 필요하다.
- 우리 앱에는 테마 슬롯 구조와 `nextjs/themes/` 폴더가 없다. 레이아웃은 `src/app/layout.tsx`에 고정돼 있다.
- Django는 `nextjs_default` 이름을 여러 곳에 직접 쓴다(`core/views.py`의 정적 경로 · 공개 파일 · 색인 뷰, `config/theme_admin.py`).
- 기준 문서 검색은 브라우저에서 장·부·책 제목을 훑는다. 별도 검색 API는 필요 없다("통합 검색" 링크만 `/search?q=` 로 간다).
- 책 = 게시판 그룹의 게시판, 부 = `bo_category_list`, 장 = 게시글(`wr_num` 순). 우리 API에는 대부분 이미 있다(`board_list_response ?group=`, `_board_payload`, 글 목록 정렬).

## 단계 (각각 따로 커밋 가능)

| 단계 | 내용 | 확인 게이트 | 규모 |
|---|---|---|---|
| 0 기준선 | `build:theme` 두 번 돌려 `out/` 해시가 같은지(결정적 빌드) 확인, 기본 테마 화면 390/768/1440 캡처 | 해시 일치 | 0.5일 |
| A 슬롯 구조 | `themes/default/{components,theme.config}`, `src/lib/theme-types.ts` · `theme.ts`, `ThemeSlotsProvider`, tsconfig `@g5-theme/*`, `next.config.ts` 별칭, `app/layout.tsx` · `app/page.tsx` · 글 보기 머리를 슬롯 경유로. `scripts/build-next.mjs`는 선택 테마 폴더만 작업공간에 복사(Tailwind가 다른 테마 클래스를 줍지 않게). `with-theme`/`theme-pair` 스크립트, `build:theme:handbook` | typecheck · lint · 가드 · `build:theme` · `check:theme-sync`, 기본 테마 CSS 바이트 동일 | 1~1.5일 |
| B Django 다중 테마 | `_active_nextjs_theme()`, 색인 뷰 · 매니페스트 · 공개 파일 · 대체 이미지 일반화, `/_themes/<theme>/_next/static/` 경로(불변 캐시), `ASSET_PATH_PREFIXES`에 `/_themes/`, `THEME_PRESENTATION["handbook"]`, 테스트 | Django 테스트(core · config) | 1~1.5일 |
| C API · 샘플 | `fields=toc` 가벼운 글 목록, `theme_settings`(매뉴얼 게시판 그룹) 설정 키, 샘플 매뉴얼 생성 명령 `ensure_handbook_samples`(장은 마지막→처음 순으로 만들어 `wr_num` 순서를 맞춘다, `--remove` 지원) | API 테스트 | 1일 |
| D 읽는 화면 이식 | `themes/handbook/*` 복사(설정 편집기 · 쇼핑 홈 · editor/shop CSS 제외), `canonicalDocPath`가 `/bbs/` 도 벗기게, 다크모드는 next-themes, 쇼핑 경로 셸 처리, `theme.pages.css`를 우리 마크업(`.board-view-card`, `.solune-view-*`)에 맞춤 | typecheck · lint · `build:theme:handbook` · sync, `out/index.html` 에 `data-g5-theme-source="handbook"` 와 `/_themes/handbook/_next/`, 기본 테마 재빌드가 기준선과 같음 | 3~4일 |
| E 반영 · QA | 격리 DB 사본에서 `cf_theme=handbook` + 샘플, 127.0.0.24 와 390/768/1440 비교(홈 · 책 · 장 · 검색 Ctrl+K · 다크 · 모바일 서랍 포커스), 기본 테마로 되돌려 회귀 확인 | 브라우저 비교 스크립트 | 1.5일 |
| F 선택 | 서비스워커가 `/_themes/*` 도 캐시, `package:theme:handbook` | | 0.5~1일 |

합계 약 9~11일.

## 위험

1. 출력 폴더(`templates/theme/handbook`)를 **B단계 전에** 커밋하면 관리자가 선택할 수 있게 되는데, 색인 뷰가 페이지 설정 없이 원본 HTML을 내보낸다 → B를 먼저.
2. 동기화 스크립트가 빌드마다 `.g5-static-compat.json`의 generation을 올린다 → 바이트 동일 검사에서 제외.
3. 우리 Next 15.5에서 webpack 별칭이 tsconfig `paths`보다 우선하는지는 미확인(기준은 16 의존) → D 게이트가 조용한 기본 테마 대체를 잡는다.
4. 작업공간 필터가 없으면 handbook의 daisyUI/Tailwind 클래스가 기본 테마 CSS에 섞인다.
5. `check-runtime-config`가 `v1_views.py`의 `"theme": "nextjs_default"` 문구를 요구한다 → 상태 응답은 바꾸지 않는다.
6. 기준 CSS는 기준 마크업 기준이라 `theme.pages.css` · `theme.booknav.css` 다시 맞추는 작업이 크다.
7. Vercel: 함수 번들이 커진다(한도 미측정). `theme_static`이 STATICFILES_DIRS 에 있어 collectstatic이 두 번 모은다. 데모 전환은 데모 DB 쓰기라 사용자가 해야 한다.

## 미확인

빌드가 지금 결정적인지, Vercel 번들 크기, 기준 CSS의 클래스 불일치 정도, 개발 서버(Turbopack)에서의 별칭 동작.
