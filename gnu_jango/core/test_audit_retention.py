"""Tests for the audit-history retention command."""

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from gnu_jango.config.models import Config


class PurgeAuditHistoryTests(TestCase):
    def _make_old_history(self):
        setting = Config.objects.create(name="cf_title", value="old")
        record = setting.history.first()
        record.history_date = timezone.now() - timedelta(days=400)
        record.save(update_fields=["history_date"])
        return setting

    def test_deletes_rows_older_than_the_retention_window(self):
        setting = self._make_old_history()
        setting.value = "new"
        setting.save()

        call_command(
            "purge_audit_history",
            days=365,
            models=["config.Config"],
            stdout=StringIO(),
        )

        remaining = list(setting.history.order_by("history_date"))
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].value, "new")
        self.assertGreater(remaining[0].history_date, timezone.now() - timedelta(days=2))

    def test_dry_run_keeps_rows(self):
        setting = self._make_old_history()
        before = setting.history.count()

        out = StringIO()
        call_command(
            "purge_audit_history",
            days=365,
            models=["config.Config"],
            dry_run=True,
            stdout=out,
        )

        self.assertEqual(setting.history.count(), before)
        self.assertIn("dry run", out.getvalue())

    def test_rejects_a_negative_window(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            call_command("purge_audit_history", days=-1, models=["config.Config"])
