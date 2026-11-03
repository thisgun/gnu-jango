"""What the core mounts for 자동 등업. Read while the settings load: no model imports here.

The rules themselves (which level needs what) are rows the admin edits (models.LevelRule), so a site
can have as many levels as it uses; the settings below only choose when the rules are checked.
"""

from gnu_jango.plugins import AdminLink, Job, Plugin, Setting

PLUGIN = Plugin(
    slug="level_up",
    title="자동 등업",
    version="1.0.0",
    api_version=1,
    admin_links=(
        AdminLink(
            "등업 규칙", "admin:level_up_levelrule_changelist", icon="military_tech", permission="level_up.view_levelrule"
        ),
        AdminLink(
            "등업 기록", "admin:level_up_levelchange_changelist", icon="trending_up", permission="level_up.view_levelchange"
        ),
    ),
    # Daily: catches members whose points or posts changed without a hook (the admin, another plugin).
    jobs=(Job("level_up_sweep", ("--apply", "--json"), ("--json",), 86400),),
    settings=(
        Setting(
            "LEVEL_UP_ON_ACTIVITY",
            "활동하면 바로 등업",
            True,
            "글·댓글·출석·로그인 때 바로 확인합니다. 끄면 하루 한 번 예약 작업으로만 올립니다",
        ),
        Setting("LEVEL_UP_NOTIFY", "등업 알림 보내기", True, "레벨이 오른 회원에게 사이트 알림을 보냅니다"),
    ),
)
