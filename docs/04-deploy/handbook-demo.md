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
python manage.py ensure_handbook_samples      # 샘플 매뉴얼: 책 4권 · 장 21개 (--remove 로 되돌림)
python manage.py check_deploy_profile --profile vercel
```

실제 매뉴얼은 관리자에서 게시판 그룹 `manual`(또는 `G5_DEFAULT_DOCS_GROUP` 에 적은 그룹)에 만들면 됩니다.
게시판 하나가 책, 게시판 분류가 부, 글이 장입니다. 샘플은 그룹 `manual` · 게시판 `hb_*` 만 건드립니다.

## 4. 확인

- 첫 화면 HTML에 `data-g5-theme-source="handbook"` 가 있고, 개발자 도구 콘솔에 404 · 스타일 거부 오류가 없어야 합니다.
- `/api/v1/settings` 의 `theme_settings.docs.group` 이 `manual` 이어야 합니다.
- 응답 헤더 `X-Vercel-Id` 의 두 번째 값이 `icn1` 이어야 합니다.

## 주의

- 두 프로젝트가 같은 `main` 을 보므로 push 한 번에 **둘 다** 배포됩니다. 한쪽만 배포하려면 프로젝트의 Ignored Build Step 을 쓰세요.
- 테마 출력은 저장소에 커밋된 파일 그대로 올라갑니다(Vercel이 `nextjs/` 를 빌드하지 않습니다). 테마를 다시 빌드했다면
  `templates/theme/<이름>` 과 `templates/theme_static/<이름>` 을 함께 커밋해야 합니다.
  `core/test_theme_static_complete.py` 가 첫 화면의 CSS · JS가 모두 있고 git이 무시하지 않는지 검사합니다.
- Vercel Hobby 는 비상업 용도입니다.
