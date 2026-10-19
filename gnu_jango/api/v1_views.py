from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from gnu_jango.bbs.models import Board, Comment, Group, Post
from gnu_jango.config import config
from gnu_jango.core.models import Site_menu
from gnu_jango.core.navigation import site_menu_items

from .response import api_response

# Site settings the Next.js site reads from /api/v1/config (moved here from the removed pre-v1 API).
PUBLIC_CONFIG_KEYS = [
    "cf_title", "cf_use_point", "cf_use_email_certify", "cf_cut_name", "cf_nick_modify",
    "cf_read_point", "me_target", "cf_write_point", "me_use", "me_mobile_use",
]


def gnu_config_wanted_keys():
    config_variables = config.get_all()
    return {key: config_variables[key] for key in PUBLIC_CONFIG_KEYS if key in config_variables}

User = get_user_model()


def _menu_payload(request):
    current_path = request.query_params.get("path") or request.path
    return site_menu_items(current_path, request.user)


@api_view(["GET"])
@permission_classes([AllowAny])
def status_view(request):
    latest_post = Post.objects.order_by("-wr_datetime", "-pk").first()
    data = {
        "service": "gnu_jango",
        "api_version": "v1",
        "status": "ok",
        "server_time": timezone.now().isoformat(),
        "counts": {
            "groups": Group.objects.count(),
            "boards": Board.objects.count(),
            "posts": Post.objects.count(),
            "comments": Comment.objects.count(),
            "members": User.objects.count(),
            "menus": Site_menu.objects.count(),
        },
        "latest_post_at": latest_post.wr_datetime.isoformat() if latest_post else None,
        "capabilities": {
            "config": True,
            "menus": True,
            "boards": True,
            "posts": True,
            "comments": True,
            "auth": True,
            "shop": "planned",
            "theme": "nextjs_default",
            "uploads": True,
        },
    }
    return api_response(data=data)


@api_view(["GET"])
@permission_classes([AllowAny])
def config_view(request):
    payload = gnu_config_wanted_keys()
    payload.setdefault("cf_title", "GNU Jango")
    return api_response(data=payload)


@api_view(["GET"])
@permission_classes([AllowAny])
def menus_view(request):
    return api_response(data=_menu_payload(request))


