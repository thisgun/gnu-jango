"""Mounted at /plugins/: each plugin's ``urls`` at /plugins/<slug>/."""

from django.urls import include, path

from . import installed_plugins

urlpatterns = [path(f"{plugin.slug}/", include(plugin.urls)) for plugin in installed_plugins() if plugin.urls]
