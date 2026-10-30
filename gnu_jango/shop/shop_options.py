"""Youngcart shop settings kept as Config rows, with youngcart's install defaults.

The admin shop settings form builds its fields from ``SHOP_CONFIG_OPTIONS`` and
runtime code reads the typed values with ``shop_options()``. A missing row means
the youngcart default, so existing installations behave as before until an
administrator saves a different value.
"""

import logging
from dataclasses import dataclass

from gnu_jango.config.models import Config

from .payment_options import config_flag

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigOption:
    name: str
    label: str
    kind: str = "text"  # text | email | bool | int | html | textarea | choice
    default: str = ""
    help_text: str = ""
    max_length: int = 255
    min_value: int = 0
    max_value: int | None = None
    choices: tuple = ()  # (value, label) pairs of a "choice" option


COMPANY_OPTIONS = (
    ConfigOption("cf_company_owner", "대표자명"),
    ConfigOption("cf_company_biz_no", "사업자등록번호", max_length=64),
    ConfigOption("cf_company_tongsin_no", "통신판매업 신고번호", max_length=128),
    ConfigOption("cf_company_buga_no", "부가통신 사업자번호", max_length=128,
                 help_text="값이 있을 때만 쇼핑몰 하단에 표시합니다."),
    ConfigOption("cf_company_fax", "팩스번호", max_length=64),
    ConfigOption("cf_company_zip", "사업장 우편번호", max_length=16),
    ConfigOption("cf_company_addr", "사업장 주소"),
    ConfigOption("cf_company_info_name", "정보관리책임자명"),
    ConfigOption("cf_company_email", "정보책임자 이메일", kind="email"),
)

ORDER_OPTIONS = (
    ConfigOption("de_guest_cart_use", "비회원 장바구니 유지", kind="bool", default="0",
                 help_text="켜면 비회원 장바구니를 보관기간 동안 유지합니다. 끄면 사이트를 3시간 이상 이용하지 않을 때 비워집니다."),
    ConfigOption("de_cart_keep_term", "장바구니 보관기간 (일)", kind="int", default="15", min_value=1, max_value=365,
                 help_text="담은 지 이 기간이 지난 상품은 장바구니에서 자동으로 빠집니다."),
    ConfigOption("de_hope_date_use", "희망배송일 사용", kind="bool", default="0",
                 help_text="켜면 주문서에서 희망배송일을 반드시 고르게 합니다."),
    ConfigOption("de_hope_date_after", "희망배송일 지정 시작 (일)", kind="int", default="3", max_value=60,
                 help_text="오늘부터 이 일수가 지난 날부터 7일 동안 고를 수 있습니다."),
    ConfigOption("de_guest_privacy", "비회원 개인정보 수집 안내", kind="html", max_length=20000,
                 help_text="비회원 주문서의 개인정보 수집 동의 항목 위에 표시합니다. 비워 두면 동의 항목만 표시합니다."),
)

POINT_OPTIONS = (
    ConfigOption("de_card_point", "PG 결제 주문에도 구매 포인트 지급", kind="bool", default="0",
                 help_text="끄면 카드·계좌이체·휴대폰·간편결제 주문은 구매 포인트를 적립하지 않습니다. "
                           "무통장입금·가상계좌 주문은 항상 적립합니다."),
    ConfigOption("de_point_days", "구매 포인트 지급 대기일", kind="int", default="7", max_value=365,
                 help_text="주문 상품이 완료 상태가 된 뒤 이 일수가 지나면 지급합니다. 0이면 완료하는 즉시 지급합니다."),
    ConfigOption("de_member_reg_coupon_use", "신규회원 쿠폰 발행", kind="bool", default="0",
                 help_text="회원가입을 마친 회원에게 금액 할인 쿠폰을 한 장 발행합니다."),
    ConfigOption("de_member_reg_coupon_price", "쿠폰 할인금액 (원)", kind="int", default="0", max_value=10_000_000),
    ConfigOption("de_member_reg_coupon_minimum", "쿠폰 주문 최소금액 (원)", kind="int", default="0",
                 max_value=100_000_000),
    ConfigOption("de_member_reg_coupon_term", "쿠폰 유효기간 (일)", kind="int", default="0", max_value=3650),
)

# 정기구독 (shop/subscriptions.py): off until the admin turns it on. The server must also allow it
# (SHOP_SUBSCRIPTIONS_ENABLED), which registers the daily charge job.
SUBSCRIPTION_OPTIONS = (
    ConfigOption("de_subscription_use", "정기구독 사용", kind="bool", default="0",
                 help_text="켜면 '정기구독 가능'으로 설정한 상품을 회원이 카드 자동결제로 정기구독할 수 있습니다. "
                           "토스페이먼츠 자동결제(빌링) 계약과 서버 설정 SHOP_SUBSCRIPTIONS_ENABLED=True가 필요합니다."),
    ConfigOption("de_subscription_notice_days", "결제 예정 안내 (일 전)", kind="int", default="3", min_value=1,
                 max_value=14, help_text="결제일 이 일수 전에 회원에게 결제 예정 메일과 알림을 보냅니다."),
    ConfigOption("de_subscription_retry_limit", "결제 실패 시 시도 횟수", kind="int", default="3", min_value=1,
                 max_value=7, help_text="결제가 실패하면 다음 날 다시 시도합니다. 이 횟수만큼 실패하면 구독을 일시정지하고 회원에게 알립니다."),
)

# Customer return / exchange requests (shop/returns.py)
RETURN_OPTIONS = (
    ConfigOption("de_return_request_use", "반품·교환 신청 사용", kind="bool", default="1",
                 help_text="켜면 고객이 배송된 상품을 주문 상세에서 반품·교환 신청할 수 있습니다. 끄면 신청 버튼을 숨기고 새 신청을 받지 않습니다."),
    ConfigOption("de_return_request_days", "반품·교환 신청 기간 (일)", kind="int", default="7", min_value=1, max_value=365,
                 help_text="상품이 배송완료(완료)된 때부터 이 일수 동안 신청할 수 있습니다. 배송중인 상품은 언제든 신청할 수 있습니다."),
    ConfigOption("de_return_shipping_fee", "단순변심 반품 배송비 (원)", kind="int", default="0", max_value=1_000_000,
                 help_text="단순변심 반품을 완료할 때 환불금액에서 빼는 반품 배송비입니다. 완료 화면에서 건마다 바꿀 수 있고, 환불금액보다 많이 빼지 않습니다."),
)

# 알림·장바구니 메일 (gnu_jango/shop/price_alerts.py, restock.py, cart_reminders.py): sent by the
# send_shop_alerts scheduled job. Everything is off until the shop turns it on.
ALERT_OPTIONS = (
    ConfigOption("de_price_alert_use", "가격 인하 알림", kind="bool", default="0",
                 help_text="켜면 회원이 상품 페이지에서 가격 인하 알림을 신청할 수 있고, 신청했을 때보다 가격이 내려가면 "
                           "메일과 사이트 알림으로 한 번 알려 줍니다."),
    ConfigOption("de_stock_sms_auto", "재입고 SMS 자동 발송", kind="bool", default="0",
                 help_text="켜면 재고가 다시 생긴 상품의 재입고 알림 신청자에게 SMS를 자동으로 보냅니다(한 번에 25건). "
                           "한 번 보내려고 했던 신청은 자동으로 다시 보내지 않으니, 실패한 건은 재입고 알림 목록에서 직접 보내세요."),
    ConfigOption("de_cart_reminder_use", "장바구니 알림 메일", kind="bool", default="0",
                 help_text="상품을 담아 두고 주문하지 않은 회원에게 알림 메일을 보냅니다. 광고성 정보이므로 정보 메일 수신에 "
                           "동의한 회원에게만 보내고 제목에 (광고)를 붙입니다. 한 회원에게는 7일에 한 번까지만 보냅니다."),
    ConfigOption("de_cart_reminder_hours", "장바구니 알림 대기 시간 (시간)", kind="int", default="24", min_value=1,
                 max_value=720, help_text="마지막으로 상품을 담은 뒤 이 시간이 지나도 주문하지 않으면 보냅니다."),
    ConfigOption("de_cart_reminder_coupon_price", "알림 쿠폰 할인금액 (원)", kind="int", default="0", max_value=10_000_000,
                 help_text="0이면 쿠폰 없이 메일만 보냅니다. 회원에게 아직 쓰지 않은 알림 쿠폰이 있으면 새로 발행하지 않습니다."),
    ConfigOption("de_cart_reminder_coupon_minimum", "알림 쿠폰 주문 최소금액 (원)", kind="int", default="0",
                 max_value=100_000_000),
    ConfigOption("de_cart_reminder_coupon_term", "알림 쿠폰 유효기간 (일)", kind="int", default="7", min_value=1,
                 max_value=365),
)

HOME_LIST_TYPES = (
    (1, "히트상품"),
    (2, "추천상품"),
    (3, "최신상품"),
    (4, "인기상품"),
    (5, "할인상품"),
)


def _home_list_options():
    options = []
    for number, title in HOME_LIST_TYPES:
        prefix = f"de_type{number}"
        mobile = f"de_mobile_type{number}"
        options += [
            ConfigOption(f"{prefix}_list_use", f"{title} 출력", kind="bool", default="1"),
            ConfigOption(f"{prefix}_list_mod", f"{title} 1줄당 상품 수 (PC)", kind="int", default="5",
                         min_value=1, max_value=8),
            ConfigOption(f"{prefix}_list_row", f"{title} 줄 수 (PC)", kind="int", default="2",
                         min_value=1, max_value=10),
            ConfigOption(f"{mobile}_list_mod", f"{title} 1줄당 상품 수 (모바일)", kind="int", default="2",
                         min_value=1, max_value=4),
            ConfigOption(f"{mobile}_list_row", f"{title} 줄 수 (모바일)", kind="int", default="4",
                         min_value=1, max_value=10),
        ]
    return tuple(options)


HOME_LIST_OPTIONS = _home_list_options()

LIST_OPTIONS = (
    ConfigOption("de_rel_list_use", "관련상품 출력", kind="bool", default="1"),
    ConfigOption("de_rel_list_mod", "관련상품 1줄당 상품 수 (PC)", kind="int", default="4", min_value=1, max_value=8),
    ConfigOption("de_mobile_rel_list_mod", "관련상품 1줄당 상품 수 (모바일)", kind="int", default="2",
                 min_value=1, max_value=4),
    ConfigOption("de_search_list_mod", "검색결과 1줄당 상품 수 (PC)", kind="int", default="5", min_value=1, max_value=8),
    ConfigOption("de_search_list_row", "검색결과 줄 수", kind="int", default="4", min_value=1, max_value=12,
                 help_text="한 페이지 상품 수는 PC 1줄당 상품 수 × 줄 수입니다."),
    ConfigOption("de_mobile_search_list_mod", "검색결과 1줄당 상품 수 (모바일)", kind="int", default="2",
                 min_value=1, max_value=4),
    ConfigOption("de_listtype_list_mod", "유형별 목록 1줄당 상품 수 (PC)", kind="int", default="5",
                 min_value=1, max_value=8),
    ConfigOption("de_listtype_list_row", "유형별 목록 줄 수", kind="int", default="4", min_value=1, max_value=12,
                 help_text="히트·추천·최신·인기·할인 상품 전체 목록 한 페이지의 줄 수입니다."),
    ConfigOption("de_mobile_listtype_list_mod", "유형별 목록 1줄당 상품 수 (모바일)", kind="int", default="2",
                 min_value=1, max_value=4),
)

# Delivery Tracker shipment tracking (shop/delivery_tracking.py). Not youngcart settings: the
# names are new, so the gnuboard import never fills them. The API keys are separate sealed rows
# (shop/delivery_tracking_settings.py).
TRACKING_OPTIONS = (
    ConfigOption("de_tracking_use", "배송조회 사용", kind="bool", default="0",
                 help_text="켜면 배송 중인 주문의 배송 상태를 Delivery Tracker에서 조회해 주문 상세에 표시합니다. "
                           "Client ID와 Client Secret을 모두 등록해야 동작하며, 그 전에는 배송 조회 링크만 표시합니다."),
    ConfigOption("de_tracking_complete_delivered", "배송완료 시 주문 완료 처리", kind="bool", default="0",
                 help_text="켜면 배송완료가 확인된 배송 상태의 주문을 '완료'로 바꾸고 고객에게 배송완료 메일을 보냅니다. "
                           "구매 포인트 지급과 주문 이력은 관리자가 완료 처리할 때와 같습니다."),
)

SHOP_CONFIG_OPTIONS = {
    option.name: option
    for option in (
        *COMPANY_OPTIONS, *ORDER_OPTIONS, *POINT_OPTIONS, *SUBSCRIPTION_OPTIONS, *RETURN_OPTIONS, *ALERT_OPTIONS,
        *HOME_LIST_OPTIONS, *LIST_OPTIONS, *TRACKING_OPTIONS,
    )
}

# adm/shop_admin/configform.php SMS 설정 (cf_sms_use, cf_sms_type, de_sms_hp, de_sms_use1..5 and
# de_sms_cont1..5 with youngcart's install texts). The iCode credentials are never a Config row:
# they come from the server environment (G5_ICODE_TOKEN_KEY or G5_ICODE_ID / G5_ICODE_PASSWORD).
SMS_SLOTS = (
    (1, "회원가입시 고객님께 발송", "{이름}님의 회원가입을 축하드립니다.\nID:{회원아이디}\n{회사명}"),
    (2, "주문시 고객님께 발송", "{이름}님 주문해주셔서 고맙습니다.\n{주문번호}\n{주문금액}원\n{회사명}"),
    (3, "주문시 관리자에게 발송", "{이름}님께서 주문하셨습니다.\n{주문번호}\n{주문금액}원\n{회사명}"),
    (4, "입금확인시 고객님께 발송", "{이름}님 입금 감사합니다.\n{입금액}원\n주문번호:\n{주문번호}\n{회사명}"),
    (5, "상품배송시 고객님께 발송", "{이름}님 배송합니다.\n택배:{택배회사}\n운송장번호:\n{운송장번호}\n{회사명}"),
)
SMS_SLOT_VARIABLES = {
    1: "{이름} {회원아이디} {회사명}",
    2: "{이름} {보낸분} {받는분} {주문번호} {주문금액} {회원아이디} {회사명}",
    3: "{이름} {보낸분} {받는분} {주문번호} {주문금액} {회원아이디} {회사명}",
    4: "{이름} {입금액} {주문번호} {회사명}",
    5: "{이름} {택배회사} {운송장번호} {주문번호} {회사명}",
}
SMS_USE_ICODE = "icode"
SMS_TYPE_LMS = "LMS"


def _sms_options():
    options = [
        ConfigOption("cf_sms_use", "SMS 사용", kind="choice", choices=(("", "사용안함"), (SMS_USE_ICODE, "아이코드")),
                     help_text="아이코드를 고르면 아래에서 켠 항목의 문자를 보냅니다. 아이코드 인증 정보는 서버 환경 변수로만 등록합니다."),
        ConfigOption("cf_sms_type", "SMS 전송유형", kind="choice", choices=(("", "SMS"), (SMS_TYPE_LMS, "LMS")),
                     help_text="SMS는 90바이트(구버전 아이디·비밀번호 방식은 80바이트)까지 보내고 나머지는 잘립니다. "
                               "LMS는 90바이트 이하는 SMS로, 그보다 길면 2,000바이트까지 LMS로 보냅니다(토큰키 방식만 지원). "
                               "요금은 건당 SMS 16원, LMS 48원입니다."),
        ConfigOption("de_sms_hp", "관리자 휴대폰번호", max_length=20,
                     help_text="주문서 작성시 쇼핑몰 관리자가 문자를 받을 휴대폰번호입니다. 테스트 발송도 이 번호로 보냅니다."),
    ]
    for number, title, default in SMS_SLOTS:
        options += [
            ConfigOption(f"de_sms_use{number}", f"{title} 사용", kind="bool", default="0"),
            ConfigOption(f"de_sms_cont{number}", f"{title} 내용", kind="textarea", default=default, max_length=2000,
                         help_text=f"사용 가능한 변수: {SMS_SLOT_VARIABLES[number]}"),
        ]
    return tuple(options)


SMS_OPTIONS = _sms_options()
SHOP_CONFIG_OPTIONS.update((option.name, option) for option in SMS_OPTIONS)

# Uploaded shop logos: Config row name -> label. The row holds the storage name.
SHOP_LOGO_FIELDS = {
    "de_logo_img": "상단 로고",
    "de_logo_img2": "하단 로고",
    "de_mobile_logo_img": "모바일 상단 로고",
    "de_mobile_logo_img2": "모바일 하단 로고",
}


def to_python(option, raw):
    """Convert a stored Config string (or None for a missing row) to its typed value."""
    value = option.default if raw is None else raw
    if option.kind == "bool":
        return config_flag(value)
    if option.kind == "int":
        try:
            number = int(str(value).strip() or option.default or 0)
        except (TypeError, ValueError):
            number = int(option.default or 0)
        number = max(option.min_value, number)
        return number if option.max_value is None else min(option.max_value, number)
    if option.kind == "choice":
        value = str(value or "")
        return value if value in {key for key, _ in option.choices} else option.default
    return str(value or "")


def to_stored(option, value):
    if option.kind == "bool":
        return "1" if value else "0"
    if option.kind == "int":
        return str(int(value))
    return str(value or "")


def shop_options(*names):
    """Typed values for the given option names (all options when none are given)."""
    selected = [SHOP_CONFIG_OPTIONS[name] for name in (names or SHOP_CONFIG_OPTIONS)]
    stored = dict(
        Config.objects.filter(name__in=[option.name for option in selected]).values_list("name", "value")
    )
    return {option.name: to_python(option, stored.get(option.name)) for option in selected}


def shop_option(name):
    return shop_options(name)[name]


def shop_logo_urls():
    """Public URLs of the uploaded shop logos; a logo that is not uploaded maps to ""."""
    from django.core.files.storage import default_storage

    stored = dict(Config.objects.filter(name__in=SHOP_LOGO_FIELDS).values_list("name", "value"))
    urls = {}
    for name in SHOP_LOGO_FIELDS:
        path = str(stored.get(name) or "").strip()
        try:
            urls[name] = default_storage.url(path) if path else ""
        except Exception:  # noqa: BLE001 - a broken storage must not break public settings
            logger.warning("Could not build the URL of shop logo %s.", name, exc_info=True)
            urls[name] = ""
    return urls
