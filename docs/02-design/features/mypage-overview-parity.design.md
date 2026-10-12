# 마이페이지 최근 활동 미리보기 설계

> 작성일: 2026-10-12 | 상태: 진행 중 | 계획: [mypage-overview-parity.plan.md](../../01-plan/features/mypage-overview-parity.plan.md)

## 설계 목표

회원 대시보드(`/mypage`)에서 기존 숫자 요약을 유지하면서 Gnuboard5와 같은 최근 주문·위시리스트를 함께 제공한다. 브라우저에서 회원 전용 API를 호출하며 Django 데이터 모델과 응답 스키마는 변경하지 않는다.

## 구성 및 데이터 흐름

1. 대시보드가 `GET /shop/orders?page=1&per_page=5`와 `GET /shop/wishlist?page=1&per_page=8`을 요청한다.
2. 주문은 최신순으로 다섯 줄까지 표에 표시한다. 주문번호는 `/shop/orders/{od_id}` 상세 링크이며 주문 금액·입금액·미입금액은 기존 `ShopOrder` 응답 값을 사용한다.
3. 위시리스트는 최신 여덟 상품까지 DaisyUI 카드와 이미지·상품명·가격으로 표시한다. 상품 링크는 기존 `shopProductHref` 규칙을 따른다.
4. 섹션별 로딩·오류·빈 상태를 표시하고 전체 목록 링크를 항상 제공한다.

## API 계약

| 화면 데이터 | API | 접근 |
|---|---|---|
| 최근 주문 | `GET /api/v1/shop/orders?page=1&per_page=5` | 로그인 회원 소유 주문만 |
| 최근 위시리스트 | `GET /api/v1/shop/wishlist?page=1&per_page=8` | 로그인 회원 소유 항목만 |

응답은 기존 `shopOrderListSchema`와 `shopWishItemListSchema`로 파싱한다. `getWishlist`에는 선택적 페이지 크기 인자를 더하되 인자 없이 부르는 기존 화면의 요청 동작은 보존한다.

## 구현 파일 및 검증

- `nextjs/src/app/mypage/page.tsx`: 섹션별 데이터·상태, 주문 표, 위시리스트 카드 추가.
- `nextjs/src/services/cart.ts`: 선택적 pagination 인자 지원.
- `nextjs/tests/mypage-overview.spec.ts`: 로그인 후 각 섹션과 전체 목록 링크 확인.
- `docs/03-analysis/nextjs-default-subpages.audit.md`: 원본 PHP 동작, QA와 게이트 결과를 다음 번호로 기록.

주문 취소·결제 API는 호출하지 않는다. 8094 QA 데이터베이스로만 Playwright를 실행하며 8081과 실제 DB는 사용하지 않는다.
