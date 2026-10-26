"""youngcart 결제설정 values kept as Config rows: 결제대행사 (de_pg_service), 결제 테스트
(de_card_test), 에스크로 사용 (de_escrow_use), the Toss Payments API keys
(cf_toss_client_key / cf_toss_secret_key, plus a test pair) and the NICEPAY authentication
payment credentials (MID plus the write-only MerchantKey, one pair per mode).

The secret keys are stored sealed (shop.sealed_values, under SECRET_KEY) and only the payment
code opens them. The server environment wins: when SHOP_TOSS_CLIENT_KEY / SHOP_TOSS_SECRET_KEY
or SHOP_NICEPAY_* MID / MERCHANT_KEY are set, the matching mode comes from there and the admin
pair is ignored; SHOP_PAYMENT_PROVIDER likewise wins over de_pg_service. The *_ADMIN_KEYS_ENABLED
flags (previews) ignore the admin keys altogether.

These rows are deliberately not part of shop_options.SHOP_CONFIG_OPTIONS, so the gnuboard
import (migrate_gnuboard5) never copies a youngcart PG choice or plaintext key into them."""

import hashlib
import re
from dataclasses import dataclass

from django.conf import settings
from django.views.decorators.debug import sensitive_variables

from gnu_jango.config.models import Config

from .sealed_values import seal, unseal

PG_SERVICE_FIELD = "de_pg_service"
CARD_TEST_FIELD = "de_card_test"
ESCROW_FIELD = "de_escrow_use"

PG_SERVICE_TOSS = "toss"
PG_SERVICE_NICEPAY = "nicepay"
PG_SERVICE_NONE = "none"
PG_SERVICE_CHOICES = (
    (PG_SERVICE_TOSS, "토스페이먼츠"),
    (PG_SERVICE_NICEPAY, "NICEPAY 인증결제"),
    (PG_SERVICE_NONE, "사용안함 (무통장입금만)"),
)
# youngcart offers these too; this shop cannot start a payment with them (shown as text only)
UNSUPPORTED_PG_SERVICES = ("NHN KCP", "KG이니시스")

KEY_MODES = ("test", "live")
KEY_KINDS = ("client", "secret")
NICEPAY_KEY_KINDS = ("mid", "merchant_key")
MODE_LABELS = {"test": "테스트", "live": "실결제"}
KIND_LABELS = {"client": "클라이언트 키", "secret": "시크릿 키"}
# Config row per (mode, kind); the live pair keeps youngcart's names
TOSS_KEY_ROWS = {
    ("test", "client"): "cf_toss_test_client_key",
    ("test", "secret"): "cf_toss_test_secret_key",
    ("live", "client"): "cf_toss_client_key",
    ("live", "secret"): "cf_toss_secret_key",
}
# NICEPAY 인증결제 uses MID + MerchantKey. MID is not a secret, MerchantKey is write-only and
# sealed like the Toss keys. The names are new Config rows, never copied from the PHP site.
NICEPAY_KEY_ROWS = {
    ("test", "mid"): "cf_nicepay_test_mid",
    ("test", "merchant_key"): "cf_nicepay_test_merchant_key",
    ("live", "mid"): "cf_nicepay_mid",
    ("live", "merchant_key"): "cf_nicepay_merchant_key",
}
# API 개별 연동 keys (ck/sk) and 결제위젯 연동 keys (gck/gsk)
KEY_PREFIXES = {
    ("test", "client"): ("test_ck_", "test_gck_"),
    ("test", "secret"): ("test_sk_", "test_gsk_"),
    ("live", "client"): ("live_ck_", "live_gck_"),
    ("live", "secret"): ("live_sk_", "live_gsk_"),
}
KEY_PATTERN = re.compile(r"[A-Za-z0-9_]{12,200}")
NICEPAY_MID_PATTERN = re.compile(r"[A-Za-z0-9]{10}")
NICEPAY_MERCHANT_KEY_PATTERN = re.compile(r"[A-Za-z0-9+/=]{10,200}")
SEAL_SALT = "shop-pg-keys"

PG_SETTING_NAMES = (
    PG_SERVICE_FIELD,
    CARD_TEST_FIELD,
    ESCROW_FIELD,
    *TOSS_KEY_ROWS.values(),
    *NICEPAY_KEY_ROWS.values(),
)


def key_label(mode, kind):
    return f"{MODE_LABELS[mode]} {KIND_LABELS[kind]}"


def seal_context(mode, kind):
    return f"shop-toss-{mode}-{kind}"


@sensitive_variables()
def seal_key(mode, kind, value):
    return seal(value, salt=SEAL_SALT, context=seal_context(mode, kind))


@sensitive_variables()
def unseal_key(mode, kind, token):
    return unseal(token, salt=SEAL_SALT, context=seal_context(mode, kind))


@sensitive_variables()
def key_prefix_error(mode, kind, value):
    """Why ``value`` cannot be the ``mode`` ``kind`` key ("" when it can)."""
    if not KEY_PATTERN.fullmatch(value or ""):
        return "토스페이먼츠 키는 영문, 숫자, 밑줄(_)만 12자 이상 입력하세요."
    prefixes = KEY_PREFIXES[(mode, kind)]
    if not value.startswith(prefixes):
        return f"{key_label(mode, kind)}는 {' 또는 '.join(prefixes)}로 시작해야 합니다."
    return ""


def key_family(value):
    """"widget" for a 결제위젯 연동 key (gck/gsk), "api" for an API 개별 연동 key (ck/sk)."""
    return "widget" if re.match(r"(?:test|live)_g(?:ck|sk)_", value or "") else "api"


def mask_key(value):
    """The key's prefix and last four characters, e.g. test_ck_****abcd."""
    value = str(value or "")
    if not value:
        return ""
    prefix = re.match(r"(?:test|live)_g?(?:ck|sk)_", value)
    head = prefix.group(0) if prefix else ""
    return f"{head}****{value[-4:]}"


def stored_rows():
    return dict(Config.objects.filter(name__in=PG_SETTING_NAMES).values_list("name", "value"))


def nicepay_seal_context(mode, kind):
    return f"shop-nicepay-{mode}-{kind}"


@sensitive_variables()
def seal_nicepay_value(mode, kind, value):
    return seal(value, salt=SEAL_SALT, context=nicepay_seal_context(mode, kind))


@sensitive_variables()
def unseal_nicepay_value(mode, kind, token):
    return unseal(token, salt=SEAL_SALT, context=nicepay_seal_context(mode, kind))


def nicepay_value_error(mode, kind, value):
    """Why ``value`` cannot be a NICEPAY ``mode`` ``kind`` value ("" when it can)."""
    label = "MID" if kind == "mid" else "MerchantKey"
    pattern = NICEPAY_MID_PATTERN if kind == "mid" else NICEPAY_MERCHANT_KEY_PATTERN
    if not pattern.fullmatch(value or ""):
        if kind == "mid":
            return "NICEPAY MID는 영문·숫자 10자리로 입력하세요."
        return "NICEPAY MerchantKey는 영문·숫자·+/= 10~200자리로 입력하세요."
    return ""


def env_nicepay_keys(mode):
    """The environment pair for one mode. The environment wins only for the mode it names."""
    prefix = "SHOP_NICEPAY_TEST_" if mode == "test" else "SHOP_NICEPAY_"
    mid = str(getattr(settings, f"{prefix}MID", "") or "").strip()
    merchant_key = str(getattr(settings, f"{prefix}MERCHANT_KEY", "") or "").strip()
    return mid, merchant_key


def env_nicepay_keys_set(mode=None):
    modes = (mode,) if mode in KEY_MODES else KEY_MODES
    return any(any(env_nicepay_keys(item)) for item in modes)


def nicepay_admin_keys_enabled():
    return bool(getattr(settings, "SHOP_NICEPAY_ADMIN_KEYS_ENABLED", True))


def nicepay_key_fingerprint(mode, mid, merchant_key):
    """A non-reversible identifier for the credential pair, kept with each payment attempt."""
    value = f"nicepay:{mode}:{mid}:{merchant_key}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:32]


@dataclass(frozen=True)
class NicepayKeys:
    mid: str
    merchant_key: str
    source: str  # "env" | "admin" | "none"
    selected_mode: str  # "test" | "live"
    pinned: bool = False

    @property
    def enabled(self):
        return bool(self.mid and self.merchant_key)

    @property
    def key_fingerprint(self):
        return nicepay_key_fingerprint(self.selected_mode, self.mid, self.merchant_key)

    def __repr__(self):  # never print the MerchantKey by accident
        return f"NicepayKeys(source={self.source!r}, selected_mode={self.selected_mode!r}, pinned={self.pinned!r})"


@sensitive_variables()
def effective_nicepay_keys(rows=None, *, mode=None):
    """The NICEPAY MID/MerchantKey pair to use for a new or an existing payment.

    A payment attempt records its mode (od_test). It is always confirmed, cancelled and looked up
    with that mode's pair, even after the admin changes 결제 테스트. The environment pair for the
    selected mode wins; a missing environment pair never falls back to the other mode.
    """
    rows = stored_rows() if rows is None else rows
    pinned = mode in KEY_MODES
    selected_mode = mode if pinned else current_mode(rows)
    env_mid, env_merchant_key = env_nicepay_keys(selected_mode)
    if env_mid or env_merchant_key:
        return NicepayKeys(env_mid, env_merchant_key, "env", selected_mode, False)
    if not nicepay_admin_keys_enabled():
        return NicepayKeys("", "", "none", selected_mode, pinned)
    mid = str(rows.get(NICEPAY_KEY_ROWS[(selected_mode, "mid")], "") or "").strip()
    merchant_key = unseal_nicepay_value(
        selected_mode,
        "merchant_key",
        rows.get(NICEPAY_KEY_ROWS[(selected_mode, "merchant_key")], ""),
    )
    return NicepayKeys(
        mid,
        merchant_key,
        "admin" if mid or merchant_key else "none",
        selected_mode,
        pinned,
    )


def nicepay_unreadable_key_rows(rows=None):
    """MerchantKey rows that can no longer be opened (SECRET_KEY changed or row altered)."""
    rows = stored_rows() if rows is None else rows
    return [
        mode
        for mode in KEY_MODES
        if str(rows.get(NICEPAY_KEY_ROWS[(mode, "merchant_key")]) or "").strip()
        and not unseal_nicepay_value(
            mode,
            "merchant_key",
            rows.get(NICEPAY_KEY_ROWS[(mode, "merchant_key")], ""),
        )
    ]


def admin_nicepay_values(rows=None):
    """{mode: {"mid": stored MID, "merchant_key": opened MerchantKey or ""}}."""
    rows = stored_rows() if rows is None else rows
    return {
        mode: {
            "mid": str(rows.get(NICEPAY_KEY_ROWS[(mode, "mid")], "") or "").strip(),
            "merchant_key": unseal_nicepay_value(
                mode,
                "merchant_key",
                rows.get(NICEPAY_KEY_ROWS[(mode, "merchant_key")], ""),
            ),
        }
        for mode in KEY_MODES
    }


def nicepay_payment_config(rows=None):
    """The effective NICEPAY setup for a new payment, without the MerchantKey itself."""
    keys = effective_nicepay_keys(rows)
    valid_mid = bool(NICEPAY_MID_PATTERN.fullmatch(keys.mid or ""))
    valid_key = bool(NICEPAY_MERCHANT_KEY_PATTERN.fullmatch(keys.merchant_key or ""))
    if not keys.mid and not keys.merchant_key:
        key_status = "missing"
    elif not keys.mid or not keys.merchant_key:
        key_status = "incomplete"
    elif not valid_mid:
        key_status = "invalid_mid"
    elif not valid_key:
        key_status = "invalid_key"
    else:
        key_status = keys.selected_mode
    return {
        "enabled": key_status in {"test", "live"},
        "key_status": key_status,
        "mid": keys.mid,
        "has_merchant_key": bool(keys.merchant_key),
        "source": keys.source,
        "selected_mode": keys.selected_mode,
        "pinned_mode": keys.selected_mode if keys.pinned and keys.source != "env" else None,
        "is_test_mode": keys.selected_mode == "test",
        "vbank_enabled": bool(
            getattr(settings, "SHOP_NICEPAY_VBANK_ENABLED", True) and key_status in {"test", "live"}
        ),
        "key_fingerprint": keys.key_fingerprint if keys.enabled else "",
    }


def env_toss_keys():
    client = str(getattr(settings, "SHOP_TOSS_CLIENT_KEY", "") or "").strip()
    secret = str(getattr(settings, "SHOP_TOSS_SECRET_KEY", "") or "").strip()
    return client, secret


def env_keys_set():
    return any(env_toss_keys())


def env_payment_provider():
    return str(getattr(settings, "SHOP_PAYMENT_PROVIDER", "") or "").strip().lower()


def admin_keys_enabled():
    return bool(getattr(settings, "SHOP_TOSS_ADMIN_KEYS_ENABLED", True))


def card_test_enabled(rows=None):
    """결제 테스트: youngcart de_card_test (1 = 테스트결제). A new shop starts in test mode."""
    rows = stored_rows() if rows is None else rows
    return str(rows.get(CARD_TEST_FIELD, "1") or "").strip() != "0"


def escrow_enabled(rows=None):
    rows = stored_rows() if rows is None else rows
    return str(rows.get(ESCROW_FIELD, "0") or "").strip() == "1"


def admin_pg_service(rows=None):
    """de_pg_service; a shop that never saved it keeps the earlier behaviour (Toss when keyed)."""
    rows = stored_rows() if rows is None else rows
    value = str(rows.get(PG_SERVICE_FIELD, PG_SERVICE_TOSS) or "").strip().lower()
    return value if value in {PG_SERVICE_TOSS, PG_SERVICE_NICEPAY, PG_SERVICE_NONE} else PG_SERVICE_TOSS


@sensitive_variables()
def admin_keys(rows=None):
    """{(mode, kind): plain key or ""} of the keys saved in the admin."""
    rows = stored_rows() if rows is None else rows
    return {
        (mode, kind): unseal_key(mode, kind, rows.get(name, ""))
        for (mode, kind), name in TOSS_KEY_ROWS.items()
    }


def unreadable_key_rows(rows=None):
    """Key rows that are saved but no longer open (SECRET_KEY changed without
    SECRET_KEY_FALLBACKS, or the row was altered): [(mode, kind), ...]."""
    rows = stored_rows() if rows is None else rows
    return [
        (mode, kind)
        for (mode, kind), name in TOSS_KEY_ROWS.items()
        if str(rows.get(name) or "").strip() and not unseal_key(mode, kind, rows.get(name))
    ]


def mode_flag(mode):
    """The ShopOrder.od_test value for a key mode (youngcart od_test: 1 = 테스트결제)."""
    return "1" if mode == "test" else "0"


def current_mode(rows=None):
    return "test" if card_test_enabled(rows) else "live"


def order_key_mode(order):
    """The admin key pair an order was paid with ("test" / "live"), from od_test; None for an
    order that does not say (it uses the shop's current 결제 테스트)."""
    value = str(getattr(order, "od_test", "") or "").strip()
    return "test" if value == "1" else "live" if value == "0" else None


@dataclass(frozen=True)
class TossKeys:
    client_key: str
    secret_key: str
    source: str  # "env" | "admin" | "none"
    selected_mode: str  # the admin pair used: "test" | "live"
    pinned: bool = False  # the mode came from an order, not from 결제 테스트

    def __repr__(self):  # never print a secret by accident
        return f"TossKeys(source={self.source!r}, selected_mode={self.selected_mode!r}, pinned={self.pinned!r})"


@sensitive_variables()
def effective_toss_keys(rows=None, *, mode=None):
    """The Toss key pair to use: the environment pair when either env key is set (the mode is
    then ignored), otherwise the admin pair of ``mode`` - an order's own mode, so a payment is
    always confirmed, cancelled and refunded with the pair it was made with - or, without one,
    the pair 결제 테스트 picks. A missing pair is never replaced by the other mode's."""
    rows = stored_rows() if rows is None else rows
    pinned = mode in KEY_MODES
    selected_mode = mode if pinned else current_mode(rows)
    client, secret = env_toss_keys()
    if client or secret:
        return TossKeys(client, secret, "env", selected_mode, False)
    if not admin_keys_enabled():
        return TossKeys("", "", "none", selected_mode, pinned)
    client = unseal_key(selected_mode, "client", rows.get(TOSS_KEY_ROWS[(selected_mode, "client")], ""))
    secret = unseal_key(selected_mode, "secret", rows.get(TOSS_KEY_ROWS[(selected_mode, "secret")], ""))
    return TossKeys(client, secret, "admin" if client or secret else "none", selected_mode, pinned)
