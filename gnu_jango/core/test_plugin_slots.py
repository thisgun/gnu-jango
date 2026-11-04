"""Theme slots for plugins: GET /api/v1/plugins/slots?name=... returns the widgets plugins put there."""

import sys
from types import ModuleType

import pytest
from django.core.exceptions import ImproperlyConfigured

from gnu_jango.plugins import Plugin, load_plugins, state
from gnu_jango.plugins.slots import clean_widget
from gnu_plugins.attendance.services import check_in

pytestmark = pytest.mark.django_db

SLOTS_URL = "/api/v1/plugins/slots"


def widgets(client, name="home.sidebar"):
    response = client.get(SLOTS_URL, {"name": name})
    assert response.status_code == 200, response.content[:300]
    assert "no-store" in response["Cache-Control"]
    return response.json()["data"]["widgets"]


def test_a_slot_name_is_required(api_client):
    assert api_client.get(SLOTS_URL).status_code == 400


def test_a_slot_no_plugin_fills_is_empty(api_client):
    assert widgets(api_client, "nowhere.at_all") == []
    assert api_client.get(SLOTS_URL, {"name": "bad name"}).status_code == 400


def test_a_visitor_sees_the_attendance_widget_with_a_sign_in_action(api_client):
    [widget] = widgets(api_client)

    assert widget["plugin"] == "attendance" and widget["title"] == "출석체크"
    assert [action["method"] for action in widget["actions"]] == ["GET"]


def test_a_member_sees_a_check_in_button_until_checked_in(member_client, member):
    [before] = widgets(member_client)
    assert before["actions"] == [
        {"label": "출석하기", "method": "POST", "url": "/api/v1/plugins/attendance/check-in", "primary": True}
    ]

    check_in(member)
    [after] = widgets(member_client)

    assert after["actions"] == []
    assert {"label": "연속 출석", "value": "1일"} in after["stats"]


def test_a_switched_off_plugin_fills_no_slot(member_client):
    state.set_enabled("attendance", False)

    assert widgets(member_client) == []


def test_a_failing_provider_is_left_out(member_client, monkeypatch):
    def broken(request):
        raise RuntimeError("plugin bug")

    monkeypatch.setattr("gnu_plugins.attendance.widgets.home_widget", broken)

    assert widgets(member_client) == []


def test_widgets_keep_only_known_fields_and_site_paths():
    widget = clean_widget(
        {
            "title": "T",
            "body": 3,
            "script": "<script>",
            "stats": [{"label": "a", "value": 1}, "junk"],
            "actions": [
                {"label": "ok", "method": "post", "url": "/api/x"},
                {"label": "js", "method": "GET", "url": "javascript:alert(1)"},
                {"label": "elsewhere", "method": "GET", "url": "//evil.example/"},
                {"label": "put", "method": "PUT", "url": "/api/y"},
            ],
        }
    )

    assert widget == {
        "title": "T",
        "body": "3",
        "stats": [{"label": "a", "value": "1"}],
        "actions": [{"label": "ok", "method": "POST", "url": "/api/x", "primary": False}],
    }


def test_slots_is_not_a_plugin_slug(monkeypatch):
    package, manifest = ModuleType("fake_slots_plugin"), ModuleType("fake_slots_plugin.plugin")
    package.__path__ = []
    manifest.PLUGIN = Plugin(slug="slots", title="Slots", api_version=1)
    monkeypatch.setitem(sys.modules, "fake_slots_plugin", package)
    monkeypatch.setitem(sys.modules, "fake_slots_plugin.plugin", manifest)

    with pytest.raises(ImproperlyConfigured, match="reserved"):
        load_plugins(["fake_slots_plugin"])
