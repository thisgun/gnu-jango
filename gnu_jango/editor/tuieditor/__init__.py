__version__ = "1.0.0"
__project__ = "django-tui.editor"
__author__ = "Qb"
__license__ = "MIT"

default_app_config = "django_tuieditor.apps.DjangoTUIEditorConfig"

from . import widgets


class Backend:
    def get(self, key):
        """
        Get the key from the backend store and return the value.
        Return None if not found.
        """
        raise NotImplementedError

    def mget(self, keys):
        """
        Get the keys from the backend store and return a list of the values.
        Return an empty list if not found.
        """
        raise NotImplementedError

    def set(self, key, value):
        """
        Add the value to the backend store given the key.
        """
        raise NotImplementedError


class tuieditor:
    def get_editor_widget(self):

        return widgets.MarkdownEditorWidget()

    def get_editor_view_html(self):

        return widgets.MarkdownViewerWidget()

    def get_editor_upload_view(self):

        return None
