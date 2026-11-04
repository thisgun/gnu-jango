"""What the core mounts for 출석체크. Read while the settings load: no model imports here."""

from gnu_jango.plugins import AdminLink, Job, Plugin, Setting, Slot

PLUGIN = Plugin(
    slug="attendance",
    title="출석체크",
    version="1.0.0",
    api_version=1,
    api_urls="gnu_plugins.attendance.api_urls",
    admin_links=(
        AdminLink(
            "출석체크 기록",
            "admin:attendance_attendance_changelist",
            icon="event_available",
            permission="attendance.view_attendance",
        ),
    ),
    # Daily: each run re-checks the last three finished months, so a bonus missed while the job was down
    # or points were off is paid later; the point ledger gives each bonus only once.
    jobs=(Job("attendance_monthly_bonus", ("--apply", "--json"), ("--json",), 86400),),
    settings=(
        Setting("ATTENDANCE_POINT", "출석 포인트", 10, "출석할 때마다 주는 포인트"),
        Setting("ATTENDANCE_STREAK_DAYS", "연속 출석 기준 일수", 7, "N일 연속마다 보너스를 더합니다. 0이면 없음"),
        Setting("ATTENDANCE_STREAK_BONUS", "연속 출석 보너스", 50),
        Setting("ATTENDANCE_MONTHLY_BONUS", "개근 보너스", 300, "한 달 매일 출석한 회원에게 다음 달에 한 번"),
        Setting("ATTENDANCE_AUTO_CHECK_IN", "방문하면 자동 출석", False, "로그인한 회원이 사이트를 열면 출석 처리"),
    ),
    slots=(Slot("home.sidebar", "gnu_plugins.attendance.widgets.home_widget"),),
)
