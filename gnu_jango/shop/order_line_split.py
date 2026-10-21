"""Partial quantity changes of an order line: cancel, return or mark sold out only some units of a
line (youngcart orderformcartupdate.php lets the admin lower ct_qty before changing the status).

Here the line is split instead: the original line keeps the units that stay (so it stays the
product's first line and keeps its product coupon) and a copy carries the units that change.
The copy then goes through the ordinary line change (shop/order_lines.py), so repricing, the stock
put back (only the copy's quantity), coupons, the refund and the history stay one code path. The
split is made inside the caller's transaction and rolled back with it when the change is refused.
"""

from dataclasses import dataclass

from gnu_jango.shop.models import ShopOrderItem
from gnu_jango.shop.order_points import resettle_split_line_points

CT_ID_MAX = ShopOrderItem._meta.get_field("ct_id").max_length


@dataclass(frozen=True)
class LineSplit:
    original_pk: int
    new_pk: int
    label: str
    before: int  # the line's quantity before the split
    moved: int  # the units that change status (the new line)
    point_taken: int = 0  # purchase points taken back because the line was paid already

    @property
    def kept(self):
        return self.before - self.moved


def posted_line_quantities(data, selected):
    """The admin line form's quantities for the chosen lines: ({pk: units to change}, {pk: the
    quantity shown}, "") from ``ct_qty_<pk>`` / ``ct_cur_<pk>``, or ({}, {}, the reason)."""
    quantities = {}
    expected = {}
    for value in selected:
        try:
            pk = int(value)
        except (TypeError, ValueError):
            continue  # plan_line_change refuses it
        for name, target in ((f"ct_qty_{pk}", quantities), (f"ct_cur_{pk}", expected)):
            raw = str(data.get(name) or "").strip()
            if not raw:
                continue
            try:
                target[pk] = int(raw)
            except ValueError:
                return {}, {}, "처리 수량은 숫자로 입력하세요."
    return quantities, expected, ""


def _split_ct_id(order, item):
    used = set(order.items.values_list("ct_id", flat=True))
    base = str(item.ct_id or item.pk)
    for number in range(1, 1000):
        suffix = f"-c{number}"
        candidate = f"{base[: CT_ID_MAX - len(suffix)]}{suffix}"
        if candidate not in used:
            return candidate
    return f"{item.pk}-c{len(used) + 1}"[:CT_ID_MAX]


def split_order_lines(order, line_ids, quantities, expected=None):
    """Split every chosen line whose quantity in ``quantities`` is below its ct_qty.

    Returns (the line ids to change, with each split line replaced by its new copy, the splits,
    "") or (None, (), the reason). ``expected`` ({pk: the quantity the admin saw}) refuses a
    resubmitted form once the line changed, so a double submit cannot split it twice. The caller
    holds the order lock and a transaction that is rolled back when the change is refused."""
    from gnu_jango.shop.order_lines import line_label

    expected = expected or {}
    wanted = []
    for value in line_ids:
        try:
            wanted.append(int(value))
        except (TypeError, ValueError):
            return None, (), "처리할 상품을 다시 선택하세요."
    chosen = set(wanted)
    if any(pk not in chosen for pk in quantities):
        return None, (), "수량을 바꾼 상품도 선택하세요."
    items = {item.pk: item for item in order.items.select_for_update().filter(pk__in=chosen).order_by("pk")}
    result = []
    splits = []
    for pk in wanted:
        item = items.get(pk)
        if item is None:
            result.append(pk)  # plan_line_change reports a line of another order
            continue
        if pk in expected and int(expected[pk]) != int(item.ct_qty):
            return None, (), (
                f"{line_label(item)}의 수량이 {expected[pk]}개에서 {item.ct_qty}개로 바뀌었습니다. "
                "이미 처리된 요청일 수 있으니 화면을 새로 고친 뒤 다시 확인하세요."
            )
        qty = quantities.get(pk)
        if qty is None or qty == item.ct_qty:
            result.append(pk)
            continue
        if not 1 <= qty < item.ct_qty:
            return None, (), f"{line_label(item)}의 처리 수량은 1~{item.ct_qty}개로 입력하세요."
        before = item.ct_qty
        new_item = ShopOrderItem.objects.get(pk=item.pk)
        new_item.pk = None
        new_item._state.adding = True
        new_item.ct_id = _split_ct_id(order, item)
        new_item.ct_qty = qty
        # the units leaving were never paid a point on their own line; see resettle_split_line_points
        new_item.ct_point_use = False
        new_item.save()
        item.ct_qty = before - qty
        item.save(update_fields=["ct_qty"])
        taken = resettle_split_line_points(item, order)
        splits.append(LineSplit(item.pk, new_item.pk, line_label(item), before, qty, taken))
        result.append(new_item.pk)
    return result, tuple(splits), ""
