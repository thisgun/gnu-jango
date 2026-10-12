from gnu_jango import defaults
from gnu_jango.config import config
from gnu_jango.utils.lib import is_mobile
from gnu_jango.utils.users import is_admin
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse


def common_dict(request):

    # 환경설정 설정값을 Template 에서 사용가능하게 context_processors 에 등록합니다.

    config_variables = config.get_all()
    # request.user is missing when a middleware failed before AuthenticationMiddleware
    # (e.g. a disallowed Host header); such a request is rendered as a guest.
    user = getattr(request, "user", None) or AnonymousUser()

    return {
        "config": config_variables,
        "theme_path": defaults.THEME_DIR + "/" + config_variables["cf_theme"] + "/",
        "site_title": config_variables["cf_title"],
        "content_title": config_variables["cf_title"],
        "home_url": defaults.HOME_URL,
        "admin_url": defaults.ADMIN_URL,
        "login_url": defaults.LOGIN_URL,
        "logout_url": defaults.LOGOUT_URL,
        "register_url": defaults.REGISTER_URL,
        "is_user": 1 if user.is_authenticated else 0,
        "is_mobile": is_mobile(request),
        "is_admin": is_admin(user),
        "gnu_editor": config_variables["cf_editor"],
        "gnu_cookie_domain": "",
        "gnu_menu_admin_url": reverse("admin:core_site_menu_changelist"),  # 사이트메뉴 관리자 url
        "IS_INDEX_PAGE": False,
    }
