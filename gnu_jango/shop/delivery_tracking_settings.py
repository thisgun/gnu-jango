"""Delivery Tracker settings: the 배송조회 사용 / 배송완료 시 주문 완료 처리 switches
(shop_options.TRACKING_OPTIONS) and the API key pair, kept as Config rows.

The Client ID and Client Secret are stored sealed (shop.sealed_values, under SECRET_KEY) like
the PG keys, only shop/delivery_tracker_client.py receives them in the clear, and the admin
never shows them back (the Client ID only masked). Tracking is on only while the switch is on
and both keys open; otherwise the site shows the courier links as before.

The rows are not part of shop_options.SHOP_CONFIG_OPTIONS, so the gnuboard import never
touches them. The webhook token in the callback URL is derived from SECRET_KEY, so it needs
no row and a token of a rotated-out key (SECRET_KEY_FALLBACKS) is still accepted."""

import re
from dataclasses import dataclass

from django.conf import settings
from django.urls import reverse
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.debug import sensitive_variables

from gnu_jango.config.models import Config

from .delivery_tracker_client import TrackerCredentials
from .sealed_values import seal, unseal
from .shop_options import shop_options

ENABLED_FIELD = "de_tracking_use"
COMPLETE_FIELD = "de_tracking_complete_delivered"
KEY_KINDS = ("client_id", "client_secret")
KEY_ROWS = {
    "client_id": "cf_delivery_tracker_client_id",
    "client_secret": "cf_delivery_tracker_client_secret",
}
KEY_LABELS = {"client_id": "Client ID", "client_secret": "Client Secret"}
KEY_PATTERN = re.compile(r"[A-Za-z0-9._~+/=-]{8,200}")
SEAL_SALT = "shop-delivery-tracker-keys"
WEBHOOK_SALT = "gnu_jango.shop.delivery_tracking.webhook"
WEBHOOK_PATH_NAME = "api_v1:shop-delivery-tracker-webhook"


def seal_context(kind):
    return f"shop-delivery-tracker-{kind}"


@sensitive_variables()
def seal_key(kind, value):
    return seal(value, salt=SEAL_SALT, context=seal_context(kind))


@sensitive_variables()
def unseal_key(kind, token):
    return unseal(token, salt=SEAL_SALT, context=seal_context(kind))


def key_error(kind, value):
    """Why ``value`` cannot be the ``kind`` key ("" when it can)."""
    if not KEY_PATTERN.fullmatch(value or ""):
        return f"{KEY_LABELS[kind]}는 영문, 숫자와 . _ ~ + / = - 기호만 8~200자로 입력하세요."
    return ""


def mask_key(value):
    value = str(value or "")
    return f"****{value[-4:]}" if value else ""


def stored_rows():
    return dict(Config.objects.filter(name__in=KEY_ROWS.values()).values_list("name", "value"))


@sensitive_variables()
def admin_keys(rows=None):
    """{kind: plain key or ""} of the saved keys."""
    rows = stored_rows() if rows is None else rows
    return {kind: unseal_key(kind, rows.get(name, "")) for kind, name in KEY_ROWS.items()}


def unreadable_keys(rows=None):
    """Kinds that are saved but no longer open (SECRET_KEY changed, or the row was altered)."""
    rows = stored_rows() if rows is None else rows
    return [
        kind
        for kind, name in KEY_ROWS.items()
        if str(rows.get(name) or "").strip() and not unseal_key(kind, rows.get(name))
    ]


@dataclass(frozen=True)
class TrackingConfig:
    switched_on: bool
    has_client_id: bool
    has_client_secret: bool
    complete_on_delivered: bool
    credentials: TrackerCredentials

    @property
    def enabled(self):
        return self.switched_on and bool(self.credentials)

    def __repr__(self):  # never print a key by accident
        return f"TrackingConfig(enabled={self.enabled!r}, complete_on_delivered={self.complete_on_delivered!r})"


@sensitive_variables("keys")
def tracking_config(rows=None):
    options = shop_options(ENABLED_FIELD, COMPLETE_FIELD)
    keys = admin_keys(rows)
    return TrackingConfig(
        switched_on=bool(options[ENABLED_FIELD]),
        has_client_id=bool(keys["client_id"]),
        has_client_secret=bool(keys["client_secret"]),
        complete_on_delivered=bool(options[COMPLETE_FIELD]),
        credentials=TrackerCredentials(keys["client_id"], keys["client_secret"]),
    )


def polling_job_enabled():
    """SHOP_DELIVERY_TRACKING_JOB: whether run_scheduled_jobs includes track_shipments."""
    return bool(getattr(settings, "SHOP_DELIVERY_TRACKING_JOB", False))


def _token(secret):
    return salted_hmac(WEBHOOK_SALT, "callback", secret=secret, algorithm="sha256").hexdigest()[:48]


def webhook_token():
    return _token(settings.SECRET_KEY)


def webhook_token_valid(token):
    token = str(token or "")
    secrets = [settings.SECRET_KEY, *getattr(settings, "SECRET_KEY_FALLBACKS", ())]
    # every candidate is compared, so the time taken does not say which one matched
    return bool(token) and sum(constant_time_compare(token, _token(secret)) for secret in secrets) > 0


def callback_base_url():
    """The public https origin Delivery Tracker calls back: SHOP_DELIVERY_TRACKER_CALLBACK_BASE_URL,
    else SOCIAL_APP_BASE_URL. "" (no webhook, polling only) unless it is https."""
    for name in ("SHOP_DELIVERY_TRACKER_CALLBACK_BASE_URL", "SOCIAL_APP_BASE_URL"):
        value = str(getattr(settings, name, "") or "").strip().rstrip("/")
        if value:
            return value if value.lower().startswith("https://") else ""
    return ""


def webhook_callback_url():
    base = callback_base_url()
    return f"{base}{reverse(WEBHOOK_PATH_NAME, args=[webhook_token()])}" if base else ""
