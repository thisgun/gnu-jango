from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gnu_jango.core"
    verbose_name = _("Core")

    def ready(self):
        from gnu_jango.notifications import checks, signals  # noqa: F401
        from . import background_checks  # noqa: F401
