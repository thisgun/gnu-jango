import logging
from datetime import datetime, time as day_time, timedelta

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMessage
from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.db.models.functions import TruncDate
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
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
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny
from .authentication import SessionJWTAuthentication as JWTAuthentication

from gnu_jango.bbs.models import Board, Comment, Post, Post_scrap, validate_upload_file_content
from gnu_jango.core.image_privacy import strip_image_metadata
from gnu_jango.bbs.utils import get_pretty_url
from gnu_jango.config import config
from gnu_jango.config.models import Config
from gnu_jango.config.theme_settings import theme_settings_for
from gnu_jango.core.models import (
    ContentPage,
    FAQItem,
    FAQMaster,
    VisitLog,
)
from gnu_jango.users import point_ledger
from gnu_jango.users.models import Profile, User_Point
from gnu_jango.utils.users import get_user_level, is_admin as gnu_is_admin

from .access import readable_post_queryset
from .search import apply_text_search, post_body_match
from .response import api_error, api_response
from .member_certify import (
    PasswordCheckThrottle,
    email_certify_enabled,
    flush_auth_session,
    issue_email_certify,
    open_profile_change_error,
    site_url,
    truthy_flag,
)
from .v1_auth import _clear_auth_cookies, member_payload, reissue_auth, revoke_member_tokens
from .auth_common import (  # noqa: F401 - tests import NICKNAME_MARKUP_CHARACTERS from v1_community
    NICKNAME_MARKUP_CHARACTERS,
    _strip_markup,
    email_rule_error,
    nickname_rule_error,
)
from .v1_board import _datetime, _excerpt_post_ids, _get_board, _pagination_meta, _plain_post_text, _post_payload
from .community_common import (  # noqa: F401 - urls, tests and models import these from v1_community
    GENERAL_QA_PRODUCT_ID,
    QA_META_CONFIG_PREFIX,
    User,
    _filter_qa_queryset,
    _general_qa_product,
    _member_display_name,
    _paginate,
    _request_data,
    _require_user,
    _safe_int,
    _text,
)
from .community_polls import (  # noqa: F401 - urls, tests and models import these from v1_community
    _active_poll_queryset,
    _poll_choice_payload,
    _poll_comment_payload,
    _poll_is_active,
    _poll_payload,
    _poll_session_key,
    _poll_summary_payload,
    _poll_user_level,
    _poll_vote_filter,
    poll_comment_detail_view,
    poll_comments_view,
    poll_current_view,
    poll_detail_view,
    poll_vote_view,
)
from .community_qas import (  # noqa: F401 - urls, tests and models import these from v1_community
    _qa_answer_payload,
    _qa_apply_attachments,
    _qa_can_manage,
    _qa_config_payload,
    _qa_delete_file,
    _qa_delete_file_requested,
    _qa_delete_meta,
    _qa_empty_meta,
    _qa_file_slot,
    _qa_item_for_request,
    _qa_load_meta,
    _qa_meta_config_name,
    _qa_normalize_meta,
    _qa_payload,
    _qa_queryset_for_user,
    _qa_related_questions,
    _qa_request_data,
    _qa_save_meta,
    _qa_uploaded_file,
    qa_answer_view,
    qa_detail_view,
    qas_config_view,
    qas_view,
)
from .community_memos import (  # noqa: F401 - urls, tests and models import these from v1_community
    _memo_payload,
    _memo_user_by_id,
    _notification_payload,
    memo_detail_view,
    memos_view,
    notifications_read_all_view,
    notifications_view,
)

logger = logging.getLogger(__name__)


def _board_post_url(board, post):
    # The public post address (/bbs/<bo_table>/<id>, %-escaped), as Post.get_absolute_url builds it.
    return get_pretty_url(board.bo_table, _public_post_id(post))


def _public_post_id(post):
    return post.wr_parent or post.pk


def _scrap_target_post(request, bo_table, wr_id):
    board = _get_board(bo_table)
    post_id = _safe_int(wr_id, 0)
    if not board or not post_id:
        return board, None
    queryset = readable_post_queryset(request, Post.objects.filter(board=board))
    post = queryset.filter(legacy_wr_id=post_id).first()
    if post:
        return board, post
    post = queryset.filter(pk=post_id).first()
    if post:
        return board, post
    return board, queryset.filter(wr_parent=post_id, wr_reply="").order_by("pk").first()


def _scrap_payload(scrap):
    post = scrap.post
    board = scrap.board
    author = post.user
    return {
        "ms_id": scrap.pk,
        "mb_id": scrap.user.get_username() if scrap.user_id else "",
        "bo_table": board.bo_table,
        "wr_id": _public_post_id(post),
        "ms_datetime": _datetime(scrap.ms_datetime),
        "bo_subject": board.bo_subject,
        "wr_subject": post.wr_subject or "",
        "wr_seo_title": post.wr_slug or "",
        "wr_datetime": _datetime(post.wr_datetime),
        "wr_name": post.wr_name or (author.get_username() if author else ""),
        "post_mb_id": author.get_username() if author else "",
        "href": _board_post_url(board, post),
    }


def _my_post_payload(post):
    return {
        "wr_id": post.pk,
        "wr_subject": post.wr_subject or "",
        "wr_seo_title": post.wr_slug or "",
        "wr_datetime": _datetime(post.wr_datetime),
        "bo_table": post.board.bo_table,
        "bo_subject": post.board.bo_subject,
    }


def _my_comment_payload(comment):
    return {
        "wr_id": comment.pk,
        "wr_content": comment.wr_content or "",
        "wr_datetime": _datetime(comment.wr_datetime),
        "bo_table": comment.board.bo_table,
        "bo_subject": comment.board.bo_subject,
        "wr_parent": comment.post_id,
    }


def _point_payload(point):
    return {
        "po_id": point.pk,
        "po_content": point.po_content or "",
        "po_point": point.po_point,
        "po_use_point": point.po_use_point,
        "po_mb_point": point.po_mb_point,
        "po_datetime": _datetime(point.po_datetime),
        "po_rel_table": point.po_rel_table or "",
        "po_rel_action": point.po_rel_action or "",
    }


def _content_payload(content):
    return {
        "co_id": content.co_id,
        "co_subject": content.co_subject or "",
        "co_content": content.co_content or "",
        "co_mobile_content": content.co_mobile_content or "",
        "co_html": content.co_html or 0,
        "co_skin": content.co_skin or "basic",
        "co_mobile_skin": content.co_mobile_skin or "basic",
        "co_seo_title": content.co_seo_title or "",
        "co_include_head": content.co_include_head or "",
        "co_include_tail": content.co_include_tail or "",
        "co_order": content.co_order or 0,
        "co_use": content.co_use or 0,
    }


def _faq_master_payload(master):
    if not master:
        return None
    return {
        "fm_id": master.fm_id,
        "fm_subject": master.fm_subject or "",
        "fm_head_html": master.fm_head_html or "",
        "fm_tail_html": master.fm_tail_html or "",
        "fm_mobile_head_html": master.fm_mobile_head_html or "",
        "fm_mobile_tail_html": master.fm_mobile_tail_html or "",
        "fm_order": master.fm_order or 0,
    }


def _faq_item_payload(item):
    return {
        "fa_id": item.fa_id,
        "fm_id": item.master_id,
        "fa_subject": item.fa_subject or "",
        "fa_content": item.fa_content or "",
        "fa_order": item.fa_order or 0,
    }


PASSWORD_RESET_SENT_MESSAGE = "입력하신 정보와 일치하는 회원이 있으면 비밀번호 재설정 메일을 보냈습니다."


def _password_reset_url(user, request):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    # The Next.js site may live on its own origin (the same setting the social login uses).
    return site_url(request, f"/forgot-password?uid={uid}&token={token}")


def _send_password_reset_mail(user, request):
    """Gnuboard5 mails the reset link; only the mailbox owner can use it."""
    title = Config.objects.filter(name="cf_title").values_list("value", flat=True).first() or "GNU Jango"
    hours = int(getattr(settings, "PASSWORD_RESET_TIMEOUT", 60 * 60 * 3)) // 3600
    body = (
        f"{user.get_username()}님, 비밀번호 재설정을 요청하셨습니다.\n\n"
        f"아래 링크에서 새 비밀번호를 설정해 주세요. 링크는 {hours}시간 동안 한 번만 사용할 수 있습니다.\n"
        f"{_password_reset_url(user, request)}\n\n"
        "본인이 요청하지 않았다면 이 메일을 무시하세요."
    )
    try:
        EmailMessage(subject=f"[{title}] 비밀번호 재설정 안내", body=body, to=[user.email]).send()
    except Exception:  # noqa: BLE001 - the response must not reveal whether the member exists
        logger.exception("Password reset mail could not be sent to user %s", user.pk)


def _user_from_password_reset_token(reset_token, uid=None, token=None):
    if reset_token and ":" in reset_token:
        uid, token = reset_token.split(":", 1)
    if not uid or not token:
        return None
    try:
        user_id = force_str(urlsafe_base64_decode(uid))
    except (TypeError, ValueError, OverflowError, UnicodeDecodeError):
        return None
    if not user_id.isdigit():
        return None
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if not user or not default_token_generator.check_token(user, token):
        return None
    return user


# Days that have ended do not change, so their counts are kept for this long (old visits can still be
# deleted by the privacy clean-up, hence not until midnight). Today is always counted live.
VISIT_HISTORY_CACHE_SECONDS = 600


def _page_visits():
    return VisitLog.objects.filter(
        method="GET",
        status_code__gte=200,
        status_code__lt=400,
        is_staff_area=False,
    ).exclude(
        Q(path__startswith="/api/")
        | Q(path__startswith="/_next/")
        | Q(path__startswith="/static/")
        | Q(path__startswith="/media/")
    )


def _visits_by_date(visits):
    # visit.lib.php counts one visit per address and day (g5_visit is unique on vi_ip, vi_date); a
    # row logged without an address cannot be matched to others and counts on its own.
    daily_visits = (
        visits.annotate(visit_date=TruncDate("created_at"))
        .values("visit_date")
        .annotate(
            addresses=Count("ip_address", distinct=True),
            unaddressed=Count("pk", filter=Q(ip_address__isnull=True)),
        )
    )
    return {row["visit_date"]: row["addresses"] + row["unaddressed"] for row in daily_visits}


def visit_stats():
    """Today / yesterday / busiest day / total, as the home "접속자집계" box shows them.

    The settings call that carries these runs on every page, and counting the whole visit history
    each time grew with every visit. Past days come from the cache; only today's rows are counted.
    """
    today = timezone.localdate()
    today_start = timezone.make_aware(datetime.combine(today, day_time.min))
    history_key = f"visit-stats:history:{today.isoformat()}"
    history = cache.get(history_key)
    if history is None:
        past = _visits_by_date(_page_visits().filter(created_at__lt=today_start))
        history = {
            "yesterday": past.get(today - timedelta(days=1), 0),
            "max": max(past.values(), default=0),
            "total": sum(past.values()),
        }
        cache.set(history_key, history, VISIT_HISTORY_CACHE_SECONDS)
    today_count = _visits_by_date(_page_visits().filter(created_at__gte=today_start)).get(today, 0)
    return {
        "today": today_count,
        "yesterday": history["yesterday"],
        "max": max(history["max"], today_count),
        "total": history["total"] + today_count,
    }


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def settings_view(request):
    return settings_response(request)


def settings_response(request):
    from gnu_jango.shop.shop_display import list_display, public_logo_urls

    data = config.get_all()
    visit_stats_payload = visit_stats()
    return api_response(
        data={
            "cf_title": data.get("cf_title", "GNU Jango"),
            "cf_company_name": data.get("cf_company_name", ""),
            "cf_company_owner": data.get("cf_company_owner", ""),
            "cf_company_addr": data.get("cf_company_addr", ""),
            "cf_company_biz_no": data.get("cf_company_biz_no", ""),
            "cf_company_tel": data.get("cf_company_tel", ""),
            "cf_company_tongsin_no": data.get("cf_company_tongsin_no", ""),
            "cf_company_buga_no": data.get("cf_company_buga_no", ""),
            "cf_company_fax": data.get("cf_company_fax", ""),
            "cf_company_info_name": data.get("cf_company_info_name", ""),
            "cf_company_email": data.get("cf_company_email", ""),
            "de_admin_company_tel": data.get("de_admin_company_tel", ""),
            "de_bank_use": data.get("de_bank_use", ""),
            "de_bank_account": data.get("de_bank_account", ""),
            "cf_home_boards": data.get("cf_home_boards", ""),
            "cf_home_gallery": data.get("cf_home_gallery", ""),
            "cf_docs_group": data.get("cf_docs_group", ""),
            "theme_settings": theme_settings_for(str(data.get("cf_theme") or ""), data),
            "cf_bbs_rewrite": _safe_int(data.get("cf_bbs_rewrite"), 0),
            "infinite_scroll": False,
            "comment_editor": False,
            "pwa_enabled": False,
            "visit": visit_stats_payload,
            # Shop logos (uploaded in the shop settings; "" when not uploaded) and the
            # search / type-list / related-products layout from the shop display settings.
            **public_logo_urls(),
            "shop_display": list_display(),
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def recent_groups_view(request):
    groups = []
    seen = set()
    for board in Board.objects.select_related("group").order_by("group__gr_id", "bo_order", "pk"):
        if not board.group_id or board.group_id in seen:
            continue
        groups.append({"gr_id": board.group.gr_id, "gr_subject": board.group.gr_subject})
        seen.add(board.group_id)
    return api_response(data=groups)


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def recent_view(request):
    return recent_response(request)


def recent_response(request):
    view = (request.query_params.get("view") or "").strip()
    gr_id = (request.query_params.get("gr_id") or "").strip()
    mb_id = (request.query_params.get("mb_id") or "").strip()

    items = []
    if view in ("", "w"):
        # new.php: only boards in the site search (b.bo_use_search = 1) feed the new posts.
        posts = readable_post_queryset(
            request,
            Post.objects.filter(board__bo_use_search=True)
            .select_related("board", "board__group", "user")
            .order_by("-wr_datetime", "-pk"),
        )
        if gr_id:
            posts = posts.filter(board__group__gr_id=gr_id)
        if mb_id:
            posts = posts.filter(user__username=mb_id)
        for post in posts[:200]:
            items.append(
                {
                    "bn_id": post.pk,
                    "gr_id": post.board.group.gr_id if post.board.group_id else "",
                    "gr_subject": post.board.group.gr_subject if post.board.group_id else "",
                    "bo_table": post.board.bo_table,
                    "bo_subject": post.board.bo_subject,
                    "wr_id": post.pk,
                    "wr_parent": post.pk,
                    "wr_subject": post.wr_subject or "",
                    "wr_seo_title": post.wr_slug or "",
                    "is_comment": False,
                    "mb_id": post.user.get_username() if post.user_id else "",
                    "wr_name": post.wr_name or "",
                    "wr_email": post.wr_email or "",
                    "wr_homepage": post.wr_homepage or "",
                    "wr_datetime": _datetime(post.wr_datetime),
                    "href": _board_post_url(post.board, post),
                }
            )

    if view in ("", "c"):
        comments = (
            Comment.objects.filter(board__bo_use_search=True)
            .select_related("board", "board__group", "post", "user")
            .order_by("-wr_datetime", "-pk")
        )
        comments = comments.filter(post__in=readable_post_queryset(request, Post.objects.all()))
        if gr_id:
            comments = comments.filter(board__group__gr_id=gr_id)
        if mb_id:
            comments = comments.filter(user__username=mb_id)
        for comment in comments[:200]:
            subject = comment.post.wr_subject if comment.post_id else ""
            items.append(
                {
                    "bn_id": comment.pk,
                    "gr_id": comment.board.group.gr_id if comment.board.group_id else "",
                    "gr_subject": comment.board.group.gr_subject if comment.board.group_id else "",
                    "bo_table": comment.board.bo_table,
                    "bo_subject": comment.board.bo_subject,
                    "wr_id": comment.pk,
                    "wr_parent": comment.post_id,
                    "wr_subject": subject,
                    "wr_seo_title": comment.post.wr_slug if comment.post_id else "",
                    "is_comment": True,
                    "mb_id": comment.user.get_username() if comment.user_id else "",
                    "wr_name": comment.wr_name or "",
                    "wr_email": comment.wr_email or "",
                    "wr_homepage": "",
                    "wr_datetime": _datetime(comment.wr_datetime),
                    "href": _board_post_url(comment.board, comment.post) if comment.post_id else "",
                }
            )

    items.sort(key=lambda item: item["wr_datetime"], reverse=True)
    page = max(_safe_int(request.query_params.get("page"), 1), 1)
    per_page = min(max(_safe_int(request.query_params.get("limit"), 20), 1), 100)
    total = len(items)
    start = (page - 1) * per_page
    return api_response(data=items[start : start + per_page], meta=_pagination_meta(total, page, per_page))


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def popular_search_view(request):
    return popular_search_response(request)


def popular_search_response(request):
    from gnu_jango.core.search_privacy import popular_keyword_rows
    limit = min(max(_safe_int(request.query_params.get("limit"), 5), 1), 20)
    days = min(max(_safe_int(request.query_params.get("days"), 3), 1), 90)
    keywords = popular_keyword_rows(days=days, limit=limit)
    return api_response(
        data=[{"pp_word": row["keyword"], "cnt": row["cnt"] or 0} for row in keywords]
    )


def _searchable_boards(request):
    """search.php:25: boards in the site search (bo_use_search = 1) whose list level the member
    reaches (bo_list_level <= mb_level); the super administrator passes the level check."""
    boards = Board.objects.filter(bo_use_search=True)
    user = getattr(request, "user", None)
    if user and gnu_is_admin(user):
        return boards
    return boards.filter(bo_list_level__lte=get_user_level(user) if user else 1)


SEARCH_PREVIEW_LENGTH = 220
SEARCH_PREVIEW_LEAD = 70
SECRET_SEARCH_PREVIEW = "비밀글입니다."


def _search_snippet(text, keyword, length=SEARCH_PREVIEW_LENGTH, lead=SEARCH_PREVIEW_LEAD):
    """The part of a post's text around the keyword (reference api_search_snippet).

    Cutting the first 200 characters would always show a long post's opening and never why it
    matched, so the snippet starts a little before the keyword; with no match in the body (only the
    title matched) it starts at the beginning. A cut side gets an ellipsis.
    """
    if not text:
        return ""
    position = text.lower().find(keyword.lower()) if keyword else -1
    start = max(0, position - lead) if position >= 0 else 0
    snippet = text[start : start + length]
    if start > 0:
        snippet = f"...{snippet}"
    if start + length < len(text):
        snippet = f"{snippet}..."
    return snippet


def _body_match(request, board, keyword):
    """Body-text matches the viewer may search. On a board that charges read points only the viewer's own
    posts and the posts they already paid for match by body (a super administrator reads everything):
    otherwise hit / no hit would tell an unpaid reader what a post says. Titles stay searchable for everyone."""
    return post_body_match(request, keyword, Post.objects.filter(board=board))


def _search_post_payload(post, request, keyword, previewable_ids):
    """A search hit: the list payload (no body) plus a short preview the viewer may already read."""
    payload = _post_payload(post, request, list_view=True)
    if post.pk not in previewable_ids:
        preview = ""
    elif payload["is_secret"]:
        preview = SECRET_SEARCH_PREVIEW
    else:
        preview = _search_snippet(_plain_post_text(post.wr_content), keyword)
    payload["wr_content_preview"] = preview
    return payload


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def search_view(request):
    """search.php: matches grouped by board. Hits carry no body — only a preview that follows the
    board list excerpt rules (read level, secret, read points), as the reference API does — title
    matches come first, and `page` walks one board's matches (with bo_table)."""
    keyword = (request.query_params.get("q") or request.query_params.get("stx") or "").strip()
    bo_table = (request.query_params.get("bo_table") or "").strip()
    sfl = (request.query_params.get("sfl") or "wr_subject||wr_content").strip()
    per_page = min(max(_safe_int(request.query_params.get("per_page"), _safe_int(request.query_params.get("limit"), 10)), 1), 50)
    # 쪽은 한 게시판만 볼 때만 넘긴다 — 여러 게시판을 함께 보면 게시판마다 건수가 달라 쪽 번호가 맞지 않는다.
    page = max(_safe_int(request.query_params.get("page"), 1), 1) if bo_table else 1
    offset = (page - 1) * per_page

    groups = []
    total_count = 0
    if keyword:
        boards = _searchable_boards(request).order_by("bo_order", "pk")
        if bo_table:
            boards = boards.filter(bo_table=bo_table)
        for board in boards:
            queryset = readable_post_queryset(
                request,
                Post.objects.filter(board=board).select_related("board", "user").order_by("-wr_datetime", "-pk"),
            )
            search_q = Q()
            if "wr_subject" in sfl:
                search_q |= Q(wr_subject__icontains=keyword)
            if "wr_content" in sfl:
                search_q |= _body_match(request, board, keyword)
            if "wr_name" in sfl:
                search_q |= Q(wr_name__icontains=keyword)
            if "mb_id" in sfl:
                search_q |= Q(user__username__icontains=keyword)
            if not search_q:
                search_q = Q(wr_subject__icontains=keyword) | _body_match(request, board, keyword)
            selected = set(sfl.split("||"))
            indexed_fields = [name for field, name in (("wr_subject", "title"), ("wr_content", "body")) if field in selected]
            queryset = apply_text_search(queryset, keyword, search_q, request=request,
                                         fields=(indexed_fields or ["title", "body"]) if not selected.intersection({"wr_name", "mb_id"}) else False)
            count = queryset.count()
            if not count:
                continue
            total_count += count
            # 제목이 맞은 글을 먼저 — 본문에만 스친 최신 글이 위에 오면 찾는 사람이 끝까지 훑어야 한다.
            ranked = queryset.annotate(
                title_rank=Case(When(wr_subject__icontains=keyword, then=Value(0)), default=Value(1), output_field=IntegerField())
            ).order_by("title_rank", *(["-_search_rank"] if "_search_rank" in queryset.query.annotations else []), "-wr_datetime", "-pk")
            posts = list(ranked[offset : offset + per_page])
            previewable_ids = _excerpt_post_ids(request, board, posts)
            groups.append(
                {
                    "bo_table": board.bo_table,
                    "bo_subject": board.bo_subject,
                    "count": count,
                    "posts": [_search_post_payload(post, request, keyword, previewable_ids) for post in posts],
                }
            )

    return api_response(
        data={"keyword": keyword, "total_count": total_count, "results": groups},
        meta=_pagination_meta(total_count, page, per_page),
    )


def _nickname_change_error(profile, nickname):
    """register_form_update.php rules for a new nickname: the shared signup rules (column limit, no
    markup, no cf_prohibit_id word) and no second change within cf_nick_modify days of mb_nick_date."""
    if not nickname or nickname == profile.nickname:
        return None
    message = nickname_rule_error(nickname)
    if not message:
        days = point_ledger.config_points("cf_nick_modify")
        changed = profile.nickname_date
        if days > 0 and changed and timezone.localdate(changed) > timezone.localdate() - timedelta(days=days):
            message = f"닉네임은 변경 후 {days}일이 지나야 다시 바꿀 수 있습니다."
    if not message:
        return None
    return api_error(
        message, status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, code="validation_error", details={"mb_nick": message}
    )


def _email_change_password_error(user, current_password):
    if not user.has_usable_password():
        return None
    if not current_password:
        message = "이메일을 변경하려면 현재 비밀번호를 입력해주세요."
        code = "current_password_required"
    elif not user.check_password(current_password):
        message = "현재 비밀번호가 올바르지 않습니다."
        code = "current_password_invalid"
    else:
        return None
    return api_error(
        message, status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, code=code, details={"mb_password_current": message}
    )


EMAIL_CHANGED_MESSAGE = "회원 정보가 수정 되었습니다.\n\nE-mail 주소가 변경되었으므로 다시 인증하셔야 합니다."


def _email_changed_response(request, user, profile):
    """register_form_update.php: the certification is cleared, a certify link goes to the new
    address and the member is logged out until they click it."""
    issue_email_certify(request, user, profile, changed=True)
    revoke_member_tokens(user)
    response = api_response(
        data={
            "member": member_payload(user, request),
            "email_certify_required": True,
            "logged_out": True,
            "message": EMAIL_CHANGED_MESSAGE,
        }
    )
    _clear_auth_cookies(response)
    flush_auth_session(request)
    return response


@api_view(["GET", "PATCH"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@throttle_classes([PasswordCheckThrottle])
def member_me_view(request):
    user, error = _require_user(request)
    if error:
        return error

    if request.method == "GET":
        profile, _ = Profile.objects.get_or_create(user=user)
        member = member_payload(user, request)
        member.update(
            {
                "mb_hp": profile.user_hp or "",
                "mb_tel": "",
                "mb_today_login": user.last_login.isoformat() if user.last_login else "",
                "mb_zip": profile.user_zip or "",
                "mb_addr1": profile.user_addr1 or "",
                "mb_addr2": profile.user_addr2 or "",
                "mb_addr3": profile.user_addr_jibeon or "",
            }
        )
        return api_response(data={"member": member})

    data = _request_data(request)
    current_password = _text(data.get("mb_password_current")) or _text(data.get("current_password"))
    new_password = _text(data.get("mb_password")) or _text(data.get("password"))
    if new_password:
        if user.has_usable_password() and not current_password:
            return api_error(
                "Current password is required.",
                status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="current_password_required",
                details={"mb_password_current": "Current password is required."},
            )
        if current_password and not user.check_password(current_password):
            return api_error(
                "Current password is invalid.",
                status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="current_password_invalid",
                details={"mb_password_current": "Current password is invalid."},
            )
        password_re = _text(data.get("mb_password_re")) or _text(data.get("password_confirm"))
        if new_password != password_re:
            return api_error(
                "Password confirmation does not match.",
                status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"mb_password_re": "Password confirmation does not match."},
            )
        try:
            validate_password(new_password, user)
        except DjangoValidationError as exc:
            return api_error(
                "Password validation failed.",
                status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="password_validation_failed",
                details={"mb_password": exc.messages},
            )
        user.set_password(new_password)

    email = (_text(data.get("mb_email")) or _text(data.get("email"))).strip()
    if email:
        # register_form_update.php checks valid_mb_email and prohibit_mb_email on an update too; the
        # barred domains only for a new address, so a member is not locked out of the form by a later ban.
        email_error = email_rule_error(email, check_prohibited=email.lower() != user.email.lower())
        if email_error:
            return api_error(
                email_error,
                status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="validation_error",
                details={"mb_email": email_error},
            )
        exists = User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists()
        if exists:
            return api_error("Email is already in use.", status=drf_status.HTTP_409_CONFLICT, code="email_exists")
        if email != user.email:
            # The address receives password reset mail, so moving it needs the current password
            # (register_form.php asks for the password before the member form opens).
            password_error = _email_change_password_error(user, current_password)
            if password_error:
                return password_error
        # register_form_update.php: a new address must be certified again when certification is on.
        email_changed = email != user.email
        email_recertify = email_changed and email_certify_enabled()
        user.email = email
    else:
        email_changed = email_recertify = False
    # register_form_update.php: clean_xss_tags() on the name; markup is dropped, not stored.
    name = _strip_markup(_text(data.get("mb_name")) or _text(data.get("name")))
    if name:
        user.first_name = name

    profile, _ = Profile.objects.get_or_create(user=user)
    nickname = (_text(data.get("mb_nick")) or _text(data.get("nickname"))).strip()
    nickname_error = _nickname_change_error(profile, nickname)
    if nickname_error:
        return nickname_error
    if nickname and nickname != profile.nickname:
        if User.objects.filter(profile__nickname__iexact=nickname).exclude(pk=user.pk).exists():
            return api_error("Nickname is already in use.", status=drf_status.HTTP_409_CONFLICT, code="nickname_exists")
        profile.nickname = nickname
        profile.nickname_date = timezone.now()  # register_form_update.php: mb_nick_date = today
    if name:
        profile.realname = name
    if "mb_open" in data:
        wanted_open = truthy_flag(data.get("mb_open"))
        open_error = open_profile_change_error(profile, wanted_open)
        if open_error:
            return api_error(
                open_error,
                status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="validation_error",
                details={"mb_open": open_error},
            )
        if wanted_open != profile.open_profile:
            profile.open_profile = wanted_open
            profile.open_profile_date = timezone.now()  # register_form_update.php: mb_open_date = today

    user.save()
    profile.save()
    if email_recertify:
        return _email_changed_response(request, user, profile)
    refreshed = authenticate(request, username=user.get_username(), password=new_password) if new_password else user
    response = api_response(data={"member": member_payload(refreshed or user, request)})
    if new_password or email_changed:
        # The password, or the address that receives the password reset mail, changed: every device
        # signed in before is logged out (their access tokens included); this one gets new tokens.
        revoke_member_tokens(user)
        response.data["data"].update(reissue_auth(response, user, request))
    return response


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([MultiPartParser, FormParser])
def member_icon_view(request):
    user, error = _require_user(request)
    if error:
        return error
    uploaded_file = request.FILES.get("mb_icon") or request.FILES.get("icon") or request.FILES.get("file")
    if not uploaded_file:
        return api_error("Icon file is required.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, details={"mb_icon": "Icon file is required."})

    try:
        validate_upload_file_content(uploaded_file)
    except DjangoValidationError as exc:
        return api_error(
            "Icon validation failed.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"mb_icon": "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)},
        )

    profile, _ = Profile.objects.get_or_create(user=user)
    profile.icon = strip_image_metadata(uploaded_file)
    profile.save(update_fields=["icon"])
    return api_response(data={"member": member_payload(user, request)})


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def member_profile_view(request, mb_id):
    if "\x00" in mb_id:
        return api_error("Member not found.", status=drf_status.HTTP_404_NOT_FOUND, code="member_not_found")

    viewer, error = _require_user(request)
    if error:
        return error

    # profile.php: only the member themself and the super admin skip the mb_open rules.
    privileged = viewer.is_superuser or viewer.get_username() == mb_id
    viewer_profile, _ = Profile.objects.get_or_create(user=viewer)
    if not privileged and not viewer_profile.open_profile:
        message = (
            "자신의 정보를 공개하지 않으면 다른분의 정보를 조회할 수 없습니다.\n\n"
            "정보공개 설정은 회원정보수정에서 하실 수 있습니다."
        )
        return api_error(message, status=drf_status.HTTP_403_FORBIDDEN, code="own_profile_not_open")

    # Gnuboard5 profile.php treats withdrawn or blocked members as not existing.
    user = User.objects.filter(username=mb_id, is_active=True).first()
    if not user:
        return api_error("Member not found.", status=drf_status.HTTP_404_NOT_FOUND, code="member_not_found")
    profile, _ = Profile.objects.get_or_create(user=user)
    if not privileged and not profile.open_profile:
        return api_error("정보공개를 하지 않았습니다.", status=drf_status.HTTP_403_FORBIDDEN, code="profile_not_open")
    payload = member_payload(user, request)
    for private_field in ("mb_no", "mb_name", "mb_email", "mb_today_login", "mb_open_date", "is_staff", "is_superuser"):
        payload.pop(private_field, None)
    payload.update(
        {
            "mb_open": 1 if profile.open_profile else 0,
            "mb_homepage": profile.user_homepage or "",
            "mb_profile": "",
            # profile.php: whole days elapsed since joining, not a difference of calendar dates
            "reg_days": max((timezone.now() - user.date_joined).days, 0) if user.date_joined else 0,
        }
    )
    return api_response(data={"member": payload})


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def member_posts_view(request):
    user, error = _require_user(request)
    if error:
        return error
    queryset = readable_post_queryset(
        request,
        Post.objects.filter(user=user).select_related("board", "user").order_by("-wr_datetime", "-pk"),
    )
    page, meta = _paginate(request, queryset, 30)
    return api_response(data=[_my_post_payload(post) for post in page], meta=meta)


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def member_comments_view(request):
    user, error = _require_user(request)
    if error:
        return error
    readable_posts = readable_post_queryset(request, Post.objects.all())
    queryset = Comment.objects.filter(user=user, post__in=readable_posts).select_related("board", "post", "user").order_by("-wr_datetime", "-pk")
    page, meta = _paginate(request, queryset, 30)
    return api_response(data=[_my_comment_payload(comment) for comment in page], meta=meta)


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def member_points_view(request):
    user, error = _require_user(request)
    if error:
        return error
    queryset = User_Point.objects.filter(user=user).order_by("-po_datetime", "-pk")
    page, meta = _paginate(request, queryset, 15)
    return api_response(data=[_point_payload(point) for point in page], meta=meta)


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def scraps_view(request):
    user, error = _require_user(request)
    if error:
        return error

    if request.method == "GET":
        readable_posts = readable_post_queryset(request, Post.objects.all())
        queryset = Post_scrap.objects.filter(user=user, post__in=readable_posts).select_related("board", "post", "post__user", "user").order_by("-ms_datetime", "-pk")
        page, meta = _paginate(request, queryset, 20)
        return api_response(data=[_scrap_payload(scrap) for scrap in page], meta=meta)

    data = _request_data(request)
    board, post = _scrap_target_post(request, data.get("bo_table") or "", data.get("wr_id"))
    if not post:
        return api_error("Scrap target was not found.", status=drf_status.HTTP_404_NOT_FOUND, code="scrap_target_not_found")

    scrap, _ = Post_scrap.objects.get_or_create(
        user=user,
        board=board,
        post=post,
        defaults={"ms_datetime": timezone.now()},
    )
    return api_response(data={"scrap": _scrap_payload(scrap), "scrapped": True}, status=drf_status.HTTP_201_CREATED)


@api_view(["GET", "DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def scrap_status_view(request, bo_table, wr_id):
    user, error = _require_user(request)
    if error:
        return error
    board, post = _scrap_target_post(request, bo_table, wr_id)
    scrap = None
    if board and post:
        scrap = Post_scrap.objects.select_related("board", "post", "post__user", "user").filter(user=user, board=board, post=post).first()
    if request.method == "DELETE":
        if scrap:
            scrap.delete()
        return api_response(data={"deleted": True, "scrapped": False})
    return api_response(data={"scrapped": bool(scrap), "scrap": _scrap_payload(scrap) if scrap else None})


@api_view(["DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def scrap_delete_view(request, scrap_id):
    user, error = _require_user(request)
    if error:
        return error
    deleted, _ = Post_scrap.objects.filter(pk=scrap_id, user=user).delete()
    return api_response(data={"deleted": bool(deleted), "ms_id": scrap_id})


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def faqs_view(request):
    return faqs_response(request)


def faqs_response(request):
    masters_qs = FAQMaster.objects.filter(fm_use__gt=0).order_by("fm_order", "fm_id")
    masters = list(masters_qs)
    fm_id = _safe_int(request.query_params.get("fm_id"), 0)
    current = next((master for master in masters if master.fm_id == fm_id), None) if fm_id else None
    if current is None and masters:
        current = masters[0]  # Gnuboard5 faq.php shows the first category for a missing or unknown one
    keyword = (request.query_params.get("stx") or request.query_params.get("q") or "").strip()

    items_qs = FAQItem.objects.filter(fa_use__gt=0, master__fm_use__gt=0).select_related("master").order_by("fa_order", "fa_id")
    if current:
        items_qs = items_qs.filter(master=current)
    if keyword:
        items_qs = items_qs.filter(Q(fa_subject__icontains=keyword) | Q(fa_content__icontains=keyword))

    page_items, meta = _paginate(request, items_qs, default_per_page=15, max_per_page=100)
    total = meta.get("total", 0)
    current_page = meta.get("current_page", 1)
    per_page = meta.get("per_page", 15)
    start = ((current_page - 1) * per_page) + 1 if total else None
    meta.update({"from": start, "to": min((current_page * per_page), total) if total else None})
    return api_response(
        data={
            "masters": [_faq_master_payload(master) for master in masters],
            "current": _faq_master_payload(current),
            "items": [_faq_item_payload(item) for item in page_items],
            "meta": meta,
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def content_list_view(request):
    queryset = ContentPage.objects.filter(co_use__gt=0).order_by("co_order", "co_id")
    return api_response(data=[_content_payload(content) for content in queryset])


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def content_detail_view(request, co_id):
    if "\x00" in co_id:
        return api_error("Content not found.", status=drf_status.HTTP_404_NOT_FOUND, code="content_not_found")

    content = ContentPage.objects.filter(co_id=co_id, co_use__gt=0).first()
    if not content:
        return api_error("Content not found.", status=drf_status.HTTP_404_NOT_FOUND, code="content_not_found")
    return api_response(data=_content_payload(content))


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def content_by_seo_view(request, slug):
    if "\x00" in slug:
        return api_error("Content not found.", status=drf_status.HTTP_404_NOT_FOUND, code="content_not_found")

    content = ContentPage.objects.filter(co_seo_title=slug, co_use__gt=0).first()
    if not content:
        content = ContentPage.objects.filter(co_id=slug, co_use__gt=0).first()
    if not content:
        return api_error("Content not found.", status=drf_status.HTTP_404_NOT_FOUND, code="content_not_found")
    return api_response(data=_content_payload(content))


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def password_reset_view(request):
    data = _request_data(request)
    step = data.get("step") or "request"
    if step in ("request", "cert_request"):
        if step == "cert_request":
            return api_error(
                "Identity verification password reset is not configured.",
                status=drf_status.HTTP_503_SERVICE_UNAVAILABLE,
                code="cert_password_reset_unconfigured",
            )
        mb_id = str(data.get("mb_id") or "").strip()
        mb_email = str(data.get("mb_email") or data.get("email") or "").strip()
        if not mb_id or not mb_email:
            return api_error(
                "아이디와 이메일을 모두 입력해주세요.",
                status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="validation_error",
            )
        user = User.objects.filter(username=mb_id, is_active=True).first()
        if user and user.email and user.email.lower() == mb_email.lower():
            _send_password_reset_mail(user, request)
        # The same answer either way, so the form cannot be used to test ids and e-mails.
        return api_response(data={"sent": True, "message": PASSWORD_RESET_SENT_MESSAGE})

    if step == "reset":
        token = str(data.get("reset_token") or "")
        user = _user_from_password_reset_token(
            token,
            uid=str(data.get("uid") or ""),
            token=str(data.get("token") or ""),
        )
        if not user:
            return api_error("Invalid reset token.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, code="invalid_reset_token")
        password = data.get("mb_password") or ""
        password_re = data.get("mb_password_re") or data.get("password_confirm") or ""
        if not password or password != password_re:
            return api_error("Password confirmation does not match.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY)
        try:
            validate_password(password, user)
        except DjangoValidationError as exc:
            return api_error(
                "Password validation failed.",
                status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                code="password_validation_failed",
                details={"mb_password": exc.messages},
            )
        user.set_password(password)
        user.save(update_fields=["password"])
        revoke_member_tokens(user)
        return api_response(data={"reset": True})

    return api_error("Invalid password reset step.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY)


# The password checks of the profile update are throttled (PasswordCheckThrottle skips plain edits).
member_me_view.cls.throttle_scope = "member-password"
