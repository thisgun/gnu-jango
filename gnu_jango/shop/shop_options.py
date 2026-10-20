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
    kind: str = "text"  # text | email | bool | int | html
    default: str = ""
    help_text: str = ""
    max_length: int = 255
    min_value: int = 0
    max_value: int | None = None


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
                 help_text="켜면 비회원 장바구니를 보관기간 동안 쿠키로 유지합니다. 끄면 브라우저 세션이 끝나면 비워집니다."),
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
    ConfigOption("de_search_list_row", "검색결과 줄 수", kind="int", default="4", min_value=1, max_value=20,
                 help_text="한 페이지 상품 수는 PC 1줄당 상품 수 × 줄 수입니다."),
    ConfigOption("de_mobile_search_list_mod", "검색결과 1줄당 상품 수 (모바일)", kind="int", default="2",
                 min_value=1, max_value=4),
    ConfigOption("de_listtype_list_mod", "유형별 목록 1줄당 상품 수 (PC)", kind="int", default="5",
                 min_value=1, max_value=8),
    ConfigOption("de_listtype_list_row", "유형별 목록 줄 수", kind="int", default="4", min_value=1, max_value=20,
                 help_text="히트·추천·최신·인기·할인 상품 전체 목록 한 페이지의 줄 수입니다."),
    ConfigOption("de_mobile_listtype_list_mod", "유형별 목록 1줄당 상품 수 (모바일)", kind="int", default="2",
                 min_value=1, max_value=4),
)

SHOP_CONFIG_OPTIONS = {
    option.name: option
    for option in (*COMPANY_OPTIONS, *ORDER_OPTIONS, *POINT_OPTIONS, *HOME_LIST_OPTIONS, *LIST_OPTIONS)
}

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
