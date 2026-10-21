# Vercel Preview를 운영 DB와 분리하기

Preview는 PR 변경을 확인하는 임시 사이트다. 운영용 `DATABASE_URL`, S3 키, PG 키를 Preview에 복사하지 않는다. 같은 Supabase 프로젝트를 쓰더라도 전용 로그인 역할과 스키마가 필요하다. 두 Vercel 프로젝트는 각각 자기 Supabase 프로젝트의 Preview 스키마를 사용한다.

## 계정 준비

DB 관리자가 전용 `g5_preview*` 역할을 `LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`로 만들고, 같은 접두사의 스키마에만 `USAGE, CREATE`를 부여한다. 스키마에 대한 PUBLIC 권한은 제거한다. 역할의 해당 DB 기본 `search_path`를 전용 스키마와 `pg_catalog`로 설정한다. 비밀번호는 저장소 밖 환경 파일에만 둔다.

`NOINHERIT`만으로 PUBLIC 권한은 없어지지 않는다. 실제 역할로 다음을 확인해야 한다.

- `current_user`, `current_schema()`가 지정한 Preview 역할·스키마인지
- 운영 public 테이블·시퀀스의 읽기·쓰기 권한이 없는지
- 전용 스키마 밖에 CREATE 권한이 없는지
- 접근 가능한 외부 스키마에 위험한 SECURITY DEFINER 함수나 pg_net 권한이 없는지
- 다른 역할의 구성원이 아닌지, `BYPASSRLS`가 없는지

문제가 있으면 운영 PUBLIC 권한을 일괄 변경하지 않는다. 별도 Supabase 프로젝트를 사용하는 방법을 검토한다. 공유 프로젝트는 CPU·디스크·연결 수까지 분리하지는 않으며, PR마다 별도 DB를 만드는 구조도 아니다. 신뢰하는 브랜치만 비밀값이 있는 Preview로 배포한다. 서로 다른 PR의 마이그레이션이 충돌하면 같은 Preview DB를 동시에 사용하지 않는다.

Supabase의 [연결 안내](https://supabase.com/docs/guides/database/connecting-to-postgres)와 [사용자 역할의 PUBLIC 권한 주의사항](https://supabase.com/docs/guides/troubleshooting/custom-role-inherits-privileges-that-were-not-explicitly-granted-ddaa1c)을 참고한다. 사용자 지정 역할은 풀러 주소의 사용자 이름에 프로젝트 참조를 붙인다. 이 구성은 역할별 기본 search_path를 유지하는 Session pooler(5432)를 사용한다.

## Vercel Preview 변수

Production과 별도로 **Preview 환경에만** 등록한다.

```dotenv
ENVIRONMENT=Preview
DEBUG=False
PREVIEW_DB_ROLE=g5_preview
PREVIEW_DB_SCHEMA=g5_preview
DATABASE_URL=<Preview 역할의 Session pooler URL>
SECRET_KEY=<Preview 전용 무작위 값>
MEDIA_STORAGE=local
CACHE_URL=db://
DB_CONN_MAX_AGE=0
DB_DISABLE_SERVER_SIDE_CURSORS=true
DB_SSL_REQUIRE=true
G5_DEFAULT_THEME=nextjs_default
```

핸드북은 `G5_DEFAULT_THEME=handbook`, `G5_DEFAULT_DOCS_GROUP=manual`로 설정한다. `ALLOWED_HOSTS`는 CLI 관리 시 명시하고 Vercel에서는 해당 배포 호스트가 자동 추가된다. `example.preview_db` 백엔드는 연결 직후 실제 역할·스키마를 대조하고 다르면 연결을 거부한다. 마이그레이션도 반드시 이 프로필과 전용 계정으로 실행한다.

```bash
python manage.py migrate
python manage.py createcachetable
python manage.py ensure_demo_samples --apply
python manage.py rebuild_search_index --batch-size 25
```

핸드북에서는 `ensure_demo_samples` 대신 `ensure_handbook_samples --stable-dates`를 사용한다. 운영 데이터·회원·주문을 복사하지 않는다. Preview 웹 빌드는 마이그레이션을 자동 실행하지 않는다. 새 PR에 마이그레이션이 있으면 관리 환경에서 먼저 적용한다.

## 제한

- DEBUG를 강제로 끄고 검색 엔진에는 noindex 헤더를 보낸다.
- 메일은 메모리에만 보관하며 외부 SMTP로 보내지 않는다.
- 결제·웹훅·소셜 로그인·SMS·cron 경로는 차단한다. 운영 통합 검증은 별도의 승인된 테스트 환경에서 진행한다.
- 파일은 `/tmp`에 임시로만 저장한다. 인스턴스가 바뀌면 사라지고 인스턴스 간 공유되지 않는다. Preview는 영속 업로드 검증용이 아니다.
- Production 변수와 기존 `.vercel/project.json` 연결을 변경하지 않는다. CLI는 별도 폴더에 프로젝트를 연결한다.
