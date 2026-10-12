"""Member memos and notifications of the community API."""


from django.db import transaction
from django.utils import timezone
from rest_framework import status as drf_status
from rest_framework.authentication import BasicAuthentication
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.permissions import AllowAny
from .authentication import SessionJWTAuthentication as JWTAuthentication

from gnu_jango.config.models import Config
from gnu_jango.core.models import (
    Notification,
)
from gnu_jango.users import point_ledger
from gnu_jango.users.models import User_Memo
from gnu_jango.utils.lib import get_client_ip

from .response import api_error, api_response
from .v1_board import _datetime

from .community_common import (
    User,
    _member_display_name,
    _paginate,
    _request_data,
    _require_user,
    _text,
)


MEMO_MAX_LENGTH = 65536  # memo_form_update.php: substr(trim($_POST['me_memo']), 0, 65536)


class _MemoFeeShort(Exception):
    """The balance no longer covers the fee (another request spent it first)."""


def _memo_send_point(sender):
    """The fee per receiver (memo_form_update.php: cf_memo_send_point, administrators free).

    Only a configured cf_memo_send_point is charged: without the setting row a site has never
    chosen a fee, so the Gnuboard5 install default (500) is not applied behind its back.
    """
    if sender.is_superuser or not point_ledger.points_enabled():
        return 0
    if not Config.objects.filter(name="cf_memo_send_point").exists():
        return 0
    return max(point_ledger.config_points("cf_memo_send_point"), 0)


def _memo_point_short_error(sender):
    balance = point_ledger.point_balance(sender)
    return api_error(
        f"보유하신 포인트({balance:,}점)가 모자라서 쪽지를 보낼 수 없습니다.",
        status=drf_status.HTTP_403_FORBIDDEN,
        code="insufficient_point",
    )


def _memo_user_by_id(user_id):
    if not user_id:
        return None
    return User.objects.filter(pk=user_id).first()


def _memo_payload(memo):
    owner = memo.user
    recv_user = _memo_user_by_id(memo.me_recv_user_id)
    if memo.me_type == "send":
        send_user = owner
    else:
        send_user = _memo_user_by_id(memo.me_send_id)
    return {
        "me_id": memo.pk,
        "me_recv_mb_id": recv_user.get_username() if recv_user else "",
        "me_send_mb_id": send_user.get_username() if send_user else "",
        "me_send_datetime": _datetime(memo.me_send_datetime),
        "me_read_datetime": _datetime(memo.me_read_datetime) or "0000-00-00 00:00:00",
        "me_memo": memo.me_memo or "",
        "me_send_id": memo.me_send_id or 0,
        "me_type": memo.me_type or "recv",
        "me_send_ip": memo.me_send_ip or "",
    }


def _notification_payload(notification):
    return {
        "nt_id": notification.nt_id,
        "nt_type": notification.nt_type or "system",
        "nt_title": notification.nt_title or "",
        "nt_body": notification.nt_body or "",
        "nt_data": notification.nt_data,
        "nt_sent_at": _datetime(notification.nt_sent_at),
        "nt_read_at": _datetime(notification.nt_read_at),
        "is_read": bool(notification.nt_read_at),
    }


@api_view(["GET", "POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def memos_view(request):
    user, error = _require_user(request)
    if error:
        return error
    if request.method == "GET":
        memo_type = request.query_params.get("type") or "recv"
        queryset = User_Memo.objects.filter(user=user, me_type=memo_type).order_by("-me_send_datetime", "-pk")
        page, meta = _paginate(request, queryset, 20)
        return api_response(data=[_memo_payload(memo) for memo in page], meta=meta)

    data = _request_data(request)
    recv_mb_id = _text(data.get("me_recv_mb_id")).strip()
    content = _text(data.get("me_memo")).strip()[:MEMO_MAX_LENGTH]
    receiver = User.objects.filter(username=recv_mb_id, is_active=True).first() if recv_mb_id else None
    if not receiver:
        return api_error("Receiver was not found.", status=drf_status.HTTP_404_NOT_FOUND, code="receiver_not_found")
    if not content:
        return api_error("Memo content is required.", status=drf_status.HTTP_422_UNPROCESSABLE_ENTITY, details={"me_memo": "Memo content is required."})

    fee = _memo_send_point(user)
    if fee and point_ledger.point_balance(user) < fee:
        return _memo_point_short_error(user)

    try:
        recv_memo, send_memo = _store_memo(request, user, receiver, content, fee)
    except _MemoFeeShort:
        return _memo_point_short_error(user)
    payload = _memo_payload(recv_memo)
    payload["send_me_id"] = send_memo.pk
    return api_response(data=payload, status=drf_status.HTTP_201_CREATED)


def _store_memo(request, user, receiver, content, fee):
    """The receiver's and the sender's copy, and the fee, in one transaction."""
    now = timezone.now()
    ip = get_client_ip(request) or ""
    with transaction.atomic():
        recv_memo = User_Memo.objects.create(
            user=receiver,
            me_recv_user_id=receiver.pk,
            me_send_id=user.pk,
            me_send_datetime=now,
            me_memo=content,
            me_type="recv",
            me_send_ip=ip,
        )
        send_memo = User_Memo.objects.create(
            user=user,
            me_recv_user_id=receiver.pk,
            me_send_id=recv_memo.pk,
            me_send_datetime=now,
            me_memo=content,
            me_type="send",
            me_send_ip=ip,
        )
        if fee:
            # memo_form_update.php: insert_point(-cf_memo_send_point, '@memo', receiver, me_id).
            receiver_name = _member_display_name(receiver)
            result = point_ledger.insert_point(
                user, -fee, f"{receiver_name}({receiver.get_username()})님께 쪽지 발송",
                "@memo", receiver.pk, str(recv_memo.pk), require_balance=True,
            )
            if result == point_ledger.INSUFFICIENT:
                raise _MemoFeeShort()  # leaving the atomic block undoes both copies
    return recv_memo, send_memo


@api_view(["GET", "DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def memo_detail_view(request, memo_id):
    user, error = _require_user(request)
    if error:
        return error
    memo = User_Memo.objects.filter(pk=memo_id, user=user).first()
    if not memo:
        return api_error("Memo not found.", status=drf_status.HTTP_404_NOT_FOUND, code="memo_not_found")
    if request.method == "DELETE":
        memo.delete()
        return api_response(data={"deleted": True, "me_id": memo_id})
    if memo.me_type == "recv" and not memo.me_read_datetime:
        read_at = timezone.now()
        memo.me_read_datetime = read_at
        memo.save(update_fields=["me_read_datetime"])
        # memo_view.php stamps the sender's copy too ("me_id = X or me_send_id = X"), so the
        # sender sees that the memo was read. The sent copy keeps the received copy's id.
        User_Memo.objects.filter(
            me_type="send", me_send_id=memo.pk, user_id=memo.me_send_id, me_read_datetime__isnull=True
        ).update(me_read_datetime=read_at)
    return api_response(data=_memo_payload(memo))


@api_view(["GET", "POST", "DELETE"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def notifications_view(request):
    user, error = _require_user(request)
    if error:
        return error

    if request.method == "DELETE":
        deleted, _ = Notification.objects.filter(user=user).delete()
        return api_response(data={"deleted": deleted})

    if request.method == "POST":
        data = _request_data(request)
        notification = Notification.objects.create(
            user=user,
            nt_type=str(data.get("nt_type") or "system")[:50],
            nt_title=str(data.get("nt_title") or data.get("title") or ""),
            nt_body=str(data.get("nt_body") or data.get("body") or ""),
            nt_data=data.get("nt_data") if isinstance(data.get("nt_data"), dict) else {},
        )
        return api_response(data=_notification_payload(notification), status=drf_status.HTTP_201_CREATED)

    queryset = Notification.objects.filter(user=user).order_by("-nt_sent_at", "-nt_id")
    if str(request.query_params.get("unread_only") or "").lower() in ("1", "true", "yes", "on"):
        queryset = queryset.filter(nt_read_at__isnull=True)
    page, meta = _paginate(request, queryset, default_per_page=30, max_per_page=100)
    return api_response(data=[_notification_payload(notification) for notification in page], meta=meta)


@api_view(["POST"])
@permission_classes([AllowAny])
@authentication_classes([JWTAuthentication, BasicAuthentication])
def notifications_read_all_view(request):
    user, error = _require_user(request)
    if error:
        return error
    read_at = timezone.now()
    Notification.objects.filter(user=user, nt_read_at__isnull=True).update(nt_read_at=read_at)
    return api_response(data={"read_at": _datetime(read_at), "message": "Notifications marked as read."})
