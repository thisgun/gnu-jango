import os
import uuid
import logging
from django.core.exceptions import SuspiciousFileOperation, ValidationError
from django.db import models
from gnu_jango.site_search.source import SearchIndexedSource
from django.db.models.functions import Coalesce

# from django.db.models import CharField, Model

# from django.template.defaultfilters import slugify  # new
from django.utils.text import slugify

# from django.db.models.fields import FieldDoesNotExist
# from django.core.exceptions import FieldDoesNotExist
from django.utils.translation import gettext_lazy as _

# from django.contrib.auth.models import User
# from autoslug import AutoSlugField
from django.urls import reverse

# from gnu_jango.config.models import Config
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.dispatch import receiver

from PIL import Image, UnidentifiedImageError

from gnu_jango import defaults
from gnu_jango.utils import lib

from . import utils as bbs_utils

# Create your models here.

UserModel = get_user_model()
logger = logging.getLogger(__name__)


class Group(models.Model):
    gr_id = models.CharField(_("그룹 ID"), max_length=20, unique=True)
    gr_subject = models.CharField(_("그룹 제목"), max_length=255)
    gr_device = models.CharField(
        _("접속기기"),
        choices=[
            ("both", _("PC와 모바일에서 모두 사용")),
            ("pc", _("PC 전용")),
            ("mobile", _("모바일 전용")),
        ],
        default="both",
        max_length=6,
    )
    gr_admin = models.CharField(_("그룹 관리자"), max_length=255, null=True, blank=True, default="")
    gr_use_access = models.PositiveSmallIntegerField(_("접근회원사용"), default=0)
    gr_order = models.IntegerField(_("접근회원수"), default=0)

    class Meta:
        app_label = "bbs"
        verbose_name = _("게시판그룹")
        verbose_name_plural = _("게시판그룹설정")

    def __str__(self):
        return "%s : %s" % (self.gr_id, self.gr_subject)


class Board(models.Model):
    group = models.ForeignKey(
        Group, on_delete=models.CASCADE, related_name="board", verbose_name=_("그룹")
    )
    # slug = AutoSlugField(_("게시판SLUG"), unique=True, max_length=128, populate_from='bo_subject', allow_unicode=True)  # new
    bo_subject = models.CharField(_("게시판 제목"), max_length=255)
    bo_table = models.SlugField(_("게시판 Slug"), null=False, allow_unicode=True, unique=True)
    # gr_id = models.CharField(_("그룹ID"), max_length=255, null=True, blank=True, default='')
    # gr_id = models.CharField(_("그룹ID"), max_length=20, choices=Group.gr_id.choices, on_delete=models.CASCADE)
    # gr_id = models.CharField(_("그룹ID"), max_length=20, choices=Group.gr_id.choices)
    bo_mobile_subject = models.CharField(
        _("모바일 게시판 제목"), max_length=255, null=True, blank=True, default=""
    )
    bo_device = models.CharField(
        _("접속기기"),
        choices=[
            ("both", _("PC와 모바일에서 모두 사용")),
            ("pc", _("PC 전용")),
            ("mobile", _("모바일 전용")),
        ],
        default="both",
        max_length=6,
    )
    # bo_device = models.TextChoices('both', 'pc', 'mobile')
    bo_category_list = models.TextField(_("분류"), null=True, blank=True, default="")

    bo_admin = models.CharField(_("게시판 관리자"), max_length=255, null=True, blank=True, default="")

    bo_list_level = models.PositiveSmallIntegerField(
        _("목록보기 권한"), default=0, choices=lib.get_levels_choices()
    )
    bo_read_level = models.PositiveSmallIntegerField(
        _("글읽기 권한"), default=0, choices=lib.get_levels_choices()
    )
    bo_write_level = models.PositiveSmallIntegerField(
        _("글쓰기 권한"), default=0, choices=lib.get_levels_choices()
    )
    bo_reply_level = models.PositiveSmallIntegerField(
        _("글답변 권한"), default=0, choices=lib.get_levels_choices()
    )
    bo_comment_level = models.PositiveSmallIntegerField(
        _("댓글쓰기 권한"), default=0, choices=lib.get_levels_choices()
    )
    bo_upload_level = models.PositiveSmallIntegerField(
        _("업로드 권한"), default=0, choices=lib.get_levels_choices()
    )
    bo_download_level = models.PositiveSmallIntegerField(
        _("다운로드 권한"), default=0, choices=lib.get_levels_choices()
    )
    bo_html_level = models.PositiveSmallIntegerField(
        _("HTML 쓰기 권한"), default=0, choices=lib.get_levels_choices()
    )
    bo_link_level = models.PositiveSmallIntegerField(
        _("링크 권한"), default=0, choices=lib.get_levels_choices()
    )
    bo_count_delete = models.PositiveSmallIntegerField(
        _("원글 삭제 불가"), default=0, choices=lib.get_levels_choices()
    )
    bo_count_modify = models.PositiveSmallIntegerField(
        _("원글 수정 불가"), default=0, choices=lib.get_levels_choices()
    )

    bo_write_point = models.IntegerField(_("글쓰기 포인트"), default=0)
    bo_read_point = models.IntegerField(_("글읽기 포인트"), default=0)
    bo_comment_point = models.IntegerField(_("댓글쓰기 포인트"), default=0)
    bo_download_point = models.IntegerField(_("다운로드 포인트"), default=0)

    bo_use_category = models.BooleanField(_("분류 사용"), default=False)
    bo_use_sideview = models.BooleanField(_("글쓴이 사이드뷰"), default=False)
    bo_use_file_content = models.BooleanField(_("파일 설명 사용"), default=False)
    bo_use_secret = models.BooleanField(_("비밀글 사용"), default=False)
    bo_use_dhtml_editor = models.BooleanField(_("DHTML 에디터 사용"), default=False)
    bo_select_editor = models.BooleanField(_("게시판 에디터 선택"), default=False)
    bo_use_rss_view = models.BooleanField(_("RSS 보이기 사용"), default=False)
    bo_use_good = models.BooleanField(_("추천 사용"), default=False)
    bo_use_nogood = models.BooleanField(_("비추천 사용"), default=False)
    bo_use_name = models.BooleanField(_("이름(실명) 사용"), default=False)
    bo_use_signature = models.BooleanField(_("서명보이기 사용"), default=False)
    bo_use_ip_view = models.BooleanField(_("IP 보이기 사용"), default=False)
    bo_use_list_view = models.BooleanField(_("전체목록보이기 사용"), default=False)
    bo_use_list_file = models.BooleanField(_("목록에서 파일 사용"), default=False)
    bo_use_list_content = models.BooleanField(_("목록에서 내용 사용"), default=False)
    bo_table_width = models.IntegerField(_("게시판 폭"), default=0)
    bo_subject_len = models.IntegerField(_("제목 길이"), default=0)
    bo_mobile_subject_len = models.IntegerField(_("모바일 제목 길이"), default=0)
    bo_page_rows = models.IntegerField(_("페이지당 목록 수"), default=0)
    bo_mobile_page_rows = models.IntegerField(_("모바일 페이지당 목록 수"), default=0)
    bo_new = models.IntegerField(_("새글 아이콘"), default=0)
    bo_hot = models.IntegerField(_("인기글 아이콘"), default=0)
    bo_image_width = models.IntegerField(_("이미지 폭 크기"), default=0)
    bo_skin = models.CharField(
        _("스킨 디렉토리"),
        choices=[("basic", "basic")],
        max_length=255,
    )
    bo_mobile_skin = models.CharField(
        _("모바일 스킨 디렉토리"),
        choices=[("basic", "basic")],
        max_length=255,
    )

    bo_content_head = models.TextField(_("상단 내용"), null=True, blank=True, default="")
    bo_mobile_content_head = models.TextField(_("모바일 상단 내용"), null=True, blank=True, default="")
    bo_content_tail = models.TextField(_("하단 내용"), null=True, blank=True, default="")
    bo_mobile_content_tail = models.TextField(_("모바일 하단 내용"), null=True, blank=True, default="")
    bo_insert_content = models.TextField(_("글쓰기 기본 내용"), null=True, blank=True, default="")

    bo_gallery_cols = models.IntegerField(_("갤러리 이미지 수"), default=0)
    bo_gallery_width = models.IntegerField(_("갤러리 이미지 폭"), default=0)
    bo_gallery_height = models.IntegerField(_("갤러리 이미지 높이"), default=0)
    bo_mobile_gallery_width = models.IntegerField(_("모바일 갤러리 이미지 폭"), default=0)
    bo_mobile_gallery_height = models.IntegerField(_("모바일 갤러리 이미지 높이"), default=0)

    bo_upload_size = models.IntegerField(_("파일 업로드 용량"), default=0)

    bo_reply_order = models.BooleanField(_("답변 달기"), default=False)
    bo_use_search = models.BooleanField(_("전체 검색 사용"), default=True)  # board_form.php: on for new boards

    bo_order = models.IntegerField(_("출력 순서"), default=0)
    bo_count_write = models.IntegerField(_("게시판 글 갯수"), default=0)
    bo_count_comment = models.IntegerField(_("게시판 댓글 갯수"), default=0)
    bo_write_min = models.IntegerField(_("최소 글수 제한"), default=0)
    bo_write_max = models.IntegerField(_("최대 글수 제한"), default=0)
    bo_comment_min = models.IntegerField(_("최소 댓글수 제한"), default=0)
    bo_comment_max = models.IntegerField(_("최대 댓글수 제한"), default=0)

    bo_notice = models.TextField(_("공지사항 번호"), null=True, blank=True, default="")
    bo_upload_count = models.PositiveSmallIntegerField(_("파일 업로드 개수"), default=0)

    bo_use_email = models.BooleanField(_("메일발송 사용"), default=False)
    bo_use_cert = models.CharField(
        _("본인확인 사용"),
        choices=[
            ("", ""),
            ("cert", "cert"),
            ("adult", "adult"),
            ("hp-cert", "hp-cert"),
            ("hp-adult", "hp-adult"),
        ],
        null=True,
        blank=True,
        default="",
        max_length=8,
    )
    # bo_use_cert = models.TextChoices('','cert','adult','hp-cert','hp-adult')

    bo_use_sns = models.BooleanField(_("SNS 사용"), default=False)
    bo_use_captcha = models.BooleanField(_("캡챠 사용"), default=False)

    bo_sort_field = models.CharField(
        _("리스트 정렬 필드"), max_length=255, null=True, blank=True, default=""
    )

    def __str__(self):
        return "%s : %s" % (self.bo_table, self.bo_subject)

    # https://stackoverflow.com/questions/63053210/changing-id-field-to-slug-field-in-django
    def get_absolute_url(self):
        # The board list on the Next.js site (served by core.views.nextjs25_board_theme).
        return bbs_utils.get_pretty_url(self.bo_table)

    # https://stackoverflow.com/questions/64306819/triyng-to-slugify-url-from-title-posts-in-a-django-blog
    def save(self, *args, **kwargs):  # new
        if not self.bo_table:
            self.bo_table = slugify(self.bo_subject)
        return super().save(*args, **kwargs)

    def get_admin_url(self):
        return reverse(
            "admin:%s_%s_change" % (self._meta.app_label, self._meta.model_name),
            args=(self.id,),
        )

    class Meta:
        app_label = "bbs"
        verbose_name = _("게시판관리")
        verbose_name_plural = _("게시판관리")


# https://stackoverflow.com/questions/6836740/how-to-change-foreignkey-display-text-in-the-django-admin
# class CustomModelChoiceField(forms.ModelChoiceField):
#      def label_from_instance(self, obj):
#          return "%s %s" % (obj.gr_id, obj.gr_subject)
# class MyInvoiceAdminForm(forms.ModelForm):
#     gr_id = CustomModelChoiceField(queryset=Group.objects.all())
#     class Meta:
#           model = Board
# class InvoiceAdmin(admin.ModelAdmin):
#       form = MyInvoiceAdminForm

# https://stackoverflow.com/questions/62337070/django-cannot-resolve-keyword-slug-into-field
class Post(SearchIndexedSource):
    board = models.ForeignKey(
        Board, on_delete=models.CASCADE, related_name="posts", verbose_name=_("게시판")
    )
    wr_num = models.BigIntegerField(_("정렬필드"), default=0)
    wr_reply = models.CharField(_("답글순서"), max_length=10, blank=True, default="")
    legacy_wr_id = models.PositiveBigIntegerField(
        _("원본 글 번호"), null=True, blank=True, editable=False
    )
    wr_parent = models.IntegerField(_("부모글번호"), default=0)
    ca_name = models.CharField(_("분류"), max_length=255, null=True, blank=True, default="")
    wr_comment = models.IntegerField(_("댓글합계수"), default=0)
    wr_option = models.CharField(
        _("글쓰기옵션"),
        default="both",
        max_length=100,
    )
    wr_subject = models.CharField(_("제목"), max_length=255, null=True, blank=True, default="")
    wr_content = models.TextField(_("내용"), null=True, blank=True, default="")
    wr_slug = models.SlugField(_("제목_슬러그"), max_length=255, null=False, allow_unicode=True)
    wr_link1 = models.TextField(_("링크1"), null=True, blank=True, default="")
    wr_link2 = models.TextField(_("링크2"), null=True, blank=True, default="")
    wr_link1_hit = models.IntegerField(_("링크1 클릭수"), default=0)
    wr_link2_hit = models.IntegerField(_("링크2 클릭수"), default=0)
    wr_hit = models.IntegerField(_("조회수"), default=0)
    wr_good = models.IntegerField(_("좋아요 수"), default=0)
    wr_nogood = models.IntegerField(_("싫어요 수"), default=0)
    user = models.ForeignKey(
        UserModel,
        on_delete=models.SET_NULL,
        related_name="user_post",
        blank=True,
        null=True,
    )
    wr_password = models.CharField(_("글 비밀번호"), max_length=255, null=True, blank=True, default="")
    wr_name = models.CharField(_("작성자"), max_length=255, null=True, blank=True, default="")
    wr_email = models.CharField(_("이메일"), max_length=255, null=True, blank=True, default="")
    wr_homepage = models.CharField(_("홈페이지주소"), max_length=255, null=True, blank=True, default="")
    wr_datetime = models.DateTimeField(_("작성일"))
    wr_file = models.PositiveSmallIntegerField(_("첨부파일 갯수"), default=0)
    wr_last = models.DateTimeField(_("수정일"), null=True, blank=True)
    wr_ip = models.CharField(_("아이피"), max_length=255, null=True, blank=True, default="")
    is_notice = models.SmallIntegerField(_("공지"), default=0)

    def _get_absolute_url(self, parent_slug=None):

        """
        Our URL scheme means we have to look up the category's ancestors. As
        that is a bit more expensive, we cache the generated URL. That is
        safe even for a stale cache, as the default implementation of
        ProductCategoryView does the lookup via primary key anyway. But if
        you change that logic, you'll have to reconsider the caching
        approach.
        """
        # return reverse('board_post_detail', kwargs={
        #     'category_slug': self.get_full_slug(parent_slug=parent_slug), 'pk': self.pk
        # })

    def __str__(self):
        return self.wr_subject

    def get_absolute_url(self):
        # kwargs = {
        #     'bo_table': self.board.bo_table,
        #     # 'board_pk': self.board.id,
        #     'post_id': self.id
        # }

        board = bbs_utils.get_board(pk=self.board_id)
        # The post page on the Next.js site, addressed by its public (Gnuboard5) id.
        return bbs_utils.get_pretty_url(board.bo_table, self.legacy_wr_id or self.id)

    def get_admin_url(self):
        return reverse(
            "admin:%s_%s_change" % (self._meta.app_label, self._meta.model_name),
            args=(self.id,),
        )
        # content_type = Post.objects.get_for_model(self.__class__)
        # return reverse("admin:%s_%s_change" % (content_type.app_label, content_type.model), args=(self.id,))

        # if your app was namespaced it would be something like
        # reverse('articles:edit_articles')

    def get_delete_url(self):
        board = bbs_utils.get_board(pk=self.board_id)
        kwargs = {"bo_table": board.bo_table, "post_id": self.id}
        return reverse("delete_post", kwargs=kwargs)

    def save(self, *args, **kwargs):  # new

        # if not self.wr_slug:
        #     pass

        # https://stackoverflow.com/questions/56304239/how-to-add-index-to-my-slug-if-it-already-exists-in-database
        # https://stackoverflow.com/questions/61935005/have-slugfield-be-as-the-same-value-as-other-field

        is_slug_update = kwargs.pop("is_slug_update", False)

        if is_slug_update:
            pass

        othis_pk = self.pk or 0
        
        self.wr_slug = bbs_utils.generate_wr_slug(
            self.wr_subject,
            othis_pk,
            board_id=self.board_id,
        )
        # self.wr_slug = slugify(self.wr_subject, allow_unicode=True)

        # print("글슬러그: " + self.wr_slug)
        # while Post.objects.filter(wr_slug__startswith=self.wr_slug).exclude(pk=othis_pk).exists():
        #     self.wr_slug += "-" + str(
        #         Post.objects.filter(wr_slug__startswith=self.wr_slug).exclude(pk=othis_pk).count()
        #     )

        return super().save(*args, **kwargs)

    class Meta:
        app_label = "bbs"
        verbose_name = _("게시물관리")
        verbose_name_plural = _("게시물관리")
        unique_together = (("board", "wr_slug"), ("board", "legacy_wr_id"))
        indexes = [
            models.Index(
                fields=["board", "is_notice", "wr_num", "id"],
                name="bbs_post_board_notice_idx",
            ),
        ]


# https://www.samuelliedtke.com/blog/implement-comment-system-blog-application-django/
class Comment(models.Model):
    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name=_("게시판"),
    )
    post = models.ForeignKey(
        Post,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name=_("게시글"),
    )
    user = models.ForeignKey(
        UserModel,
        on_delete=models.SET_NULL,
        related_name="comments",
        blank=True,
        null=True,
    )
    order_num = models.BigIntegerField(_("댓글순서"), default=0)
    wr_comment = models.BigIntegerField(_("Gnuboard comment group order"), null=True, blank=True, default=None)
    parent = models.IntegerField(_("댓글의부모번호"), default=0)
    wr_comment_reply = models.CharField(_("댓글정렬"), max_length=5, null=True, blank=True, default="")
    wr_option = models.CharField(
        _("글쓰기옵션"),
        default="both",
        max_length=100,
    )
    wr_content = models.TextField(_("내용"), null=True, blank=True, default="")
    wr_good = models.IntegerField(_("좋아요 수"), default=0)
    wr_nogood = models.IntegerField(_("싫어요 수"), default=0)
    wr_password = models.CharField(_("댓글 비밀번호"), max_length=255, null=True, blank=True, default="")
    wr_name = models.CharField(_("작성자"), max_length=255, null=True, blank=True, default="")
    wr_email = models.CharField(_("이메일"), max_length=255, null=True, blank=True, default="")
    wr_datetime = models.DateTimeField(_("작성일"))
    wr_file = models.PositiveSmallIntegerField(_("첨부파일 갯수"), default=0)
    wr_last = models.DateTimeField(_("수정일"), null=True, blank=True)
    wr_ip = models.CharField(_("아이피"), max_length=255, null=True, blank=True, default="")

    def __str__(self):
        username = self.user.get_username() if self.user_id and self.user else self.wr_name
        return "comment ID %s by %s" % (self.pk, username or "anonymous")

    def get_delete_url(self):
        board = bbs_utils.get_board(pk=self.board_id)
        kwargs = {"bo_table": board.bo_table, "post_id": self.post_id, "comment_id": self.pk}
        return reverse("delete_comment", kwargs=kwargs)

    def _next_comment_group(self):
        """Gnuboard5 write_comment_update.php: a new comment takes the post's highest wr_comment + 1,
        so comments list oldest first and after any imported ones."""
        if not self.post_id:
            return self.order_num
        top = Comment.objects.filter(post_id=self.post_id).aggregate(
            top=models.Max(Coalesce("wr_comment", "order_num"))
        )["top"]
        return max(top or 0, 0) + 1

    def save(self, *args, **kwargs):
        request = kwargs.pop("request", None)

        if self.board_id is None:
            self.board_id = self.post.board_id
        if not self.wr_datetime:
            self.wr_datetime = timezone.now()
        if not self.wr_last:
            self.wr_last = timezone.now()
        if not self.order_num:
            self.order_num = bbs_utils.get_next_num(True, board_id=self.board_id)
        if self.wr_comment is None:
            parent_comment = None
            if self.parent and self.post_id:
                parent_comment = Comment.objects.filter(pk=self.parent, post_id=self.post_id).only(
                    "wr_comment", "order_num"
                ).first()
            if parent_comment:
                self.wr_comment = (
                    parent_comment.wr_comment
                    if parent_comment.wr_comment is not None
                    else parent_comment.order_num
                )
            else:
                self.wr_comment = self._next_comment_group()
        
        # wr_ip가 없으면
        if not self.wr_ip:
            if request:
                self.wr_ip = lib.get_client_ip(request)
                # self.wr_comment_reply = None
                # self.parent = None
                # self.wr_option = None
                
        super().save(*args, **kwargs)

    class Meta:
        app_label = "bbs"
        verbose_name = _("댓글관리")
        verbose_name_plural = _("댓글관리")
        indexes = [
            models.Index(
                fields=["order_num", "parent", "wr_datetime"],
                name="bbs_comment_order_idx",
            ),
        ]


def validate_file_extension(value):
    ext = os.path.splitext(value.name)[1]  # [0] returns path+filename
    valid_extensions = [
        ".pdf",
        ".doc",
        ".docx",
        ".jpg",
        ".jpeg",
        ".gif",
        ".png",
        ".xlsx",
        ".xls",
        ".zip",
        ".jfif",
    ]
    if ext.lower() not in valid_extensions:
        raise ValidationError("Unsupported file extension.")


# Pillow reports a JPEG that carries an MPF segment (phone portrait/depth shots) as "MPO"; it is
# still a JPEG to browsers, so it is accepted wherever JPEG is.
IMAGE_UPLOAD_FORMATS = {
    ".gif": {"GIF"},
    ".jfif": {"JPEG", "MPO"},
    ".jpg": {"JPEG", "MPO"},
    ".jpeg": {"JPEG", "MPO"},
    ".png": {"PNG"},
}
FILE_SIGNATURES = {
    ".doc": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    ".xls": (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
    ".docx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".xlsx": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
    ".pdf": (b"%PDF-",),
    ".zip": (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
}
CONTENT_TYPES_BY_EXTENSION = {
    ".doc": {"application/msword"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/x-zip-compressed",
    },
    ".gif": {"image/gif"},
    ".jfif": {"image/jpeg", "image/pjpeg"},
    ".jpg": {"image/jpeg", "image/pjpeg"},
    ".jpeg": {"image/jpeg", "image/pjpeg"},
    ".pdf": {"application/pdf", "application/x-pdf"},
    ".png": {"image/png"},
    ".xls": {"application/vnd.ms-excel"},
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/zip",
        "application/x-zip-compressed",
    },
    ".zip": {"application/zip", "application/x-zip-compressed"},
}


def _reset_uploaded_file(uploaded_file):
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError):
        pass


def _validate_image_upload_content(uploaded_file, extension):
    _reset_uploaded_file(uploaded_file)
    try:
        image = Image.open(uploaded_file)
        image_format = image.format
        image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValidationError(
            _("Uploaded file content is not a valid image."),
            code="invalid_file_content",
        ) from exc
    finally:
        _reset_uploaded_file(uploaded_file)

    if image_format not in IMAGE_UPLOAD_FORMATS[extension]:
        raise ValidationError(
            _("Uploaded image content does not match the file extension."),
            code="invalid_file_content",
        )


def _validate_signature_upload_content(uploaded_file, extension):
    signatures = FILE_SIGNATURES[extension]
    header_length = max(len(signature) for signature in signatures)

    _reset_uploaded_file(uploaded_file)
    try:
        header = uploaded_file.read(header_length)
    finally:
        _reset_uploaded_file(uploaded_file)

    if not any(header.startswith(signature) for signature in signatures):
        raise ValidationError(
            _("Uploaded file content does not match the file extension."),
            code="invalid_file_content",
        )


def _validate_upload_content_type(uploaded_file, extension):
    content_type = getattr(uploaded_file, "content_type", "")
    content_type = content_type.split(";", 1)[0].strip().lower()
    if not content_type or content_type == "application/octet-stream":
        return

    expected_content_types = CONTENT_TYPES_BY_EXTENSION.get(extension)
    if expected_content_types and content_type not in expected_content_types:
        raise ValidationError(
            _("Uploaded MIME type does not match the file extension."),
            code="invalid_file_content_type",
        )


def validate_upload_file_content(uploaded_file):
    extension = os.path.splitext(getattr(uploaded_file, "name", ""))[1].lower()

    if extension in IMAGE_UPLOAD_FORMATS:
        _validate_image_upload_content(uploaded_file, extension)
    elif extension in FILE_SIGNATURES:
        _validate_signature_upload_content(uploaded_file, extension)

    _validate_upload_content_type(uploaded_file, extension)


# https://zzzinho.tistory.com/100
# https://www.faqcode4u.com/faq/141262/django-how-to-save-original-filename-in-filefield
# https://stackoverflow.com/questions/2673647/enforce-unique-upload-file-names-using-django


def get_board_file_path(board_id):

    return os.path.join(defaults.BBS_FILE_DIR + "/" + str(board_id))


def file_upload_to(instance, filename):
    if getattr(instance, "bf_source", "") == "":
        instance.bf_source = filename

    ext = filename.split(".")[-1] if "." in filename else ""
    filename = "%s.%s" % (str(uuid.uuid4().hex), ext)

    return os.path.join(defaults.BBS_FILE_DIR + "/" + str(instance.board.id) + "/", filename)


def delete_post_file_storage(field_file):
    file_name = getattr(field_file, "name", "")
    if not file_name:
        return

    storage = getattr(field_file, "storage", None)
    if not storage:
        return

    try:
        if storage.exists(file_name):
            storage.delete(file_name)
    except (OSError, SuspiciousFileOperation) as exc:
        logger.warning("Failed to delete post file '%s': %s", file_name, exc)


class Post_file(models.Model):
    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="board_files",
        verbose_name=_("게시판"),
    )
    post = models.ForeignKey(
        Post, on_delete=models.CASCADE, related_name="post_files", verbose_name=_("게시글")
    )
    bf_no = models.IntegerField(_("게시글파일순서"), default=0)
    bf_file = models.FileField(
        blank=True,
        upload_to=file_upload_to,
        verbose_name="Files",
        validators=[validate_file_extension, validate_upload_file_content],
        help_text="Allowed size is 50MB",
    )
    #  path = models.FileField(upload_to=file_upload_path, null=True)
    # bf_file = models.CharField(_("파일명"), max_length=255, null=True, blank=True, default='')
    bf_source = models.CharField(_("파일원본이름"), max_length=255, null=True, blank=True, default="")
    bf_download = models.IntegerField(_("다운로드수"), default=0)
    bf_content = models.TextField(_("내용"), null=True, blank=True, default="")
    bf_fileurl = models.CharField(_("파일url"), max_length=255, null=True, blank=True, default="")
    bf_thumburl = models.CharField(_("썸네일url"), max_length=255, null=True, blank=True, default="")
    bf_storage = models.CharField(_("스토리지이름"), max_length=20, null=True, blank=True, default="")
    bf_filesize = models.IntegerField(_("파일용량"), default=0)
    bf_width = models.IntegerField(_("파일가로길이"), default=0)
    bf_height = models.IntegerField(_("파일세로길이"), default=0)
    bf_type = models.PositiveSmallIntegerField(_("첨부파일유형"), default=0)
    bf_datetime = models.DateTimeField(_("등록일"))

    def save(self, *args, **kwargs):

        # self.bf_type = 0
        # self.bf_width = 0
        # self.bf_height = 0
        # self.bf_filesize = 0

        if self.bf_file and hasattr(self.bf_file, "file"):

            trial_image = {}

            try:

                if hasattr(self.bf_file.file, "content_type"):
                    self.bf_type = bbs_utils.get_image_type_number(self.bf_file.file.content_type)

                trial_image = Image.open(self.bf_file.file)
                trial_image.verify()
                self.bf_width, self.bf_height = trial_image.size

            except (IOError, SyntaxError) as e:
                pass

            self.bf_filesize = self.bf_file.file.size

        if self.bf_datetime is None:
            self.bf_datetime = timezone.now()

        super().save(*args, **kwargs)

    # https://zzzinho.tistory.com/100
    def upload_to(self, instance, filename):
        return defaults.BBS_FILE_DIR + "/" + instance.board.id + "/" + filename

    @property
    def update_counter(self):
        self.bf_download = self.bf_download + 1
        self.save()

    class Meta:
        app_label = "bbs"
        verbose_name = _("글 첨부파일")
        verbose_name_plural = _("글 첨부파일")
        # unique_together = (("board", "post", "id"),)


@receiver(models.signals.post_delete, sender=Post_file)
def auto_delete_file_on_delete(sender, instance, **kwargs):
    """
    Deletes file from filesystem
    when corresponding `Post_file` object is deleted.
    """
    delete_post_file_storage(instance.bf_file)


@receiver(models.signals.pre_save, sender=Post_file)
def auto_delete_file_on_change(sender, instance, **kwargs):
    """
    Deletes old file from filesystem
    when corresponding `Post_file` object is updated
    with new file.
    """
    if not instance.pk:
        return False

    try:
        old_file = Post_file.objects.get(pk=instance.pk).bf_file
    except Post_file.DoesNotExist:
        return False

    new_file = instance.bf_file
    if not old_file == new_file:
        delete_post_file_storage(old_file)


def auto_save_uid():
    # nickname 필드의 default 값
    return uuid.uuid4().hex


class Post_scrap(models.Model):
    user = models.ForeignKey(
        UserModel,
        on_delete=models.CASCADE,
        related_name="post_scrap",
        blank=True,
        null=True,
        db_index=True,
    )
    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        verbose_name=_("게시판"),
    )
    post = models.ForeignKey(
        Post, on_delete=models.CASCADE, related_name="post", verbose_name=_("게시글")
    )
    ms_datetime = models.DateTimeField(_("등록일"))

    class Meta:
        db_table = defaults.DB_PREFIX + "post_scrap"
        verbose_name = _("Post scrap")
        verbose_name_plural = _("Post scraps")
        indexes = [
            models.Index(fields=["user"]),
        ]



class Post_good(models.Model):
    """One recommend / not-recommend per member and post (Gnuboard5 g5_board_good)."""

    user = models.ForeignKey(UserModel, on_delete=models.CASCADE, related_name="post_goods")
    board = models.ForeignKey(Board, on_delete=models.CASCADE, verbose_name=_("게시판"))
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="goods", verbose_name=_("게시글"))
    bg_flag = models.CharField(_("구분"), max_length=10)
    bg_datetime = models.DateTimeField(_("일시"), default=timezone.now)

    class Meta:
        db_table = defaults.DB_PREFIX + "post_good"
        verbose_name = _("Post good")
        verbose_name_plural = _("Post goods")
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="bbs_post_good_once_per_member")]

class Gnu_auto_save(models.Model):
    user = models.ForeignKey(
        UserModel,
        on_delete=models.SET_NULL,
        related_name="gnu_auto_save",
        blank=True,
        null=True,
        db_index=True,
    )
    as_uid = models.CharField(_("임시문자열"), max_length=100, unique=True, default=auto_save_uid)
    as_subject = models.CharField(_("임시제목"), max_length=255, null=True, blank=True, default="")
    as_content = models.TextField(_("임시내용"), max_length=255, null=True, blank=True, default="")
    as_datetime = models.DateTimeField(_("저장일"))

    class Meta:
        verbose_name = _("Autosave draft")
        verbose_name_plural = _("Autosave drafts")
        unique_together = (("user", "as_uid"),)

    @classmethod
    def user_autosave_count(self, user):
        return self.objects.filter(user=user).count()
