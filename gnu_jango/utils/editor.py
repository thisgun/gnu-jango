import logging


from urllib.parse import urlparse

# https://bleach.readthedocs.io/en/latest/clean.html
from django import forms
from django.utils.translation import gettext_lazy as _
from django.utils.module_loading import import_string

# from gnu_jango.editor.tuieditor.fields import MarkdownFormField

# from django_tuieditor.templatetags import render_widget
# from django_tuieditor.widgets import (
#     MarkdownEditorWidget,
#     MarkdownViewerWidget,
#     StaticMarkdownViewerWidget,
# )

# from gnu_jango.editor.tuieditor.fields import MarkdownFormField
# from gnu_jango.editor.tuieditor import widgets as tui_widgets

from gnu_jango.config import config
from gnu_jango.templatetags.bleach_tags import bleach_value

logger = logging.getLogger(__name__)

DEFAULT_EDITOR_BACKEND = "tuieditor"
ALLOWED_EDITOR_BACKENDS = {"tuieditor"}
RETIRED_EDITOR_BACKENDS = {"ckeditor4"}


# class Web_Editor:
#     def __init__(self):

#         print("aaaaa")
#         print(config.cf_editor)

#         if config.cf_editor:
#             backend = "gnu_jango.editor." + config.cf_editor + "." + config.cf_editor

#             super().__setattr__("_editor", lib.import_module_attr(backend)())


# Web_Editor()


def get_editor_module_string(editor_cls_name):

    return "gnu_jango.editor." + editor_cls_name + "." + editor_cls_name


def get_configured_editor_name():
    editor_name = str(getattr(config, "cf_editor", "") or "").strip()
    if not editor_name:
        return ""
    if editor_name in ALLOWED_EDITOR_BACKENDS:
        return editor_name

    if editor_name in RETIRED_EDITOR_BACKENDS:
        logger.warning("Retired editor backend '%s' requested; falling back to %s.", editor_name, DEFAULT_EDITOR_BACKEND)
    else:
        logger.warning("Unsupported editor backend '%s' requested; falling back to %s.", editor_name, DEFAULT_EDITOR_BACKEND)
    return DEFAULT_EDITOR_BACKEND


def get_editor_class():
    editor_name = get_configured_editor_name()
    if not editor_name:
        return None
    return import_string(get_editor_module_string(editor_name))


# class EditorWidget(forms.Textarea):
#     template_name = "django_tuieditor/editor.html"

#     class Media:
#         css = {
#             "screen": (
#                 "django_tuieditor/codemirror.css",
#                 "django_tuieditor/toastui-editor.css",
#                 "django_tuieditor/django-fixes.css",
#             )
#         }
#         js = (
#             "django_tuieditor/codemirror.js",
#             "django_tuieditor/toastui-editor.js",
#             "django_tuieditor/django-fixes.js",
#         )


def allow_src(tag, name, value):
    if name in ("alt", "height", "width"):
        return True

    if name == "src":
        p = urlparse(value)
        return (not p.netloc) or p.netloc == "youtube.com"

    return True


def editor_view_html(id, content, is_dhtml_editor=False):

    # content = mark_safe(bleach.clean(content, tags=["iframe"], attributes={"img": allow_src}))

    content = bleach_value(content)

    if is_dhtml_editor and get_configured_editor_name() == "tuieditor":

        class DefaultCheckForm(forms.Form):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                # self.fields[id] = MarkdownFormField()
                self.fields[id] = forms.CharField(
                    label="", required=False, widget=get_editor_view_html()
                )

        form = DefaultCheckForm({"wr_content": content})

        return {"html": form.as_table(), "media": form.media}

    return {
        "media": "",
        "html": content,
    }


def editor_html(id, content, is_dhtml_editor=False):
    if is_dhtml_editor:

        class DefaultCheckForm(forms.Form):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                # self.fields[id] = MarkdownFormField()
                self.fields[id] = forms.CharField(
                    label="", required=False, widget=get_editor_widget()
                )

        form = DefaultCheckForm({"wr_content": content})

        return {"html": form.as_table(), "media": form.media}

        # widget = get_editor_widget()

        # return {
        #     "html": render_widget(widget=widget, name=id, value=content),
        #     "media": "",
        # }

    return {
        "media": "",
        "html": '<textarea id="'
        + id
        + '" name="'
        + id
        + '" class="form-control" placeholder="'
        + _("내용")
        + '" >'
        + content
        + "</textarea>",
    }


def get_editor_js(id, is_dhtml_editor=False):
    return "var {id}_editor = document.getElementById('{id}');\n"


def chk_editor_js(id, is_dhtml_editor=False):
    return (
        'if (!{id}_editor.value) { alert("내용을 입력해 주십시오."); {id}_editor.focus(); return false; }\n'
    )


def get_editor_view_html():
    editor_cl = get_editor_class()
    if editor_cl:

        return editor_cl().get_editor_view_html()

        # return tui_widgets.MarkdownViewerWidget()


def get_editor_widget():

    editor_cl = get_editor_class()
    if editor_cl:

        return editor_cl().get_editor_widget()

        # return tui_widgets.MarkdownEditorWidget()


def get_editor_upload_view():

    editor_cl = get_editor_class()
    if editor_cl:

        return editor_cl().get_editor_upload_view()

        # return tui_widgets.MarkdownEditorWidget()
