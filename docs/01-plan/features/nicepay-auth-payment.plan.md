# NICEPAY 인증결제 구현 계획

## 목표

기존 Toss/무통장입금 주문 흐름을 유지하면서 NICEPAY PG 인증결제를 주문 화면·서버 승인·
관리자 취소·가상계좌 입금통보까지 연결한다.

## 제품 선택

- NICEPAY PG 인증결제: MID, MerchantKey, 인증 응답 AuthToken
- 제외: PAYU, clientId/secretKey 기반 별도 API 제품
- 근거: 공식 `docs/pg/auth/*`, 공식 Python 인증결제 샘플, 결제통보·거래조회 문서

## 단계

1. 기존 결제 추상화와 주문/재고/포인트/쿠폰/취소 흐름 분석
2. NICEPAY 설정·키 보관·write-only 관리자 필드 추가
3. `ShopPaymentAttempt`로 모드·MID·금액·TID·AuthToken·키 지문·상태 영속화
4. prepare: 서버 금액, EdiDate/SignData, attempt token, pg_extra 생성
5. confirm: 인증 서명·필드 검증, NextAppURL allow-list, 서버 승인, 응답 서명 검증
6. timeout/unknown: uncertain + NetCancelURL 망취소
7. 로컬 저장 실패: approved_local_failed + 관리자 확인
8. 전체/부분취소 및 기존 주문 취소·환불 원장 연결
9. 가상계좌 발급·입금통보·거래조회 기반 확정
10. PC/Mobile 프런트 SDK·Return URL·결과 페이지 연결
11. 모의 테스트, 회귀 테스트, 타입/린트, 테마 빌드 검증
12. 운영 전환·실제 테스트 한계 문서화

## 완료 조건

- 인증 성공만으로 결제완료가 되지 않는다.
- 승인 응답 검증 후에만 주문·재고·포인트·쿠폰이 한 번 반영된다.
- 승인 불명확·로컬 저장 실패가 관리자에게 보이는 상태로 남는다.
- 취소 성공 후에만 로컬 환불이 반영된다.
- 가상계좌는 거래조회로 입금을 확인한 후에만 결제완료가 된다.
- 비밀값이 브라우저·로그·문서·커밋에 노출되지 않는다.
- 실제 테스트 가맹점이 없어 못 한 검증은 명시한다.
