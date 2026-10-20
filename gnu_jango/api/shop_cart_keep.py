"""YoungCart cart keeping rules: the cart keep term and the guest cart lifetime.

* ``de_cart_keep_term`` (lib/shop.lib.php cart_item_clean): a cart line put in the cart more than
  this many days ago is dropped. Each stored line carries ``ct_time`` (unix seconds of when it was put
  in the cart, kept when the same option is added again, like youngcart's ct_time). A line stored
  before ``ct_time`` existed is treated as put in the cart now, so existing carts are not emptied.
* ``de_guest_cart_use`` (lib/shop.lib.php set_cart_id): a guest cart survives the browser session for
  the keep term. The guest cart lives in the Django session, so the session itself is kept that long
  while it holds a cart; when the option is off it keeps the default sliding session lifetime.
"""

from django.utils import timezone

from gnu_jango.shop.shop_options import shop_options

CART_TIME_KEY = "ct_time"
SECONDS_PER_DAY = 86400
# Session flag: this guest session was given the long cart lifetime (so it can be taken back).
GUEST_CART_KEEP_FLAG = "g5_guest_cart_keep"
_REQUEST_CACHE_ATTR = "_g5_cart_keep_options"


def cart_now():
    return int(timezone.now().timestamp())


def cart_keep_options(request=None):
    """``(guest_cart_use, keep_term_days)``, read once per request."""
    cached = getattr(request, _REQUEST_CACHE_ATTR, None) if request is not None else None
    if cached is not None:
        return cached
    opts = shop_options("de_guest_cart_use", "de_cart_keep_term")
    value = (bool(opts["de_guest_cart_use"]), max(1, int(opts["de_cart_keep_term"])))
    if request is not None:
        try:
            setattr(request, _REQUEST_CACHE_ATTR, value)
        except AttributeError:
            pass
    return value


def _row_time(row):
    value = row.get(CART_TIME_KEY)
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def prune_cart_rows(rows, keep_term_days, now=None):
    """Drop lines older than the keep term and stamp lines without a time.

    Returns ``(rows, changed)``; the input list and its dicts are not modified.
    """
    now = cart_now() if now is None else now
    cutoff = now - keep_term_days * SECONDS_PER_DAY
    kept = []
    changed = False
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            changed = True
            continue
        put_at = _row_time(row)
        if put_at is None:
            kept.append({**row, CART_TIME_KEY: now})
            changed = True
        elif put_at < cutoff:
            changed = True
        else:
            kept.append(row)
    return kept, changed


def keep_guest_cart_session(request, has_items):
    """Give a guest session holding a cart the keep-term lifetime when de_guest_cart_use is on."""
    session = getattr(request, "session", None)
    if session is None:
        return
    guest_cart_use, keep_term = cart_keep_options(request)
    if guest_cart_use and has_items:
        session.set_expiry(keep_term * SECONDS_PER_DAY)
        session[GUEST_CART_KEEP_FLAG] = True
    elif session.get(GUEST_CART_KEEP_FLAG):
        reset_guest_cart_session(request)


def reset_guest_cart_session(request):
    """Back to the default sliding session lifetime (at sign-in, or when the guest cart is gone)."""
    session = getattr(request, "session", None)
    if session is None:
        return
    if session.pop(GUEST_CART_KEEP_FLAG, None) is not None:
        session.set_expiry(None)
