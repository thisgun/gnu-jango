# 감사 로그·이력 관리

주문·주문상품·상품 가격/재고·쿠폰·배송정책·포인트 원장·쿠폰 사용·사이트 설정의 변경
이력을 `django-simple-history`로 기록한다. 관리자 화면에는 통합 감사 로그
(`/admin/audit-log/`)와 모델별 이력/복원 화면이 있다.

## 기록 대상

| 모델 | 이력 테이블 | 비고 |
| --- | --- | --- |
| `shop.ShopOrder` | `shop_historicalshoporder` | 주소·메모·송장·상태·금액 등 필드 단위 |
| `shop.ShopOrderItem` | `shop_historicalshoporderitem` | 수량·금액·상태·쿠폰/포인트 관련 필드 |
| `shop.ShopProduct` | `shop_historicalshopproduct` | 가격·재고·옵션·판매상태. 긴 설명/이미지/조회·판매 카운터는 제외 |
| `shop.ShopCoupon` | `shop_historicalshopcoupon` | 발급 쿠폰의 할인율·기간·대상. 사용 상태(`cp_used`)는 사용 로그에서 추적 |
| `shop.ShopShippingPolicy` | `shop_historicalshopshippingpolicy` | 배송비·배송정책 싱글턴 |
| `shop.ShopCouponLog` | `shop_historicalshopcouponlog` | 쿠폰 사용/복원 기록 |
| `users.User_Point` | `users_historicaluser_point` | 포인트 원장 |
| `config.Config` | `config_historicalconfig` | 실제 설정 이름(`cf_`, `de_`, `shop_`, `pg_`)만 |

- 각 이력 행에는 `history_date`, `history_type`(`+`/`~`/`-`), `history_user`가 저장된다.
- `HistoryRequestMiddleware`가 요청 중 저장되는 이력에 `request.user`를 자동으로 붙인다.
  관리자 화면·관리자 액션·커스텀 설정 화면과 DRF JWT API 요청 모두 해당된다. 웹훅/배치/게스트
  주문처럼 request user가 없는 변경은 `System`으로 표시된다.
- `ShopOrder.od_ip`, `od_vbank_secret_hash`는 이력에서 제외한다. 개인정보/비밀값을 이력
  테이블에 중복 저장하지 않기 위해서다.
- `ShopProduct`는 긴 설명·이미지·조회/판매 카운터를 이력에서 제외한다. 가격·재고·옵션은 남긴다.
- `Config`의 비밀값(`*secret*`, `*password*`, `*token*`, KG 본인확인 키 등)은 이력에
  `********`로 저장한다. 비밀값 이력은 복원할 수 없다(마스킹된 값으로 덮어쓰는 사고 방지).
- 장바구니(`auth_cart_*`), 소셜 신원, 샘플 데이터 매니페스트처럼 설정이 아닌 `Config`
  행은 이력에 저장하지 않는다. 장바구니 갱신 때마다 이력이 쌓이는 것을 막는다.

## 복원 규칙

| 모델 | 복원 | 이유 |
| --- | --- | --- |
| `Config` (비밀값 제외) | 가능 | 설정 화면에 즉시 반영되고 캐시도 비운다. |
| `ShopOrder` | 주소·메모·송장 등 안전한 필드만 | 상태·결제·환불·포인트를 직접 되돌리면 재고·쿠폰·포인트·PG 환불과 불일치한다. |
| `User_Point` | 불가 | 원장 행과 `Profile.user_point`는 `point_ledger.insert_point`가 함께 쓴다. |
| `ShopCouponLog` | 불가 | 주문 금액과 쿠폰 복원에 직접 영향을 주는 원장이다. |
| `ShopOrderItem` | 불가 | 수량·상태 변경은 재고·포인트와 연결되어 주문 처리 흐름으로만 바꾼다. |
| `ShopProduct` | 불가 | 재고·옵션 복원이 재고 예약/조정 경로를 우회한다. 가격 수정은 상품 폼에서 한다. |
| `ShopCoupon` | 불가 | 발급된 쿠폰의 과거 규칙으로 되돌리면 이미 사용된 쿠폰의 의미가 바뀐다. |
| `ShopShippingPolicy` | 불가 | 배송비/전화번호가 Config·캐시와 함께 움직이므로 live 폼에서 수정한다. |


`ShopOrder` 복원에서 `ORDER_HISTORY_LOCKED_FIELDS`(상태, 결제/환불 금액, `od_misu`,
포인트/쿠폰, 가상계좌 상태 등)는 항상 현재 주문의 값으로 되돌린 뒤 저장한다. 즉 과거
스냅샷의 주소·메모·송장은 복원되지만, 상태와 금액은 복원되지 않고 현재 값이 유지된다.
POST로 보호 필드를 조작해도 서버에서 현재 값으로 덮어쓴다. 상태 변경은 반드시 주문 처리
흐름(상태 변경/취소/반품)을 사용한다.

## 운영

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py backfill_audit_history --dry-run --import-order-history
python manage.py backfill_audit_history --import-order-history
```

- `backfill_audit_history`는 이력이 없는 객체에만 `+` 초기 스냅샷을 만든다. 재실행해도
  중복되지 않는다. `--models shop.ShopProduct ...`로 범위를 좁힐 수 있다.
- `--import-order-history`는 기존 `ShopOrder.od_mod_history`의 `주문상태 A→B 처리` 줄을
  읽어 과거 상태 전이를 `~` 이력으로 추가한다. 레거시 텍스트에는 전체 필드가 없으므로
  상태 외 필드는 현재 스냅샷이며 `history_change_reason`에 `od_mod_history import`를 남긴다.
- `Config` 백필은 실제 설정 접두사(`cf_`, `de_`, `shop_`, `pg_`)만 대상으로 한다. 장바구니
  같은 임시 행은 제외한다.
- Audit log의 **CSV 다운로드**는 현재 필터 결과(모델별 최대 500건)를 내려받는다.
- `Config` 이력 복원은 설정 화면과 같은 필드 타입으로 검증한다. 숫자/이메일/선택지가
  잘못된 값이나 설정 화면에 없는 이름은 복원되지 않는다.
- 보관 기간이 지난 이력은 아래 명령으로 삭제한다. 삭제 전 개인정보 보관 기간과 분쟁 대응
  기간을 함께 검토하고, DB 백업/권한 분리 정책을 먼저 정한다.

```bash
# 365일보다 오래된 이력 삭제 (dry-run 먼저)
python manage.py purge_audit_history --days 365 --dry-run
python manage.py purge_audit_history --days 365
```

- `purge_audit_history`는 `--models`로 범위를 좁힐 수 있고, `history_date`만 기준으로
  삭제한다. 기준일 이전의 최신 스냅샷도 예외 없이 삭제되므로, 최신 기준점을 남기려면
  `--days`를 데이터 보관 정책에 맞게 조정해야 한다. 이력 테이블은 앱 레벨에서 수정
  가능하므로 법적 불변성이 필요하면 DB 계정 권한/트리거/백업을 별도로 구성해야 한다.
- `ShopProduct.options` JSON은 옵션별 재고 이력을 위해 포함한다. 고볼륨몰에서는
  `shop_historicalshopproduct` 행 크기와 증가 속도를 모니터링한다.
- 통합 감사 로그는 모델별 최근 500건을 스캔해 최신순으로 합친다. 기간·사용자·모델·검색어
  필터로 범위를 좁혀 사용한다.

## 테스트

`gnu_jango/core/test_audit_history.py`, `test_audit_backfill.py`, `test_audit_api.py`,
`test_audit_retention.py`가 다음을 검증한다.

- 8개 모델의 생성/수정 이력과 필드 diff
- 주문/상품 이력에서 민감 필드·대용량 필드 제외
- 설정 비밀값 마스킹과 복원 값 타입 검증
- 관리자 이력 화면/통합 감사 로그 접근 권한·액션 라벨·CSV export
- 설정 복원, 주문 안전 필드 복원/보호 필드 유지, 원장/카탈로그 복원 차단
- 백필 초기 스냅샷·idempotency·`od_mod_history` 상태 이벤트 import
- 보존 기간 초과 이력 삭제와 dry-run
- JWT API 주문 생성 시 `history_user`가 회원으로 기록되는지
- `HistoryRequestMiddleware`의 `history_user` 기록
