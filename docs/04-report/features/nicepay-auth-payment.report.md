# NICEPAY 인증결제 구현 보고

## 구현 범위

NICEPAY PG 인증결제(`MID` / `MerchantKey` / `AuthToken`)를 기존 Django 주문·재고·포인트·
쿠폰·결제 로그·관리자 취소 흐름에 연결했습니다. PAYU/clientId·secretKey 제품은 사용하지
않았습니다.

### 백엔드

- `gnu_jango/api/shop_nicepay.py`
  - 인증 응답 검증과 `NextAppURL` 서버 승인
  - 승인 응답의 상태 코드·MID·주문번호·TID·금액·결제수단·서명 검증
  - 승인 타임아웃 시 `NetCancelURL` 망취소와 `uncertain`/`net_canceled` 상태
  - 승인 후 로컬 저장 실패 시 `approved_local_failed` 보존
  - 전체/부분취소, 가상계좌 발급, 거래조회, 입금통보 검증
  - NextAppURL/NetCancelURL HTTPS 호스트·경로 allow-list, EUC-KR form, 타임아웃
  - 비회원 모바일 복귀용 일회성 attempt token과 `ReqReserved`
- `gnu_jango/shop/models.py` + migration `0036_shoppaymentattempt.py`
  - `ShopPaymentAttempt`: 모드·MID·금액·결제수단·TID·암호화 AuthToken·승인 URL·키 지문·
    상태·마지막 오류·응답 스냅샷
- `gnu_jango/shop/pg_settings.py`
  - NICEPAY MID/MerchantKey 설정, 테스트/실결제 모드, 환경 변수 우선순위, 봉인 저장,
    키 지문, 설정 상태
- `gnu_jango/api/shop_payments.py`
  - PG 선택과 결제수단 계산에 NICEPAY 추가, 로그 마스킹 확장
- `gnu_jango/api/v1_shop.py`
  - 결제 config/prepare/confirm/cancel 연결, NICEPAY `pg_extra`, 모바일 반환 endpoint
- `gnu_jango/api/v1_urls.py`
  - `/api/v1/shop/payment/nicepay/return`
  - `/api/v1/shop/payment/nicepay/vbank/notification`
- `gnu_jango/shop/order_flow.py`, `gnu_jango/shop/order_lines.py`
  - 관리자 전체취소와 부분취소에서 NICEPAY API 사용
- `gnu_jango/shop/admin_pg_settings.py`, `admin_settings.py`, 관리자 템플릿
  - NICEPAY 필드, write-only MerchantKey, 상태·경고·URL 안내
  - 관리자 `ShopPaymentAttempt` 읽기 전용 목록

### 프런트엔드

- `nextjs/src/lib/payment.nicepay.ts`
  - 최신 공식 스크립트 `pg-web.nicepay.co.kr/v3/common/js/nicepay-pgweb.js`
  - PC/Mobile `goPay`, 모바일은 서버 `ReturnURL`로 복귀
  - 서버가 준 `EdiDate`/`SignData`/MID/attempt token 사용
  - 승인은 `/shop/payment/confirm` 서버 호출로만 수행
- `nextjs/src/lib/payment.types.ts`
  - attempt token, `ReqReserved`, 결제수단 필드
- `nextjs/src/app/shop/order/orderSubmitActions.ts`
  - NICEPAY 준비 응답 허용
- `nextjs/src/app/shop/payment/success/page.tsx`
  - 서버 Return URL 결과(`payment_status=paid|pending|error`)를 표시하고 중복 confirm 방지
- `nextjs/tests/payment-nicepay.spec.ts`
  - 최신 모바일 goPay 흐름에 맞춘 테스트

## 기존 코드 재사용·수정

- 주문 생성, 금액·세금·배송비 계산, 재고 예약, 포인트·쿠폰 사용, 주문 상태 전환은 기존
  `create_order_from_request`, `confirm_order_payment`, `cancel_order_and_refund_benefits`,
  `change_locked_order_lines`를 그대로 사용했습니다.
- Toss 결제 흐름과 무통장입금 흐름은 기존 테스트로 회귀 확인했습니다.
- 관리자 인증/CSRF는 유지하고, 외부 Return URL/입금통보 endpoint만 `csrf_exempt`로
  제한했습니다.
- 개인결제 온라인 결제는 기존 토스 전용 동작을 유지했습니다.

## 테스트 결과

- `manage.py check`: 통과 (기존 silenced 1개)
- `gnu_jango.core.test_shop_nicepay`: **43개 통과** (관리자 설정 상속 회귀 포함)
- `manage.py test` 전체: **2,900개 통과**, 23개 skip
- Next.js `npm run typecheck`: 통과
- Next.js `npm run lint`: 통과
- `npx playwright test tests/payment-nicepay.spec.ts --workers=1`: **10개 통과**
- `nextjs_default` 정적 테마 빌드: 통과
- `handbook` 정적 테마 빌드: 통과
  - 일회용 DB(`migrate` + `ensure_handbook_samples --stable-dates`)와 빈 공개 URL로 빌드
  - `check:theme-sync`, `check:theme-sync:handbook`: 통과
  - `git diff origin/main`에서 새 금지 문자열(127.0.0.1, 8000/8081/8090, 로컬 경로,
    로컬 DB 게시판) 없음 확인

실제 NICEPAY 테스트 가맹점 정보가 없어 실제 결제창·승인·취소·가상계좌 입금통보는
수행하지 못했습니다. 모의 테스트 통과를 실제 연동 성공으로 보고하지 않습니다.

## 마이그레이션

- `gnu_jango/shop/migrations/0036_shoppaymentattempt.py`
- `ShopPaymentAttempt` 테이블 생성. 운영 DB와 데모/핸드북 Supabase에는 병합 전에 별도
  적용이 필요합니다. 이번 작업에서는 운영/로컬 DB에 migrate하지 않았습니다.

## 코드 리뷰 반영 (PR #84)

- **H1 이중 결제 방지**: 새 attempt 생성 시 주문 row를 `select_for_update(of=("self",))`로
  잠그고 이전 open attempt를 `superseded`로 닫습니다. 승인 전에도 주문 상태/`od_tno`를
  잠금 하에 확인하며, 승인 후 다른 TID가 이미 기록되어 있으면 해당 승인을 망취소하고
  `superseded`로 남깁니다.
- **H2 가상계좌 통보**: 운영(`DEBUG=False`)에서 IP 허용 목록이 비면 403; 공식 NICEPAY
  통보 IP(`121.133.126.10`, `121.133.126.11`, `211.33.136.39`)를 문서화했습니다.
  `ResultCode=4110`/`StateCd=0`/`PayMethod=VBANK`를 확인하고, 거래조회의 TID/MID/주문번호/
  금액/결제수단(존재하는 경우)을 대조합니다. 동일 TID 재통보는 아무 것도 바꾸지 않습니다.
- **M1**: `approved_local_failed`는 다음 복귀/확인에서 `recover_nicepay_attempt`로 로컬
  반영만 재시도합니다.
- **M2**: `recover_nicepay_attempts` 관리 명령을 추가하고 `run_scheduled_jobs`의 5분 주기
  작업에 등록했습니다. 오래된 `approving`/`uncertain`/`approved_local_failed`를 거래조회로
  정리합니다.
- **M3**: 취소 한도를 `od_receipt_price - od_refund_price` 잔액으로 제한하고, 취소 응답
  유실 시 거래조회 `Status=1`을 확인한 뒤 전체취소만 already-canceled로 인정합니다.
  `SHOP_NICEPAY_TAX_FREE_CANCEL_ENABLED` 계약 옵션이 켜진 경우 `TaxFreeAmt`를 보냅니다.
- **LOW**: 취소 로그에서 환불 계좌/예금주/SignData를 마스킹하고, 인증 오류 상태 변경을
  row lock 하에서 수행하며, attempt FK를 `SET_NULL`로 바꿔 결제 기록이 주문 삭제와 함께
  사라지지 않게 했습니다.
- 마이그레이션은 기존 `0036_shoppaymentattempt.py`를 수정했습니다(아직 병합 전).

## 남은 작업·제한

- 실제 NICEPAY 테스트 MID/MerchantKey로 PC·모바일 인증→승인→취소, 가상계좌 입금통보를
  확인해야 합니다.
- NICEPAY 에스크로·현금영수증 자동 발급·간편결제 독립 버튼은 계약/ MID 옵션 확인 후
  추가해야 합니다.
- 가상계좌 입금 후 환불은 환불 계좌·은행·예금주 입력 UI와 관리자 승인 절차가 필요합니다.
- NICEPAY 취소 API에는 idempotency key가 없어, 응답 유실 시 거래조회/상점관리자 확인 전
  자동 재시도하지 않습니다.
- 관리자 `ShopPaymentAttempt` 화면에서 `approved_local_failed`/`uncertain` 거래의 복구
  액션(조회 후 로컬 반영)을 별도 버튼으로 노출하는 후속 작업이 필요합니다. 현재는 상태와
  오류/응답 스냅샷을 확인할 수 있습니다.
- 실제 Vercel 배포 프로필에서 Redis/Celery가 없는 경우 즉시 승인은 동작하지만, 메일·SMS
  후속 작업은 기존 작업 큐 정책을 따릅니다.

## 운영 전환 준비물

- NICEPAY 인증결제 테스트/실결제 MID와 MerchantKey
- NICEPAY 상점관리자에 등록할 공개 HTTPS Return URL, 결과 URL, 가상계좌 입금통보 URL
- 사용할 결제수단과 가상계좌/에스크로/현금영수증 계약 범위
- `SHOP_NICEPAY_*` 환경 변수와 CSP 허용 호스트
- 마이그레이션 적용 후 `ShopPaymentAttempt` 테이블 확인

## 이번 작업에서 하지 않은 것

- PR 병합·배포 (리뷰 반영 커밋과 push, PR 생성은 수행)
- 운영 DB/로컬 8081 DB 변경 및 8081 서버 재시작
- 실제 결제·환불·NICEPAY 테스트 승인
- 실제 테스트 가맹점 키 입력 또는 하드코딩
