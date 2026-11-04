"""What the core mounts for 주문 알림. Read while the settings load: no model imports here.

Where the messages go (webhook URLs, the Telegram bot token) is a secret, so it is read from the
environment only and never shown or saved on /admin/plugins/ (channels.CHANNEL_ENV). The settings
below choose which order events are sent.
"""

from gnu_jango.plugins import AdminLink, Job, Plugin, Setting

PLUGIN = Plugin(
    slug="order_notify",
    title="주문 알림",
    version="1.0.0",
    api_version=1,
    admin_links=(
        AdminLink(
            "주문 알림 기록",
            "admin:order_notify_ordernotice_changelist",
            icon="notifications_active",
            permission="order_notify.view_ordernotice",
        ),
    ),
    # Every 5 minutes under Celery Beat (an HTTP cron such as Vercel's runs it as often as the cron fires):
    # sends again the messages a channel refused or could not take in time, and deletes old ones.
    jobs=(Job("order_notify_retry", ("--apply", "--json"), ("--json",), 300),),
    settings=(
        Setting("ORDER_NOTIFY_PLACED", "새 주문 알림", True, "주문이 들어오면 알립니다"),
        Setting("ORDER_NOTIFY_PAID", "결제 완료 알림", True, "카드 결제가 끝나거나 입금이 확인되면 알립니다"),
        Setting("ORDER_NOTIFY_CANCELLED", "취소·반품 알림", True),
        Setting("ORDER_NOTIFY_OTHER_STATUS", "그 밖의 상태 변경 알림", False, "준비·배송·완료로 바뀔 때도 알립니다"),
        Setting("ORDER_NOTIFY_FULL_NAME", "주문자 이름 전체 표시", False, "끄면 홍*동처럼 가운데를 가립니다"),
    ),
)
