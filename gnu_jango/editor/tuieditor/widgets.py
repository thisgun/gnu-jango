from django import forms


class MarkdownEditorWidget(forms.Textarea):
    template_name = "editor/tuieditor/editor.html"

    class Media:
        css = {
            "screen": (
                "editor/tuieditor/codemirror.css",
                "editor/tuieditor/toastui-editor.css",
                "editor/tuieditor/django-fixes.css",
            )
        }
        js = (
            "editor/tuieditor/codemirror.js",
            "editor/tuieditor/toastui-editor.js",
            "editor/tuieditor/django-fixes.js",
        )


class MarkdownViewerWidget(forms.Textarea):
    template_name = "editor/tuieditor/viewer.html"

    def __init__(self, attrs=None):
        default_attrs = {"class": "tui-editor-contents"}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)

    class Media:
        css = {
            "screen": (
                "editor/tuieditor/codemirror.css",
                "editor/tuieditor/toastui-editor.css",
                "editor/tuieditor/django-fixes.css",
            )
        }
        js = (
            "editor/tuieditor/codemirror.js",
            "editor/tuieditor/toastui-editor-viewer.js",
            "editor/tuieditor/django-fixes.js",
        )


class StaticMarkdownViewerWidget(forms.Textarea):
    template_name = "editor/tuieditor/static_viewer.html"

    def __init__(self, attrs=None):
        default_attrs = {"class": "tui-editor-contents"}
        if attrs:
            default_attrs.update(attrs)
        super().__init__(default_attrs)

    class Media:
        css = {
            "screen": (
                "editor/tuieditor/toastui-editor.css",
                "editor/tuieditor/django-fixes.css",
            )
        }
        js = ()
