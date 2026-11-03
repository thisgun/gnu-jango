"""The admin sidebar: the core groups (settings.G5_ADMIN_NAVIGATION) and then the plugins' links.

UNFOLD["SIDEBAR"]["navigation"] names this callable, so plugins are read per request, after the app
registry is ready, and never while the settings load.
"""

from django.conf import settings
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from . import installed_plugins


def _item(link):
    item = {"title": link.title, "icon": link.icon, "link": reverse_lazy(link.url_name)}
    if link.permission:
        item["permission"] = lambda request, perm=link.permission: request.user.has_perm(perm)
    return item


def sidebar_navigation(request):
    groups = list(settings.G5_ADMIN_NAVIGATION)
    items = [_item(link) for plugin in installed_plugins() for link in plugin.admin_links]
    if items:
        groups.append({"title": _("플러그인"), "separator": True, "collapsible": True, "items": items})
    return groups
