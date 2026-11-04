from django.core.management.base import BaseCommand, CommandError

from gnu_plugins.order_notify import channels, messages


class Command(BaseCommand):
    help = "주문 알림: send a test message to every configured channel (nothing is saved)."

    def handle(self, *args, **options):
        for channel in channels.misconfigured():
            names = ", ".join(channels.CHANNEL_ENV[channel])
            self.stderr.write(f"{channels.CHANNEL_LABELS[channel]}: {names} 값의 형식이 맞지 않아 건너뜁니다.")
        targets = channels.configured()
        if not targets:
            raise CommandError("설정된 채널이 없습니다. ORDER_NOTIFY_* 환경 변수를 확인하세요.")
        failed = []
        for channel in targets:
            label = channels.CHANNEL_LABELS[channel]
            try:
                channels.send(channel, messages.TEST_TEXT)
            except channels.ChannelError as exc:
                failed.append(label)
                self.stderr.write(f"{label}: 실패 ({exc})")
                continue
            self.stdout.write(f"{label}: 보냈습니다")
        if failed:
            raise CommandError(f"보내지 못한 채널: {', '.join(failed)}")
