"""Checking in, the streak bonus and the monthly bonus. Points go through the core point ledger."""

import calendar
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from gnu_jango.plugins import hooks
from gnu_jango.users.point_ledger import APPLIED, insert_point

from . import conf
from .models import Attendance

# The ledger's relation for these points: one row per member and day (or month), never two.
POINT_TABLE = "@attendance"

# The default monthly-bonus run looks back this many finished months, so a bonus missed while the
# job was down or points were off is paid later; the ledger keeps each bonus to one payment.
CATCH_UP_MONTHS = 3


def rules():
    return {
        "point": conf.value("ATTENDANCE_POINT"),
        "streak_days": conf.value("ATTENDANCE_STREAK_DAYS"),
        "streak_bonus": conf.value("ATTENDANCE_STREAK_BONUS"),
        "monthly_bonus": conf.value("ATTENDANCE_MONTHLY_BONUS"),
    }


def daily_point(streak):
    point = conf.value("ATTENDANCE_POINT")
    every = conf.value("ATTENDANCE_STREAK_DAYS")
    if every > 0 and streak % every == 0:
        point += conf.value("ATTENDANCE_STREAK_BONUS")
    return point


def _hooked_point(point, **context):
    """The point after the attendance.point hook; a listener's non-number is ignored, never negative."""
    try:
        return max(0, int(hooks.replace("attendance.point", point, **context)))
    except (TypeError, ValueError):
        return point


def check_in(user, *, today=None):
    """Today's attendance of ``user`` and whether this call created it (with its points).

    Other plugins may change the points through the ``attendance.point`` hook (point, user, streak,
    day) and hear about each check-in through ``attendance.checked_in`` (attendance).
    """
    today = today or timezone.localdate()
    existing = Attendance.objects.filter(user=user, day=today).first()
    if existing:
        return existing, False

    previous = Attendance.objects.filter(user=user, day=today - timedelta(days=1)).values_list("streak", flat=True)
    streak = (previous.first() or 0) + 1
    point = _hooked_point(daily_point(streak), user=user, streak=streak, day=today)
    try:
        with transaction.atomic():
            attendance = Attendance.objects.create(user=user, day=today, streak=streak)
            awarded = insert_point(user, point, f"{today:%Y-%m-%d} 출석체크", POINT_TABLE, user.pk, f"{today:%Y-%m-%d}")
            if awarded == APPLIED:
                attendance.point = point
                attendance.save(update_fields=["point"])
    except IntegrityError:  # a parallel request checked in first
        return Attendance.objects.get(user=user, day=today), False

    hooks.emit("attendance.checked_in", attendance=attendance)
    return attendance, True


def last_day(month):
    return month.replace(day=calendar.monthrange(month.year, month.month)[1])


def parse_month(text):
    """The first day of a "YYYY-MM" month, or None."""
    try:
        year, month = (int(part) for part in str(text).split("-"))
        return date(year, month, 1)
    except ValueError:
        return None


def last_month(today=None):
    return ((today or timezone.localdate()).replace(day=1) - timedelta(days=1)).replace(day=1)


def recent_months(count=CATCH_UP_MONTHS, today=None):
    """The first days of the last ``count`` finished months, newest first."""
    months = [last_month(today)]
    while len(months) < count:
        months.append(last_month(months[-1]))
    return months


def summary(user, month=None):
    today = timezone.localdate()
    month = month or today.replace(day=1)
    days = Attendance.objects.filter(user=user, day__range=(month, last_day(month))).order_by("day")
    latest = Attendance.objects.filter(user=user, day__in=(today, today - timedelta(days=1))).order_by("-day").first()
    return {
        "today": f"{today:%Y-%m-%d}",
        "checked_in_today": bool(latest and latest.day == today),
        "streak": latest.streak if latest else 0,
        "month": f"{month:%Y-%m}",
        "days": [f"{day:%Y-%m-%d}" for day in days.values_list("day", flat=True)],
        "rules": rules(),
    }


def perfect_attendance(month):
    """The ids of the members who checked in on every day of ``month``."""
    days_in_month = last_day(month).day
    return list(
        Attendance.objects.filter(day__range=(month, last_day(month)))
        .order_by()
        .values("user")
        .annotate(days=Count("day", distinct=True))
        .filter(days=days_in_month)
        .values_list("user", flat=True)
    )


def award_monthly_bonus(month, *, apply):
    user_ids = perfect_attendance(month)
    awarded = 0
    if apply:
        bonus = conf.value("ATTENDANCE_MONTHLY_BONUS")
        label = f"{month:%Y-%m}"
        for user in get_user_model().objects.filter(pk__in=user_ids, is_active=True):
            if insert_point(user, bonus, f"{label} 개근 보너스", POINT_TABLE, user.pk, f"monthly-{label}") == APPLIED:
                awarded += 1
    return {"month": f"{month:%Y-%m}", "members": len(user_ids), "awarded": awarded, "dry_run": not apply}
