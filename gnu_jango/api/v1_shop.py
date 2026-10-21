import hashlib
import hmac
import json
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Avg, Count, Exists, F, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    parser_classes,
    permission_classes,
    throttle_classes,
)
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle
from .authentication import SessionJWTAuthentication as JWTAuthentication

from gnu_jango.config.models import Config
from gnu_jango.core.legacy_assets import first_existing_legacy_path
from gnu_jango.core.thumbnails import thumbnail_url
from gnu_jango.shop.models import (
    ShopAddress,
    ShopBanner,
    ShopCategory,
    ShopCoupon,
    ShopCouponLog,
    ShopCouponZone,
    ShopEvent,
    ShopOrder,
    ShopOrderData,
    ShopOrderItem,
    ShopProduct,
    ShopStockNotification,
)
from gnu_jango.shop.coupon_dates import coupon_end_date
from gnu_jango.shop.inventory import StockAdjustmentError, cancel_order_with_stock_restore, reserve_product_stock
from gnu_jango.shop.images import upload_product_images
from gnu_jango.shop.notifications import queue_order_placed_mails
from gnu_jango.shop.order_points import (
    item_purchase_point,
    item_status_update,
    order_line_points_enabled,
    purchase_point_notice,
    take_back_order_points,
)
from gnu_jango.shop.payment_options import (
    cash_receipt_method_enabled,
    cash_receipt_preferences,
    online_payment_method_enabled,
)
from gnu_jango.shop.order_coupons import order_coupon_totals
from gnu_jango.shop.shipping import (
    allowed_point_use,
    current_shipping_policy,
    shipping_quote,
)
from gnu_jango.shop.shop_display import related_list_enabled
from gnu_jango.shop.taxes import calculate_order_tax_amounts
from gnu_jango.users import point_ledger
from gnu_jango.users.models import Profile
from gnu_jango.utils.lib import get_client_ip

from .response import api_error, api_response
from .search import any_icontains, apply_text_search
from .shop_search import search_products
from .shop_common import (
    fit_to_columns,
    on_sale_products,
    legacy_shop_asset_url,
    product_image_url,
    product_thumbnail_url,
    PRODUCT_LINE_IMAGE_WIDTH,
    CANCELLED_STATUSES,
    ORDERED_STATUSES,  # noqa: F401 - re-exported for existing importers
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_ORDERED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_SHIPPING,
    PAID_STATUSES,
    PAYMENT_ADAPTER_PROVIDERS,
    ShopStaffPermission,
    auth_cart_config_name,  # noqa: F401 - re-exported for existing importers
    bool_int,
    configured_bank_accounts,
    current_user,
    datetime_value,
    first_value,
    generate_numeric_order_id,
    guest_order_password_config_name,
    guest_order_password_hash,
    guest_order_password_matches,
    guest_order_password_needs_upgrade,
    next_coupon_log_id,
    normalize_hp,
    normalize_order_status,
    order_cancel_state,
    paginate_queryset,
    pagination_meta,
    payment_confirm_access_allowed,
    read_smoke_config,
    request_data,
    request_values,
    require_user,
    safe_int,
    shop_policy_payload,
)
from .shop_coupons import (
    coupon_discount,
    coupon_exceeds_base,
    coupon_matches_cart_item,
    coupon_payload,
    coupon_raw_discount,
    coupon_zone_payload,
    items_with_product_coupon_prices,
    member_coupons_queryset,
    product_coupon_entries,
    product_line_totals,
    valid_coupons_queryset,
)
from .shop_order_options import guest_privacy_html, hope_date_range, order_hope_date
from .shop_cart import (
    refresh_cart_prices,
    address_detail_view,  # noqa: F401 - re-exported for existing importers
    address_legacy_update_view,  # noqa: F401 - re-exported for existing importers
    address_payload,
    cart_item_payload,
    cart_item_view,  # noqa: F401 - re-exported for existing importers
    cart_items,
    cart_legacy_update_view,  # noqa: F401 - re-exported for existing importers
    cart_payload,
    cart_view,  # noqa: F401 - re-exported for existing importers
    normalize_address_zip,
    normalize_zip_from_keys,
    save_cart_items,
    wishlist_check_view,  # noqa: F401 - re-exported for existing importers
    wishlist_item_view,  # noqa: F401 - re-exported for existing importers
    wishlist_legacy_update_view,  # noqa: F401 - re-exported for existing importers
    wishlist_view,  # noqa: F401 - re-exported for existing importers
)
from .shop_personal_pay import (
    personalpay_payload,  # noqa: F401 - re-exported for existing importers
    personalpay_start_view,  # noqa: F401 - re-exported for existing importers
    personalpay_view,  # noqa: F401 - re-exported for existing importers
)
from .shop_recommend import product_recommend_view  # noqa: F401 - re-exported for existing importers
from .shop_reviews import (
    my_qna_view,  # noqa: F401 - re-exported for existing importers
    my_reviews_view,  # noqa: F401 - re-exported for existing importers
    qna_detail_view,  # noqa: F401 - re-exported for existing importers
    qna_view,  # noqa: F401 - re-exported for existing importers
    review_detail_view,  # noqa: F401 - re-exported for existing importers
    review_summary_view,  # noqa: F401 - re-exported for existing importers
    reviews_view,  # noqa: F401 - re-exported for existing importers
)
from .shop_payments import (
    cancel_pending_toss_vbank,
    checkout_payment_methods,
    configured_payment_provider,
    confirm_adapter_payment,
    confirm_order_payment,
    confirm_toss_payment,
    payment_adapter_config,
    payment_adapter_enabled,
    payment_adapter_request,  # noqa: F401 - re-exported for existing importers
    payment_adapter_success,  # noqa: F401 - re-exported for existing importers
    payment_amount,
    payment_callback_secret,
    payment_callback_signature_error,
    payment_callback_success,
    payment_order_id,
    payment_transaction_id,
    record_payment_raw_log,
    redact_payment_data,  # noqa: F401 - re-exported for existing importers
    safe_amount_int,
    safe_receipt_url,
    settle_case_is_bank,
    settle_case_is_vbank,
    settle_case_supports_cash_receipt,
    toss_api_confirm,  # noqa: F401 - re-exported for existing importers
    toss_api_get_payment_by_order,
    toss_method_is_vbank,
    toss_payment_config,
)
def category_payload(category, *, include_children=False):
    data = {
        "ca_id": category.ca_id,
        "ca_name": category.ca_name,
        "ca_order": category.ca_order,
        "ca_skin": category.ca_skin,
        "ca_parent": category.ca_parent,
        "item_count": getattr(category, "item_count", None) if hasattr(category, "item_count") else category_products(category.ca_id).count(),
    }
    if include_children:
        children = (
            ShopCategory.objects.filter(ca_parent=category.ca_id, ca_use=True)
            .annotate(item_count=category_tree_item_count())
            .order_by("ca_order", "ca_id")
        )
        data["children"] = [category_payload(child) for child in children]
    return data


def shop_event_image_url(event, suffix, request):
    field_name = "ev_head_image" if suffix == "h" else "ev_tail_image"
    uploaded_image = getattr(event, field_name)
    if uploaded_image:
        try:
            return request.build_absolute_uri(uploaded_image.url)
        except (OSError, ValueError):
            pass
    relative_path = f"data/event/{event.ev_id}_{suffix}"
    try:
        stored = default_storage.exists(relative_path)
    except OSError:
        stored = False
    if stored:
        return request.build_absolute_uri(default_storage.url(relative_path))
    if first_existing_legacy_path(relative_path):
        return legacy_shop_asset_url(f"/{relative_path}")
    return ""


def shop_product_ordering(sort=None, sortodr=None):
    sort = str(sort or "").strip().lower()
    sortodr = str(sortodr or "").strip().lower()
    aliases = {
        "latest": ("it_update_time", "desc"),
        "recent": ("it_update_time", "desc"),
        "popular": ("it_sum_qty", "desc"),
        "sales": ("it_sum_qty", "desc"),
        "price_asc": ("it_price", "asc"),
        "price_desc": ("it_price", "desc"),
        "name": ("it_name", "asc"),
        "rating": ("it_use_avg", "desc"),
        "reviews": ("it_use_cnt", "desc"),
    }
    field_directions = {
        "it_name": "asc",
        "it_sum_qty": "desc",
        "it_price": "asc",
        "it_use_avg": "desc",
        "it_use_cnt": "desc",
        "it_update_time": "desc",
    }
    if sort in {"", "default"}:
        return ["it_order", "-it_id"]
    field, default_direction = aliases.get(sort, (sort, field_directions.get(sort)))
    if field not in field_directions:
        return ["it_order", "-it_id"]
    direction = sortodr if sortodr in {"asc", "desc"} else default_direction
    prefix = "-" if direction == "desc" else ""
    return [f"{prefix}{field}", "it_order", "-it_id"]


def product_image_urls(product, fallback_url):
    urls = []
    for image in product.images or []:
        if isinstance(image, str):
            url = image
        elif isinstance(image, dict):
            url = image.get("url") or image.get("src") or image.get("image_url") or ""
        else:
            url = ""
        url = legacy_shop_asset_url(url)
        if url and url not in urls:
            urls.append(url)

    if not urls and fallback_url:
        urls.append(fallback_url)
    return urls


def category_member_q(category_ref):
    """Match products assigned directly to this category through any Gnuboard category slot."""
    return Q(category_id=category_ref) | Q(category2_id=category_ref) | Q(category3_id=category_ref)


def category_tree_member_q(category_ref):
    """Match products in this category tree through any Gnuboard category slot."""
    return (
        Q(category__ca_id__startswith=category_ref)
        | Q(category2__ca_id__startswith=category_ref)
        | Q(category3__ca_id__startswith=category_ref)
    )


def category_products(category_id):
    return ShopProduct.objects.filter(category_member_q(category_id))


def category_tree_products(category_id):
    return ShopProduct.objects.filter(category_tree_member_q(category_id))


def category_item_count():
    members = (
        on_sale_products().filter(category_member_q(OuterRef("pk")))
        .order_by()
        .values(group=Value(1))
        .annotate(total=Count("pk"))
        .values("total")
    )
    return Coalesce(Subquery(members, output_field=IntegerField()), 0)


def category_tree_item_count():
    members = (
        on_sale_products()
        .filter(category_tree_member_q(OuterRef("pk")))
        .order_by()
        .values(group=Value(1))
        .annotate(total=Count("pk"))
        .values("total")
    )
    return Coalesce(Subquery(members, output_field=IntegerField()), 0)


def annotate_product_coupon_badge(queryset):
    today = timezone.localdate()
    matching_coupons = ShopCoupon.objects.filter(
        cp_start__lte=today,
        cp_end__gte=today,
    ).filter(
        Q(cp_method=0, cp_target=OuterRef("it_id"))
        | Q(cp_method=1, cp_target=OuterRef("category_id"))
        | Q(cp_method=1, cp_target=OuterRef("category2_id"))
        | Q(cp_method=1, cp_target=OuterRef("category3_id"))
    )
    return queryset.annotate(has_coupon=Exists(matching_coupons))


def product_coupon_badge_available(product):
    today = timezone.localdate()
    matching_target = Q(cp_method=0, cp_target=product.it_id)
    if product.category_ids:
        matching_target |= Q(cp_method=1, cp_target__in=product.category_ids)
    return ShopCoupon.objects.filter(
        cp_start__lte=today,
        cp_end__gte=today,
    ).filter(matching_target).exists()


def product_payload(product, request=None, *, detail=False):
    category = product.category
    review_stats = getattr(product, "review_stats", None)
    review_count = getattr(product, "review_count", None)
    qa_count = getattr(product, "qa_count", None)
    # Cards and rows show `image_url` (a 400px copy); the detail gallery shows the original `images`.
    images = product_image_urls(product, product_image_url(product))
    image_url = product_thumbnail_url(product)
    option_subject = product.it_option_subject.strip()
    raw_options = product.options if isinstance(product.options, list) else []
    product_options = [
        {**item, "io_type": safe_int(item.get("io_type"), -1)}
        for item in raw_options
        if isinstance(item, dict) and safe_int(item.get("io_type"), -1) in (0, 1)
    ]
    choice_options = [
        item for item in product_options if item["io_type"] == 0
    ]
    if choice_options and not option_subject:
        option_count = max(len(str(item.get("io_id") or "").split("\x1e")) for item in choice_options)
        option_subject = ",".join(f"선택 옵션 {index}" for index in range(1, option_count + 1))
    supply_subject = product.it_supply_subject.strip()
    if not supply_subject and any(item["io_type"] == 1 for item in product_options):
        supply_subject = "추가 옵션"
    has_coupon = (
        bool(product.has_coupon)
        if hasattr(product, "has_coupon")
        else product_coupon_badge_available(product)
    )
    info_items = []
    info_title = product.it_info_title
    if product.it_info_title:
        try:
            info_data = json.loads(product.it_info_title)
        except (TypeError, ValueError):
            info_data = None
        if isinstance(info_data, dict) and info_data.get("value"):
            info_title = "\uc0c1\ud488 \uc815\ubcf4 \uace0\uc2dc"
            info_items.append(
                {
                    "key": str(info_data.get("key") or "info"),
                    "label": str(info_data.get("key") or "info"),
                    "value": str(info_data.get("value") or ""),
                }
            )
    data = {
        "it_id": product.it_id,
        "ca_id": product.category_id or "",
        "ca_id2": product.category2_id or "",
        "ca_id3": product.category3_id or "",
        "ca_name": category.ca_name if category else "",
        "it_name": product.it_name,
        "it_seo_title": product.it_seo_title,
        "it_brand": product.it_brand,
        "it_maker": product.it_maker,
        "it_origin": product.it_origin,
        "it_model": product.it_model,
        "it_price": product.it_price,
        "it_basic_price": product.it_basic_price or product.it_price,
        "it_cust_price": product.it_cust_price,
        "it_hit": product.it_hit,
        "it_point": product.it_point,
        "it_point_type": product.it_point_type,
        "it_stock_qty": product.it_stock_qty,
        "it_notax": product.it_notax,
        "it_buy_min_qty": product.it_buy_min_qty,
        "it_buy_max_qty": product.it_buy_max_qty,
        "it_tel_inq": product.it_tel_inq,
        "it_soldout": product.it_soldout,
        "it_stock_sms": product.it_stock_sms,
        "it_option_subject": option_subject,
        "it_supply_subject": supply_subject,
        "stock_sms_privacy": "",
        "it_sc_type": product.it_sc_type,
        "it_sc_method": product.it_sc_method,
        "it_sc_price": product.it_sc_price,
        "it_sc_minimum": product.it_sc_minimum,
        "it_sc_qty": product.it_sc_qty,
        "it_type1": product.it_type1,
        "it_type2": product.it_type2,
        "it_type3": product.it_type3,
        "it_type4": product.it_type4,
        "it_type5": product.it_type5,
        "has_coupon": has_coupon,
        "it_content": product.it_content,
        "it_explan": product.it_explan,
        "it_basic": product.it_basic,
        "it_head_html": product.it_head_html,
        "it_tail_html": product.it_tail_html,
        "it_info_gubun": product.it_info_gubun,
        "it_info_title": info_title,
        "it_info_items": info_items,
        "image_url": image_url,
        "images": images,
        "options": product_options,
        "category": category_payload(category) if category else None,
        "review_count": review_count if review_count is not None else product.reviews.count(),
        "review_avg": round(float(review_stats or product.reviews.aggregate(avg=Avg("is_score"))["avg"] or 0), 1),
        "qa_count": qa_count if qa_count is not None else product.qas.count(),
    }
    if detail:
        prev_product = annotate_product_coupon_badge(
            on_sale_products().filter(it_id__lt=product.it_id)
        ).order_by("-it_id").first()
        next_product = annotate_product_coupon_badge(
            on_sale_products().filter(it_id__gt=product.it_id)
        ).order_by("it_id").first()
        # The shop setting de_rel_list_use switches the related-products list off (no lookup at all).
        relation = read_smoke_config(f"rel_{product.it_id}", {}) if related_list_enabled() else {}
        related_ids = [
            item.strip()
            for item in str(relation.get("related_csv") or "").split(",")
            if item.strip()
        ]
        related = annotate_product_coupon_badge(
            on_sale_products().filter(pk__in=related_ids).select_related("category")
        )
        related_by_id = {item.it_id: item for item in related}
        data["prev_item"] = product_payload(prev_product) if prev_product else None
        data["next_item"] = product_payload(next_product) if next_product else None
        data["related_items"] = [
            product_payload(related_by_id[item_id])
            for item_id in related_ids
            if item_id in related_by_id
        ]
    return data


def order_item_payload(item):
    line_unit_price = item.io_price if item.io_type == 1 else item.ct_price + item.io_price
    line_total = max(0, line_unit_price) * item.ct_qty
    return {
        "ct_id": item.ct_id,
        "it_id": item.it_id,
        "it_name": item.it_name,
        "it_seo_title": item.product.it_seo_title if item.product else "",
        "ct_price": item.ct_price,
        "ct_qty": item.ct_qty,
        "ct_point": item.ct_point,
        "line_total": line_total,
        "line_point": item.ct_point * item.ct_qty,
        "ct_option": item.ct_option,
        "ct_status": item.ct_status,
        "ct_stock_use": 1 if item.stock_adjusted else 0,
        "stock_adjusted": bool(item.stock_adjusted),
        "io_type": item.io_type,
        "io_price": item.io_price,
        "ct_notax": item.ct_notax,
        "ct_send_cost": item.ct_send_cost,
        "image_url": thumbnail_url(item.image_url, PRODUCT_LINE_IMAGE_WIDTH),
    }


def order_payload(order, *, detail=False):
    items = list(order.items.select_related("product").all()) if detail else []
    status_value = normalize_order_status(order.od_status)
    # a product coupon on a cancelled, returned or sold-out line no longer counts
    coupons = order_coupon_totals(order, items=items if detail else None)
    cart_coupon, order_coupon, send_coupon = coupons.cart, coupons.order, coupons.send
    if status_value == ORDER_STATUS_CANCELLED:
        cart_coupon = 0
        order_coupon = 0
        send_coupon = 0
    can_cancel, cancel_block_reason = order_cancel_state(order)
    list_price = order.od_cart_price + order.od_send_cost + order.od_send_cost2
    total_price = max(
        0,
        list_price
        - cart_coupon
        - order_coupon
        - send_coupon
        - order.od_cancel_price,
    )
    receipt_total = order.od_receipt_price + order.od_receipt_point
    receipt_url = ""
    if order.od_tno and str(order.od_pg or "").lower() == "toss":
        receipt_url = f"https://dashboard.tosspayments.com/receipt/redirection?transactionId={order.od_tno}"
    delivery_inquiry_url = ""
    if order.od_invoice:
        delivery_inquiry_url = f"https://trace.cjlogistics.com/next/tracking.html?wblNo={order.od_invoice}"
    cash_receipt_url = safe_receipt_url(order.od_cash_res)
    bank_account = str(order.od_bank_account or "").strip()
    if not bank_account and settle_case_is_bank(order.od_settle_case):
        # Older orders did not persist the selected account. Keep their prior
        # instructions available from current settings when possible.
        bank_account = "\n".join(configured_bank_accounts())
    data = {
        "od_id": order.od_id,
        "uid": order.uid,
        "mb_id": order.user.get_username() if order.user_id else "",
        "item_count": order.items.count(),
        "od_cart_count": order.items.count(),
        "od_name": order.od_name,
        "od_tel": order.od_tel,
        "od_hp": order.od_hp,
        "od_email": order.od_email,
        "od_zip": order.od_zip,
        "od_addr1": order.od_addr1,
        "od_addr2": order.od_addr2,
        "od_addr3": order.od_addr3,
        "od_b_name": order.od_b_name,
        "od_b_tel": order.od_b_tel,
        "od_b_hp": order.od_b_hp,
        "od_b_zip": order.od_b_zip,
        "od_b_addr1": order.od_b_addr1,
        "od_b_addr2": order.od_b_addr2,
        "od_b_addr3": order.od_b_addr3,
        "od_memo": order.od_memo,
        "od_hope_date": order.od_hope_date.isoformat() if order.od_hope_date else "",
        "od_cart_price": order.od_cart_price,
        "od_send_cost": order.od_send_cost,
        "od_send_cost2": order.od_send_cost2,
        "od_receipt_price": order.od_receipt_price,
        "od_cancel_price": order.od_cancel_price,
        "od_refund_price": order.od_refund_price,
        "od_receipt_point": order.od_receipt_point,
        "od_deposit_name": order.od_deposit_name,
        "od_status": status_value,
        "od_settle_case": order.od_settle_case,
        "od_bank_account": bank_account if settle_case_is_bank(order.od_settle_case) else "",
        "od_vbank_bank_code": order.od_vbank_bank_code if detail else "",
        "od_vbank_account": order.od_vbank_account if detail else "",
        "od_vbank_customer_name": order.od_vbank_customer_name if detail else "",
        "od_vbank_due_date": order.od_vbank_due_date if detail else "",
        "od_vbank_status": order.od_vbank_status if detail else "",
        "od_test": order.od_test,
        "od_misu": order.od_misu,
        "od_pg": order.od_pg,
        "od_tno": order.od_tno,
        "od_app_no": order.od_app_no,
        "od_tax_flag": order.od_tax_flag,
        "od_tax_invoice_request": order.od_tax_invoice_request,
        "od_tax_mny": order.od_tax_mny,
        "od_vat_mny": order.od_vat_mny,
        "od_free_mny": order.od_free_mny,
        "od_coupon": order.od_coupon,
        "od_cart_coupon": cart_coupon,
        "od_send_coupon": order.od_send_coupon,
        "od_point": order.od_point,
        "od_cash_request": order.od_cash_request,
        "od_cash_type": order.od_cash_type,
        "od_cash": 1 if order.od_cash_no else 0,
        "od_cash_no": order.od_cash_no,
        "od_cash_res": order.od_cash_res,
        "od_cash_info": f"현금영수증 승인번호 {order.od_cash_no}" if order.od_cash_no else "",
        "od_datetime": datetime_value(order.od_datetime),
        "od_time": datetime_value(order.od_datetime),
        "od_receipt_time": order.od_receipt_time,
        "od_ip": order.od_ip or "",
        "od_total_price": total_price,
        "od_order_price": order.od_cart_price,
        "od_list_price": list_price,
        "od_receipt_total": receipt_total,
        "od_misu_price": max(0, total_price - (receipt_total - order.od_refund_price)),
        "od_is_fully_paid": order.od_misu <= 0,
        "od_delivery_company": order.od_delivery_company,
        "od_invoice": order.od_invoice,
        "od_invoice_time": order.od_invoice_time,
        "delivery_inquiry_url": delivery_inquiry_url,
        "od_delivery_inquiry_url": delivery_inquiry_url,
        "receipt_url": receipt_url,
        "od_payment_receipt_url": receipt_url,
        "od_payment_app_label": "승인번호" if order.od_app_no else "거래번호" if order.od_tno else "",
        "od_payment_app_value": order.od_app_no or order.od_tno,
        "cash_receipt_url": cash_receipt_url,
        "od_cash_receipt_url": cash_receipt_url,
        "cash_receipt_issue_url": "" if order.od_cash_no else "",
        "od_cash_receipt_issue_url": "" if order.od_cash_no else "",
        "can_cancel": can_cancel,
        "cancel_block_reason": cancel_block_reason,
    }
    if detail:
        data["items"] = [order_item_payload(item) for item in items]
    return data


def create_order_from_request(request, data, *, order_id=None, force_status=None):
    user = current_user(request)
    guest_password = str(data.get("od_pwd") or "").strip()
    if not user and not guest_password:
        raise StockAdjustmentError(
            "Guest order password is required.",
            code="guest_order_password_required",
        )
    cart = cart_payload(request, data.get("ct_ids"))
    if not cart["items"]:
        raise StockAdjustmentError("Cart is empty.", code="cart_empty")
    if refresh_cart_prices(request, {str(item["ct_id"]) for item in cart["items"]}):
        # YoungCart orderform: a price that changed after the cart was shown stops the order, so the
        # customer sees the new amount before paying it.
        raise StockAdjustmentError(
            "장바구니 금액에 변동사항이 있습니다. 장바구니를 다시 확인해 주세요.",
            code="cart_price_changed",
        )
    hope_date = order_hope_date(data)
    order_id = order_id or generate_numeric_order_id()
    selected_ct_ids = {str(item["ct_id"]) for item in cart["items"]}
    cart_total = cart["total_price"]
    product_coupons = product_coupon_entries(user, cart["items"])
    item_coupon_entries = [(coupon, discount) for _, coupon, discount in product_coupons]
    # each product coupon is at most its product's total, so together they never pass cart_total
    cart_coupon = sum(discount for _, discount in item_coupon_entries)
    # the lines as ordered: each product's validated coupon on its first line (tax split, snapshot)
    coupon_lines = items_with_product_coupon_prices(cart["items"], product_coupons)
    orderer_zip = normalize_zip_from_keys(
        data,
        full_keys=("od_zip", "zip"),
        split_keys=("od_zip1", "od_zip2"),
    )
    recipient_zip = normalize_zip_from_keys(
        data,
        full_keys=("od_b_zip", "b_zip"),
        split_keys=("od_b_zip1", "od_b_zip2"),
        default=orderer_zip,
    )
    shipping = shipping_quote(cart_total, recipient_zip, items=cart["items"])
    send_cost = shipping["base"]
    send_cost2 = shipping["extra"]
    settle_case = str(data.get("od_settle_case") or data.get("payment_method") or "bank")
    if not online_payment_method_enabled(settle_case):
        raise StockAdjustmentError(
            "사용할 수 없는 결제수단입니다. 결제수단을 다시 선택해 주세요.",
            code="payment_method_disabled",
        )
    is_bank_settle = settle_case in {"bank", "무통장", "무통장입금"}
    if not is_bank_settle and not force_status:
        # an online payment is created through payment prepare and marked paid only after the
        # gateway approves it (YoungCart orderformupdate.php); never paid here on the client's word
        raise StockAdjustmentError("결제수단을 다시 선택해 주세요.", code="payment_requires_gateway")
    tax_invoice_request = bool_int(data.get("od_tax_invoice_request")) == 1
    cash_receipt_request = bool_int(data.get("od_cash_request")) == 1
    cash_receipt_type = str(data.get("od_cash_type") or "income").strip()
    cash_receipt_identity_number = re.sub(
        r"\D+", "", str(data.get("cash_receipt_registration_number") or "")
    )
    tax_invoice_company = str(data.get("od_tax_company") or "").strip()
    tax_invoice_business_no = re.sub(r"\D+", "", str(data.get("od_tax_business_no") or ""))
    tax_invoice_email = str(data.get("od_tax_email") or "").strip()
    if (tax_invoice_request or cash_receipt_request) and not (
        user and user.is_authenticated
    ):
        raise StockAdjustmentError(
            "Receipt requests require a member account.",
            code="receipt_request_requires_member",
        )
    if cash_receipt_request:
        if cash_receipt_type not in {"income", "expense"}:
            raise StockAdjustmentError(
                "Select a valid cash receipt type.",
                code="cash_receipt_type_invalid",
            )
        if not settle_case_supports_cash_receipt(settle_case):
            raise StockAdjustmentError(
                "Cash receipt requests are available only for bank transfer, virtual account, or account transfer.",
                code="cash_receipt_payment_method_invalid",
            )
        if not cash_receipt_method_enabled(settle_case):
            raise StockAdjustmentError(
                "Cash receipt requests are not enabled for this payment method.",
                code="cash_receipt_method_disabled",
            )
        if not settle_case_is_bank(settle_case):
            identity_length = len(cash_receipt_identity_number)
            identity_is_valid = (
                identity_length == 10
                if cash_receipt_type == "expense"
                else 8 <= identity_length <= 30
            )
            if not identity_is_valid:
                raise StockAdjustmentError(
                    "Enter a valid cash receipt identification number.",
                    code="cash_receipt_identity_invalid",
                )
    else:
        cash_receipt_type = ""
        cash_receipt_identity_number = ""
    if tax_invoice_request:
        if not tax_invoice_company or len(tax_invoice_company) > 100:
            raise StockAdjustmentError(
                "Enter the company name for the tax invoice.",
                code="tax_invoice_company_required",
            )
        if len(tax_invoice_business_no) != 10:
            raise StockAdjustmentError(
                "Enter a 10-digit business registration number.",
                code="tax_invoice_business_number_invalid",
            )
        if len(tax_invoice_email) > 254:
            raise StockAdjustmentError(
                "The tax invoice email address is too long.",
                code="tax_invoice_email_invalid",
            )
        try:
            validate_email(tax_invoice_email)
        except ValidationError as exc:
            raise StockAdjustmentError(
                "Enter a valid email address for the tax invoice.",
                code="tax_invoice_email_invalid",
            ) from exc
    else:
        tax_invoice_company = ""
        tax_invoice_business_no = ""
        tax_invoice_email = ""
    bank_accounts = configured_bank_accounts()
    selected_bank_account = str(data.get("od_bank_account") or "").strip()
    deposit_name = str(data.get("od_deposit_name") or "").strip()
    if is_bank_settle:
        if not bank_accounts:
            raise StockAdjustmentError(
                "Bank transfer is not configured.",
                code="bank_transfer_unavailable",
            )
        if not selected_bank_account or selected_bank_account not in bank_accounts:
            raise StockAdjustmentError(
                "Select a configured bank account.",
                code="bank_account_invalid",
            )
        if not deposit_name:
            raise StockAdjustmentError(
                "Enter the depositor name.",
                code="deposit_name_required",
            )
        if len(deposit_name) > 100:
            raise StockAdjustmentError(
                "Depositor name is too long.",
                code="deposit_name_too_long",
            )
    else:
        selected_bank_account = ""
        deposit_name = ""
    status_value = normalize_order_status(force_status) if force_status else (ORDER_STATUS_ORDERED if is_bank_settle else ORDER_STATUS_PAID)
    order_coupon = 0
    send_coupon = 0
    coupon_entries = list(item_coupon_entries)

    order_cp_id = str(data.get("cp_id") or data.get("cp_id_order") or "").strip()
    if user and order_cp_id:
        coupon = valid_coupons_queryset(user).filter(pk=order_cp_id, cp_method=2).first()
        if coupon:
            order_base = max(0, cart_total - cart_coupon)
            if coupon_exceeds_base(coupon, order_base):
                # YoungCart orderformupdate.php dies ('Order coupon error.') rather than shrink it
                raise StockAdjustmentError(
                    "쿠폰할인금액이 주문금액보다 크므로 쿠폰을 적용할 수 없습니다.",
                    code="order_coupon_exceeds_amount",
                )
            order_coupon = coupon_raw_discount(coupon, order_base)
            if order_coupon > 0:
                coupon_entries.append((coupon, order_coupon))

    send_cp_id = str(data.get("cp_id_send") or "").strip()
    if user and send_cp_id and send_cost > 0:
        coupon = valid_coupons_queryset(user).filter(pk=send_cp_id, cp_method=3).first()
        if coupon:
            # YoungCart orderformupdate.php: the base shipping fee only (not the remote-area extra),
            # with the coupon minimum checked against the order amount after the product and order
            # coupons ($tot_od_price)
            send_coupon = min(
                coupon_discount(coupon, send_cost, minimum_base=cart_total - cart_coupon - order_coupon),
                send_cost,
            )
            if send_coupon > 0:
                coupon_entries.append((coupon, send_coupon))

    point_use = 0
    if user:
        requested_point = max(0, safe_int(data.get("point_use") or data.get("od_receipt_point"), 0))
        if requested_point > 0:
            profile, _ = Profile.objects.get_or_create(user=user)
            point_use = allowed_point_use(
                requested_point,
                profile.user_point,
                cart_total - cart_coupon - order_coupon,
            )

    receipt_due = max(0, cart_total + send_cost + send_cost2 - cart_coupon - order_coupon - send_coupon - point_use)
    tax_amounts = calculate_order_tax_amounts(
        coupon_lines,
        send_cost=send_cost,
        send_cost2=send_cost2,
        order_coupon=order_coupon,
        send_coupon=send_coupon,
        receipt_point=point_use,
        payable_amount=receipt_due,
        mixed_tax_enabled=bool(current_shipping_policy().de_tax_flag_use),
    )
    receipt_price = receipt_due if force_status or status_value in PAID_STATUSES else 0
    misu_price = 0 if status_value in PAID_STATUSES else receipt_due
    now_label = timezone.localtime().strftime("%Y-%m-%d %H:%M:%S") if status_value in PAID_STATUSES else ""
    # Coupons are consumed when the order is created, also for an order waiting for an online
    # payment, so one coupon cannot discount two pending orders; cancelling or expiring the order
    # gives it back (restore_order_coupons_and_points).
    mark_coupons_used = True
    address_subject = str(data.get("ad_subject") or data.get("address_subject") or "").strip()
    should_save_address = bool(
        user
        and user.is_authenticated
        and (
            bool_int(data.get("save_address"))
            or bool_int(data.get("ad_default"))
            or address_subject
        )
    )
    # youngcart cartupdate.php / orderformupdate.php: each line records its purchase point; with
    # de_card_point off an order paid online (card, transfer, phone, easy pay) records none.
    earns_line_points = order_line_points_enabled(settle_case, receipt_due)
    with transaction.atomic():
        order = ShopOrder.objects.create(**fit_to_columns(ShopOrder, dict(
            od_id=order_id,
            user=user if user and user.is_authenticated else None,
            od_name=str(data.get("od_name") or data.get("name") or getattr(user, "username", "") or "Guest"),
            od_tel=str(data.get("od_tel") or ""),
            od_hp=str(data.get("od_hp") or data.get("od_b_hp") or ""),
            od_email=str(data.get("od_email") or getattr(user, "email", "") or ""),
            od_zip=orderer_zip or recipient_zip,
            od_addr1=str(data.get("od_addr1") or data.get("od_b_addr1") or ""),
            od_addr2=str(data.get("od_addr2") or data.get("od_b_addr2") or ""),
            od_addr3=str(data.get("od_addr3") or data.get("od_b_addr3") or ""),
            od_b_name=str(data.get("od_b_name") or data.get("od_name") or ""),
            od_b_tel=str(data.get("od_b_tel") or data.get("od_tel") or ""),
            od_b_hp=str(data.get("od_b_hp") or data.get("od_hp") or ""),
            od_b_zip=recipient_zip or orderer_zip,
            od_b_addr1=str(data.get("od_b_addr1") or data.get("od_addr1") or ""),
            od_b_addr2=str(data.get("od_b_addr2") or data.get("od_addr2") or ""),
            od_b_addr3=str(data.get("od_b_addr3") or data.get("od_addr3") or ""),
            od_memo=str(data.get("od_memo") or ""),
            od_hope_date=hope_date,
            od_cart_price=cart_total,
            od_send_cost=send_cost,
            od_send_cost2=send_cost2,
            od_receipt_price=receipt_price,
            od_receipt_point=point_use,
            od_bank_account=selected_bank_account,
            od_deposit_name=deposit_name,
            od_status=status_value,
            od_settle_case=settle_case,
            od_misu=misu_price,
            od_pg=str(data.get("od_pg") or data.get("pg_service") or ""),
            od_coupon=order_coupon,
            od_send_coupon=send_coupon,
            od_tax_flag=tax_amounts["od_tax_flag"],
            od_tax_invoice_request=tax_invoice_request,
            od_tax_company=tax_invoice_company,
            od_tax_business_no=tax_invoice_business_no,
            od_tax_email=tax_invoice_email,
            od_tax_mny=tax_amounts["od_tax_mny"],
            od_vat_mny=tax_amounts["od_vat_mny"],
            od_free_mny=tax_amounts["od_free_mny"],
            od_cash_request=cash_receipt_request,
            od_cash_type=cash_receipt_type,
            od_receipt_time=now_label,
            od_ip=get_client_ip(request),
        )))
        for item in cart["items"]:
            product = reserve_product_stock(item["it_id"], item["ct_qty"], item.get("ct_option") or "", item.get("io_type") or 0)
            ShopOrderItem.objects.create(
                order=order,
                product=product,
                ct_id=item["ct_id"],
                it_id=item["it_id"],
                it_name=item["it_name"],
                ct_price=item["ct_price"],
                ct_qty=item["ct_qty"],
                ct_point=item_purchase_point(
                    product,
                    io_type=item.get("io_type") or 0,
                    io_price=item.get("io_price") or 0,
                    has_option=bool(item.get("ct_option")),
                ) if earns_line_points else 0,
                ct_option=item["ct_option"],
                ct_status=status_value,
                io_type=item.get("io_type") or 0,
                io_price=item.get("io_price") or 0,
                ct_notax=item.get("ct_notax") or 0,
                ct_send_cost=item.get("ct_send_cost") or 0,
                stock_adjusted=True,
                # Keep the original picture: the cart line carries a signed list-size copy URL.
                image_url=(product_image_url(product) if product else "") or item.get("image_url") or "",
            )

        if should_save_address:
            is_default_address = bool_int(data.get("ad_default")) == 1
            if is_default_address:
                ShopAddress.objects.filter(user=user).update(ad_default=False)
            ShopAddress.objects.create(
                user=user,
                ad_subject=address_subject or order.od_b_name or "배송지",
                ad_default=is_default_address,
                ad_name=order.od_b_name,
                ad_tel=order.od_b_tel,
                ad_hp=order.od_b_hp,
                ad_zip=order.od_b_zip,
                ad_addr1=order.od_b_addr1,
                ad_addr2=order.od_b_addr2,
                ad_addr3=order.od_b_addr3,
                ad_jibeon=str(data.get("od_b_addr_jibeon") or data.get("ad_jibeon") or ""),
            )

        for coupon, discount in coupon_entries:
            ShopCouponLog.objects.create(
                cl_id=next_coupon_log_id(),
                coupon=coupon,
                cp_id=coupon.cp_id,
                user=user if user and user.is_authenticated else None,
                mb_id=user.get_username() if user and user.is_authenticated else "",
                order=order,
                od_id=order.od_id,
                cp_price=discount,
                cl_datetime=timezone.now(),
            )
            if coupon.cp_all_members:
                # one use per member: the coupon row is locked so two orders cannot both pass
                ShopCoupon.objects.select_for_update().filter(pk=coupon.pk).first()
                if ShopCouponLog.objects.filter(coupon=coupon, user=user).exclude(order=order).exists():
                    raise StockAdjustmentError("Coupon was already used.", code="coupon_already_used")
            elif mark_coupons_used and not ShopCoupon.objects.filter(pk=coupon.pk, cp_used="").update(cp_used="1"):
                raise StockAdjustmentError("Coupon was already used.", code="coupon_already_used")

        if user and point_use > 0:
            if not change_member_point(user, -point_use, f"주문번호 {order.od_id} 결제", "@order", order.od_id):
                raise StockAdjustmentError("Not enough points.", code="insufficient_points")

        if not user and guest_password:
            Config.objects.update_or_create(
                name=guest_order_password_config_name(order.od_id),
                defaults={"value": guest_order_password_hash(guest_password)},
            )

        ShopOrderData.objects.update_or_create(
            log_id=f"cart-{order.od_id}"[:40],
            defaults={
                "order": order,
                "od_id": order.od_id,
                "cart_id": "",
                "user": user if user and user.is_authenticated else None,
                "mb_id": user.get_username() if user and user.is_authenticated else "",
                "dt_pg": "cart:prepared" if force_status else "cart:order",
                "dt_data": json.dumps(coupon_lines, ensure_ascii=False, default=str),
                "dt_time": timezone.now(),
            },
        )

    remaining_items = [item for item in cart_items(request) if str(item.get("ct_id")) not in selected_ct_ids]
    save_cart_items(request, remaining_items)
    if not user:
        guest_order_ids = list(request.session.get("g5_guest_order_ids", []))
        if order.od_id not in guest_order_ids:
            guest_order_ids.append(order.od_id)
        request.session["g5_guest_order_ids"] = guest_order_ids[-20:]
        request.session.modified = True
    return order


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def categories_view(request):
    return categories_response(request)


def categories_response(request):
    queryset = ShopCategory.objects.filter(ca_use=True).annotate(item_count=category_tree_item_count()).order_by("ca_order", "ca_id")
    categories = list(queryset)
    children = {}
    for category in categories:
        children.setdefault(category.ca_parent, []).append(category_payload(category))
    return api_response(data=[
        {**category_payload(category), "children": children.get(category.ca_id, [])}
        for category in categories if not category.ca_parent
    ])


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def category_detail_view(request, ca_id):
    category = ShopCategory.objects.filter(pk=ca_id, ca_use=True).annotate(item_count=category_tree_item_count()).first()
    if not category:
        return api_error("Category not found.", status=drf_status.HTTP_404_NOT_FOUND, code="category_not_found")
    products = annotate_product_coupon_badge(
        category_tree_products(category.ca_id).filter(it_use="1").select_related("category")
    ).annotate(
        review_count=Count("reviews", distinct=True),
        qa_count=Count("qas", distinct=True),
        review_stats=Avg("reviews__is_score"),
    ).order_by(*shop_product_ordering(request.query_params.get("sort"), request.query_params.get("sortodr")))
    page, meta = paginate_queryset(request, products, default_per_page=20)
    subcategories = (
        ShopCategory.objects.filter(ca_parent=category.ca_id, ca_use=True)
        .annotate(item_count=category_tree_item_count())
        .order_by("ca_order", "ca_id")
    )
    return api_response(
        data={
            "category": category_payload(category),
            "subcategories": [category_payload(item) for item in subcategories],
            "items": [product_payload(product) for product in page],
            "meta": meta,
        },
        meta=meta,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def products_view(request):
    return products_response(request)


def products_response(request, *, limit=None):
    queryset = on_sale_products().select_related("category")
    ca_id = request.query_params.get("ca_id") or request.query_params.get("category")
    q = request.query_params.get("q") or request.query_params.get("stx")
    product_type = request.query_params.get("type")
    sort = (request.query_params.get("sort") or "").strip().lower()
    if ca_id:
        queryset = queryset.filter(category_tree_member_q(ca_id))
    if q:
        # search.php: the ticked name / description / code / summary columns, all when none is ticked
        queryset = search_products(queryset, q, request.query_params)
    if product_type in {"1", "2", "3", "4", "5"}:
        queryset = queryset.filter(**{f"it_type{product_type}": "1"})
    for type_index in range(1, 6):
        if request.query_params.get(f"it_type{type_index}") == "1":
            queryset = queryset.filter(**{f"it_type{type_index}": "1"})
    qfrom = request.query_params.get("qfrom")
    qto = request.query_params.get("qto")
    if qfrom not in (None, ""):
        queryset = queryset.filter(it_price__gte=max(0, safe_int(qfrom, 0)))
    if qto not in (None, ""):
        queryset = queryset.filter(it_price__lte=max(0, safe_int(qto, 0)))
    queryset = annotate_product_coupon_badge(queryset).annotate(
        review_count=Count("reviews", distinct=True),
        qa_count=Count("qas", distinct=True),
        review_stats=Avg("reviews__is_score"),
    )
    relevance = ["-_search_rank"] if q and sort in {"", "default", "relevance"} and "_search_rank" in queryset.query.annotations else []
    queryset = queryset.order_by(*relevance, *shop_product_ordering(sort, request.query_params.get("sortodr")))
    if limit is None:
        page, meta = paginate_queryset(request, queryset, default_per_page=20)
    else:
        page, meta = queryset[:limit], {}
    return api_response(data=[product_payload(product) for product in page], meta=meta)


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def product_detail_view(request, it_id):
    product = annotate_product_coupon_badge(
        on_sale_products().select_related("category").filter(pk=it_id)
    ).first()
    if not product:
        return api_error("Product not found.", status=drf_status.HTTP_404_NOT_FOUND, code="product_not_found")
    return api_response(data=product_payload(product, request, detail=True))


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def product_by_seo_view(request, slug):
    product = annotate_product_coupon_badge(
        on_sale_products().select_related("category").filter(it_seo_title=slug)
    ).first()
    if not product:
        return api_error("Product not found.", status=drf_status.HTTP_404_NOT_FOUND, code="product_not_found")
    return api_response(data=product_payload(product, request, detail=True))


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def product_hit_view(request, it_id):
    product = on_sale_products().filter(pk=it_id).only("it_id").first()
    if not product:
        return api_error("Product not found.", status=drf_status.HTTP_404_NOT_FOUND, code="product_not_found")

    today = timezone.localdate().isoformat()
    session_hits = request.session.get("shop_viewed_products", {})
    if not isinstance(session_hits, dict) or session_hits.get("date") != today:
        session_hits = {"date": today, "ids": []}
    stored_ids = session_hits.get("ids", [])
    seen_ids = [str(value) for value in stored_ids] if isinstance(stored_ids, list) else []
    recorded = str(it_id) not in seen_ids
    if recorded:
        ShopProduct.objects.filter(pk=product.pk).update(it_hit=F("it_hit") + 1)
        session_hits["ids"] = (seen_ids + [str(it_id)])[-100:]
        request.session["shop_viewed_products"] = session_hits

    return api_response(data={"it_id": it_id, "recorded": recorded})


@api_view(["GET"])
@permission_classes([AllowAny])
def product_suggest_view(request):
    query = (request.query_params.get("q") or request.query_params.get("keyword") or "").strip()
    if len(query) < 2:
        return api_response(data=[])
    limit = min(max(safe_int(request.query_params.get("limit"), 10), 1), 20)
    queryset = (
        on_sale_products()
        .select_related("category")
        .order_by("it_name", "it_id")
    )
    queryset = apply_text_search(
        queryset,
        query,
        any_icontains(("it_id", "it_name", "it_basic"), query),
    )[:limit]
    return api_response(
        data=[
            {
                "it_id": product.it_id,
                "it_name": product.it_name,
                "it_seo_title": product.it_seo_title,
                "it_price": product.it_price,
                "it_tel_inq": product.it_tel_inq,
                "image_url": product_thumbnail_url(product),
                "ca_id": product.category_id or "",
            }
            for product in queryset
        ]
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@throttle_classes([ScopedRateThrottle])
def product_stock_notify_view(request, it_id):
    data = request_data(request)
    agree = data.get("agree")
    if isinstance(agree, str):
        agree = agree.strip().lower() in {"1", "true", "yes", "on"}
    if not agree:
        return api_error(
            "Consent to the privacy notice is required.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details={"agree": "Consent to the privacy notice is required."},
        )

    raw_hp = data.get("hp") or data.get("phone") or ""
    phone_digits = re.sub(r"\D+", "", str(raw_hp))
    if not re.fullmatch(r"01[0-9]{8,9}", phone_digits):
        return api_error(
            "A valid phone number is required.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details={"hp": "Enter a valid South Korean mobile number."},
        )

    hp = normalize_hp(phone_digits)
    with transaction.atomic():
        product = ShopProduct.objects.select_for_update().filter(pk=it_id).first()
        if not product:
            return api_error("Product not found.", status=drf_status.HTTP_404_NOT_FOUND, code="product_not_found")
        if str(product.it_soldout or "0") != "1" and safe_int(product.it_stock_qty, 0) > 0:
            return api_error(
                "Product is currently in stock.",
                status=drf_status.HTTP_409_CONFLICT,
                code="stock_available",
                details={"it_id": product.it_id, "it_stock_qty": product.it_stock_qty},
            )
        if str(product.it_stock_sms or "0") != "1":
            return api_error(
                "Restock notifications are not enabled for this product.",
                status=drf_status.HTTP_409_CONFLICT,
                code="stock_notification_disabled",
            )
        existing_phone_numbers = ShopStockNotification.objects.filter(
            it_id=product.it_id,
            ss_send=False,
        ).values_list("ss_hp", flat=True)
        if any(re.sub(r"\D+", "", existing_hp) == phone_digits for existing_hp in existing_phone_numbers):
            return api_error(
                "Already subscribed.",
                status=drf_status.HTTP_409_CONFLICT,
                code="already_subscribed",
                details={"already_subscribed": True},
            )
        ShopStockNotification.objects.create(
            product=product,
            it_id=product.it_id,
            ss_hp=hp,
            ss_datetime=timezone.now(),
            ss_ip=str(get_client_ip(request) or "")[:45],
        )
    return api_response(data={"registered": True, "it_id": product.it_id}, status=drf_status.HTTP_201_CREATED)


product_stock_notify_view.cls.throttle_scope = "stock-notify"


# The main banner spans the content width (1440px at most), so a 1440px copy is sharp enough.
BANNER_IMAGE_WIDTH = 1440


@api_view(["GET"])
@permission_classes([AllowAny])
def banners_view(request):
    return banners_response(request)


def banners_response(request):
    now = timezone.now()
    position = (request.query_params.get("position") or "메인").strip()
    device = (request.query_params.get("device") or "all").strip().lower()
    if device not in {"pc", "desktop", "mobile", "all"}:
        device = "all"
    if device == "desktop":
        device = "pc"

    banners = ShopBanner.objects.filter(
        is_active=True,
        bn_position=position,
    ).filter(
        Q(begin_at__isnull=True) | Q(begin_at__lte=now),
        Q(end_at__isnull=True) | Q(end_at__gte=now),
    )
    if device != "all":
        banners = banners.filter(bn_device__in=[device, "all", "both"])

    data = []
    for banner in banners:
        if banner.image_file:
            image_url = thumbnail_url(banner.image_file.url, BANNER_IMAGE_WIDTH, storage_path=banner.image_file.name)
        else:
            image_url = thumbnail_url(legacy_shop_asset_url(banner.image_url), BANNER_IMAGE_WIDTH)
        if image_url.startswith("/sample-data/"):
            # These bundled demo assets are served by the Next.js frontend. Keep them relative so
            # they resolve on that host even when Django's API runs as a separate Vercel project.
            pass
        elif image_url.startswith("/"):
            image_url = request.build_absolute_uri(image_url)
        data.append(
            {
                "bn_id": banner.bn_id,
                "bn_alt": banner.bn_alt,
                "bn_url": banner.bn_url,
                "bn_position": banner.bn_position,
                "bn_device": banner.bn_device,
                "bn_border": int(banner.bn_border),
                "bn_new_win": int(banner.bn_new_win),
                "bn_order": banner.bn_order,
                "image_url": image_url,
                "hit_url": f"/shop/bannerhit.php?bn_id={banner.bn_id}",
            }
        )
    return api_response(data=data)


@api_view(["GET"])
@permission_classes([AllowAny])
def banner_hit_view(request, bn_id):
    banner = ShopBanner.objects.filter(pk=bn_id, is_active=True).first()
    if not banner:
        return api_error("Banner not found.", status=drf_status.HTTP_404_NOT_FOUND, code="banner_not_found")

    if request.query_params.get("count") == "1":
        ShopBanner.objects.filter(pk=banner.pk).update(hit_count=F("hit_count") + 1)
    return api_response(data={"redirect_url": banner.bn_url})


@api_view(["GET"])
@permission_classes([AllowAny])
def popups_view(request):
    return popups_response(request)


def popups_response(request):
    return api_response(data=[])


@api_view(["GET"])
@permission_classes([AllowAny])
def policy_view(request):
    return api_response(data=shop_policy_payload())


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def shipping_quote_view(request):
    cart = cart_payload(request)
    policy = shop_policy_payload()
    item_total = cart["total_price"]
    if item_total <= 0:
        return api_error(
            "Cart is empty. Add items before quoting shipping.",
            status=drf_status.HTTP_400_BAD_REQUEST,
            code="cart_empty",
        )
    postal_code = normalize_zip_from_keys(
        request.query_params,
        full_keys=("od_b_zip", "zip"),
        split_keys=("zip1", "zip2"),
    )
    shipping = shipping_quote(item_total, postal_code, items=cart["items"])
    return api_response(
        data={
            "item_total": item_total,
            "cart_coupon": cart.get("cart_coupon", 0),
            "zip1": request.query_params.get("zip1") or "",
            "zip2": request.query_params.get("zip2") or "",
            "base": shipping["base"],
            "extra": shipping["extra"],
            "total": shipping["total"],
            "free_threshold": policy["free_threshold"],
            "free_remaining": max(0, policy["free_threshold"] - item_total),
            "policy": policy,
        }
    )


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def addresses_view(request):
    user, error = require_user(request)
    if error:
        return error
    if request.method == "GET":
        queryset = ShopAddress.objects.filter(user=user)
        page, meta = paginate_queryset(request, queryset, default_per_page=20)
        return api_response(data=[address_payload(item) for item in page], meta=meta)

    data = request_data(request)
    missing = {
        field: "필수 입력 항목입니다."
        for field, value in (
            ("ad_name", data.get("ad_name") or data.get("name")),
            ("ad_zip", normalize_address_zip(data)),
            ("ad_addr1", data.get("ad_addr1")),
        )
        if not str(value or "").strip()
    }
    if missing:
        return api_error("배송지 정보를 입력해 주세요.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, code="validation_error", details=missing)
    is_default = bool(bool_int(data.get("ad_default")))
    if is_default:
        ShopAddress.objects.filter(user=user).update(ad_default=False)
    address = ShopAddress.objects.create(
        user=user,
        ad_subject=str(data.get("ad_subject") or data.get("subject") or ""),
        ad_default=is_default,
        ad_name=str(data.get("ad_name") or data.get("name") or ""),
        ad_tel=str(data.get("ad_tel") or ""),
        ad_hp=str(data.get("ad_hp") or ""),
        ad_zip=normalize_address_zip(data),
        ad_addr1=str(data.get("ad_addr1") or ""),
        ad_addr2=str(data.get("ad_addr2") or ""),
        ad_addr3=str(data.get("ad_addr3") or ""),
        ad_jibeon=str(data.get("ad_jibeon") or ""),
    )
    return api_response(data=address_payload(address), status=drf_status.HTTP_201_CREATED)


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([JSONParser, FormParser])
def orders_view(request):
    if request.method == "GET":
        user = current_user(request)
        queryset = ShopOrder.objects.all()
        if user:
            queryset = queryset.filter(user=user)
        else:
            queryset = queryset.none()
        page, meta = paginate_queryset(request, queryset, default_per_page=10)
        return api_response(data=[order_payload(order) for order in page], meta=meta)

    try:
        order = create_order_from_request(request, request_data(request))
    except StockAdjustmentError as exc:
        return api_error(str(exc), status=drf_status.HTTP_400_BAD_REQUEST, code=exc.code, details=exc.details)
    # youngcart orderformupdate.php ordermail1/2: a bank-deposit order is complete once it is saved
    queue_order_placed_mails(order)
    data = order_payload(order, detail=True)
    redirect_url = f"/shop/orders/{order.od_id}" if order.user_id else f"/shop/orders/{order.od_id}?uid={order.uid}"
    return api_response(
        data={"order": data, "od_id": order.od_id, "order_id": order.od_id, "uid": order.uid, "redirect_url": redirect_url},
        status=drf_status.HTTP_201_CREATED,
    )


@api_view(["GET", "PATCH"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def order_detail_view(request, od_id):
    user = current_user(request)
    uid = request.query_params.get("uid") or request_data(request).get("uid")
    queryset = ShopOrder.objects.filter(pk=od_id)
    guest_uid_filter = Q(user__isnull=True, uid=uid) if uid else Q(pk__in=[])
    if user and user.is_authenticated:
        queryset = queryset.filter(Q(user=user) | guest_uid_filter)
    elif uid:
        queryset = queryset.filter(user__isnull=True, uid=uid)
    else:
        queryset = queryset.none()
    order = queryset.first()
    if not order:
        return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
    if request.method == "PATCH":
        can_cancel, reason = order_cancel_state(order)
        if not can_cancel:
            return api_error(reason or "Order cannot be cancelled.", status=drf_status.HTTP_400_BAD_REQUEST, code="order_cancel_blocked")
        data = request_data(request)
        toss_cancel_error = cancel_pending_toss_vbank(order, str(data.get("reason") or "cancelled"))
        if toss_cancel_error:
            return toss_cancel_error
        order, _, cancel_error = cancel_shop_order_locally(order.pk, str(data.get("reason") or "cancelled"))
        if cancel_error:
            return cancel_error
    return api_response(data=order_payload(order, detail=True))


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ScopedRateThrottle])
def order_lookup_view(request):
    data = request_data(request)
    order = ShopOrder.objects.filter(pk=str(data.get("od_id") or "").strip()).first()
    if not order or order.user_id is not None:
        guest_order_password_matches("", data.get("od_pwd"), "")  # same cost as a real lookup
        return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
    stored = Config.objects.filter(name=guest_order_password_config_name(order.od_id)).values_list("value", flat=True).first()
    if not stored or not guest_order_password_matches(order.od_id, data.get("od_pwd"), stored):
        return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
    if guest_order_password_needs_upgrade(stored):
        Config.objects.update_or_create(
            name=guest_order_password_config_name(order.od_id),
            defaults={"value": guest_order_password_hash(data.get("od_pwd"))},
        )
    return api_response(data={"od_id": order.od_id, "uid": order.uid, "redirect_url": f"/shop/orders/{order.od_id}?uid={order.uid}"})


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([FormParser, JSONParser])
def order_legacy_data_view(request):
    values = request_values(request)
    request.session["g5_shop_order_data"] = values
    request.session.modified = True
    return api_response(data={"saved": True})


def change_member_point(user, delta, content, rel_table, rel_action):
    """Move a member's point balance for an order and record it in the point history.

    A spend is refused (returns False) when the balance no longer covers it, so two orders placed
    at the same moment cannot both use the same points. Refunds apply even if points were
    switched off after the order.
    """
    result = point_ledger.insert_point(
        user, delta, content, rel_table, user.pk, rel_action, require_balance=delta < 0, force=delta > 0
    )
    return result in (point_ledger.APPLIED, point_ledger.DUPLICATE) if delta > 0 else result == point_ledger.APPLIED


def restore_order_coupons_and_points(order):
    point_to_restore = int(order.od_receipt_point or 0)
    coupon_logs = list(order.coupon_logs.select_related("coupon").all())
    for log in coupon_logs:
        if log.coupon_id:
            ShopCoupon.objects.filter(pk=log.cp_id, cp_all_members=False).update(cp_used="")
    if coupon_logs:
        ShopCouponLog.objects.filter(pk__in=[log.pk for log in coupon_logs]).delete()
    if point_to_restore > 0 and order.user_id:
        change_member_point(order.user, point_to_restore, f"주문번호 {order.od_id} 취소", "@order-cancel", order.od_id)


def cancel_order_and_refund_benefits(order, reason, *, refund_price=0, history="", status=ORDER_STATUS_CANCELLED):
    """Cancel an order, put the stock back and give its coupons and points back, once.

    The one cancel path of the customer, the expiry jobs and the admin (which cancels the PG
    payment first and passes the refunded amount; ``status`` 반품 for a returned order). An order
    that is already cancelled is left as it is, so its refund record is not overwritten by a
    second call."""
    with transaction.atomic():
        locked = ShopOrder.objects.select_for_update().filter(pk=order.pk).first() or order
        if str(locked.od_status or "") in CANCELLED_STATUSES:
            return locked, 0
        restore_order_coupons_and_points(locked)
        return cancel_order_with_stock_restore(locked, reason, refund_price=refund_price, history=history, status=status)


def cancel_shop_order_locally(order_id, reason):
    with transaction.atomic():
        order = ShopOrder.objects.select_for_update().filter(pk=order_id).first()
        if not order:
            return None, 0, api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
        if str(order.od_status or "") in CANCELLED_STATUSES:
            return order, 0, None
        can_cancel, block_reason = order_cancel_state(order)
        if not can_cancel:
            return None, 0, api_error(
                block_reason or "Order cannot be cancelled.",
                status=drf_status.HTTP_400_BAD_REQUEST,
                code="order_cancel_blocked",
            )
        order, restored_count = cancel_order_and_refund_benefits(order, reason)
        if settle_case_is_vbank(order.od_settle_case):
            order.od_vbank_status = "CANCELED"
            order.save(update_fields=["od_vbank_status"])
        return order, restored_count, None


def restore_order_cart_snapshot(request, order):
    log = ShopOrderData.objects.filter(log_id=f"cart-{order.od_id}"[:40]).first()
    if not log:
        return 0
    try:
        rows = json.loads(log.dt_data)
    except (TypeError, ValueError):
        rows = []
    if not isinstance(rows, list):
        return 0
    existing = cart_items(request)
    existing_ids = {str(item.get("ct_id")) for item in existing}
    restored = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        ct_id = str(row.get("ct_id") or "")
        if not ct_id or ct_id in existing_ids:
            continue
        existing.append(
            {
                "ct_id": ct_id,
                "it_id": str(row.get("it_id") or ""),
                "it_name": str(row.get("it_name") or row.get("it_id") or ""),
                "ct_price": safe_int(row.get("ct_price"), 0),
                "ct_qty": max(1, safe_int(row.get("ct_qty"), 1)),
                "ct_option": str(row.get("ct_option") or ""),
                "io_type": safe_int(row.get("io_type"), 0),
                "io_price": safe_int(row.get("io_price"), 0),
                "ct_direct": safe_int(row.get("ct_direct"), 0),
                "ct_send_cost": safe_int(row.get("ct_send_cost"), 0),
                "cp_id": str(row.get("cp_id") or ""),
                "cp_price": safe_int(row.get("cp_price"), 0),
            }
        )
        existing_ids.add(ct_id)
        restored += 1
    if restored:
        save_cart_items(request, existing)
    return restored


@api_view(["GET"])
@permission_classes([AllowAny])
def payment_config_view(request):
    toss_config = toss_payment_config()
    adapter_config = payment_adapter_config()
    pg_service = configured_payment_provider()
    # The external adapter can confirm a payment, but this checkout flow does
    # not yet prepare the provider-specific client payload needed to start one.
    # Only advertise the native Toss flow while its client and server keys exist.
    pg_enabled = pg_service == "toss" and toss_config["enabled"]
    bank_accounts = configured_bank_accounts()
    methods = checkout_payment_methods(toss_config=toss_config, pg_service=pg_service, bank_accounts=bank_accounts)
    cash_receipt = cash_receipt_preferences()
    return api_response(
        data={
            "pg_service": pg_service,
            "client": {"client_key": toss_config["client_key"] if pg_enabled else "", "mid": "", "script_url": ""},
            "payment_methods": methods,
            "cash_receipt": cash_receipt,
            "easy_pay_services": ["tosspay"] if methods["easy_pay"] else [],
            "bank_accounts": bank_accounts,
            "hope_date": hope_date_range(),
            "guest_privacy": guest_privacy_html(),
            "is_test_mode": toss_config["is_test_mode"],
            "purchase_point": purchase_point_notice(),
            "providers": {
                "toss": {
                    "enabled": toss_config["enabled"],
                    "has_client_key": bool(toss_config["client_key"]),
                    "has_secret_key": bool(toss_config["has_secret_key"]),
                },
                "adapter": {
                    "enabled": adapter_config["enabled"],
                    "providers": adapter_config["providers"],
                }
            },
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def payment_prepare_view(request):
    data = request_data(request)
    settle_case = str(data.get("od_settle_case") or data.get("payment_method") or "bank").strip()
    requested_pg = str(data.get("pg_service") or data.get("od_pg") or "").strip().lower()
    toss_config = toss_payment_config()
    if settle_case_is_vbank(settle_case):
        pg_service = requested_pg or configured_payment_provider()
        if pg_service != "toss" or not toss_config["vbank_enabled"]:
            return api_error(
                "Toss virtual account payments are not enabled.",
                status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
                code="toss_vbank_unconfigured",
            )
    elif settle_case_is_bank(settle_case):
        pg_service = requested_pg or "bank"
        if pg_service not in {"bank", "manual_bank"}:
            return api_error(
                "The selected payment method does not match the order.",
                status=drf_status.HTTP_400_BAD_REQUEST,
                code="payment_method_mismatch",
            )
    else:
        pg_service = requested_pg or configured_payment_provider()
        if pg_service == "toss" and not toss_config["enabled"]:
            return api_error(
                "Toss Payments is not configured.",
                status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
                code="toss_payment_unconfigured",
            )
        if pg_service in PAYMENT_ADAPTER_PROVIDERS and not payment_adapter_enabled(pg_service):
            return api_error(
                "The selected payment provider is not configured.",
                status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
                code="payment_adapter_unconfigured",
            )
        if pg_service not in PAYMENT_ADAPTER_PROVIDERS and pg_service != "toss":
            return api_error(
                "The selected payment provider is not supported.",
                status=drf_status.HTTP_400_BAD_REQUEST,
                code="payment_provider_unsupported",
            )
    order_id = generate_numeric_order_id()
    try:
        order = create_order_from_request(request, data, order_id=order_id, force_status="order")
    except StockAdjustmentError as exc:
        return api_error(str(exc), status=drf_status.HTTP_400_BAD_REQUEST, code=exc.code, details=exc.details)
    amount = order.od_receipt_price
    return api_response(
        data={
            "order_id": order.od_id,
            "uid": order.uid,
            "order_name": str(data.get("order_name") or "Shop order"),
            "amount": amount,
            "buyer_name": order.od_name,
            "buyer_email": order.od_email or "noemail@example.com",
            "buyer_tel": order.od_hp or order.od_tel,
            "cash_receipt_request": bool(order.od_cash_request),
            "cash_receipt_type": order.od_cash_type,
            # The identifier is validated for this request and returned only to the checkout
            # browser for the PG call. It is deliberately not saved on ShopOrder.
            "cash_receipt_registration_number": (
                re.sub(r"\D+", "", str(data.get("cash_receipt_registration_number") or ""))
                if (
                    pg_service == "toss"
                    and order.od_cash_request
                    and not settle_case_is_bank(order.od_settle_case)
                )
                else ""
            ),
            "pg_service": pg_service,
            "pg_extra": {},
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def payment_cancel_view(request):
    data = request_data(request)
    order_id = str(data.get("order_id") or data.get("od_id") or "").strip()
    uid = str(data.get("uid") or "").strip()
    if not order_id:
        return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
    user = current_user(request)
    queryset = ShopOrder.objects.filter(pk=order_id)
    guest_uid_filter = Q(user__isnull=True, uid=uid) if uid else Q(pk__in=[])
    if user and user.is_authenticated:
        queryset = queryset.filter(Q(user=user) | guest_uid_filter)
    elif uid:
        queryset = queryset.filter(user__isnull=True, uid=uid)
    elif order_id not in set(request.session.get("g5_guest_order_ids", [])):
        queryset = queryset.none()
    else:
        queryset = queryset.filter(user__isnull=True)
    order = queryset.first()
    if not order:
        return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
    can_cancel, reason = order_cancel_state(order)
    if not can_cancel:
        return api_error(reason or "Order cannot be cancelled.", status=drf_status.HTTP_400_BAD_REQUEST, code="order_cancel_blocked")
    cancel_reason = str(data.get("reason") or "payment cancelled")
    toss_cancel_error = cancel_pending_toss_vbank(order, cancel_reason)
    if toss_cancel_error:
        return toss_cancel_error
    order, _, cancel_error = cancel_shop_order_locally(order.pk, cancel_reason)
    if cancel_error:
        return cancel_error
    restored_rows = restore_order_cart_snapshot(request, order)
    return api_response(data={"order_id": order.od_id, "uid": order.uid, "status": order.od_status, "restored_rows": restored_rows})


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def payment_confirm_view(request):
    data = request_data(request)
    order_id = payment_order_id(data)
    amount = payment_amount(data)
    transaction_id = payment_transaction_id(data)
    pg_service = str(data.get("pg_service") or data.get("od_pg") or "").strip().lower()
    order = ShopOrder.objects.filter(pk=order_id).first()
    if not order or not payment_confirm_access_allowed(request, order, data):
        return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
    authorized_order_id = str(order.od_id)
    payment_status = ""

    if pg_service != "toss" and pg_service not in PAYMENT_ADAPTER_PROVIDERS:
        record_payment_raw_log(
            order,
            order_id,
            "client-confirm",
            transaction_id,
            data,
            prefix="pay-reject",
        )
        return api_error(
            "This payment method requires a verified payment provider.",
            status=drf_status.HTTP_409_CONFLICT,
            code="payment_confirmation_provider_unsupported",
        )

    if pg_service == "toss":
        toss_payment, error = confirm_toss_payment(data)
        if error:
            return error
        payment_status = str(toss_payment.get("status") or "").upper()
        transaction_id = str(toss_payment.get("paymentKey") or transaction_id)
        data = {**data, "toss_payment": toss_payment}
        if payment_status == "WAITING_FOR_DEPOSIT":
            pending_order = ShopOrder.objects.filter(pk=authorized_order_id).first()
            if not pending_order:
                return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
            return api_response(data={
                "order_id": pending_order.od_id,
                "uid": pending_order.uid,
                "status": pending_order.od_status,
                "payment_status": payment_status,
                "vbank": {
                    "bank_code": pending_order.od_vbank_bank_code,
                    "account_number": pending_order.od_vbank_account,
                    "customer_name": pending_order.od_vbank_customer_name,
                    "due_date": pending_order.od_vbank_due_date,
                },
            })
    elif pg_service in PAYMENT_ADAPTER_PROVIDERS:
        order_id, amount, transaction_id, data, error = confirm_adapter_payment(pg_service, data)
        if error:
            return error
        if str(order_id) != authorized_order_id:
            order = ShopOrder.objects.filter(pk=order_id).first()
            if not order or not payment_confirm_access_allowed(request, order, data):
                return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
    order, error = confirm_order_payment(order_id, amount, pg_service, transaction_id, data)
    if error:
        return error
    return api_response(data={"order_id": order.od_id, "uid": order.uid, "status": order.od_status, "payment_status": payment_status})


@api_view(["POST"])
@permission_classes([AllowAny])
@parser_classes([JSONParser])
def toss_vbank_webhook_view(request):
    event = request_data(request)
    event_type = str(event.get("eventType") or "").strip().upper()
    event_data = event.get("data") if isinstance(event.get("data"), dict) else {}
    order_id = str(event_data.get("orderId") or "").strip()
    secret = str(event_data.get("secret") or "")
    if event_type != "DEPOSIT_CALLBACK" or not order_id or not secret:
        return api_error(
            "Invalid Toss virtual account callback.",
            status=drf_status.HTTP_400_BAD_REQUEST,
            code="toss_vbank_webhook_invalid",
        )

    order = ShopOrder.objects.filter(pk=order_id, od_pg="toss").first()
    if not order or not order.od_vbank_secret_hash:
        return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
    received_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(received_hash, order.od_vbank_secret_hash):
        record_payment_raw_log(order, order_id, "toss-vbank", event_data.get("transactionKey"), event, prefix="toss-vbank-reject")
        return api_error(
            "Invalid Toss virtual account callback secret.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="toss_vbank_webhook_forbidden",
        )

    toss_payment, error = toss_api_get_payment_by_order(order_id)
    if error:
        record_payment_raw_log(order, order_id, "toss-vbank", event_data.get("transactionKey"), event, prefix="toss-vbank-retry")
        return error
    raw_data = {"eventType": event_type, "data": event_data, "toss_payment": toss_payment}
    provider_order_id = str(toss_payment.get("orderId") or "") if isinstance(toss_payment, dict) else ""
    provider_amount = safe_amount_int(toss_payment.get("totalAmount"), -1) if isinstance(toss_payment, dict) else -1
    provider_payment_key = str(toss_payment.get("paymentKey") or "") if isinstance(toss_payment, dict) else ""
    if (
        provider_order_id != str(order.od_id)
        or provider_amount != order.od_receipt_price
        or not toss_method_is_vbank(toss_payment.get("method") if isinstance(toss_payment, dict) else "")
        or (order.od_tno and provider_payment_key != order.od_tno)
    ):
        record_payment_raw_log(order, order_id, "toss-vbank", provider_payment_key, raw_data, prefix="toss-vbank-mismatch")
        return api_response(data={"order_id": order.od_id, "processed": False, "manual_review": True})

    provider_status = str(toss_payment.get("status") or "").upper()
    if provider_status == "DONE":
        if str(order.od_status or "") in CANCELLED_STATUSES:
            record_payment_raw_log(order, order_id, "toss-vbank", provider_payment_key, raw_data, prefix="toss-vbank-late-paid")
            return api_response(data={"order_id": order.od_id, "processed": False, "manual_review": True})
        paid_order, error = confirm_order_payment(
            order_id, provider_amount, "toss", provider_payment_key, raw_data, log_prefix="toss-vbank"
        )
        if error:
            return error
        ShopOrder.objects.filter(pk=paid_order.pk).update(od_vbank_status=provider_status)
        return api_response(data={"order_id": paid_order.od_id, "status": paid_order.od_status, "processed": True})

    if provider_status == "WAITING_FOR_DEPOSIT":
        with transaction.atomic():
            locked = ShopOrder.objects.select_for_update().filter(pk=order_id).first()
            if not locked:
                return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
            if str(locked.od_status or "") in CANCELLED_STATUSES or str(locked.od_status or "") in {ORDER_STATUS_SHIPPING, "shipping"}:
                record_payment_raw_log(locked, order_id, "toss-vbank", provider_payment_key, raw_data, prefix="toss-vbank-review")
                return api_response(data={"order_id": locked.od_id, "processed": False, "manual_review": True})
            locked.od_vbank_status = provider_status
            fields = ["od_vbank_status"]
            if str(locked.od_status or "") in PAID_STATUSES:
                locked.od_status = ORDER_STATUS_ORDERED
                locked.od_misu = locked.od_receipt_price
                locked.od_receipt_time = ""
                locked.items.exclude(ct_status__in=CANCELLED_STATUSES).update(**item_status_update(ORDER_STATUS_ORDERED))
                take_back_order_points(locked)
                fields.extend(["od_status", "od_misu", "od_receipt_time"])
            locked.save(update_fields=fields)
            record_payment_raw_log(locked, order_id, "toss-vbank", provider_payment_key, raw_data, prefix="toss-vbank")
        return api_response(data={"order_id": order_id, "status": ORDER_STATUS_ORDERED, "processed": True})

    if provider_status in {"CANCELED", "EXPIRED"}:
        with transaction.atomic():
            locked = ShopOrder.objects.select_for_update().filter(pk=order_id).first()
            if not locked:
                return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND, code="order_not_found")
            if str(locked.od_status or "") in PAID_STATUSES:
                record_payment_raw_log(locked, order_id, "toss-vbank", provider_payment_key, raw_data, prefix="toss-vbank-review")
                return api_response(data={"order_id": locked.od_id, "processed": False, "manual_review": True})
            if str(locked.od_status or "") not in CANCELLED_STATUSES:
                restore_order_coupons_and_points(locked)
                locked, _ = cancel_order_with_stock_restore(locked, f"Toss virtual account {provider_status.lower()}")
            ShopOrder.objects.filter(pk=locked.pk).update(od_vbank_status=provider_status)
            record_payment_raw_log(locked, order_id, "toss-vbank", provider_payment_key, raw_data, prefix="toss-vbank")
        return api_response(data={"order_id": order_id, "status": ORDER_STATUS_CANCELLED, "processed": True})

    record_payment_raw_log(order, order_id, "toss-vbank", provider_payment_key, raw_data, prefix="toss-vbank-ignored")
    return api_response(data={"order_id": order_id, "processed": False, "provider_status": provider_status})


@api_view(["POST"])
@permission_classes([AllowAny])
@parser_classes([FormParser, JSONParser])
def payment_callback_view(request, provider):
    data = request_values(request)
    configured_secret = str(getattr(settings, "SHOP_PAYMENT_CALLBACK_SECRET", "") or "").strip()
    if not configured_secret:
        return api_error(
            "Payment callback secret is not configured.",
            status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
            code="payment_callback_unconfigured",
        )
    if not hmac.compare_digest(payment_callback_secret(request, data).encode(), str(configured_secret).encode()):
        record_payment_raw_log(
            None,
            payment_order_id(data),
            f"callback:{provider}",
            payment_transaction_id(data),
            data,
            prefix="cb-reject",
        )
        return api_error("Invalid payment callback secret.", status=drf_status.HTTP_403_FORBIDDEN, code="payment_callback_forbidden")
    signature_error = payment_callback_signature_error(request, provider, data)
    if signature_error:
        record_payment_raw_log(
            None,
            payment_order_id(data),
            f"callback:{provider}",
            payment_transaction_id(data),
            data,
            prefix="cb-reject",
        )
        return signature_error
    if not payment_callback_success(data):
        record_payment_raw_log(
            None,
            payment_order_id(data),
            f"callback:{provider}",
            payment_transaction_id(data),
            data,
            prefix="cb-fail",
        )
        return api_error(
            "Payment callback did not report success.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="payment_callback_not_success",
        )

    order, error = confirm_order_payment(
        payment_order_id(data),
        payment_amount(data),
        f"callback:{provider}",
        payment_transaction_id(data),
        data,
        log_prefix="cb",
    )
    if error:
        return error
    return api_response(data={"order_id": order.od_id, "uid": order.uid, "status": order.od_status})


@api_view(["GET"])
@permission_classes([AllowAny])
def naverpay_config_view(request):
    return api_response(
        data={
            "enabled": False,
            "reason": "Naver Pay is not configured.",
            "test": False,
            "mobile": False,
            "shop_id": "",
            "button_key": "",
            "button_count_item": 0,
            "button_count_cart": 0,
            "script_url": "",
            "order_url": "",
            "wish_url": "",
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def naverpay_order_view(request):
    return api_response(data={"order_id": "", "shop_id": "", "total_price": 0, "redirect_url": ""})


@api_view(["POST"])
@permission_classes([AllowAny])
def naverpay_wish_view(request):
    data = request_data(request)
    item_ids = data.get("it_ids") if isinstance(data.get("it_ids"), list) else [data.get("it_id")] if data.get("it_id") else []
    return api_response(data={"shop_id": "", "item_ids": item_ids, "redirect_url": ""})


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def coupons_view(request):
    user = current_user(request)
    if not user:
        return api_response(data=[], meta=pagination_meta(0, 1, safe_int(request.query_params.get("per_page"), 20)))
    queryset = valid_coupons_queryset(user) if bool_int(request.query_params.get("usable")) == 1 else member_coupons_queryset(user)
    method = request.query_params.get("method")
    if method not in (None, ""):
        queryset = queryset.filter(cp_method=safe_int(method, 2))
    page, meta = paginate_queryset(request, queryset, default_per_page=20)
    return api_response(data=[coupon_payload(coupon) for coupon in page], meta=meta)


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def coupon_zone_view(request):
    user = current_user(request)
    today = timezone.localdate()
    queryset = ShopCouponZone.objects.filter(cz_start__lte=today).filter(Q(cz_end__isnull=True) | Q(cz_end__gte=today))
    return api_response(data=[coupon_zone_payload(zone, user=user) for zone in queryset])


def issue_coupon_from_zone(zone, user):
    today = timezone.localdate()
    # YoungCart: a coupon of an N-day zone is valid from today through the N-th day
    end_date = coupon_end_date(today, zone.cz_period)
    # one coupon per member and zone, used or not (is_coupon_downloaded)
    coupon = ShopCoupon.objects.filter(user=user, coupon_zone=zone).first()
    created = False
    if coupon is None:
        coupon = ShopCoupon.objects.create(
            user=user,
            coupon_zone=zone,
            cp_subject=zone.cz_subject,
            cp_method=zone.cp_method,
            cp_target=zone.cp_target,
            cp_type=zone.cp_type,
            cp_price=zone.cp_price,
            cp_minimum=zone.cp_minimum,
            cp_maximum=zone.cp_maximum,
            cp_trunc=zone.cp_trunc,
            cp_start=today,
            cp_end=end_date,
        )
        created = True
        zone.cz_download += 1
        zone.save(update_fields=["cz_download"])
    return coupon, created


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def coupon_download_view(request):
    user, error = require_user(request)
    if error:
        return error
    data = request_data(request)
    zone = ShopCouponZone.objects.filter(pk=safe_int(data.get("cz_id") or data.get("cp_id"), 0)).first()
    if not zone:
        return api_error("Coupon zone not found.", status=drf_status.HTTP_404_NOT_FOUND, code="coupon_zone_not_found")
    today = timezone.localdate()
    if zone.cz_start > today or (zone.cz_end and zone.cz_end < today):
        return api_error("다운로드할 수 없는 쿠폰입니다.", status=drf_status.HTTP_400_BAD_REQUEST, code="coupon_zone_closed")
    # YoungCart ajax.coupondownload.php: only point-type zones (cz_type 1) cost points
    point_cost = zone.cz_point if int(zone.cz_type or 0) == 1 else 0
    with transaction.atomic():
        # one member's downloads run one at a time, so a double click cannot issue or charge twice
        Profile.objects.get_or_create(user=user)
        balance = Profile.objects.select_for_update().get(user=user).user_point
        if ShopCoupon.objects.filter(user=user, coupon_zone=zone).exists():
            return api_error("이미 다운로드하신 쿠폰입니다.", status=drf_status.HTTP_400_BAD_REQUEST, code="already_downloaded")
        if point_cost > 0 and balance < point_cost:
            return api_error(
                "보유하신 포인트가 부족하여 쿠폰을 다운로드할 수 없습니다.",
                status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="not_enough_points",
            )
        coupon, created = issue_coupon_from_zone(zone, user)
        if point_cost > 0:
            point_ledger.insert_point(user, -point_cost, f"쿠폰 {coupon.pk} 발급", "@coupon_zone", zone.pk, "download")
    return api_response(
        data={**coupon_payload(coupon), "cz_id": zone.pk, "downloaded": True, "created": created},
        status=drf_status.HTTP_201_CREATED,
    )


def same_product_cart_lines(items, target):
    """The cart lines of ``target``'s product in the same cart (regular or direct purchase)."""
    return [
        item
        for item in items
        if str(item.get("it_id")) == str(target.get("it_id"))
        and bool_int(item.get("ct_direct")) == bool_int(target.get("ct_direct"))
    ]


def product_coupon_base(items, target):
    """What a product coupon on ``target``'s line is judged on: the total of all its product's
    lines (YoungCart orderitemcoupon.php)."""
    lines = [cart_item_payload(item) for item in same_product_cart_lines(items, target)]
    return product_line_totals(lines).get(str(target.get("it_id")), 0)


def coupon_list_amount(request, item):
    """The amount a coupon list shows discounts on: the product total for an item coupon, else the
    cart after its product coupons (YoungCart ordercoupon.php: org_od_price - item_coupon)."""
    if item is not None:
        return product_coupon_base(cart_items(request), item)
    cart = cart_payload(request)
    return max(0, cart["total_price"] - cart["cart_coupon"])


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def coupon_applicable_view(request):
    user, error = require_user(request)
    if error:
        return error
    ct_id = str(request.query_params.get("ct_id") or "")
    item = next((entry for entry in cart_items(request) if str(entry.get("ct_id")) == ct_id), None)
    amount = coupon_list_amount(request, item)
    queryset = valid_coupons_queryset(user)
    if item is not None:
        # the item coupon picker offers product and category coupons only (orderitemcoupon.php)
        queryset = queryset.filter(cp_method__in=(0, 1))
    coupons = [coupon for coupon in queryset if item is None or coupon_matches_cart_item(coupon, item)]
    return api_response(data=[coupon_payload(coupon, amount=amount) for coupon in coupons])


def coupon_legacy_view(request, kind):
    user, error = require_user(request)
    if error:
        return error
    values = request_values(request)
    ct_id = str(first_value(values, "ct_id", "ct_id[]"))
    item = next((entry for entry in cart_items(request) if str(entry.get("ct_id")) == ct_id), None)
    amount = coupon_list_amount(request, item)
    coupons = valid_coupons_queryset(user)
    if kind == "legacy-item" and item:
        coupons = [coupon for coupon in coupons if coupon_matches_cart_item(coupon, item)]
    return api_response(data={"coupons": [coupon_payload(coupon, amount=amount) for coupon in coupons]})


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def coupon_legacy_order_view(request):
    return coupon_legacy_view(request, "legacy-order")


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def coupon_legacy_item_view(request):
    return coupon_legacy_view(request, "legacy-item")


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def coupon_apply_cart_view(request):
    user, error = require_user(request)
    if error:
        return error
    data = request_data(request)
    ct_id = str(data.get("ct_id") or "")
    cp_id = str(data.get("cp_id") or "")
    items = cart_items(request)
    target = next((item for item in items if str(item.get("ct_id")) == ct_id), None)
    if target is None:
        return api_error("Cart item not found.", status=drf_status.HTTP_404_NOT_FOUND, code="cart_item_not_found")
    coupon = None
    discount = 0
    if cp_id:
        coupon = valid_coupons_queryset(user).filter(pk=cp_id).first()
        if not coupon:
            return api_error("Coupon not found.", status=drf_status.HTTP_404_NOT_FOUND, code="coupon_not_found")
        # only product and category coupons belong on a cart line (orderitemcoupon.php)
        if coupon.cp_method not in (0, 1) or not coupon_matches_cart_item(coupon, target):
            return api_error("Coupon is not applicable to this cart item.", status=drf_status.HTTP_400_BAD_REQUEST, code="coupon_not_applicable")
        # YoungCart judges a product coupon on the product's total over all its lines
        base = product_coupon_base(items, target)
        if base < coupon.cp_minimum:
            return api_error("쿠폰 사용 최소 상품금액에 미달하여 쿠폰을 적용할 수 없습니다.", status=drf_status.HTTP_400_BAD_REQUEST, code="coupon_minimum_not_met")
        if coupon_exceeds_base(coupon, base):
            # orderform.sub.php refuses it rather than shrink it to the product total
            return api_error("쿠폰할인금액이 상품 주문금액보다 크므로 쿠폰을 적용할 수 없습니다.", status=drf_status.HTTP_400_BAD_REQUEST, code="coupon_exceeds_item_price")
        discount = coupon_raw_discount(coupon, base)
    product_lines = {id(item) for item in same_product_cart_lines(items, target)}

    def updated(item):
        if item is target:
            return {**item, "cp_id": coupon.cp_id if coupon else "", "cp_price": discount}
        # one coupon per product, and a coupon moved here leaves the line that had it
        if id(item) in product_lines or (coupon and str(item.get("cp_id") or "") == coupon.cp_id):
            return {**item, "cp_id": "", "cp_price": 0}
        return item

    save_cart_items(request, [updated(item) for item in items])
    payload = cart_payload(request, ct_id)
    payload["discount"] = discount
    payload["ct_id"] = ct_id
    return api_response(data=payload)


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def point_summary_view(request):
    user = current_user(request)
    balance = 0
    if user:
        profile, _ = Profile.objects.get_or_create(user=user)
        balance = profile.user_point
    return api_response(data={"balance": balance, "usable": balance})


@api_view(["GET"])
@permission_classes([AllowAny])
def events_view(request, ev_id=None):
    smoke_event = read_smoke_config("event", None)
    if ev_id is not None:
        event = ShopEvent.objects.filter(pk=safe_int(ev_id, 0), ev_use=True).first()
        if event:
            products = annotate_product_coupon_badge(
                on_sale_products().filter(
                    shop_events=event,
                ).select_related("category")
            ).annotate(
                review_count=Count("reviews", distinct=True),
                qa_count=Count("qas", distinct=True),
                review_stats=Avg("reviews__is_score"),
            )
            sort = (request.query_params.get("sort") or "").strip().lower()
            sortodr = (request.query_params.get("sortodr") or "").strip().lower()
            products = products.order_by(*shop_product_ordering(sort, sortodr))

            return api_response(
                data={
                    "ev_id": event.ev_id,
                    "ev_subject": event.ev_subject,
                    "ev_subject_strong": int(event.ev_subject_strong),
                    "ev_head_html": event.ev_head_html,
                    "ev_tail_html": event.ev_tail_html,
                    "ev_head_image_url": shop_event_image_url(event, "h", request),
                    "ev_tail_image_url": shop_event_image_url(event, "t", request),
                    "products": [product_payload(product) for product in products],
                }
            )

        if not smoke_event or str(smoke_event.get("event_id")) != str(ev_id):
            return api_error("Event not found.", status=drf_status.HTTP_404_NOT_FOUND, code="event_not_found")
        product = annotate_product_coupon_badge(
            ShopProduct.objects.filter(pk=str(smoke_event.get("product_id") or ""))
        ).first()
        return api_response(
            data={
                "ev_id": smoke_event.get("event_id"),
                "ev_subject": smoke_event.get("ev_subject", ""),
                "ev_subject_strong": int(bool(smoke_event.get("ev_subject_strong"))),
                "ev_head_html": smoke_event.get("ev_head_html", ""),
                "ev_tail_html": smoke_event.get("ev_tail_html", ""),
                "ev_head_image_url": smoke_event.get("ev_head_image_url", ""),
                "ev_tail_image_url": smoke_event.get("ev_tail_image_url", ""),
                "products": [product_payload(product)] if product else [],
            }
        )

    events = ShopEvent.objects.filter(ev_use=True).annotate(
        item_count=Count("items__product", filter=Q(items__product__it_use="1"), distinct=True)
    ).order_by("-ev_id")
    rows = [
        {
            "ev_id": event.ev_id,
            "ev_subject": event.ev_subject,
            "ev_subject_strong": int(event.ev_subject_strong),
            "item_count": event.item_count,
        }
        for event in events[:50]
    ]
    if not rows and smoke_event:
        product_count = on_sale_products().filter(
            pk=str(smoke_event.get("product_id") or ""),
        ).count()
        rows.append(
            {
                "ev_id": smoke_event.get("event_id"),
                "ev_subject": smoke_event.get("ev_subject", ""),
                "ev_subject_strong": int(bool(smoke_event.get("ev_subject_strong"))),
                "item_count": product_count,
            }
        )
    return api_response(data=rows, meta=pagination_meta(len(rows), 1, 50))


@api_view(["POST"])
@permission_classes([ShopStaffPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([MultiPartParser, FormParser])
def upload_product_image(request, it_id):
    product = ShopProduct.objects.filter(pk=it_id).first()
    if not product:
        return api_error("Product not found.", status=drf_status.HTTP_404_NOT_FOUND, code="product_not_found")
    files = [uploaded_file for _, uploaded_files in request.FILES.lists() for uploaded_file in uploaded_files]
    if not files:
        return api_error("Image file is required.", status=drf_status.HTTP_400_BAD_REQUEST, code="image_required")
    try:
        _, urls = upload_product_images(it_id, files)
    except ValidationError as exc:
        return api_error(
            "; ".join(str(item) for item in exc.messages),
            status=drf_status.HTTP_400_BAD_REQUEST,
            code="invalid_image_upload",
        )
    return api_response(data=urls, status=drf_status.HTTP_201_CREATED)


# a guest order is opened with its number and password, so guessing is limited per address
order_lookup_view.cls.throttle_scope = "order-lookup"
