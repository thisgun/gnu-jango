# NICEPAY 인증결제 운영 가이드

이 문서는 NICEPAY **PG 인증결제** 제품군(`MID` + `MerchantKey` + 인증 응답의 `AuthToken`)을
Django + Next.js 쇼핑몰에 연결한 구현의 운영·전환 안내입니다. PAYU나 `clientId`/`secretKey`를
사용하는 별도 NICEPAY API 제품과 혼합하지 않습니다.

## 1. 선택한 제품과 공식 규격

- 결제창: `https://pg-web.nicepay.co.kr/v3/common/js/nicepay-pgweb.js`
  (`goPay(form)`, PC/Mobile 공통)
- 결제창 요청 서명: `hex(sha256(EdiDate + MID + Amt + MerchantKey))`
- 인증 응답 확인: `AuthResultCode=0000`, `Signature=hex(sha256(AuthToken + MID + Amt + MerchantKey))`
- 승인: 인증 응답의 `NextAppURL`로 `TID`(인증 응답의 `TxTid`), `AuthToken`, `MID`, `Amt`,
  `EdiDate`, `SignData`를 `application/x-www-form-urlencoded`, EUC-KR로 POST
- 승인 서명: `hex(sha256(AuthToken + MID + Amt + EdiDate + MerchantKey))`
- 승인 응답 서명: `hex(sha256(TID + MID + Amt + MerchantKey))`
- 성공 코드: 카드 `3001`, 계좌이체 `4000`, 가상계좌 `4100`, 휴대폰 `A000`
- 승인취소: `https://pg-api.nicepay.co.kr/webapi/cancel_process.jsp`,
  서명 `hex(sha256(MID + CancelAmt + EdiDate + MerchantKey))`,
  성공 코드 `2001`/`2211`, 응답 서명 `hex(sha256(TID + MID + CancelAmt + MerchantKey))`
- 망취소: 인증 응답의 `NetCancelURL`, `NetCancel=1`, 성공 코드 `2001`
- 거래조회: `https://webapi.nicepay.co.kr/webapi/inquery/trans_status.jsp`
  (`Status=0` 승인, `1` 취소, `9` 거래 없음), 서명
  `hex(sha256(TID + MID + EdiDate + MerchantKey))`
- 가상계좌 입금통보: NICEPAY 결제통보 규격을 수신하되, 통보의 `ResultCode`/`StateCd`를
  신뢰하지 않고 거래조회 결과로 검증한 뒤 결제완료 처리

공식 샘플 `app.py`와 최신 문서가 다른 부분:

- 샘플은 오래된 PC 중심 폼 전송 예제이고, 최신 문서의 결제창 스크립트는
  `pg-web.nicepay.co.kr/v3/common/js/nicepay-pgweb.js`입니다. 프런트 어댑터를 최신 스크립트로
  통일했습니다.
- 승인취소는 문서와 샘플 모두 `pg-api.nicepay.co.kr`를 사용합니다. 인증응답의
  `NetCancelURL`은 `dc1-api`/`dc2-api`의 `cancel_process.jsp`이므로 승인취소와 망취소를
  서로 다른 endpoint로 분리했습니다.
- 문서의 승인 응답 `Amt`는 12자리 zero-padding 예시가 있습니다. 서명 검증에는 응답에 온
  문자열을 그대로 사용하고, 주문 금액 비교는 정수로 합니다.

## 2. 지원 범위

지원:

- 신용카드, 실시간 계좌이체, 가상계좌, 휴대폰 소액결제
- PC `goPay` + AJAX 서버 승인
- Mobile `goPay` → NICEPAY가 `ReturnURL`로 인증 응답 POST → Django 서버 승인 → Next.js 결과 페이지
- 비회원 주문: 세션에 의존하지 않고 서버가 발급한 일회성 attempt token과 `ReqReserved`로 연결
- 전체취소·부분취소(카드/계좌이체/휴대폰), 승인취소 응답 검증
- 가상계좌 발급, 입금통보 수신, 거래조회 기반 입금 확정
- 승인 타임아웃/통신 단절 시 망취소, 로컬 저장 실패 상태 보존 및 관리자 확인
- 관리자 주문 취소·부분취소 흐름과 기존 재고·포인트·쿠폰·주문 원장 재사용

현재 미지원/계약 확인 필요:

- NICEPAY 에스크로: 별도 계약과 상점관리자 설정이 필요하므로 이번 구현에서는 노출하지 않습니다.
- NICEPAY 현금영수증 자동 발급: 인증결제 승인 요청에 현금영수증 식별번호를 보내는 흐름은
  가맹점 계약/ MID 옵션 확인 후 추가해야 합니다. 기존 토스 현금영수증 동작은 유지합니다.
- 간편결제를 독립 결제수단으로 노출하는 UI: NICEPAY 인증결제의 카드 직접호출 옵션과
  가맹점 계약이 확인되지 않아 `easy_pay` 버튼은 NICEPAY에서 비활성화합니다.
- 개인결제(personal pay): 기존 개인결제 온라인 결제는 토스 전용입니다. NICEPAY 개인결제는
  이번 범위에 포함하지 않았습니다.
- 가상계좌 입금 후 환불: NICEPAY 취소 API가 환불 계좌번호·은행코드·예금주를 요구하므로
  관리자 화면에서 해당 정보를 받는 별도 절차가 필요합니다. 정보가 없으면 자동 취소하지 않고
  수동 환불 대상으로 남깁니다.

## 3. 관리자 설정

`/admin/shop-settings/`의 **결제설정 → 결제대행사와 결제 방식**에서 `NICEPAY 인증결제`를
선택합니다.

- `결제 테스트`: 테스트/실결제 모드
- `NICEPAY 테스트 MID`, `NICEPAY 테스트 MerchantKey`
- `NICEPAY 실결제 MID`, `NICEPAY 실결제 MerchantKey`
- 결제수단 사용 여부: 신용카드·가상계좌·계좌이체·휴대폰 기존 스위치
- MID는 공개 식별자이므로 화면에 표시할 수 있습니다. MerchantKey는 저장 후 다시 표시하지
  않으며, 빈 입력은 기존 값을 유지하고 `삭제`를 선택할 때만 지웁니다.
- 두 값이 한쪽만 있으면 저장을 거부합니다. 실제 결제는 MID와 MerchantKey가 모두 있고 현재
  모드의 쌍이 완성된 경우에만 시작됩니다.
- 관리자 저장값은 `shop.sealed_values`로 암호화됩니다. 저장 이력에는 값이 남지 않습니다.

환경 변수 우선순위:

| 모드 | 환경 변수 |
| --- | --- |
| 테스트 | `SHOP_NICEPAY_TEST_MID`, `SHOP_NICEPAY_TEST_MERCHANT_KEY` |
| 실결제 | `SHOP_NICEPAY_MID`, `SHOP_NICEPAY_MERCHANT_KEY` |
| PG 선택 | `SHOP_PAYMENT_PROVIDER=nicepay` |
| 관리자 키 사용 | `SHOP_NICEPAY_ADMIN_KEYS_ENABLED` (미리보기에서는 `False`) |
| 가상계좌 | `SHOP_NICEPAY_VBANK_ENABLED` |
| 복합과세 취소 | `SHOP_NICEPAY_TAX_FREE_CANCEL_ENABLED` (계약 시에만) |
| 모바일/PC 복귀 | `SHOP_NICEPAY_RETURN_URL` |
| 결과 페이지 | `SHOP_NICEPAY_SUCCESS_URL` 또는 `SHOP_NICEPAY_FRONTEND_URL` |
| 입금통보 IP 제한 | `SHOP_NICEPAY_VBANK_NOTIFY_ALLOWED_IPS` (쉼표 구분, 선택) |
| 타임아웃 | `SHOP_NICEPAY_CONNECT_TIMEOUT`, `SHOP_NICEPAY_READ_TIMEOUT` |

환경 변수는 해당 모드의 관리자 키보다 우선합니다. 한 모드의 값만 설정하고 다른 모드로
결제하지 않도록 주의하세요.

## 4. URL 등록

NICEPAY 상점관리자에 아래 공개 HTTPS URL을 등록합니다.

- 복귀 URL(모바일/PC 표준 폼 전송):
  `https://<쇼핑몰-API-호스트>/api/v1/shop/payment/nicepay/return`
  (`SHOP_NICEPAY_RETURN_URL` 권장)
- 결과 페이지:
  `https://<쇼핑몰-프런트-호스트>/shop/payment/success`
  (`SHOP_NICEPAY_SUCCESS_URL`)
- 가상계좌 입금통보:
  `https://<쇼핑몰-API-호스트>/api/v1/shop/payment/nicepay/vbank/notification`
  (NICEPAY 상점관리자 결제통보 URL/IP)
  - NICEPAY 공식 결제통보 서버 IP: `121.133.126.10`, `121.133.126.11`, `211.33.136.39`
  - `SHOP_NICEPAY_VBANK_NOTIFY_ALLOWED_IPS`를 비우면 개발(`DEBUG=True`)에서만 수신하고
    운영(`DEBUG=False`)에서는 403으로 거절합니다. 운영에서는 위 IP를 명시하세요.
  - 통보의 `ResultCode=4110`, `StateCd=0`, `PayMethod=VBANK`를 확인하고, 거래조회의
    `Status=0`과 조회 응답에 포함된 TID/MID/주문번호/금액/결제수단도 대조합니다.
- 취소·망취소·거래조회 endpoint는 NICEPAY가 인증 응답/문서로 제공하는 호스트만 사용하며,
  관리자가 임의 URL을 넣을 수 없습니다.

`SHOP_NICEPAY_RETURN_URL`을 비워 두면 요청 호스트로 URL을 만들지만, 운영에서는 반드시
명시적인 HTTPS URL을 등록하세요. Vercel preview/개발 호스트는 NICEPAY 상점관리자에 등록하지
않습니다.

## 5. 결제·입금·취소 상태 흐름

결제 시도(`ShopPaymentAttempt`) 상태:

`prepared` → `approving` → `approved` (카드/계좌이체/휴대폰)
`prepared` → `approving` → `pending_deposit` (가상계좌)
`approving` → `uncertain` → `net_canceled` 또는 `uncertain` (승인 결과 불명확)
`approving` → `approved_local_failed` (PG 승인 후 로컬 저장 실패)
`failed`, `canceled` (거절/취소)

원칙:

- 인증 성공(`AuthResultCode=0000`)만으로 주문을 결제완료로 바꾸지 않습니다.
- 승인 응답의 `ResultCode`·MID·주문번호·TID·금액·결제수단·Signature를 모두 확인한 후
  `confirm_order_payment`를 한 번만 실행합니다.
- 승인 요청 타임아웃/통신 단절은 `uncertain`으로 두고 `NetCancelURL`로 망취소를 시도합니다.
  망취소 성공 시 `net_canceled`, 실패 시 `uncertain`으로 남겨 관리자가 확인합니다.
- 승인은 성공했지만 로컬 저장이 실패하면 `approved_local_failed`로 남깁니다. 응답 스냅샷과
  TID를 보존하고, 관리자 복구 시 로컬 결제 반영만 재시도합니다. 승인 API를 다시 호출하지
  않습니다.
- 가상계좌는 `4100` 승인 응답 후 `pending_deposit`입니다. 입금통보를 받으면 거래조회
  `Status=0`을 확인한 뒤에만 결제완료 처리합니다. 중복·지연 통보는 거래조회 결과로
  멱등 처리합니다.
- 취소는 기존 관리자/구매자 권한과 주문 상태 제한을 그대로 따릅니다. NICEPAY 전체/부분취소는
  누적 취소액과 잔액을 검증하고, 동시 취소는 주문 잠금과 기존 부분취소 계획으로 막습니다.
- NICEPAY는 취소 API에 idempotency key가 없습니다. 요청 타임아웃 후에는 거래조회/상점관리자
  거래 상태를 확인하기 전까지 재시도하지 않습니다. 성공 응답을 받은 취소만 로컬 환불로
  반영합니다.

## 6. 장애 복구

- 승인 결과 불명확: `ShopPaymentAttempt.state=uncertain`, `last_error`, 원본 응답 로그를
  확인합니다. 망취소가 성공했으면 `net_canceled`입니다. 실패했으면 NICEPAY 상점관리자에서
  TID와 승인 상태를 확인합니다.
- 승인 후 저장 실패: `approved_local_failed`. 동일 TID/금액으로 로컬 반영만 복구합니다.
- 입금통보 조회 실패: endpoint가 503을 반환해 NICEPAY가 재통보하도록 합니다. 성공한
  중복 통보는 200/OK로 멱등 처리합니다.
- 취소 후 로컬 저장 실패: 기존 `order_lines`/`order_flow`가 PG 성공을 기록하고 관리자에게
  확인을 요청합니다.
- 가상계좌 만료 후 입금/취소 후 입금: 자동으로 결제완료 처리하지 않고
  `nicepay-vbank-late-paid`/`nicepay-vbank-review` 로그와 관리자 확인 대상으로 남깁니다.
- 키 교체: 결제 시도에 MID/MerchantKey의 비가역 지문을 기록합니다. 승인·취소 시 현재 키
  지문이 다르면 자동 처리하지 않고 기존 키 복원 또는 NICEPAY 상점관리자 처리를 안내합니다.

## 7. 보안·배포

- `NextAppURL`/`NetCancelURL`은 HTTPS, 허용 호스트, 정확한 `/webapi/...` 경로, 443 포트만
  허용합니다. 사용자 정보·쿼리·프래그먼트·리다이렉트를 거부합니다.
- TLS 인증서 검증을 유지하고 연결/읽기 타임아웃을 둡니다.
- 승인·취소·조회 요청은 서버에서만 수행하며 MerchantKey/AuthToken을 브라우저에 보내지
  않습니다. 로그에는 `AuthToken`, `Signature`, `MerchantKey`, 구매자 개인정보를 마스킹합니다.
- 외부 콜백인 Return URL과 가상계좌 통보만 CSRF 예외로 두고, 관리자·주문 API의 기존 인증과
  CSRF 보호는 유지합니다.
- 장바구니/주문 금액은 서버가 확정합니다. 프런트가 보낸 `amount`는 승인 판단에 사용하지
  않습니다. 정수 원 단위만 사용합니다.
- Vercel에서는 Celery/Redis 작업자가 항상 실행된다고 가정하지 않습니다. 승인과 가상계좌
  통보 검증은 요청 안에서 완료하고, 메일·SMS는 기존 작업 큐가 실패해도 결제 상태를 잃지
  않게 합니다. 별도 서버에서는 Celery worker/beat의 outbox 소진 상태를 모니터링합니다.
- CSP는 NICEPAY 결제창 스크립트(`pg-web.nicepay.co.kr`)와 프레임/폼 전송 호스트를 허용해야
  합니다. `docs/nginx/nextjs25-security-map.conf`도 같은 호스트를 포함하도록 갱신합니다.

## 8. 운영 전환 체크리스트

1. NICEPAY 상점관리자에서 인증결제 MID와 MerchantKey, 사용할 결제수단, 가상계좌 사용 여부,
   Return URL, 입금통보 URL을 등록합니다.
2. 관리자 결제설정에서 테스트 모드로 테스트 MID/MerchantKey를 저장하고 테스트 결제창을
   엽니다. 실제 승인/취소는 NICEPAY 테스트 계정에서만 수행합니다.
3. 테스트 카드·계좌이체·가상계좌·휴대폰의 승인, 취소, 가상계좌 입금통보를 확인합니다.
4. 실결제 MID/MerchantKey를 별도 모드로 저장하고 `결제 테스트`를 실결제로 바꿉니다.
5. `SHOP_NICEPAY_RETURN_URL`, `SHOP_NICEPAY_SUCCESS_URL`이 공개 HTTPS인지 확인합니다.
6. Vercel/운영 서버의 환경 변수와 CSP를 배포하고, 실제 소액 결제 1건과 취소 1건을
   NICEPAY 테스트/승인된 범위에서 확인합니다.

## 9. 검증 범위

모의 응답으로 다음을 검증했습니다.

- 설정 선택·MID/MerchantKey 누락/형식, 비밀값 비노출
- 서버 금액·서명 생성, 인증 응답 서명, 승인 응답 서명
- 금액·MID·주문번호·TID 변조 거부
- 카드 승인 성공, 중복 승인, 승인 실패
- 승인 타임아웃 및 망취소, 승인 후 로컬 저장 실패
- 전체/부분취소 서명·응답 검증
- 가상계좌 거래조회 기반 입금 완료, 금액 불일치 거부
- 비회원 모바일 Return URL 승인, attempt token 누락 거부
- 외부 URL 허용 목록(SSRF) 거부

실제 NICEPAY 테스트 MID/MerchantKey가 없어 수행하지 못한 검증:

- 실제 PC/모바일 결제창 호출과 인증
- 실제 NICEPAY 테스트 승인·취소·망취소
- 실제 가상계좌 발급·입금통보·만료
- 실제 가맹점 계약 옵션(에스크로·현금영수증·간편결제) 확인

이 항목은 테스트 가맹점 정보가 준비된 뒤 별도로 확인해야 하며, 모의 테스트 통과를 실제
NICEPAY 연동 성공으로 간주하지 않습니다.
