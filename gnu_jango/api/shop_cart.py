"""Cart, wish list and saved addresses of the shop API."""

import json
import uuid

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    parser_classes,
    permission_classes,
)
from rest_framework.parsers import FormParser, JSONParser
from rest_framework.permissions import AllowAny
from .authentication import SessionJWTAuthentication as JWTAuthentication
from .contracts import envelope
from .contracts.orders import ShopCartSerializer

from gnu_jango.config.models import Config
from gnu_jango.shop.models import (
    ShopAddress,
    ShopOrderData,
    ShopProduct,
    ShopWishlist,
)
from gnu_jango.shop.shipping import (
    DEFAULT_FREE_THRESHOLD,
    DEFAULT_SHIPPING_COST,
    cart_send_cost_flag,
    shipping_quote,
    with_server_send_cost_flags,
)

from .response import api_error, api_response
from .shop_cart_keep import (
    CART_TIME_KEY,
    cart_keep_options,
    cart_now,
    keep_guest_cart_session,
    prune_cart_rows,
)

from .shop_common import (
    SHOP_CART_SESSION_KEY,
    auth_cart_config_name,
    bool_int,
    current_user,
    datetime_value,
    first_value,
    list_values,
    paginate_queryset,
    parse_ct_ids,
    product_thumbnail_url,
    PRODUCT_LINE_IMAGE_WIDTH,
    request_data,
    request_values,
    require_user,
    safe_int,
    session_key,
)

# A cart holds at most this many lines (the member cart is stored as one JSON value).
MAX_CART_ROWS = 100


def _stored_cart_items(request):
    user = current_user(request)
    if user:
        item = Config.objects.filter(name=auth_cart_config_name(user)).first()
        if not item:
            return []
        try:
            data = json.loads(item.value)
        except (TypeError, ValueError):
            return []
        return data if isinstance(data, list) else []
    return list(request.session.get(SHOP_CART_SESSION_KEY, []))


def cart_items(request):
    """The stored cart lines, without lines older than the cart keep term (de_cart_keep_term)."""
    rows = _stored_cart_items(request)
    if not rows:
        return rows
    _, keep_term = cart_keep_options(request)
    kept, changed = prune_cart_rows(rows, keep_term)
    if changed:
        save_cart_items(request, kept)
    return kept


def save_cart_items(request, items):
    # ct_send_cost is the server's call (YoungCart cartupdate.php), whatever a row came in with
    items = with_server_send_cost_flags(items)
    user = current_user(request)
    if user:
        value = json.dumps(list(items), ensure_ascii=False, separators=(",", ":"))
        Config.objects.update_or_create(
            name=auth_cart_config_name(user),
            defaults={"value": value},
        )
        return
    request.session[SHOP_CART_SESSION_KEY] = items
    request.session.modified = True
    keep_guest_cart_session(request, bool(items))


def next_cart_id(items):
    used = {str(item.get("ct_id")) for item in items}
    while True:
        value = str(100000000000 + (uuid.uuid4().int % 900000000000))
        if value not in used:
            return value


def current_cart_line_prices(item, product=None):
    """The product and option prices a cart line should carry now (None if the product is gone)."""
    product = product or ShopProduct.objects.filter(pk=item.get("it_id")).first()
    if not product:
        return None
    option_price = safe_int(item.get("io_price"), 0)
    io_id = str(item.get("ct_option") or "")
    if io_id:
        io_type = safe_int(item.get("io_type"), 0)
        option = next(
            (
                row for row in (product.options or [])
                if isinstance(row, dict) and str(row.get("io_id") or "") == io_id and safe_int(row.get("io_type"), 0) == io_type
            ),
            None,
        )
        if option is not None:
            option_price = safe_int(option.get("io_price"), 0)
    # an add-on option (io_type 1) line carries only its option price
    item_price = safe_int(product.it_price, 0) if safe_int(item.get("io_type"), 0) == 0 else 0
    return item_price, option_price


def refresh_cart_prices(request, ct_ids=None):
    """YoungCart before_check_cart_price: bring cart lines to the current prices.

    Returns True when a price changed (and saves the corrected cart). With ``ct_ids`` only those
    lines are checked.
    """
    lines = [item for item in cart_items(request) if not ct_ids or str(item.get("ct_id")) in ct_ids]
    products = ShopProduct.objects.in_bulk({str(item.get("it_id")) for item in lines})
    corrections = {}
    for item in lines:
        product = products.get(str(item.get("it_id")))
        if not product:
            continue
        price, option_price = current_cart_line_prices(item, product)
        if safe_int(item.get("ct_price"), price) != price or safe_int(item.get("io_price"), 0) != option_price:
            corrections[str(item.get("ct_id"))] = (price, option_price)
    if not corrections:
        return False
    # apply to a fresh read so a line added meanwhile (another tab) is not lost
    items = cart_items(request)
    for item in items:
        if str(item.get("ct_id")) in corrections:
            item["ct_price"], item["io_price"] = corrections[str(item.get("ct_id"))]
    save_cart_items(request, items)
    return True


def cart_item_payload(item):
    product = ShopProduct.objects.filter(pk=item.get("it_id")).first()
    price = safe_int(item.get("ct_price"), product.it_price if product else 0)
    qty = max(1, safe_int(item.get("ct_qty"), 1))
    option_price = safe_int(item.get("io_price"), 0)
    option_type = safe_int(item.get("io_type"), 0)
    line_unit_price = option_price if option_type == 1 else price + option_price
    image_url = product_thumbnail_url(product, PRODUCT_LINE_IMAGE_WIDTH) if product else "/icon-192.png"
    name = product.it_name if product else str(item.get("it_name") or item.get("it_id") or "Product")
    return {
        "ct_id": str(item.get("ct_id") or ""),
        "it_id": str(item.get("it_id") or ""),
        "it_name": name,
        "it_seo_title": product.it_seo_title if product else "",
        "ct_price": price,
        "ct_qty": qty,
        "ct_option": str(item.get("ct_option") or ""),
        "io_type": option_type,
        "io_price": option_price,
        "ct_direct": safe_int(item.get("ct_direct"), 0),
        "ct_send_cost": cart_send_cost_flag(product, item.get("ct_send_cost")),
        "it_sc_type": product.it_sc_type if product else 0,
        "it_sc_method": product.it_sc_method if product else 0,
        "it_sc_price": product.it_sc_price if product else DEFAULT_SHIPPING_COST,
        "it_sc_minimum": product.it_sc_minimum if product else DEFAULT_FREE_THRESHOLD,
        "it_sc_qty": product.it_sc_qty if product else 0,
        "line_total": max(0, line_unit_price) * qty,
        "it_basic_price": product.it_basic_price if product else price,
        "it_stock_qty": product.it_stock_qty if product else 9999,
        "it_notax": product.it_notax if product else 0,
        "ct_notax": product.it_notax if product else 0,
        "it_soldout": product.it_soldout if product else "",
        "it_use": product.it_use if product else "1",
        "it_tel_inq": product.it_tel_inq if product else "",
        "image_url": image_url,
        "cp_price": safe_int(item.get("cp_price"), 0),
        "cp_id": str(item.get("cp_id") or ""),
    }


def restore_pending_cart_rows_for_ct_ids(request, ct_ids, raw_items):
    if not ct_ids:
        return raw_items
    existing_ids = {str(item.get("ct_id")) for item in raw_items}
    missing_ids = set(ct_ids) - existing_ids
    if not missing_ids:
        return raw_items

    user = current_user(request)
    logs = ShopOrderData.objects.filter(dt_pg="cart:prepared")
    if user:
        logs = logs.filter(user=user)
    else:
        guest_order_ids = request.session.get("g5_guest_order_ids", [])
        logs = logs.filter(od_id__in=guest_order_ids)

    restored = []
    for log in logs.order_by("-dt_time")[:20]:
        try:
            rows = json.loads(log.dt_data)
        except (TypeError, ValueError):
            rows = []
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            ct_id = str(row.get("ct_id") or "")
            if ct_id in missing_ids:
                restored.append(row)
                missing_ids.remove(ct_id)
            if not missing_ids:
                break
        if not missing_ids:
            break

    if restored:
        current = cart_items(request)
        current_ids = {str(item.get("ct_id")) for item in current}
        for row in restored:
            if str(row.get("ct_id")) not in current_ids:
                current.append(row)
        save_cart_items(request, current)
        raw_items = current
    return raw_items


def cart_payload(request, ct_ids_value=None):
    raw_items = cart_items(request)
    ct_ids = parse_ct_ids(request.query_params.get("ct_ids") if ct_ids_value is None else ct_ids_value)
    raw_items = restore_pending_cart_rows_for_ct_ids(request, ct_ids, raw_items)
    if ct_ids:
        raw_items = [item for item in raw_items if str(item.get("ct_id")) in ct_ids]
    else:
        raw_items = [item for item in raw_items if not bool_int(item.get("ct_direct"))]
    items = [cart_item_payload(item) for item in raw_items]
    total_price = sum(item["line_total"] for item in items)
    total_qty = sum(item["ct_qty"] for item in items)
    recipient_zip = normalize_zip_from_keys(
        request.query_params,
        full_keys=("od_b_zip", "zip"),
        split_keys=("zip1", "zip2"),
    )
    shipping = shipping_quote(total_price, recipient_zip, items=items)
    shipping_cost = shipping["total"]
    return {
        "items": items,
        "total_price": total_price,
        "total_qty": total_qty,
        "cart_coupon": sum(safe_int(item.get("cp_price"), 0) for item in items),
        "send_cost": shipping_cost,
        "send_cost2": shipping["extra"],
        "shipping_cost": shipping_cost,
    }


def wishlist_queryset(request):
    user = current_user(request)
    if user:
        return ShopWishlist.objects.filter(user=user)
    return ShopWishlist.objects.filter(session_key=session_key(request))


def wishlist_payload(entry):
    product = entry.product or ShopProduct.objects.filter(pk=entry.it_id).first()
    return {
        "wi_id": str(entry.pk),
        "it_id": entry.it_id,
        "it_name": product.it_name if product else entry.it_id,
        "it_seo_title": product.it_seo_title if product else "",
        "it_basic_price": product.it_basic_price if product else 0,
        "it_cust_price": product.it_cust_price if product else 0,
        "it_tel_inq": product.it_tel_inq if product else "",
        "it_soldout": product.it_soldout if product else "",
        "it_use": product.it_use if product else "1",
        "it_stock_qty": product.it_stock_qty if product else 0,
        "option_count": len(product.options or []) if product else 0,
        "can_add_cart": bool(product and product.it_use == "1" and product.it_soldout != "1"),
        "cart_block_reason": "" if product else "Product not found.",
        "image_url": product_thumbnail_url(product) if product else "/icon-192.png",
        "wi_time": datetime_value(entry.wi_time),
    }


def normalize_zip_from_keys(values, *, full_keys=(), split_keys=(), default=""):
    zip_value = first_value(values, *full_keys, default=None)
    if zip_value not in (None, ""):
        return str(zip_value).strip()
    zip1_key = split_keys[0] if split_keys else ""
    zip2_key = split_keys[1] if len(split_keys) > 1 else ""
    zip1 = str(first_value(values, zip1_key, default="") or "") if zip1_key else ""
    zip2 = str(first_value(values, zip2_key, default="") or "") if zip2_key else ""
    combined = f"{zip1}{zip2}".strip()
    return combined or str(default or "").strip()


def normalize_address_zip(values, *, default=""):
    return normalize_zip_from_keys(
        values,
        full_keys=("ad_zip", "zip"),
        split_keys=("ad_zip1", "ad_zip2"),
        default=default,
    )


def split_address_zip(zip_value):
    normalized = str(zip_value or "").strip()
    return normalized[:3], normalized[3:]


def address_payload(address):
    zip1, zip2 = split_address_zip(address.ad_zip)
    return {
        "ad_id": address.pk,
        "ad_subject": address.ad_subject,
        "ad_default": 1 if address.ad_default else 0,
        "ad_name": address.ad_name,
        "ad_tel": address.ad_tel,
        "ad_hp": address.ad_hp,
        "ad_zip": address.ad_zip,
        "ad_zip1": zip1,
        "ad_zip2": zip2,
        "ad_addr1": address.ad_addr1,
        "ad_addr2": address.ad_addr2,
        "ad_addr3": address.ad_addr3,
        "ad_jibeon": address.ad_jibeon,
    }


def add_to_cart(request, data):
    """Validate and add one product (with its option rows) to the cart.

    Returns ``(created_lines, None)`` or ``(None, error_response)``. Shared by the JSON cart API and
    the YoungCart form path so both apply the same product, option, quantity and stock rules.
    """
    it_id = str(data.get("it_id") or "").strip()
    if not it_id:
        return None, api_error("Product id is required.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, details={"it_id": "Product id is required."})
    product = ShopProduct.objects.filter(pk=it_id).first()
    if not product:
        return None, api_error("Product not found.", status=drf_status.HTTP_404_NOT_FOUND, code="product_not_found")
    if str(product.it_tel_inq or "0") == "1":
        return None, api_error("Telephone inquiry products cannot be added to cart.", status=drf_status.HTTP_400_BAD_REQUEST, code="tel_inquiry_product")
    if str(product.it_use or "1") != "1" or str(product.it_soldout or "0") == "1":
        return None, api_error("This product is not available for purchase.", status=drf_status.HTTP_400_BAD_REQUEST, code="product_unavailable")

    items = cart_items(request)
    is_direct = bool_int(data.get("direct"))
    if is_direct and data.get("replace_direct", True) is not False:
        items = [item for item in items if not item.get("ct_direct")]

    option_rows = data.get("options") if isinstance(data.get("options"), list) else None
    if not option_rows:
        option_rows = [{"io_id": data.get("ct_option") or "", "ct_qty": data.get("ct_qty") or 1}]

    submitted_base_qty = sum(
        max(1, safe_int(option.get("ct_qty") if isinstance(option, dict) else 1, 1))
        for option in option_rows
        if safe_int(option.get("io_type") if isinstance(option, dict) else 0, 0) == 0
    )
    min_qty = max(0, safe_int(product.it_buy_min_qty, 0))
    max_qty = max(0, safe_int(product.it_buy_max_qty, 0))
    if submitted_base_qty > 0 and min_qty > 0 and submitted_base_qty < min_qty:
        return None, api_error(
            f"Minimum purchase quantity is {min_qty}.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="min_buy_qty",
            details={"it_buy_min_qty": min_qty},
        )

    existing_base_qty = sum(
        max(1, safe_int(item.get("ct_qty"), 1))
        for item in items
        if str(item.get("it_id")) == it_id
        and safe_int(item.get("io_type"), 0) == 0
        and bool_int(item.get("ct_direct")) == is_direct
    )
    if submitted_base_qty > 0 and max_qty > 0 and existing_base_qty + submitted_base_qty > max_qty:
        return None, api_error(
            f"Maximum purchase quantity is {max_qty}.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="max_buy_qty",
            details={"it_buy_max_qty": max_qty, "current_qty": existing_base_qty},
        )

    product_options = [item for item in (product.options or []) if isinstance(item, dict)]
    base_options = [item for item in product_options if safe_int(item.get("io_type"), 0) == 0]
    if product.it_option_subject.strip() and not base_options:
        return None, api_error(
            "선택 가능한 상품 옵션이 없습니다.",
            status=drf_status.HTTP_409_CONFLICT,
            code="product_options_unavailable",
        )
    if base_options and not any(
        isinstance(option, dict)
        and safe_int(option.get("io_type"), 0) == 0
        and str(option.get("io_id") or "").strip()
        for option in option_rows
    ):
        return None, api_error(
            "상품 옵션을 선택해주세요.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="option_required",
        )

    validated_option_rows = []
    requested_stock_by_option = {}
    for option in option_rows:
        if not isinstance(option, dict):
            return None, api_error(
                "상품 옵션 요청이 올바르지 않습니다.",
                status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="invalid_option",
            )

        io_type = safe_int(option.get("io_type"), 0)
        io_id = str(option.get("io_id") or "").strip()
        qty = max(1, safe_int(option.get("ct_qty"), 1))
        if io_type not in (0, 1):
            return None, api_error(
                "상품 옵션 요청이 올바르지 않습니다.",
                status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="invalid_option",
            )

        matched_option = None
        stock_limit = 0
        option_price = 0
        if io_type == 0 and base_options:
            matched_option = next(
                (
                    item
                    for item in base_options
                    if str(item.get("io_id") or "") == io_id
                    and safe_int(item.get("io_use"), 1) == 1
                ),
                None,
            )
            if not matched_option:
                return None, api_error(
                    "선택할 수 없는 상품 옵션입니다.",
                    status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    code="invalid_option",
                )
            stock_limit = max(0, safe_int(matched_option.get("io_stock_qty"), 0))
            option_price = safe_int(matched_option.get("io_price"), 0)
        elif io_type == 0:
            if io_id:
                return None, api_error(
                    "선택할 수 없는 상품 옵션입니다.",
                    status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    code="invalid_option",
                )
            stock_limit = max(0, safe_int(product.it_stock_qty, 0))
        else:
            matched_option = next(
                (
                    item
                    for item in product_options
                    if safe_int(item.get("io_type"), 0) == 1
                    and str(item.get("io_id") or "") == io_id
                    and safe_int(item.get("io_use"), 1) == 1
                ),
                None,
            )
            if not matched_option:
                return None, api_error(
                    "선택할 수 없는 추가 옵션입니다.",
                    status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    code="invalid_option",
                )
            stock_limit = max(0, safe_int(matched_option.get("io_stock_qty"), 0))
            option_price = safe_int(matched_option.get("io_price"), 0)

        if (io_type == 1 or base_options) and stock_limit <= 0:
            return None, api_error(
                "선택한 옵션의 재고가 없습니다.",
                status=drf_status.HTTP_409_CONFLICT,
                code="option_out_of_stock",
                details={"io_id": io_id},
            )

        stock_key = (io_type, io_id)
        requested_stock_by_option[stock_key] = requested_stock_by_option.get(stock_key, 0) + qty
        existing_option_qty = sum(
            max(1, safe_int(item.get("ct_qty"), 1))
            for item in items
            if str(item.get("it_id")) == it_id
            and safe_int(item.get("io_type"), 0) == io_type
            and str(item.get("ct_option") or "") == io_id
            and bool_int(item.get("ct_direct")) == is_direct
        )
        if stock_limit > 0 and existing_option_qty + requested_stock_by_option[stock_key] > stock_limit:
            return None, api_error(
                f"선택한 옵션의 재고는 {stock_limit}개입니다.",
                status=drf_status.HTTP_409_CONFLICT,
                code="option_stock_limit",
                details={"io_id": io_id, "io_stock_qty": stock_limit},
            )

        validated_option_rows.append(
            {"io_id": io_id, "ct_qty": qty, "io_type": io_type, "io_price": option_price}
        )

    if not base_options and safe_int(product.it_stock_qty, 0) <= 0:
        return None, api_error("재고수량이 부족합니다.", status=drf_status.HTTP_409_CONFLICT, code="out_of_stock")
    if not base_options and safe_int(product.it_stock_qty, 0) > 0:
        if existing_base_qty + submitted_base_qty > safe_int(product.it_stock_qty, 0):
            return None, api_error(
                f"상품 재고는 {product.it_stock_qty}개입니다.",
                status=drf_status.HTTP_409_CONFLICT,
                code="product_stock_limit",
                details={"it_stock_qty": product.it_stock_qty},
            )

    def same_line(option):
        return next(
            (
                item for item in items
                if str(item.get("it_id")) == it_id
                and safe_int(item.get("io_type"), 0) == option["io_type"]
                and str(item.get("ct_option") or "") == option["io_id"]
                and bool_int(item.get("ct_direct")) == is_direct
            ),
            None,
        )

    new_rows = sum(1 for option in validated_option_rows if same_line(option) is None)
    if len(items) + new_rows > MAX_CART_ROWS:
        return None, api_error(
            f"장바구니에는 최대 {MAX_CART_ROWS}개까지 담을 수 있습니다.",
            status=drf_status.HTTP_409_CONFLICT,
            code="cart_full",
        )
    created = []
    for option in validated_option_rows:
        qty = option["ct_qty"]
        ct_option = option["io_id"]
        io_type = option["io_type"]
        existing = same_line(option)
        if existing is not None:
            # YoungCart cartupdate: the same option again adds to the line already in the cart
            # (stock was checked against the combined quantity above)
            existing["ct_qty"] = max(1, safe_int(existing.get("ct_qty"), 1)) + qty
            existing["ct_price"] = product.it_price if io_type == 0 else 0
            existing["io_price"] = option["io_price"]
            created.append({"ct_id": existing["ct_id"]})
            continue
        row = {
            "ct_id": next_cart_id(items),
            "it_id": it_id,
            "it_name": product.it_name if product else it_id,
            "ct_price": product.it_price if io_type == 0 else 0,
            "ct_qty": qty,
            "ct_option": ct_option,
            "io_type": io_type,
            "io_price": option["io_price"],
            "ct_direct": bool_int(data.get("direct")),
            # only a product that lets the customer pick (it_sc_method 2) takes their pick
            "ct_send_cost": cart_send_cost_flag(product, data.get("ct_send_cost")),
            CART_TIME_KEY: cart_now(),
        }
        items.append(row)
        created.append({"ct_id": row["ct_id"]})
    save_cart_items(request, items)
    return created, None


@extend_schema(methods=["GET"], responses=envelope("ShopCart", ShopCartSerializer()))
@api_view(["GET", "POST", "DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def cart_view(request):
    if request.method == "GET":
        # YoungCart cart.php shows (and stores) the current prices.
        refresh_cart_prices(request)
        return api_response(data=cart_payload(request))
    if request.method == "DELETE":
        save_cart_items(request, [])
        return api_response(data=cart_payload(request))

    data = request_data(request)
    created, error = add_to_cart(request, data)
    if error is not None:
        return error
    payload = cart_payload(request)
    payload["cart_items"] = payload.get("items", [])
    payload["items"] = created if len(created) > 1 else []
    payload["ct_id"] = created[0]["ct_id"] if len(created) == 1 else ""
    payload["items_created"] = created
    return api_response(data=payload, status=drf_status.HTTP_201_CREATED)


@api_view(["PATCH", "DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def cart_item_view(request, ct_id):
    items = cart_items(request)
    if request.method == "DELETE":
        save_cart_items(request, [item for item in items if str(item.get("ct_id")) != str(ct_id)])
        return api_response(data=cart_payload(request))

    data = request_data(request)
    target = next((item for item in items if str(item.get("ct_id")) == str(ct_id)), None)
    if target is None:
        return api_error("Cart item not found.", status=drf_status.HTTP_404_NOT_FOUND, code="cart_item_not_found")
    if target:
        qty = max(1, safe_int(data.get("ct_qty"), target.get("ct_qty") or 1))
        product = ShopProduct.objects.filter(pk=str(target.get("it_id") or "")).first()
        io_type = safe_int(target.get("io_type"), 0)
        io_id = str(target.get("ct_option") or "")
        stock_limit = 0
        if product:
            product_options = [option for option in (product.options or []) if isinstance(option, dict)]
            has_base_options = any(safe_int(row.get("io_type"), 0) == 0 for row in product_options)
            if io_type == 1:
                option = next(
                    (
                        row
                        for row in product_options
                        if safe_int(row.get("io_type"), 0) == 1
                        and str(row.get("io_id") or "") == io_id
                        and safe_int(row.get("io_use"), 1) == 1
                    ),
                    None,
                )
                if not option:
                    return api_error(
                        "선택할 수 없는 추가 옵션입니다.",
                        status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                        code="invalid_option",
                    )
                stock_limit = max(0, safe_int(option.get("io_stock_qty"), 0))
            elif has_base_options:
                option = next(
                    (
                        row
                        for row in product_options
                        if safe_int(row.get("io_type"), 0) == 0
                        and str(row.get("io_id") or "") == io_id
                        and safe_int(row.get("io_use"), 1) == 1
                    ),
                    None,
                )
                if not option:
                    return api_error(
                        "선택할 수 없는 상품 옵션입니다.",
                        status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                        code="invalid_option",
                    )
                stock_limit = max(0, safe_int(option.get("io_stock_qty"), 0))
            else:
                stock_limit = max(0, safe_int(product.it_stock_qty, 0))

            if (io_type == 1 or has_base_options) and stock_limit <= 0:
                return api_error(
                    "선택한 옵션의 재고가 없습니다.",
                    status=drf_status.HTTP_409_CONFLICT,
                    code="option_out_of_stock",
                )
            if io_type == 0 and not has_base_options and stock_limit <= 0:
                return api_error("재고수량이 부족합니다.", status=drf_status.HTTP_409_CONFLICT, code="out_of_stock")

        other_option_qty = sum(
            max(1, safe_int(item.get("ct_qty"), 1))
            for item in items
            if item is not target
            and str(item.get("it_id")) == str(target.get("it_id"))
            and safe_int(item.get("io_type"), 0) == io_type
            and str(item.get("ct_option") or "") == io_id
            and bool_int(item.get("ct_direct")) == bool_int(target.get("ct_direct"))
        )
        if stock_limit > 0 and other_option_qty + qty > stock_limit:
            return api_error(
                f"선택한 옵션의 재고는 {stock_limit}개입니다.",
                status=drf_status.HTTP_409_CONFLICT,
                code="option_stock_limit",
                details={"io_id": io_id, "io_stock_qty": stock_limit},
            )

        if product and io_type == 0:
            min_qty = max(0, safe_int(product.it_buy_min_qty, 0))
            max_qty = max(0, safe_int(product.it_buy_max_qty, 0))
            current_product_qty = sum(
                max(1, safe_int(item.get("ct_qty"), 1))
                for item in items
                if str(item.get("it_id")) == str(target.get("it_id"))
                and safe_int(item.get("io_type"), 0) == 0
                and bool_int(item.get("ct_direct")) == bool_int(target.get("ct_direct"))
            )
            next_product_qty = current_product_qty - max(1, safe_int(target.get("ct_qty"), 1)) + qty
            if min_qty > 0 and next_product_qty < min_qty:
                return api_error(
                    f"이 상품은 최소 {min_qty}개 이상 구매해야 합니다.",
                    status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    code="min_buy_qty",
                )
            if max_qty > 0 and next_product_qty > max_qty:
                return api_error(
                    f"이 상품은 최대 {max_qty}개까지 구매할 수 있습니다.",
                    status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    code="max_buy_qty",
                )
        target["ct_qty"] = qty
    save_cart_items(request, items)
    return api_response(data=cart_payload(request))


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([FormParser, JSONParser])
def cart_legacy_update_view(request):
    values = request_values(request)
    action = str(first_value(values, "act", "action", "w")).lower()
    items = cart_items(request)

    if action in {"alldelete", "delete_all", "clear"}:
        items = []
    elif action in {"seldelete", "delete", "d"}:
        ct_ids = {str(item) for item in list_values(values, "ct_id[]", "ct_id")}
        it_ids = {str(item) for item in list_values(values, "it_id[]", "it_id")}
        items = [
            item
            for item in items
            if (not ct_ids or str(item.get("ct_id")) not in ct_ids) and (not it_ids or str(item.get("it_id")) not in it_ids)
        ]
    else:
        ct_ids = list_values(values, "ct_id[]", "ct_id")
        qty_values = list_values(values, "ct_qty[]", "ct_qty")
        if ct_ids:
            qty_by_id = {
                str(ct_id): max(1, safe_int(qty_values[index] if index < len(qty_values) else 1, 1))
                for index, ct_id in enumerate(ct_ids)
            }
            for item in items:
                ct_id = str(item.get("ct_id"))
                if ct_id in qty_by_id:
                    item["ct_qty"] = qty_by_id[ct_id]
        else:
            it_ids = list_values(values, "it_id[]", "it_id")
            qty_values = list_values(values, "ct_qty[]", "ct_qty")
            option_values = list_values(values, "io_id[]", "io_id", "ct_option[]", "ct_option")
            type_values = list_values(values, "io_type[]", "io_type")
            is_direct = bool_int(first_value(values, "sw_direct", "direct"))
            for index, it_id in enumerate(it_ids):
                qty = qty_values[index] if index < len(qty_values) else first_value(values, "ct_qty", default=1)
                _, error = add_to_cart(
                    request,
                    {
                        "it_id": str(it_id),
                        "options": [
                            {
                                "io_id": str(option_values[index] if index < len(option_values) else ""),
                                "io_type": safe_int(type_values[index] if index < len(type_values) else 0, 0),
                                "ct_qty": max(1, safe_int(qty, 1)),
                            }
                        ],
                        "direct": is_direct,
                        # a buy-now form replaces the earlier buy-now lines once, not per product
                        "replace_direct": index == 0,
                    },
                )
                if error is not None:
                    return error
            items = cart_items(request)

    save_cart_items(request, items)
    redirect = "/shop/order?direct=1" if bool_int(first_value(values, "sw_direct", "direct")) else "/shop/cart"
    return api_response(data={**cart_payload(request), "redirect": redirect})


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def wishlist_view(request):
    if request.method == "GET":
        queryset = wishlist_queryset(request).select_related("product")
        page, meta = paginate_queryset(request, queryset, default_per_page=20)
        return api_response(data=[wishlist_payload(item) for item in page], meta=meta)

    data = request_data(request)
    it_id = str(data.get("it_id") or "").strip()
    if not it_id:
        return api_error("Product id is required.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY)
    user = current_user(request)
    product = ShopProduct.objects.filter(pk=it_id).first()
    if not product:
        return api_error("Product not found.", status=drf_status.HTTP_404_NOT_FOUND, code="product_not_found")
    defaults = {"product": product, "wi_time": timezone.now()}
    if user:
        entry, _ = ShopWishlist.objects.update_or_create(user=user, it_id=it_id, defaults=defaults)
    else:
        entry, _ = ShopWishlist.objects.update_or_create(session_key=session_key(request), it_id=it_id, defaults=defaults)
    return api_response(data=wishlist_payload(entry), status=drf_status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def wishlist_check_view(request, it_id):
    entry = wishlist_queryset(request).filter(it_id=it_id).select_related("product").first()
    return api_response(
        data={
            "it_id": it_id,
            "wishlisted": bool(entry),
            "item": wishlist_payload(entry) if entry else None,
        }
    )


@api_view(["DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def wishlist_item_view(request, it_id):
    deleted, _ = wishlist_queryset(request).filter(it_id=it_id).delete()
    return api_response(data={"deleted": bool(deleted), "it_id": it_id})


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([FormParser, JSONParser])
def wishlist_legacy_update_view(request):
    user, error = require_user(request)
    if error:
        return error
    values = request_values(request)
    it_id = str(first_value(values, "it_id", "it_id[]")).strip()
    if not it_id:
        return api_error("Product id is required.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY)
    action = str(first_value(values, "act", "action", "w")).lower()
    if action in {"delete", "d", "remove"}:
        ShopWishlist.objects.filter(user=user, it_id=it_id).delete()
    else:
        product = ShopProduct.objects.filter(pk=it_id).first()
        ShopWishlist.objects.update_or_create(user=user, it_id=it_id, defaults={"product": product, "wi_time": timezone.now()})
    return api_response(data={"redirect": "/shop/wishlist"})


@api_view(["PATCH", "DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def address_detail_view(request, ad_id):
    user, error = require_user(request)
    if error:
        return error
    address = ShopAddress.objects.filter(pk=ad_id, user=user).first()
    if not address:
        return api_error("Address not found.", status=drf_status.HTTP_404_NOT_FOUND, code="address_not_found")
    if request.method == "DELETE":
        address.delete()
        return api_response(data={"deleted": True, "ad_id": ad_id})
    data = request_data(request)
    for field in ("ad_subject", "ad_name", "ad_tel", "ad_hp", "ad_addr1", "ad_addr2", "ad_addr3", "ad_jibeon"):
        if field in data:
            setattr(address, field, str(data.get(field) or ""))
    if any(field in data for field in ("ad_zip", "zip", "ad_zip1", "ad_zip2", "zip1", "zip2")):
        address.ad_zip = normalize_address_zip(data, default=address.ad_zip)
    if "ad_default" in data:
        is_default = bool(bool_int(data.get("ad_default")))
        if is_default:
            ShopAddress.objects.filter(user=user).exclude(pk=address.pk).update(ad_default=False)
        address.ad_default = is_default
    address.save()
    return api_response(data=address_payload(address))


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([FormParser, JSONParser])
def address_legacy_update_view(request):
    user, error = require_user(request)
    if error:
        return error
    values = request_values(request)
    ad_id = safe_int(first_value(values, "ad_id"), 0)
    action = str(first_value(values, "w", "act", "action")).lower()
    address = ShopAddress.objects.filter(pk=ad_id, user=user).first() if ad_id else None
    if action in {"d", "delete", "remove"}:
        if address:
            address.delete()
        return api_response(data={"redirect": "/mypage/addresses", "deleted": bool(address)})
    if address is None:
        address = ShopAddress(user=user)
    address.ad_subject = str(first_value(values, "ad_subject", default=address.ad_subject))
    address.ad_default = bool_int(first_value(values, "ad_default", "ad_default[]", default=address.ad_default))
    address.ad_name = str(first_value(values, "ad_name", default=address.ad_name))
    address.ad_tel = str(first_value(values, "ad_tel", default=address.ad_tel))
    address.ad_hp = str(first_value(values, "ad_hp", default=address.ad_hp))
    address.ad_zip = normalize_address_zip(values, default=address.ad_zip)
    address.ad_addr1 = str(first_value(values, "ad_addr1", default=address.ad_addr1))
    address.ad_addr2 = str(first_value(values, "ad_addr2", default=address.ad_addr2))
    address.ad_addr3 = str(first_value(values, "ad_addr3", default=address.ad_addr3))
    address.ad_jibeon = str(first_value(values, "ad_jibeon", default=address.ad_jibeon))
    if address.ad_default:
        ShopAddress.objects.filter(user=user, ad_default=True).exclude(pk=address.pk).update(ad_default=False)
    address.save()
    return api_response(data={**address_payload(address), "redirect": "/mypage/addresses"})
