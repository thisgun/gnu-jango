from django.apps import AppConfig


class AttendanceConfig(AppConfig):
    name = "gnu_plugins.attendance"
    label = "attendance"
    verbose_name = "출석체크"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import listeners  # noqa: F401 - registers the plugin's hooks
