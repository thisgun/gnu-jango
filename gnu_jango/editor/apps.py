import django.contrib.admin.options as options
from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _

# from .tuieditor.models import MarkdownField
# from .tuieditor.widgets import MarkdownEditorWidget


class EditorConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gnu_jango.editor"
    verbose_name = _("Editor")
