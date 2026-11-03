from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

# Level 1 is a visitor and 10 the site admin (Gnuboard5): a rule can only give 2-9.
MIN_LEVEL = 2
MAX_LEVEL = 9
ATTENDANCE_APP = "gnu_plugins.attendance"


class LevelRule(models.Model):
    """The member reaches ``level`` once every condition is met; 0 means the condition is not used."""

    level = models.PositiveSmallIntegerField(
        "올려 줄 레벨", unique=True, validators=[MinValueValidator(MIN_LEVEL), MaxValueValidator(MAX_LEVEL)]
    )
    min_points = models.PositiveIntegerField("보유 포인트", default=0)
    min_posts = models.PositiveIntegerField("쓴 글 수", default=0)
    min_comments = models.PositiveIntegerField("쓴 댓글 수", default=0)
    min_days = models.PositiveIntegerField("가입 후 일수", default=0)
    min_attendance = models.PositiveIntegerField("출석 일수", default=0, help_text="출석체크 플러그인이 있어야 씁니다")
    is_active = models.BooleanField("사용", default=True)
    updated_at = models.DateTimeField("바꾼 시각", auto_now=True)

    class Meta:
        verbose_name = "등업 규칙"
        verbose_name_plural = "등업 규칙"
        ordering = ("level",)
        # Also for rows made outside the admin form (shell, fixtures): never level 1 or 10.
        constraints = [
            models.CheckConstraint(
                condition=models.Q(level__gte=MIN_LEVEL, level__lte=MAX_LEVEL), name="level_rule_level_2_to_9"
            )
        ]

    def __str__(self):
        return f"레벨 {self.level}"

    def clean(self):
        if self.min_attendance and not apps.is_installed(ATTENDANCE_APP):
            raise ValidationError({"min_attendance": "출석체크 플러그인이 설치되어 있지 않아 이 조건을 채울 수 없습니다."})


class LevelChange(models.Model):
    """A level the plugin gave: who, from which level to which, and what the member had then."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="level_changes", verbose_name="회원"
    )
    old_level = models.PositiveSmallIntegerField("이전 레벨")
    new_level = models.PositiveSmallIntegerField("새 레벨")
    reason = models.CharField("그때 활동", max_length=255, blank=True, default="")
    created_at = models.DateTimeField("올린 시각", auto_now_add=True)

    class Meta:
        verbose_name = "등업"
        verbose_name_plural = "등업 기록"
        ordering = ("-created_at", "-id")

    def __str__(self):
        return f"{self.user} {self.old_level}→{self.new_level}"
