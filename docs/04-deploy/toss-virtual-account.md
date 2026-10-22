# Toss 가상계좌 운영 설정

가상계좌 결제는 기본 비활성화되어 있습니다. Toss의 공개 HTTPS 웹훅을 등록하고 테스트한 뒤 `.env`에 `SHOP_TOSS_VBANK_ENABLED=True`를 설정하세요.

## 환경 변수

키는 관리자 > 쇼핑몰 설정 > 결제설정의 결제대행사 항목에 등록할 수도 있습니다(암호화 저장, 결제 테스트 설정에 따라 테스트·실결제 키 쌍 선택). 아래 환경 변수의 키가 하나라도 있으면 환경 변수가 우선합니다. 같은 화면에 가상계좌 입금통보 URL이 전체 주소로 표시됩니다.

```dotenv
SHOP_TOSS_CLIENT_KEY=발급받은_클라이언트_키
SHOP_TOSS_SECRET_KEY=발급받은_시크릿_키
SHOP_TOSS_API_BASE_URL=https://api.tosspayments.com
SHOP_TOSS_VBANK_ENABLED=True
```

키는 저장소에 올리지 말고 배포 환경의 비밀 변수 저장소에서 관리하세요. 테스트 키와 라이브 키를 섞지 마세요.

## Toss 웹훅 등록

Toss 개발자센터에서 `DEPOSIT_CALLBACK` 이벤트를 등록하고 다음 URL을 입력합니다.

```text
https://<공개-도메인>/api/v1/shop/payment/toss/vbank/webhook
```

서버에서 이 엔드포인트로 들어온 이벤트의 결제별 `secret`을 SHA-256 해시와 비교한 뒤, Toss 결제 조회 API에서 최신 상태·주문번호·금액·결제수단을 확인합니다. 결제 조회가 일시 실패하면 웹훅 재시도를 위해 오류 응답을 반환합니다.

## 주문 상태

- 가상계좌 발급 직후에는 `WAITING_FOR_DEPOSIT`으로 저장하고 계좌번호와 입금 기한을 주문 상세에 표시합니다.
- Toss가 `DONE`을 확인한 뒤에만 주문을 결제 완료로 바꿉니다.
- 입금 오류로 다시 `WAITING_FOR_DEPOSIT`이 오면 주문을 입금 대기로 되돌립니다.
- 미입금 주문 취소는 Toss 계좌 취소가 확인된 후 재고와 쿠폰을 복구합니다.
- Toss는 입금 기한 만료만으로 웹훅을 보내지 않습니다. `expire_toss_vbank_orders` 명령을 정기 실행해 만료 주문을 조회하고 Toss 취소가 확인된 경우에만 재고와 쿠폰을 복구합니다.

## 만료 주문 정리 예약

먼저 dry-run으로 만료 후보를 확인합니다. 기본 실행은 데이터베이스와 Toss에 쓰지 않습니다.

```powershell
python manage.py expire_toss_vbank_orders --json
```

출력된 후보와 기한을 확인한 뒤 `--apply`를 붙여 실행합니다. 이때 서버는 Toss 결제 상태와 주문번호·금액·결제수단을 확인하고, 아직 입금 대기인 계좌만 취소합니다. Toss 조회·취소에 실패하면 주문과 재고 상태를 유지합니다.

```powershell
python manage.py expire_toss_vbank_orders --apply --json
```

운영 서버의 작업 스케줄러에서 하루 한 번 이상 실행하고, 실패 건은 명령 종료 코드와 출력 로그로 확인하세요. 실제 배포에서는 주문량에 따라 `--limit`을 조정합니다.

## 배포 전 점검

1. Toss 테스트 키와 테스트 웹훅으로 계좌 발급을 확인합니다.
2. 테스트 결제 내역에서 입금 처리 후 주문이 결제 완료로 바뀌는지 확인합니다.
3. 미입금 상태의 취소로 Toss 계좌가 취소되고 재고가 복구되는지 확인합니다.
4. 정상 동작을 확인한 뒤 라이브 키와 운영 웹훅으로 전환합니다.

## 로컬 회귀 검증

2026-10-09 기준, 다음 검증이 통과했습니다.

```powershell
python manage.py test gnu_jango.core.test_shop_security gnu_jango.core.test_shop_inventory gnu_jango.core.test_toss_vbank gnu_jango.core.test_shop_vbank_expiry
npm run build:theme
```

Django 33개 테스트는 주문 권한, 재고 취소, 가상계좌 발급·웹훅·만료 정리 흐름을 확인합니다. Toss API 응답은 mock 처리했으므로 실제 Toss 테스트 거래와 공개 HTTPS 웹훅 확인을 대신하지 않습니다. 현재 환경의 정적 빌드는 99개 라우트를 생성하고 Django 테마 산출물 371개 파일이 `nextjs/out`과 일치했습니다.
