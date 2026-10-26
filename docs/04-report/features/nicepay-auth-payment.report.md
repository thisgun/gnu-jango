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
- `gnu_jango.core.test_shop_nicepay`: **32개 통과** (관리자 설정 상속 회귀 포함)
- `gnu_jango.core.test_shop_payments_api`: **154개 통과**
- `test_shop_payments_api` + `test_shop_nicepay` 동시 실행: **186개 통과**
- `gnu_jango.core.test_shop_pg_settings`: **41개 통과**
- `gnu_jango.core.test_shop_personal_pay_checkout`: 별도 회귀 예정
- `gnu_jango.core.test_shop_partial_cancel`, `test_shop_partial_qty_cancel`,
  `test_shop_admin_order_processing`, `test_shop_vbank_expiry`,
  `test_shop_personal_pay_checkout`: **115개 통과**
- Next.js `npm run typecheck`: 통과
- Next.js `npm run lint`: 통과
- `npx playwright test tests/payment-nicepay.spec.ts --workers=1`: **10개 통과**
- `nextjs_default` 정적 테마 빌드: 통과
- `handbook` 정적 테마 빌드: 통과
  - 공개 API URL을 비우고 G5/APP URL은 로컬 fallback을 피하기 위해 HTTPS 운영 문서
    주소로 빌드했습니다.
  - 그러나 `NEXT_PUBLIC_API_URL`이 비어 있을 때 `config.ts`의 개발 fallback
    (`127.0.0.9`)과 라이브러리 코드의 `localhost` 문자열이 번들에 남는 것을 확인했습니다.
    따라서 저장소 규칙에 따라 **생성 테마 결과물은 커밋하지 않았습니다.** 운영 URL을 확정한
    뒤 다시 빌드해야 합니다. 로컬 경로·로컬 게시판 페이지는 생성되지 않았습니다.
  - 이번 작업은 요청대로 커밋·push·PR·배포를 하지 않았으므로 생성 테마 파일은 작업 트리에만
    남아 있습니다.

실제 NICEPAY 테스트 가맹점 정보가 없어 실제 결제창·승인·취소·가상계좌 입금통보는
수행하지 못했습니다. 모의 테스트 통과를 실제 연동 성공으로 보고하지 않습니다.

## 마이그레이션

- `gnu_jango/shop/migrations/0036_shoppaymentattempt.py`
- `ShopPaymentAttempt` 테이블 생성. 운영 DB와 데모/핸드북 Supabase에는 병합 전에 별도
  적용이 필요합니다. 이번 작업에서는 운영/로컬 DB에 migrate하지 않았습니다.

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

- 커밋, push, PR 생성·병합, 배포
- 운영 DB/로컬 8081 DB 변경 및 8081 서버 재시작
- 실제 결제·환불·NICEPAY 테스트 승인
- 실제 테스트 가맹점 키 입력 또는 하드코딩
