"""Plugins: Django apps listed in ``G5_PLUGINS`` that add features without editing the core.

A plugin package holds

- ``plugin.py`` with ``PLUGIN = Plugin(...)``: the URLs, admin links, scheduled jobs and settings
  the core mounts for it. The core reads it while the settings load (the Celery Beat schedule needs
  the jobs), so it must not import models or anything that needs the app registry;
- an ordinary Django app (``apps.py``, models, migrations, admin) whose ``AppConfig.ready()``
  imports the module that registers its hooks (``gnu_jango.plugins.hooks``).

Installing a plugin (G5_PLUGINS) takes a deploy; switching an installed one off and on, and editing
its settings, happen in the admin (/admin/plugins/, gnu_jango.plugins.state).

See docs/04-deploy/plugins.md.
"""

import re
from dataclasses import dataclass
from importlib import import_module

from django.core.exceptions import ImproperlyConfigured

# A slug is part of the plugin's URLs (/plugins/<slug>/, /api/v1/plugins/<slug>/) and of the Config
# names that hold its state ("plugin.<slug>.enabled"), whose column takes 50 characters.
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,29}$")
SETTING_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{1,59}$")
SLOT_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
# /api/v1/plugins/slots is the core's own endpoint.
RESERVED_SLUGS = {"slots"}
CONFIG_NAME_LENGTH = 50
SETTING_TYPES = (bool, int, str)

# The version of this contract (Plugin, hooks, mounts). A change that breaks existing plugins raises
# it; a plugin declares the version it was written for and the core refuses any other.
PLUGIN_API_VERSION = 1


@dataclass(frozen=True)
class Job:
    """A management command the scheduler runs (core.scheduled_jobs.ScheduledJob)."""

    command: str
    apply_args: tuple[str, ...] = ()
    dry_run_args: tuple[str, ...] = ("--dry-run",)
    interval_seconds: int = 3600


@dataclass(frozen=True)
class AdminLink:
    """An item of the admin sidebar's plugin group; ``permission`` is "app_label.codename"."""

    title: str
    url_name: str
    icon: str = "extension"
    permission: str = ""


@dataclass(frozen=True)
class Setting:
    """A value the admin may edit on /admin/plugins/; its type is the type of ``default``."""

    name: str
    label: str
    default: bool | int | str
    help: str = ""


@dataclass(frozen=True)
class Slot:
    """A widget the plugin puts in a theme slot (e.g. "home.sidebar").

    ``provider`` is the dotted path of a function(request) that returns the widget as a dict - title,
    body, stats [{label, value}], actions [{label, method GET/POST, url (a site path), primary}] - or
    None to show nothing (gnu_jango.plugins.slots)."""

    name: str
    provider: str


@dataclass(frozen=True)
class Plugin:
    slug: str
    title: str
    version: str = "0.1.0"
    urls: str = ""  # URLconf module mounted at /plugins/<slug>/
    api_urls: str = ""  # URLconf module mounted at /api/v1/plugins/<slug>/
    admin_links: tuple[AdminLink, ...] = ()
    jobs: tuple[Job, ...] = ()
    settings: tuple[Setting, ...] = ()
    slots: tuple[Slot, ...] = ()
    api_version: int = 0  # must be declared: the PLUGIN_API_VERSION the plugin was written for

    def setting(self, name):
        for setting in self.settings:
            if setting.name == name:
                return setting
        raise KeyError(f"The plugin {self.slug!r} declares no setting {name!r}.")


def _check_settings(module_name, plugin):
    for setting in plugin.settings:
        if not SETTING_NAME_PATTERN.match(setting.name):
            raise ImproperlyConfigured(f"{module_name}: the setting {setting.name!r} must be UPPER_CASE.")
        if not isinstance(setting.default, SETTING_TYPES):
            raise ImproperlyConfigured(f"{module_name}: {setting.name} needs a bool, int or str default.")
        if len(f"plugin.{plugin.slug}.{setting.name}") > CONFIG_NAME_LENGTH:
            raise ImproperlyConfigured(f"{module_name}: the slug and {setting.name} together are too long.")
    names = [setting.name for setting in plugin.settings]
    if len(set(names)) != len(names):
        raise ImproperlyConfigured(f"{module_name} declares a setting twice.")


def _manifest(name):
    module_name = f"{name}.plugin"
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name not in (name, module_name):
            raise
        raise ImproperlyConfigured(f"G5_PLUGINS lists {name!r}, which has no plugin.py.") from exc
    plugin = getattr(module, "PLUGIN", None)
    if not isinstance(plugin, Plugin):
        raise ImproperlyConfigured(f"{module_name} must define PLUGIN = Plugin(...).")
    if not SLUG_PATTERN.match(plugin.slug):
        raise ImproperlyConfigured(
            f"{module_name}: the slug {plugin.slug!r} must be 2-30 lowercase letters, digits or _."
        )
    if plugin.slug in RESERVED_SLUGS:
        raise ImproperlyConfigured(f"{module_name}: the slug {plugin.slug!r} is reserved by the core.")
    if plugin.api_version != PLUGIN_API_VERSION:
        raise ImproperlyConfigured(
            f"{module_name} declares api_version={plugin.api_version}; this core supports "
            f"api_version={PLUGIN_API_VERSION}."
        )
    _check_settings(module_name, plugin)
    for slot in plugin.slots:
        if not SLOT_NAME_PATTERN.match(slot.name):
            raise ImproperlyConfigured(f"{module_name}: the slot name {slot.name!r} must look like home.sidebar.")
    return plugin


def load_plugins(names):
    """The manifests of the given plugin packages, in order; refuses a missing or repeated plugin."""
    plugins = []
    for name in names:
        plugin = _manifest(name)
        if any(other.slug == plugin.slug for other in plugins):
            raise ImproperlyConfigured(f"Two plugins in G5_PLUGINS use the slug {plugin.slug!r}.")
        plugins.append(plugin)
    return tuple(plugins)


def _installed_names():
    from django.conf import settings

    return tuple(getattr(settings, "G5_PLUGINS", ()) or ())


def installed_plugins():
    """The manifests of the plugins this site runs (settings.G5_PLUGINS)."""
    return load_plugins(_installed_names())


def installed_plugin_packages():
    """(package name, manifest) of each installed plugin."""
    names = _installed_names()
    return tuple(zip(names, load_plugins(names)))
