"""Mounted at /api/v1/plugins/: each plugin's ``api_urls`` at /api/v1/plugins/<slug>/.

Plugin endpoints are not part of the core API contract (openapi/schema.json), so their views should
use @extend_schema(exclude=True).
"""

from . import installed_plugins
from .routing import mount

urlpatterns = [mount(plugin, plugin.api_urls) for plugin in installed_plugins() if plugin.api_urls]
