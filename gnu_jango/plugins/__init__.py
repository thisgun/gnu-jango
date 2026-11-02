"""Plugins: Django apps listed in ``G5_PLUGINS`` that add features without editing the core.

A plugin package holds

- ``plugin.py`` with ``PLUGIN = Plugin(...)``: the URLs, admin links and scheduled jobs the core
  mounts for it. The core reads it while the settings load (the Celery Beat schedule needs the
  jobs), so it must not import models or anything that needs the app registry;
- an ordinary Django app (``apps.py``, models, migrations, admin) whose ``AppConfig.ready()``
  imports the module that registers its hooks (``gnu_jango.plugins.hooks``).

See docs/04-deploy/plugins.md.
"""

import re
from dataclasses import dataclass
from importlib import import_module

from django.core.exceptions import ImproperlyConfigured

# A slug is part of the plugin's URLs: /plugins/<slug>/ and /api/v1/plugins/<slug>/.
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


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
class Plugin:
    slug: str
    title: str
    version: str = "0.1.0"
    urls: str = ""  # URLconf module mounted at /plugins/<slug>/
    api_urls: str = ""  # URLconf module mounted at /api/v1/plugins/<slug>/
    admin_links: tuple[AdminLink, ...] = ()
    jobs: tuple[Job, ...] = ()


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
            f"{module_name}: the slug {plugin.slug!r} must be 2-40 lowercase letters, digits or _."
        )
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


def installed_plugins():
    """The manifests of the plugins this site runs (settings.G5_PLUGINS)."""
    from django.conf import settings

    return load_plugins(getattr(settings, "G5_PLUGINS", ()) or ())
