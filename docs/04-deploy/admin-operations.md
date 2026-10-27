# 관리자 운영 도구

Unfold 관리자에 상품·회원·주문 CSV/XLSX 작업, 운영 KPI, 지원용 impersonation, 주문·배송 일괄 작업을 추가한 구성입니다.

## 1. 상품·회원·주문 가져오기/내보내기

`django-import-export`의 표준 미리보기·확인 화면을 사용합니다. 설치 버전은 `django-import-export==4.4.3`입니다.

| 대상 | 메뉴 | 가져오기 | 내보내기 |
|---|---|---|---|
| 상품 | 쇼핑몰 → 상품 | `add_shopproduct`와 `change_shopproduct` | `view_shopproduct` |
| 회원 | 인증 → 사용자 | 최고 관리자만 | 최고 관리자만 |
| 주문 | 쇼핑몰 → 주문 | 최고 관리자만 | `view_shoporder` + `shop.export_shoporder` |

### 상품

`ShopProductResource`는 상품 코드(`it_id`)를 기준으로 등록·수정합니다. 이미 있는 상품의 `it_stock_qty`를 CSV로 바꾸면 거부하며, 재고는 **재고 일괄조정** 화면을 사용해야 합니다. 이미지·옵션·상세 HTML·판매/조회 카운터는 이 CSV에 포함하지 않습니다. 기존 상품의 이미지·옵션은 기존 도구를 사용하세요. 신규 판매 상품은 가격이 필요하며, 전화문의 상품은 `it_tel_inq=1`을 지정해야 합니다. 판매 중인 기존 상품도 0원으로 바꿀 수 없습니다(전화문의 상품 예외). 기존 행을 가져올 때 파일에 열은 있지만 빈 칸이면 기존 값을 유지합니다. 값을 지우려면 빈 칸이 아니라 명시적인 값을 넣어야 합니다. 기존 행 수정은 파일에 실제로 들어온 열만 `update_fields`로 저장하며, 재고·판매 수·상태·결제 필드는 다시 쓰지 않습니다.

### 회원

`UserResource`는 회원 ID를 기준으로 등록·수정합니다. 새 회원은 사용할 수 없는 비밀번호로 만들어지므로, 본인 확인 후 비밀번호 재설정 흐름으로 로그인하게 해야 합니다. 비밀번호, 직원/최고 관리자 권한, 포인트, 토큰 버전은 CSV로 바꿀 수 없습니다. 기존 관리자 계정이 포함된 행은 거부합니다. 이메일은 형식 검사를 통과해야 하며, 기존 회원 또는 같은 파일 안에서 이미 쓰인 이메일은 거부합니다. 모델 인스턴스 `full_clean` 검증(`clean_model_instances`)을 사용합니다. 기존 회원의 이메일을 바꾸면 기존 JWT 세션을 폐기합니다.

### 주문

주문에는 두 가지 resource가 있습니다.

- **기존 주문 갱신**: `ShopOrderResource`는 주문번호가 이미 존재하는 주문의 받는 사람·연락처·주소·메모·희망일 같은 설명 필드만 수정합니다. 주문 상태·금액·결제 키·배송 등록·변경 이력은 읽기 전용입니다.
- **주문 등록**: `ShopOrderRegistrationResource`는 한 행에 주문 하나와 상품 한 줄을 만들어 **미결제 무통장 주문**으로 등록합니다. 상품 가격·수량으로 금액을 계산하고 재고를 예약합니다. 상품의 최소/최대 구매수량(`it_buy_min_qty`, `it_buy_max_qty`)을 검사하고, 0원 상품은 거부합니다. 온라인 결제, 쿠폰, 포인트, 옵션, 여러 상품으로 이루어진 주문은 지원하지 않습니다. 결제 확인과 상태 전이는 등록 후 기존 주문 액션으로 처리하세요.

가져오기는 `IMPORT_EXPORT_USE_TRANSACTIONS=True`로 실행되고 관리자 로그에 결과가 남습니다. 기존 주문 갱신도 파일에 들어온 열만 저장하며, 빈 칸은 기존 값을 유지합니다. 대량 파일은 먼저 미리보기로 오류 행을 확인한 뒤 확인 단계에서 반영하세요. 내보낸 텍스트 셀이 `=`, `+`, `-`, `@`, 탭, CR로 시작하면 Excel 수식으로 해석되지 않도록 앞에 작은따옴표(`'`)를 붙입니다. 숫자 열은 숫자로 유지합니다. 주문·상품·회원 export는 성공할 때 `LogEntry`에 실행자, 행 수, IP를 기록합니다.

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
- 시작·종료·만료·로그아웃은 `LogEntry`에 실행자, 대상, IP와 함께 감사 기록을 남깁니다.
- 대상의 `last_login`은 바꾸지 않습니다.
- 시작 시 Django 세션을 대상 회원으로 전환하고, 짧은 수명의 회원 access 쿠키만 발급합니다. refresh 쿠키는 발급하지 않습니다.
- 지원 세션은 **읽기 전용**입니다. `POST`/`PUT`/`PATCH`/`DELETE` API 요청은 `ImpersonationReadOnlyMiddleware`가 거부합니다. JWT access token에 `imp` claim을 넣어 session이 없는 token-only 요청도 차단합니다. 회원 데이터를 바꾸려면 지원 세션을 종료한 뒤 관리자 계정으로 수행하세요.
- **지원 세션은 30분 후 만료**되지만, 발급되는 회원 access token의 수명은 기본 설정상 **15분**입니다. 따라서 쇼핑몰 화면의 로그인 상태는 보통 15분에 끊기고, `/impersonation/` 종료 페이지는 최대 30분까지 유지됩니다. 두 수명은 서로 다른 설정이며, 30분을 쇼핑몰 로그인 유지 시간으로 오해하지 마세요.
- **비밀번호 없는 로그아웃**도 허용됩니다. 지원 세션 중 `POST /impersonation/logout/` 또는 관리자 로그아웃(`POST /admin/logout/`)을 사용하면 관리자 비밀번호 없이 종료되며, refresh token jti 폐기와 storefront 쿠키 삭제도 함께 수행합니다. 비밀번호를 모르는 관리자가 갇히지 않도록 하기 위한 경로입니다.
- 비밀번호로 종료할 때는 **관리자 비밀번호 재확인**이 필요합니다. 틀린 비밀번호가 5회 누적되면 지원 세션을 강제 종료하고 refresh token을 폐기합니다. 관리자 Django 세션은 복원되지만 브라우저의 storefront 인증 쿠키는 지워지므로 storefront는 다시 로그인해야 합니다. 발급한 refresh token은 jti 기준으로 폐기하며 원문 token은 session에 저장하지 않습니다.
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

주문 export 전용 권한은 `shop.0038_export_shoporder_permission` 마이그레이션에서 생성됩니다. 운영 배포 시 마이그레이션을 적용한 뒤, 주문 export가 필요한 staff 그룹에 `shop.view_shoporder`와 `shop.export_shoporder`를 함께 부여하세요. 실제 운영 전에는 최고 관리자·일반 회원·준비 상태 주문을 각각 하나씩 준비해 가져오기 미리보기, 내보내기(권한별 403 포함), 지원 세션 시작·종료·로그아웃을 확인하세요.
