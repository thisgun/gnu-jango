# Vercel 사이트의 외부 Celery 작업자 배포

이 구성은 **기존 Vercel 웹과 Supabase DB·Storage를 유지하고**, 별도 Linux 서버에 Redis·일반 작업자·이미지 작업자·Beat만 실행할 때 사용합니다. 서버 주소·SSH 계정·적용할 사이트와 비밀 설정이 준비되어야 실제로 배포할 수 있습니다. 서버를 구매하거나 공개 데모 설정을 자동으로 변경하지 않습니다.

새로운 독립 사이트 전체를 만드는 경우에는 [기존 VPS 구성](background-jobs.md#3-vps에서-시작하기)을 사용하세요. 아래 파일은 기본 `docker-compose.yml`과 합치지 않는 **독립 Compose 파일**입니다. 웹 서버나 PostgreSQL 컨테이너가 포함되지 않습니다.

## 1. 먼저 준비하기

- Docker Engine과 Docker Compose 2.30 이상을 실행할 수 있는 Linux 서버.
- 웹에 배포할 코드와 동일한 커밋의 저장소. 첫 전환 전에 같은 코드로 웹도 준비합니다.
- 적용할 사이트 하나: `gnu-jango-demo` 또는 `gnu-jango-handbook`. 프로젝트·비밀 파일·Redis 볼륨·Beat 이력은 사이트마다 분리합니다.
- 해당 사이트의 `SECRET_KEY`, PostgreSQL 주소, S3 버킷·접근 키, 공유 캐시, 메일·SMS·PG 설정. 기존 웹 설정과 일치해야 합니다. 다른 사이트의 키를 섞지 않습니다.
- DB·미디어 백업과 새 `core.0015_backgroundjob` 마이그레이션 적용 여부 확인.

`deploy/env/background-worker.env.example`을 저장소 밖 `/srv/gnu-jango-secrets/demo-worker.env` 같은 경로에 복사해 편집하고 파일 권한을 `600`으로 제한합니다. 실제 값을 저장소나 채팅에 넣지 마세요. 이 파일은 `env_file`의 `raw` 형식으로 읽으므로 `KEY=value`를 쓰고 값에 따옴표나 `${OTHER_VAR}`를 추가하지 않습니다. `$`·`#`가 포함된 기존 비밀값도 그대로 전달합니다. Compose 2.30 이상이 필요한 이유는 [Docker의 raw env_file 지원](https://docs.docker.com/reference/compose-file/services/#env_file)입니다.

대상 DB는 **기존 사이트의 DB**입니다. 이 단계는 빈 DB를 만들거나 샘플 데이터를 추가하는 절차가 아닙니다. 웹이 S3 업로드를 쓰면 작업자도 같은 버킷·접두사·공개 URL을 사용해야 합니다. Vercel의 `/tmp` 또는 서버의 로컬 미디어 폴더는 서로 공유되지 않습니다.

### 공유 캐시와 브로커

`CACHE_URL`은 웹과 동일한 공유 캐시로 맞춥니다. `db://`를 쓰는 사이트라면 해당 DB에 캐시 테이블이 이미 있어야 합니다. 컨테이너 내부 Redis의 캐시로 임의 변경하면 웹과 작업자의 제한·캐시 무효화가 분리됩니다.

반면 이 구성의 `CELERY_BROKER_URL`과 결과 저장소는 `redis://redis:6379/0`을 사용할 수 있습니다. 새 모드의 웹 요청은 outbox를 DB에 기록하고, 이 서버의 Beat·작업자가 Redis에 UUID를 전달합니다. 이를 위해 Redis 포트를 인터넷에 공개할 필요가 없습니다. 사이트의 `SECRET_KEY`가 다르면 브로커 namespace도 달라지므로 웹·작업자·Beat의 키를 일치시키세요.

## 2. 서버에서 설정·이미지 준비

아래 예시는 **이미 해당 Linux 서버에 로그인하고 저장소 디렉터리로 이동한 상태**입니다. Windows 개발 PC에서 그대로 실행해 원격 배포되는 명령이 아닙니다.

```bash
export BACKGROUND_PROJECT=gnu-jango-demo-background
export BACKGROUND_ENV_FILE=/srv/gnu-jango-secrets/demo-worker.env
# 핸드북은 프로젝트명과 파일을 각각 handbook용으로 바꿉니다.

docker compose version
docker compose -f docker-compose.background.yml config --quiet
docker compose -f docker-compose.background.yml build worker media-worker beat
```

실제 키가 설정된 상태에서 `docker compose config`를 옵션 없이 출력하면 비밀값까지 표시될 수 있습니다. 구문 확인에는 `config --quiet`를 사용하세요. 일반 `.env`는 Compose 보간용이며 컨테이너에 자동 전달되지 않습니다. 이 독립 구성은 지정한 `BACKGROUND_ENV_FILE`을 컨테이너에 명시적으로 전달합니다. [Docker 환경 변수 전달 안내](https://docs.docker.com/compose/how-tos/environment-variables/set-environment-variables/)도 참고하세요.

기본 파일의 작업자 build는 일반 런타임 의존성을 사용합니다. 알림 설정에서 Channels가 필요한 별도 실시간 서비스를 켠 사이트라면 빌드 전에 `BACKGROUND_INSTALL_REALTIME=1`을 지정하세요. 이 파일 자체는 WebSocket 서버를 만들지 않습니다.

## 3. 읽기 전용 사전 점검

```bash
docker compose -f docker-compose.background.yml run --rm --no-deps worker true
```

컨테이너의 사전 점검은 PostgreSQL·S3 사용 여부, Django 호환 설정과 `migrate --check`를 확인합니다. 누락된 마이그레이션이 있으면 실패하며, 시작 과정에서 마이그레이션을 적용하지 않습니다. `RUN_MIGRATIONS=0`과 전용 entrypoint를 사용합니다. DB 접속·마이그레이션 조회는 수행하지만 메일·SMS·PG 요청은 보내지 않습니다. SMTP/S3 제공자 연결까지 검증하는 명령은 아닙니다.

캐시 테이블과 마이그레이션 적용은 별도 DB 배포 절차에서 백업 후 수행합니다. 자동으로 실패를 무시하거나 entrypoint를 제거해서 작업자를 시작하지 마세요.

## 4. 전환 순서

1. 웹에 같은 커밋을 준비하고 처음에는 기존 `BACKGROUND_JOBS_ENABLED=False`를 유지합니다.
2. DB 백업과 새 마이그레이션 적용을 완료합니다. 사전 점검이 통과해야 합니다.
3. 이 사이트를 처리하는 기존 system cron·Vercel Cron·알림 watch의 목록을 확인합니다. Beat 전환 시 중복되지 않도록 중단할 대상을 정합니다.
4. 먼저 일반·이미지 작업자를 시작합니다.

   ```bash
   docker compose -f docker-compose.background.yml up -d worker media-worker
   docker compose -f docker-compose.background.yml exec worker celery -A example inspect active_queues --timeout=5
   ```

   `general@...`이 `celery`, `maintenance`, `communications`, `payments`를, `media@...`가 `media`를 소비하는지 확인합니다. [Celery의 active_queues 점검](https://docs.celeryq.dev/en/stable/userguide/workers.html#inspecting-workers)으로 확인할 수 있습니다.

5. 기존 예약 실행을 중단하고 Beat를 **하나만** 시작합니다. 이때부터 정기 유지보수 작업이 실제 DB에 등록·실행됩니다.

   ```bash
   docker compose -f docker-compose.background.yml up -d beat
   docker compose -f docker-compose.background.yml ps
   ```

6. 웹의 `BACKGROUND_JOBS_ENABLED=True`, `CELERY_TASK_ALWAYS_EAGER=False`를 적용해 새 웹 배포를 만듭니다. 작업자에만 설정을 바꾸면 웹 요청은 계속 기존 동기 경로로 처리됩니다.
7. 운영자 소유 테스트 수신처·테스트 주문·테스트 이미지로 접수·실행을 확인합니다. `/admin/core/backgroundjob/`에서 `pending → running → succeeded`, 원문 제거와 실패 코드를 확인합니다. 실제 고객에게 임의 테스트 메일·SMS를 보내지 않습니다.

웹이 비동기 모드일 때 작업자가 멈추면 발송·이미지 처리가 대기합니다. 단순 HTTP 200이나 Flower 접속만으로 작업 처리가 정상이라고 판단하지 말고 DB 대기열과 실제 테스트 수신 결과를 확인하세요. 결제는 사업자 테스트키와 테스트 주문으로 입금 확인·중복 웹훅·만료·실패 후 수동 검토까지 확인합니다. 이 구성을 준비하는 것만으로 실사업자 검증이 완료되지는 않습니다.

## 5. Flower와 로그

비밀 환경 파일의 `FLOWER_BASIC_AUTH`를 설정한 뒤 다음을 실행합니다. 핸드북도 같은 서버에서 실행한다면 호스트의 `FLOWER_PORT`를 다른 값으로 지정하세요.

```bash
docker compose -f docker-compose.background.yml --profile monitoring up -d --build flower
docker compose -f docker-compose.background.yml logs --tail=100 worker media-worker beat
```

Flower는 `127.0.0.1:5555`에만 연결합니다. 원격 접속은 로컬 PC에서 `ssh -L 5555:127.0.0.1:5555 <사용자>@<서버>`로 터널을 연 뒤 브라우저로 접속합니다. console 메일 backend를 사용하면 메일 내용이 로그에 남으므로 합성 데모 메시지에만 사용하고, 실제 회원 메일은 SMTP로 전환하세요.

## 6. 중단·업데이트

웹 요청을 잠시 제한하고 DB의 남은 작업을 먼저 처리합니다. pending/running이 남은 상태에서 기능을 끄거나 볼륨을 삭제하면 발송·이미지가 미완료로 남습니다. `delivery_uncertain`은 제공자 기록을 확인한 뒤에만 재처리합니다.

코드를 갱신할 때는 Beat를 먼저 멈추고 같은 커밋의 이미지로 작업자를 교체한 뒤 Beat 하나를 다시 시작합니다. 종료 유예는 기본 hard timeout보다 긴 330초로 두었습니다. 실제 배포에선 중단 창과 요청 제어도 함께 정하세요. 웹과 작업자의 코드·환경 변수가 서로 다른 상태를 장기간 유지하지 마세요.

DB 마이그레이션을 되돌리거나 `down -v`, Redis 데이터 삭제로 대기열을 비우는 것은 복구 방법이 아닙니다. 정기 작업의 운영 주체를 기존 cron으로 돌리려면 Beat 중단을 확인하고 기존 예약을 복구합니다. 원문이 남은 실패 작업은 [실패 큐 운영 가이드](background-jobs.md#4-실패-큐와-재시도)를 따릅니다.
