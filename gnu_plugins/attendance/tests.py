"""출석체크 (the example plugin): daily check-in, streak bonus, monthly bonus, API and hooks."""

import json
from datetime import date, timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from gnu_jango.plugins import hooks
from gnu_jango.testing.factories import MemberFactory
from gnu_jango.users.point_ledger import point_balance

from .models import Attendance
from .services import check_in

pytestmark = pytest.mark.django_db

CHECK_IN_URL = "/api/v1/plugins/attendance/check-in"
ME_URL = "/api/v1/plugins/attendance/me"
TODAY = date(2026, 11, 2)


def attend(user, *days):
    for day in days:
        Attendance.objects.create(user=user, day=day, streak=1, point=0)


@override_settings(ATTENDANCE_POINT=10)
def test_the_first_check_in_of_the_day_gives_the_daily_point_once(member):
    attendance, created = check_in(member, today=TODAY)
    again, created_again = check_in(member, today=TODAY)

    assert created and not created_again
    assert again.pk == attendance.pk
    assert (attendance.streak, attendance.point) == (1, 10)
    assert point_balance(member) == 10


@override_settings(ATTENDANCE_POINT=10, ATTENDANCE_STREAK_DAYS=3, ATTENDANCE_STREAK_BONUS=50)
def test_every_streak_of_n_days_adds_the_streak_bonus(member):
    check_in(member, today=TODAY - timedelta(days=2))
    second, _ = check_in(member, today=TODAY - timedelta(days=1))
    third, _ = check_in(member, today=TODAY)

    assert (second.streak, second.point) == (2, 10)
    assert (third.streak, third.point) == (3, 60)


def test_a_missed_day_restarts_the_streak(member):
    check_in(member, today=TODAY - timedelta(days=2))
    attendance, _ = check_in(member, today=TODAY)

    assert attendance.streak == 1


@override_settings(ATTENDANCE_POINT=10)
def test_other_plugins_can_change_the_point_through_the_attendance_point_hook(member, monkeypatch):
    monkeypatch.setattr(hooks, "_listeners", {})
    hooks.on("attendance.point")(lambda point, user, streak, **kwargs: point * 3)

    attendance, _ = check_in(member, today=TODAY)

    assert attendance.point == 30


@override_settings(ATTENDANCE_POINT=10)
def test_a_listener_returning_a_non_number_leaves_the_point_alone(member, monkeypatch):
    monkeypatch.setattr(hooks, "_listeners", {})
    hooks.on("attendance.point")(lambda point, **kwargs: None)

    attendance, _ = check_in(member, today=TODAY)

    assert attendance.point == 10


def test_with_points_switched_off_the_check_in_is_kept_without_points(member):
    from gnu_jango.config.models import Config

    Config.objects.update_or_create(name="cf_use_point", defaults={"value": "0"})
    attendance, created = check_in(member, today=TODAY)

    assert created and attendance.point == 0
    assert point_balance(member) == 0


def test_the_api_needs_a_signed_in_member(api_client):
    assert api_client.post(CHECK_IN_URL).status_code in (401, 403)
    assert api_client.get(ME_URL).status_code in (401, 403)


@override_settings(ATTENDANCE_POINT=10)
def test_checking_in_through_the_api(member_client, member):
    first = member_client.post(CHECK_IN_URL)
    second = member_client.post(CHECK_IN_URL)

    assert first.status_code == 201 and second.status_code == 200
    body = first.json()["data"]
    assert body["checked_in_today"] is True and body["created"] is True and body["point"] == 10
    assert second.json()["data"]["created"] is False
    assert Attendance.objects.filter(user=member).count() == 1


def test_the_month_view_lists_the_days_attended(member_client, member):
    attend(member, date(2026, 10, 1), date(2026, 10, 2), date(2026, 9, 30))

    data = member_client.get(ME_URL, {"month": "2026-10"}).json()["data"]

    assert data["month"] == "2026-10"
    assert data["days"] == ["2026-10-01", "2026-10-02"]
    assert set(data["rules"]) == {"point", "streak_days", "streak_bonus", "monthly_bonus"}


def test_a_bad_month_is_refused(member_client):
    response = member_client.get(ME_URL, {"month": "2026-13"})

    assert response.status_code == 400


def test_a_visit_checks_in_only_when_the_site_turns_it_on(member_client, member):
    member_client.get("/api/v1/auth/me")
    assert not Attendance.objects.filter(user=member).exists()

    with override_settings(ATTENDANCE_AUTO_CHECK_IN=True):
        member_client.get("/api/v1/auth/me")
        member_client.get("/api/v1/auth/me")

    assert Attendance.objects.filter(user=member).count() == 1


def test_after_today_s_check_in_further_visits_skip_the_database(member_client, member):
    from unittest.mock import patch

    from . import services

    with override_settings(ATTENDANCE_AUTO_CHECK_IN=True), patch(
        "gnu_plugins.attendance.listeners.services.check_in", wraps=services.check_in
    ) as spy:
        for _ in range(3):
            member_client.get("/api/v1/auth/me")

    assert spy.call_count == 1
    assert Attendance.objects.filter(user=member).count() == 1


def test_the_api_limits_request_floods(member_client):
    from unittest.mock import patch

    from .api import AttendanceThrottle

    with patch.object(AttendanceThrottle, "rate", "2/min"):
        codes = [member_client.get(ME_URL).status_code for _ in range(3)]

    assert codes == [200, 200, 429]


def run_monthly_bonus(*args):
    stdout = StringIO()
    call_command("attendance_monthly_bonus", "--json", *args, stdout=stdout)
    return json.loads(stdout.getvalue())


@override_settings(ATTENDANCE_MONTHLY_BONUS=300)
def test_members_who_attended_every_day_get_the_monthly_bonus_once():
    regular, sometimes = MemberFactory(), MemberFactory()
    october = [date(2026, 10, day) for day in range(1, 32)]
    attend(regular, *october)
    attend(sometimes, *october[:30])

    preview = run_monthly_bonus("--month", "2026-10")
    applied = run_monthly_bonus("--month", "2026-10", "--apply")
    again = run_monthly_bonus("--month", "2026-10", "--apply")

    assert preview == {"month": "2026-10", "members": 1, "awarded": 0, "dry_run": True}
    assert applied["awarded"] == 1 and again["awarded"] == 0
    assert point_balance(regular) == 300 and point_balance(sometimes) == 0


def test_by_default_the_monthly_bonus_catches_up_the_last_three_months():
    report = run_monthly_bonus()

    first_of_this_month = timezone.localdate().replace(day=1)
    last_month = (first_of_this_month - timedelta(days=1)).strftime("%Y-%m")
    assert [month["month"] for month in report["months"]][0] == last_month
    assert len(report["months"]) == 3 and report["dry_run"] is True


@override_settings(ATTENDANCE_MONTHLY_BONUS=300)
def test_a_bonus_skipped_while_points_were_off_is_paid_once_they_are_back(monkeypatch):
    from gnu_jango.config.models import Config

    regular = MemberFactory()
    attend(regular, *[date(2026, 10, day) for day in range(1, 32)])
    Config.objects.update_or_create(name="cf_use_point", defaults={"value": "0"})
    assert run_monthly_bonus("--month", "2026-10", "--apply")["awarded"] == 0

    Config.objects.update_or_create(name="cf_use_point", defaults={"value": "1"})
    assert run_monthly_bonus("--month", "2026-10", "--apply")["awarded"] == 1
    assert point_balance(regular) == 300


def test_the_plugin_migrations_match_its_models():
    call_command("makemigrations", "attendance", "--check", "--dry-run", stdout=StringIO())
