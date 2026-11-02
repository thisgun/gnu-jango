"""The plugin's hook listeners, registered by AttendanceConfig.ready()."""

from gnu_jango.plugins import hooks

from . import conf, services


@hooks.on("member.visited")
def check_in_on_visit(user, **kwargs):
    # member.visited comes on every signed-in page load; check_in() is a single lookup once done.
    if conf.value("ATTENDANCE_AUTO_CHECK_IN") and user.is_active:
        services.check_in(user)
