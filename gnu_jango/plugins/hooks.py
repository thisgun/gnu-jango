"""Plugin hooks, the counterpart of Gnuboard5's run_event / run_replace.

- ``emit(name, **payload)`` calls every listener of ``name`` and ignores what they return.
- ``replace(name, value, **context)`` passes ``value`` through the listeners and returns the result.

Listeners run in ``priority`` order (lower first), each in its own savepoint. A listener that raises
is logged and skipped and its database writes are rolled back, so a plugin bug never breaks the
request (or the transaction) that sent the hook. Listeners run inside the request: keep them quick.
Register listeners from the plugin's ``AppConfig.ready()``; registering the same function again
replaces the earlier registration.

Hooks the core sends (docs/04-deploy/plugins.md keeps the list):
- ``member.visited`` (user, request): a member signed in, or a signed-in member loaded a page
  (/api/v1/auth/me). It can come many times a day, so listeners must be idempotent.
- ``shop.order.placed`` / ``shop.order.status_changed`` / ``shop.order.paid``: see
  gnu_jango.shop.order_hooks. They are sent after the change commits.
"""

import logging

from django.db import transaction

logger = logging.getLogger(__name__)

DEFAULT_PRIORITY = 10

# name -> [(priority, "module.qualname", function)], kept sorted by priority
_listeners = {}


def on(name, *, priority=DEFAULT_PRIORITY):
    """Decorator: run the function when the hook ``name`` is sent."""

    def register(func):
        key = f"{func.__module__}.{func.__qualname__}"
        others = [entry for entry in _listeners.get(name, ()) if entry[1] != key]
        _listeners[name] = sorted([*others, (priority, key, func)], key=lambda entry: entry[0])
        return func

    return register


def emit(name, **payload):
    for _priority, key, func in tuple(_listeners.get(name, ())):
        try:
            with transaction.atomic():
                func(**payload)
        except Exception:
            logger.exception("Plugin hook %s failed in %s", name, key)


def replace(name, value, **context):
    for _priority, key, func in tuple(_listeners.get(name, ())):
        try:
            with transaction.atomic():
                value = func(value, **context)
        except Exception:
            logger.exception("Plugin hook %s failed in %s; the value is kept", name, key)
    return value
