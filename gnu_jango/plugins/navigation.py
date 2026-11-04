"""The admin sidebar: the core groups (settings.G5_ADMIN_NAVIGATION) and then the plugins' group.

UNFOLD["SIDEBAR"]["navigation"] names this callable, so plugins are read per request, after the app
registry is ready, and never while the settings load. The group opens with the plugin manager
(superusers only) and lists the links of the plugins that are switched on.
"""

from django.conf import settings
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _

from . import installed_plugins, state


def _item(link):
    item = {"title": link.title, "icon": link.icon, "link": reverse_lazy(link.url_name)}
    if link.permission:
        item["permission"] = lambda request, perm=link.permission: request.user.has_perm(perm)
    return item


def _manager():
    return {
        "title": _("플러그인 관리"),
        "icon": "extension",
        "link": reverse_lazy("admin-plugins"),
        "permission": lambda request: request.user.is_superuser,
    }


def sidebar_navigation(request):
    groups = list(settings.G5_ADMIN_NAVIGATION)
    plugins = installed_plugins()
    if plugins:
        links = [_item(link) for plugin in plugins if state.is_enabled(plugin.slug) for link in plugin.admin_links]
        groups.append(
            {"title": _("플러그인"), "separator": True, "collapsible": True, "items": [_manager(), *links]}
        )
    return groups
