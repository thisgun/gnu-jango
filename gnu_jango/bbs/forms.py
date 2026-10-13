import logging

from django import forms
from django.template.defaultfilters import filesizeformat
from django.utils.translation import gettext_lazy as _
from django.forms.models import (
    inlineformset_factory,
)

from django.core.exceptions import (
    SuspiciousFileOperation,
    ValidationError,
)

# from django_tuieditor.fields import MarkdownFormField
# from django_tuieditor.widgets import MarkdownEditorWidget


from django_recaptcha.fields import ReCaptchaField

from .models import Comment, Post, Post_file, validate_upload_file_content

from django.forms import MultiWidget
from gnu_jango.utils.editor import get_editor_widget

logger = logging.getLogger(__name__)


def delete_uploaded_file_from_storage(field_file):
    file_name = getattr(field_file, "name", "")
    storage = getattr(field_file, "storage", None)

    if not file_name or not storage:
        return

    try:
        if storage.exists(file_name):
            field_file.delete(False)
    except (OSError, SuspiciousFileOperation) as exc:
        logger.warning("Failed to delete uploaded file '%s': %s", file_name, exc)


class EditorMultiWidget(MultiWidget):
    def decompress(self, value):
        return [value for _ in self.widgets]


# https://stackoverflow.com/questions/34006994/how-to-upload-multiple-images-to-a-blog-post-in-django/34007383#34007383
class WriteForm(forms.ModelForm):
    board = None
    post = None
    user = None
    is_dhtml_editor = False

    class Meta:
        model = Post  # 사용할 모델
        fields = [
            "wr_subject",
            "wr_content",
            "wr_name",
            "wr_email",
            "wr_homepage",
            "wr_link1",
            "wr_link2",
        ]  # WriteForm에서 사용할 Post 모델의 속성
        labels = {
            "wr_subject": _("제목"),
            "wr_content": _("내용"),
            "wr_name": _("이름"),
            "wr_email": _("이메일"),
            "wr_homepage": _("홈페이지"),
            "wr_link1": _("링크1"),
            "wr_link2": _("링크2"),
        }

    def __init__(self, user, *args, **kwargs):

        if "board" in kwargs:
            self.board = kwargs.pop("board")

        if "post" in kwargs:
            self.post = kwargs.pop("post")

        if "is_dhtml_editor" in kwargs:
            self.is_dhtml_editor = kwargs.pop("is_dhtml_editor")

        self.user = user

        # if "request" in kwargs:
        #     request = kwargs.pop("request")

        super().__init__(*args, **kwargs)

        # print(self.user.is_authenticated)

        # 로그인 했으면 이름, 이메일, 홈페이지 입력이 필요없으니 지운다.
        if hasattr(user, "is_authenticated") and user.is_authenticated:
            self.fields.pop("wr_name")
            self.fields.pop("wr_email")
            self.fields.pop("wr_homepage")

        if self.is_dhtml_editor:
            # 마크다운 에디터 활성화
            # self.fields["wr_content"] = forms.CharField(widget=MarkdownEditorWidget())

            self.fields["wr_content"] = forms.CharField(widget=get_editor_widget())

    def check_forms(self):
        # send email using the self.cleaned_data dictionary
        pass


# class WriteFileForm(WriteForm): #extending form
#     file = forms.FileField(widget=forms.ClearableFileInput(attrs={'multiple': True}))
#     class Meta(WriteForm.Meta):
#         fields = WriteForm.Meta.fields + ['file',]


class WriteFileForm(forms.ModelForm):
    # bf_file = forms.FileField(widget=forms.ClearableFileInput(attrs={"multiple": True}))
    bf_file = forms.FileField(label=" ", label_suffix="", required=False)

    def __init__(self, *args, board=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.board = board or getattr(self.instance, "board", None)

    class Meta:
        model = Post_file  # 사용할 모델
        fields = [
            "bf_file",
        ]

    # https://stackoverflow.com/questions/30844679/django-clearablefileinput-how-to-detect-whether-to-delete-the-file
    def clean(self):
        cleaned_data = super().clean()
        bf_file = cleaned_data.get("bf_file")
        if (bf_file == False) and self.instance.bf_file:
            delete_uploaded_file_from_storage(self.instance.bf_file)

        return cleaned_data

    def clean_bf_file(self):
        file = self.cleaned_data.get("bf_file", False)

        if not file:
            return False

        upload_limit = int(getattr(self.board, "bo_upload_size", 0) or 0)
        if upload_limit > 0 and file.size > upload_limit:
            raise ValidationError(
                _(
                    "Uploaded file is too large (%(size)s). Maximum size is %(max_size)s."
                ),
                code="file_too_large",
                params={
                    "size": filesizeformat(file.size),
                    "max_size": filesizeformat(upload_limit),
                },
            )

        validate_upload_file_content(file)

        return file

    # def is_valid(self):

    #     print(self.bf_file)

    #     valid = super().is_valid()

    #     return valid


class PasswordForm(forms.ModelForm):
    class Meta:
        model = Post  # 사용할 모델
        fields = ["wr_password"]  # PasswordForm에서 사용할 Post 모델의 속성
        labels = {"wr_password": "비밀번호"}


# 댓글폼
class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment  # 사용할 모델
        fields = [
            "wr_content",
            "wr_name",
        ]  # CommentForm에서 사용할 Comment 모델의 속성
        # widgets = {
        #     'subject': forms.TextInput(attrs={'class': 'form-control'}),
        #     'content': forms.Textarea(attrs={'class': 'form-control', 'rows': 10}),
        # }
        labels = {
            "wr_content": "내용",
        }

    def __init__(self, user, *args, **kwargs):

        self.user = user

        super().__init__(*args, **kwargs)

        # 비회원이면 캡챠를 사용합니다.
        if user.is_anonymous:
            self.fields["captcha"] = ReCaptchaField()

    def is_valid(self):

        valid = super().is_valid()

        return valid

    def check_forms(self):
        # send email using the self.cleaned_data dictionary
        pass


# 스크랩 댓글폼
class Scrap_CommentForm(forms.ModelForm):
    class Meta:
        model = Comment  # 사용할 모델
        fields = [
            "wr_content",
        ]
        labels = {
            "wr_content": "내용",
        }

    def __init__(self, user, *args, **kwargs):

        self.user = user

        super().__init__(*args, **kwargs)

    def is_valid(self):

        valid = super().is_valid()

        return valid

    def check_forms(self):
        # send email using the self.cleaned_data dictionary
        pass


def bbs_fileformset(request, **kwargs):

    extra = kwargs.get("extra", 0)
    can_order = kwargs.get("can_order", True)

    return inlineformset_factory(
        Post,
        Post_file,
        # fields=("bf_file",),
        form=WriteFileForm,
        extra=int(extra),
        can_delete=False,
        can_order=can_order,
    )
