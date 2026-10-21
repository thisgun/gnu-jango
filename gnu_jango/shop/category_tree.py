"""Category tree rules of youngcart categoryform.php / categoryformupdate.php.

A category code grows by two base-36 characters per level ("10" -> "1010" -> "101020"), five
levels at most. A category that still has child categories or products cannot be deleted.
"""

from django.db.models import Q

from gnu_jango.shop.models import ShopCategory, ShopProduct

CATEGORY_ID_STEP = 2
MAX_CATEGORY_DEPTH = 5
MAX_CATEGORY_ID_LENGTH = CATEGORY_ID_STEP * MAX_CATEGORY_DEPTH
SUBID_SPACE = 36 * 36
BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"
# itemlist/categorylist list at most this many blocking product codes in the refusal message
BLOCKER_SAMPLE = 10


def _to_base36(number):
    digits = ""
    while True:
        number, remainder = divmod(number, 36)
        digits = BASE36[remainder] + digits
        if not number:
            return digits


def next_child_category_id(parent_id=""):
    """The code youngcart proposes for a new child of ``parent_id`` ("" = a first-level category).

    categoryform.php takes the largest existing two-character suffix under the parent, reads it in
    base 36 and adds 36 ("10" -> "20", none yet -> "10"). Returns "" when the parent is already at
    the deepest level or every code is taken."""
    parent_id = str(parent_id or "")
    if len(parent_id) >= MAX_CATEGORY_ID_LENGTH:
        return ""
    length = len(parent_id) + CATEGORY_ID_STEP
    suffixes = [
        ca_id[len(parent_id):].lower()
        for ca_id in ShopCategory.objects.filter(ca_id__startswith=parent_id).values_list("ca_id", flat=True)
        if len(ca_id) == length
    ]
    largest = 0
    for suffix in suffixes:
        try:
            largest = max(largest, int(suffix, 36))
        except ValueError:
            continue
    taken = set(suffixes)
    # youngcart stops at "z0"; past it the first free code (from "10" on) is offered instead
    candidates = range(largest + 36, SUBID_SPACE) if largest + 36 < SUBID_SPACE else range(36, SUBID_SPACE)
    for candidate in candidates:
        suffix = _to_base36(candidate).rjust(CATEGORY_ID_STEP, "0")
        if suffix not in taken:
            return parent_id + suffix
    return ""


def child_categories(category):
    return ShopCategory.objects.filter(
        Q(ca_parent=category.ca_id) | Q(ca_id__startswith=category.ca_id)
    ).exclude(pk=category.pk)


def category_products(category):
    return ShopProduct.objects.filter(
        Q(category=category) | Q(category2=category) | Q(category3=category)
    )


def category_delete_blockers(category):
    """Korean reasons the category cannot be deleted yet (empty when it can)."""
    reasons = []
    children = list(child_categories(category).order_by("ca_id").values_list("ca_id", flat=True)[: BLOCKER_SAMPLE + 1])
    if children:
        sample = ", ".join(children[:BLOCKER_SAMPLE]) + (" …" if len(children) > BLOCKER_SAMPLE else "")
        reasons.append(
            f"분류 {category.ca_id}({category.ca_name}): 하위 분류가 있으므로 삭제할 수 없습니다. "
            f"하위분류를 우선 삭제하여 주십시오. ({sample})"
        )
    products = category_products(category)
    total = products.count()
    if total:
        sample_ids = list(products.order_by("it_id").values_list("it_id", flat=True)[:BLOCKER_SAMPLE])
        sample = ", ".join(sample_ids) + (" …" if total > BLOCKER_SAMPLE else "")
        reasons.append(
            f"분류 {category.ca_id}({category.ca_name}): 이 분류와 관련된 상품이 총 {total}건 존재하므로 "
            f"상품을 삭제하거나 다른 분류로 옮긴 후 삭제하여 주십시오. ({sample})"
        )
    return reasons
