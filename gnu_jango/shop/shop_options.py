"""Youngcart shop settings kept as Config rows, with youngcart's install defaults.

The admin shop settings form builds its fields from ``SHOP_CONFIG_OPTIONS`` and
runtime code reads the typed values with ``shop_options()``. A missing row means
the youngcart default, so existing installations behave as before until an
administrator saves a different value.
"""

from dataclasses import dataclass

from gnu_jango.config.models import Config

from .payment_options import config_flag


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

SHOP_CONFIG_OPTIONS = {option.name: option for option in (*COMPANY_OPTIONS,)}


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
