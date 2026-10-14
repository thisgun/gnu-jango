"""Polls of the community API: current poll, votes, results and comments."""


from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from .authentication import SessionJWTAuthentication as JWTAuthentication

from gnu_jango.core.models import (
    Poll,
    PollChoice,
    PollComment,
    PollVote,
)
from gnu_jango.users import point_ledger
from gnu_jango.utils.lib import get_client_ip
from gnu_jango.utils.users import get_user_level

from .response import api_error, api_response
from .v1_auth import _auth_user_from_request
from .v1_board import _datetime

from .community_common import (
    _member_display_name,
    _request_data,
    _safe_int,
    _text,
)


def _poll_is_active(poll):
    today = timezone.localdate()
    if not poll or not poll.po_use:
        return False
    if poll.po_begin_date and poll.po_begin_date > today:
        return False
    if poll.po_end_date and poll.po_end_date < today:
        return False
    return True


def _poll_session_key(request, create=False):
    session = getattr(request, "session", None)
    if not session:
        return ""
    if create and not session.session_key:
        session.create()
    return session.session_key or ""


def _poll_vote_filter(request, create_session=False):
    """The votes that count as this voter's (poll_update.php).

    Members are tracked by id (mb_ids) and visitors by address (po_ips) separately, so a member's
    vote never blocks, or reveals the results to, a visitor on the same address. A visitor also
    matches their own session's guest votes.
    """
    user = _auth_user_from_request(request)
    if user:
        return Q(user=user)

    guest = Q(pk__in=[])
    session_key = _poll_session_key(request, create=create_session)
    if session_key:
        guest |= Q(session_key=session_key)
    ip = get_client_ip(request)
    if ip:
        guest |= Q(ip=ip)
    return Q(user__isnull=True) & guest


def _poll_user_level(user):
    if not user:
        return 1
    try:
        return get_user_level(user)
    except (AttributeError, TypeError, ValueError):
        return 1


def _poll_choice_payload(choice, total_count, *, hidden=False):
    count = 0 if hidden else choice.count or 0
    rate = round((count / total_count) * 100, 1) if total_count and not hidden else 0
    return {
        "num": choice.num,
        "content": choice.content or "",
        "count": count,
        "rate": rate,
        "bar": int(rate),
    }


def _poll_comment_payload(comment, request_user):
    can_delete = bool(
        request_user
        and getattr(request_user, "is_authenticated", False)
        and (request_user.is_superuser or comment.user_id == request_user.id)
    )
    return {
        "pc_id": comment.pc_id,
        "po_id": comment.poll_id,
        "mb_id": comment.user.get_username() if comment.user_id else "",
        "pc_name": comment.pc_name or _member_display_name(comment.user),
        "pc_idea": comment.pc_idea or "",
        "pc_datetime": _datetime(comment.pc_datetime),
        "can_delete": can_delete,
    }


def _poll_summary_payload(poll, current_id=None):
    return {
        "po_id": poll.po_id,
        "po_subject": poll.po_subject or "",
        "po_date": poll.po_date.isoformat() if poll.po_date else "",
        "po_use": poll.po_use or 0,
        "is_current": bool(current_id and poll.po_id == current_id),
    }


def _active_poll_queryset():
    today = timezone.localdate()
    return (
        Poll.objects.filter(po_use__gt=0)
        .filter(Q(po_begin_date__isnull=True) | Q(po_begin_date__lte=today))
        .filter(Q(po_end_date__isnull=True) | Q(po_end_date__gte=today))
        .order_by("-po_date", "-po_id")
    )


def _poll_payload(poll, request):
    request_user = _auth_user_from_request(request)
    choices = list(poll.choices.order_by("num", "id"))
    total_count = sum(choice.count or 0 for choice in choices)
    has_voted = PollVote.objects.filter(poll=poll).filter(_poll_vote_filter(request)).exists()
    is_active = _poll_is_active(poll)
    can_view_result = bool(has_voted or not is_active or _poll_user_level(request_user) >= poll.po_level)
    can_vote = bool(is_active and not has_voted and _poll_user_level(request_user) >= poll.po_level)
    comments = poll.comments.select_related("user").order_by("-pc_datetime", "-pc_id")[:100]
    other_polls = Poll.objects.filter(po_use__gt=0).exclude(pk=poll.pk).order_by("-po_date", "-po_id")[:20]
    return {
        "po_id": poll.po_id,
        "po_subject": poll.po_subject or "",
        "po_etc": poll.po_etc or "",
        "po_level": poll.po_level or 1,
        "po_point": poll.po_point or 0,
        "po_date": poll.po_date.isoformat() if poll.po_date else "",
        "po_use": poll.po_use or 0,
        "is_active": is_active,
        "options": [_poll_choice_payload(choice, total_count, hidden=not can_view_result) for choice in choices],
        "total_count": total_count if can_view_result else 0,
        "has_voted": has_voted,
        "can_vote": can_vote,
        "can_view_result": can_view_result,
        "can_comment": bool(is_active and (poll.po_etc or "").strip() and _poll_user_level(request_user) >= (poll.po_level or 1)),
        "etc_comments": [_poll_comment_payload(comment, request_user) for comment in comments],
        "other_polls": [_poll_summary_payload(item, current_id=poll.po_id) for item in other_polls],
    }


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def poll_current_view(request):
    return poll_current_response(request)


def poll_current_response(request):
    poll = _active_poll_queryset().first()
    if not poll:
        return api_error("Poll not found.", status=drf_status.HTTP_404_NOT_FOUND, code="poll_not_found")
    return api_response(data=_poll_payload(poll, request))


@api_view(["GET"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def poll_detail_view(request, po_id):
    poll = Poll.objects.filter(pk=po_id).first()
    if not poll:
        return api_error("Poll not found.", status=drf_status.HTTP_404_NOT_FOUND, code="poll_not_found")
    return api_response(data=_poll_payload(poll, request))


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def poll_vote_view(request, po_id):
    poll = Poll.objects.filter(pk=po_id).first()
    if not poll:
        return api_error("Poll not found.", status=drf_status.HTTP_404_NOT_FOUND, code="poll_not_found")
    user = _auth_user_from_request(request)
    if not _poll_is_active(poll):
        return api_error("Poll is not active.", status=drf_status.HTTP_403_FORBIDDEN, code="poll_inactive")
    if _poll_user_level(user) < poll.po_level:
        return api_error("You do not have permission to vote.", status=drf_status.HTTP_403_FORBIDDEN, code="poll_forbidden")

    data = _request_data(request)
    option = _safe_int(data.get("option") or data.get("num") or data.get("poll"), 0)
    if option < 1:
        return api_error("Poll option is required.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, details={"option": "Poll option is required."})

    identity_filter = _poll_vote_filter(request, create_session=True)
    if PollVote.objects.filter(poll=poll).filter(identity_filter).exists():
        return api_error("You have already voted.", status=drf_status.HTTP_409_CONFLICT, code="poll_already_voted")

    choice = PollChoice.objects.filter(poll=poll, num=option).first()
    if not choice:
        return api_error("Poll option was not found.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, details={"option": "Poll option was not found."})

    with transaction.atomic():
        poll = Poll.objects.select_for_update().get(pk=poll.pk)
        choice = PollChoice.objects.select_for_update().get(pk=choice.pk)
        if PollVote.objects.filter(poll=poll).filter(identity_filter).exists():
            return api_error("You have already voted.", status=drf_status.HTTP_409_CONFLICT, code="poll_already_voted")
        choice.count = (choice.count or 0) + 1
        choice.save(update_fields=["count"])
        PollVote.objects.create(
            poll=poll,
            choice=choice,
            user=user,
            session_key=_poll_session_key(request),
            ip=get_client_ip(request) or None,
        )
        point_ledger.insert_point(
            user, poll.po_point or 0, f"{poll.po_id}. {(poll.po_subject or '')[:20]} 투표 참여",
            "@poll", poll.po_id, "투표",
        )

    return api_response(data=_poll_payload(Poll.objects.get(pk=po_id), request))


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def poll_comments_view(request, po_id):
    poll = Poll.objects.filter(pk=po_id).first()
    if not poll:
        return api_error("Poll not found.", status=drf_status.HTTP_404_NOT_FOUND, code="poll_not_found")
    if not _poll_is_active(poll):
        return api_error("Poll is not active.", status=drf_status.HTTP_403_FORBIDDEN, code="poll_inactive")
    # Gnuboard5 poll_etc_update.php: other opinions must be enabled and the member's level high enough.
    if not (poll.po_etc or "").strip():
        return api_error("기타의견이 비활성화되어 있습니다.", status=drf_status.HTTP_403_FORBIDDEN, code="poll_comments_disabled")
    if _poll_user_level(_auth_user_from_request(request)) < (poll.po_level or 1):
        return api_error("권한이 없습니다.", status=drf_status.HTTP_403_FORBIDDEN, code="poll_comment_forbidden")

    data = _request_data(request)
    idea = (_text(data.get("pc_idea")) or _text(data.get("idea"))).strip()
    if not idea:
        return api_error("Poll comment is required.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, details={"pc_idea": "Poll comment is required."})

    user = _auth_user_from_request(request)
    name = _member_display_name(user) or (_text(data.get("pc_name")) or _text(data.get("name"))).strip()
    if not name:
        return api_error("Poll comment name is required.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, details={"pc_name": "Poll comment name is required."})

    PollComment.objects.create(
        poll=poll,
        user=user,
        pc_name=name[:255],
        pc_idea=idea[:255],
        pc_ip=get_client_ip(request) or None,
    )
    return api_response(data=_poll_payload(poll, request), status=drf_status.HTTP_201_CREATED)


@api_view(["DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def poll_comment_detail_view(request, po_id, pc_id):
    user = _auth_user_from_request(request)
    comment = PollComment.objects.filter(pk=pc_id, poll_id=po_id).first()
    if not comment:
        return api_error("Poll comment not found.", status=drf_status.HTTP_404_NOT_FOUND, code="poll_comment_not_found")
    if not user or not getattr(user, "is_authenticated", False) or not (user.is_superuser or comment.user_id == user.id):
        return api_error("You do not have permission to delete this comment.", status=drf_status.HTTP_403_FORBIDDEN, code="poll_comment_forbidden")
    poll = comment.poll
    comment.delete()
    return api_response(data=_poll_payload(poll, request))
