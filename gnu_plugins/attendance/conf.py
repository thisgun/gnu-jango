"""The plugin's settings, declared in plugin.py: the admin's saved value, else the Django setting,
else the environment variable, else the declared default (gnu_jango.plugins.state.setting)."""

from gnu_jango.plugins import state

from .plugin import PLUGIN


def value(name):
    return state.setting(PLUGIN.slug, name)
