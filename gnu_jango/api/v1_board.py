import html
import os
import re
import uuid
from urllib.parse import quote, unquote, urlsplit

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import SuspiciousFileOperation, ValidationError as DjangoValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Case, Count, F, IntegerField, OuterRef, Q, Subquery, When
from django.db.models.functions import Coalesce
from django.http import FileResponse
from django.utils import timezone
from django.utils.html import strip_tags
from django.utils.text import get_valid_filename
from rest_framework import status as drf_status
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, parser_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from .authentication import SessionJWTAuthentication as JWTAuthentication

from gnu_jango.bbs.delete_posts import Delete_all_posts
from gnu_jango.bbs.models import Board, Comment, Post, Post_file, Post_good, Post_scrap, validate_upload_file_content
from gnu_jango.core.image_privacy import strip_image_metadata
from gnu_jango.core.legacy_assets import legacy_area_roots
from gnu_jango.core.thumbnails import thumbnail_url
from gnu_jango.bbs.utils import get_next_num
from gnu_jango.utils.lib import check_password, get_client_ip, get_encrypt_string
from gnu_jango.utils.users import get_user_level, is_admin as gnu_is_admin
from gnu_jango.users import point_ledger

from .access import listable_post_queryset, readable_post_queryset, secret_post_session_key
from .response import api_error, api_response
from .search import apply_text_search
from .v1_auth import _auth_user_from_request, _captcha_matches, _consume_captcha, member_payload

IMAGE_EXTENSIONS = {".gif", ".jfif", ".jpg", ".jpeg", ".png", ".webp"}
EDITOR_UPLOAD_EXTENSIONS = IMAGE_EXTENSIONS | {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip"}
MAX_EDITOR_UPLOAD_SIZE = 10 * 1024 * 1024
BOARD_TABLE_ALIASES = {"cm_free": "free"}


def _request_data(request):
    if isinstance(request.data, dict):
        return request.data
    return {}


def _truthy(value):
    return value in (True, 1, "1", "true", "True", "yes", "on", "secret")


def _bool_int(value):
    return 1 if bool(value) else 0


def _datetime(value):
    if not value:
        return ""
    try:
        return timezone.localtime(value).isoformat()
    except ValueError:
        return value.isoformat()


def _safe_int(value, default=0):
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if -(1 << 63) <= result <= (1 << 63) - 1 else default


def _member_name(user):
    if not user:
        return ""
    profile = getattr(user, "profile", None)
    return (
        getattr(profile, "nickname", "")
        or getattr(profile, "realname", "")
        or user.get_full_name()
        or user.get_username()
    )


def _user_level(user):
    if not user or not getattr(user, "is_authenticated", False):
        return 1
    return get_user_level(user)


def _authenticated_user(request):
    return _auth_user_from_request(request)


def _is_board_admin(user, board):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser:
        return True

    username = user.get_username()
    if board.bo_admin and board.bo_admin == username:
        return True
    group = getattr(board, "group", None)
    return bool(group and group.gr_admin and group.gr_admin == username)


def _admin_role(user, board):
    if not user or not getattr(user, "is_authenticated", False):
        return ""
    if user.is_superuser:
        return "super"
    group = getattr(board, "group", None)
    if group and group.gr_admin == user.get_username():
        return "group"
    if board.bo_admin == user.get_username():
        return "board"
    return ""


def _can_manage_post(user, post):
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.is_superuser or post.user_id == user.id:
        return True

    if _admin_role(user, post.board) not in {"group", "board"}:
        return False

    owner_level = _user_level(post.user) if post.user_id else 1
    return _user_level(user) >= owner_level


def _require_user(request):
    user = _authenticated_user(request)
    if not user:
        return None, api_error(
            "Authentication credentials were not provided.",
            status=drf_status.HTTP_401_UNAUTHORIZED,
            code="not_authenticated",
        )
    return user, None


def _get_board(bo_table):
    board_key = BOARD_TABLE_ALIASES.get(str(bo_table), bo_table)
    lookup = Q(pk=board_key) if str(board_key).isdigit() else Q(bo_table=board_key)
    return Board.objects.select_related("group").filter(lookup).first()


def _add_unique_slug_candidate(candidates, value):
    value = str(value or "").strip().strip("/")
    if value and value not in candidates:
        candidates.append(value)


def _legacy_mojibake_slug(value):
    try:
        return value.encode("utf-8").decode("latin-1")
    except UnicodeError:
        return ""


def _slug_candidates(slug):
    candidates = []
    raw = str(slug or "").strip().strip("/")
    decoded = unquote(raw)

    for value in (raw, decoded):
        _add_unique_slug_candidate(candidates, value)
        _add_unique_slug_candidate(candidates, value.lower())
        _add_unique_slug_candidate(candidates, _legacy_mojibake_slug(value))
        _add_unique_slug_candidate(candidates, _legacy_mojibake_slug(value.lower()))

    return candidates


def _post_ordering_for_slug_match(queryset):
    return queryset.order_by("wr_parent", "pk")


def _board_payload(board):
    post_count = getattr(board, "post_count", None)
    comment_count = getattr(board, "comment_count", None)
    if post_count is None:
        post_count = board.posts.count()
    if comment_count is None:
        comment_count = board.comments.count()

    return {
        "id": board.pk,
        "bo_table": board.bo_table,
        "gr_id": board.group.gr_id if board.group_id and board.group else "",
        "group_id": board.group_id,
        "bo_subject": board.bo_subject,
        "bo_mobile_subject": board.bo_mobile_subject or "",
        "bo_device": board.bo_device,
        "bo_admin": board.bo_admin or "",
        "gr_admin": board.group.gr_admin if board.group_id and board.group else "",
        "bo_category_list": board.bo_category_list or "",
        "bo_list_level": board.bo_list_level,
        "bo_read_level": board.bo_read_level,
        "bo_write_level": board.bo_write_level,
        "bo_reply_level": board.bo_reply_level,
        "bo_comment_level": board.bo_comment_level,
        "bo_upload_level": board.bo_upload_level,
        "bo_download_level": board.bo_download_level,
        "bo_html_level": board.bo_html_level,
        "bo_link_level": board.bo_link_level,
        "bo_count_delete": board.bo_count_delete,
        "bo_count_modify": board.bo_count_modify,
        "bo_read_point": board.bo_read_point,
        "bo_write_point": board.bo_write_point,
        "bo_comment_point": board.bo_comment_point,
        "bo_download_point": board.bo_download_point,
        "bo_use_category": _bool_int(board.bo_use_category),
        "bo_use_sideview": _bool_int(board.bo_use_sideview),
        "bo_use_file_content": _bool_int(board.bo_use_file_content),
        "bo_use_secret": _bool_int(board.bo_use_secret),
        "bo_use_captcha": _bool_int(board.bo_use_captcha),
        "bo_use_dhtml_editor": _bool_int(board.bo_use_dhtml_editor),
        "bo_use_rss_view": _bool_int(board.bo_use_rss_view),
        "bo_use_good": _bool_int(board.bo_use_good),
        "bo_use_nogood": _bool_int(board.bo_use_nogood),
        "bo_use_name": _bool_int(board.bo_use_name),
        "bo_use_signature": _bool_int(board.bo_use_signature),
        "bo_use_ip_view": _bool_int(board.bo_use_ip_view),
        "bo_use_list_view": _bool_int(board.bo_use_list_view),
        "bo_use_list_file": _bool_int(board.bo_use_list_file),
        "bo_use_list_content": _bool_int(board.bo_use_list_content),
        "bo_use_email": _bool_int(board.bo_use_email),
        "bo_page_rows": board.bo_page_rows,
        "bo_mobile_page_rows": board.bo_mobile_page_rows,
        "bo_subject_len": board.bo_subject_len,
        "bo_mobile_subject_len": board.bo_mobile_subject_len,
        "bo_new": board.bo_new,
        "bo_hot": board.bo_hot,
        "bo_image_width": board.bo_image_width,
        "bo_skin": board.bo_skin,
        "bo_mobile_skin": board.bo_mobile_skin,
        "bo_content_head": board.bo_content_head or "",
        "bo_content_tail": board.bo_content_tail or "",
        "bo_mobile_content_head": board.bo_mobile_content_head or "",
        "bo_mobile_content_tail": board.bo_mobile_content_tail or "",
        "bo_gallery_cols": board.bo_gallery_cols,
        "bo_gallery_width": board.bo_gallery_width,
        "bo_gallery_height": board.bo_gallery_height,
        "bo_mobile_gallery_width": board.bo_mobile_gallery_width,
        "bo_mobile_gallery_height": board.bo_mobile_gallery_height,
        "bo_upload_size": board.bo_upload_size,
        "bo_reply_order": _bool_int(board.bo_reply_order),
        "bo_use_search": _bool_int(board.bo_use_search),
        "bo_order": board.bo_order,
        "bo_count_write": post_count,
        "bo_count_comment": comment_count,
        "bo_write_min": board.bo_write_min,
        "bo_write_max": board.bo_write_max,
        "bo_comment_min": board.bo_comment_min,
        "bo_comment_max": board.bo_comment_max,
        "bo_notice": board.bo_notice or "",
        "bo_upload_count": board.bo_upload_count,
        "bo_content": board.bo_content_head or "",
        "post_count": post_count,
        "comment_count": comment_count,
    }


def _absolute_url(request, path):
    if not path:
        return ""
    if str(path).startswith(("http://", "https://")):
        return str(path)
    return request.build_absolute_uri(path)


def _field_file_url(request, field_file):
    if not field_file:
        return ""
    try:
        if not field_file.storage.exists(field_file.name):
            return ""
        return _absolute_url(request, field_file.url)
    except (OSError, ValueError):
        return ""


def _legacy_file_url(request, post_file):
    raw_url = (post_file.bf_fileurl or "").strip()
    if not raw_url:
        return ""

    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return ""
    if parsed.scheme or parsed.netloc:
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return ""
        if parsed.netloc.casefold() != request.get_host().casefold():
            return raw_url

    clean_path = unquote(parsed.path).replace("\\", "/").lstrip("/")
    if clean_path.startswith("data/file/"):
        relative_path = clean_path[len("data/file/") :]
        path_parts = relative_path.split("/")
        if not relative_path or any(part in {"", ".", ".."} for part in path_parts):
            return ""
        for root in legacy_area_roots("file"):
            try:
                if (root / relative_path).is_file():
                    return _absolute_url(request, f"/data/file/{quote(relative_path, safe='/')}")
            except OSError:
                continue
        return ""

    if post_file.bf_storage == "legacy_missing":
        return ""
    return _absolute_url(request, raw_url)


def _file_payload(post_file, request):
    if post_file.bf_storage == "sample_static":
        file_url = post_file.bf_thumburl or post_file.bf_fileurl
    else:
        file_url = _field_file_url(request, post_file.bf_file) or _legacy_file_url(request, post_file)
    checked_url = _download_url(post_file) if file_url and post_file.bf_file else ""
    return {
        "bf_no": post_file.bf_no,
        "bo_table": post_file.board.bo_table if post_file.board_id else "",
        "wr_id": post_file.post_id,
        "bf_source": post_file.bf_source or os.path.basename(post_file.bf_file.name or ""),
        "bf_file": post_file.bf_file.name if post_file.bf_file else "",
        "bf_download": post_file.bf_download,
        "bf_content": post_file.bf_content or "",
        "bf_fileurl": post_file.bf_fileurl or "",
        "bf_thumburl": post_file.bf_thumburl or "",
        "bf_storage": post_file.bf_storage or "",
        "bf_filesize": post_file.bf_filesize,
        "bf_width": post_file.bf_width,
        "bf_height": post_file.bf_height,
        "bf_type": post_file.bf_type,
        "bf_datetime": _datetime(post_file.bf_datetime),
        "bf_url": file_url if not checked_url or post_file.bf_type else checked_url,
        "bf_download_url": checked_url or file_url,
        "bf_download_available": bool(file_url),
    }


def _download_url(post_file):
    """The checked download (level, points, count), as a site-relative API path."""
    bo_table = post_file.board.bo_table if post_file.board_id else ""
    post_id = point_ledger.post_point_id(post_file.post) if post_file.post_id else 0
    return f"/api/v1/boards/{quote(bo_table)}/{post_id}/files/{post_file.bf_no}/download"


def _member_payload_for_author(user, request):
    if not user:
        return {"mb_id": "", "mb_nick": "", "mb_icon_path": ""}
    payload = member_payload(user, request)
    return {
        "mb_id": payload.get("mb_id", ""),
        "mb_nick": payload.get("mb_nick", ""),
        "mb_icon_path": payload.get("mb_icon_path", ""),
    }


SECRET_COMMENT_CONTENT = "비밀글 입니다."


def _can_read_comment(viewer, request, comment):
    """Gnuboard5: a secret comment is shown to its author, the post's author, board admins, or a
    visitor who entered its password in this session."""
    if "secret" not in (comment.wr_option or ""):
        return True
    if viewer and (
        comment.user_id == viewer.id
        or (comment.post_id and comment.post.user_id == viewer.id)
        or (comment.board_id and _is_board_admin(viewer, comment.board))
    ):
        return True
    session = getattr(request, "session", None)
    return bool(session and session.get(f"ss_secret_comment_{comment.board_id}_{comment.pk}"))


def _comment_payload(comment, request):
    member = _member_payload_for_author(comment.user, request)
    viewer = _authenticated_user(request)
    board = comment.board
    sees_private = bool(viewer and board and (comment.user_id == viewer.id or _is_board_admin(viewer, board)))
    content = (comment.wr_content or "") if _can_read_comment(viewer, request, comment) else SECRET_COMMENT_CONTENT
    return {
        "id": comment.pk,
        "wr_id": comment.pk,
        "bo_table": comment.board.bo_table if comment.board_id else "",
        "wr_parent": comment.post_id,
        "wr_is_comment": 1,
        "wr_comment": comment.wr_comment if comment.wr_comment is not None else comment.order_num,
        "wr_comment_reply": comment.wr_comment_reply or "",
        "wr_content": content,
        "content": content,
        "wr_name": comment.wr_name or member["mb_nick"] or member["mb_id"],
        "mb_id": member["mb_id"],
        "mb_nick": member["mb_nick"],
        "member": member,
        "wr_datetime": _datetime(comment.wr_datetime),
        "wr_last": _datetime(comment.wr_last or comment.wr_datetime),
        "wr_ip": _visible_ip(comment.wr_ip, board, full=sees_private) if board else "",
        "wr_option": comment.wr_option or "",
    }


LIST_THUMBNAIL_WIDTH = 400
GUEST_LEVEL = 1


def _public_copy_allowed(board, is_secret):
    """Whether a post's pictures may get a list-size copy URL.

    A copy URL never expires and is cached publicly for a year, so it is only handed out for
    pictures any visitor may already see: not on a secret post, not on a members-only board and not
    on a board that charges points to read. Elsewhere the original (on S3, a short-lived signed URL)
    is kept.
    """
    if is_secret or board is None:
        return False
    return (board.bo_read_level or 0) <= GUEST_LEVEL and (board.bo_read_point or 0) >= 0


def _thumbnail_from_files(files, request, *, list_copy=True):
    for post_file in files:
        if post_file.bf_type > 0:
            if post_file.bf_storage == "sample_static":
                return post_file.bf_thumburl or post_file.bf_fileurl
            url = _field_file_url(request, post_file.bf_file)
            if not url or not list_copy:
                return url
            # Gallery cards and the home gallery are ~200-300px wide: send a 400px copy, not the upload.
            return thumbnail_url(url, LIST_THUMBNAIL_WIDTH, storage_path=post_file.bf_file.name)
    return ""


def _public_post_id(post):
    return post.legacy_wr_id or post.pk


def _nav_payload(post):
    if not post:
        return None
    return {
        "wr_id": _public_post_id(post),
        "wr_subject": post.wr_subject or "",
        "wr_seo_title": post.wr_slug or "",
    }


def _visible_ip(ip, board, *, full):
    ip = str(ip or "")
    if full:
        return ip
    if not ip or not board.bo_use_ip_view:
        return ""
    parts = ip.split(".")
    if len(parts) == 4:
        return f"{parts[0]}.♡.{parts[2]}.{parts[3]}"  # Gnuboard5's masking
    return ""


def _post_payload(post, request, *, detail=False, list_view=False):
    board = post.board
    viewer = _authenticated_user(request)
    member = _member_payload_for_author(post.user, request)
    is_secret = "secret" in (post.wr_option or "")
    redact_secret_list_content = list_view and is_secret
    # Gnuboard5 never hands out the author's address and shows the IP masked (bo_use_ip_view) to
    # others; administrators and the author see them in full.
    sees_private = bool(viewer and (post.user_id == viewer.id or _is_board_admin(viewer, board)))
    files = list(getattr(post, "_prefetched_objects_cache", {}).get("post_files", []))
    if not files and detail:
        files = list(post.post_files.select_related("board").order_by("bf_no", "pk"))
    comments = []
    if detail:
        prefetched_comments = getattr(post, "_prefetched_objects_cache", {}).get("comments")
        comment_qs = prefetched_comments
        if comment_qs is None:
            comment_qs = post.comments.select_related("board", "user")
        comment_qs = sorted(
            comment_qs,
            key=lambda comment: (
                comment.wr_comment if comment.wr_comment is not None else comment.order_num,
                comment.wr_comment_reply or "",
                comment.order_num,
                comment.pk,
            ),
        )
        comments = [_comment_payload(comment, request) for comment in comment_qs]

    payload = {
        "id": post.pk,
        "wr_id": _public_post_id(post),
        "bo_table": board.bo_table,
        "bo_subject": board.bo_subject,
        "wr_num": post.wr_num,
        "wr_reply": post.wr_reply,
        "wr_parent": post.wr_parent or post.pk,
        "wr_is_comment": 0,
        "wr_comment": post.wr_comment,
        "wr_comment_reply": "",
        "ca_name": post.ca_name or "",
        "wr_option": post.wr_option or "",
        "wr_subject": post.wr_subject or "",
        "wr_content": "" if list_view else post.wr_content or "",
        "content": "" if list_view else post.wr_content or "",
        "wr_seo_title": post.wr_slug or "",
        "wr_slug": post.wr_slug or "",
        "wr_link1": "" if list_view else post.wr_link1 or "",
        "wr_link2": "" if list_view else post.wr_link2 or "",
        "wr_link1_hit": post.wr_link1_hit,
        "wr_link2_hit": post.wr_link2_hit,
        "wr_hit": post.wr_hit,
        "wr_good": post.wr_good,
        "wr_nogood": post.wr_nogood,
        "wr_name": post.wr_name or member["mb_nick"] or member["mb_id"],
        "wr_email": (post.wr_email or getattr(post.user, "email", "") or "") if sees_private and not redact_secret_list_content else "",
        "wr_homepage": "" if redact_secret_list_content else post.wr_homepage or "",
        "wr_datetime": _datetime(post.wr_datetime),
        "wr_last": _datetime(post.wr_last or post.wr_datetime),
        "wr_ip": _visible_ip(post.wr_ip, board, full=sees_private and not list_view),
        "mb_id": member["mb_id"],
        "mb_nick": member["mb_nick"],
        "mb_icon_path": member["mb_icon_path"],
        "member": member,
        "thumbnail": "" if redact_secret_list_content else _thumbnail_from_files(
            files, request, list_copy=_public_copy_allowed(board, is_secret)
        ),
        "is_notice": bool(post.is_notice),
        "is_new": False,
        "is_hot": bool(post.wr_hit >= board.bo_hot > 0),
        "is_secret": is_secret,
        "bo_use_good": _bool_int(board.bo_use_good),
        "bo_use_nogood": _bool_int(board.bo_use_nogood),
        "can_manage": _can_manage_post(viewer, post),
        "admin_role": _admin_role(viewer, board),
        "is_scrapped": False,
        "scrap_id": 0,
    }

    if viewer and viewer.is_authenticated:
        scrap = Post_scrap.objects.filter(user=viewer, board=board, post=post).first()
        if scrap:
            payload["is_scrapped"] = True
            payload["scrap_id"] = scrap.pk

    if detail:
        payload["files"] = [_file_payload(post_file, request) for post_file in files]
        payload["comments"] = comments
        payload["prev_post"] = _nav_payload(
            readable_post_queryset(
                request,
                Post.objects.filter(board=board, pk__lt=post.pk).select_related("board", "user"),
            )
            .order_by("-pk")
            .first()
        )
        payload["next_post"] = _nav_payload(
            readable_post_queryset(
                request,
                Post.objects.filter(board=board, pk__gt=post.pk).select_related("board", "user"),
            )
            .order_by("pk")
            .first()
        )

    return payload


def _pagination_meta(total, page, per_page):
    last_page = (total + per_page - 1) // per_page if total else 1
    if total:
        start = (page - 1) * per_page + 1
        end = min(start + per_page - 1, total)
    else:
        start = None
        end = None
    return {
        "total": total,
        "current_page": page,
        "per_page": per_page,
        "last_page": last_page,
        "from": start,
        "to": end,
        "count": total,
        "page": page,
        "page_size": per_page,
        "total_pages": last_page,
    }


def _paginate(request, queryset, default_per_page):
    page = max(_safe_int(request.query_params.get("page"), 1), 1)
    per_page = request.query_params.get("per_page", request.query_params.get("page_size", default_per_page))
    per_page = min(max(_safe_int(per_page, default_per_page), 1), 100)
    total = queryset.count()
    start = (page - 1) * per_page
    rows = queryset[start : start + per_page] if start < total else queryset.none()
    return rows, _pagination_meta(total, page, per_page)


def _paginate_board_posts(request, posts, notices, default_per_page, notice_ids=()):
    page = max(_safe_int(request.query_params.get("page"), 1), 1)
    per_page = request.query_params.get("per_page", request.query_params.get("page_size", default_per_page))
    per_page = min(max(_safe_int(per_page, default_per_page), 1), 100)

    post_count = posts.count()
    notice_count = notices.count()
    start = (page - 1) * per_page
    ordered_notices = list(notices)
    if notice_ids:
        notice_rank = {notice_id: index for index, notice_id in enumerate(notice_ids)}
        ordered_notices.sort(
            key=lambda post: (
                notice_rank.get(_public_post_id(post), len(notice_rank)),
                post.wr_num,
                _public_post_id(post),
            )
        )

    # Gnuboard renders notices above a full page of regular posts. Notice rows
    # are excluded from the regular queryset and appear only on the pages their
    # configured notice positions cover.
    page_notices = ordered_notices[start : start + per_page]
    page_posts = list(posts[start : start + per_page]) if start < post_count else []

    total = post_count + notice_count
    meta = _pagination_meta(total, page, per_page)
    last_page = max((post_count + per_page - 1) // per_page, 1)
    meta.update(
        {
            "last_page": last_page,
            "total_pages": last_page,
            "notice_count": len(page_notices),
            "total_notice_count": notice_count,
            "from": start + 1 if total else None,
            "to": min(start + per_page, post_count) if total else None,
        }
    )
    return [*page_notices, *page_posts], meta


def _filter_posts(request, queryset):
    sca = (request.query_params.get("sca") or "").strip()
    stx = (request.query_params.get("stx") or "").strip()
    sfl = (request.query_params.get("sfl") or "wr_subject||wr_content").strip()

    if sca:
        queryset = queryset.filter(ca_name=sca)

    if stx:
        fields = {
            "wr_subject": "wr_subject__icontains",
            "wr_content": "wr_content__icontains",
            "wr_name": "wr_name__icontains",
            "mb_id": "user__username__icontains",
            "ca_name": "ca_name__icontains",
        }
        search_q = Q()
        for field in sfl.split("||"):
            lookup = fields.get(field)
            if lookup:
                search_q |= Q(**{lookup: stx})
        if not search_q:
            search_q = Q(wr_subject__icontains=stx) | Q(wr_content__icontains=stx)
        selected = set(sfl.split("||"))
        indexed_fields = [name for field, name in (("wr_subject", "title"), ("wr_content", "body")) if field in selected]
        if not selected.intersection(fields):
            indexed_fields = ["title", "body"]
        queryset = apply_text_search(queryset, stx, search_q, request=request,
                                     fields=indexed_fields if not selected.intersection({"wr_name", "mb_id", "ca_name"}) else False)

    return queryset


def _post_option(data):
    if _truthy(data.get("secret")):
        return "secret"
    html = str(data.get("html", "")).strip()
    if html == "1":
        return "html1"
    if html == "2":
        return "html2"
    return "both"


def _requests_secret(data):
    # Gnuboard5 write_update.php looks for the word "secret" in the secret, html and mail fields.
    if _post_option(data) == "secret":
        return True
    return any("secret" in str(data.get(key, "") or "").lower() for key in ("secret", "html", "mail"))


SUBJECT_MAX_LENGTH = 255  # write_update.php:31 cut_str(..., 255)
LINK_MAX_LENGTH = 1000  # write_update.php:56 substr(..., 0, 1000)


class _NotText(ValueError):
    """A form field that arrived as a JSON list, object or boolean instead of text."""

    def __init__(self, field):
        super().__init__(field)
        self.field = field


def _text_field(data, field):
    value = data.get(field)
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    raise _NotText(field)


def _clean_link(value):
    # write_update.php:54-65: trim(strip_tags(substr($link, 0, 1000)))
    return strip_tags(value[:LINK_MAX_LENGTH]).strip()


def _validation_error(message, field, code="validation_error"):
    return api_error(
        message,
        status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
        code=code,
        details={field: message},
    )


def _clean_category(data, board, is_admin):
    """write_update.php:14-28: a category from bo_category_list is required where the board uses
    categories (administrators may also pick 공지); elsewhere the category is dropped."""
    if board is None or not board.bo_use_category:
        return "", None
    ca_name = _text_field(data, "ca_name").strip()
    if not ca_name:
        return None, _validation_error("분류를 선택하세요.", "ca_name")
    category_list = (board.bo_category_list or "") + ("|공지" if is_admin else "")
    categories = [category.strip() for category in category_list.split("|")]
    if ca_name not in categories:
        return None, _validation_error("분류를 올바르게 입력하세요.", "ca_name")
    return ca_name, None


def _validate_post_payload(data, board=None, is_admin=False):
    try:
        return _validate_post_fields(data, board, is_admin)
    except _NotText as exc:
        return None, _validation_error("This field must be text.", exc.field)


def _validate_post_fields(data, board, is_admin):
    subject = _text_field(data, "wr_subject").strip()[:SUBJECT_MAX_LENGTH].strip()
    content = _text_field(data, "wr_content")
    if board is not None and not is_admin and not board.bo_use_secret and _requests_secret(data):
        return None, api_error(
            "비밀글 미사용 게시판 이므로 비밀글로 등록할 수 없습니다.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="secret_not_allowed",
        )
    if not subject:
        return None, _validation_error("Subject is required.", "wr_subject")
    if not content.strip():
        return None, _validation_error("Content is required.", "wr_content")
    ca_name, error = _clean_category(data, board, is_admin)
    if error:
        return None, error
    return {
        "ca_name": ca_name,
        "wr_subject": subject,
        "wr_content": content,
        "wr_link1": _clean_link(_text_field(data, "wr_link1")),
        "wr_link2": _clean_link(_text_field(data, "wr_link2")),
        "wr_option": _post_option(data),
    }, None


def _validate_guest_identity(data):
    name = str(data.get("wr_name") or "").strip()
    password = str(data.get("wr_password") or "")
    if not name:
        return None, api_error(
            "Name is required.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details={"wr_name": "Name is required."},
        )
    if len(name) > 255:
        return None, api_error(
            "Name is too long.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details={"wr_name": "Name must be 255 characters or fewer."},
        )
    if not password or len(password) > 128:
        return None, api_error(
            "A password of 1 to 128 characters is required.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details={"wr_password": "A password of 1 to 128 characters is required."},
        )
    return {"wr_name": name, "wr_password": get_encrypt_string(password)}, None


def _validate_guest_captcha(request, board, user, data, *, force=False):
    if user or not (force or board.bo_use_captcha):
        return None
    if _captcha_matches(request, data.get("captcha_key")):
        return None
    return api_error(
        "The anti-spam code is incorrect or expired.",
        status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
        code="captcha_invalid",
        details={"captcha_key": "The anti-spam code is incorrect or expired."},
    )


def _update_board_counts(board):
    Board.objects.filter(pk=board.pk).update(
        bo_count_write=Post.objects.filter(board=board).count(),
        bo_count_comment=Comment.objects.filter(board=board).count(),
    )


def _next_post_reply_marker(board, wr_num, parent_reply):
    """Return the next Gnuboard-style A-Z marker below a post reply."""
    parent_reply = str(parent_reply or "")
    if len(parent_reply) >= 10:
        return None

    child_letters = set()
    existing_replies = Post.objects.filter(
        board=board,
        wr_num=wr_num,
        wr_reply__startswith=parent_reply,
    ).exclude(wr_reply="").values_list("wr_reply", flat=True)
    for reply in existing_replies:
        if len(reply) > len(parent_reply):
            child_letter = reply[len(parent_reply)]
            if "A" <= child_letter <= "Z":
                child_letters.add(child_letter)

    if board.bo_reply_order:
        next_codepoint = ord(max(child_letters)) + 1 if child_letters else ord("A")
        if next_codepoint > ord("Z"):
            return None
    else:
        next_codepoint = ord(min(child_letters)) - 1 if child_letters else ord("Z")
        if next_codepoint < ord("A"):
            return None

    return parent_reply + chr(next_codepoint)


def _update_post_comment_count(post):
    count = Comment.objects.filter(post=post).count()
    Post.objects.filter(pk=post.pk).update(wr_comment=count)
    return count


def _related_count(rows):
    """Number of `rows` (already filtered to OuterRef("pk")) as an annotation; 0 when there are none."""
    counted = rows.order_by().values("board").annotate(total=Count("pk")).values("total")
    return Coalesce(Subquery(counted, output_field=IntegerField()), 0)


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def board_list_view(request):
    return board_list_response(request)


def board_list_response(request):
    # One counting subquery per table (_related_count). Counting both relations in one join multiplied every board's
    # posts by its comments before DISTINCT (2.2 s for 5,600 posts) and stalled the other home requests.
    queryset = (
        Board.objects.select_related("group")
        .annotate(
            post_count=_related_count(Post.objects.filter(board=OuterRef("pk"))),
            comment_count=_related_count(Comment.objects.filter(board=OuterRef("pk"))),
        )
        .order_by("bo_order", "pk")
    )
    group = (request.query_params.get("group") or "").strip()
    if group:
        queryset = queryset.filter(Q(group__gr_id=group) | Q(group_id=_safe_int(group, 0)))
    return api_response(data=[_board_payload(board) for board in queryset])


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def board_detail_view(request, bo_table):
    board = _get_board(bo_table)
    if not board:
        return api_error("Board not found.", status=drf_status.HTTP_404_NOT_FOUND, code="board_not_found")
    return api_response(data=_board_payload(board))


POST_EXCERPT_LENGTH = 70
_EXCERPT_BREAK_RE = re.compile(r"<(br\s*/?|/p|/div|/li|/h[1-6])>", re.IGNORECASE)
_EXCERPT_MEDIA_TOKEN_RE = re.compile(r"\{(이미지|동영상)\s*:\s*\d+\}")


def _plain_post_text(content):
    """A post body as one line of readable text: tags and media tokens removed, entities decoded."""
    text = _EXCERPT_BREAK_RE.sub(" ", content or "")
    text = _EXCERPT_MEDIA_TOKEN_RE.sub(" ", text)
    return " ".join(html.unescape(strip_tags(text)).split())


def _post_excerpt(content, length=POST_EXCERPT_LENGTH):
    """Two-line plain-text excerpt for gallery cards: tags stripped, line breaks kept as spaces."""
    text = _plain_post_text(content)
    return f"{text[:length]}…" if len(text) > length else text


def _excerpt_post_ids(request, board, posts):
    """Ids of listed posts whose text the viewer may already read.

    Listing a board does not grant reading it, so an excerpt needs read access (secret posts
    included). On a board that charges read points, only the author and members who already
    paid for that post see it, so the excerpt never gives away text the reader has not paid for.
    """
    ids = [post.pk for post in posts]
    if not ids:
        return set()
    readable = set(readable_post_queryset(request, Post.objects.filter(pk__in=ids)).values_list("pk", flat=True))
    if board.bo_read_point >= 0 or not point_ledger.points_enabled():
        return readable
    user = _authenticated_user(request)
    if not user:
        return set()
    if gnu_is_admin(user):
        # The super administrator reads every post without paying.
        return readable
    return {
        post.pk
        for post in posts
        if post.pk in readable
        and (
            post.user_id == user.id
            or point_ledger.has_point_row(user, board.bo_table, point_ledger.post_point_id(post), "읽기")
        )
    }


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def board_category_counts_view(request, bo_table):
    """Posts per category for a board list's category chips; counts is null with a reason when skipped."""
    board = _get_board(bo_table)
    if not board:
        return api_error("Board not found.", status=drf_status.HTTP_404_NOT_FOUND, code="board_not_found")
    user = _authenticated_user(request)
    if (get_user_level(user) if user else 1) < board.bo_list_level and not _is_board_admin(user, board):
        return api_error(
            "You do not have permission to list this board.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="board_list_forbidden",
        )
    if not board.bo_use_category:
        return api_response(data={"counts": None, "reason": "no_category"})
    if not settings.BOARD_CATEGORY_COUNTS:
        return api_response(data={"counts": None, "reason": "disabled"})
    max_posts = settings.BOARD_CATEGORY_COUNTS_MAX_POSTS
    if max_posts > 0 and (board.bo_count_write or 0) > max_posts:
        return api_response(data={"counts": None, "reason": "too_many_posts"})

    cache_key = f"board-category-counts:{board.bo_table}"
    counts = cache.get(cache_key)
    if counts is None:
        rows = (
            Post.objects.filter(board=board)
            .exclude(ca_name__isnull=True)
            .exclude(ca_name="")
            .values("ca_name")
            .annotate(total=Count("pk"))
        )
        counts = {row["ca_name"]: row["total"] for row in rows}
        cache.set(cache_key, counts, 300)
    return api_response(data={"counts": counts, "reason": None})


def board_posts_response(request, bo_table):
    board = _get_board(bo_table)
    if not board:
        return api_error("Board not found.", status=drf_status.HTTP_404_NOT_FOUND, code="board_not_found")

    queryset = listable_post_queryset(
        request,
        Post.objects.filter(board=board).select_related("board", "user").prefetch_related("post_files"),
    )
    ordered_queryset = queryset.order_by(
        "-is_notice",
        "wr_num",
        Case(
            When(wr_reply="", then=0),
            default=1,
            output_field=IntegerField(),
        ),
        "wr_reply",
        "wr_parent",
    )
    list_filter_active = bool(
        (request.query_params.get("sca") or "").strip()
        or (request.query_params.get("stx") or "").strip()
    )
    if list_filter_active:
        posts = _filter_posts(request, ordered_queryset.filter(is_notice=False))
        notices = ordered_queryset.none()
    else:
        posts = _filter_posts(request, ordered_queryset.filter(is_notice=False))
        notices = ordered_queryset.filter(is_notice=True)

    notice_ids = []
    for value in (board.bo_notice or "").replace("\n", ",").split(","):
        notice_id = _safe_int(value.strip(), -1)
        if notice_id >= 0:
            notice_ids.append(notice_id)
    page_posts, meta = _paginate_board_posts(
        request,
        posts,
        notices,
        board.bo_page_rows or 20,
        notice_ids,
    )
    rows = [_post_payload(post, request, list_view=True) for post in page_posts]
    wants_excerpt = "excerpt" in {part.strip() for part in (request.query_params.get("with") or "").split(",")}
    if wants_excerpt:
        allowed = _excerpt_post_ids(request, board, page_posts)
        for post, row in zip(page_posts, rows):
            # 비밀글은 읽을 수 있는 사람에게도 카드에 본문을 내지 않는다(자물쇠 표시 · 사이트 검색과 같다).
            if post.pk in allowed and not row["is_secret"]:
                row["wr_excerpt"] = _post_excerpt(post.wr_content)
    return api_response(data=rows, meta=meta)
@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def board_posts_view(request, bo_table):
    if request.method == "GET":
        return board_posts_response(request, bo_table)

    board = _get_board(bo_table)
    if not board:
        return api_error("Board not found.", status=drf_status.HTTP_404_NOT_FOUND, code="board_not_found")

    user = _authenticated_user(request)
    data = _request_data(request)
    reply_to = _safe_int(data.get("reply_to"), 0)
    is_reply = reply_to > 0
    is_admin = _is_board_admin(user, board)
    error = _check_write_cost(
        user, board, board.bo_comment_point if is_reply else board.bo_write_point, "글답변" if is_reply else "글쓰기"
    )
    if error:
        return error
    if is_reply:
        if _user_level(user) < board.bo_reply_level and not is_admin:
            return api_error(
                "답글을 작성할 권한이 없습니다.",
                status=drf_status.HTTP_403_FORBIDDEN,
                code="reply_forbidden",
            )
        parent_board, parent = _get_post_for_board(request, bo_table, reply_to)
        if not parent_board or not parent:
            return api_error(
                "원글을 찾을 수 없습니다.",
                status=drf_status.HTTP_404_NOT_FOUND,
                code="reply_parent_not_found",
            )
        if parent.is_notice:
            return api_error(
                "공지에는 답글을 작성할 수 없습니다.",
                status=drf_status.HTTP_403_FORBIDDEN,
                code="reply_to_notice_forbidden",
            )
    elif _user_level(user) < board.bo_write_level and not is_admin:
        return api_error(
            "글을 작성할 권한이 없습니다.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="write_forbidden",
        )

    payload, error = _validate_post_payload(data, board, is_admin)
    if error:
        return error
    if not user:
        identity, error = _validate_guest_identity(data)
        if error:
            return error
        payload.update(identity)
    error = _validate_guest_captcha(request, board, user, data)
    if error:
        return error

    now = timezone.now()
    with transaction.atomic():
        if is_reply:
            thread_id = parent.wr_parent or parent.pk
            root_queryset = Post.objects.select_for_update().filter(
                board=board,
                wr_reply="",
            )
            root = root_queryset.filter(wr_parent=thread_id).order_by("pk").first()
            if not root:
                root = root_queryset.filter(pk=thread_id).first()
            if not root:
                return api_error(
                    "원글을 찾을 수 없습니다.",
                    status=drf_status.HTTP_404_NOT_FOUND,
                    code="reply_parent_not_found",
                )

            # Lock the thread root before allocating a marker so replies to
            # different branches of the same thread cannot claim the same slot.
            parent_board, parent = _get_post_for_board(
                request, bo_table, reply_to, for_update=True
            )
            if not parent_board or not parent:
                return api_error(
                    "원글을 찾을 수 없습니다.",
                    status=drf_status.HTTP_404_NOT_FOUND,
                    code="reply_parent_not_found",
                )
            thread_id = parent.wr_parent or parent.pk
            if parent.is_notice:
                return api_error(
                    "공지에는 답글을 작성할 수 없습니다.",
                    status=drf_status.HTTP_403_FORBIDDEN,
                    code="reply_to_notice_forbidden",
                )
            if "secret" in (parent.wr_option or ""):
                payload["wr_option"] = "secret"

            reply_marker = _next_post_reply_marker(board, parent.wr_num, parent.wr_reply)
            if reply_marker is None:
                return api_error(
                    "답글 단계당 최대 26개, 최대 깊이 10단계까지만 작성할 수 있습니다.",
                    status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                    code="reply_limit_reached",
                )
            post = Post.objects.create(
                board=board,
                wr_num=parent.wr_num,
                wr_reply=reply_marker,
                wr_parent=thread_id,
                ca_name=payload["ca_name"],
                wr_option=payload["wr_option"],
                wr_subject=payload["wr_subject"],
                wr_content=payload["wr_content"],
                wr_link1=payload["wr_link1"],
                wr_link2=payload["wr_link2"],
                user=user,
                wr_password=payload.get("wr_password", ""),
                wr_name=payload.get("wr_name") or _member_name(user),
                wr_email=(user.email or "") if user else "",
                wr_datetime=now,
                wr_last=now,
                wr_ip=get_client_ip(request) or "",
            )
        else:
            post = Post.objects.create(
                board=board,
                wr_num=get_next_num(board_id=board.pk),
                wr_parent=0,
                ca_name=payload["ca_name"],
                wr_option=payload["wr_option"],
                wr_subject=payload["wr_subject"],
                wr_content=payload["wr_content"],
                wr_link1=payload["wr_link1"],
                wr_link2=payload["wr_link2"],
                user=user,
                wr_password=payload.get("wr_password", ""),
                wr_name=payload.get("wr_name") or _member_name(user),
                wr_email=(user.email or "") if user else "",
                wr_datetime=now,
                wr_last=now,
                wr_ip=get_client_ip(request) or "",
            )
            post.wr_parent = post.pk
            post.save(update_fields=["wr_parent"])
        point_id = point_ledger.post_point_id(post)
        if is_reply:
            point_ledger.insert_point(user, board.bo_comment_point, f"{board.bo_subject} {point_id} 글답변", board.bo_table, point_id, "쓰기")
        else:
            point_ledger.insert_point(user, board.bo_write_point, f"{board.bo_subject} {point_id} 글쓰기", board.bo_table, point_id, "쓰기")
        _update_board_counts(board)
        if not user and board.bo_use_captcha:
            _consume_captcha(request)

    _remember_secret_unlock(request, post)
    return api_response(data=_post_payload(post, request, detail=True), status=drf_status.HTTP_201_CREATED)


def _remember_secret_unlock(request, post):
    """write_update.php:705-712: the writer of a secret post is not asked for its password again."""
    if "secret" in (post.wr_option or ""):
        request.session[secret_post_session_key(post)] = True


def _point_shortage_error(balance, cost, action, user):
    message = (
        f"보유하신 포인트({balance:,})가 없거나 모자라서 {action}({cost:,})가 불가합니다."
        if user
        else f"{action} 권한이 없습니다. 회원이시라면 로그인 후 이용해 보십시오."
    )
    return api_error(message, status=drf_status.HTTP_403_FORBIDDEN, code="insufficient_points")


def _check_write_cost(user, board, cost, action):
    """Gnuboard5 refuses a post or comment whose (negative) points the member cannot pay."""
    if not user or cost >= 0 or _is_board_admin(user, board) or not point_ledger.points_enabled():
        return None
    balance = point_ledger.point_balance(user)
    if balance + cost < 0:
        return _point_shortage_error(balance, cost, action, user)
    return None


def _charge_point_once(request, board, post, *, cost, action, rel_action, content, exempt_admin):
    """Charge (or grant) a post's read/download points once per member, as Gnuboard5 does.

    The author is never charged; board administrators skip download points (board.php charges
    them for reading, download.php does not). A charge the balance cannot cover is refused.
    Returns an error response or None.
    """
    if not cost or not point_ledger.points_enabled():
        return None
    user = _authenticated_user(request)
    if user and (post.user_id == user.id or (exempt_admin and _is_board_admin(user, board))):
        return None
    if not user:
        return _point_shortage_error(0, cost, action, None) if cost < 0 else None
    point_id = point_ledger.post_point_id(post)
    if point_ledger.has_point_row(user, board.bo_table, point_id, rel_action):
        return None
    balance = point_ledger.point_balance(user)
    if balance + cost < 0:
        return _point_shortage_error(balance, cost, action, user)
    result = point_ledger.insert_point(user, cost, content, board.bo_table, point_id, rel_action, require_balance=True)
    if result == point_ledger.INSUFFICIENT:
        return _point_shortage_error(point_ledger.point_balance(user), cost, action, user)
    return None


def _charge_read_points(request, board, post):
    user = _authenticated_user(request)
    if (
        not user
        and not post.user_id
        and board.bo_read_level <= 1
        and post.wr_ip
        and post.wr_ip == (get_client_ip(request) or "")
    ):
        # A visitor reading their own guest post (same IP) is not charged, as in Gnuboard5.
        return None
    return _charge_point_once(
        request, board, post,
        cost=board.bo_read_point, action="글읽기", rel_action="읽기",
        content=f"{board.bo_subject} {point_ledger.post_point_id(post)} 글읽기",
        exempt_admin=False,
    )


def _read_post_response(request, board, post):
    """A post's detail for a reader: read points first, then the hit (once per session)."""
    error = _charge_read_points(request, board, post)
    if error:
        return error
    viewed_key = f"ss_view_{board.bo_table}_{post.pk}"
    if not request.session.get(viewed_key):
        # Gnuboard5 counts a read once per browser session.
        Post.objects.filter(pk=post.pk).update(wr_hit=F("wr_hit") + 1)
        post.refresh_from_db(fields=["wr_hit"])
        request.session[viewed_key] = True
    return api_response(data=_post_payload(post, request, detail=True))


def _get_post_for_board(request, bo_table, wr_id=None, slug=None, *, for_update=False, include_guest_posts=False):
    board = _get_board(bo_table)
    if not board:
        return None, None

    queryset = Post.objects.select_related("board", "board__group", "user").prefetch_related("post_files", "comments")
    if for_update:
        # lock only the post row: PostgreSQL refuses FOR UPDATE on the outer-joined user/group
        queryset = queryset.select_for_update(of=("self",))
    if include_guest_posts:
        # A visitor proves a guest post is theirs with its password (delete.php:33-37), secret or not.
        readable_ids = readable_post_queryset(request, Post.objects.filter(board=board)).values("pk")
        queryset = queryset.filter(board=board).filter(Q(pk__in=readable_ids) | Q(user__isnull=True))
    else:
        queryset = readable_post_queryset(request, queryset.filter(board=board))
    if slug is not None:
        candidates = _slug_candidates(slug)
        exact_query = Q()
        prefix_query = Q()
        for candidate in candidates:
            exact_query |= Q(wr_slug__iexact=candidate)
            if len(candidate) >= 3:
                prefix_query |= Q(wr_slug__istartswith=candidate)

        if exact_query:
            post = _post_ordering_for_slug_match(queryset.filter(exact_query)).first()
            if post:
                return board, post

        if prefix_query:
            post = _post_ordering_for_slug_match(queryset.filter(prefix_query)).first()
            if post:
                return board, post

        return board, None
    post = queryset.filter(legacy_wr_id=wr_id).first()
    if post:
        return board, post

    # Top-level URLs from databases imported before legacy_wr_id was available
    # can still resolve through wr_parent. New Django rows resolve by their PK.
    post = queryset.filter(pk=wr_id).first()
    if post:
        return board, post
    root = queryset.filter(wr_parent=wr_id, wr_reply="").order_by("pk").first()
    if root:
        return board, root
    return board, None


@api_view(["GET", "PATCH", "DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def post_detail_view(request, bo_table, wr_id):
    if request.method == "GET":
        board, post = _get_post_for_board(request, bo_table, wr_id)
        if not board or not post:
            return api_error("Post not found.", status=drf_status.HTTP_404_NOT_FOUND, code="post_not_found")
        return _read_post_response(request, board, post)

    user = _authenticated_user(request)
    data = _request_data(request)
    guest_password = "" if user else str(data.get("wr_password") or "")
    if not user and not guest_password:
        _, error = _require_user(request)
        return error
    if guest_password and not GuestPasswordThrottle().allow_request(request, None):
        return api_error("잠시 후 다시 시도해 주세요.", status=drf_status.HTTP_429_TOO_MANY_REQUESTS, code="throttled")

    with transaction.atomic():
        board, post = _get_post_for_board(request, bo_table, wr_id, for_update=True, include_guest_posts=not user)
        if not board or not post:
            return api_error("Post not found.", status=drf_status.HTTP_404_NOT_FOUND, code="post_not_found")
        error = _post_manage_error(user, guest_password, post, deleting=request.method == "DELETE")
        if error:
            return error

        if request.method == "DELETE":
            return _delete_post(user, board, post, wr_id)

        error = _post_edit_rule_error(user, board, post)
        if error:
            return error
        payload, error = _validate_post_payload(data, board, _is_board_admin(user, board))
        if error:
            return error
        for field, value in payload.items():
            setattr(post, field, value)
        post.wr_last = timezone.now()
        post.wr_ip = get_client_ip(request) or post.wr_ip
        post.save()

    _remember_secret_unlock(request, post)
    return api_response(data=_post_payload(post, request, detail=True))


class GuestPasswordThrottle(SimpleRateThrottle):
    """Limits how often a visitor may try a guest post's password (edit or delete), per address."""

    scope = "guest-password"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


def _post_manage_error(user, guest_password, post, *, deleting):
    """delete.php:16-37 / write.php:63-74: members manage what _can_manage_post allows; a visitor
    manages their own guest post with its password."""
    if user:
        if not _can_manage_post(user, post):
            return api_error("You do not have permission to manage this post.", status=drf_status.HTTP_403_FORBIDDEN)
        return None
    if post.user_id:
        return api_error(
            "로그인 후 삭제하세요." if deleting else "로그인 후 수정하세요.",
            status=drf_status.HTTP_401_UNAUTHORIZED,
            code="not_authenticated",
        )
    if not post.wr_password or not check_password(guest_password, post.wr_password):
        return api_error(
            "비밀번호가 틀리므로 삭제할 수 없습니다." if deleting else "비밀번호가 틀리므로 수정할 수 없습니다.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="password_mismatch",
        )
    return None


def _comments_by_others(post, user):
    """Comments on the post not written by this member (guest comments count for members)."""
    comments = Comment.objects.filter(post=post)
    if user:
        return comments.exclude(user=user).count()
    return comments.filter(user__isnull=False).count()


def _post_edit_rule_error(user, board, post):
    """write.php:76-97: without administrator rights a post with replies, or with bo_count_modify
    comments by others, cannot be edited."""
    if _is_board_admin(user, board):
        return None
    if Delete_all_posts().get_descendants(post, board):
        return api_error(
            "이 글과 관련된 답변글이 존재하므로 수정 할 수 없습니다.\n\n답변글이 있는 원글은 수정할 수 없습니다.",
            status=drf_status.HTTP_409_CONFLICT,
            code="post_has_replies",
        )
    limit = board.bo_count_modify
    if limit and _comments_by_others(post, user) >= limit:
        return api_error(
            f"이 글과 관련된 댓글이 존재하므로 수정 할 수 없습니다.\n\n댓글이 {limit}건 이상 달린 원글은 수정할 수 없습니다.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="post_has_comments",
        )
    return None


def _delete_post(user, board, post, wr_id):
    """delete.php: replies first (administrators excepted), then the bo_count_delete rule."""
    is_admin = _is_board_admin(user, board)
    deletion = Delete_all_posts()
    descendants = deletion.get_descendants(post, board)
    if descendants and not is_admin:
        return api_error(
            "Delete the replies before deleting the original post.",
            status=drf_status.HTTP_409_CONFLICT,
            code="post_has_replies",
        )
    if descendants and any(not _can_manage_post(user, reply) for reply in descendants):
        return api_error(
            "You do not have permission to delete one or more replies.",
            status=drf_status.HTTP_403_FORBIDDEN,
        )
    # Gnuboard5 compares even a zero bo_count_delete; here 0 means the rule is off, as for
    # bo_count_modify, so boards created with the default stay deletable.
    limit = board.bo_count_delete
    if limit and not is_admin and _comments_by_others(post, user) >= limit:
        return api_error(
            f"이 글과 관련된 코멘트가 존재하므로 삭제 할 수 없습니다.\n\n코멘트가 {limit}건 이상 달린 원글은 삭제할 수 없습니다.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="post_has_comments",
        )

    deleted_ids = [_public_post_id(post), *[_public_post_id(reply) for reply in descendants]]
    deletion.check_delete(post, board, descendants=descendants)
    deletion.etc_check(post, board)
    post.delete()
    _update_board_counts(board)
    return api_response(data={"deleted": True, "wr_id": wr_id, "deleted_ids": deleted_ids})


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def post_by_seo_view(request, bo_table, slug):
    board, post = _get_post_for_board(request, bo_table, slug=slug)
    if not board or not post:
        return api_error("Post not found.", status=drf_status.HTTP_404_NOT_FOUND, code="post_not_found")
    return _read_post_response(request, board, post)


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def post_vote_view(request, bo_table, wr_id, vote_type):
    board, post = _get_post_for_board(request, bo_table, wr_id)
    if not board or not post:
        return api_error("Post not found.", status=drf_status.HTTP_404_NOT_FOUND, code="post_not_found")
    if vote_type not in {"good", "nogood"}:
        return api_error("Invalid vote type.", status=drf_status.HTTP_404_NOT_FOUND, code="invalid_vote_type")

    # good.php:21-24, 45-48: members only, and never on their own post.
    user = _authenticated_user(request)
    if not user:
        return api_error("회원만 가능합니다.", status=drf_status.HTTP_401_UNAUTHORIZED, code="not_authenticated")
    if post.user_id and post.user_id == user.id:
        return api_error(
            "자신의 글에는 추천 또는 비추천 하실 수 없습니다.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="vote_own_post",
        )

    if vote_type == "good" and not board.bo_use_good:
        return api_error("Good vote is disabled.", status=drf_status.HTTP_403_FORBIDDEN)
    if vote_type == "nogood" and not board.bo_use_nogood:
        return api_error("No-good vote is disabled.", status=drf_status.HTTP_403_FORBIDDEN)

    # good.php:56-70: one vote per member and post, either kind
    with transaction.atomic():
        vote, created = Post_good.objects.get_or_create(
            post=post, user=user, defaults={"board": board, "bg_flag": vote_type}
        )
        if not created:
            label = "추천" if vote.bg_flag == "good" else "비추천"
            message = f"이미 {label} 하신 글 입니다." if vote.bg_flag == vote_type else "이미 추천 또는 비추천 하신 글 입니다."
            return api_error(message, status=drf_status.HTTP_403_FORBIDDEN, code="already_voted")
        if vote_type == "good":
            Post.objects.filter(pk=post.pk).update(wr_good=F("wr_good") + 1)
        else:
            Post.objects.filter(pk=post.pk).update(wr_nogood=F("wr_nogood") + 1)

    post.refresh_from_db(fields=["wr_good", "wr_nogood"])
    return api_response(data={"flag": vote_type, "wr_good": post.wr_good, "wr_nogood": post.wr_nogood})


@api_view(["POST", "DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def comment_view(request, bo_table, item_id):
    user = _authenticated_user(request)

    if request.method == "DELETE":
        if not user:
            _, error = _require_user(request)
            return error
        board = _get_board(bo_table)
        if not board:
            return api_error("Board not found.", status=drf_status.HTTP_404_NOT_FOUND, code="board_not_found")
        comment = Comment.objects.select_related("board", "post", "user").filter(pk=item_id, board=board).first()
        if not comment:
            return api_error("Comment not found.", status=drf_status.HTTP_404_NOT_FOUND, code="comment_not_found")
        error = _comment_delete_error(user, comment)
        if error:
            return error
        post = comment.post
        board = comment.board
        with transaction.atomic():
            point_ledger.delete_point(comment.user, board.bo_table, comment.pk, "댓글")
            comment.delete()
        _update_post_comment_count(post)
        _update_board_counts(board)
        return api_response(data={"deleted": True, "wr_id": item_id})

    board, post = _get_post_for_board(request, bo_table, item_id)
    if not board or not post:
        return api_error("Post not found.", status=drf_status.HTTP_404_NOT_FOUND, code="post_not_found")
    if _user_level(user) < board.bo_comment_level and not _is_board_admin(user, board):
        return api_error("You do not have permission to comment on this board.", status=drf_status.HTTP_403_FORBIDDEN)

    data = _request_data(request)
    content = str(data.get("wr_content") or "").strip()
    if not content:
        return api_error(
            "Comment content is required.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details={"wr_content": "Comment content is required."},
        )
    guest_identity = {}
    if not user:
        guest_identity, error = _validate_guest_identity(data)
        if error:
            return error
    error = _validate_guest_captcha(request, board, user, data, force=True)
    if error:
        return error

    parent_id = _safe_int(data.get("comment_id"), 0)
    parent = None
    if parent_id:
        parent = Comment.objects.filter(pk=parent_id, post=post).first()
        if not parent:
            return api_error("Parent comment not found.", status=drf_status.HTTP_404_NOT_FOUND, code="comment_not_found")

    error = _check_write_cost(user, board, board.bo_comment_point, "댓글쓰기")
    if error:
        return error
    with transaction.atomic():
        # Lock the post so two comments cannot take the same group number or reply marker.
        Post.objects.select_for_update().filter(pk=post.pk).first()
        reply_marker = ""
        if parent:
            reply_marker, error = _next_comment_reply_marker(board, post, parent)
            if error:
                return error
        comment = _create_comment_with_points(board, post, user, parent, reply_marker, content, guest_identity, request)
    _update_post_comment_count(post)
    _update_board_counts(board)
    if not user:
        _consume_captcha(request)
    return api_response(data=_comment_payload(comment, request), status=drf_status.HTTP_201_CREATED)


COMMENT_REPLY_MAX_DEPTH = 5  # write_comment_update.php:84


def _comment_group(comment):
    return comment.wr_comment if comment.wr_comment is not None else comment.order_num


def _comment_group_filter(group):
    return Q(wr_comment=group) | Q(wr_comment__isnull=True, order_num=group)


def _next_comment_reply_marker(board, post, parent):
    """write_comment_update.php:110-150: each reply to a comment takes the next free letter below it
    (A upwards with bo_reply_order, otherwise Z downwards), five levels and 26 siblings at most."""
    parent_reply = parent.wr_comment_reply or ""
    if len(parent_reply) >= COMMENT_REPLY_MAX_DEPTH:
        return None, _validation_error(
            "더 이상 답변하실 수 없습니다.\n\n답변은 5단계 까지만 가능합니다.", "comment_id", code="comment_reply_too_deep"
        )
    siblings = (
        Comment.objects.filter(post=post, wr_comment=_comment_group(parent), wr_comment_reply__startswith=parent_reply)
        .exclude(pk=parent.pk)
        .values_list("wr_comment_reply", flat=True)
    )
    letters = {reply[len(parent_reply)] for reply in siblings if reply and len(reply) > len(parent_reply)}
    letters = {letter for letter in letters if "A" <= letter <= "Z"}
    if board.bo_reply_order:
        first, last, step, current = "A", "Z", 1, max(letters, default="")
    else:
        first, last, step, current = "Z", "A", -1, min(letters, default="")
    if not current:
        return parent_reply + first, None
    if current == last:
        return None, _validation_error(
            "더 이상 답변하실 수 없습니다.\n\n답변은 26개 까지만 가능합니다.", "comment_id", code="comment_reply_limit"
        )
    return parent_reply + chr(ord(current) + step), None


def _comment_delete_error(user, comment):
    """delete_comment.php:22-66: a board or group administrator cannot delete a comment of a member
    above their level; without administrator rights only one's own comment without replies goes."""
    role = _admin_role(user, comment.board)
    if role in {"group", "board"} and comment.user_id and _user_level(user) < _user_level(comment.user):
        manager = "그룹관리자" if role == "group" else "게시판관리자"
        return api_error(
            f"{manager}의 권한보다 높은 회원의 코멘트이므로 삭제할 수 없습니다.",
            status=drf_status.HTTP_403_FORBIDDEN,
            code="comment_delete_forbidden",
        )
    if role:
        return None
    if comment.user_id != user.id:
        return api_error("You do not have permission to delete this comment.", status=drf_status.HTTP_403_FORBIDDEN)
    reply = comment.wr_comment_reply or ""
    has_replies = (
        Comment.objects.filter(post_id=comment.post_id, wr_comment_reply__startswith=reply)
        .filter(_comment_group_filter(_comment_group(comment)))
        .exclude(pk=comment.pk)
        .exclude(wr_comment_reply=reply)
        .exists()
    )
    if has_replies:
        return api_error(
            "이 코멘트와 관련된 답변코멘트가 존재하므로 삭제 할 수 없습니다.",
            status=drf_status.HTTP_409_CONFLICT,
            code="comment_has_replies",
        )
    return None


def _create_comment_with_points(board, post, user, parent, reply_marker, content, guest_identity, request):
    comment = Comment.objects.create(
        board=board,
        post=post,
        user=user,
        parent=parent.pk if parent else 0,
        wr_comment_reply=reply_marker,
        wr_option="html1" if "<" in content and ">" in content else "both",
        wr_content=content,
        wr_password=guest_identity.get("wr_password", ""),
        wr_name=guest_identity.get("wr_name") or _member_name(user),
        wr_email=(user.email or "") if user else "",
        wr_datetime=timezone.now(),
        wr_last=timezone.now(),
        wr_ip=get_client_ip(request) or "",
    )
    point_ledger.insert_point(
        user, board.bo_comment_point,
        f"{board.bo_subject} {point_ledger.post_point_id(post)}-{comment.pk} 댓글쓰기",
        board.bo_table, comment.pk, "댓글",
    )
    return comment


def _upload_files_from_request(request):
    files = request.FILES.getlist("files[]")
    if not files:
        files = request.FILES.getlist("files")
    if not files and request.FILES:
        files = [value for _, value in request.FILES.items()]
    return files


def _save_post_file(board, post, uploaded_file, bf_no):
    post_file = Post_file(
        board=board,
        post=post,
        bf_no=bf_no,
        bf_source=uploaded_file.name,
        bf_datetime=timezone.now(),
    )
    post_file.bf_file = strip_image_metadata(uploaded_file)
    post_file.full_clean(exclude=["board", "post"])
    post_file.save()
    return post_file


def _attachment_count_after(post, orders, uploaded_files):
    """How many attachments the post would have: every uploaded file plus the kept ones the order
    list names (write_update.php:476-490 counts the uploaded files themselves)."""
    existing_numbers = set(Post_file.objects.filter(post_id=post.pk).values_list("bf_no", flat=True))
    kept = {_safe_int(order, -1) for order in orders if not str(order).startswith("new:")}
    return max(len(uploaded_files) + len(kept & existing_numbers), len(orders))


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([MultiPartParser, FormParser, JSONParser])
def post_files_view(request, bo_table, wr_id):
    board, post = _get_post_for_board(request, bo_table, wr_id)
    if not board or not post:
        return api_error("Post not found.", status=drf_status.HTTP_404_NOT_FOUND, code="post_not_found")

    if request.method == "GET":
        files = post.post_files.select_related("board").order_by("bf_no", "pk")
        return api_response(data=[_file_payload(post_file, request) for post_file in files])

    user, error = _require_user(request)
    if error:
        return error
    if not _can_manage_post(user, post):
        return api_error("You do not have permission to manage files for this post.", status=drf_status.HTTP_403_FORBIDDEN)
    if _user_level(user) < board.bo_upload_level and not _is_board_admin(user, board):
        return api_error("You do not have permission to upload files to this board.", status=drf_status.HTTP_403_FORBIDDEN)

    uploaded_files = _upload_files_from_request(request)
    if hasattr(request.data, "getlist"):
        orders = request.data.getlist("order[]")
    elif isinstance(request.data, dict):
        orders = request.data.get("order[]", [])
    else:
        return api_error(
            "Invalid attachment order.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="invalid_attachment_order",
        )
    if isinstance(orders, str):
        orders = [orders]
    if not isinstance(orders, (list, tuple)) or any(
        isinstance(order, bool) or not isinstance(order, (str, int)) for order in orders
    ):
        return api_error(
            "Invalid attachment order.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="invalid_attachment_order",
        )

    if board.bo_upload_count and _attachment_count_after(post, orders, uploaded_files) > board.bo_upload_count:
        return api_error("Too many attached files.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY)
    for uploaded_file in uploaded_files:
        if board.bo_upload_size and uploaded_file.size > board.bo_upload_size:
            return api_error(
                "Attached file is too large.",
                status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
                details={"files": "Attached file is too large."},
            )

    existing = {item.bf_no: item for item in post.post_files.select_related("board").order_by("bf_no", "pk")}
    kept_pks = set()
    new_files = list(uploaded_files)
    created = []

    try:
        with transaction.atomic():
            if not orders and not uploaded_files:
                post.post_files.all().delete()
            else:
                slot = 0
                for order in orders:
                    if str(order).startswith("new:"):
                        index = _safe_int(str(order).split(":", 1)[1], -1)
                        if 0 <= index < len(new_files):
                            created_file = _save_post_file(board, post, new_files[index], slot)
                            created.append(created_file)
                            kept_pks.add(created_file.pk)
                            slot += 1
                        continue

                    existing_no = _safe_int(order, -1)
                    post_file = existing.get(existing_no)
                    if post_file:
                        if post_file.bf_no != slot:
                            post_file.bf_no = slot
                            post_file.save(update_fields=["bf_no"])
                        kept_pks.add(post_file.pk)
                        slot += 1

                for index, uploaded_file in enumerate(new_files):
                    marker = "new:%s" % index
                    if marker in orders:
                        continue
                    created_file = _save_post_file(board, post, uploaded_file, slot)
                    created.append(created_file)
                    kept_pks.add(created_file.pk)
                    slot += 1

                post.post_files.exclude(pk__in=kept_pks).delete()

            # Count from the table: post.post_files may still hold the prefetched rows.
            file_count = Post_file.objects.filter(post_id=post.pk).count()
            Post.objects.filter(pk=post.pk).update(wr_file=file_count)
            post.wr_file = file_count
    except DjangoValidationError as exc:
        return api_error(
            "File validation failed.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details={"files": "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)},
        )

    files = post.post_files.select_related("board").order_by("bf_no", "pk")
    return api_response(data=[_file_payload(post_file, request) for post_file in files])


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
@parser_classes([MultiPartParser, FormParser])
def editor_upload_view(request):
    user, error = _require_user(request)
    if error:
        return error

    uploaded_file = request.FILES.get("file") or request.FILES.get("upload")
    if not uploaded_file and request.FILES:
        uploaded_file = next(iter(request.FILES.values()))
    if not uploaded_file:
        return api_error(
            "Upload file is required.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            code="validation_error",
            details={"file": "Upload file is required."},
        )

    if uploaded_file.size > MAX_EDITOR_UPLOAD_SIZE:
        return api_error(
            "Upload file is too large.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"file": "Upload file is too large."},
        )

    extension = os.path.splitext(uploaded_file.name)[1].lower()
    if extension not in EDITOR_UPLOAD_EXTENSIONS:
        return api_error(
            "Unsupported upload file extension.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"file": "Unsupported upload file extension."},
        )

    # Same content check as board attachments: a page or script renamed to .jpg is not an image.
    try:
        validate_upload_file_content(uploaded_file)
    except DjangoValidationError as exc:
        message = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
        return api_error(
            "File validation failed.",
            status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY,
            details={"file": message},
        )

    safe_name = get_valid_filename(os.path.basename(uploaded_file.name))
    uploaded_file = strip_image_metadata(uploaded_file)
    unique_name = "%s%s" % (uuid.uuid4().hex, extension)
    path = default_storage.save(os.path.join("uploads", "editor", unique_name), uploaded_file)
    url = _absolute_url(request, default_storage.url(path))
    return api_response(
        data={
            "file_url": url,
            "url": url,
            "file_name": safe_name,
            "size": uploaded_file.size,
            "uploaded_by": user.get_username(),
        },
        status=drf_status.HTTP_201_CREATED,
    )


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def post_file_download_view(request, bo_table, wr_id, bf_no):
    """Gnuboard5 download.php: download level, download points once per post, download count."""
    board, post = _get_post_for_board(request, bo_table, wr_id)
    if not board or not post:
        return api_error("Post not found.", status=drf_status.HTTP_404_NOT_FOUND, code="post_not_found")
    post_file = post.post_files.filter(bf_no=bf_no).first()
    if not post_file or not post_file.bf_file:
        return api_error("파일 정보가 존재하지 않습니다.", status=drf_status.HTTP_404_NOT_FOUND, code="file_not_found")

    try:
        handle = post_file.bf_file.storage.open(post_file.bf_file.name, "rb")
    except (OSError, ValueError, SuspiciousFileOperation):
        return api_error("파일이 존재하지 않습니다.", status=drf_status.HTTP_404_NOT_FOUND, code="file_missing")

    user = _authenticated_user(request)
    if _user_level(user) < board.bo_download_level and not _is_board_admin(user, board):
        handle.close()
        message = "다운로드 권한이 없습니다." if user else "다운로드 권한이 없습니다. 회원이시라면 로그인 후 이용해 보십시오."
        return api_error(message, status=drf_status.HTTP_403_FORBIDDEN, code="download_forbidden")
    error = _charge_point_once(
        request, board, post,
        cost=board.bo_download_point, action="다운로드", rel_action="다운로드",
        content=f"{board.bo_subject} {point_ledger.post_point_id(post)} 파일 다운로드",
        exempt_admin=True,
    )
    if error:
        handle.close()
        return error

    counted_key = f"ss_down_{board.bo_table}_{post.pk}_{post_file.bf_no}"
    if not request.session.get(counted_key):
        Post_file.objects.filter(pk=post_file.pk).update(bf_download=F("bf_download") + 1)
        request.session[counted_key] = True
    filename = os.path.basename((post_file.bf_source or post_file.bf_file.name).replace(chr(92), "/"))
    return FileResponse(handle, as_attachment=True, filename=filename or "download")
