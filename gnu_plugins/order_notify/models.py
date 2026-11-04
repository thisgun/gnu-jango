from django.db import models


class OrderNotice(models.Model):
    """One message to one channel: the send log, and the queue of messages to send again."""

    PENDING = "pending"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    STATUS_CHOICES = ((PENDING, "보낼 예정"), (SENDING, "보내는 중"), (SENT, "보냄"), (FAILED, "실패"))
    EVENT_CHOICES = (
        ("placed", "새 주문"),
        ("paid", "결제 완료"),
        ("cancelled", "취소·반품"),
        ("status", "상태 변경"),
    )
    CHANNEL_CHOICES = (("discord", "Discord"), ("slack", "Slack"), ("telegram", "Telegram"))

    od_id = models.CharField("주문번호", max_length=40)
    event = models.CharField("알림 종류", max_length=20, choices=EVENT_CHOICES)
    # What makes the message unique for its order: the event, plus the statuses of a status change.
    key = models.CharField(max_length=120)
    channel = models.CharField("채널", max_length=20, choices=CHANNEL_CHOICES)
    text = models.TextField("내용")
    status = models.CharField("상태", max_length=10, choices=STATUS_CHOICES, default=PENDING)
    attempts = models.PositiveSmallIntegerField("보낸 횟수", default=0)
    last_error = models.CharField("마지막 오류", max_length=255, blank=True, default="")
    created_at = models.DateTimeField("만든 시각", auto_now_add=True)
    # When a sender took the notice (status "sending"); one left there too long is released again.
    claimed_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField("보낸 시각", null=True, blank=True)

    class Meta:
        verbose_name = "주문 알림"
        verbose_name_plural = "주문 알림 기록"
        ordering = ("-created_at", "-id")
        constraints = [
            models.UniqueConstraint(fields=("od_id", "key", "channel"), name="order_notice_once_per_channel")
        ]
        indexes = [models.Index(fields=("status", "created_at"), name="order_notice_queue_idx")]

    def __str__(self):
        return f"{self.od_id} {self.get_event_display()} → {self.get_channel_display()}"
