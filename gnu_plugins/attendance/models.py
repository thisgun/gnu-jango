from django.conf import settings
from django.db import models


class Attendance(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="attendances", verbose_name="회원"
    )
    day = models.DateField("출석일")
    streak = models.PositiveIntegerField("연속 출석일", default=1)
    point = models.IntegerField("지급 포인트", default=0)
    created_at = models.DateTimeField("출석 시각", auto_now_add=True)

    class Meta:
        verbose_name = "출석"
        verbose_name_plural = "출석체크 기록"
        ordering = ("-day", "-id")
        constraints = [models.UniqueConstraint(fields=("user", "day"), name="attendance_once_a_day")]
        indexes = [models.Index(fields=("day",), name="attendance_day_idx")]

    def __str__(self):
        return f"{self.user} {self.day:%Y-%m-%d}"
