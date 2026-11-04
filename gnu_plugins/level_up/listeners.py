"""The plugin's hook listeners, registered by LevelUpConfig.ready(): each activity that can move a
member past a rule checks that member at once (LEVEL_UP_ON_ACTIVITY); the daily sweep catches the rest."""

from django.core.cache import cache
from django.utils import timezone

from gnu_jango.plugins import hooks

from . import conf, services

VISIT_CACHE_SECONDS = 24 * 60 * 60


def _check(user):
    if user is not None and conf.value("LEVEL_UP_ON_ACTIVITY"):
        services.check(user)


@hooks.on("bbs.post.created")
def check_after_post(user=None, **kwargs):
    _check(user)


@hooks.on("bbs.comment.created")
def check_after_comment(user=None, **kwargs):
    _check(user)


@hooks.on("member.joined")
def check_after_joining(user, **kwargs):
    _check(user)  # a rule with no conditions (or only points the sign-up gives) applies at once


@hooks.on("attendance.checked_in")
def check_after_attendance(attendance, **kwargs):
    _check(attendance.user)


@hooks.on("member.visited")
def check_on_the_first_visit_of_the_day(user, **kwargs):
    # member.visited comes on every signed-in page load: once a day is enough for "days since joining".
    # The key is taken first, so a failing check is not retried on every page. Once a day per member
    # needs a shared cache (CACHE_URL); a per-process cache checks once per process, which is only slower.
    key = f"level_up:visited:{user.pk}:{timezone.localdate():%Y%m%d}"
    if cache.add(key, True, VISIT_CACHE_SECONDS):
        _check(user)
