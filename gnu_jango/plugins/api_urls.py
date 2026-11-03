"""Mounted at /api/v1/plugins/: each plugin's ``api_urls`` at /api/v1/plugins/<slug>/.

Plugin endpoints are not part of the core API contract (openapi/schema.json), so their views should
use @extend_schema(exclude=True).
"""

from django.urls import include, path

from . import installed_plugins

urlpatterns = [
    path(f"{plugin.slug}/", include(plugin.api_urls)) for plugin in installed_plugins() if plugin.api_urls
]
