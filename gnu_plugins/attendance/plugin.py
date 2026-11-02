"""What the core mounts for 출석체크. Read while the settings load: no model imports here."""

from gnu_jango.plugins import AdminLink, Job, Plugin

PLUGIN = Plugin(
    slug="attendance",
    title="출석체크",
    version="1.0.0",
    api_urls="gnu_plugins.attendance.api_urls",
    admin_links=(
        AdminLink(
            "출석체크 기록",
            "admin:attendance_attendance_changelist",
            icon="event_available",
            permission="attendance.view_attendance",
        ),
    ),
    # Daily: last month's bonus is paid on the first run of the month (a missed day is caught up later
    # that month, not after it ends); the point ledger gives each bonus only once.
    jobs=(Job("attendance_monthly_bonus", ("--apply", "--json"), ("--json",), 86400),),
)
