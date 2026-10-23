# 감사 로그·이력 관리

주문·포인트·쿠폰 사용·사이트 설정의 변경 이력을 `django-simple-history`로 기록한다.
관리자 화면에는 통합 감사 로그(`/admin/audit-log/`)와 모델별 이력/복원 화면이 있다.

## 기록 대상

| 모델 | 이력 테이블 | 비고 |
| --- | --- | --- |
| `shop.ShopOrder` | `shop_historicalshoporder` | 주소·메모·송장·상태·금액 등 필드 단위 |
| `users.User_Point` | `users_historicaluser_point` | 포인트 원장 |
| `shop.ShopCouponLog` | `shop_historicalshopcouponlog` | 쿠폰 사용/복원 기록 |
| `config.Config` | `config_historicalconfig` | 실제 설정 이름(`cf_`, `de_`, `shop_`, `pg_`)만 |

- 각 이력 행에는 `history_date`, `history_type`(`+`/`~`/`-`), `history_user`가 저장된다.
- `HistoryRequestMiddleware`가 요청 중 저장되는 이력에 `request.user`를 자동으로 붙인다.
  관리자 화면·관리자 액션·커스텀 설정 화면 모두 해당된다. API/웹훅/배치처럼 request user가
  없는 변경은 `System`으로 표시된다.
- `ShopOrder.od_ip`, `od_vbank_secret_hash`는 이력에서 제외한다. 개인정보/비밀값을 이력
  테이블에 중복 저장하지 않기 위해서다.
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

`ShopOrder` 복원에서 `ORDER_HISTORY_LOCKED_FIELDS`(상태, 결제/환불 금액, `od_misu`,
포인트/쿠폰, 가상계좌 상태 등)는 항상 현재 주문의 값으로 되돌린 뒤 저장한다. 즉 과거
스냅샷의 주소·메모·송장은 복원되지만, 상태와 금액은 복원되지 않고 현재 값이 유지된다.
POST로 보호 필드를 조작해도 서버에서 현재 값으로 덮어쓴다. 상태 변경은 반드시 주문 처리
흐름(상태 변경/취소/반품)을 사용한다.

## 운영

```bash
pip install -r requirements.txt
python manage.py migrate
```

- 이력은 배포 이후 발생한 변경부터 쌓인다. 기존 데이터를 `+` 이력으로 채우면 "모두 오늘
  생성된 것"처럼 보이므로 자동 백필하지 않는다.
- 보관 기간 정책이 필요하면 `Historical*` 테이블에서 `history_date` 기준으로 오래된 행을
  삭제하는 배치를 별도로 둔다. 삭제 전 개인정보 보관 기간과 분쟁 대응 기간을 함께 검토한다.
- 통합 감사 로그는 모델별 최근 500건을 스캔해 최신순으로 합친다. 기간·사용자·모델·검색어
  필터로 범위를 좁혀 사용한다.

## 테스트

`gnu_jango/core/test_audit_history.py`가 다음을 검증한다.

- 네 모델의 생성/수정 이력과 필드 diff
- 주문 이력에서 민감 필드 제외
- 설정 비밀값 마스킹
- 관리자 이력 화면/통합 감사 로그 접근 권한
- 설정 복원, 주문 안전 필드 복원/보호 필드 유지, 포인트 원장 복원 차단
- `HistoryRequestMiddleware`의 `history_user` 기록
