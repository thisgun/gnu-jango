# https://stackoverflow.com/questions/20010108/checking-if-username-exists-in-django
import hashlib

from django.conf import settings
from django.utils.http import urlencode
from django.contrib.auth import get_user_model

# from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _
from django.core.files.storage import default_storage

from gnu_jango import defaults
from gnu_jango.config import config
from gnu_jango.utils.get_path import static_url_version

from sorl.thumbnail import get_thumbnail

# from gnu_jango.templatetags.widgets import user_icon_url

User = get_user_model()


def is_admin(user):

    is_authority = ""

    if user.is_superuser:
        is_authority = "super"

    return is_authority


def username_exists(username):
    if User.objects.filter(username=username).exists():
        return True

    return False


def username_exists_info(username=None, **kwargs):

    user_id = kwargs.get("pk", None)

    if user_id:
        try:
            return User.objects.filter(pk=int(user_id)).first()
        except (TypeError, ValueError):
            return None
    if username:
        return User.objects.filter(username=username).first()
    return None


def get_user(user_id, **kwargs):

    return username_exists_info(pk=user_id)


def get_user_level(user):

    if user.is_authenticated:
        profile = getattr(user, "profile", None)  # a missing profile reads as level 1
        return int(getattr(profile, "user_level", 1) or 1)

    # 비회원은 레벨이 1입니다.
    return 1


def get_user_point(user):

    if user.is_authenticated:
        profile = getattr(user, "profile", None)
        user_point = getattr(profile, "user_point", 0) or 0
        return int(user_point)

    return 0


def get_user_nickname(user, length=0):

    if user.is_authenticated:
        profile = getattr(user, "profile", None)
        user_nickname = getattr(profile, "nickname", "") or ""
        return user_nickname[:length] if user_nickname and length else user_nickname

    return ""


def get_user_realname(user, length=0):
    if user.is_authenticated:
        profile = getattr(user, "profile", None)
        realname = getattr(profile, "realname", "") or ""
        return realname[:length] if realname and length else realname

    return ""


def get_user_homepage(user):
    # if user.is_authenticated:
    #     user_homepage = getattr(getattr(user, "profile"), "homepage") or ""
    #     return user_homepage

    return ""


def username_text_name(user):

    if user:
        profile = getattr(user, "profile", None)
        return getattr(profile, "nickname", "") or user.username

    return ""


def get_gravatar_url(email, size=50):
    default = "mm"
    size = (
        int(size) * 2
    )  # requested at retina size by default and scaled down at point of use with css
    gravatar_provider_url = getattr(settings, "GRAVATAR_PROVIDER_URL", "//www.gravatar.com/avatar")

    if (not email) or (gravatar_provider_url is None):
        return None

    gravatar_url = "{gravatar_provider_url}/{hash}?{params}".format(
        gravatar_provider_url=gravatar_provider_url.rstrip("/"),
        hash=hashlib.md5(email.lower().encode("utf-8")).hexdigest(),
        params=urlencode({"s": size, "d": default}),
    )

    return gravatar_url


def user_icon_url(user, width=20, height=20):
    if (
        hasattr(user, "profile")
        and user.profile.icon
        and default_storage.exists(user.profile.icon.path)
    ):
        # return user.profile.icon.url

        im = get_thumbnail(
            user.profile.icon.path,
            "%sx%s" % (width, height),
            crop="center",
            quality=defaults.THUMBNAIL_QUALITY,
        )
        return im.url

    return static_url_version("img/no_profile.gif")


def get_sideview_data(user, name="", email="", homepage="", **kwargs):
    """Name, icon and link flags for a writer's side menu (Gnuboard5 get_sideview).

    The member's account e-mail is never included: Gnuboard5 shows only a form-mail link.
    """
    request = kwargs.get("request", None)

    if user and isinstance(user, int):
        user = get_user_model().objects.filter(pk=user).first()

    tmp_name = ""

    is_user = False

    datas = {
        "is_user": False,
        "name": "",
        "email": "",
        "user_icon_url": "",
        "absolute_user_icon_url": "",
        "memo_url": "",
        "mail_url": "",
        "homepage_url": "",
        "profile_url": "",
        "user_posts_url": "",
    }

    if hasattr(user, "id"):

        is_user = True
        datas["is_user"] = True
        profile = getattr(user, "profile", None)
        datas["name"] = getattr(profile, "nickname", "") or user.get_username()

        if config.cf_use_user_icon:
            datas["user_icon_url"] = user_icon_url(
                user, config.cf_user_icon_width, config.cf_user_icon_height
            )

            if request:
                datas["absolute_user_icon_url"] = request.build_absolute_uri(datas["user_icon_url"])

    if is_user:
        datas["memo_url"] = "#"

    if email:
        datas["mail_url"] = "#"

    if homepage:
        datas["homepage_url"] = "#"

    if is_user:
        datas["profile_url"] = "#"

    if is_user:
        datas["user_posts_url"] = "#"

    return datas


# def get_sideview(user, name='', email='', homepage='', **kwargs):

#     datas = get_sideview_data(user, name, email, homepage, **kwargs)

# 	# 수정,삭제 등 변화가 있다면 이 값의 해당 키를 반드시 초기화 할것
#     if not hasattr(get_sideview, 'user_views'):
#         get_sideview.user_views = {}

#     if hasattr(user, 'id'):
#         user_id = user.id
#     elif user and isinstance(user, int):
#         user_id = user

#     if user_id in get_sideview.user_views:
#         return get_sideview.user_views[user_id]

#     if user and isinstance(user, int):
#         user = get_user_model().objects.get(pk=user)

#     tmp_name = ''

#     # title = _("%(name)s 자기소개") % {"name": name}

#     is_user = False

#     if hasattr(user, 'id'):
#         name = user.profile.nickname
#         email = user.email

#         title = _("%(name)s 자기소개") % {"name": name}

#         is_user = True
#         tmp_name = '<a href="#" class="sv_user" title="'+ title +'" target="_blank" rel="nofollow" onclick="return false;">'

#         if config.cf_use_user_icon:
#             width = config.cf_user_icon_width
#             height = config.cf_user_icon_height
#             tmp_name += '<span class="profile_img"><img src="%s" width="%d" height="%d" alt=""></span>' % (user_icon_url(user, width, height), width, height)

#             if config.cf_use_user_icon == '2':
#                 tmp_name += ' %s' % name

#         else:
#             tmp_name += ' %s' % name

#         tmp_name += '</a>'

#     sides = []
#     if is_user:
#         sides.append("<a href=\"#\" onclick=\"win_memo(this.href); return false;\">%s</a>" % (_('쪽지보내기')))

#     if email:
#         sides.append("<a href=\"#\" onclick=\"win_email(this.href); return false;\">%s</a>" % (_('메일보내기')))

#     if homepage:
#         sides.append("<a href=\"%s\" target=\"_blank\">%s</a>" % (homepage, _('홈페이지')))

#     if is_user:
#         sides.append("<a href=\"#\" onclick=\"win_profile(this.href); return false;\">%s</a>" % (_('자기소개')))

#     if is_user:
#         sides.append("<a href=\"#\" class=\"link_new_page\" onclick=\"check_goto_new(this.href, event);\">%s</a>" % (_('전체게시물')))

#     # inners = "\n".join([
#     #     "<a href=\"#\" onclick=\"win_memo(this.href); return false;\">%s</a>" % (_('쪽지보내기')),
#     #     "<a href=\"#\" onclick=\"win_email(this.href); return false;\">%s</a>" % (_('메일보내기')),
#     #     "<a href=\"%s\" target=\"_blank\">%s</a>" % (homepage, _('홈페이지')),
#     #     "<a href=\"#\" onclick=\"win_profile(this.href); return false;\">%s</a>" % (_('자기소개')),
#     #     "<a href=\"#\" class=\"link_new_page\" onclick=\"check_goto_new(this.href, event);\">%s</a>" % (_('전체게시물')),
#     # ])

#     inners = "\n".join(sides)
#     get_sideview.user_views[user_id] = "\n".join([
#         "<span class=\"sv_wrap\">",
#         tmp_name,
#         "<span class=\"sv\">",
#         inners,
#         "</span>",
#         "<noscript class=\"sv_nojs\">" + inners + "</noscript>",
#         "</span>",
#     ])

#     return get_sideview.user_views[user_id]


def get_sideview(user, name="", email="", homepage="", **kwargs):

    datas = get_sideview_data(user, name, email, homepage, **kwargs)

    tmp_name = ""

    # title = _("%(name)s 자기소개") % {"name": name}

    if datas["is_user"]:
        name = datas["name"]
        email = datas["email"]

        title = _("%(name)s 자기소개") % {"name": name}

        is_user = True
        tmp_name = (
            '<a href="#" class="sv_user" title="'
            + title
            + '" target="_blank" rel="nofollow" onclick="return false;">'
        )

        if config.cf_use_user_icon:
            width = config.cf_user_icon_width
            height = config.cf_user_icon_height
            tmp_name += (
                '<span class="profile_img"><img src="%s" width="%d" height="%d" alt=""></span>'
                % (datas["user_icon_url"], width, height)
            )

            if config.cf_use_user_icon == "2":
                tmp_name += " %s" % name

        else:
            tmp_name += " %s" % name

        tmp_name += "</a>"

    sides = []
    if datas["memo_url"]:
        sides.append(
            '<a href="#" onclick="win_memo(this.href); return false;">%s</a>' % (_("쪽지보내기"))
        )

    if datas["mail_url"]:
        sides.append(
            '<a href="#" onclick="win_email(this.href); return false;">%s</a>' % (_("메일보내기"))
        )

    if datas["homepage_url"]:
        sides.append('<a href="%s" target="_blank">%s</a>' % (homepage, _("홈페이지")))

    if datas["profile_url"]:
        sides.append(
            '<a href="#" onclick="win_profile(this.href); return false;">%s</a>' % (_("자기소개"))
        )

    if datas["user_posts_url"]:
        sides.append(
            '<a href="#" class="link_new_page" onclick="check_goto_new(this.href, event);">%s</a>'
            % (_("전체게시물"))
        )

    # inners = "\n".join([
    #     "<a href=\"#\" onclick=\"win_memo(this.href); return false;\">%s</a>" % (_('쪽지보내기')),
    #     "<a href=\"#\" onclick=\"win_email(this.href); return false;\">%s</a>" % (_('메일보내기')),
    #     "<a href=\"%s\" target=\"_blank\">%s</a>" % (homepage, _('홈페이지')),
    #     "<a href=\"#\" onclick=\"win_profile(this.href); return false;\">%s</a>" % (_('자기소개')),
    #     "<a href=\"#\" class=\"link_new_page\" onclick=\"check_goto_new(this.href, event);\">%s</a>" % (_('전체게시물')),
    # ])

    inners = "\n".join(sides)
    return "\n".join(
        [
            '<span class="sv_wrap">',
            tmp_name,
            '<span class="sv">',
            inners,
            "</span>",
            '<noscript class="sv_nojs">' + inners + "</noscript>",
            "</span>",
        ]
    )
