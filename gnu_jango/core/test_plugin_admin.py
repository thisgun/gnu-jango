"""Switching installed plugins on and off, and editing their settings, in the admin (/admin/plugins/)."""

import pytest
from asgiref.sync import async_to_sync
from django.test import AsyncClient, override_settings

from gnu_jango.core import scheduled_jobs
from gnu_jango.plugins import state
from gnu_jango.plugins.navigation import sidebar_navigation
from gnu_jango.testing.factories import AdminFactory, MemberFactory
from gnu_plugins.attendance.models import Attendance
from gnu_plugins.attendance.services import check_in

pytestmark = pytest.mark.django_db

ADMIN_URL = "/admin/plugins/"
CHECK_IN_URL = "/api/v1/plugins/attendance/check-in"
SETTINGS_FORM = {
    "slug": "attendance",
    "action": "save",
    "ATTENDANCE_POINT": "25",
    "ATTENDANCE_STREAK_DAYS": "7",
    "ATTENDANCE_STREAK_BONUS": "50",
    "ATTENDANCE_MONTHLY_BONUS": "300",
}


def test_an_installed_plugin_starts_switched_on():
    assert state.is_enabled("attendance")


def test_a_switched_off_plugin_s_urls_answer_404(member_client):
    state.set_enabled("attendance", False)
    assert member_client.post(CHECK_IN_URL).status_code == 404

    state.set_enabled("attendance", True)
    assert member_client.post(CHECK_IN_URL).status_code == 201


@override_settings(ATTENDANCE_AUTO_CHECK_IN=True)
def test_plugin_urls_resolve_under_asgi():
    # Under ASGI (Vercel) Django resolves URLs in the event loop, where the database and a db://
    # cache may not be touched; the on/off switch must be read only once the view runs.
    client = AsyncClient()

    assert async_to_sync(client.post)(CHECK_IN_URL).status_code == 401
    assert async_to_sync(client.get)("/api/v1/plugins/no-such-plugin/x").status_code == 404


def test_a_switched_off_plugin_s_urls_answer_404_under_asgi():
    state.set_enabled("attendance", False)

    assert async_to_sync(AsyncClient().post)(CHECK_IN_URL).status_code == 404


def test_a_switched_off_plugin_s_listeners_do_not_run(member_client, member):
    state.set_enabled("attendance", False)

    member_client.get("/api/v1/auth/me")

    assert not Attendance.objects.filter(user=member).exists()


def test_a_switched_off_plugin_s_jobs_are_skipped_not_failed():
    state.set_enabled("attendance", False)
    job = scheduled_jobs.select_jobs(["attendance_monthly_bonus"])[0]

    def runner(*args, **kwargs):
        raise AssertionError("a switched-off plugin's job must not run")

    report = scheduled_jobs.run_scheduled_jobs(jobs=[job], runner=runner)

    assert report["jobs"][0]["status"] == "skipped"
    assert report["ok"] and report["failed"] == 0


def test_the_sidebar_hides_a_switched_off_plugin_but_keeps_the_manager(rf):
    request = rf.get("/admin/")
    request.user = AdminFactory()
    state.set_enabled("attendance", False)
    state.set_enabled("order_notify", False)
    state.set_enabled("level_up", False)

    items = sidebar_navigation(request)[-1]["items"]

    assert [str(item["link"]) for item in items] == ["/admin/plugins/"]
    assert items[0]["permission"](request) is True
    request.user = MemberFactory(is_staff=True)
    assert items[0]["permission"](request) is False


def test_only_superusers_open_the_plugin_admin(client):
    client.force_login(MemberFactory(is_staff=True))

    assert client.get(ADMIN_URL).status_code == 403
    assert client.post(ADMIN_URL, {"slug": "attendance", "action": "disable"}).status_code == 403
    assert state.is_enabled("attendance")


def test_the_plugin_admin_switches_plugins_and_saves_their_settings(admin_client, member_client):
    page = admin_client.get(ADMIN_URL)
    assert page.status_code == 200
    assert "출석체크" in page.content.decode() and "ATTENDANCE_POINT" in page.content.decode()

    admin_client.post(ADMIN_URL, {"slug": "attendance", "action": "disable"})
    assert not state.is_enabled("attendance")
    admin_client.post(ADMIN_URL, {"slug": "attendance", "action": "enable"})
    assert state.is_enabled("attendance")

    response = admin_client.post(ADMIN_URL, SETTINGS_FORM)

    assert response.status_code == 302
    assert state.setting("attendance", "ATTENDANCE_AUTO_CHECK_IN") is False  # unchecked box
    assert member_client.post(CHECK_IN_URL).json()["data"]["point"] == 25


def test_a_bad_number_saves_nothing(admin_client):
    response = admin_client.post(ADMIN_URL, {**SETTINGS_FORM, "ATTENDANCE_POINT": "lots"}, follow=True)

    assert "ATTENDANCE_POINT" in response.content.decode()
    assert state.saved_value("attendance", "ATTENDANCE_POINT") is None
    assert state.saved_value("attendance", "ATTENDANCE_STREAK_DAYS") is None


def test_an_unknown_plugin_is_refused(admin_client):
    response = admin_client.post(ADMIN_URL, {"slug": "nope", "action": "disable"})

    assert response.status_code == 400


@override_settings(ATTENDANCE_POINT=10)
def test_a_value_saved_in_the_admin_wins_over_the_django_setting(member):
    state.save_settings("attendance", {"ATTENDANCE_POINT": 40})

    attendance, _ = check_in(member)

    assert attendance.point == 40
