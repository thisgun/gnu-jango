"""Whether each installed plugin is switched on, and the settings values saved in the admin.

Both live in Config rows ("plugin.<slug>.enabled" = "0"/"1", "plugin.<slug>.<SETTING>" = value), so
they need no migration and changes show in the audit history. An installed plugin is on until the
admin switches it off. The rows are cached for a minute; saving through this module clears the cache.
"""

from decouple import config as env_config
from django.conf import settings
from django.core.cache import cache
from django.db import transaction

from . import installed_plugin_packages, installed_plugins

CACHE_KEY = "gnu_jango:plugins:state"
CACHE_SECONDS = 60
PREFIX = "plugin."
TRUE_VALUES = {"1", "true", "yes", "on"}


def _enabled_name(slug):
    return f"{PREFIX}{slug}.enabled"


def _setting_name(slug, name):
    return f"{PREFIX}{slug}.{name}"


def _rows():
    rows = cache.get(CACHE_KEY)
    if rows is None:
        from gnu_jango.config.models import Config

        rows = dict(Config.objects.filter(name__startswith=PREFIX).values_list("name", "value"))
        cache.set(CACHE_KEY, rows, CACHE_SECONDS)
    return rows


def clear():
    cache.delete(CACHE_KEY)


def _write(values):
    """Save {config name: text} in one transaction, then drop the cached rows."""
    from gnu_jango.config.models import Config

    with transaction.atomic():
        for name, text in values.items():
            Config.objects.update_or_create(name=name, defaults={"value": text})
    transaction.on_commit(clear)
    clear()


def is_enabled(slug):
    return _rows().get(_enabled_name(slug), "1") != "0"


def set_enabled(slug, enabled):
    _write({_enabled_name(slug): "1" if enabled else "0"})


def owner_slug(module_name):
    """The slug of the installed plugin whose package holds ``module_name`` ("" for the core)."""
    for package, plugin in installed_plugin_packages():
        if module_name == package or module_name.startswith(f"{package}."):
            return plugin.slug
    return ""


def module_enabled(module_name):
    slug = owner_slug(module_name)
    return not slug or is_enabled(slug)


def _plugin(slug):
    for plugin in installed_plugins():
        if plugin.slug == slug:
            return plugin
    raise KeyError(f"No installed plugin uses the slug {slug!r}.")


def saved_value(slug, name):
    """The text saved in the admin for a setting, or None."""
    return _rows().get(_setting_name(slug, name))


def cast(default, text):
    """``text`` as the type of ``default``; ValueError when it is not one."""
    if isinstance(default, bool):
        return str(text).strip().lower() in TRUE_VALUES
    if isinstance(default, int):
        return int(str(text).strip())
    return str(text)


def setting(slug, name):
    """A plugin setting: the admin's saved value, else the Django setting, else the env var, else the default."""
    declared = _plugin(slug).setting(name)
    saved = saved_value(slug, name)
    if saved is not None:
        try:
            return cast(declared.default, saved)
        except ValueError:
            pass
    if hasattr(settings, name):
        return getattr(settings, name)
    return env_config(name, default=declared.default, cast=type(declared.default))


def save_settings(slug, values):
    """Save typed values ({setting name: value}) of a plugin's declared settings."""
    plugin = _plugin(slug)
    texts = {}
    for name, value in values.items():
        declared = plugin.setting(name)
        if isinstance(declared.default, bool):
            texts[_setting_name(slug, name)] = "1" if value else "0"
        else:
            texts[_setting_name(slug, name)] = str(value)
    _write(texts)
