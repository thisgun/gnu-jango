# 배송조회 (Delivery Tracker) 운영 설정

배송 중인 주문의 배송 상태를 [Delivery Tracker](https://tracker.delivery)에서 받아 고객 주문 상세에 타임라인으로, 관리자 주문 화면에 조회 상태로 보여 줍니다. 기본은 꺼져 있고, 꺼져 있거나 키가 없으면 지금처럼 배송회사 조회 링크만 표시합니다.

## 1. 키 발급

1. [Delivery Tracker 콘솔](https://console.tracker.delivery)에 가입하고 프로젝트를 만듭니다.
2. 프로젝트의 API 키에서 **Client ID**와 **Client Secret**을 발급합니다. 2024-05-13 이전에 만든 Client ID는 API 키 방식으로 쓸 수 없으니 새로 발급하세요.
3. 요금제와 호출 한도는 콘솔에서 확인합니다. 이 사이트는 주문 한 건을 조회할 때 `track` 한 번, 웹훅을 쓰면 하루 한 번 정도 `registerTrackWebhook`을 더 호출합니다.

## 2. 켜기

관리자 > 쇼핑몰 설정 > 배송설정 > **배송조회 (Delivery Tracker)**

| 항목 | 설명 |
|---|---|
| 배송조회 사용 | 켜야 조회합니다. Client ID와 Client Secret을 모두 등록해야 동작합니다. |
| Client ID / Client Secret | 암호화해 저장하고 다시 표시하지 않습니다(Client ID는 끝 4자리만). 바꿀 때만 입력하고, 지울 때는 삭제를 체크합니다. `SECRET_KEY`를 바꾸면 다시 입력해야 합니다(`SECRET_KEY_FALLBACKS`에 옛 키를 두면 그대로 열립니다). |
| 배송완료 시 주문 완료 처리 | 기본 꺼짐. 켜면 배송완료가 확인된 **배송** 상태 주문을 **완료**로 바꾸고 고객에게 배송완료 메일을 보냅니다. 관리자가 상태를 바꿀 때와 같은 경로(`order_flow.move_order_status`)라 주문 상품 상태, 구매 포인트, 판매 수량, 주문 처리 이력이 함께 반영됩니다. |

자동 조회 예약 작업은 서버 환경 변수로 켭니다.

```dotenv
SHOP_DELIVERY_TRACKING_JOB=True
# 웹훅을 받을 공개 https 주소 (비우면 SOCIAL_APP_BASE_URL)
SHOP_DELIVERY_TRACKER_CALLBACK_BASE_URL=https://shop.example.com
```

`SHOP_DELIVERY_TRACKING_JOB`이 꺼져 있으면 관리자 주문 화면의 **지금 조회**로만 조회합니다.

## 3. 조회 대상과 주기

`manage.py track_shipments` (예약 작업 `run_scheduled_jobs`, 5분마다, 한 번에 30건, 약 45초 안에서)가 다음 주문을 조회합니다.

- 주문 상태가 **배송**이고 운송장번호가 있으며, 배송회사가 Delivery Tracker 택배사 코드와 연결된 주문 (`gnu_jango/shop/delivery.py`의 `DELIVERY_TRACKER_CARRIERS`. 우리택배는 코드가 불분명해 링크만 표시)
- 처음 조회하는 주문, 배송회사·운송장번호가 바뀐 주문(처음부터 다시 조회), 웹훅이 알린 주문이 먼저입니다.
- 다음 조회: 이동 중이면 3시간 뒤(웹훅 등록 시 12시간 뒤), 택배사에 아직 운송장이 없으면(NOT_FOUND) 6시간 뒤, 오류면 30분부터 두 배씩 최대 24시간.
- 배송완료가 확인되거나 조회를 시작한 지 30일이 지나면 자동 조회를 멈춥니다.
- 같은 배송은 30초 안에 다시 조회하지 않고, 두 작업이 겹치면 먼저 집은 쪽만 조회합니다.
- 배송완료로 확인됐는데 주문 완료 처리를 못 했으면(나중에 스위치를 켠 경우 포함) 다음 실행에서 다시 조회하지 않고 완료 처리만 합니다.

```powershell
python manage.py track_shipments --json          # 조회할 주문만 보기 (dry-run)
python manage.py track_shipments --apply --json  # 실제 조회
```

## 4. 웹훅

공개 https 주소가 있으면 조회를 시작할 때 `registerTrackWebhook`으로 48시간짜리 웹훅을 등록하고, 남은 시간이 하루 아래로 내려가면 연장합니다. Delivery Tracker는 상태가 바뀌면 다음 주소로 `{"carrierId", "trackingNumber"}`만 POST합니다.

```text
https://<공개-도메인>/api/v1/shop/delivery-tracker/webhook/<사이트 토큰>
```

- 콜백에는 서명이 없어서(공식 문서) 주소에 `SECRET_KEY`에서 만든 사이트 토큰을 넣고, 토큰이 틀리면 404로 답합니다. 주소별 분당 600회로 제한합니다. 토큰은 URL 경로에 있으므로 프록시 접근 로그에 남지 않게 하거나 로그 접근을 제한하세요(`SECRET_KEY`를 바꾸면 토큰도 바뀌고, 웹훅은 다음 조회 때 새 주소로 다시 등록됩니다).
- 받은 내용으로 상태를 바꾸지 않습니다. 해당 배송을 "지금 조회할 대상"으로 표시만 하고 202로 바로 답하며, 다음 예약 작업이 Delivery Tracker에 직접 다시 조회합니다.
- http 주소만 있으면 웹훅을 등록하지 않고 예약 작업의 주기 조회만 합니다.

## 5. 확인

- 관리자 주문 화면의 **배송조회** 칸: 상태, 마지막 이벤트·조회 시각, 다음 자동 조회, 웹훅 만료, 최근 이벤트 5개, 마지막 오류. **지금 조회**는 그 자리에서 한 번 조회합니다.
- 키 오류(UNAUTHENTICATED/FORBIDDEN)는 주문의 마지막 오류에 남고 백오프로 다시 시도합니다. 키를 고친 뒤 **지금 조회**로 확인하세요.
- 고객 주문 상세: 송장 정보 아래에 현재 상태와 배송 진행 내역(최신 순, 5건 뒤는 펼치기). 배송 조회 링크는 그대로 있습니다.
