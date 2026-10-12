from html import unescape
import re

from django.utils.html import strip_tags

from .models import ShopShippingCost, ShopShippingPolicy


DEFAULT_SHIPPING_COST = 3000
DEFAULT_FREE_THRESHOLD = 50000


def current_shipping_policy():
    return ShopShippingPolicy.objects.filter(pk=1).first() or ShopShippingPolicy(
        pk=1,
        de_delivery_company="Default courier",
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


def shipping_free_threshold(policy=None):
    policy = policy or current_shipping_policy()
    if str(policy.de_send_cost_case or "").strip() == "무료":
        return 0
    rules = shipping_rules(policy)
    return max((rule["limit"] for rule in rules), default=DEFAULT_FREE_THRESHOLD)


def base_shipping_cost(item_total, policy=None):
    policy = policy or current_shipping_policy()
    item_total = max(0, int(item_total or 0))
    case = str(policy.de_send_cost_case or "").strip()
    if case == "무료":
        return 0

    rules = shipping_rules(policy)
    if case == "차등" and rules:
        for rule in rules:
            if item_total < rule["limit"]:
                return rule["cost"]
        return 0

    return 0 if item_total >= DEFAULT_FREE_THRESHOLD else DEFAULT_SHIPPING_COST


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
    combined price. Lines the customer pays on delivery (ct_send_cost) are left out.
    """
    from math import ceil

    from .models import ShopProduct

    groups = {}
    for item in items:
        if int(item.get("ct_send_cost") or 0):
            continue
        group = groups.setdefault(str(item.get("it_id")), [0, 0])
        group[0] += max(0, int(item.get("line_total") or 0))
        group[1] += max(0, int(item.get("ct_qty") or 0))
    products = ShopProduct.objects.in_bulk(list(groups))
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
    rules = shipping_rules(policy)
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
