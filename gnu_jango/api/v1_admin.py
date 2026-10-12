import uuid

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Count, Sum, Q
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone
from django.utils.dateparse import parse_date
from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import BasePermission
from .authentication import SessionJWTAuthentication as JWTAuthentication

from gnu_jango.bbs.models import Board, Group, Post
from gnu_jango.config.models import Config
from gnu_jango.shop.models import (
    ShopCategory,
    ShopCoupon,
    ShopCouponLog,
    ShopOrder,
    ShopOrderData,
    ShopPersonalPay,
    ShopProduct,
    ShopQA,
)
from gnu_jango.shop.images import upload_product_images
from gnu_jango.users.models import Profile

from .member_lifecycle import leave_member
from .response import api_error, api_response
from .auth_sessions import revoke_member_tokens
from .v1_auth import _auth_user_from_request
from .v1_board import _board_payload
from .v1_shop import (
    cancel_order_and_refund_benefits,
    CANCELLED_STATUSES,
    category_item_count,
    category_member_q,
    category_payload,
    order_payload,
    paginate_queryset,
    product_payload,
    safe_int,
)

User = get_user_model()


class AdminOnlyPermission(BasePermission):
    message = "Admin permission is required."

    def has_permission(self, request, view):
        user = _auth_user_from_request(request)
        if user and (user.is_staff or user.is_superuser):
            request.gnu_jango_admin_user = user
            return True
        return False


def request_data(request):
    if isinstance(request.data, dict):
        return request.data
    return {}


def datetime_value(value):
    if not value:
        return ""
    try:
        return timezone.localtime(value).isoformat()
    except ValueError:
        return value.isoformat()


def require_admin(request):
    user = getattr(request, "gnu_jango_admin_user", None) or _auth_user_from_request(request)
    if user and (user.is_staff or user.is_superuser):
        return user, None
    return None, api_error("Admin permission is required.", status=drf_status.HTTP_403_FORBIDDEN, code="admin_required")


def profile_for(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile


def leave_date_value(user, profile):
    """g5_member.mb_leave_date (Ymd). Members deactivated before the leave date was stored show today."""
    if profile.leave_date:
        return profile.leave_date.strftime("%Y%m%d")
    return "" if user.is_active else datetime_value(timezone.now())


def member_payload(user):
    profile = profile_for(user)
    return {
        "mb_no": user.pk,
        "mb_id": user.username,
        "mb_name": profile.realname or user.get_full_name() or user.first_name or user.username,
        "mb_nick": profile.nickname or user.username,
        "mb_email": user.email,
        "mb_hp": profile.user_hp or "",
        "mb_tel": profile.user_hp or "",
        "mb_level": profile.user_level,
        "mb_point": profile.user_point,
        "mb_certify": "",
        "mb_adult": 0,
        "mb_mailling": 0,
        "mb_sms": 0,
        "mb_open": 1 if profile.open_profile else 0,
        "mb_open_date": datetime_value(profile.open_profile_date),
        "mb_today_login": datetime_value(timezone.now()),
        "mb_datetime": datetime_value(user.date_joined),
        "mb_leave_date": leave_date_value(user, profile),
        "mb_intercept_date": "" if user.is_active or profile.leave_date else datetime_value(timezone.now()),
        "mb_email_certify": datetime_value(profile.email_certify),
        "mb_icon_path": profile.icon.url if profile.icon else "",
        "mb_homepage": profile.user_homepage or "",
        "mb_signature": "",
        "mb_profile": "",
        "mb_memo": "",
        "is_staff": user.is_staff,
        "is_superuser": user.is_superuser,
    }


def deactivate_member(mb_id):
    user = User.objects.filter(username=mb_id).first()
    if not user:
        return None, api_error("Member not found.", status=drf_status.HTTP_404_NOT_FOUND)
    user.is_active = False
    user.save(update_fields=["is_active"])
    # mb_intercept_date: the member is signed out everywhere, and lifting the block later does not
    # bring the tokens issued before it back.
    revoke_member_tokens(user)
    return user, None


def default_group():
    group, _ = Group.objects.get_or_create(gr_id="community", defaults={"gr_subject": "Community"})
    return group


def config_map():
    rows = Config.objects.all()
    data = {row.name: row.value for row in rows}
    data.setdefault("cf_title", "GNU Jango")
    data.setdefault("cf_admin_email", "")
    data.setdefault("cf_admin", "")
    data.setdefault("cf_theme", "nextjs_default")
    return data


def save_config_map(data):
    writable = {
        "cf_title",
        "cf_admin_email",
        "cf_admin",
        "cf_theme",
        "cf_use_point",
        "cf_login_point",
        "cf_register_level",
    }
    for key, value in data.items():
        if key in writable:
            Config.objects.update_or_create(name=key, defaults={"value": str(value or "")})


def qa_payload(item):
    return {
        "qa_id": item.pk,
        "qa_subject": item.iq_subject,
        "qa_content": item.iq_question,
        "qa_answer": item.iq_answer,
        "qa_name": item.iq_name,
        "mb_id": item.mb_id,
        "qa_datetime": datetime_value(item.iq_time),
        "qa_status": "answered" if item.iq_answer else "pending",
        "it_id": item.product_id,
        "it_name": item.product.it_name if item.product_id else "",
    }


@api_view(["GET"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def dashboard_stats_view(request):
    _, error = require_admin(request)
    if error:
        return error
    today = timezone.localdate()
    return api_response(
        data={
            "total_members": User.objects.count(),
            "today_members": User.objects.filter(date_joined__date=today).count(),
            "total_posts": Post.objects.count(),
            "today_orders": ShopOrder.objects.filter(od_datetime__date=today).count(),
        }
    )


@api_view(["GET"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def recent_orders_view(request):
    _, error = require_admin(request)
    if error:
        return error
    limit = min(max(safe_int(request.query_params.get("limit"), 5), 1), 20)
    orders = ShopOrder.objects.order_by("-od_datetime")[:limit]
    return api_response(
        data=[
            {
                "od_id": order.od_id,
                "od_name": order.od_name,
                "od_receipt_price": order.od_receipt_price,
                "od_status": order.od_status,
                "od_datetime": datetime_value(order.od_datetime),
            }
            for order in orders
        ]
    )


@api_view(["GET"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def recent_members_view(request):
    _, error = require_admin(request)
    if error:
        return error
    limit = min(max(safe_int(request.query_params.get("limit"), 5), 1), 20)
    users = User.objects.order_by("-date_joined")[:limit]
    return api_response(
        data=[
            {
                "mb_id": user.username,
                "mb_nick": profile_for(user).nickname or user.username,
                "mb_email": user.email,
                "mb_datetime": datetime_value(user.date_joined),
            }
            for user in users
        ]
    )


def order_raw_log_payload(log):
    preview = log.dt_data or ""
    return {
        "log_id": log.log_id,
        "od_id": log.od_id,
        "cart_id": log.cart_id,
        "mb_id": log.mb_id,
        "dt_pg": log.dt_pg,
        "dt_time": datetime_value(log.dt_time),
        "dt_data_preview": preview[:500],
        "dt_data_length": len(preview),
    }


def coupon_log_payload(log):
    return {
        "cl_id": log.cl_id,
        "cp_id": log.cp_id,
        "mb_id": log.mb_id,
        "od_id": log.od_id,
        "cp_price": log.cp_price,
        "cl_datetime": datetime_value(log.cl_datetime),
    }


def money_sum(queryset, field):
    return queryset.aggregate(value=Sum(field))["value"] or 0


def report_date_range(request):
    start = parse_date(str(request.query_params.get("date_from") or request.query_params.get("start") or ""))
    end = parse_date(str(request.query_params.get("date_to") or request.query_params.get("end") or ""))
    return start, end


def filter_datetime_range(queryset, field, start, end):
    if start:
        queryset = queryset.filter(**{f"{field}__date__gte": start})
    if end:
        queryset = queryset.filter(**{f"{field}__date__lte": end})
    return queryset


def group_counts(queryset, field):
    return [
        {"key": row[field] or "", "count": row["count"]}
        for row in queryset.values(field).annotate(count=Count("pk")).order_by("-count", field)
    ]


def grouped_money(queryset, group_field, money_field):
    return [
        {"key": row[group_field] or "", "count": row["count"], "amount": row["amount"] or 0}
        for row in queryset.values(group_field).annotate(count=Count("pk"), amount=Sum(money_field)).order_by("-amount", group_field)
    ]


def sales_series(queryset, period):
    trunc = TruncMonth("od_datetime") if period == "month" else TruncDate("od_datetime")
    rows = (
        queryset.annotate(period_value=trunc)
        .values("period_value")
        .annotate(
            order_count=Count("pk"),
            receipt_price=Sum("od_receipt_price"),
            cart_price=Sum("od_cart_price"),
            cancel_price=Sum("od_cancel_price"),
            coupon_price=Sum("od_coupon"),
            tax_base=Sum("od_tax_mny"),
            vat_amount=Sum("od_vat_mny"),
            exempt_amount=Sum("od_free_mny"),
        )
        .order_by("period_value")
    )
    return [
        {
            "period": row["period_value"].isoformat() if row["period_value"] else "",
            "order_count": row["order_count"],
            "receipt_price": row["receipt_price"] or 0,
            "cart_price": row["cart_price"] or 0,
            "cancel_price": row["cancel_price"] or 0,
            "coupon_price": row["coupon_price"] or 0,
            "tax_base": row["tax_base"] or 0,
            "vat_amount": row["vat_amount"] or 0,
            "exempt_amount": row["exempt_amount"] or 0,
        }
        for row in rows
    ]


@api_view(["GET"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def shop_report_summary_view(request):
    _, error = require_admin(request)
    if error:
        return error
    start, end = report_date_range(request)
    orders = filter_datetime_range(ShopOrder.objects.all(), "od_datetime", start, end)
    coupon_logs = filter_datetime_range(ShopCouponLog.objects.all(), "cl_datetime", start, end)
    raw_logs = filter_datetime_range(ShopOrderData.objects.all(), "dt_time", start, end)
    return api_response(
        data={
            "date_from": start.isoformat() if start else "",
            "date_to": end.isoformat() if end else "",
            "order_count": orders.count(),
            "order_item_count": ShopOrder.objects.filter(pk__in=orders.values("pk")).aggregate(count=Count("items"))["count"] or 0,
            "receipt_price": money_sum(orders, "od_receipt_price"),
            "cart_price": money_sum(orders, "od_cart_price"),
            "cancel_price": money_sum(orders, "od_cancel_price"),
            "tax_base": money_sum(orders, "od_tax_mny"),
            "vat_amount": money_sum(orders, "od_vat_mny"),
            "exempt_amount": money_sum(orders, "od_free_mny"),
            "misu_price": money_sum(orders, "od_misu"),
            "coupon_price": money_sum(orders, "od_coupon"),
            "send_coupon_price": money_sum(orders, "od_send_coupon"),
            "coupon_log_count": coupon_logs.count(),
            "coupon_log_price": money_sum(coupon_logs, "cp_price"),
            "raw_log_count": raw_logs.count(),
            "personalpay_count": filter_datetime_range(ShopPersonalPay.objects.all(), "pp_time", start, end).count(),
            "personalpay_price": money_sum(filter_datetime_range(ShopPersonalPay.objects.all(), "pp_time", start, end), "pp_price"),
            "personalpay_receipt_price": money_sum(filter_datetime_range(ShopPersonalPay.objects.all(), "pp_time", start, end), "pp_receipt_price"),
        }
    )


@api_view(["GET"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def shop_report_sales_view(request):
    _, error = require_admin(request)
    if error:
        return error
    start, end = report_date_range(request)
    period = request.query_params.get("period") if request.query_params.get("period") in {"day", "month"} else "day"
    orders = filter_datetime_range(ShopOrder.objects.all(), "od_datetime", start, end)
    return api_response(
        data={
            "date_from": start.isoformat() if start else "",
            "date_to": end.isoformat() if end else "",
            "period": period,
            "summary": {
                "order_count": orders.count(),
                "receipt_price": money_sum(orders, "od_receipt_price"),
                "cart_price": money_sum(orders, "od_cart_price"),
                "cancel_price": money_sum(orders, "od_cancel_price"),
                "tax_base": money_sum(orders, "od_tax_mny"),
                "vat_amount": money_sum(orders, "od_vat_mny"),
                "exempt_amount": money_sum(orders, "od_free_mny"),
                "misu_price": money_sum(orders, "od_misu"),
                "coupon_price": money_sum(orders, "od_coupon"),
                "send_cost": money_sum(orders, "od_send_cost"),
                "send_cost2": money_sum(orders, "od_send_cost2"),
            },
            "by_status": grouped_money(orders, "od_status", "od_receipt_price"),
            "by_settle_case": grouped_money(orders, "od_settle_case", "od_receipt_price"),
            "by_pg": grouped_money(orders, "od_pg", "od_receipt_price"),
            "series": sales_series(orders, period),
        }
    )


@api_view(["GET"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def shop_report_coupons_view(request):
    _, error = require_admin(request)
    if error:
        return error
    start, end = report_date_range(request)
    logs = filter_datetime_range(ShopCouponLog.objects.select_related("coupon", "order", "user"), "cl_datetime", start, end)
    issued = ShopCoupon.objects.all()
    if start:
        issued = issued.filter(created_at__date__gte=start)
    if end:
        issued = issued.filter(created_at__date__lte=end)
    top_coupons = [
        {
            "cp_id": row["cp_id"] or "",
            "count": row["count"],
            "discount": row["discount"] or 0,
        }
        for row in logs.values("cp_id").annotate(count=Count("cl_id"), discount=Sum("cp_price")).order_by("-discount", "cp_id")[:30]
    ]
    return api_response(
        data={
            "date_from": start.isoformat() if start else "",
            "date_to": end.isoformat() if end else "",
            "issued_count": issued.count(),
            "unused_count": issued.filter(cp_used="").count(),
            "used_log_count": logs.count(),
            "used_discount": money_sum(logs, "cp_price"),
            "by_member": [
                {"mb_id": row["mb_id"] or "", "count": row["count"], "discount": row["discount"] or 0}
                for row in logs.values("mb_id").annotate(count=Count("cl_id"), discount=Sum("cp_price")).order_by("-discount", "mb_id")[:30]
            ],
            "top_coupons": top_coupons,
        }
    )


@api_view(["GET", "POST"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def boards_view(request):
    _, error = require_admin(request)
    if error:
        return error
    if request.method == "GET":
        boards = Board.objects.select_related("group").all().order_by("bo_order", "bo_table")
        return api_response(data=[_board_payload(board) for board in boards])

    data = request_data(request)
    bo_table = str(data.get("bo_table") or "").strip()
    bo_subject = str(data.get("bo_subject") or "").strip()
    if not bo_table or not bo_subject:
        return api_error("Board id and subject are required.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY)
    board = Board.objects.create(group=default_group(), bo_table=bo_table, bo_subject=bo_subject)
    return api_response(data=_board_payload(board), status=drf_status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def board_detail_view(request, bo_table):
    _, error = require_admin(request)
    if error:
        return error
    board = Board.objects.filter(bo_table=bo_table).first()
    if not board:
        return api_error("Board not found.", status=drf_status.HTTP_404_NOT_FOUND, code="board_not_found")
    if request.method == "DELETE":
        board.delete()
        return api_response(data={"deleted": True, "bo_table": bo_table})
    if request.method == "PATCH":
        data = request_data(request)
        for field in (
            "bo_subject",
            "bo_mobile_subject",
            "bo_admin",
            "bo_category_list",
            "bo_skin",
            "bo_mobile_skin",
            "bo_content_head",
            "bo_content_tail",
        ):
            if field in data:
                setattr(board, field, str(data.get(field) or ""))
        for field in (
            "bo_list_level",
            "bo_read_level",
            "bo_write_level",
            "bo_comment_level",
            "bo_upload_level",
            "bo_download_level",
            "bo_page_rows",
            "bo_upload_size",
            "bo_upload_count",
            "bo_order",
        ):
            if field in data:
                setattr(board, field, safe_int(data.get(field), getattr(board, field)))
        for field in ("bo_use_category", "bo_use_dhtml_editor", "bo_use_good", "bo_use_nogood", "bo_use_search"):
            if field in data:
                setattr(board, field, bool(data.get(field)))
        board.save()
    return api_response(data=_board_payload(board))


@api_view(["GET"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def members_view(request):
    _, error = require_admin(request)
    if error:
        return error
    queryset = User.objects.all().order_by("-date_joined")
    stx = request.query_params.get("stx")
    sfl = request.query_params.get("sfl") or "mb_id"
    if stx:
        if sfl == "mb_email":
            queryset = queryset.filter(email__icontains=stx)
        elif sfl == "mb_name":
            queryset = queryset.filter(Q(first_name__icontains=stx) | Q(last_name__icontains=stx) | Q(profile__realname__icontains=stx))
        elif sfl == "mb_nick":
            queryset = queryset.filter(profile__nickname__icontains=stx)
        else:
            queryset = queryset.filter(username__icontains=stx)
    page, meta = paginate_queryset(request, queryset, default_per_page=20)
    return api_response(data=[member_payload(user) for user in page], meta=meta)


@api_view(["GET", "PATCH"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def member_detail_view(request, mb_id):
    _, error = require_admin(request)
    if error:
        return error
    user = User.objects.filter(username=mb_id).first()
    if not user:
        return api_error("Member not found.", status=drf_status.HTTP_404_NOT_FOUND, code="member_not_found")
    if request.method == "PATCH":
        data = request_data(request)
        profile = profile_for(user)
        previous_email = user.email
        if "mb_email" in data:
            user.email = str(data.get("mb_email") or "")
        if "mb_name" in data:
            profile.realname = str(data.get("mb_name") or "")
        if "mb_nick" in data:
            profile.nickname = str(data.get("mb_nick") or user.username)
        if "mb_level" in data:
            profile.user_level = safe_int(data.get("mb_level"), profile.user_level)
        if "mb_point" in data:
            profile.user_point = safe_int(data.get("mb_point"), profile.user_point)
        if "mb_hp" in data:
            profile.user_hp = str(data.get("mb_hp") or "")
        user.save()
        profile.save()
        if user.email != previous_email:
            # The address receives the password reset mail: the member signs in again.
            revoke_member_tokens(user)
    return api_response(data=member_payload(user))


@api_view(["PATCH"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def member_ban_view(request, mb_id):
    _, error = require_admin(request)
    if error:
        return error
    user, error = deactivate_member(mb_id)
    if error:
        return error
    return api_response(data=member_payload(user))


@api_view(["PATCH"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def member_leave_view(request, mb_id):
    _, error = require_admin(request)
    if error:
        return error
    user = User.objects.filter(username=mb_id).first()
    if not user:
        return api_error("Member not found.", status=drf_status.HTTP_404_NOT_FOUND)
    # adm/member_list_update.php: the admin's leave stamps mb_leave_date like g5_leave_member.
    if not leave_member(user):
        deactivate_member(mb_id)
    user.refresh_from_db()
    return api_response(data=member_payload(user))


@api_view(["GET", "PATCH"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def settings_view(request):
    _, error = require_admin(request)
    if error:
        return error
    if request.method == "PATCH":
        save_config_map(request_data(request))
    return api_response(data=config_map())


@api_view(["GET", "POST"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def shop_categories_view(request):
    _, error = require_admin(request)
    if error:
        return error
    if request.method == "GET":
        queryset = ShopCategory.objects.annotate(item_count=category_item_count()).order_by("ca_order", "ca_id")
        return api_response(data=[category_payload(category) for category in queryset])
    data = request_data(request)
    category = ShopCategory.objects.create(
        ca_id=str(data.get("ca_id") or uuid.uuid4().hex[:8]),
        ca_name=str(data.get("ca_name") or ""),
        ca_parent=str(data.get("ca_parent") or ""),
        ca_order=safe_int(data.get("ca_order"), 0),
        ca_skin=str(data.get("ca_skin") or ""),
    )
    return api_response(data=category_payload(category), status=drf_status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def shop_category_detail_view(request, ca_id):
    _, error = require_admin(request)
    if error:
        return error
    category = ShopCategory.objects.filter(pk=ca_id).first()
    if not category:
        return api_error("Category not found.", status=drf_status.HTTP_404_NOT_FOUND)
    if request.method == "GET":
        return api_response(data=category_payload(category))
    if request.method == "DELETE":
        category.delete()
        return api_response(data={"deleted": True, "ca_id": ca_id})
    data = request_data(request)
    for field in ("ca_name", "ca_parent", "ca_skin"):
        if field in data:
            setattr(category, field, str(data.get(field) or ""))
    if "ca_order" in data:
        category.ca_order = safe_int(data.get("ca_order"), category.ca_order)
    category.save()
    return api_response(data=category_payload(category))


@api_view(["PATCH"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def shop_category_order_view(request, ca_id):
    _, error = require_admin(request)
    if error:
        return error
    category = ShopCategory.objects.filter(pk=ca_id).first()
    if not category:
        return api_error("Category not found.", status=drf_status.HTTP_404_NOT_FOUND)
    direction = request_data(request).get("direction")
    category.ca_order += -1 if direction == "up" else 1
    category.save(update_fields=["ca_order"])
    return api_response(data=category_payload(category))


@api_view(["GET", "POST"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def shop_products_view(request):
    _, error = require_admin(request)
    if error:
        return error
    if request.method == "GET":
        queryset = ShopProduct.objects.select_related("category").all()
        q = request.query_params.get("q") or request.query_params.get("stx")
        ca_id = request.query_params.get("ca_id")
        if q:
            queryset = queryset.filter(Q(it_id__icontains=q) | Q(it_name__icontains=q))
        if ca_id:
            queryset = queryset.filter(category_member_q(ca_id))
        page, meta = paginate_queryset(request, queryset, default_per_page=20)
        return api_response(data=[product_payload(product) for product in page], meta=meta)
    data = request_data(request)
    product = upsert_product(None, data)
    return api_response(data=product_payload(product, detail=True), status=drf_status.HTTP_201_CREATED)


def upsert_product(product, data):
    it_id = str(data.get("it_id") or (product.it_id if product else uuid.uuid4().hex[:10]))
    category = ShopCategory.objects.filter(pk=str(data.get("ca_id") or "")).first()
    if product is None:
        product = ShopProduct(it_id=it_id)
    product.category = category
    # Secondary categories are only touched when the client sends them, so older
    # clients that only know ca_id cannot wipe values imported from Gnuboard5.
    # An empty value clears the slot; an unknown id (typo) keeps the stored value.
    for key, attr in (("ca_id2", "category2"), ("ca_id3", "category3")):
        if key not in data:
            continue
        requested = str(data.get(key) or "").strip()
        if not requested:
            setattr(product, attr, None)
            continue
        matched = ShopCategory.objects.filter(pk=requested).first()
        if matched:
            setattr(product, attr, matched)
    product.it_name = str(data.get("it_name") or product.it_name or it_id)
    for field in ("it_seo_title", "it_tel_inq", "it_soldout", "it_use", "it_stock_sms", "it_type1", "it_type2", "it_type3", "it_type4", "it_type5", "it_basic", "it_content", "it_explan", "it_head_html", "it_tail_html", "it_info_gubun", "it_info_title", "image_url"):
        if field in data:
            setattr(product, field, str(data.get(field) or ""))
    for field in ("it_price", "it_basic_price", "it_cust_price", "it_point", "it_point_type", "it_stock_qty", "it_buy_min_qty", "it_buy_max_qty", "it_sc_type", "it_sc_method", "it_sc_price", "it_sc_minimum", "it_sc_qty"):
        if field in data:
            setattr(product, field, safe_int(data.get(field), getattr(product, field)))
    if isinstance(data.get("images"), list):
        product.images = data.get("images")
    if isinstance(data.get("options"), list):
        product.options = data.get("options")
    product.save()
    return product


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def shop_product_detail_view(request, it_id):
    _, error = require_admin(request)
    if error:
        return error
    product = ShopProduct.objects.select_related("category").filter(pk=it_id).first()
    if not product:
        return api_error("Product not found.", status=drf_status.HTTP_404_NOT_FOUND)
    if request.method == "DELETE":
        product.delete()
        return api_response(data={"deleted": True, "it_id": it_id})
    if request.method == "PATCH":
        product = upsert_product(product, request_data(request))
    return api_response(data=product_payload(product, detail=True))


@api_view(["POST"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([MultiPartParser, FormParser])
def shop_product_images_view(request, it_id):
    _, error = require_admin(request)
    if error:
        return error
    if not ShopProduct.objects.filter(pk=it_id).exists():
        return api_error("Product not found.", status=drf_status.HTTP_404_NOT_FOUND)
    files = [uploaded_file for _, uploaded_files in request.FILES.lists() for uploaded_file in uploaded_files]
    if not files:
        return api_error("Image file is required.", status=drf_status.HTTP_400_BAD_REQUEST)
    try:
        _, urls = upload_product_images(it_id, files)
    except ValidationError as exc:
        return api_error(
            "; ".join(str(item) for item in exc.messages),
            status=drf_status.HTTP_400_BAD_REQUEST,
            code="invalid_image_upload",
        )
    return api_response(data=urls, status=drf_status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def shop_orders_view(request):
    _, error = require_admin(request)
    if error:
        return error
    queryset = ShopOrder.objects.all()
    status_filter = request.query_params.get("status")
    stx = request.query_params.get("stx")
    if status_filter:
        queryset = queryset.filter(od_status=status_filter)
    if stx:
        queryset = queryset.filter(Q(od_id__icontains=stx) | Q(od_name__icontains=stx))
    page, meta = paginate_queryset(request, queryset, default_per_page=20)
    return api_response(data=[order_payload(order) for order in page], meta=meta)


@api_view(["GET", "PATCH"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def shop_order_detail_view(request, od_id):
    _, error = require_admin(request)
    if error:
        return error
    order = ShopOrder.objects.filter(pk=od_id).first()
    if not order:
        return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND)
    if request.method == "PATCH":
        data = request_data(request)
        requested_status = str(data.get("od_status") or "")
        if requested_status in ("cancel", "cancelled"):
            reason = str(data.get("reason") or data.get("memo") or data.get("od_memo") or "cancelled by admin")
            order, _ = cancel_order_and_refund_benefits(order, reason)
        else:
            for field in ("od_status", "od_delivery_company", "od_invoice", "od_invoice_time", "od_memo"):
                if field in data:
                    setattr(order, field, str(data.get(field) or ""))
            aliases = {
                "delivery_company": "od_delivery_company",
                "tracking_number": "od_invoice",
                "invoice": "od_invoice",
                "invoice_time": "od_invoice_time",
                "memo": "od_memo",
            }
            for source, target in aliases.items():
                if source in data:
                    setattr(order, target, str(data.get(source) or ""))
            if order.od_invoice and not order.od_invoice_time:
                order.od_invoice_time = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            order.save()
            if requested_status:
                order.items.exclude(ct_status__in=CANCELLED_STATUSES).update(ct_status=order.od_status)
    data = order_payload(order, detail=True)
    raw_logs = ShopOrderData.objects.filter(order=order).order_by("-dt_time", "-log_id")
    coupon_logs = ShopCouponLog.objects.filter(order=order).order_by("-cl_datetime", "-cl_id")
    data["raw_log_count"] = raw_logs.count()
    data["coupon_log_count"] = coupon_logs.count()
    data["raw_logs"] = [order_raw_log_payload(log) for log in raw_logs[:10]]
    data["coupon_logs"] = [coupon_log_payload(log) for log in coupon_logs[:10]]
    return api_response(data=data)


@api_view(["PATCH"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def shop_order_cancel_view(request, od_id):
    _, error = require_admin(request)
    if error:
        return error
    order = ShopOrder.objects.filter(pk=od_id).first()
    if not order:
        return api_error("Order not found.", status=drf_status.HTTP_404_NOT_FOUND)
    order, _ = cancel_order_and_refund_benefits(order, str(request_data(request).get("reason") or "cancelled by admin"))
    return api_response(data=order_payload(order, detail=True))


@api_view(["GET"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def qas_view(request):
    _, error = require_admin(request)
    if error:
        return error
    queryset = ShopQA.objects.select_related("product", "user").all()
    page, meta = paginate_queryset(request, queryset, default_per_page=20)
    return api_response(data=[qa_payload(item) for item in page], meta=meta)


@api_view(["GET", "PATCH"])
@permission_classes([AdminOnlyPermission])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def qa_detail_view(request, qa_id):
    _, error = require_admin(request)
    if error:
        return error
    qa = ShopQA.objects.select_related("product", "user").filter(pk=qa_id).first()
    if not qa:
        return api_error("Q&A not found.", status=drf_status.HTTP_404_NOT_FOUND)
    if request.method == "PATCH":
        data = request_data(request)
        if "qa_answer" in data or "iq_answer" in data:
            qa.iq_answer = str(data.get("qa_answer") or data.get("iq_answer") or "")
            qa.save(update_fields=["iq_answer"])
    return api_response(data=qa_payload(qa))
