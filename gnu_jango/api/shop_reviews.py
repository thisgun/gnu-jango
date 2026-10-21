"""Product reviews and product Q&A of the shop API."""


from django.db.models import Avg, Q
from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import (
    api_view,
    authentication_classes,
    permission_classes,
)
from rest_framework.permissions import AllowAny
from .authentication import SessionJWTAuthentication as JWTAuthentication

from gnu_jango.shop.models import (
    ShopOrderItem,
    ShopProduct,
    ShopQA,
    ShopReview,
)

from gnu_jango.shop.product_counters import recount_product_reviews
from gnu_jango.shop.shipping import current_shipping_policy

from .response import api_error, api_response

from .community_common import GENERAL_QA_PRODUCT_ID
from .shop_common import (
    bool_int,
    current_user,
    datetime_value,
    member_display_name,
    pagination_meta,
    paginate_queryset,
    product_thumbnail_url,
    request_data,
    require_user,
    safe_int,
    strip_script_and_style_blocks,
)


def review_payload(review):
    product = review.product
    return {
        "is_id": str(review.pk),
        "it_id": product.it_id if product else "",
        "it_name": product.it_name if product else "Deleted product",
        "it_seo_title": product.it_seo_title if product else "",
        "ca_id": (product.category_id or "") if product else "",
        "it_price": product.it_price if product else 0,
        "mb_id": review.mb_id,
        "mb_nick": review.mb_nick,
        "is_name": review.is_name,
        "is_score": review.is_score,
        "is_subject": review.is_subject,
        "is_content": review.is_content,
        "is_confirm": review.is_confirm,
        "is_time": datetime_value(review.is_time),
        "product_image_url": product_thumbnail_url(product) if product else "/icon-192.png",
    }


HIDDEN_WRITER_NAME = "비공개"


def product_questions():
    """Product questions only. 1:1 inquiries are ShopQA rows on the "__general_qa__" pseudo product and are
    served by the 1:1 API (community_qas) alone — the product Q&A endpoints must never list or open them."""
    return ShopQA.objects.exclude(product_id=GENERAL_QA_PRODUCT_ID)

# itemuselist.php / itemqalist.php search fields (sfl) -> (model field, how the keyword matches).
# Names and member ids match exactly, item ids by prefix, the rest by substring — as the reference API.
REVIEW_SEARCH_FIELDS = {
    "i.it_name": ("product__it_name", "icontains"),
    "r.it_id": ("product__it_id", "startswith"),
    "r.is_subject": ("is_subject", "icontains"),
    "r.is_content": ("is_content", "icontains"),
    "r.is_name": ("is_name", "exact"),
    "r.mb_id": ("mb_id", "exact"),
}
QNA_SEARCH_FIELDS = {
    "i.it_name": ("product__it_name", "icontains"),
    "q.it_id": ("product__it_id", "startswith"),
    "q.iq_subject": ("iq_subject", "icontains"),
    "q.iq_question": ("iq_question", "icontains"),
    "q.iq_name": ("iq_name", "exact"),
    "q.mb_id": ("mb_id", "exact"),
}


def _search_board_list(queryset, request, fields, default_fields):
    """Filter a review/Q&A list by `q` (or `stx`) in the field `sfl` names, or in every default field."""
    keyword = (request.query_params.get("q") or request.query_params.get("stx") or "").strip()
    if not keyword:
        return queryset
    field = fields.get((request.query_params.get("sfl") or "").strip())
    if field:
        name, lookup = field
        return queryset.filter(**{f"{name}__{lookup}": keyword})
    condition = Q()
    for name in default_fields:
        condition |= Q(**{f"{name}__icontains": keyword})
    return queryset.filter(condition)


def qa_payload(qa, request=None):
    product = qa.product
    user = current_user(request) if request else None
    can_manage = bool(user and (user.is_staff or user.is_superuser or qa.user_id == user.id))
    can_view = qa.iq_secret == 0 or can_manage
    # A secret question the viewer cannot read does not say who asked it either (reference API: "비공개").
    return {
        "iq_id": str(qa.pk),
        "it_id": product.it_id if product else "",
        "it_name": product.it_name if product else "Deleted product",
        "it_seo_title": product.it_seo_title if product else "",
        "ca_id": (product.category_id or "") if product else "",
        "it_price": product.it_price if product else 0,
        "mb_id": qa.mb_id if can_view else "",
        "mb_nick": qa.mb_nick if can_view else HIDDEN_WRITER_NAME,
        "iq_name": qa.iq_name if can_view else HIDDEN_WRITER_NAME,
        "iq_subject": qa.iq_subject if can_view else "\ube44\ubc00\uae00\uc785\ub2c8\ub2e4.",
        "iq_question": qa.iq_question if can_view else "",
        "iq_answer": qa.iq_answer if can_view else "",
        "iq_secret": qa.iq_secret,
        "iq_email": qa.iq_email if can_manage else "",
        "iq_hp": qa.iq_hp if can_manage else "",
        "is_answered": bool(qa.iq_answer),
        "can_view": can_view,
        "can_edit": can_manage,
        "can_delete": can_manage,
        "iq_time": datetime_value(qa.iq_time),
        "product_image_url": product_thumbnail_url(product) if product else "",
    }


def _review_score(value):
    """1 to 5, or None for anything else (YoungCart offers only those choices)."""
    try:
        score = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return score if 1 <= score <= 5 else None


def _has_received_product(user, product):
    """YoungCart check_itemuse_write: with de_item_use_write on, only a member whose line of this
    product is 완료 (delivered) may review it; the super administrator is exempt."""
    if user.is_superuser:
        return True
    return ShopOrderItem.objects.filter(order__user=user, it_id=product.it_id, ct_status="완료").exists()


def reviews_response(request):
    queryset = ShopReview.objects.select_related("product")
    user = current_user(request)
    if not (user and (user.is_staff or user.is_superuser)):
        queryset = queryset.filter(is_confirm="1")
    it_id = request.query_params.get("it_id")
    if it_id:
        queryset = queryset.filter(product_id=it_id)
    queryset = _search_board_list(
        queryset, request, REVIEW_SEARCH_FIELDS, ("is_subject", "is_content", "product__it_name", "is_name", "product__it_id")
    )
    focus_id = safe_int(request.query_params.get("focus_is_id"), 0)
    focus_review = (
        queryset.filter(pk=focus_id).first()
        if focus_id > 0 and it_id
        else None
    )
    if focus_review:
        requested_page_size = safe_int(
            request.query_params.get("per_page") or request.query_params.get("limit"),
            20,
        )
        per_page = min(max(1, requested_page_size), 100)
        preceding = queryset.filter(
            Q(is_time__gt=focus_review.is_time)
            | Q(is_time=focus_review.is_time, pk__gt=focus_review.pk)
        ).count()
        current_page = preceding // per_page + 1
        start = (current_page - 1) * per_page
        page = queryset[start : start + per_page]
        meta = pagination_meta(queryset.count(), current_page, per_page)
    else:
        page, meta = paginate_queryset(request, queryset, default_per_page=10)
    return api_response(data=[review_payload(item) for item in page], meta=meta)
@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def reviews_view(request):
    if request.method == "GET":
        return reviews_response(request)

    user, error = require_user(request)
    if error:
        return error
    data = request_data(request)
    product = ShopProduct.objects.filter(pk=str(data.get("it_id") or "")).first()
    if not product:
        return api_error("Product not found.", status=drf_status.HTTP_404_NOT_FOUND, code="product_not_found")
    score = _review_score(data.get("is_score", 5))
    if score is None:
        return api_error("평점은 1점에서 5점 사이로 선택해 주세요.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, code="invalid_score")
    policy = current_shipping_policy()
    if int(policy.de_item_use_write or 0) == 1 and not _has_received_product(user, product):
        return api_error("사용후기는 주문이 완료된 경우에만 작성하실 수 있습니다.", status=drf_status.HTTP_403_FORBIDDEN, code="review_requires_purchase")
    review = ShopReview.objects.create(
        product=product,
        user=user,
        mb_id=user.get_username(),
        mb_nick=getattr(getattr(user, "profile", None), "nickname", "") or user.get_username(),
        is_name=member_display_name(user),
        is_score=score,
        # with moderation on (de_item_use_use) a new review waits for an administrator
        is_confirm="0" if int(policy.de_item_use_use or 0) == 1 else "1",
        is_subject=str(data.get("is_subject") or ""),
        is_content=strip_script_and_style_blocks(data.get("is_content")),
    )
    # youngcart itemuseformupdate.php: update_use_cnt / update_use_avg after every write
    recount_product_reviews([review.product_id])
    return api_response(data=review_payload(review), status=drf_status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([AllowAny])
def review_summary_view(request):
    it_id = request.query_params.get("it_id")
    queryset = ShopReview.objects.filter(is_confirm="1")
    if it_id:
        queryset = queryset.filter(product_id=it_id)
    total = queryset.count()
    average = float(queryset.aggregate(avg=Avg("is_score"))["avg"] or 0)
    scores = []
    for score in range(5, 0, -1):
        count = queryset.filter(is_score=score).count()
        scores.append({"score": score, "count": count, "percentage": round((count / total) * 100, 1) if total else 0})
    return api_response(data={"total": total, "average": round(average, 1), "photo_count": 0, "scores": scores})


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def review_detail_view(request, review_id):
    review = ShopReview.objects.select_related("product", "user").filter(pk=review_id).first()
    if not review:
        return api_error("Review not found.", status=drf_status.HTTP_404_NOT_FOUND, code="review_not_found")
    user = current_user(request)
    is_moderator = bool(user and (user.is_staff or user.is_superuser))
    is_author = bool(user and review.user_id == user.id)
    if review.is_confirm != "1" and not (is_moderator or is_author):
        # an unapproved review is not visible to others
        return api_error("Review not found.", status=drf_status.HTTP_404_NOT_FOUND, code="review_not_found")
    if request.method in ("PATCH", "DELETE") and not (is_moderator or is_author):
        return api_error("Permission denied.", status=drf_status.HTTP_403_FORBIDDEN, code="permission_denied")
    if request.method == "DELETE":
        product_id = review.product_id
        review.delete()
        recount_product_reviews([product_id])
        return api_response(data={"deleted": True, "is_id": review_id})
    if request.method == "PATCH":
        data = request_data(request)
        for field in ("is_subject", "is_content"):
            if field in data:
                value = strip_script_and_style_blocks(data.get(field)) if field == "is_content" else str(data.get(field) or "")
                setattr(review, field, value)
        if "is_score" in data:
            score = _review_score(data.get("is_score"))
            if score is None:
                return api_error("평점은 1점에서 5점 사이로 선택해 주세요.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, code="invalid_score")
            review.is_score = score
        review.save()
        recount_product_reviews([review.product_id])
    return api_response(data=review_payload(review))


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def qna_view(request):
    if request.method == "GET":
        queryset = product_questions().select_related("product", "user")
        it_id = request.query_params.get("it_id")
        if it_id:
            queryset = queryset.filter(product_id=it_id)
        queryset = _search_board_list(
            queryset, request, QNA_SEARCH_FIELDS, ("iq_subject", "iq_question", "product__it_name", "iq_name", "product__it_id")
        )
        focus_id = safe_int(request.query_params.get("focus_iq_id"), 0)
        focus_question = (
            queryset.filter(pk=focus_id).first()
            if focus_id > 0 and it_id
            else None
        )
        if focus_question:
            requested_page_size = safe_int(
                request.query_params.get("per_page") or request.query_params.get("limit"),
                20,
            )
            per_page = min(max(1, requested_page_size), 100)
            preceding = queryset.filter(
                Q(iq_time__gt=focus_question.iq_time)
                | Q(iq_time=focus_question.iq_time, pk__gt=focus_question.pk)
            ).count()
            current_page = preceding // per_page + 1
            start = (current_page - 1) * per_page
            page = queryset[start : start + per_page]
            meta = pagination_meta(queryset.count(), current_page, per_page)
        else:
            page, meta = paginate_queryset(request, queryset, default_per_page=10)
        return api_response(data=[qa_payload(item, request) for item in page], meta=meta)

    user, error = require_user(request)
    if error:
        return error
    data = request_data(request)
    product = ShopProduct.objects.filter(pk=str(data.get("it_id") or "")).first()
    if not product:
        return api_error("Product not found.", status=drf_status.HTTP_404_NOT_FOUND, code="product_not_found")
    qa = ShopQA.objects.create(
        product=product,
        user=user,
        mb_id=user.get_username(),
        mb_nick=getattr(getattr(user, "profile", None), "nickname", "") or user.get_username(),
        iq_name=member_display_name(user),
        iq_subject=str(data.get("iq_subject") or ""),
        iq_question=strip_script_and_style_blocks(data.get("iq_question")),
        iq_secret=bool_int(data.get("iq_secret")),
        iq_email=str(data.get("iq_email") or user.email or ""),
        iq_hp=str(data.get("iq_hp") or ""),
    )
    return api_response(data=qa_payload(qa, request), status=drf_status.HTTP_201_CREATED)


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def qna_detail_view(request, iq_id):
    qa = product_questions().select_related("product", "user").filter(pk=iq_id).first()
    if not qa:
        return api_error("Q&A not found.", status=drf_status.HTTP_404_NOT_FOUND, code="qa_not_found")
    user = current_user(request)
    if request.method in ("PATCH", "DELETE") and not (user and (user.is_staff or user.is_superuser or qa.user_id == user.id)):
        return api_error("Permission denied.", status=drf_status.HTTP_403_FORBIDDEN, code="permission_denied")
    if request.method in ("PATCH", "DELETE") and qa.iq_answer and not (user.is_staff or user.is_superuser):
        # YoungCart: an answered question can no longer be changed or removed by the member
        return api_error("답변이 달린 문의는 수정하거나 삭제할 수 없습니다.", status=drf_status.HTTP_403_FORBIDDEN, code="qa_answered")
    if request.method == "DELETE":
        qa.delete()
        return api_response(data={"deleted": True, "iq_id": iq_id})
    if request.method == "PATCH":
        data = request_data(request)
        is_moderator = bool(user and (user.is_staff or user.is_superuser))
        editable_fields = ["iq_subject", "iq_question", "iq_email", "iq_hp"]
        if is_moderator:
            editable_fields.append("iq_answer")
        for field in editable_fields:
            if field in data:
                value = strip_script_and_style_blocks(data.get(field)) if field in {"iq_question", "iq_answer"} else str(data.get(field) or "")
                setattr(qa, field, value)
        if "iq_secret" in data:
            qa.iq_secret = bool_int(data.get("iq_secret"))
        qa.save()
    return api_response(data=qa_payload(qa, request))


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def my_reviews_view(request):
    user, error = require_user(request)
    if error:
        return error
    queryset = ShopReview.objects.filter(user=user).select_related("product")
    page, meta = paginate_queryset(request, queryset, default_per_page=10)
    return api_response(data=[review_payload(item) for item in page], meta=meta)


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def my_qna_view(request):
    user, error = require_user(request)
    if error:
        return error
    queryset = product_questions().filter(user=user).select_related("product")
    page, meta = paginate_queryset(request, queryset, default_per_page=10)
    return api_response(data=[qa_payload(item, request) for item in page], meta=meta)
