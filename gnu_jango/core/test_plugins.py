"""The plugin seams (gnu_jango.plugins): manifests, hooks, URLs, admin sidebar and scheduled jobs.

The test suite installs the example plugin (gnu_plugins.attendance) through G5_PLUGINS, so these tests
see the seams the way a site with that plugin does.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest
from django.apps import apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import RequestFactory
from django.urls import reverse

from gnu_jango.core import scheduled_jobs
from gnu_jango.core.job_registry import build_scheduled_jobs
from gnu_jango.plugins import Plugin, hooks, installed_plugins, load_plugins
from gnu_jango.plugins.navigation import sidebar_navigation
from gnu_jango.testing.factories import AdminFactory, MemberFactory


@pytest.fixture
def no_listeners(monkeypatch):
    """A clean hook registry, so a test sees only the listeners it registers."""
    monkeypatch.setattr(hooks, "_listeners", {})


def fake_plugin_package(monkeypatch, name, plugin):
    package = ModuleType(name)
    package.__path__ = []
    manifest = ModuleType(f"{name}.plugin")
    manifest.PLUGIN = plugin
    monkeypatch.setitem(sys.modules, name, package)
    monkeypatch.setitem(sys.modules, f"{name}.plugin", manifest)


def test_the_example_plugin_is_installed_for_the_suite():
    assert "gnu_plugins.attendance" in settings.G5_PLUGINS
    assert apps.is_installed("gnu_plugins.attendance")
    assert [plugin.slug for plugin in installed_plugins()] == ["attendance", "order_notify"]


def test_a_listed_package_without_plugin_py_is_refused():
    with pytest.raises(ImproperlyConfigured, match="plugin.py"):
        load_plugins(["gnu_jango.utils"])


def test_a_manifest_must_be_a_plugin(monkeypatch):
    fake_plugin_package(monkeypatch, "fake_plugin_a", {"slug": "fake"})
    with pytest.raises(ImproperlyConfigured, match="PLUGIN = Plugin"):
        load_plugins(["fake_plugin_a"])


def test_slugs_must_be_url_safe_and_unique(monkeypatch):
    fake_plugin_package(monkeypatch, "fake_plugin_b", Plugin(slug="Bad Slug", title="Bad"))
    with pytest.raises(ImproperlyConfigured, match="slug"):
        load_plugins(["fake_plugin_b"])

    with pytest.raises(ImproperlyConfigured, match="attendance"):
        load_plugins(["gnu_plugins.attendance", "gnu_plugins.attendance"])


def test_a_plugin_must_declare_the_plugin_api_version_it_was_written_for(monkeypatch):
    fake_plugin_package(monkeypatch, "fake_plugin_c", Plugin(slug="future", title="Future", api_version=99))
    with pytest.raises(ImproperlyConfigured, match="api_version=99"):
        load_plugins(["fake_plugin_c"])

    fake_plugin_package(monkeypatch, "fake_plugin_d", Plugin(slug="undeclared", title="Undeclared"))
    with pytest.raises(ImproperlyConfigured, match="api_version=0"):
        load_plugins(["fake_plugin_d"])


# Listeners run in a savepoint, so even these need the database.
@pytest.mark.django_db
def test_emit_calls_listeners_by_priority_and_survives_a_failing_one(no_listeners, caplog):
    calls = []

    @hooks.on("test.event", priority=20)
    def late(value, **kwargs):
        calls.append(("late", value))

    @hooks.on("test.event", priority=5)
    def broken(value, **kwargs):
        raise RuntimeError("plugin bug")

    @hooks.on("test.event", priority=10)
    def early(value, **kwargs):
        calls.append(("early", value))

    hooks.emit("test.event", value=1)

    assert calls == [("early", 1), ("late", 1)]
    assert "test.event" in caplog.text and "broken" in caplog.text


# Listeners run in a savepoint, so even these need the database.
@pytest.mark.django_db
def test_replace_chains_listeners_and_keeps_the_value_when_one_fails(no_listeners):
    @hooks.on("test.price")
    def double(value, **kwargs):
        return value * 2

    @hooks.on("test.price", priority=20)
    def broken(value, **kwargs):
        raise ValueError("plugin bug")

    @hooks.on("test.price", priority=30)
    def add_one(value, **kwargs):
        return value + 1

    assert hooks.replace("test.price", 10) == 21
    assert hooks.replace("test.unknown", 10) == 10


@pytest.mark.django_db
def test_a_failing_listener_s_database_writes_are_rolled_back(no_listeners, member):
    from django.db import transaction

    from gnu_jango.config.models import Config

    @hooks.on("test.write")
    def write_then_fail(**kwargs):
        Config.objects.create(name="plugin_half_done", value="1")
        raise RuntimeError("plugin bug after a write")

    with transaction.atomic():
        hooks.emit("test.write")
        # The caller's transaction is still usable and holds none of the listener's work.
        assert not Config.objects.filter(name="plugin_half_done").exists()


# Listeners run in a savepoint, so even these need the database.
@pytest.mark.django_db
def test_registering_the_same_function_again_replaces_it(no_listeners):
    calls = []

    def listener(**kwargs):
        calls.append(1)

    hooks.on("test.once")(listener)
    hooks.on("test.once", priority=1)(listener)
    hooks.emit("test.once")

    assert calls == [1]


def test_plugin_urls_are_mounted_under_their_slug():
    # Inside the core API's namespace (api_v1), under the plugin's own app_name.
    assert reverse("api_v1:attendance_api:check-in") == "/api/v1/plugins/attendance/check-in"


def test_plugin_jobs_join_the_scheduled_jobs():
    job = scheduled_jobs.select_jobs(["attendance_monthly_bonus"])[0]
    assert job.interval_seconds == 86400
    assert "--apply" in job.apply_args and "--apply" not in job.dry_run_args


def test_the_job_list_comes_only_from_the_values_it_is_given():
    jobs = build_scheduled_jobs({"SHOP_SUBSCRIPTIONS_ENABLED": True, "G5_PLUGINS": ["gnu_plugins.attendance"]}.get)

    assert [job.name for job in jobs][-2:] == ["charge_shop_subscriptions", "attendance_monthly_bonus"]
    assert "charge_shop_subscriptions" not in [job.name for job in build_scheduled_jobs({}.get)]


def test_celery_beat_keeps_the_optional_and_plugin_jobs():
    # The beat schedule is built while the settings load; reading django.conf.settings there used
    # to drop every optional and plugin job. Only a fresh process shows it.
    code = (
        "import django, json; django.setup(); from django.conf import settings; "
        "from gnu_jango.core.scheduled_jobs import JOB_NAMES; "
        "print(json.dumps({'beat': sorted(settings.CELERY_BEAT_SCHEDULE), 'jobs': list(JOB_NAMES)}))"
    )
    env = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "example.settings",
        "BACKGROUND_JOBS_ENABLED": "True",
        "SHOP_SUBSCRIPTIONS_ENABLED": "True",
        "G5_PLUGINS": "gnu_plugins.attendance",
    }
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=True,
    )
    report = json.loads(result.stdout.strip().splitlines()[-1])

    for name in ("charge_shop_subscriptions", "attendance_monthly_bonus"):
        assert f"maintenance-{name}" in report["beat"]
        assert name in report["jobs"]


@pytest.mark.django_db
def test_the_sidebar_adds_a_plugins_group_after_the_core_groups():
    request = RequestFactory().get("/admin/")
    request.user = AdminFactory()

    groups = sidebar_navigation(request)

    assert groups[: len(settings.G5_ADMIN_NAVIGATION)] == list(settings.G5_ADMIN_NAVIGATION)
    links = {str(item["link"]): item for item in groups[-1]["items"]}
    assert list(links) == ["/admin/plugins/", "/admin/attendance/attendance/", "/admin/order_notify/ordernotice/"]
    item = links["/admin/attendance/attendance/"]
    assert item["permission"](request) is True

    request.user = MemberFactory(is_staff=True)
    assert item["permission"](request) is False


@pytest.mark.django_db
def test_the_admin_renders_the_plugin_link(admin_client):
    response = admin_client.get("/admin/")

    assert response.status_code == 200
    assert "/admin/attendance/attendance/" in response.content.decode()


@pytest.mark.django_db
def test_a_signed_in_page_load_emits_member_visited(no_listeners, member_client, member):
    seen = []
    hooks.on("member.visited")(lambda user, request, **kwargs: seen.append(user.pk))

    response = member_client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert seen == [member.pk]
