"""/admin/plugins/: the installed plugins, switched on and off, and their settings (superusers only).

Installing a plugin takes G5_PLUGINS and a deploy; this page only switches installed ones and edits
the settings their plugin.py declares.
"""

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseBadRequest, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.translation import gettext as _

from . import installed_plugins, state

ACTIONS = {"enable", "disable", "save"}


def _kind(default):
    if isinstance(default, bool):
        return "bool"
    return "int" if isinstance(default, int) else "str"


def _rows():
    return [
        {
            "plugin": plugin,
            "enabled": state.is_enabled(plugin.slug),
            "settings": [
                {
                    "setting": setting,
                    "kind": _kind(setting.default),
                    "value": state.setting(plugin.slug, setting.name),
                    "saved": state.saved_value(plugin.slug, setting.name) is not None,
                }
                for setting in plugin.settings
            ],
        }
        for plugin in installed_plugins()
    ]


def _parse(plugin, post):
    """({name: typed value}, [names that are not numbers]); an unchecked box is False."""
    values, errors = {}, []
    for setting in plugin.settings:
        if isinstance(setting.default, bool):
            values[setting.name] = setting.name in post
            continue
        try:
            values[setting.name] = state.cast(setting.default, post.get(setting.name, ""))
        except ValueError:
            errors.append(setting.name)
    return values, errors


def _apply(request, plugin, action):
    if action in ("enable", "disable"):
        state.set_enabled(plugin.slug, action == "enable")
        done = _("켰습니다") if action == "enable" else _("껐습니다")
        messages.success(request, _("%(title)s 플러그인을 %(done)s.") % {"title": plugin.title, "done": done})
        return
    values, errors = _parse(plugin, request.POST)
    if errors:
        messages.error(request, _("숫자가 아닌 값이 있어 저장하지 않았습니다: %(names)s") % {"names": ", ".join(errors)})
        return
    state.save_settings(plugin.slug, values)
    messages.success(request, _("%(title)s 설정을 저장했습니다.") % {"title": plugin.title})


def plugin_settings(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    if request.method == "POST":
        slug, action = request.POST.get("slug", ""), request.POST.get("action", "")
        plugin = next((plugin for plugin in installed_plugins() if plugin.slug == slug), None)
        if plugin is None or action not in ACTIONS:
            return HttpResponseBadRequest("Unknown plugin or action.")
        _apply(request, plugin, action)
        return HttpResponseRedirect(reverse("admin-plugins"))

    context = {**admin.site.each_context(request), "title": _("플러그인 관리"), "rows": _rows()}
    request.current_app = admin.site.name
    return TemplateResponse(request, "admin/plugins/plugin_settings.html", context)
