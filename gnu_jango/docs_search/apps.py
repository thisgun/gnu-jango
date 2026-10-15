from django.apps import AppConfig


class DocsSearchConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gnu_jango.docs_search"
    verbose_name = "Handbook search"

    def ready(self):
        from . import signals  # noqa: F401
