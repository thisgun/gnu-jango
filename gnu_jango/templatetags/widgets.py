import re
import uuid
from django.template import Library
from django.core.files.storage import default_storage
from django.utils.html import format_html
from django.forms.utils import flatatt

# from django.shortcuts import render_to_response, redirect
# from django.contrib.staticfiles.finders import find
# from django.templatetags.static import static

from gnu_jango import defaults
from gnu_jango.config import config
from gnu_jango.bbs.models import Post
from gnu_jango.bbs.utils import get_bbs_list
from gnu_jango.utils.lib import (
    get_template_theme_mobile_path,
    get_template_replace_path,
)
from gnu_jango.utils.cache import gnu_set_cache, gnu_get_cache
from gnu_jango.utils.users import (
    get_gravatar_url,
    get_sideview as get_user_sideview,
    user_icon_url as get_user_icon_url,
)
from gnu_jango.utils.get_path import static_url_version as get_static_url_version

from sorl.thumbnail import get_thumbnail

register = Library()

# https://stackoverflow.com/questions/1490059/django-inclusion-tag-with-configurable-template


class CustomRequest:
    def __init__(self, user):
        self.user = user


@register.filter(name="dict_key")
def dict_key(d, k):
    """Return a mapping value or indexed item without breaking template rendering."""
    try:
        return d.get(k)
    except AttributeError:
        try:
            return d[k]
        except (IndexError, KeyError, TypeError):
            return None


@register.filter(name="list_key")
def list_key(l, k):
    """Return an item by index, or a mapping value for legacy templates."""
    if hasattr(l, "get"):
        return l.get(k)
    try:
        return l[int(k)]
    except (IndexError, TypeError, ValueError):
        return None


@register.filter
def to_class_name(value):
    return value.__class__.__name__


# https://stackoverflow.com/questions/44394482/template-tag-not-working-with-csrf-token

# 아웃로그인
@register.simple_tag(takes_context=True)
def outlogin(context, skin_dir="basic"):

    is_auth = False
    nickname = ""
    point = 0

    request = context.get("request")
    custom_request = CustomRequest(request.user)
    current_url_escaped = request.get_full_path()
    is_mobile = context["is_mobile"]

    p = re.compile("^theme/(.+)$")
    m = p.match(skin_dir)

    if m:
        if is_mobile:
            template_path = (
                get_template_theme_mobile_path() + "/" + defaults.SKIN_DIR + "/outlogin/" + m[1]
            )

    template_path = defaults.SKIN_DIR + "/outlogin/" + skin_dir + "/"

    tpl_path = template_path

    if custom_request.user.is_authenticated:  # 로그인 했으면
        nickname = (
            getattr(getattr(custom_request.user, "profile"), "nickname")[
                : getattr(config, "cf_cut_name2 ") or 10
            ]
            if hasattr(custom_request.user, "profile")
            else custom_request.user.username
        )
        point = (
            getattr(getattr(custom_request.user, "profile"), "user_point")
            if hasattr(custom_request.user, "profile")
            else 0
        )
        tpl_path += "outlogin.skin.2.html"
    else:
        tpl_path += "outlogin.skin.1.html"

    # tpl = get_template(tpl_path)

    # https://stackoverflow.com/questions/38167348/django-next-with-query-parameters

    # return tpl.render(Context(
    #     {
    #         'nickname': nickname,
    #         'outlogin_static_path': get_template_replace_path(template_path),
    #         'next' : quote(current_url_escaped)
    #     }
    # ))

    # https://stackoverflow.com/questions/38167348/django-next-with-query-parameters
    # return tpl.render(
    #     {
    #         "nickname": nickname,
    #         "outlogin_static_path": get_template_replace_path(template_path),
    #         # 'next' : quote(current_url_escaped),      # quote 하니까 안됨 ㅠㅠ
    #         "next": current_url_escaped,
    #         "point": point,
    #     },
    #     request,
    # )

    c = {
        "nickname": nickname,
        "outlogin_static_path": get_template_replace_path(template_path),
        # 'next' : quote(current_url_escaped),      # quote 하니까 안됨 ㅠㅠ
        "next": current_url_escaped,
        "point": point,
    }
    template_as_object = context.template.engine.get_template(tpl_path)

    context.update(c)
    # # # context.render_context["block_context"] = template_as_object

    # # context.render_context["block_context"] = loader_tags.BlockContext()
    # # print(template_as_object)
    # # block_context = context.render_context["block_context"]

    return template_as_object.render(context)


@register.simple_tag
def static_url_version(path, is_filetime=False):
    return get_static_url_version(path, is_filetime)


@register.simple_tag
def conv_content(content, html, filter=True):
    return content


# https://stackoverflow.com/questions/26301447/django-read-cookie-in-template-tag
@register.simple_tag(takes_context=True)
def get_cookie(context, cookie_name):  # could feed in additional argument to use as default value
    request = context["request"]
    result = request.COOKIES.get(cookie_name, "")  # I use blank as default value
    return result


@register.simple_tag(takes_context=True)
def pop_up_cookie(context, cookie_prefix, pk):

    return get_cookie(context, "%s%s" % (cookie_prefix, pk))


@register.simple_tag(takes_context=True)
def get_sideview(context, user, name="", email="", homepage=""):
    return get_user_sideview(
        user, name, email, homepage, request=context.get("request")
    )
    # if isinstance(user, int):
    #     user = get_user_model().objects.get(pk=user)

    # if hasattr(user, "_cached_get_sideview"):
    #     return user._cached_get_sideview

    # tmp_name = ''

    # title = _("%(name)s 자기소개") % {"name": name}

    # is_user = False

    # if hasattr(user, 'id'):
    #     is_user = True
    #     tmp_name = '<a href="#" class="sv_member" title="'+ title +'" target="_blank" rel="nofollow" onclick="return false;">'

    #     if config.cf_use_member_icon:
    #         width = config.cf_member_icon_width
    #         height = config.cf_member_icon_height
    #         tmp_name += '<span class="profile_img"><img src="%s" width="%d" height="%d" alt=""></span>' % (user_icon_url(user, width, height), width, height)

    #         # 회원아이콘+이름
    #         if config.cf_use_member_icon == 2:
    #             tmp_name += ' ' + name

    #     else:
    #         tmp_name += ' ' + name

    #     tmp_name += '</a>'

    # sides = []
    # if is_user:
    #     sides.append("<a href=\"#\" onclick=\"win_memo(this.href); return false;\">%s</a>" % (_('쪽지보내기')))

    # if email:
    #     sides.append("<a href=\"#\" onclick=\"win_email(this.href); return false;\">%s</a>" % (_('메일보내기')))

    # if homepage:
    #     sides.append("<a href=\"%s\" target=\"_blank\">%s</a>" % (homepage, _('홈페이지')))

    # if is_user:
    #     sides.append("<a href=\"#\" onclick=\"win_profile(this.href); return false;\">%s</a>" % (_('자기소개')))

    # if is_user:
    #     sides.append("<a href=\"#\" class=\"link_new_page\" onclick=\"check_goto_new(this.href, event);\">%s</a>" % (_('전체게시물')))

    # # inners = "\n".join(
    # #     "<a href=\"#\" onclick=\"win_memo(this.href); return false;\">%s</a>" % (_('쪽지보내기')),
    # #     "<a href=\"#\" onclick=\"win_email(this.href); return false;\">%s</a>" % (_('메일보내기')),
    # #     "<a href=\"%s\" target=\"_blank\">%s</a>" % (homepage, _('홈페이지')),
    # #     "<a href=\"#\" onclick=\"win_profile(this.href); return false;\">%s</a>" % (_('자기소개')),
    # #     "<a href=\"#\" class=\"link_new_page\" onclick=\"check_goto_new(this.href, event);\">%s</a>" % (_('전체게시물')),
    # # )

    # inners = "\n".join(sides)
    # user._cached_get_sideview = "\n".join(
    #     "<span class=\"sv_wrap\">",
    #     tmp_name,
    #     "<span class=\"sv\">",
    #     inners,
    #     "</span>",
    #     "<noscript class=\"sv_nojs\">" + inners + "</noscript>",
    #     "</span>",
    # )

    # return user._cached_get_sideview


@register.simple_tag
def get_member_profile_img(
    user, width=0, height=0, alt="profile_image", title="", gravatar_only=False
):

    avatar_width = width if width else 50
    avatar_height = height if height else 50
    src = avatar_url(user, avatar_width, avatar_height, gravatar_only)

    attributes = {"src": src, "alt": alt}
    if width:
        attributes["width"] = width
    if height:
        attributes["height"] = height
    if title:
        attributes["title"] = title
    return format_html("<img{}>", flatatt(attributes))



@register.simple_tag
def avatar_url(user, width=50, height=50, gravatar_only=False):
    if (
        not gravatar_only
        and hasattr(user, "profile")
        and user.profile.avatar
        # .name, not .path: remote storages (MEDIA_STORAGE=s3) have no local filesystem path.
        and default_storage.exists(user.profile.avatar.name)
    ):
        from gnu_jango.core.background import enabled
        if enabled():
            from gnu_jango.core.thumbnails import thumbnail_url
            return thumbnail_url(user.profile.avatar.url, 240, storage_path=user.profile.avatar.name)
        im = get_thumbnail(
            user.profile.avatar,
            "%sx%s" % (width, height),
            crop="center",
            quality=defaults.THUMBNAIL_QUALITY,
        )
        return im.url

    if hasattr(user, "email"):
        gravatar_url = get_gravatar_url(user.email, size=width)
        if gravatar_url is not None:
            return gravatar_url

    return static_url_version("img/no_profile.gif")


@register.simple_tag
def get_uuid():
    return uuid.uuid4().hex


@register.simple_tag
def user_icon_url(user, width=20, height=20):
    return get_user_icon_url(user, width, height)

    # if (
    #     hasattr(user, 'profile')
    #     and user.profile.icon
    #     and default_storage.exists(user.profile.icon.path)
    # ):
    #     #return user.profile.icon.url

    #     im = get_thumbnail(user.profile.icon.path, '%sx%s' % (width, height), crop='center', quality=defaults.THUMBNAIL_QUALITY)
    #     return im.url

    # return static_url_version('img/no_profile.gif')


@register.simple_tag
def get_selected(field, value):
    if field == value:
        return ' selected="selected"'
    else:
        return ""


def build_latest_posts(board, rows=10, subject_len=40, request=None, queryset=None):
    if not board:
        return []

    if queryset is None:
        queryset = Post.objects.filter(board_id__exact=board.id, is_notice=0).order_by(
            "wr_num", "-pk"
        )[:rows]

    items = []

    for row in queryset:
        row.wr_password = ""
        row.wr_email = ""

        if "secret" in (row.wr_option or ""):
            row.wr_content = ""
            row.wr_link1 = ""
            row.wr_link2 = ""
            row.file = None

        items.append(get_bbs_list(row, board, "", subject_len, request=request))

    if len(items) > rows:
        items = items[:rows]

    return items


@register.simple_tag(takes_context=True)
def latest(context, skin_dir="", board=None, rows=10, subject_len=40, cache_time=1, options=None):
    options = options or {}
    time_unit = 3600  # 1시간으로 고정

    if not board:
        return None

    if not skin_dir:
        skin_dir = "basic"

    request = context.get("request") or None

    # print("리퀘스트")
    # print(request)
    template_path = defaults.SKIN_DIR + "/latest/" + skin_dir + "/"

    caches = None
    # 1시간으로 고정
    time_unit = 3600

    is_use_cache = defaults.USE_CACHE

    if is_use_cache:
        cache_key = "latest-%s-%s" % (str(board.id), defaults.BBS_CACHE_ROWS)
        # cache_key = "latest-%s-%s-%s-%s" % (str(board.id), skin_dir, str(rows), str(subject_len))
        caches = gnu_get_cache(cache_key, int(time_unit) * int(cache_time))

    if caches == None:

        list = []

        # results = Post.objects.filter(board=board, is_notice=0).order_by('wr_num', '-pk')[:rows]
        results = Post.objects.filter(board_id__exact=board.id, is_notice=0).order_by(
            "wr_num", "-pk"
        )[: defaults.BBS_CACHE_ROWS]

        for row in results:

            row.wr_password = ""  # 캐시에 패스워드 저장 안함
            row.wr_email = ""  # 캐시에 이메일 저장 안함

            if "secret" in row.wr_option:
                row.wr_content = ""
                row.wr_link1 = ""
                row.wr_link2 = ""
                row.file = None

            list.append(get_bbs_list(row, board, "", subject_len, request=request))

        if is_use_cache:
            caches = {
                "list": list,
            }

            gnu_set_cache(cache_key, caches, int(time_unit) * int(cache_time))

    else:
        list = caches["list"]

    if len(list) > rows:
        list = list[:rows]

    # API 에서 최신글을 가져간다면 list 만 return 함
    if "get_api" in options:
        if options["get_api"] == 1:
            return list

    tpl_path = template_path + "latest.skin.html"
    c = {
        "list": list,
        "board": board,
        "latest_static_path": get_template_replace_path(template_path),
        "options": options,
        "request": request,
    }

    # django_engine = engines["django"]
    # template = django_engine.from_string("Hello {{ name }}!")

    # print(context)
    # print(RequestContext(request))

    # c = Context(
    #     {
    #         "list": list,
    #         "board": board,
    #         "latest_static_path": get_template_replace_path(template_path),
    #         "options": options,
    #         "request": request,
    #     }
    # )

    # t = Template(
    #     self.loadstatement
    #     + "{% if post|posted_by:request.user %}OWNER{% else %}NO_OWNER{% endif %}"
    # )
    # c = Context({"post": post, "request": request})
    # rendered = t.render(c)

    # context.update(c)

    # # print( get_template_replace_path(template_path)  )
    # # context['list'] = list
    # # context['board'] = board
    # # context['latest_static_path'] = get_template_replace_path(template_path)
    # return render_to_string(tpl_path, context, request)

    # return '{% include "default_table.html" %}'

    # template_as_object = context.template.engine.from_string(tpl_path)
    # return template_as_object.render(context)

    template_as_object = context.template.engine.get_template(tpl_path)

    context.update(c)
    # # # context.render_context["block_context"] = template_as_object

    # # context.render_context["block_context"] = loader_tags.BlockContext()
    # # print(template_as_object)
    # # block_context = context.render_context["block_context"]

    return template_as_object.render(context)

    # tpl = get_template(tpl_path)

    # # print("위")
    # # print(request)

    # context.update(c)
    # return tpl.render(context, request)
