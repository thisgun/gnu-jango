"""Theme slots: widgets that plugins put in named places of the theme ("home.sidebar").

GET /api/v1/plugins/slots?name=home.sidebar returns {"name", "widgets"} from the plugins that are
switched on. A widget is plain data that the theme draws with one renderer, never plugin HTML:

    {plugin, title, body, stats: [{label, value}], actions: [{label, method, url, primary}]}

Only GET actions (links) and POST actions (buttons that call the API) are kept, and only for site
paths, so a widget cannot point the page at another site or a javascript: URL. A provider that
raises is logged and left out. The answer is per member, so it is never cached.
"""

import logging

from django.utils.module_loading import import_string
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny

from gnu_jango.api.response import api_error, api_response

from . import SLOT_NAME_PATTERN, installed_plugins, state

logger = logging.getLogger(__name__)

ACTION_METHODS = {"GET", "POST"}
MAX_TEXT_LENGTH = 300


def _text(value):
    return str("" if value is None else value)[:MAX_TEXT_LENGTH]


def _is_site_path(url):
    url = str(url or "")
    return url.startswith("/") and not url.startswith("//") and "\\" not in url


def clean_widget(widget):
    """The known fields of a provider's widget, as text; actions only for site paths and GET/POST."""
    stats = [
        {"label": _text(stat.get("label")), "value": _text(stat.get("value"))}
        for stat in widget.get("stats") or ()
        if isinstance(stat, dict)
    ]
    actions = []
    for action in widget.get("actions") or ():
        if not isinstance(action, dict):
            continue
        method = str(action.get("method") or "GET").upper()
        if method in ACTION_METHODS and _is_site_path(action.get("url")):
            actions.append(
                {
                    "label": _text(action.get("label")),
                    "method": method,
                    "url": str(action["url"]),
                    "primary": bool(action.get("primary")),
                }
            )
    return {"title": _text(widget.get("title")), "body": _text(widget.get("body")), "stats": stats, "actions": actions}


def widgets(request, name):
    found = []
    for plugin in installed_plugins():
        if not state.is_enabled(plugin.slug):
            continue
        for slot in plugin.slots:
            if slot.name != name:
                continue
            try:
                widget = import_string(slot.provider)(request)
            except Exception:
                logger.exception("Plugin slot %s failed in %s", name, plugin.slug)
                continue
            if isinstance(widget, dict):
                found.append({"plugin": plugin.slug, **clean_widget(widget)})
    return found


@never_cache
@extend_schema(exclude=True)
@api_view(["GET"])
@permission_classes([AllowAny])
def slots_view(request):
    name = request.query_params.get("name", "")
    if not SLOT_NAME_PATTERN.match(name):
        return api_error("name must look like home.sidebar.", status=400, code="invalid_slot")
    return api_response(data={"name": name, "widgets": widgets(request, name)})
