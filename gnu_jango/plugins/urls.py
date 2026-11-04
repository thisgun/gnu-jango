"""Mounted at /plugins/: each plugin's ``urls`` at /plugins/<slug>/."""

from . import installed_plugins
from .routing import mount

urlpatterns = [mount(plugin, plugin.urls) for plugin in installed_plugins() if plugin.urls]
