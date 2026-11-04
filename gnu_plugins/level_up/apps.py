from django.apps import AppConfig


class LevelUpConfig(AppConfig):
    name = "gnu_plugins.level_up"
    label = "level_up"
    verbose_name = "자동 등업"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import listeners  # noqa: F401 - registers the plugin's hooks
