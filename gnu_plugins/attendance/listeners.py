"""The plugin's hook listeners, registered by AttendanceConfig.ready()."""

from django.core.cache import cache
from django.utils import timezone

from gnu_jango.plugins import hooks

from . import conf, services

VISIT_CACHE_SECONDS = 24 * 60 * 60


@hooks.on("member.visited")
def check_in_on_visit(user, **kwargs):
    if not (conf.value("ATTENDANCE_AUTO_CHECK_IN") and user.is_active):
        return
    # member.visited comes on every signed-in page load: once today's check-in is done, skip the DB.
    key = f"attendance:visited:{user.pk}:{timezone.localdate():%Y%m%d}"
    if cache.get(key):
        return
    services.check_in(user)
    cache.set(key, True, VISIT_CACHE_SECONDS)
