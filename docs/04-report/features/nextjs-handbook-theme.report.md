# Next.js 매뉴얼(handbook) 테마 보고서

- 날짜: 2026-10-14
- 기준: `http://127.0.0.24/` (`C:\xampp824\www\gnuboard5_3\nextjs\themes\handbook`, 읽기 전용)
- 계획: `docs/01-plan/features/nextjs-handbook-theme.plan.md`

## 결과

`nextjs_default` 옆에 **두 번째 테마 handbook** 을 추가했다. 관리자 › 테마 설정에서 **Handbook (매뉴얼)** 을 고르면 바뀐다.
게시판 그룹 하나가 매뉴얼, 게시판이 책, 분류가 부, 글이 장이 된다.

화면(읽는 화면 전체): 상단 바와 문서 검색(Ctrl K), 책의 부·장 사이드바(모바일 서랍), 첫 화면(책 카드 · 최근 추가한 장),
책 목록, 장 보기(`04 / 7장`, 이전/다음 장, 페이지 목차), 다크 모드. 관리자 설정 편집기와 쇼핑몰 홈은 범위에서 뺐다.

## 단계

| 단계 | 내용 | 커밋 |
|---|---|---|
| 선행 | Next.js 15.5 → 16.3.8, React 19.2.7, ESLint flat config, `proxy.ts`, Turbopack 루트 | `445892417` |
| A | 테마 슬롯 구조(`themes/<이름>`, `@g5-theme/*` 별칭, 슬롯 · 기능 스위치), 빌드 · 동기화 스크립트의 테마 이름 일반화 | `c95842bd1` |
| B | Django 가 활성 테마(`cf_theme`)의 export 를 서빙, `/_next/static` 을 설치된 export 전체에서 탐색, 관리자 테마 선택에 표시 | `22b4ca778` |
| C | `cf_docs_group` 설정, 샘플 매뉴얼 명령 `ensure_handbook_samples` | `3495ba8d0` |
| D | 읽는 화면 이식, 테마 설정 전달(런타임 설정 · `theme_settings`), 목록 행 스타일 | `9f781f58e` |
| E | 두 테마 결과물 · 문서 · 확인 | 이 브랜치의 마지막 커밋 |

## 확인

| 항목 | 결과 |
|---|---|
| 기본 테마 CSS(5개 파일) | 변경 전 빌드와 **내용 지문 동일**(`7cde4299f0`) |
| handbook 빌드 | `data-g5-theme-source="handbook"`, 빌드 ID `g5-handbook-static` |
| `typecheck` · `lint` · `check:runtime-config` · `check:static-export-guards` | 통과 |
| 테마 스펙(`tests/handbook-docs.spec.ts`) | 12개 통과 |
| Django 테스트 | 전체 2104개 통과(skip 6), 그중 이 작업의 테마 테스트 27개 |
| handbook 화면 36개(12경로 × 390/768/1440) | 가로 넘침 없음. 오류는 없는 게시판 · 글을 연 두 경로의 404 뿐 |
| 기본 테마 50개 화면(8097) | 이전 확인과 같은 예상 오류만(후기 외부 이미지, 개인결제 401, 404 화면). worktree 에 업로드 미디어가 없어 회원 이미지 404 가 추가로 보임 |
| 상호작용 | 검색(Ctrl K → 장 찾기), 다크 모드, 이전/다음 장 이동, 홈 → 장 링크, 모바일 서랍 열기/닫기 |

격리 DB 사본(`handbook-qa.sqlite3`, `default-qa.sqlite3`)에 샘플 매뉴얼을 만들어 확인했다. 운영 DB 와 8081 은 건드리지 않았다.
캡처: `.tmp-nextjs-runtime/handbook/` (기준 `*-1440.png`, 우리 `ours/`, 전체 훑기 `hb-sweep/`, `default-sweep/`).

## 기준과 다른 점

- 상단 메뉴(시작하기 · 개발·배포 …)는 관리자 메뉴 설정을 따르는 것이 이 테마의 설계다. 확인용 DB 에는 사이트 메뉴가 없어 비어 보인다.
- 샘플 매뉴얼은 책 4권 · 장 21개의 예시 글이다. 기준 사이트의 실제 글(약 150장)은 가져오지 않았다.
- 기준의 관리자 편집기(장 순서 · 사이드바 표시 · 사이트 문구)는 없다. 책 순서는 게시판 출력 순서, 장 순서는 글 번호, 문구는 `theme.config.ts` 다.
- 쇼핑몰 화면은 핸드북 틀 안에 들어가지만 이 테마의 범위가 아니다(스타일 미조정).

## 남은 일

- Vercel 데모를 handbook 으로 바꾸려면 데모 DB 의 `cf_theme` 을 바꿔야 한다(데모 DB 쓰기라 직접 해야 한다).
- 기본 테마 결과물은 Next 16 빌드로 갱신했다. 파일 수가 454 → 623개로 늘었다(Next 16 이 화면 조각 `.txt` 를 더 내보낸다).
- 실제 매뉴얼 데이터가 생기면 `fields=toc`(가벼운 글 목록)가 필요한지 장 수백 개 규모에서 다시 본다.
