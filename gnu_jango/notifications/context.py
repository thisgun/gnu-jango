from contextlib import contextmanager
from contextvars import ContextVar

_suppressed = ContextVar("notification_events_suppressed", default=False)


def events_suppressed():
    return _suppressed.get()


@contextmanager
def suppress_notification_events():
    """Local to this import/task; concurrent live requests retain normal notifications."""
    token = _suppressed.set(True)
    try:
        yield
    finally:
        _suppressed.reset(token)
