"""Shared constants and request/format helpers of the shop API."""

import hashlib
import hmac
import json
import re
import uuid

from django.conf import settings
from django.contrib.auth.hashers import check_password, identify_hasher, make_password
from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework.permissions import BasePermission

from gnu_jango.config.models import Config
from gnu_jango.core.thumbnails import thumbnail_url
from gnu_jango.shop.models import (
    ShopProduct,
    ShopCouponLog,
)
from gnu_jango.shop.order_flow import STATUS_ALIASES
from gnu_jango.shop.order_statuses import (
    INACTIVE_LINE_STATUSES,
    STATUS_COMPLETED,
    STATUS_PAID,
    STATUS_READY,
    STATUS_SHIPPING,
)
from gnu_jango.shop.shipping import (
    shipping_policy_payload,
)

from .response import api_error
from .v1_auth import _auth_user_from_request


SHOP_CART_SESSION_KEY = "g5_shop_cart"
SMOKE_CONFIG_PREFIX = "nextjs_smoke_"
AUTH_CART_CONFIG_PREFIX = "nextjs_cart_"
ORDER_STATUS_ORDERED = "주문"
ORDER_STATUS_PAID = "입금"
ORDER_STATUS_SHIPPING = "배송"
ORDER_STATUS_CANCELLED = "취소"
# youngcart $status_cancel (취소, 반품, 품절): every "cancelled" check of the shop goes through
# CANCELLED_STATUSES, so a returned or sold-out line or order counts as cancelled too.
CANCELLED_STATUSES = INACTIVE_LINE_STATUSES


def _spellings(*statuses):
    """The statuses with the English spellings older rows use for them (order_flow.STATUS_ALIASES)."""
    return frozenset(statuses) | {alias for alias, status in STATUS_ALIASES.items() if status in statuses}


# youngcart: an order is paid from 입금 on. 준비 (preparing), 배송 (shipped) and 완료 (delivered) are
# later steps of the same paid order - adm/shop_admin/orderlistupdate.php stamps the receipt only on
# 주문 -> 입금 (order_update_receipt) and moves 입금 -> 준비 -> 배송 -> 완료 with change_status alone.
PAID_STATUSES = _spellings(STATUS_PAID, STATUS_READY, STATUS_SHIPPING, STATUS_COMPLETED)
# The paid orders an operator has already moved on from 입금: a payment event that would roll the
# order back to 주문 leaves these to a person instead.
FULFILMENT_STATUSES = _spellings(STATUS_READY, STATUS_SHIPPING, STATUS_COMPLETED)
ORDERED_STATUSES = {ORDER_STATUS_ORDERED, "order", "ordered"}
PAYMENT_ADAPTER_PROVIDERS = {"kcp", "kcp_v2", "inicis", "nicepay", "naverpay", "kakaopay", "samsungpay"}
# Guest order passwords used to be stored as sha256(SECRET_KEY:od_id:password) with this prefix; they
# still verify and are re-hashed with the password hasher on the next successful lookup.
GUEST_ORDER_PASSWORD_HASH_PREFIX = "sha256$"
_SCRIPT_OR_STYLE_OPEN = re.compile(r"<(script|style)(?=[\s/>])", re.IGNORECASE)
_SCRIPT_OR_STYLE_CLOSE = {
    name: re.compile(rf"</{name}(?=[\s/>])[^>]*>", re.IGNORECASE) for name in ("script", "style")
}
_SCRIPT_OR_STYLE_TAG = re.compile(r"<(?=/?(?:script|style)(?![\w-]))", re.IGNORECASE)


class ShopStaffPermission(BasePermission):
    def has_permission(self, request, view):
        user = current_user(request)
        return bool(user and user.is_authenticated and (user.is_staff or user.is_superuser))


def smoke_config_name(suffix):
    return f"{SMOKE_CONFIG_PREFIX}{suffix}"[:50]


def read_smoke_config(suffix, default):
    item = Config.objects.filter(name=smoke_config_name(suffix)).first()
    if not item:
        return default
    try:
        value = json.loads(item.value)
    except (TypeError, ValueError):
        return default
    return value if isinstance(value, dict) else default


def configured_bank_accounts():
    rows = dict(
        Config.objects.filter(name__in=("de_bank_use", "de_bank_account"))
        .values_list("name", "value")
    )
    use_value = str(rows.get("de_bank_use", "")).strip().lower()
    if use_value in {"", "0", "false", "no", "off"}:
        return []
    return [line.strip() for line in str(rows.get("de_bank_account", "")).splitlines() if line.strip()]


def write_smoke_config(suffix, value):
    Config.objects.update_or_create(
        name=smoke_config_name(suffix),
        defaults={"value": json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:2000]},
    )


def strip_script_and_style_blocks(value):
    """Remove <script>/<style> blocks from member-written HTML (reviews, Q&A) before it is stored.

    Every renderer still sanitises the stored HTML with an allow-list (sanitizeUserHtml in Next.js);
    this keeps the stored text itself free of script blocks. Plain text is left as written (no entity
    escaping), so text views and edit forms show what the member typed.
    """
    text = str(value or "")
    # One linear scan: a regex with a lazy ".*?" rescans to the end from every unclosed tag.
    kept = []
    position = 0
    while (opening := _SCRIPT_OR_STYLE_OPEN.search(text, position)) is not None:
        kept.append(text[position : opening.start()])
        closing = _SCRIPT_OR_STYLE_CLOSE[opening.group(1).lower()].search(text, opening.end())
        if closing is None:
            position = len(text)  # an unclosed block runs to the end, as in a browser
            break
        position = closing.end()
    kept.append(text[position:])
    # Removing an inner block can join the pieces of an outer tag ("<scr<script></script>ipt>");
    # neutralise whatever tag is left instead of scanning again.
    return _SCRIPT_OR_STYLE_TAG.sub("&lt;", "".join(kept))


def member_display_name(user):
    profile = getattr(user, "profile", None)
    return (
        getattr(profile, "realname", "")
        or user.get_full_name()
        or getattr(profile, "nickname", "")
        or user.get_username()
    )


def normalize_hp(value):
    digits = re.sub(r"\D+", "", str(value or ""))
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    return str(value or "").strip()


def normalize_review_score(value, default=5):
    score = safe_int(value, default)
    return score if 1 <= score <= 5 else 1


def request_data(request):
    if isinstance(request.data, dict):
        return request.data
    return {}


def request_values(request):
    values = {}
    for source in (request.query_params, request.data):
        if not source:
            continue
        if hasattr(source, "lists"):
            for key, items in source.lists():
                clean_items = [item for item in items if item not in (None, "")]
                if not clean_items:
                    continue
                values[key] = clean_items if len(clean_items) > 1 or key.endswith("[]") else clean_items[-1]
        elif isinstance(source, dict):
            for key, value in source.items():
                if value not in (None, ""):
                    values[key] = value
    return values


def first_value(values, *keys, default=""):
    for key in keys:
        value = values.get(key)
        if isinstance(value, list):
            if value:
                return value[0]
        elif value not in (None, ""):
            return value
    return default


def list_values(values, *keys):
    for key in keys:
        value = values.get(key)
        if isinstance(value, list):
            return [item for item in value if item not in (None, "")]
        if value not in (None, ""):
            return [value]
    return []


def safe_int(value, default=0):
    try:
        if value in (None, ""):
            return default
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if -(1 << 63) <= result <= (1 << 63) - 1 else default


def bool_int(value):
    return 1 if value in (True, 1, "1", "true", "True", "yes", "on") else 0


def split_setting_list(value):
    return {item.strip().lower() for item in str(value or "").replace("|", ",").split(",") if item.strip()}


def datetime_value(value):
    if not value:
        return ""
    try:
        return timezone.localtime(value).isoformat()
    except ValueError:
        return value.isoformat()


def current_user(request):
    return _auth_user_from_request(request)


def require_user(request):
    user = current_user(request)
    if user:
        return user, None
    return None, api_error(
        "Authentication credentials were not provided.",
        status=drf_status.HTTP_401_UNAUTHORIZED,
        code="not_authenticated",
    )


def session_key(request):
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key or ""


def auth_cart_config_name(user):
    return f"{AUTH_CART_CONFIG_PREFIX}{user.pk}"[:50]


def guest_order_password_config_name(order_id):
    return f"guest_order_pwd_{order_id}"[:50]


def guest_order_password_hash(password):
    return make_password(str(password or ""))


def _legacy_guest_order_password_hash(order_id, password):
    raw = f"{settings.SECRET_KEY}:{order_id}:{password or ''}".encode("utf-8")
    return f"{GUEST_ORDER_PASSWORD_HASH_PREFIX}{hashlib.sha256(raw).hexdigest()}"


def _uses_password_hasher(stored_value):
    try:
        identify_hasher(stored_value)
    except ValueError:
        return False
    return True


def guest_order_password_needs_upgrade(stored):
    """True for the legacy SHA-256 and plaintext values, which are re-hashed after a successful lookup."""
    return not _uses_password_hasher(str(stored or ""))


def guest_order_password_matches(order_id, password, stored):
    stored_value = str(stored or "")
    if not stored_value:
        # Pay the hasher's cost anyway, so the response time does not reveal which guest orders exist.
        make_password(str(password or ""))
        return False
    if stored_value.startswith(GUEST_ORDER_PASSWORD_HASH_PREFIX):
        return hmac.compare_digest(_legacy_guest_order_password_hash(order_id, password), stored_value)
    if _uses_password_hasher(stored_value):
        return check_password(str(password or ""), stored_value)
    # Plaintext from imported YoungCart orders.
    return hmac.compare_digest(str(password or ""), stored_value)


def payment_confirm_access_allowed(request, order, data):
    user = current_user(request)
    if user and user.is_authenticated:
        if order.user_id and order.user_id == user.pk:
            return True
        if user.is_staff or user.is_superuser:
            return True
        return False

    uid = str(data.get("uid") or data.get("order_uid") or "").strip()
    if not order.user_id and uid and hmac.compare_digest(uid, str(order.uid or "")):
        return True
    return not order.user_id and str(order.od_id) in {
        str(item) for item in request.session.get("g5_guest_order_ids", [])
    }


def normalize_order_status(value):
    status = str(value or "").strip()
    lowered = status.lower()
    if status in {ORDER_STATUS_ORDERED, ORDER_STATUS_PAID, ORDER_STATUS_SHIPPING, ORDER_STATUS_CANCELLED}:
        return status
    if lowered in {"order", "ordered", "pending", "bank"}:
        return ORDER_STATUS_ORDERED
    if lowered in {"paid", "payment", "complete", "completed"}:
        return ORDER_STATUS_PAID
    if lowered in {"shipping", "delivery"}:
        return ORDER_STATUS_SHIPPING
    if lowered in {"cancel", "cancelled", "canceled"}:
        return ORDER_STATUS_CANCELLED
    return status or ORDER_STATUS_ORDERED


def is_order_cancelled(order):
    return str(order.od_status or "") in CANCELLED_STATUSES


def order_cancel_state(order):
    """YoungCart orderinquirycancel.php: the customer may cancel only an untouched order - status
    주문, nothing cancelled yet, and every line still 주문."""
    if is_order_cancelled(order):
        return False, "취소된 주문입니다."
    if str(order.od_status or "") in PAID_STATUSES:
        return False, "입금 이후 주문은 관리자에게 문의해 주세요."
    if (
        normalize_order_status(order.od_status) != ORDER_STATUS_ORDERED
        or int(order.od_cancel_price or 0) > 0
        or any(normalize_order_status(item.ct_status) != ORDER_STATUS_ORDERED for item in order.items.all())
    ):
        return False, "취소할 수 있는 주문이 아닙니다."
    return True, ""


def on_sale_products():
    """Products a visitor may see and buy: on sale, and not in a switched-off category
    (YoungCart item.php / list.php / search.php check it_use and ca_use)."""
    return ShopProduct.objects.filter(it_use="1").exclude(category__ca_use=False)


def fit_to_columns(model, values):
    """Cut text to its column size, as YoungCart's MySQL columns do, instead of failing the insert."""
    fitted = dict(values)
    for name, value in values.items():
        if isinstance(value, str):
            max_length = getattr(model._meta.get_field(name), "max_length", None)
            if max_length and len(value) > max_length:
                fitted[name] = value[:max_length]
    return fitted


def parse_ct_ids(value):
    if isinstance(value, (list, tuple, set)):
        parts = value
    else:
        parts = str(value or "").split(",")
    return {str(item).strip() for item in parts if str(item).strip()}


def next_coupon_log_id():
    latest = ShopCouponLog.objects.order_by("-cl_id").values_list("cl_id", flat=True).first()
    return int(latest or 0) + 1


def generate_numeric_order_id():
    # YoungCart's od_id starts with the shop's local date and time (date('YmdHis')), not UTC
    return timezone.localtime().strftime("%Y%m%d%H%M%S") + f"{uuid.uuid4().int % 1000000:06d}"


def pagination_meta(total, page, per_page):
    last_page = max(1, (total + per_page - 1) // per_page)
    if total <= 0:
        return {
            "total": 0,
            "current_page": page,
            "per_page": per_page,
            "last_page": 1,
            "from": None,
            "to": None,
        }
    start = (page - 1) * per_page + 1
    end = min(total, page * per_page)
    return {
        "total": total,
        "current_page": page,
        "per_page": per_page,
        "last_page": last_page,
        "from": start,
        "to": end,
    }


def paginate_queryset(request, queryset, default_per_page=20, max_per_page=100):
    page = max(1, safe_int(request.query_params.get("page"), 1))
    per_page = min(max(1, safe_int(request.query_params.get("per_page") or request.query_params.get("limit"), default_per_page)), max_per_page)
    total = queryset.count()
    start = (page - 1) * per_page
    rows = queryset[start : start + per_page] if start < total else queryset.none()
    return rows, pagination_meta(total, page, per_page)


def shop_policy_payload():
    return shipping_policy_payload()


def legacy_shop_asset_url(url):
    value = str(url or "").strip()
    if not value.startswith(("/data/item/", "/data/banner/", "/data/event/")):
        return value

    legacy_asset_base = str(getattr(settings, "LEGACY_GNUBOARD5_BASE_URL", "") or "").strip().rstrip("/")
    return f"{legacy_asset_base}{value}" if legacy_asset_base else value


def product_image_url(product):
    return legacy_shop_asset_url(product.image_url)


# Product cards are ~200-300px wide (400 covers 2x screens); cart, order and mini-cart rows ~100px.
PRODUCT_LIST_IMAGE_WIDTH = 400
PRODUCT_LINE_IMAGE_WIDTH = 240


def _product_image_storage_path(product):
    """Storage name of the main picture when it was uploaded here (its stored URL may be signed)."""
    primary = str(product.image_url or "").strip()
    for image in product.images if isinstance(product.images, list) else []:
        if isinstance(image, dict) and image.get("storage_path") and image.get("url") == primary:
            return str(image["storage_path"])
    return ""


def product_thumbnail_url(product, width=PRODUCT_LIST_IMAGE_WIDTH):
    """A list-size copy of the main picture (the original when Django cannot read it)."""
    return thumbnail_url(
        product_image_url(product), width, storage_path=_product_image_storage_path(product)
    )
