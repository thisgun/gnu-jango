"""Models and migrations stay in step, and removed legacy columns do not come back."""

from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from gnu_jango.core.models import Notification


class ModelMigrationTests(TestCase):
    # makemigrations reads the applied-migration table, so the test needs the database.
    def test_every_model_change_has_a_migration(self):
        out = StringIO()
        try:
            call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=out)
        except SystemExit:
            self.fail(f"Models changed without a migration:\n{out.getvalue()}")

    def test_notification_has_no_calendar_dday_column(self):
        # dday_id belonged to the removed calendar (D-day) app; nothing reads or writes it.
        field_names = {field.name for field in Notification._meta.get_fields()}
        self.assertNotIn("dday_id", field_names)
