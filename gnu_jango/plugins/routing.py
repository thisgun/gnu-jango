"""Mount a plugin's URLconf so that its URLs answer 404 while the admin has the plugin switched off."""

from django.urls import URLResolver, include
from django.urls.exceptions import Resolver404
from django.urls.resolvers import RoutePattern

from . import state


class PluginURLResolver(URLResolver):
    def __init__(self, slug, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.slug = slug

    def resolve(self, path):
        if not state.is_enabled(self.slug):
            raise Resolver404({"tried": [], "path": path})
        return super().resolve(path)


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
