"""Shared request helpers of the community API."""


from django.contrib.auth import get_user_model
from rest_framework import status as drf_status

from gnu_jango.shop.models import ShopProduct

from .response import api_error
from .v1_auth import _auth_user_from_request
from .v1_board import _pagination_meta


User = get_user_model()


GENERAL_QA_PRODUCT_ID = "__general_qa__"


QA_META_CONFIG_PREFIX = "qa_meta_"


def _request_data(request):
    return request.data if isinstance(request.data, dict) else {}


def _text(value):
    """A request field as text; a number, list, object or null sent instead counts as missing."""
    return value if isinstance(value, str) else ""


def _safe_int(value, default=0):
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if -(1 << 63) <= result <= (1 << 63) - 1 else default


def _require_user(request):
    user = _auth_user_from_request(request)
    if not user:
        return None, api_error(
            "Authentication credentials were not provided.",
            status=drf_status.HTTP_401_UNAUTHORIZED,
            code="not_authenticated",
        )
    return user, None


def _paginate(request, queryset, default_per_page=20, max_per_page=100):
    page = max(_safe_int(request.query_params.get("page"), 1), 1)
    per_page = request.query_params.get("per_page", request.query_params.get("limit", default_per_page))
    per_page = min(max(_safe_int(per_page, default_per_page), 1), max_per_page)
    total = queryset.count()
    start = (page - 1) * per_page
    # A page past the end is empty; slicing with it could overflow the database integer range.
    rows = queryset[start : start + per_page] if start < total else queryset.none()
    return rows, _pagination_meta(total, page, per_page)


def _general_qa_product():
    product, _ = ShopProduct.objects.get_or_create(
        it_id=GENERAL_QA_PRODUCT_ID,
        defaults={
            "it_name": "General Q&A",
            "it_use": "",
            "it_stock_qty": 0,
        },
    )
    return product


def _filter_qa_queryset(request, queryset):
    status_value = request.query_params.get("status")
    if status_value in {"0", 0}:
        queryset = queryset.filter(iq_answer="")
    elif status_value in {"1", 1}:
        queryset = queryset.exclude(iq_answer="")

    keyword = (request.query_params.get("stx") or request.query_params.get("q") or "").strip()
    if keyword:
        field = request.query_params.get("sfl") or "qa_subject"
        if field == "qa_content":
            queryset = queryset.filter(iq_question__icontains=keyword)
        elif field == "qa_name":
            queryset = queryset.filter(iq_name__icontains=keyword)
        elif field == "mb_id":
            queryset = queryset.filter(mb_id__icontains=keyword)
        else:
            queryset = queryset.filter(iq_subject__icontains=keyword)
    return queryset


def _member_display_name(user):
    if not user:
        return ""
    profile = getattr(user, "profile", None)
    return (
        getattr(profile, "nickname", "")
        or getattr(profile, "realname", "")
        or user.get_full_name()
        or user.get_username()
    )
