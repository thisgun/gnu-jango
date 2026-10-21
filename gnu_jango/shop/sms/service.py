"""Shop SMS on top of the iCode transport: youngcart's cf_sms_use / cf_sms_type / de_sms_* settings.

``send_message`` is the one entry point for business code. It never raises: a gateway, network or
configuration failure comes back as a rejected / unknown ``ICodeSendResult`` and is logged with
the recipient masked, so an order, a status change or a signup never fails because of a text.
"""

import logging
from dataclasses import dataclass, field

from django.core.cache import cache

from gnu_jango.config.models import Config
from gnu_jango.shop.shop_options import SMS_SLOTS, SMS_TYPE_LMS, SMS_USE_ICODE, shop_options

from . import icode
from .icode import ICodeSendResult

logger = logging.getLogger(__name__)

TEST_SEND_CACHE_KEY = "shop-sms:test-send"
TEST_SEND_INTERVAL_SECONDS = 60
STATUS_LABELS = {"accepted": "접수", "rejected": "실패", "unknown": "확인필요"}


@dataclass(frozen=True)
class SmsSettings:
    enabled: bool = False
    allow_lms: bool = False
    admin_hp: str = ""
    company_name: str = ""
    callback: str = ""
    slots: dict = field(default_factory=dict)

    def slot(self, number):
        """(enabled, template) of youngcart's de_sms_use<number> / de_sms_cont<number>."""
        return self.slots.get(number, (False, ""))


def _sms_option_names():
    names = ["cf_sms_use", "cf_sms_type", "de_sms_hp"]
    for number, _title, _default in SMS_SLOTS:
        names += [f"de_sms_use{number}", f"de_sms_cont{number}"]
    return names


def sms_settings():
    from gnu_jango.shop.models import ShopShippingPolicy

    options = shop_options(*_sms_option_names())
    policy = ShopShippingPolicy.objects.filter(pk=1).only("de_admin_company_name", "de_admin_company_tel").first()
    company_name = str(getattr(policy, "de_admin_company_name", "") or "").strip()
    callback = str(getattr(policy, "de_admin_company_tel", "") or "").strip()
    if not callback:
        callback = str(
            Config.objects.filter(name="de_admin_company_tel").values_list("value", flat=True).first() or ""
        ).strip()
    return SmsSettings(
        enabled=options["cf_sms_use"] == SMS_USE_ICODE,
        allow_lms=options["cf_sms_type"] == SMS_TYPE_LMS,
        admin_hp=options["de_sms_hp"].strip(),
        company_name=company_name,
        callback=callback,
        slots={
            number: (bool(options[f"de_sms_use{number}"]), options[f"de_sms_cont{number}"])
            for number, _title, _default in SMS_SLOTS
        },
    )


def render_template(template, variables):
    """youngcart str_replace of {이름}, {주문번호}, ... in a de_sms_cont text."""
    text = str(template or "")
    for name, value in variables.items():
        text = text.replace("{" + name + "}", str(value if value is not None else ""))
    return text


def mask_phone(value):
    digits = "".join(character for character in str(value or "") if character.isdigit())
    return f"••••{digits[-4:]}" if len(digits) >= 4 else "••••"


def status_label(result):
    return STATUS_LABELS.get(result.status, result.status)


def send_message(recipient, message, *, current=None, subject="", purpose="sms"):
    """Send one text to ``recipient`` with the shop's callback number. Never raises."""
    current = current or sms_settings()
    try:
        result = icode.send_message(
            recipient,
            current.callback,
            message,
            subject=subject or current.company_name,
            allow_lms=current.allow_lms,
        )
    except icode.ICodeConfigurationError as exc:
        result = ICodeSendResult("rejected", "configuration", str(exc))
    except Exception as exc:  # noqa: BLE001 - a text must never break the shop flow
        logger.exception("Shop SMS %s to %s failed unexpectedly", purpose, mask_phone(recipient))
        result = ICodeSendResult("unknown", "unexpected", type(exc).__name__)
    log = logger.info if result.status == "accepted" else logger.warning
    log(
        "Shop SMS %s to %s: %s %s (%s) %s",
        purpose,
        mask_phone(recipient),
        result.message_type,
        result.status,
        result.provider_code,
        result.error_text,
    )
    return result


def operator_test_text(current):
    return f"[{current.company_name or '쇼핑몰'}] 아이코드 SMS 테스트 발송입니다."


def reserve_test_send():
    """True when no test text went out in the last minute (the admin button's throttle)."""
    return cache.add(TEST_SEND_CACHE_KEY, "1", TEST_SEND_INTERVAL_SECONDS)


def send_test_message(recipient=None):
    """The operator's test text, to ``recipient`` or the admin phone (de_sms_hp).

    Sent whether or not cf_sms_use is on, so the credentials can be tried before going live."""
    current = sms_settings()
    return send_message(recipient or current.admin_hp, operator_test_text(current), current=current, purpose="test")
