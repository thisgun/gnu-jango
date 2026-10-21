"""Shop SMS on top of the iCode transport: youngcart's cf_sms_use / cf_sms_type / de_sms_* settings.

``send_message`` is the one entry point for business code. It never raises: a gateway, network or
configuration failure comes back as a rejected / unknown ``ICodeSendResult`` and is logged with
the recipient masked, so an order, a status change or a signup never fails because of a text.

Every text passes ``_send_guard`` first, so all callers (guest checkout, signup, Toss confirm,
status moves, restock alerts) share the same limits: a per-recipient and a site-wide hourly cap
and a circuit breaker that skips the gateway for a while after a connect/read timeout. Texts stay
synchronous (on_commit on the request thread) on purpose: a background thread is not reliable on
Vercel, which may freeze the function once the response is sent, and a queue would need a worker
the VPS profile does not have. Tight socket timeouts (icode.py) plus the breaker bound the delay
instead: at most one slow attempt per breaker window.
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field

from django.conf import settings
from django.core.cache import cache

from gnu_jango.config.models import Config
from gnu_jango.shop.shop_options import SMS_SLOTS, SMS_TYPE_LMS, SMS_USE_ICODE, shop_options

from . import icode
from .icode import ICodeSendResult

logger = logging.getLogger(__name__)

TEST_SEND_CACHE_KEY = "shop-sms:test-send"
TEST_SEND_INTERVAL_SECONDS = 60
BREAKER_CACHE_KEY = "shop-sms:breaker"
GLOBAL_COUNT_KEY = "shop-sms:sent:{bucket}"
RECIPIENT_COUNT_KEY = "shop-sms:to:{digest}:{bucket}"
WINDOW_SECONDS = 3600
DEFAULT_RECIPIENT_HOURLY_LIMIT = 5
DEFAULT_HOURLY_LIMIT = 300
DEFAULT_BREAKER_SECONDS = 300
# transport failures that mean the gateway is unreachable or hanging (icode._exchange)
BREAKER_CODES = {"connect_timeout", "timeout", "socket_error"}
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


def _int_setting(name, default):
    try:
        return int(getattr(settings, name, default))
    except (TypeError, ValueError):
        return default


def _phone_key(value):
    return "".join(character for character in str(value or "") if character.isdigit())


def _count_send(key, limit):
    """Add one to ``key``'s hourly counter; False once it is past ``limit`` (0 or less: no limit)."""
    if limit <= 0:
        return True
    cache.add(key, 0, WINDOW_SECONDS + 60)
    try:
        count = cache.incr(key)
    except ValueError:  # expired between add and incr
        cache.add(key, 1, WINDOW_SECONDS + 60)
        count = 1
    return count <= limit


def _send_guard(recipient, current, *, check_breaker=True):
    """A rejected result when this text must not go out (breaker open, a cap reached), else None."""
    if check_breaker and cache.get(BREAKER_CACHE_KEY):
        return ICodeSendResult("rejected", "circuit_open", "SMS gateway paused after a recent timeout.")
    bucket = int(time.time() // WINDOW_SECONDS)
    digits = _phone_key(recipient)
    # the admin's own phone gets one text per order; only the site-wide cap applies to it
    if digits and digits != _phone_key(current.admin_hp):
        digest = hashlib.sha256(digits.encode("ascii")).hexdigest()[:24]
        limit = _int_setting("G5_SMS_RECIPIENT_HOURLY_LIMIT", DEFAULT_RECIPIENT_HOURLY_LIMIT)
        if not _count_send(RECIPIENT_COUNT_KEY.format(digest=digest, bucket=bucket), limit):
            return ICodeSendResult("rejected", "recipient_limit", "Hourly text limit for this number reached.")
    limit = _int_setting("G5_SMS_HOURLY_LIMIT", DEFAULT_HOURLY_LIMIT)
    if not _count_send(GLOBAL_COUNT_KEY.format(bucket=bucket), limit):
        return ICodeSendResult("rejected", "hourly_limit", "Hourly text limit of the shop reached.")
    return None


def _trip_breaker(result):
    if result.status == "accepted":
        # the gateway answers again (e.g. the operator's test text): stop skipping texts
        cache.delete(BREAKER_CACHE_KEY)
        return
    if result.provider_code not in BREAKER_CODES:
        return
    seconds = _int_setting("G5_SMS_BREAKER_SECONDS", DEFAULT_BREAKER_SECONDS)
    if seconds > 0 and cache.add(BREAKER_CACHE_KEY, "1", seconds):
        logger.error(
            "Shop SMS gateway %s: pausing every text for %s seconds.", result.provider_code, seconds
        )


def send_message(recipient, message, *, current=None, subject="", purpose="sms"):
    """Send one text to ``recipient`` with the shop's callback number. Never raises."""
    current = current or sms_settings()
    try:
        # the operator's test text goes through a paused gateway, to see whether it is back
        blocked = _send_guard(recipient, current, check_breaker=purpose != "test")
    except Exception:  # noqa: BLE001 - a cache outage must not stop the shop's texts
        logger.exception("Shop SMS limits could not be checked; sending %s anyway", purpose)
        blocked = None
    if blocked is not None:
        logger.warning("Shop SMS %s to %s skipped: %s", purpose, mask_phone(recipient), blocked.provider_code)
        return blocked
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
    try:
        _trip_breaker(result)
    except Exception:  # noqa: BLE001
        logger.exception("Shop SMS breaker could not be set")
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
