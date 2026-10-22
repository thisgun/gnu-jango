from html import unescape
import re

from django.utils.html import strip_tags

from .models import ShopShippingCost, ShopShippingPolicy


# product-level fallbacks of a cart line whose product is gone (it_sc_price / it_sc_minimum)
DEFAULT_SHIPPING_COST = 3000
DEFAULT_FREE_THRESHOLD = 50000

SEND_COST_CASE_TIERED = "차등"
SEND_COST_CASE_FREE = "무료"
# youngcart install/install_db.php: a new shop starts with 금액별차등 - under 20,000 4,000, under
# 30,000 3,000, under 40,000 2,000 and free from 40,000. Used until the settings are saved once.
INSTALL_SEND_COST_LIMIT = "20000;30000;40000"
INSTALL_SEND_COST_LIST = "4000;3000;2000"

# ct_send_cost of a cart line (YoungCart g5_shop_cart.ct_send_cost)
SEND_COST_PREPAID = 0
SEND_COST_ON_DELIVERY = 1  # 착불: the customer pays the courier, not the order
SEND_COST_FREE = 2  # 무료
# it_sc_method of a product
SC_METHOD_ON_DELIVERY = 1
SC_METHOD_CUSTOMER_CHOICE = 2


def _flag_value(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return SEND_COST_PREPAID


def cart_send_cost_flag(product, chosen=SEND_COST_PREPAID):
    """The ct_send_cost a cart line of this product carries, decided by the server.

    YoungCart cartupdate.php: free shipping products (it_sc_type 1) are 2, products with their own
    fee paid on delivery (it_sc_type > 1, it_sc_method 1) are 1, everything else 0. A client value
    never sets it; only where the product lets the customer pick (it_sc_method 2) is their pick
    between prepaid (0) and on delivery (1) kept.
    """
    if product is None:
        return SEND_COST_PREPAID
    sc_type = int(product.it_sc_type or 0)
    if sc_type == 1:
        return SEND_COST_FREE
    if sc_type > 1:
        method = int(product.it_sc_method or 0)
        if method == SC_METHOD_ON_DELIVERY:
            return SEND_COST_ON_DELIVERY
        if method == SC_METHOD_CUSTOMER_CHOICE and _flag_value(chosen) == SEND_COST_ON_DELIVERY:
            return SEND_COST_ON_DELIVERY
    return SEND_COST_PREPAID


def with_server_send_cost_flags(rows):
    """Copies of the cart rows with ct_send_cost recomputed from the current products."""
    from .models import ShopProduct

    rows = list(rows)
    it_ids = {str(row.get("it_id") or "") for row in rows if isinstance(row, dict)}
    products = ShopProduct.objects.in_bulk(list(it_ids)) if it_ids else {}
    return [
        {**row, "ct_send_cost": cart_send_cost_flag(products.get(str(row.get("it_id") or "")), row.get("ct_send_cost"))}
        if isinstance(row, dict)
        else row
        for row in rows
    ]


def current_shipping_policy():
    return ShopShippingPolicy.objects.filter(pk=1).first() or ShopShippingPolicy(
        pk=1,
        de_delivery_company="Default courier",
        de_send_cost_case=SEND_COST_CASE_TIERED,
        de_send_cost_limit=INSTALL_SEND_COST_LIMIT,
        de_send_cost_list=INSTALL_SEND_COST_LIST,
    )


def _digits(value):
    return re.sub(r"[^0-9]", "", str(value or ""))


def _money(value):
    return int(_digits(value) or 0)


def shipping_rules(policy=None):
    policy = policy or current_shipping_policy()
    limits = str(policy.de_send_cost_limit or "").split(";")
    costs = str(policy.de_send_cost_list or "").split(";")
    rules = []
    for index, raw_limit in enumerate(limits):
        limit = _money(raw_limit)
        if limit <= 0:
            continue
        rules.append({"limit": limit, "cost": max(0, _money(costs[index] if index < len(costs) else 0))})
    return sorted(rules, key=lambda rule: rule["limit"])


def active_shipping_rules(policy=None):
    """The amount tiers in force: only 금액별차등 (차등) charges by tier; any other case charges no
    shared shipping fee (youngcart get_sendcost)."""
    policy = policy or current_shipping_policy()
    if str(policy.de_send_cost_case or "").strip() != SEND_COST_CASE_TIERED:
        return []
    return shipping_rules(policy)


def shipping_free_threshold(policy=None):
    """The order amount from which the shared shipping fee is 0 (0: it is always 0)."""
    return max((rule["limit"] for rule in active_shipping_rules(policy)), default=0)


def base_shipping_cost(item_total, policy=None):
    """youngcart get_sendcost: the shared fee of the products without a shipping type of their
    own. 차등 charges the cost of the first tier whose limit the amount is under and 0 past the last
    one; 무료, an empty case or 차등 without tiers charge 0."""
    item_total = max(0, int(item_total or 0))
    for rule in active_shipping_rules(policy):
        if item_total < rule["limit"]:
            return rule["cost"]
    return 0


def extra_shipping_cost(postal_code):
    postal_code = _digits(postal_code)
    if not postal_code:
        return 0
    rule = (
        ShopShippingCost.objects.filter(sc_zip1__lte=postal_code, sc_zip2__gte=postal_code)
        .order_by("sc_id")
        .only("sc_price")
        .first()
    )
    return max(0, int(rule.sc_price or 0)) if rule else 0


def items_shipping_cost(items, policy=None):
    """YoungCart get_sendcost / get_item_sendcost over cart lines (it_id, line_total, ct_qty).

    Per product: 1 free; 2 free from its own minimum, else its fee; 3 its fee; 4 its fee per started
    batch of it_sc_qty. Products without a type of their own (0) share the shop rule on their
    combined price. Lines paid on delivery or shipped free (ct_send_cost) are left out; the flag
    comes from the current product, never from what the cart line stored or a client sent.
    """
    from math import ceil

    from .models import ShopProduct

    items = list(items)
    products = ShopProduct.objects.in_bulk(list({str(item.get("it_id")) for item in items}))
    groups = {}
    for item in items:
        it_id = str(item.get("it_id"))
        if cart_send_cost_flag(products.get(it_id), item.get("ct_send_cost")) != SEND_COST_PREPAID:
            continue
        group = groups.setdefault(it_id, [0, 0])
        group[0] += max(0, int(item.get("line_total") or 0))
        group[1] += max(0, int(item.get("ct_qty") or 0))
    total = 0
    shared_price = 0
    for it_id, (price, qty) in groups.items():
        product = products.get(it_id)
        sc_type = int(product.it_sc_type or 0) if product else 0
        if sc_type == 1:
            continue
        if sc_type == 2:
            total += 0 if price >= int(product.it_sc_minimum or 0) else int(product.it_sc_price or 0)
        elif sc_type == 3:
            total += int(product.it_sc_price or 0)
        elif sc_type >= 4:
            total += int(product.it_sc_price or 0) * ceil(qty / max(1, int(product.it_sc_qty or 0)))
        else:
            shared_price += price
    if shared_price > 0:
        total += base_shipping_cost(shared_price, policy)
    return total


def shipping_quote(item_total, postal_code="", policy=None, items=None):
    item_total = max(0, int(item_total or 0))
    if item_total == 0:
        return {"base": 0, "extra": 0, "total": 0}
    base = items_shipping_cost(items, policy) if items is not None else base_shipping_cost(item_total, policy)
    extra = extra_shipping_cost(postal_code)
    return {"base": base, "extra": extra, "total": base + extra}


def shipping_policy_payload(policy=None):
    policy = policy or current_shipping_policy()
    rules = active_shipping_rules(policy)
    return {
        "de_admin_company_name": policy.de_admin_company_name,
        "de_admin_company_tel": policy.de_admin_company_tel,
        "delivery_company": policy.de_delivery_company or "Default courier",
        "send_cost_case": policy.de_send_cost_case,
        "send_cost_limit": policy.de_send_cost_limit,
        "send_cost_list": policy.de_send_cost_list,
        "shipping_rules": rules,
        "base_shipping_cost": base_shipping_cost(0, policy),
        "free_threshold": shipping_free_threshold(policy),
        "delivery_content": policy.de_baesong_content,
        "delivery_content_text": unescape(strip_tags(policy.de_baesong_content or "")).strip(),
        "exchange_content": policy.de_change_content,
        "exchange_content_text": unescape(strip_tags(policy.de_change_content or "")).strip(),
        "review_requires_completed_order": int(policy.de_item_use_write or 0) == 1,
        "review_requires_moderation": int(policy.de_item_use_use or 0) == 1,
        "point_use_enabled": True,
        "settle_min_point": int(policy.de_settle_min_point or 0),
        "settle_max_point": int(policy.de_settle_max_point or 0),
        "settle_point_unit": int(policy.de_settle_point_unit or 1),
    }


def allowed_point_use(requested, balance, payable_amount, policy=None):
    """Points a member may pay with: the YoungCart rule the checkout form also applies.

    The balance must reach the minimum; the use is capped by the balance, the maximum and the
    amount still to pay, and rounded down to a multiple of the unit.
    """
    from gnu_jango.users.point_ledger import points_enabled

    if not points_enabled():
        return 0
    policy = policy or current_shipping_policy()
    balance = max(0, int(balance or 0))
    if balance < max(0, int(policy.de_settle_min_point or 0)):
        return 0
    unit = max(1, int(policy.de_settle_point_unit or 1))
    cap = min(balance, max(0, int(policy.de_settle_max_point or 0)), max(0, int(payable_amount or 0)))
    use = min(max(0, int(requested or 0)), cap)
    return use // unit * unit
