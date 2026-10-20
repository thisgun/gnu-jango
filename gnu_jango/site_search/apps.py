from django.apps import AppConfig


class SiteSearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gnu_jango.site_search"
    verbose_name = "Unified search"

    def ready(self):
        from . import signals  # noqa: F401
