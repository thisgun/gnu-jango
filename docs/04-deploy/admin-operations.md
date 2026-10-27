# 관리자 운영 도구

Unfold 관리자에 상품·회원·주문 CSV/XLSX 작업, 운영 KPI, 지원용 impersonation, 주문·배송 일괄 작업을 추가한 구성입니다.

## 1. 상품·회원·주문 가져오기/내보내기

`django-import-export`의 표준 미리보기·확인 화면을 사용합니다. 설치 버전은 `django-import-export==4.4.3`입니다.

| 대상 | 메뉴 | 가져오기 | 내보내기 |
|---|---|---|---|
| 상품 | 쇼핑몰 → 상품 | `add_shopproduct`와 `change_shopproduct` | `view_shopproduct` |
| 회원 | 인증 → 사용자 | 최고 관리자만 | 최고 관리자만 |
| 주문 | 쇼핑몰 → 주문 | 최고 관리자만 | `view_shoporder` |

### 상품

`ShopProductResource`는 상품 코드(`it_id`)를 기준으로 등록·수정합니다. 이미 있는 상품의 `it_stock_qty`를 CSV로 바꾸면 거부하며, 재고는 **재고 일괄조정** 화면을 사용해야 합니다. 이미지·옵션·상세 HTML·판매/조회 카운터는 이 CSV에 포함하지 않습니다. 기존 상품의 이미지·옵션은 기존 도구를 사용하세요.

### 회원

`UserResource`는 회원 ID를 기준으로 등록·수정합니다. 새 회원은 사용할 수 없는 비밀번호로 만들어지므로, 본인 확인 후 비밀번호 재설정 흐름으로 로그인하게 해야 합니다. 비밀번호, 직원/최고 관리자 권한, 포인트, 토큰 버전은 CSV로 바꿀 수 없습니다. 기존 관리자 계정이 포함된 행은 거부합니다. 기존 회원의 이메일을 바꾸면 기존 JWT 세션을 폐기합니다.

### 주문

`ShopOrderResource`는 주문번호가 **이미 존재하는 주문**만 수정합니다. 받는 사람·연락처·주소·메모·희망일 같은 설명 필드만 가져오며, 주문 상태·금액·결제 키·배송 등록·변경 이력은 읽기 전용입니다. 상태 변경은 주문 일괄 액션, 배송 등록은 배송 일괄등록/배송 액션을 사용하세요. 없는 주문번호는 새 주문을 만들지 않고 오류로 남깁니다.

가져오기는 `IMPORT_EXPORT_USE_TRANSACTIONS=True`로 실행되고 관리자 로그에 결과가 남습니다. 대량 파일은 먼저 미리보기로 오류 행을 확인한 뒤 확인 단계에서 반영하세요. 내보낸 셀의 선행 `=`, `+`, `-`, `@`는 Excel 수식으로 해석되지 않도록 이스케이프합니다.

## 2. 관리자 대시보드 KPI

`/admin/` 대시보드에 기존 주문·회원·정산 지표와 함께 다음 지표를 표시합니다.

- **Today sales**: 오늘 주문의 순수령액(수령액 - 환불액)
- **Today orders**: 오늘 주문 수와 수령액
- **Low stock**: 판매 중이고 재고가 5 이하인 상품 수(품절 수 포함)
- **Today members**: 오늘 가입 회원과 활성 회원

대시보드 요약은 60초 캐시를 사용합니다. 링크는 기존 주문·재고·회원 운영 화면으로 이동합니다.

## 3. 지원용 impersonation

회원 변경 화면의 **View as this member** 버튼으로 시작합니다.

- **최고 관리자만** 시작할 수 있습니다.
- 대상은 활성 상태의 일반 회원이어야 하며, 직원·최고 관리자·본인은 대상이 될 수 없습니다.
- 시작과 종료는 `LogEntry`에 감사 기록을 남깁니다.
- 대상의 `last_login`은 바꾸지 않습니다.
- 시작 시 Django 세션을 대상 회원으로 전환하고, 짧은 수명의 회원 access 쿠키만 발급합니다. refresh 쿠키는 발급하지 않습니다.
- 지원 세션은 **읽기 전용**입니다. `POST`/`PUT`/`PATCH`/`DELETE` API 요청은 `ImpersonationReadOnlyMiddleware`가 거부합니다. 회원 데이터를 바꾸려면 지원 세션을 종료한 뒤 관리자 계정으로 수행하세요.
- 종료는 `/impersonation/` 페이지의 **Stop impersonation** 버튼 또는 `POST /impersonation/stop/`입니다. 종료하면 관리자 세션과 이전 인증 쿠키를 복원하고, 발급한 refresh 토큰은 폐기합니다.
- 운영자는 지원 세션을 공유 브라우저에 남기지 말고, 작업 후 반드시 종료하세요.

## 4. 주문·배송 일괄 작업

주문 목록의 액션에서 다음을 사용할 수 있습니다.

- **선택 주문 상태 변경**: 기존 주문 상태 전이·재고·쿠폰·포인트·PG 환불 규칙을 그대로 적용합니다.
- **Register carrier and invoice for selected orders**: 선택한 준비 상태 주문에 배송회사와 운송장 번호를 넣고 배송 상태로 이동합니다. 배송 안내 SMS는 체크한 경우에만 발송합니다.
- 기존 **배송 일괄등록** 화면은 CSV/XLSX 파일로 여러 주문을 처리할 때 계속 사용할 수 있습니다.

## 5. 점검 명령

```bash
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py test gnu_jango.core.test_admin_import_export gnu_jango.core.test_admin_impersonation gnu_jango.core.test_admin_ported_from_next
```

`django-import-export`는 별도 마이그레이션을 만들지 않습니다. 실제 운영 전에는 최고 관리자·일반 회원·준비 상태 주문을 각각 하나씩 준비해 가져오기 미리보기, 내보내기, 지원 세션 시작·종료를 확인하세요.
