# gnuboard5-grade-completion - Plan Document

> Version: 1.0.0 | Date: 2026-06-16 | Status: Draft
> Level: Starter

> 2026-10-07 경로 갱신: 프런트엔드 소스는 현재 `nextjs/`입니다. 이 문서의 테마 경로 `nextjs25`는 기존 산출물을 뜻합니다. 새 기본 테마 전환은 [Next.js Default 플랜](nextjs-default-theme.plan.md)을 따릅니다.

---

## 1. Overview

### 1.1 Purpose
현재 Django 기반 `gnu_jango` 프로젝트를 `C:\xampp824\www\gnuboard5_3` 프로젝트의 API, Next.js 프론트엔드, 운영 경험을 참고하여 그누보드5 수준의 완성도를 갖춘 게시판/회원/관리자 플랫폼으로 완성한다.

### 1.2 Background
참고 프로젝트는 PHP 기반 그누보드5 구조와 별도 `api`, `nextjs` 프로젝트를 포함한다. 대상 프로젝트는 이미 Django 앱, DRF 일부 API, SQLite 개발 DB, Django admin 템플릿 오버라이드, 기존 테마/스킨 구조를 가지고 있으므로 PHP 코드를 단순 복사하지 않고 Django/DRF/Next.js 구조에 맞게 재구성한다.

## 2. Goals

### 2.1 Primary Goals
- [ ] `C:\xampp824\www\gnuboard5_3\api`의 주요 기능을 Django/DRF `/api/v1/...` 엔드포인트로 재설계한다.
- [ ] `C:\xampp824\www\gnuboard5_3\nextjs`를 이 프로젝트의 `nextjs` 앱으로 가져와 Vercel 배포가 가능하게 만든다.
- [ ] Next.js 정적/템플릿 산출물이 `gnu_jango/templates/theme/nextjs25`와 `gnu_jango/templates/theme_static/nextjs25`에서 실행될 수 있게 한다.
- [ ] `/admin/`을 그누보드5 관리자급 반응형 운영 화면으로 커스터마이징한다.
- [ ] 게시판, 회원, 댓글, 파일첨부, 검색, 알림, 설정, 관리자 메뉴가 실제 운영 가능한 품질로 동작하게 한다.

### 2.2 Quality Target
이 작업의 최종 기준은 "작동하는 데모"가 아니라 "그누보드5만큼 운영에 투입 가능한 완성도"다. 기능 수, 권한 처리, 파일 업로드, 관리자 편의성, 반응형 UI, 오류 처리, 보안 기본값, 배포 가능성까지 모두 완료 기준에 포함한다.

### 2.3 Gnuboard5 Completeness Baseline
`C:\xampp824\www\gnuboard5_3` 프로젝트를 기능/운영 완성도의 기준선으로 삼는다. 목표는 일부 화면만 동작하는 데모나 단순 테마 이식이 아니라, 게시판/회원/관리자 흐름, 권한 처리, 파일 업로드, 반응형 관리 화면, 배포 준비성까지 그누보드5에 준하는 수준으로 `gnu_jango`를 완성하는 것이다.

완료 판정 전에는 Django API, Next.js 테마, 템플릿 출력물, 관리자 커스터마이징을 기준 프로젝트와 비교하여 누락된 운영 기능이 없는지 확인해야 한다.

### 2.4 Mandatory Completion Standard
`C:\xampp824\www\gnuboard5_3` is the minimum functional and operational reference. The target project must not stop at copying the API and Next.js folders; it must raise `gnu_jango` to a Gnuboard5-grade completion level.

Completion means board, member, admin, content, file, shop/order, permission, migration, deployment, and responsive-management workflows should be usable at a level comparable to Gnuboard5. Any area that cannot reach that level in this phase must be explicitly listed as a remaining gap with verification evidence and follow-up work.

### 2.5 Non-Goals
- PHP 런타임을 Django 프로젝트 안에서 그대로 실행하지 않는다.
- 그누보드5 PHP 내부 구조를 Django 모델/뷰에 무비판적으로 복제하지 않는다.
- Vercel 배포용 Next.js 앱과 Django 서버를 하나의 프로세스로 억지 통합하지 않는다.

## 3. Scope

### 3.1 In Scope
- API v1 호환 라우팅, 공통 응답 포맷, 상태 점검 API
- 게시판/게시글/댓글/회원/메뉴/설정 API 확장
- 업로드, 첨부파일, 검색, 알림, 스크랩, 메모 기능의 단계적 구현
- 쇼핑몰 API는 참고 프로젝트 기능 목록을 기준으로 설계 문서화 후 우선순위 적용
- Next.js 프로젝트 복사, 환경변수 정리, Vercel 설정 검증
- Django theme 출력 경로와 static 경로 동기화 스크립트
- Django admin 반응형 레이아웃, 메뉴, 대시보드, 리스트/폼 화면 개선
- 로컬 실행, 빌드, 핵심 URL smoke test

### 3.2 Out of Scope
- 실제 운영 서버 DNS, 실결제 PG 계약, 실명 인증 상용 계정 발급
- 기존 사용자 데이터의 완전한 마이그레이션 자동화
- 모든 PHP 플러그인의 1:1 기능 복제

## 4. Success Criteria

- [ ] `python manage.py check`가 통과한다.
- [ ] `http://127.0.0.1:8000/api/v1/status`가 정상 응답한다.
- [ ] `/api/v1/config`, `/api/v1/menus`, `/api/v1/boards`, `/api/v1/posts`가 Next.js에서 사용할 수 있는 JSON을 반환한다.
- [ ] `nextjs`에서 `npm run build`가 통과한다.
- [ ] `nextjs/vercel.json`과 환경변수 예제가 Vercel 배포 기준으로 정리되어 있다.
- [ ] Django theme 산출물이 `gnu_jango/templates/theme/nextjs25`에 생성 또는 동기화된다.
- [ ] `/admin/`이 데스크톱과 모바일에서 반응형으로 사용할 수 있다.
- [ ] 관리자 대시보드가 회원/게시판/게시글/댓글/운영 상태를 보여준다.
- [ ] 기존 Django admin CRUD 기능이 손상되지 않는다.
- [ ] 그누보드5 핵심 기능 대비 누락 항목이 문서화되어 있고, 구현된 항목은 검증 증거가 있다.

- [ ] `C:\xampp824\www\gnuboard5_3` compared checklist confirms Gnuboard5-grade completeness for board/member/admin/content/file/shop/order/permission/migration/deployment/responsive-management flows, or documents remaining gaps explicitly.

## 5. Schedule

| Phase | Target Date | Status |
|-------|-------------|--------|
| Plan | 2026-06-16 | In Progress |
| Design | TBD | Pending |
| Implementation | TBD | Pending |
| Review | TBD | Pending |
| Report | TBD | Pending |

## 6. Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| PHP API 기능 범위가 넓어 한 번에 완성하기 어려움 | High | High | v1 호환 기반부터 만들고 기능군별로 단계 구현 |
| Next.js가 PHP API 응답에 강하게 결합되어 있음 | High | Medium | 응답 호환 어댑터와 환경변수 기반 API client 유지 |
| Django admin 템플릿 오버라이드가 기본 기능을 깨뜨릴 수 있음 | High | Medium | `admin/base_site.html`, CSS/JS 중심으로 점진 개선 |
| Vercel과 Django theme 실행 방식이 다름 | Medium | High | Vercel 앱과 Django theme sync를 별도 스크립트로 분리 |
| 기존 데이터 모델이 그누보드5 전체 기능을 담지 못함 | High | Medium | 설계 단계에서 모델 gap 분석 후 마이그레이션 추가 |

## 7. References

- Source reference: `C:\xampp824\www\gnuboard5_3`
- Target Django project: `E:\gnu-jango\gnu_jango`
- PHP API reference: `C:\xampp824\www\gnuboard5_3\api`
- Next.js reference: `C:\xampp824\www\gnuboard5_3\nextjs`
- Django API target: `gnu_jango/api`
- Django theme target: `gnu_jango/templates/theme/nextjs25`
- Django admin target: `gnu_jango/templates/admin`
