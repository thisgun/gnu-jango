from django import template
from django.core.cache import cache
from django.db.models.functions import Substr, Length

from gnu_jango.core.models import MENU_CACHE_VERSION_KEY, Site_menu
from gnu_jango.bbs.utils import get_pretty_url

register = template.Library()


def build_menu(parser, token):
    """
    {% menu menu_name %}
    """
    try:
        tag_name, menu_name = token.split_contents()
    except ValueError:
        raise template.TemplateSyntaxError(
            "%r tag requires exactly one argument" % token.contents.split()[0]
        )
    return MenuObject(menu_name)


class MenuObject(template.Node):
    def __init__(self, menu_name):
        self.menu_name = menu_name

    def render(self, context):
        try:
            current_path = context["request"].path
            user = context["request"].user
        except KeyError:
            current_path = None
            user = None

        context["menuitems"] = get_items(self.menu_name, current_path, user)
        return ""


def get_menu_link(me_link, me_type, me_type_pk):

    if me_type == "Board":
        return get_pretty_url("Board", board_pk=me_type_pk)

    return me_link


def get_items(menu_name, current_path, user):
    """
    If possible, use a cached list of items to avoid continually re-querying
    the database.
    The key contains the menu name, whether the user is authenticated, and the current path.
    Disable caching by setting MENU_CACHE_TIME to -1.
    """
    from django.conf import settings

    cache_time = getattr(settings, "MENU_CACHE_TIME", 1800)
    debug = getattr(settings, "DEBUG", False)

    if cache_time >= 0 and not debug:
        # the menu does not depend on the path or the visitor; the version changes when a menu is saved
        cache_key = "django-gnu-menu-items/%s/%s" % (cache.get(MENU_CACHE_VERSION_KEY, 0), menu_name)
        menuitems = cache.get(cache_key, {})
        if menuitems:
            return menuitems
    else:
        menuitems = {}

    result = (
        Site_menu.objects.annotate(text_len=Length("me_code"))
        .filter(text_len__exact=2, me_use=1)
        .order_by("me_order", "pk")
    )

    if not result:
        return {}

    for i, row in enumerate(result):

        row.ori_me_link = row.me_link
        row.me_link = get_menu_link(row.me_link, row.me_type, row.me_type_pk)
        row.sub = getattr(row, "sub", [])

        result2 = (
            Site_menu.objects.annotate(
                search_me_code=Substr("me_code", 1, 2), text_len=Length("me_code")
            )
            .filter(text_len__exact=4, search_me_code__exact=row.me_code, me_use=1)
            .order_by("me_order", "pk")
        )

        for row2 in result2:
            row2.ori_me_link = row2.me_link
            row2.me_link = get_menu_link(row2.me_link, row2.me_type, row2.me_type_pk)

            row.sub.append(row2)

        menuitems[i] = row

    # for i in MenuItem.objects.filter(menu=menu).order_by("order"):
    #     if current_path:
    #         current = (i.link_url != "/" and current_path.startswith(i.link_url)) or (
    #             i.link_url == "/" and current_path == "/"
    #         )
    #         if menu.base_url and i.link_url == menu.base_url and current_path != i.link_url:
    #             current = False
    #     else:
    #         current = False

    #     show_anonymous = i.anonymous_only and is_anonymous
    #     show_auth = i.login_required and is_authenticated
    #     if (
    #         (not (i.login_required or i.anonymous_only))
    #         or (i.login_required and show_auth)
    #         or (i.anonymous_only and show_anonymous)
    #     ):
    #         menuitems.append(
    #             {
    #                 "url": i.link_url,
    #                 "title": i.title,
    #                 "current": current,
    #             }
    #         )

    if cache_time >= 0 and not debug:
        cache.set(cache_key, menuitems, cache_time)

    return menuitems


# @register.simple_tag
# def gnu_menu_admin_url():
#     return "aaabbbasda"
#     return HttpResponseRedirect(reverse("admin:core_site_menu_changelist"))


register.tag("gnu_menu", build_menu)
