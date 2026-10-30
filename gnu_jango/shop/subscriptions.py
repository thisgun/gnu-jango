"""정기구독: recurring subscription orders paid by Toss card billing (자동결제).

A member picks a product line (option, quantity) and a delivery cycle on the product page and
registers a card in the Toss billing window. The success page hands the one-time authKey back;
complete_registration checks it belongs to the member's pending registration, has Toss issue the
billing key (kept sealed, never shown) and charges the first cycle at once.

Every charge is an ordinary checkout order: create_order_from_lines (the checkout's own order
builder: stock, coupons, points, address) makes the 주문 order, Toss approves the amount on the
billing key, and confirm_order_payment marks it paid exactly as a Toss checkout payment (status,
lines, mails, SMS, payment log). A declined charge cancels that order again the way an expired
checkout does (cancel_order_and_refund_benefits). The price is the product's price on the day of
the charge, less the product's subscription discount.

Double charging is ruled out in three layers: the subscription row is locked while a charge is
claimed, the database allows one pending/done charge per cycle (ShopSubscriptionCharge), and each
attempt sends its own Idempotency-Key to Toss. A charge whose answer was lost stays pending until
the scheduler looks the payment up by its orderId (reconcile_stale_charges).
"""

import logging
import secrets
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import SimpleNamespace

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Max, Q
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.debug import sensitive_variables

from . import toss_billing
from .models import ShopAddress, ShopBillingCustomer, ShopOrder, ShopProduct, ShopSubscription, ShopSubscriptionCharge
from .sealed_values import seal, unseal
from .shop_options import shop_options
from .toss_billing import TossBillingError, card_company_name

logger = logging.getLogger(__name__)

Sub = ShopSubscription
Charge = ShopSubscriptionCharge

CYCLE_ORDER = ("1w", "2w", "4w", "1m")
CYCLE_LABELS = dict(Sub.CYCLE_CHOICES)
CYCLE_WEEKS = {"1w": 1, "2w": 2, "4w": 4}
MAX_DISCOUNT_RATE = 50
REGISTRATION_TTL = timedelta(minutes=30)
# a charge still pending after this long lost its answer: look the payment up at Toss
STALE_CHARGE_AGE = timedelta(minutes=10)
PENDING_REGISTRATION_LIMIT = 5
BILLING_KEY_SALT = "toss-billing-key"
SETTLE_CASE = "신용카드"
OPEN_CHARGE_STATUSES = (Charge.STATUS_PENDING, Charge.STATUS_DONE, Charge.STATUS_REVIEW)
STOCK_ERROR_CODES = {"insufficient_stock", "option_not_found", "option_unavailable"}

# why a cycle cannot be charged: (API message, notice to the member)
UNAVAILABLE = {
    "product_missing": ("This product cannot be subscribed to.", "상품이 더 이상 판매되지 않습니다."),
    "product_unavailable": ("This product cannot be subscribed to.", "상품이 지금 판매 중이 아닙니다."),
    "option_required": ("Select an available option.", "선택한 옵션을 더 이상 주문할 수 없습니다."),
    "out_of_stock": ("The product is out of stock.", "상품 재고가 부족합니다."),
    "quantity_invalid": ("The quantity is outside the allowed range.", "주문할 수 있는 수량이 바뀌었습니다."),
}

NOTICE_TITLES = {
    "upcoming": "정기구독 결제 예정 안내",
    "charged": "정기구독 결제가 완료되었습니다",
    "failed": "정기구독 결제에 실패했습니다",
    "paused": "정기구독이 일시정지되었습니다",
    "skipped": "이번 정기구독 배송을 건너뛰었습니다",
    "cancelled": "정기구독이 해지되었습니다",
}


class SubscriptionError(Exception):
    """A subscription request that cannot be done; ``status`` is the HTTP status for the API."""

    def __init__(self, message, *, code="subscription_error", status=400, details=None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.details = details or {}


@dataclass
class ChargeResult:
    status: str  # charged | failed | skipped | pending | review | already | not_due | inactive | paused | cancelled | missing
    charge: object = None
    message: str = ""
    code: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def order_id(self):
        return getattr(self.charge, "od_id", "") or ""


# --- settings and product offer -------------------------------------------------------------


def server_enabled():
    return bool(getattr(settings, "SHOP_SUBSCRIPTIONS_ENABLED", False))


def feature_enabled():
    """The server allows subscriptions (SHOP_SUBSCRIPTIONS_ENABLED) and the admin turned them on."""
    return server_enabled() and bool(shop_options("de_subscription_use")["de_subscription_use"])


def retry_limit():
    return shop_options("de_subscription_retry_limit")["de_subscription_retry_limit"]


def notice_days():
    return shop_options("de_subscription_notice_days")["de_subscription_notice_days"]


def parse_cycles(value):
    chosen = {part.strip() for part in str(value or "").split(",")}
    return tuple(cycle for cycle in CYCLE_ORDER if cycle in chosen)


def product_cycles(product):
    return parse_cycles(getattr(product, "it_subscription_cycles", ""))


def discount_rate(product):
    return min(MAX_DISCOUNT_RATE, max(0, int(getattr(product, "it_subscription_discount", 0) or 0)))


def discounted_price(price, rate):
    price = max(0, int(price or 0))
    return price - price * int(rate or 0) // 100


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def base_options(product):
    return [
        row for row in (product.options or [])
        if isinstance(row, dict) and _int(row.get("io_type"), 0) == 0
    ]


def matched_option(product, io_id):
    io_id = str(io_id or "")
    if not io_id:
        return None
    return next(
        (row for row in base_options(product) if str(row.get("io_id") or "") == io_id and _int(row.get("io_use"), 1) == 1),
        None,
    )


def product_unavailable_code(product, io_id, qty):
    """"" when ``qty`` of ``product`` (option ``io_id``) can be subscribed and charged now, else the
    reason (a key of UNAVAILABLE)."""
    if product is None:
        return "product_missing"
    if (
        str(product.it_use or "") != "1"
        or str(product.it_soldout or "") == "1"
        or str(product.it_tel_inq or "") == "1"
        or not product.it_subscription_use
        or int(product.it_price or 0) <= 0
        or not product_cycles(product)
    ):
        return "product_unavailable"
    qty = _int(qty, 0)
    if base_options(product):
        option = matched_option(product, io_id)
        if option is None:
            return "option_required"
        stock = _int(option.get("io_stock_qty"), 0)
    elif io_id:
        return "option_required"
    else:
        stock = _int(product.it_stock_qty, 0)
    minimum = max(1, _int(product.it_buy_min_qty, 1))
    maximum = max(0, _int(product.it_buy_max_qty, 0))
    if qty < minimum or (maximum and qty > maximum):
        return "quantity_invalid"
    if stock < qty:
        return "out_of_stock"
    return ""


def product_offer(product):
    """What the product page offers (``subscription`` of the product detail), None when the product
    cannot be subscribed to (or the feature is off)."""
    if not getattr(product, "it_subscription_use", False):
        return None
    cycles = product_cycles(product)
    if not cycles or int(product.it_price or 0) <= 0 or str(product.it_tel_inq or "") == "1" or not feature_enabled():
        return None
    rate = discount_rate(product)
    return {
        "cycles": [{"value": cycle, "label": CYCLE_LABELS[cycle]} for cycle in cycles],
        "discount_rate": rate,
        "price": discounted_price(product.it_price, rate),
    }


def charge_line(sub, product):
    """The cart line a charge orders (the checkout's line shape), priced as of now."""
    from gnu_jango.api.shop_cart import cart_item_payload, next_cart_id

    option = matched_option(product, sub.io_id)
    return cart_item_payload({
        "ct_id": next_cart_id([]),
        "it_id": product.it_id,
        "it_name": product.it_name,
        "ct_price": discounted_price(product.it_price, discount_rate(product)),
        "ct_qty": sub.qty,
        "ct_option": sub.io_id,
        "io_type": 0,
        "io_price": _int(option.get("io_price"), 0) if option else 0,
        "ct_direct": 0,
        "ct_send_cost": 0,
    })


def estimated_amount(sub, product=None):
    """What the next charge would come to at today's prices (goods and shipping), None if the
    product cannot be charged now."""
    from gnu_jango.shop.shipping import shipping_quote

    product = product if product is not None else ShopProduct.objects.filter(pk=sub.it_id).first()
    if product_unavailable_code(product, sub.io_id, sub.qty):
        return None
    line = charge_line(sub, product)
    shipping = shipping_quote(line["line_total"], sub.od_b_zip, items=[line])
    return line["line_total"] + int(shipping["total"] or 0)


# --- schedule -------------------------------------------------------------------------------


def add_month(value, day):
    year, month = (value.year + 1, 1) if value.month == 12 else (value.year, value.month + 1)
    return date(year, month, min(max(1, int(day or 1)), monthrange(year, month)[1]))


def next_cycle_date(sub, value):
    weeks = CYCLE_WEEKS.get(sub.cycle)
    if weeks:
        return value + timedelta(weeks=weeks)
    return add_month(value, sub.billing_day or value.day)


def due_date(sub):
    return sub.retry_date or sub.next_charge_date


def is_due(sub, today):
    due = due_date(sub)
    return sub.status == Sub.STATUS_ACTIVE and due is not None and due <= today


def advance_cycle(sub, today):
    """Close the current cycle: the next one is scheduled a cycle after it, never on or before today."""
    value = next_cycle_date(sub, sub.next_charge_date or today)
    while value <= today:
        value = next_cycle_date(sub, value)
    sub.next_charge_date = value
    sub.cycle_no += 1
    sub.retry_date = None
    sub.failure_count = 0


def _next_attempt(sub):
    latest = sub.charges.filter(cycle_no=sub.cycle_no).aggregate(latest=Max("attempt"))["latest"]
    return int(latest or 0) + 1


def _has_pending_charge(sub):
    return sub.charges.filter(status=Charge.STATUS_PENDING).exists()


# --- billing key and customer key -----------------------------------------------------------


def _seal_context(sub):
    return f"shop-subscription:{sub.pk}:{sub.user_id}"


def billing_key(sub):
    return unseal(sub.billing_key_sealed, salt=BILLING_KEY_SALT, context=_seal_context(sub)) if sub.billing_key_sealed else ""


def new_customer_key():
    # Toss: 2-50 letters, digits and - _ = . @, at least one special character, not guessable
    return f"gj_{secrets.token_urlsafe(24)}"


def billing_customer(user):
    customer = ShopBillingCustomer.objects.filter(user=user).first()
    if customer:
        return customer
    try:
        with transaction.atomic():
            return ShopBillingCustomer.objects.create(user=user, customer_key=new_customer_key())
    except IntegrityError:
        return ShopBillingCustomer.objects.get(user=user)


def _token_hash(token):
    """What the database keeps of a one-time registration token (32 random bytes): a digest keyed
    with SECRET_KEY, never the token itself."""
    return salted_hmac("gnu_jango.shop.subscriptions.registration", str(token or ""), algorithm="sha256").hexdigest()


def toss_context():
    """(config, key mode) of the Toss pair a new registration uses; refuses a shop without a usable
    API pair. Billing needs the API individual keys (ck / sk), not the payment widget keys."""
    from gnu_jango.api.shop_payments import current_toss_mode_flag, toss_api_context

    mode = current_toss_mode_flag()
    config, authorization = toss_api_context(SimpleNamespace(od_test=mode))
    if not authorization or not config["enabled"]:
        raise SubscriptionError("Toss Payments is not configured.", code="toss_payment_unconfigured", status=503)
    if "_gck_" in str(config["client_key"] or ""):
        raise SubscriptionError(
            "Card billing needs the Toss API individual keys, not the payment widget keys.",
            code="toss_billing_keys_unsupported",
            status=503,
        )
    return config, mode


def require_feature():
    if not feature_enabled():
        raise SubscriptionError("Subscriptions are not available.", code="subscription_unavailable", status=404)


# --- registration ---------------------------------------------------------------------------

ADDRESS_FIELDS = {
    "od_b_name": 100, "od_b_tel": 50, "od_b_hp": 50, "od_b_zip": 20,
    "od_b_addr1": 255, "od_b_addr2": 255, "od_b_addr3": 255, "od_b_addr_jibeon": 255,
}


def delivery_address(user, data):
    """The delivery address of a new subscription: a saved ShopAddress (ad_id) or the fields typed
    in, as the checkout takes them (od_b_*)."""
    from gnu_jango.api.shop_cart import normalize_zip_from_keys

    ad_id = _int(data.get("ad_id"), 0)
    if ad_id:
        saved = ShopAddress.objects.filter(pk=ad_id, user=user).first()
        if saved is None:
            raise SubscriptionError("Address not found.", code="address_not_found", status=404)
        values = {
            "od_b_name": saved.ad_name, "od_b_tel": saved.ad_tel, "od_b_hp": saved.ad_hp, "od_b_zip": saved.ad_zip,
            "od_b_addr1": saved.ad_addr1, "od_b_addr2": saved.ad_addr2, "od_b_addr3": saved.ad_addr3,
            "od_b_addr_jibeon": saved.ad_jibeon,
        }
    else:
        values = {name: str(data.get(name) or "").strip() for name in ADDRESS_FIELDS}
        values["od_b_zip"] = normalize_zip_from_keys(data, full_keys=("od_b_zip",), split_keys=("od_b_zip1", "od_b_zip2"))
    values = {name: str(values.get(name) or "").strip()[:limit] for name, limit in ADDRESS_FIELDS.items()}
    if not values["od_b_name"] or not (values["od_b_hp"] or values["od_b_tel"]) or not values["od_b_zip"] or not values["od_b_addr1"]:
        raise SubscriptionError("Enter the delivery address.", code="subscription_address_required", status=422)
    return values


def registration_payload(sub, token, config):
    return {
        "subscription_id": sub.pk,
        "registration_token": token,
        "customer_key": sub.customer_key,
        "client_key": config["client_key"],
        "customer_name": sub.od_name,
        "customer_email": sub.od_email,
        "expires_at": sub.auth_expires_at.isoformat() if sub.auth_expires_at else None,
    }


def start_subscription(user, data):
    """Open a card registration for a new subscription (a 카드 등록 대기 row). Returns what the
    browser needs to open the Toss billing window (registration_payload)."""
    from gnu_jango.api.shop_common import member_display_name

    require_feature()
    config, mode = toss_context()
    it_id = str(data.get("it_id") or "").strip()
    io_id = str(data.get("io_id") or data.get("ct_option") or "").strip()
    qty = _int(data.get("qty") or data.get("ct_qty"), 1)
    cycle = str(data.get("cycle") or "").strip()
    product = ShopProduct.objects.filter(pk=it_id).first() if it_id else None
    code = product_unavailable_code(product, io_id, qty)
    if code:
        raise SubscriptionError(UNAVAILABLE[code][0], code=f"subscription_{code}", status=409 if code == "out_of_stock" else 422)
    if cycle not in product_cycles(product):
        raise SubscriptionError("Select a delivery cycle offered for this product.", code="subscription_cycle_invalid", status=422)
    address = delivery_address(user, data)
    now = timezone.now()
    Sub.objects.filter(user=user, status=Sub.STATUS_PENDING, auth_expires_at__lt=now).delete()
    if Sub.objects.filter(user=user, status=Sub.STATUS_PENDING).count() >= PENDING_REGISTRATION_LIMIT:
        raise SubscriptionError(
            "Too many card registrations are in progress. Try again later.",
            code="subscription_registration_limit",
            status=429,
        )
    customer = billing_customer(user)
    token = secrets.token_urlsafe(32)
    sub = Sub.objects.create(
        user=user,
        product=product,
        it_id=product.it_id,
        it_name=product.it_name[:255],
        io_id=io_id[:255],
        qty=qty,
        cycle=cycle,
        status=Sub.STATUS_PENDING,
        customer_key=customer.customer_key,
        od_name=str(data.get("od_name") or "").strip()[:100] or member_display_name(user)[:100],
        od_email=(user.email or "")[:254],
        od_hp=str(data.get("od_hp") or address["od_b_hp"] or "").strip()[:50],
        od_memo=str(data.get("od_memo") or "").strip()[:255],
        auth_token_hash=_token_hash(token),
        auth_expires_at=now + REGISTRATION_TTL,
        auth_mode=mode,
        **address,
    )
    return registration_payload(sub, token, config)


def _owned(user, pk, *, lock=False):
    queryset = Sub.objects.filter(user=user).exclude(status=Sub.STATUS_PENDING)
    if lock:
        queryset = queryset.select_for_update()
    sub = queryset.filter(pk=_int(pk, 0)).first()
    if sub is None:
        raise SubscriptionError("Subscription not found.", code="subscription_not_found", status=404)
    return sub


def _busy_error():
    return SubscriptionError(
        "A payment for this subscription is being processed. Try again shortly.",
        code="subscription_charge_in_progress",
        status=409,
    )


def start_card_change(user, pk):
    """Open a card registration that replaces the card of an existing subscription."""
    require_feature()
    config, mode = toss_context()
    token = secrets.token_urlsafe(32)
    with transaction.atomic():
        sub = _owned(user, pk, lock=True)
        if sub.status == Sub.STATUS_CANCELLED:
            raise SubscriptionError("This subscription has been cancelled.", code="subscription_cancelled", status=409)
        if _has_pending_charge(sub):
            raise _busy_error()
        if not sub.customer_key:
            sub.customer_key = billing_customer(user).customer_key
        sub.auth_token_hash = _token_hash(token)
        sub.auth_expires_at = timezone.now() + REGISTRATION_TTL
        sub.auth_mode = mode
        sub.save(update_fields=["customer_key", "auth_token_hash", "auth_expires_at", "auth_mode", "updated_at"])
    return registration_payload(sub, token, config)


def discard_registration(user, token):
    """The billing window failed or was closed: forget the registration (a new subscription row
    goes, a card change leaves the subscription as it was)."""
    if not token:
        return False
    with transaction.atomic():
        sub = Sub.objects.select_for_update().filter(user=user, auth_token_hash=_token_hash(token)).first()
        if sub is None:
            return False
        if sub.status == Sub.STATUS_PENDING:
            sub.delete()
            return True
        sub.auth_token_hash = ""
        sub.auth_expires_at = None
        sub.save(update_fields=["auth_token_hash", "auth_expires_at", "updated_at"])
    return True


def _card_fields(billing):
    card = billing.get("card") if isinstance(billing.get("card"), dict) else {}
    company = str(billing.get("cardCompany") or "") or card_company_name(card.get("issuerCode"))
    return {
        "card_company": company[:50],
        "card_number": str(card.get("number") or billing.get("cardNumber") or "")[:30],
        "card_type": str(card.get("cardType") or "")[:20],
    }


@sensitive_variables("auth_key", "billing", "new_key", "old_key")
def complete_registration(user, token, auth_key, customer_key):
    """The billing window succeeded: check the authKey belongs to this member's pending
    registration, have Toss issue the billing key and keep it sealed. A new subscription is then
    charged for its first cycle at once; if that charge does not go through it is not started.

    Returns (subscription, ChargeResult or None for a card change)."""
    require_feature()
    token, auth_key, customer_key = str(token or ""), str(auth_key or ""), str(customer_key or "")
    if not token or not auth_key or not customer_key:
        raise SubscriptionError("The card registration result is incomplete.", code="subscription_auth_incomplete", status=422)
    refusal = None
    with transaction.atomic():
        sub = (
            Sub.objects.select_for_update()
            .filter(user=user, auth_token_hash=_token_hash(token))
            .exclude(status=Sub.STATUS_CANCELLED)
            .first()
        )
        if sub is None:
            raise SubscriptionError(
                "Card registration was not found or has expired.", code="subscription_registration_not_found", status=404
            )
        if not sub.auth_expires_at or sub.auth_expires_at < timezone.now():
            refusal = SubscriptionError(
                "Card registration was not found or has expired.", code="subscription_registration_not_found", status=404
            )
        elif not constant_time_compare(customer_key, sub.customer_key):
            refusal = SubscriptionError(
                "The card registration does not belong to this member.", code="subscription_customer_mismatch", status=409
            )
        is_new = sub.status == Sub.STATUS_PENDING
        mode = sub.auth_mode
        # one use only: a second submit of the success page finds nothing
        sub.auth_token_hash = ""
        sub.auth_expires_at = None
        sub.save(update_fields=["auth_token_hash", "auth_expires_at", "updated_at"])
    if refusal is not None:
        raise refusal

    try:
        billing = toss_billing.issue_billing_key(
            auth_key, customer_key, mode=mode, idempotency_key=f"gj-billing-{sub.pk}-{_token_hash(auth_key)[:32]}"
        )
    except TossBillingError as exc:
        Sub.objects.filter(pk=sub.pk).update(last_error=str(exc)[:255])
        raise SubscriptionError(
            "The card could not be registered.",
            code="subscription_card_rejected",
            status=502 if exc.uncertain else 400,
            details={"provider_code": exc.code, "provider_message": str(exc)},
        ) from None
    new_key = str(billing.get("billingKey") or "")
    if not new_key or str(billing.get("customerKey") or "") != customer_key:
        raise SubscriptionError(
            "Toss Payments returned an invalid billing response.", code="subscription_billing_invalid", status=502
        )

    today = timezone.localdate()
    if not is_new:
        with transaction.atomic():
            if _has_pending_charge(Sub.objects.select_for_update().get(pk=sub.pk)):
                # a charge is using the current card: keep it and drop the key just issued
                transaction.on_commit(lambda: toss_billing.delete_billing_key(new_key, mode=mode))
                refusal = _busy_error()
        if refusal is not None:
            raise refusal
    with transaction.atomic():
        sub = Sub.objects.select_for_update().get(pk=sub.pk)
        old_key, old_mode = billing_key(sub), sub.toss_mode
        sub.billing_key_sealed = seal(new_key, salt=BILLING_KEY_SALT, context=_seal_context(sub))
        sub.toss_mode = mode
        sub.card_registered_at = timezone.now()
        sub.last_error = ""
        for name, value in _card_fields(billing).items():
            setattr(sub, name, value)
        if is_new:
            sub.status = Sub.STATUS_ACTIVE
            sub.started_at = timezone.now()
            sub.next_charge_date = today
            sub.billing_day = today.day
            sub.cycle_no = 1
        sub.save()
        if old_key and old_key != new_key:
            # the replaced card's key is dropped at Toss once the new one is saved
            transaction.on_commit(lambda: toss_billing.delete_billing_key(old_key, mode=old_mode))
    if not is_new:
        return sub, None

    result = charge_subscription(sub.pk, today=today, source="first")
    # review: Toss answered with a payment the admin must look at; nothing is undone
    if result.status in {"charged", "pending", "review"}:
        sub.refresh_from_db()
        return sub, result
    with transaction.atomic():
        locked = Sub.objects.select_for_update().get(pk=sub.pk)
        end_subscription(locked, "첫 결제가 완료되지 않아 시작하지 않았습니다.", notify_member=False)
    raise SubscriptionError(
        "The first payment could not be made, so the subscription was not started.",
        code="subscription_first_charge_failed",
        status=402,
        details={"provider_code": result.code, "provider_message": result.message},
    )


# --- charging -------------------------------------------------------------------------------


def _order_name(sub):
    return f"[정기구독] {sub.it_name or sub.it_id}"[:100]


def _create_order(sub, product, order_id):
    """The 주문 order of one charge, built by the checkout's own order code."""
    from gnu_jango.api.v1_shop import create_order_from_lines
    from gnu_jango.shop.inventory import append_order_history, order_history_line

    data = {
        "od_name": sub.od_name or sub.od_b_name,
        "od_email": sub.od_email,
        "od_hp": sub.od_hp or sub.od_b_hp,
        "od_tel": sub.od_b_tel,
        "od_zip": sub.od_b_zip,
        "od_addr1": sub.od_b_addr1,
        "od_addr2": sub.od_b_addr2,
        "od_addr3": sub.od_b_addr3,
        "od_b_name": sub.od_b_name,
        "od_b_tel": sub.od_b_tel,
        "od_b_hp": sub.od_b_hp,
        "od_b_zip": sub.od_b_zip,
        "od_b_addr1": sub.od_b_addr1,
        "od_b_addr2": sub.od_b_addr2,
        "od_b_addr3": sub.od_b_addr3,
        "od_memo": sub.od_memo,
        "od_settle_case": SETTLE_CASE,
        "od_pg": "toss",
    }
    order = create_order_from_lines(
        sub.user, [charge_line(sub, product)], data, order_id=order_id, force_status="order", subscription=True
    )
    # the key pair the billing key belongs to: refunds of this order use it too (od_test)
    order.od_test = sub.toss_mode
    order.od_mod_history = append_order_history(
        order.od_mod_history, order_history_line(f"정기구독 #{sub.pk} {sub.cycle_no}회차 자동결제 주문", "system")
    )
    order._change_reason = "Subscription charge order"
    order.save(update_fields=["od_test", "od_mod_history"])
    return order


def charge_subscription(subscription_id, *, today=None, source="schedule", force=False):
    """Charge the current cycle of a subscription once. ``force`` (the admin's retry) charges an
    active or payment-paused subscription that is not due yet. Never raises for a refused card."""
    from gnu_jango.api.shop_common import generate_numeric_order_id
    from gnu_jango.shop.inventory import StockAdjustmentError

    today = today or timezone.localdate()
    with transaction.atomic():
        sub = Sub.objects.select_for_update().select_related("user").filter(pk=subscription_id).first()
        if sub is None:
            return ChargeResult("missing")
        payment_paused = sub.status == Sub.STATUS_PAUSED and sub.pause_reason == Sub.PAUSE_PAYMENT
        if sub.status != Sub.STATUS_ACTIVE and not (force and payment_paused):
            return ChargeResult("inactive")
        if force:
            # the admin retries a failed cycle; it never charges a cycle early
            failed_now = sub.charges.filter(cycle_no=sub.cycle_no, status=Charge.STATUS_FAILED).exists()
            if not (payment_paused or failed_now or is_due(sub, today)):
                return ChargeResult("not_due")
        elif not is_due(sub, today):
            return ChargeResult("not_due")
        if not sub.user.is_active:
            end_subscription(sub, "회원 계정을 사용할 수 없어 해지했습니다.", notify_member=False)
            return ChargeResult("cancelled")
        if not billing_key(sub):
            pause_subscription(sub, Sub.PAUSE_PAYMENT, "등록된 카드가 없습니다. 카드를 다시 등록해 주세요.")
            return ChargeResult("paused")
        if sub.charges.filter(cycle_no=sub.cycle_no, status__in=OPEN_CHARGE_STATUSES).exists():
            return ChargeResult("already")
        attempt = _next_attempt(sub)
        order_id = generate_numeric_order_id()
        try:
            with transaction.atomic():
                charge = Charge.objects.create(
                    subscription=sub,
                    cycle_no=sub.cycle_no,
                    attempt=attempt,
                    scheduled_date=sub.next_charge_date or today,
                    source=source,
                    od_id=order_id,
                    idempotency_key=f"gj-sub-{sub.pk}-{sub.cycle_no}-{attempt}-{secrets.token_hex(6)}",
                )
        except IntegrityError:
            # another run claimed this cycle first
            return ChargeResult("already")
        product = ShopProduct.objects.filter(pk=sub.it_id).first()
        code = product_unavailable_code(product, sub.io_id, sub.qty)
        if code:
            return _skip(sub, charge, code, today)
        try:
            with transaction.atomic():
                order = _create_order(sub, product, order_id)
        except StockAdjustmentError as exc:
            return _skip(sub, charge, "out_of_stock" if exc.code in STOCK_ERROR_CODES else "product_unavailable", today)
        except Exception:  # noqa: BLE001 - the attempt fails and is retried like a declined card
            logger.exception("subscription %s: the charge order could not be created", sub.pk)
            message = "주문을 만들지 못해 결제하지 않았습니다."
            charge.status = Charge.STATUS_FAILED
            charge.failure_code = "order_error"
            charge.failure_message = message
            charge.save(update_fields=["status", "failure_code", "failure_message", "updated_at"])
            if charge.source != "first":
                _count_failure(sub, charge, message, today)
            return ChargeResult("failed", charge, message=message, code="order_error")
        charge.order = order
        charge.amount = int(order.od_receipt_price or 0)
        charge.save(update_fields=["order", "amount", "updated_at"])
    return _approve(charge.pk, today=today)


def _skip(sub, charge, code, today):
    """This cycle cannot be charged (``sub`` is locked): note why, move on to the next cycle (or
    pause when the product is gone) and tell the member."""
    message = UNAVAILABLE[code][1]
    charge.status = Charge.STATUS_SKIPPED
    charge.failure_code = code
    charge.failure_message = message
    charge.save(update_fields=["status", "failure_code", "failure_message", "updated_at"])
    if charge.source == "first":
        return ChargeResult("skipped", charge, message=message, code=code)
    if code == "product_missing":
        pause_subscription(sub, Sub.PAUSE_ADMIN, message)
        return ChargeResult("paused", charge, message=message, code=code)
    skipped_date = due_date(sub)
    advance_cycle(sub, today)
    sub.last_error = message
    sub.save()
    notify(sub, "skipped", charge=charge, reason=message, skipped_date=skipped_date)
    return ChargeResult("skipped", charge, message=message, code=code)


def _approve(charge_pk, *, today):
    from gnu_jango.api.shop_payments import toss_tax_free_amount

    charge = Charge.objects.select_related("subscription", "order").get(pk=charge_pk)
    sub = charge.subscription
    try:
        payment = toss_billing.charge_billing_key(
            billing_key(sub),
            mode=sub.toss_mode,
            customer_key=sub.customer_key,
            amount=charge.amount,
            order_id=charge.od_id,
            order_name=_order_name(sub),
            idempotency_key=charge.idempotency_key,
            customer_email=sub.od_email,
            customer_name=sub.od_name,
            tax_free_amount=toss_tax_free_amount(charge.order) if charge.order else 0,
        )
    except TossBillingError as exc:
        if exc.uncertain:
            # the answer was lost: reconcile_stale_charges looks the orderId up later
            Charge.objects.filter(pk=charge.pk).update(failure_code=exc.code[:64], failure_message=str(exc)[:255])
            return ChargeResult("pending", charge, message=str(exc), code=exc.code)
        return record_failure(charge.pk, exc.code, str(exc), today=today, inline=True)
    return record_payment(charge.pk, payment, today=today)


def _without_secrets(payment):
    return {key: value for key, value in payment.items() if key not in {"billingKey", "secret"}}


def _mark_review(charge_pk, code, message, payment=None):
    """Leave a charge for the admin (확인 필요). When Toss approved a payment for this charge's own
    orderId, its paymentKey goes on the order: the unpaid-order expiry then leaves the order alone
    and the admin can refund it through the order's Toss cancel."""
    updated = Charge.objects.filter(pk=charge_pk, status=Charge.STATUS_PENDING).update(
        status=Charge.STATUS_REVIEW, failure_code=code[:64], failure_message=message[:255]
    )
    payment = payment if isinstance(payment, dict) else {}
    payment_key_value = str(payment.get("paymentKey") or "")[:255]
    charge = Charge.objects.filter(pk=charge_pk).first()
    if updated and charge and charge.order_id and payment_key_value and str(payment.get("orderId") or "") == charge.od_id:
        ShopOrder.objects.filter(pk=charge.order_id, od_tno="").update(od_tno=payment_key_value, od_pg="toss")
        Charge.objects.filter(pk=charge_pk).update(payment_key=payment_key_value[:200])
    logger.error("subscription charge %s needs review: %s", charge_pk, code)


def record_payment(charge_pk, payment, *, today=None):
    """Toss approved the charge: mark its order paid (the checkout's confirm_order_payment) and
    close the cycle. A payment that does not match the charge is left for the admin (확인 필요)."""
    from gnu_jango.api.shop_payments import confirm_order_payment, note_toss_payment_terms, safe_amount_int

    today = today or timezone.localdate()
    charge = Charge.objects.select_related("subscription").get(pk=charge_pk)
    if charge.status != Charge.STATUS_PENDING:
        return ChargeResult("already", charge)
    payment = payment if isinstance(payment, dict) else {}
    if str(payment.get("orderId") or "") != charge.od_id:
        _mark_review(charge.pk, "order_mismatch", "토스페이먼츠 결제의 주문번호가 이 결제와 다릅니다.")
        return ChargeResult("review", charge)
    if str(payment.get("status") or "").upper() != "DONE":
        _mark_review(charge.pk, "not_done", f"토스페이먼츠 결제 상태가 완료가 아닙니다: {payment.get('status')}", payment)
        return ChargeResult("review", charge)
    if safe_amount_int(payment.get("totalAmount"), -1) != charge.amount:
        _mark_review(charge.pk, "amount_mismatch", "토스페이먼츠 승인 금액이 주문 금액과 다릅니다.", payment)
        return ChargeResult("review", charge)
    payment_key_value = str(payment.get("paymentKey") or "")
    raw = {"toss_payment": _without_secrets(payment), "subscription_id": charge.subscription_id, "cycle_no": charge.cycle_no}
    order, error = confirm_order_payment(charge.od_id, charge.amount, "toss", payment_key_value, raw, log_prefix="sub")
    if error is not None:
        _mark_review(charge.pk, "order_not_confirmed", "결제는 승인되었지만 주문을 결제완료로 바꾸지 못했습니다.", payment)
        return ChargeResult("review", charge)
    note_toss_payment_terms(order, payment)
    with transaction.atomic():
        sub = Sub.objects.select_for_update().get(pk=charge.subscription_id)
        charge = Charge.objects.select_for_update().get(pk=charge.pk)
        if charge.status != Charge.STATUS_PENDING:
            return ChargeResult("already", charge)
        charge.status = Charge.STATUS_DONE
        charge.payment_key = payment_key_value[:200]
        charge.failure_code = ""
        charge.failure_message = ""
        charge.save(update_fields=["status", "payment_key", "failure_code", "failure_message", "updated_at"])
        if sub.cycle_no == charge.cycle_no:
            advance_cycle(sub, today)
        if sub.status == Sub.STATUS_PAUSED and sub.pause_reason == Sub.PAUSE_PAYMENT:
            sub.status = Sub.STATUS_ACTIVE
            sub.pause_reason = ""
        sub.last_error = ""
        sub.save()
        notify(sub, "charged", charge=charge, order=order)
    return ChargeResult("charged", charge)


def _count_failure(sub, charge, message, today):
    """One more failed attempt of the current cycle (``sub`` locked): retry tomorrow, or pause
    after de_subscription_retry_limit failures, and tell the member."""
    if sub.cycle_no != charge.cycle_no or sub.status not in {Sub.STATUS_ACTIVE, Sub.STATUS_PAUSED}:
        return
    sub.failure_count += 1
    sub.last_error = message[:255]
    if sub.failure_count >= retry_limit():
        sub.status = Sub.STATUS_PAUSED
        sub.pause_reason = Sub.PAUSE_PAYMENT
        sub.retry_date = None
        kind = "paused"
    else:
        sub.retry_date = today + timedelta(days=1)
        kind = "failed"
    sub.save()
    notify(sub, kind, charge=charge, reason=message)


def record_failure(charge_pk, code, message, *, today=None, inline=False):
    """Toss declined the charge: cancel its order (stock, coupons and points go back), then try
    again tomorrow or, after de_subscription_retry_limit failures, pause the subscription.
    ``inline``: decided during the charge call itself (complete_registration ends a subscription
    whose first charge fails there); a first charge settled later by reconcile ends it here."""
    from gnu_jango.api.shop_common import CANCELLED_STATUSES
    from gnu_jango.api.v1_shop import cancel_order_and_refund_benefits
    from gnu_jango.notifications.context import suppress_notification_events
    from gnu_jango.shop.inventory import order_history_line

    today = today or timezone.localdate()
    charge = Charge.objects.select_related("order").get(pk=charge_pk)
    if charge.status != Charge.STATUS_PENDING:
        return ChargeResult("already", charge)
    if charge.order is not None and str(charge.order.od_status or "") not in CANCELLED_STATUSES:
        # the order was never paid: the member hears about the failed charge, not a 주문→취소
        with suppress_notification_events():
            cancel_order_and_refund_benefits(
                charge.order, "", history=order_history_line("정기구독 자동결제 실패로 주문 취소", "system")
            )
    message = str(message or "") or "결제가 승인되지 않았습니다."
    with transaction.atomic():
        sub = Sub.objects.select_for_update().get(pk=charge.subscription_id)
        charge = Charge.objects.select_for_update().get(pk=charge.pk)
        if charge.status != Charge.STATUS_PENDING:
            return ChargeResult("already", charge)
        charge.status = Charge.STATUS_FAILED
        charge.failure_code = str(code or "")[:64]
        charge.failure_message = message[:255]
        charge.save(update_fields=["status", "failure_code", "failure_message", "updated_at"])
        first = charge.source == "first" and not sub.charges.filter(status=Charge.STATUS_DONE).exists()
        if first and inline:
            return ChargeResult("failed", charge, message=message, code=charge.failure_code)
        if first:
            if sub.status != Sub.STATUS_CANCELLED:
                end_subscription(sub, f"첫 결제가 완료되지 않아 정기구독을 시작하지 않았습니다({message}).")
            return ChargeResult("failed", charge, message=message, code=charge.failure_code)
        _count_failure(sub, charge, message, today)
    return ChargeResult("failed", charge, message=message, code=charge.failure_code)


def reconcile_stale_charges(*, now=None, limit=50):
    """Settle charges whose Toss answer was lost, from Toss's record of their orderId."""
    now = now or timezone.now()
    report = {"stale": 0, "charged": 0, "failed": 0, "unresolved": 0}
    stale = (
        Charge.objects.filter(status=Charge.STATUS_PENDING, updated_at__lt=now - STALE_CHARGE_AGE)
        .select_related("subscription")
        .order_by("updated_at")[:limit]
    )
    for charge in stale:
        report["stale"] += 1
        if charge.order_id is None:
            record_failure(charge.pk, "order_missing", "결제할 주문이 없습니다.")
            report["failed"] += 1
            continue
        try:
            payment = toss_billing.payment_by_order_id(charge.od_id, mode=charge.subscription.toss_mode)
        except TossBillingError:
            report["unresolved"] += 1
            continue
        status = str((payment or {}).get("status") or "").upper()
        if payment is None or status in {"ABORTED", "EXPIRED", "CANCELED"}:
            record_failure(charge.pk, "NOT_FOUND_PAYMENT", "토스페이먼츠에 승인된 결제가 없어 실패로 처리했습니다.")
            report["failed"] += 1
        elif status == "DONE":
            result = record_payment(charge.pk, payment)
            report["charged" if result.status == "charged" else "unresolved"] += 1
        else:
            report["unresolved"] += 1
    return report


# --- member and admin changes ---------------------------------------------------------------


def pause_subscription(sub, reason, message=""):
    """Pause ``sub`` (locked by the caller) and tell the member."""
    sub.status = Sub.STATUS_PAUSED
    sub.pause_reason = reason
    sub.retry_date = None
    if message:
        sub.last_error = message[:255]
    sub.save()
    if reason != Sub.PAUSE_MEMBER:
        notify(sub, "paused", reason=message)


@sensitive_variables("old_key")
def end_subscription(sub, reason="", *, notify_member=True):
    """Cancel ``sub`` (locked by the caller) and drop its billing key, at Toss too once committed."""
    old_key, mode = billing_key(sub), sub.toss_mode
    sub.status = Sub.STATUS_CANCELLED
    sub.pause_reason = ""
    sub.cancelled_at = timezone.now()
    sub.retry_date = None
    sub.billing_key_sealed = ""
    sub.auth_token_hash = ""
    sub.auth_expires_at = None
    if reason:
        sub.last_error = reason[:255]
    sub.save()
    if old_key:
        transaction.on_commit(lambda: toss_billing.delete_billing_key(old_key, mode=mode))
    if notify_member:
        notify(sub, "cancelled", reason=reason)


def _state_error():
    return SubscriptionError(
        "This change is not possible in the subscription's current state.", code="subscription_state_invalid", status=409
    )


def skip_next(sub, today, *, source="member"):
    """Leave out the current cycle (``sub`` locked, active, nothing pending)."""
    Charge.objects.create(
        subscription=sub,
        cycle_no=sub.cycle_no,
        attempt=_next_attempt(sub),
        scheduled_date=due_date(sub) or today,
        status=Charge.STATUS_SKIPPED,
        source=source,
        idempotency_key=f"gj-sub-{sub.pk}-{sub.cycle_no}-skip-{secrets.token_hex(6)}",
        failure_code="skipped_by_request",
        failure_message="요청으로 이번 회차를 건너뛰었습니다.",
    )
    advance_cycle(sub, today)


def member_action(user, pk, action, *, cycle=""):
    """pause | resume | skip | cycle | cancel, by the member who owns the subscription."""
    require_feature()
    today = timezone.localdate()
    with transaction.atomic():
        sub = _owned(user, pk, lock=True)
        if sub.status == Sub.STATUS_CANCELLED:
            raise SubscriptionError("This subscription has been cancelled.", code="subscription_cancelled", status=409)
        if _has_pending_charge(sub):
            raise _busy_error()
        if action == "pause":
            if sub.status != Sub.STATUS_ACTIVE:
                raise _state_error()
            pause_subscription(sub, Sub.PAUSE_MEMBER)
        elif action == "resume":
            # an admin pause (or a product that is gone) is not the member's to lift
            if sub.status != Sub.STATUS_PAUSED or sub.pause_reason not in {Sub.PAUSE_MEMBER, Sub.PAUSE_PAYMENT}:
                raise _state_error()
            if not billing_key(sub):
                raise SubscriptionError("Register a card before resuming.", code="subscription_card_required", status=409)
            sub.status = Sub.STATUS_ACTIVE
            sub.pause_reason = ""
            sub.failure_count = 0
            sub.retry_date = None
            sub.last_error = ""
            # a resumed subscription is charged from tomorrow at the earliest, never on the click
            if not sub.next_charge_date or sub.next_charge_date <= today:
                sub.next_charge_date = today + timedelta(days=1)
                sub.billing_day = sub.next_charge_date.day
            sub.save()
        elif action == "skip":
            if sub.status != Sub.STATUS_ACTIVE:
                raise _state_error()
            skip_next(sub, today)
            sub.save()
        elif action == "cycle":
            offered = product_cycles(sub.product) if sub.product_id else ()
            if cycle not in offered:
                raise SubscriptionError(
                    "Select a delivery cycle offered for this product.", code="subscription_cycle_invalid", status=422
                )
            sub.cycle = cycle
            if cycle == "1m" and sub.next_charge_date:
                sub.billing_day = sub.next_charge_date.day
            sub.save()
        elif action == "cancel":
            end_subscription(sub, "회원 요청으로 해지했습니다.")
        else:
            raise SubscriptionError("Unknown subscription action.", code="subscription_action_invalid", status=422)
    return sub


def admin_pause(sub_pk):
    with transaction.atomic():
        sub = Sub.objects.select_for_update().filter(pk=sub_pk).first()
        if sub is None or sub.status != Sub.STATUS_ACTIVE or _has_pending_charge(sub):
            return False
        pause_subscription(sub, Sub.PAUSE_ADMIN, "쇼핑몰 운영자가 정기구독을 일시정지했습니다.")
    return True


def admin_cancel(sub_pk):
    with transaction.atomic():
        sub = Sub.objects.select_for_update().filter(pk=sub_pk).first()
        if sub is None or sub.status in {Sub.STATUS_CANCELLED, Sub.STATUS_PENDING} or _has_pending_charge(sub):
            return False
        end_subscription(sub, "쇼핑몰 운영자가 정기구독을 해지했습니다.")
    return True


def admin_retry(sub_pk):
    """Charge the current cycle of an active or payment-paused subscription now."""
    return charge_subscription(sub_pk, source="admin", force=True)


# --- notices --------------------------------------------------------------------------------


def _format_date(value):
    return value.strftime("%Y-%m-%d") if value else "-"


def _notice_body(sub, kind, *, charge=None, order=None, reason="", skipped_date=None):
    item = f"{sub.it_name or sub.it_id} {sub.qty}개"
    if kind == "upcoming":
        amount = estimated_amount(sub)
        estimate = f" 현재 가격 기준 예상 금액은 {amount:,}원입니다." if amount is not None else ""
        return (
            f"{item} 정기구독이 {_format_date(sub.next_charge_date)}에 결제됩니다. 결제 금액은 결제하는 날의 "
            f"상품 가격으로 정해집니다.{estimate}"
        )
    if kind == "charged":
        return f"{item} {charge.cycle_no}회차 {charge.amount:,}원을 결제했습니다. 주문번호 {charge.od_id}"
    if kind == "failed":
        return f"{item} 결제에 실패했습니다({reason}). {_format_date(sub.retry_date)}에 다시 결제합니다."
    if kind == "paused":
        if sub.pause_reason == Sub.PAUSE_PAYMENT and charge is not None:
            return (
                f"{item} 결제가 {sub.failure_count}회 실패해 정기구독을 일시정지했습니다({reason}). "
                "카드를 변경한 뒤 다시 시작해 주세요."
            )
        return f"{item} 정기구독을 일시정지했습니다. {reason}".strip()
    if kind == "skipped":
        return (
            f"{reason} {item} {_format_date(skipped_date)} 회차는 건너뛰었고 다음 결제일은 "
            f"{_format_date(sub.next_charge_date)}입니다."
        )
    return f"{item} 정기구독이 해지되었습니다. {reason}".strip()


def notify(sub, kind, *, charge=None, order=None, reason="", skipped_date=None):
    """The member's in-app notification and mail about ``sub`` (sent once the change commits)."""
    from gnu_jango.notifications.outbox import event_on_commit

    from .notifications import queue_subscription_mail

    title = NOTICE_TITLES[kind]
    body = _notice_body(sub, kind, charge=charge, order=order, reason=reason, skipped_date=skipped_date)
    href = f"/shop/orders/{order.od_id}" if order is not None else "/mypage/subscriptions"
    cycle_no = charge.cycle_no if charge is not None else sub.cycle_no
    attempt = charge.attempt if charge is not None else 0
    event_on_commit(sub.user_id, f"subscription:{sub.pk}:{kind}:{cycle_no}:{attempt}", {
        "nt_type": "subscription",
        "nt_title": title,
        "nt_body": body,
        "nt_data": {"href": href, "subscription_id": sub.pk},
    })
    queue_subscription_mail(sub, title=title, body=body, path=href)


def send_upcoming_notices(today, *, apply=True, limit=500):
    """결제 예정 안내 for active subscriptions charged within de_subscription_notice_days, once a cycle."""
    target = today + timedelta(days=notice_days())
    due = Sub.objects.filter(
        status=Sub.STATUS_ACTIVE,
        retry_date__isnull=True,
        next_charge_date__gt=today,
        next_charge_date__lte=target,
        notice_cycle_no__lt=F("cycle_no"),
    ).order_by("next_charge_date", "pk")
    if not apply:
        return due.count()
    sent = 0
    for sub in due[:limit]:
        # claim the notice first: a second run (or worker) finds it sent
        if Sub.objects.filter(pk=sub.pk, notice_cycle_no__lt=sub.cycle_no).update(notice_cycle_no=sub.cycle_no):
            notify(sub, "upcoming")
            sent += 1
    return sent


def cleanup_registrations(now):
    """Forget card registrations that were never finished."""
    removed, _ = Sub.objects.filter(status=Sub.STATUS_PENDING, created_at__lt=now - timedelta(days=1)).delete()
    Sub.objects.exclude(auth_token_hash="").filter(auth_expires_at__lt=now).update(auth_token_hash="", auth_expires_at=None)
    return removed


def due_subscriptions(today):
    return Sub.objects.filter(status=Sub.STATUS_ACTIVE).filter(
        Q(retry_date__lte=today) | Q(retry_date__isnull=True, next_charge_date__lte=today)
    ).order_by("next_charge_date", "pk")


def run_scheduled(*, today=None, apply=False, limit=100):
    """The daily job (charge_shop_subscriptions): settle lost answers, charge what is due, send the
    결제 예정 notices and drop stale registrations. Without ``apply`` it only counts."""
    today = today or timezone.localdate()
    now = timezone.now()
    summary = {
        "enabled": feature_enabled(), "applied": bool(apply), "date": today.isoformat(), "due": 0, "charged": 0,
        "failed": 0, "skipped": 0, "pending": 0, "review": 0, "other": 0, "reconciled": 0, "notices": 0,
        "registrations_removed": 0, "samples": [],
    }
    if not summary["enabled"]:
        return summary
    due_ids = list(due_subscriptions(today).values_list("pk", flat=True)[:limit])
    summary["due"] = len(due_ids)
    if not apply:
        summary["notices"] = send_upcoming_notices(today, apply=False)
        return summary
    reconciled = reconcile_stale_charges(now=now)
    summary["reconciled"] = reconciled["charged"] + reconciled["failed"]
    for pk in due_ids:
        try:
            result = charge_subscription(pk, today=today)
        except Exception:  # noqa: BLE001 - one subscription must not stop the others
            logger.exception("subscription %s could not be charged", pk)
            result = ChargeResult("error")
        key = result.status if result.status in {"charged", "failed", "skipped", "pending", "review"} else "other"
        summary[key] += 1
        if len(summary["samples"]) < 20:
            summary["samples"].append({"subscription": pk, "result": result.status, "order_id": result.order_id})
    summary["notices"] = send_upcoming_notices(today)
    summary["registrations_removed"] = cleanup_registrations(now)
    return summary
