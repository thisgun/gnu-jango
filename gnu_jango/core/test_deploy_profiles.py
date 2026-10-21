"""Deployment profiles: env-driven settings helpers, scheduled jobs, the cron endpoint, readiness checks.

The settings helpers are pure functions, so these tests never import django-storages, boto3 or redis:
they only assert on the dicts the helpers return (or the errors they raise).
"""

import json
import importlib
import os
import subprocess
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import global_settings, settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from example.settings import deploy
from gnu_jango.core import deploy_profile, scheduled_jobs

S3_ENV = {
    "MEDIA_STORAGE": "s3",
    "S3_BUCKET": "media",
    "S3_ENDPOINT_URL": "https://project-ref.storage.supabase.co/storage/v1/s3",
    "S3_REGION": "ap-northeast-2",
    "S3_ACCESS_KEY_ID": "access-key-placeholder",
    "S3_SECRET_ACCESS_KEY": "secret-key-placeholder",
}


def _load_production_settings(env=None):
    settings_env = {
        "ALLOWED_HOSTS": "localhost",
        "SECRET_KEY": "production-settings-tests-only",
        "DATABASE_URL": "",
        "DB_ENGINE": "",
        "DB_CONN_MAX_AGE": "0",
        "DB_SSL_REQUIRE": "false",
        "DB_DISABLE_SERVER_SIDE_CURSORS": "true",
        "MEDIA_STORAGE": "local",
        "EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend",
        "DEBUG": "False",
        "CACHE_URL": "",
        "LOG_TO_FILE": "False",
        "VERCEL": "0",
    }
    settings_env.update(env or {})
    with mock.patch.dict(os.environ, settings_env):
        os.environ.pop("DYNO", None)
        module = importlib.import_module("example.settings.production")
        return importlib.reload(module)


class HerokuOptionalDependencyTests(SimpleTestCase):
    def test_missing_django_heroku_has_actionable_error(self):
        with mock.patch.dict("sys.modules", {"django_heroku": None}):
            with self.assertRaisesMessage(ImproperlyConfigured, "pip install django-heroku==0.3.1"):
                _load_production_settings().configure_heroku({})

    def test_installed_django_heroku_receives_settings(self):
        django_heroku = mock.Mock()
        settings_mapping = {"SECRET_KEY": "test"}

        with mock.patch.dict("sys.modules", {"django_heroku": django_heroku}):
            _load_production_settings().configure_heroku(settings_mapping)

        django_heroku.settings.assert_called_once_with(settings_mapping)


class ProductionSettingsSerializationTests(SimpleTestCase):
    def test_ci_database_settings_are_serializable(self):
        ci_env = {
            "CI": "1",
            "DATABASE_URL": "postgresql://ci:ci@localhost:5432/ci",
            "DB_CONN_MAX_AGE": "0",
            "DB_SSL_REQUIRE": "false",
            "DB_DISABLE_SERVER_SIDE_CURSORS": "true",
            "ALLOWED_HOSTS": "localhost",
            "SECRET_KEY": "ci-settings-serialization-only",
            "MEDIA_STORAGE": "local",
            "EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend",
        }

        production = _load_production_settings(ci_env)
        json.dumps(production.DATABASES, default=str)

    def _run_vercel_settings_scan(self, **overrides):
        """Import the settings the way Vercel's build scan does, in a clean process."""
        repo_root = Path(__file__).resolve().parents[2]
        scanner = r"""
import importlib
import json
import os
import runpy
import sys
import django.core.management

class StopAfterManagePySetsSettings(Exception):
    pass

def stop(*args, **kwargs):
    raise StopAfterManagePySetsSettings

django.core.management.execute_from_command_line = stop
sys.argv = ["manage.py"]
try:
    runpy.run_path("manage.py", run_name="__main__")
except StopAfterManagePySetsSettings:
    pass

settings_module = os.environ["DJANGO_SETTINGS_MODULE"]
module = importlib.import_module(settings_module)
settings = {key: getattr(module, key) for key in dir(module) if key.isupper()}
print(json.dumps({"settings_module": settings_module, "django_settings": settings}, default=str))
"""
        env = {key: os.environ[key] for key in ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
        env.update({
            "PYTHONPATH": str(repo_root),
            "DJANGO_SETTINGS_MODULE": "example.settings",
            "ENVIRONMENT": "Production",
            "VERCEL": "1",
            "CI": "1",
            "SECRET_KEY": "vercel-settings-scan-test-only",
            "ALLOWED_HOSTS": "localhost",
            "DATABASE_URL": "",
            "DB_ENGINE": "",
            # Vercel needs shared media storage and a shared cache (production.py refuses others).
            "MEDIA_STORAGE": "s3",
            "S3_BUCKET": "scan-test-bucket",
            "S3_REGION": "ap-northeast-2",
            "S3_ACCESS_KEY_ID": "scan-test-key",
            "S3_SECRET_ACCESS_KEY": "scan-test-secret",
            "EMAIL_BACKEND": "django.core.mail.backends.console.EmailBackend",
            "DEBUG": "False",
            "CACHE_URL": "db://",
            "LOG_TO_FILE": "False",
        })
        env.update(overrides)

        return subprocess.run(
            [sys.executable, "-c", scanner],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_vercel_settings_scan_can_serialize_lazy_settings(self):
        result = self._run_vercel_settings_scan()

        error_tail = "\n".join(result.stderr.strip().splitlines()[-12:])
        self.assertEqual(
            result.returncode,
            0,
            f"Vercel's settings scan could not serialize Django settings:\n{error_tail}",
        )
        serialized = json.loads(result.stdout)
        self.assertEqual(serialized["django_settings"]["WSGI_APPLICATION"], "example.wsgi.application")

    def test_vercel_refuses_local_media_storage(self):
        # Each function instance has its own disk, so uploads would vanish between requests.
        result = self._run_vercel_settings_scan(MEDIA_STORAGE="local")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Vercel requires MEDIA_STORAGE=s3", result.stderr)

    def test_vercel_refuses_a_per_process_cache(self):
        result = self._run_vercel_settings_scan(CACHE_URL="")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Vercel requires a shared cache", result.stderr)


class MediaStorageConfigTests(SimpleTestCase):
    def test_defaults_to_local_filesystem_storage(self):
        self.assertEqual(deploy.media_storage_config({}), {"BACKEND": deploy.FILESYSTEM_STORAGE_BACKEND})
        self.assertEqual(
            deploy.media_storage_config({"MEDIA_STORAGE": " Local "}),
            {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        )

    def test_s3_maps_to_django_storages_with_safe_defaults(self):
        config = deploy.media_storage_config(S3_ENV)

        self.assertEqual(config["BACKEND"], "storages.backends.s3.S3Storage")
        options = config["OPTIONS"]
        self.assertEqual(options["bucket_name"], "media")
        self.assertEqual(options["endpoint_url"], S3_ENV["S3_ENDPOINT_URL"])
        self.assertEqual(options["region_name"], "ap-northeast-2")
        self.assertEqual(options["access_key"], "access-key-placeholder")
        self.assertEqual(options["secret_key"], "secret-key-placeholder")
        self.assertIsNone(options["default_acl"])
        # Django's FileSystemStorage never overwrites; S3Storage does by default.
        self.assertFalse(options["file_overwrite"])
        self.assertEqual(options["addressing_style"], "path")
        self.assertEqual(options["signature_version"], "s3v4")
        # Without a public base URL the bucket is treated as private: signed URLs.
        self.assertTrue(options["querystring_auth"])
        self.assertNotIn("custom_domain", options)
        self.assertNotIn("location", options)

    def test_public_base_url_turns_off_querystring_auth(self):
        env = {
            **S3_ENV,
            "S3_PUBLIC_BASE_URL": "https://project-ref.supabase.co/storage/v1/object/public/media/",
            "S3_LOCATION": "/uploads/",
        }
        options = deploy.media_storage_config(env)["OPTIONS"]

        self.assertFalse(options["querystring_auth"])
        self.assertEqual(options["custom_domain"], "project-ref.supabase.co/storage/v1/object/public/media")
        self.assertEqual(options["url_protocol"], "https:")
        self.assertEqual(options["location"], "uploads")
        self.assertEqual(
            deploy.media_url_for(env),
            "https://project-ref.supabase.co/storage/v1/object/public/media/uploads/",
        )

    def test_custom_domain_is_used_as_is(self):
        options = deploy.media_storage_config({**S3_ENV, "S3_CUSTOM_DOMAIN": "cdn.example.com"})["OPTIONS"]

        self.assertEqual(options["custom_domain"], "cdn.example.com")
        self.assertFalse(options["querystring_auth"])

    def test_s3_without_required_variables_lists_every_missing_one(self):
        with self.assertRaises(ImproperlyConfigured) as caught:
            deploy.media_storage_config({"MEDIA_STORAGE": "s3", "S3_BUCKET": "media"})

        message = str(caught.exception)
        for name in ("S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_REGION"):
            self.assertIn(name, message)
        self.assertNotIn("S3_BUCKET", message)

    def test_rejects_unknown_storage_and_bad_public_url(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "MEDIA_STORAGE"):
            deploy.media_storage_config({"MEDIA_STORAGE": "cloudinary"})
        with self.assertRaisesMessage(ImproperlyConfigured, "S3_PUBLIC_BASE_URL"):
            deploy.media_storage_config({**S3_ENV, "S3_PUBLIC_BASE_URL": "project-ref.supabase.co/media"})

    def test_media_url_stays_local_by_default(self):
        self.assertEqual(deploy.media_url_for({}), "/media/")
        self.assertEqual(deploy.media_url_for(S3_ENV), "/media/")
        self.assertEqual(deploy.media_url_for({**S3_ENV, "S3_CUSTOM_DOMAIN": "cdn.example.com"}), "https://cdn.example.com/")


class CacheConfigTests(SimpleTestCase):
    def test_empty_and_locmem_keep_djangos_default(self):
        self.assertEqual(deploy.cache_config({}), global_settings.CACHES)
        self.assertEqual(deploy.cache_config({"CACHE_URL": "locmem://"}), global_settings.CACHES)
        self.assertEqual(
            deploy.cache_config({"CACHE_URL": "locmem://named"})["default"],
            {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "named"},
        )

    def test_db_uses_the_project_cache_table(self):
        self.assertEqual(
            deploy.cache_config({"CACHE_URL": "db://"})["default"],
            {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "gnu_jango_cache"},
        )
        self.assertEqual(deploy.cache_config({"CACHE_URL": "db://my_cache"})["default"]["LOCATION"], "my_cache")
        with self.assertRaises(ImproperlyConfigured):
            deploy.cache_config({"CACHE_URL": "db://bad-name;drop"})

    def test_redis_and_dummy(self):
        redis_url = "rediss://default:placeholder@redis.example.com:6380/1"
        self.assertEqual(
            deploy.cache_config({"CACHE_URL": redis_url, "CACHE_KEY_PREFIX": "gj"})["default"],
            {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": redis_url, "KEY_PREFIX": "gj"},
        )
        self.assertEqual(
            deploy.cache_config({"CACHE_URL": "dummy://"})["default"],
            {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
        )

    def test_rejects_unknown_scheme(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "CACHE_URL"):
            deploy.cache_config({"CACHE_URL": "memcached://127.0.0.1:11211"})


class DatabaseConfigTests(SimpleTestCase):
    def test_no_database_url_returns_none(self):
        self.assertIsNone(deploy.database_from_env({}, default_conn_max_age=0, default_ssl_require=False))

    def test_postgres_url_with_ssl_and_pooler_options(self):
        env = {
            "DATABASE_URL": "postgresql://postgres.ref:pw@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres",
            "DB_DISABLE_SERVER_SIDE_CURSORS": "true",
            "DB_CONN_MAX_AGE": "0",
        }
        config = deploy.database_from_env(env, default_conn_max_age=600, default_ssl_require=True)

        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["PORT"], 6543)
        self.assertEqual(config["OPTIONS"]["sslmode"], "require")
        self.assertTrue(config["DISABLE_SERVER_SIDE_CURSORS"])
        self.assertEqual(config["CONN_MAX_AGE"], 0)

    def test_sqlite_url_never_gets_sslmode(self):
        config = deploy.database_from_env(
            {"DATABASE_URL": "sqlite:////srv/gnu_jango/db.sqlite3"}, default_conn_max_age=600, default_ssl_require=True
        )

        self.assertEqual(config["ENGINE"], "django.db.backends.sqlite3")
        self.assertNotIn("sslmode", config.get("OPTIONS", {}))

    def test_ssl_can_be_switched_off_for_a_local_compose_database(self):
        config = deploy.database_from_env(
            {"DATABASE_URL": "postgres://u:p@db:5432/gnu_jango", "DB_SSL_REQUIRE": "false"},
            default_conn_max_age=600,
            default_ssl_require=True,
        )

        self.assertNotIn("sslmode", config.get("OPTIONS", {}))
        self.assertEqual(config["CONN_MAX_AGE"], 600)

    def test_vercel_hosts_are_added_only_on_vercel(self):
        env = {"VERCEL": "1", "VERCEL_URL": "app-abc.vercel.app", "VERCEL_PROJECT_PRODUCTION_URL": "app.vercel.app"}
        self.assertEqual(deploy.vercel_allowed_hosts(env), ["app-abc.vercel.app", "app.vercel.app"])
        self.assertEqual(deploy.vercel_allowed_hosts({"VERCEL_URL": "app-abc.vercel.app"}), [])


class SecretKeyTests(SimpleTestCase):
    def test_development_gets_the_published_fallback(self):
        self.assertEqual(deploy.secret_key_for({}, is_production=False), deploy.DEVELOPMENT_SECRET_KEY)
        self.assertEqual(deploy.secret_key_for({"SECRET_KEY": "local"}, is_production=False), "local")

    def test_production_requires_a_key(self):
        with self.assertRaisesMessage(ImproperlyConfigured, "SECRET_KEY environment variable is required"):
            deploy.secret_key_for({}, is_production=True)

    def test_production_refuses_the_keys_published_in_this_repository(self):
        # The development fallback and the docker-compose placeholder are public, so anyone could
        # forge sessions and JWTs signed with them.
        placeholders = (
            deploy.DEVELOPMENT_SECRET_KEY,
            "unsafe-compose-secret-change-me",
            " unsafe-anything",
            '<generate: python -c "...">',
        )
        for key in placeholders:
            with self.subTest(key=key), self.assertRaisesMessage(ImproperlyConfigured, "placeholder"):
                deploy.secret_key_for({"SECRET_KEY": key}, is_production=True)

    def test_production_accepts_a_real_key(self):
        self.assertEqual(deploy.secret_key_for({"SECRET_KEY": GOOD_SECRET_KEY}, is_production=True), GOOD_SECRET_KEY)


class CurrentDefaultsTests(SimpleTestCase):
    """Without the new variables the running settings are exactly what they were before."""

    def test_storage_cache_and_media_defaults_are_unchanged(self):
        self.assertEqual(settings.STORAGES["default"]["BACKEND"], "django.core.files.storage.FileSystemStorage")
        self.assertEqual(settings.CACHES["default"]["BACKEND"], "django.core.cache.backends.locmem.LocMemCache")
        self.assertEqual(settings.MEDIA_URL, "/media/")
        self.assertTrue(str(settings.MEDIA_ROOT).endswith("media"))
        self.assertEqual(settings.CRON_SECRET, "")


def fake_runner(failing=()):
    calls = []

    def runner(name, *args, stdout=None, stderr=None):
        calls.append((name, args))
        if name in failing:
            raise CommandError(f"{name} exploded")
        if "--json" in args:
            stdout.write(json.dumps({"applied": "--apply" in args, "cancelled": 2, "samples": [{"order_id": "1"}]}))
        else:
            stdout.write("Admin privacy cleanup: visits=3 dry_run=no\n")

    runner.calls = calls
    return runner


class ScheduledJobsRunnerTests(TestCase):
    def test_runs_every_job_with_apply(self):
        runner = fake_runner()

        report = scheduled_jobs.run_scheduled_jobs(runner=runner)

        self.assertTrue(report["ok"])
        self.assertEqual(report["failed"], 0)
        self.assertEqual(
            [name for name, _ in runner.calls],
            [
                "expire_pending_payment_orders",
                "expire_pending_email_members",
                "expire_toss_vbank_orders",
                "cleanup_admin_privacy",
                "cleanup_search_clicks",
                "save_order_points",
            ],
        )
        for name, args in runner.calls:
            if name in {"cleanup_admin_privacy", "cleanup_search_clicks"}:
                self.assertNotIn("--dry-run", args)
            else:
                self.assertIn("--apply", args)
        first = report["jobs"][0]
        self.assertEqual(first["status"], "ok")
        # Counts are kept, per-row samples (order ids, user ids) are not.
        self.assertEqual(first["summary"], {"applied": True, "cancelled": 2})
        self.assertIn("visits=3", report["jobs"][3]["summary"])

    def test_dry_run_never_applies(self):
        runner = fake_runner()

        report = scheduled_jobs.run_scheduled_jobs(dry_run=True, runner=runner)

        self.assertTrue(report["dry_run"])
        for name, args in runner.calls:
            self.assertNotIn("--apply", args)
            if name in {"cleanup_admin_privacy", "cleanup_search_clicks"}:
                self.assertIn("--dry-run", args)

    def test_one_failing_job_does_not_stop_the_others(self):
        runner = fake_runner(failing={"expire_pending_email_members"})

        with self.assertLogs("gnu_jango.core.scheduled_jobs", "ERROR"):
            report = scheduled_jobs.run_scheduled_jobs(runner=runner)

        self.assertFalse(report["ok"])
        self.assertEqual(report["failed"], 1)
        self.assertEqual(report["succeeded"], len(scheduled_jobs.SCHEDULED_JOBS) - 1)
        self.assertEqual(len(runner.calls), len(scheduled_jobs.SCHEDULED_JOBS))
        failed = report["jobs"][1]
        self.assertEqual(failed["status"], "failed")
        self.assertIn("exploded", failed["error"])

    def test_overlapping_run_is_skipped(self):
        runner = fake_runner()
        with scheduled_jobs.job_lock() as acquired:
            self.assertTrue(acquired)
            report = scheduled_jobs.run_scheduled_jobs(runner=runner)

        self.assertTrue(report["skipped"])
        self.assertEqual(runner.calls, [])
        # The lock is released afterwards.
        self.assertFalse(scheduled_jobs.run_scheduled_jobs(runner=runner)["skipped"])

    def test_real_commands_run_cleanly_on_an_empty_database(self):
        report = scheduled_jobs.run_scheduled_jobs(dry_run=True)
        self.assertTrue(report["ok"], report)
        report = scheduled_jobs.run_scheduled_jobs()
        self.assertTrue(report["ok"], report)


class RunScheduledJobsCommandTests(TestCase):
    def test_prints_summary_and_succeeds(self):
        stdout = StringIO()
        with mock.patch.object(scheduled_jobs, "default_runner", fake_runner()):
            call_command("run_scheduled_jobs", stdout=stdout)

        output = stdout.getvalue()
        self.assertIn("expire_pending_payment_orders: ok", output)
        self.assertIn("5 ok, 0 failed", output)

    def test_exits_non_zero_when_any_job_failed(self):
        stdout = StringIO()
        with mock.patch.object(scheduled_jobs, "default_runner", fake_runner(failing={"cleanup_admin_privacy"})):
            with self.assertLogs("gnu_jango.core.scheduled_jobs", "ERROR"):
                with self.assertRaisesMessage(CommandError, "1 scheduled job(s) failed"):
                    call_command("run_scheduled_jobs", stdout=stdout)

        self.assertIn("cleanup_admin_privacy: failed", stdout.getvalue())
        self.assertIn("expire_toss_vbank_orders: ok", stdout.getvalue())

    def test_dry_run_and_json(self):
        stdout = StringIO()
        runner = fake_runner()
        with mock.patch.object(scheduled_jobs, "default_runner", runner):
            call_command("run_scheduled_jobs", "--dry-run", "--json", stdout=stdout)

        report = json.loads(stdout.getvalue())
        self.assertTrue(report["dry_run"])
        self.assertTrue(all("--apply" not in args for _, args in runner.calls))


CRON_URL = "/api/internal/cron"


class CronEndpointTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @override_settings(CRON_SECRET="")
    def test_disabled_without_a_configured_secret(self):
        response = self.client.get(CRON_URL, HTTP_AUTHORIZATION="Bearer ")
        self.assertEqual(response.status_code, 404)

    @override_settings(CRON_SECRET="short-secret")
    def test_disabled_with_a_guessable_secret(self):
        response = self.client.get(CRON_URL, HTTP_AUTHORIZATION="Bearer short-secret")
        self.assertEqual(response.status_code, 404)

    @override_settings(CRON_SECRET="s" * 32)
    def test_rejects_missing_or_wrong_credentials(self):
        runner = fake_runner()
        with mock.patch.object(scheduled_jobs, "default_runner", runner):
            for header in (None, "Bearer wrong", "s" * 32, "Basic " + "s" * 32, "Bearer " + "s" * 31):
                kwargs = {"HTTP_AUTHORIZATION": header} if header is not None else {}
                response = self.client.get(CRON_URL, **kwargs)
                self.assertEqual(response.status_code, 401, header)
                self.assertFalse(response.json()["ok"])
        self.assertEqual(runner.calls, [])

    @override_settings(CRON_SECRET="s" * 32)
    def test_runs_jobs_with_the_vercel_cron_header(self):
        runner = fake_runner()
        with mock.patch.object(scheduled_jobs, "default_runner", runner):
            response = self.client.get(CRON_URL, HTTP_AUTHORIZATION="Bearer " + "s" * 32)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["data"]["failed"], 0)
        self.assertEqual(len(body["data"]["jobs"]), len(scheduled_jobs.SCHEDULED_JOBS))
        self.assertIn("no-store", response["Cache-Control"])
        self.assertTrue(all("--apply" in args for name, args in runner.calls
                            if name not in {"cleanup_admin_privacy", "cleanup_search_clicks"}))

    @override_settings(CRON_SECRET="s" * 32)
    def test_post_and_dry_run_query(self):
        runner = fake_runner()
        with mock.patch.object(scheduled_jobs, "default_runner", runner):
            response = self.client.post(f"{CRON_URL}?dry_run=1", HTTP_AUTHORIZATION="Bearer " + "s" * 32)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["data"]["dry_run"])
        self.assertTrue(all("--apply" not in args for _, args in runner.calls))

    @override_settings(CRON_SECRET="s" * 32)
    def test_partial_failure_reports_each_job(self):
        with mock.patch.object(scheduled_jobs, "default_runner", fake_runner(failing={"expire_toss_vbank_orders"})):
            with self.assertLogs("gnu_jango.core.scheduled_jobs", "ERROR"):
                response = self.client.get(CRON_URL, HTTP_AUTHORIZATION="Bearer " + "s" * 32)

        self.assertEqual(response.status_code, 500)
        body = response.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["data"]["failed"], 1)
        statuses = {job["name"]: job["status"] for job in body["data"]["jobs"]}
        self.assertEqual(statuses["expire_toss_vbank_orders"], "failed")
        self.assertEqual(statuses["cleanup_admin_privacy"], "ok")
        self.assertIn("expire_toss_vbank_orders", body["errors"])
        self.assertIn("no-store", response["Cache-Control"])


GOOD_SECRET_KEY = "k" * 20 + "abcdefghijklmnopqrstuvwxyz0123456789"


def profile_settings(**overrides):
    values = {
        "DEBUG": False,
        "SECRET_KEY": GOOD_SECRET_KEY,
        "ALLOWED_HOSTS": ["api.example.com"],
        "DATABASES": {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "HOST": "aws-0-ap-northeast-2.pooler.supabase.com",
                "PORT": 6543,
                "CONN_MAX_AGE": 0,
                "DISABLE_SERVER_SIDE_CURSORS": True,
                "OPTIONS": {"sslmode": "require"},
            }
        },
        "STORAGES": {
            "default": {"BACKEND": deploy.S3_STORAGE_BACKEND, "OPTIONS": {}},
            "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
        },
        "CACHES": {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "gnu_jango_cache"}},
        "MEDIA_ROOT": "/srv/gnu_jango/media",
        "STATIC_ROOT": "/srv/gnu_jango/staticfiles",
        "LOG_TO_FILE": False,
        "SESSION_ENGINE": "django.contrib.sessions.backends.db",
        "CELERY_TASK_ALWAYS_EAGER": True,
        "CRON_SECRET": "c" * 32,
        "CORS_ALLOW_ALL_ORIGINS": False,
        "CORS_ALLOWED_ORIGINS": [],
        "CORS_ALLOW_CREDENTIALS": False,
        "CSRF_TRUSTED_ORIGINS": [],
        "SESSION_COOKIE_SECURE": True,
        "CSRF_COOKIE_SECURE": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def statuses(report):
    return {check["name"]: check["status"] for check in report["checks"]}


VERCEL_ENV = {"DATABASE_URL": "postgresql://placeholder", "CRON_SECRET": "c" * 32}


class DeployProfileCheckTests(SimpleTestCase):
    def evaluate(self, profile, env=None, **overrides):
        return deploy_profile.evaluate_deploy_profile(
            profile, settings_obj=profile_settings(**overrides), env=env if env is not None else VERCEL_ENV,
            cache_table_exists=lambda table: True,
        )

    def test_complete_vercel_profile_passes(self):
        report = self.evaluate("vercel")
        self.assertEqual(report["summary"]["failed"], 0, report)
        self.assertEqual(report["summary"]["warnings"], 0, report)

    def test_vercel_requires_every_serverless_switch(self):
        report = self.evaluate(
            "vercel",
            env={},
            DEBUG=True,
            SECRET_KEY="unsafe-development-secret-key-change-me",
            DATABASES={"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": "db.sqlite3"}},
            STORAGES={"default": {"BACKEND": deploy.FILESYSTEM_STORAGE_BACKEND}, "staticfiles": {}},
            CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
            CRON_SECRET="",
            LOG_TO_FILE=True,
        )
        result = statuses(report)
        for name in ("debug", "secret_key", "database", "media_storage", "cache", "cron_secret", "writable_paths"):
            self.assertEqual(result[name], "fail", name)

    def test_vercel_pooler_needs_server_side_cursors_off(self):
        databases = profile_settings().DATABASES
        databases["default"]["DISABLE_SERVER_SIDE_CURSORS"] = False
        report = self.evaluate("vercel", DATABASES=databases)
        self.assertEqual(statuses(report)["database"], "fail")

    def test_vercel_db_cache_needs_its_table(self):
        report = deploy_profile.evaluate_deploy_profile(
            "vercel", settings_obj=profile_settings(), env=VERCEL_ENV, cache_table_exists=lambda table: False
        )
        check = next(item for item in report["checks"] if item["name"] == "cache")
        self.assertEqual(check["status"], "fail")
        self.assertIn("createcachetable", check["action"])

    def test_vps_warns_on_locmem_with_several_workers(self):
        overrides = {
            "STORAGES": {"default": {"BACKEND": deploy.FILESYSTEM_STORAGE_BACKEND}, "staticfiles": {}},
            "CACHES": {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
            "CRON_SECRET": "",
        }
        report = self.evaluate("vps", env={"GUNICORN_WORKERS": "3"}, **overrides)
        self.assertEqual(statuses(report)["cache"], "warn")
        self.assertEqual(report["summary"]["failed"], 0, report)

        single = self.evaluate("vps", env={"GUNICORN_WORKERS": "1"}, **overrides)
        self.assertEqual(statuses(single)["cache"], "pass")

    def test_vps_requires_a_media_root_for_local_storage(self):
        report = self.evaluate(
            "vps",
            env={},
            MEDIA_ROOT="",
            STORAGES={"default": {"BACKEND": deploy.FILESYSTEM_STORAGE_BACKEND}, "staticfiles": {}},
        )
        self.assertEqual(statuses(report)["media_storage"], "fail")

    def test_split_proxy_mode_needs_no_cors(self):
        report = self.evaluate("split", env={"SPLIT_AUTH_MODE": "proxy"})
        self.assertEqual(report["summary"]["failed"], 0, report)
        self.assertEqual(statuses(report)["cross_domain"], "pass")

    def test_split_direct_mode_requires_cors_csrf_and_secure_cookies(self):
        report = self.evaluate("split", env={"SPLIT_AUTH_MODE": "direct"}, SESSION_COOKIE_SECURE=False)
        result = statuses(report)
        self.assertEqual(result["cross_domain"], "fail")
        self.assertEqual(result["secure_cookies"], "fail")

        configured = self.evaluate(
            "split",
            env={"SPLIT_AUTH_MODE": "direct"},
            CORS_ALLOWED_ORIGINS=["https://front.example.com"],
            CORS_ALLOW_CREDENTIALS=True,
            CSRF_TRUSTED_ORIGINS=["https://front.example.com"],
        )
        # Passes the gate, but still warns that the SameSite=Lax refresh cookie does not cross sites.
        self.assertEqual(statuses(configured)["cross_domain"], "warn")
        self.assertEqual(configured["summary"]["failed"], 0, configured)

    def test_split_rejects_wildcard_cors_with_credentials(self):
        report = self.evaluate("split", env={}, CORS_ALLOW_ALL_ORIGINS=True, CORS_ALLOW_CREDENTIALS=True)
        self.assertEqual(statuses(report)["cross_domain"], "fail")

    def test_unknown_profile_is_an_error(self):
        with self.assertRaises(ValueError):
            self.evaluate("heroku")


class CheckDeployProfileCommandTests(TestCase):
    def test_reports_failures_and_exits_non_zero(self):
        stdout = StringIO()
        with self.assertRaisesMessage(CommandError, "Deploy profile 'vercel' failed"):
            call_command("check_deploy_profile", "--profile", "vercel", stdout=stdout)
        self.assertIn("[fail]", stdout.getvalue())

    def test_profile_comes_from_the_environment(self):
        stdout = StringIO()
        with mock.patch.dict("os.environ", {"DEPLOY_PROFILE": "vps", "GUNICORN_WORKERS": "1"}):
            with self.assertRaises(CommandError):
                # The development SECRET_KEY fails the gate...
                call_command("check_deploy_profile", "--json", stdout=stdout)
        report = json.loads(stdout.getvalue())
        self.assertEqual(report["profile"], "vps")
        # ...but local media and the locmem cache with one worker are fine for a VPS.
        self.assertEqual(statuses(report)["cache"], "pass")

    def test_requires_a_profile(self):
        with mock.patch.dict("os.environ", {"DEPLOY_PROFILE": ""}):
            with self.assertRaisesMessage(CommandError, "DEPLOY_PROFILE"):
                call_command("check_deploy_profile", stdout=StringIO())

    def test_release_readiness_includes_the_profile_gate(self):
        from gnu_jango.core.management.commands.check_release_readiness import Command

        with mock.patch.dict("os.environ", {"DEPLOY_PROFILE": "vercel"}):
            check = Command().check_deploy_profile(strict=False)
        self.assertEqual(check["name"], "deploy_profile")
        self.assertEqual(check["status"], "fail")
        with mock.patch.dict("os.environ", {"DEPLOY_PROFILE": ""}):
            self.assertIsNone(Command().check_deploy_profile(strict=False))


class RemoteStorageCompatibilityTests(SimpleTestCase):
    """Remote storages (S3) raise NotImplementedError on FieldFile.path; member images must use .name."""

    def remote_file(self):
        class RemoteFieldFile:
            name = "member/icon/a.png"

            def __bool__(self):
                return True

            @property
            def path(self):
                raise NotImplementedError("This backend doesn't support absolute paths.")

        return RemoteFieldFile()

    def test_member_icon_and_avatar_thumbnails_do_not_need_a_local_path(self):
        from gnu_jango.templatetags import widgets
        from gnu_jango.utils import users

        remote = self.remote_file()
        user = SimpleNamespace(profile=SimpleNamespace(icon=remote, avatar=remote), email="")
        thumbnail = SimpleNamespace(url="https://cdn.example.com/cache/thumb.png")

        with mock.patch.object(users.default_storage, "exists", return_value=True) as exists, mock.patch.object(
            users, "get_thumbnail", return_value=thumbnail
        ) as icon_thumb:
            self.assertEqual(users.user_icon_url(user), thumbnail.url)
        exists.assert_called_with("member/icon/a.png")
        self.assertIs(icon_thumb.call_args.args[0], remote)

        with mock.patch.object(widgets.default_storage, "exists", return_value=True), mock.patch.object(
            widgets, "get_thumbnail", return_value=thumbnail
        ) as avatar_thumb:
            self.assertEqual(widgets.avatar_url(user), thumbnail.url)
        self.assertIs(avatar_thumb.call_args.args[0], remote)
