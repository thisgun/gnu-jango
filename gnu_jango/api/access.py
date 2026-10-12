from django.db.models import Exists, OuterRef, Q

from gnu_jango.bbs.models import Board, Post
from gnu_jango.utils.users import get_user_level, is_admin as gnu_is_admin


def secret_post_session_filters(request):
    filters = Q()
    if not request:
        return filters

    for key, value in request.session.items():
        if not value or not key.startswith("ss_secret_"):
            continue

        parts = key.split("_")
        if len(parts) != 4:
            continue

        try:
            board_id = int(parts[2])
            wr_num = int(parts[3])
        except ValueError:
            continue

        filters |= Q(board_id=board_id, wr_num=wr_num)

    return filters


def secret_post_session_key(post):
    """The session flag Gnuboard5 sets once a secret thread is unlocked (write_update.php:712)."""
    return f"ss_secret_{post.board_id}_{post.wr_num}"


def managed_board_filter(user):
    """Posts of boards the member administers as board or group administrator (Gnuboard5 is_admin)."""
    username = user.get_username()
    if not username:
        return Q(pk__in=[])
    # A subquery rather than a join keeps select_for_update() callers free of outer joins.
    managed = Board.objects.filter(Q(bo_admin=username) | Q(group__gr_admin=username)).values("pk")
    return Q(board_id__in=managed)


def secret_thread_owner_filter(user):
    """Replies in a thread whose original post the member wrote (board.php:84-95)."""
    root_by_user = Post.objects.filter(
        board_id=OuterRef("board_id"), wr_num=OuterRef("wr_num"), wr_reply="", user=user
    )
    return ~Q(wr_reply="") & Q(Exists(root_by_user))


def readable_post_queryset(request, queryset=None):
    if queryset is None:
        queryset = Post.objects.all()

    user = getattr(request, "user", None)
    if user and gnu_is_admin(user):
        return queryset

    user_level = get_user_level(user) if user else 1
    readable = Q(board__bo_read_level__lte=user_level)
    if user and user.is_authenticated:
        readable |= Q(user=user)

    queryset = queryset.filter(readable)

    secret_allowed = (
        ~Q(wr_option__contains="secret") | secret_post_session_filters(request)
    )
    if user and user.is_authenticated:
        # Gnuboard5 board.php:78: the author or an administrator of the board passes; the author of
        # a secret thread's original post also reads the replies in it.
        secret_allowed |= Q(user=user) | managed_board_filter(user) | secret_thread_owner_filter(user)

    return queryset.filter(secret_allowed)


def listable_post_queryset(request, queryset=None):
    """Posts visible in a board list, including secret posts with content withheld."""
    if queryset is None:
        queryset = Post.objects.all()

    user = getattr(request, "user", None)
    if user and gnu_is_admin(user):
        return queryset

    user_level = get_user_level(user) if user else 1
    listable = Q(board__bo_list_level__lte=user_level)
    if user and user.is_authenticated:
        listable |= Q(user=user)

    return queryset.filter(listable)
