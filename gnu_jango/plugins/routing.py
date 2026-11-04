"""Mount a plugin's URLconf so that its URLs answer 404 while the admin has the plugin switched off.

The switch is read when the view runs, not while the URL is resolved: under ASGI (Vercel) Django
resolves URLs in the event loop, where the database (and so a db:// cache) may not be touched. A
sync view runs in a worker thread there, and an async view reads the switch through sync_to_async.
"""

import functools

from asgiref.sync import iscoroutinefunction, sync_to_async
from django.http import Http404
from django.urls import URLResolver, include
from django.urls.resolvers import RoutePattern

from . import state


def _check_enabled(slug):
    if not state.is_enabled(slug):
        raise Http404("This plugin is switched off.")


def switched(slug, view):
    """``view``, answering 404 while the plugin ``slug`` is switched off."""
    if iscoroutinefunction(view):

        @functools.wraps(view)
        async def switched_async_view(*args, **kwargs):
            await sync_to_async(_check_enabled)(slug)
            return await view(*args, **kwargs)

        return switched_async_view

    @functools.wraps(view)
    def switched_view(*args, **kwargs):
        _check_enabled(slug)
        return view(*args, **kwargs)

    return switched_view


class PluginURLResolver(URLResolver):
    def __init__(self, slug, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.slug = slug

    def resolve(self, path):
        match = super().resolve(path)
        # The match is new for this request; the enclosing resolvers build theirs from its func.
        match.func = switched(self.slug, match.func)
        return match


def mount(plugin, urlconf):
    """``path(f"{plugin.slug}/", include(urlconf))``, switched by the plugin's admin state."""
    urlconf_module, app_name, namespace = include(urlconf)
    return PluginURLResolver(
        plugin.slug,
        RoutePattern(f"{plugin.slug}/", is_endpoint=False),
        urlconf_module,
        app_name=app_name,
        namespace=namespace,
    )
