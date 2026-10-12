from datetime import timedelta

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import format_html
from django.urls import path
from unfold.admin import ModelAdmin

from gnu_jango.bbs.models import Group, Board, Post, Comment, Gnu_auto_save, Post_file, Post_scrap
from gnu_jango.config import config
from django.utils.translation import gettext_lazy as _


# from django_tuieditor.widgets import (
#     MarkdownEditorWidget,
#     MarkdownViewerWidget,
#     StaticMarkdownViewerWidget,
# )

# from gnu_jango.editor.tuieditor.widgets import (
#     MarkdownEditorWidget,
#     MarkdownViewerWidget,
#     StaticMarkdownViewerWidget,
# )

from gnu_jango.utils import editor
from gnu_jango.utils.admin_display import (
    badge,
    compact_text,
    fieldsets_without,
    format_number,
    snapshot_panel,
)


def datetime_value(value):
    if not value:
        return "-"
    try:
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value.strftime("%Y-%m-%d %H:%M:%S")


class GroupAdmin(ModelAdmin):
    # 관리자 리스트 페이지에서 노출되는 필드
    list_display = ["gr_id", "gr_subject"]


class BoardAdmin(ModelAdmin):
    # 관리자 리스트 페이지에서 노출되는 필드
    list_display = [
        "bo_table",
        "board_subject_display",
        "board_status",
        "board_volume",
        "board_permissions",
        "bo_device",
    ]
    list_display_links = ("bo_table", "board_subject_display")
    search_fields = ("bo_table", "bo_subject", "bo_mobile_subject", "bo_admin")
    list_filter = ("group", "bo_device", "bo_use_category", "bo_use_secret", "bo_use_search")
    readonly_fields = ("board_snapshot",)
    list_fullwidth = True
    # fields    = ('name', 'slug')

    # #list of fields to display in django admin
    # list_display = ['id', 'name', 'slug']

    # #if you want django admin to show the search bar, just add this line
    # search_fields = ['name', 'slug']

    # #to define model data list ordering
    # ordering = ('id','name')

    # fieldsets = (
    #     (None, {
    #         'fields': ('bo_list_level', 'bo_read_level', 'bo_write_level', 'bo_reply_level', 'bo_comment_level', 'bo_link_level', 'bo_upload_level', 'bo_download_level', 'bo_html_level'),
    #         'description': _('권한 1은 비회원, 2 이상 회원입니다. 권한은 10 이 가장 높습니다.')
    #     }),
    #     # ('Advanced options', {
    #     #     'classes': ('collapse',),
    #     #     'fields': ('registration_required', 'template_name'),
    #     # }),
    # )

    def get_form(self, request, obj=None, **kwargs):
        form = super(BoardAdmin, self).get_form(request, obj, **kwargs)

        form_initials = {
            "bo_count_delete": 1,
            "bo_count_modify": 1,
            "bo_read_point": getattr(config, "cf_read_point"),
            "bo_write_point": getattr(config, "cf_write_point"),
            "bo_comment_point": getattr(config, "cf_comment_point"),
            "bo_download_point": getattr(config, "cf_download_point"),
            "bo_gallery_cols": 4,
            "bo_gallery_width": 202,
            "bo_gallery_height": 150,
            "bo_mobile_gallery_width": 125,
            "bo_mobile_gallery_height": 100,
            "bo_table_width": 100,
            "bo_page_rows": getattr(config, "cf_page_rows"),
            "bo_mobile_page_rows": getattr(config, "cf_page_rows"),
            "bo_subject_len": 60,
            "bo_mobile_subject_len": 30,
            "bo_new": 24,
            "bo_hot": 100,
            "bo_image_width": 600,
            "bo_upload_count": 2,
            "bo_upload_size": 1048576,
            "bo_reply_order": 1,
            "bo_use_search": 1,
            "bo_use_secret": 0,
        }

        for k, v in form_initials.items():
            form.base_fields[k].initial = v

        # 환경설정에서 에디터를 사용한다면
        if config.cf_editor:
            # form.base_fields["bo_content_head"].widget = MarkdownEditorWidget()
            # form.base_fields["bo_mobile_content_head"].widget = MarkdownEditorWidget()
            # form.base_fields["bo_content_tail"].widget = MarkdownEditorWidget()
            # form.base_fields["bo_mobile_content_tail"].widget = MarkdownEditorWidget()
            # form.base_fields["bo_insert_content"].widget = MarkdownEditorWidget()

            form.base_fields["bo_content_head"].widget = editor.get_editor_widget()
            form.base_fields["bo_mobile_content_head"].widget = editor.get_editor_widget()
            form.base_fields["bo_content_tail"].widget = editor.get_editor_widget()
            form.base_fields["bo_mobile_content_tail"].widget = editor.get_editor_widget()
            form.base_fields["bo_insert_content"].widget = editor.get_editor_widget()

        # self.fields['privCreate'].label = 'Create a document'
        # form.base_fields['bo_gallery_cols'].initial = 4
        # form.base_fields['bo_list_level'].initial = 1
        # form.base_fields['gr_id'].label_from_instance = lambda inst: "{} {}".format(inst.gr_id, inst.gr_subject)
        return form

    def get_fieldsets(self, request, obj=None):
        fieldsets = fieldsets_without(tuple(super().get_fieldsets(request, obj)), "board_snapshot")
        return (
            (
                _("Board snapshot"),
                {
                    "classes": ("tab",),
                    "fields": ("board_snapshot",),
                },
            ),
        ) + fieldsets

    @admin.display(description=_("Board"), ordering="bo_subject")
    def board_subject_display(self, obj):
        return obj.bo_subject

    @admin.display(description=_("Status"))
    def board_status(self, obj):
        if not obj.bo_use_search:
            return badge(_("Search hidden"), "warning")
        if obj.bo_use_secret:
            return badge(_("Secret enabled"), "info")
        return badge(_("Open board"), "success")

    @admin.display(description=_("Volume"))
    def board_volume(self, obj):
        return format_html(
            "{} / {}",
            badge(_("%(count)s posts") % {"count": format_number(obj.bo_count_write)}, "info"),
            badge(_("%(count)s comments") % {"count": format_number(obj.bo_count_comment)}, "neutral"),
        )

    @admin.display(description=_("Permissions"))
    def board_permissions(self, obj):
        return compact_text(
            _("Read %(level)s") % {"level": obj.bo_read_level},
            _("Write %(level)s") % {"level": obj.bo_write_level},
            _("Comment %(level)s") % {"level": obj.bo_comment_level},
        )

    @admin.display(description=_("Board snapshot"))
    def board_snapshot(self, obj):
        if not obj:
            return "-"
        state = _("Open board")
        tone = "success"
        if obj.bo_use_secret:
            state, tone = _("Secret enabled"), "info"
        if not obj.bo_use_search:
            state, tone = _("Search hidden"), "warning"

        feature_count = sum(
            bool(value)
            for value in (
                obj.bo_use_category,
                obj.bo_use_secret,
                obj.bo_use_dhtml_editor,
                obj.bo_use_rss_view,
                obj.bo_use_good,
                obj.bo_use_nogood,
                obj.bo_use_sns,
                obj.bo_use_captcha,
            )
        )
        return snapshot_panel(
            _("Board snapshot"),
            state,
            tone,
            _("Review board exposure, permissions, post volume, points, and mobile behavior together."),
            (
                (_("Board identity"), obj.bo_subject, compact_text(obj.bo_table, obj.bo_mobile_subject)),
                (_("Content volume"), format_number(obj.bo_count_write), _("%(count)s comments") % {"count": format_number(obj.bo_count_comment)}),
                (_("Access levels"), _("Read %(read)s / write %(write)s") % {"read": obj.bo_read_level, "write": obj.bo_write_level}, _("Comment %(level)s") % {"level": obj.bo_comment_level}),
                (_("Points"), _("Write %(write)s / read %(read)s") % {"write": format_number(obj.bo_write_point), "read": format_number(obj.bo_read_point)}, _("Comment %(point)s") % {"point": format_number(obj.bo_comment_point)}),
                (_("Features"), _("%(count)s enabled") % {"count": format_number(feature_count)}, compact_text(_("Category") if obj.bo_use_category else "", _("Secret") if obj.bo_use_secret else "", _("RSS") if obj.bo_use_rss_view else "")),
                (_("Mobile behavior"), obj.bo_device, _("%(rows)s rows") % {"rows": format_number(obj.bo_mobile_page_rows)}),
            ),
        )


# Register your models here.
admin.site.register(Group, GroupAdmin)
admin.site.register(Board, BoardAdmin)


@admin.register(Post)
class PostAdmin(ModelAdmin):
    list_before_template = "admin/bbs/post_list_before.html"
    list_display = (
        "id",
        "post_subject_display",
        "board",
        "author_display",
        "post_status",
        "post_engagement",
        "wr_datetime",
    )
    list_display_links = ("id", "post_subject_display")
    search_fields = ("wr_subject", "wr_content", "wr_name", "wr_email", "board__bo_subject", "board__bo_table")
    list_filter = ("board", "is_notice", "wr_option", "wr_datetime")
    list_select_related = ("board", "user")
    readonly_fields = ("post_snapshot",)
    list_fullwidth = True

    def get_fieldsets(self, request, obj=None):
        fieldsets = fieldsets_without(tuple(super().get_fieldsets(request, obj)), "post_snapshot")
        return (
            (
                _("Post snapshot"),
                {
                    "classes": ("tab",),
                    "fields": ("post_snapshot",),
                },
            ),
        ) + fieldsets

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "activity/",
                self.admin_site.admin_view(self.activity_report_view),
                name="bbs_post_activity",
            ),
        ]
        return custom_urls + urls

    def activity_report_view(self, request):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied

        today = timezone.localdate()
        raw_start = str(request.GET.get("date_from") or "").strip()
        raw_end = str(request.GET.get("date_to") or "").strip()
        start = parse_date(raw_start)
        end = parse_date(raw_end)
        if not raw_start and not raw_end:
            start = today - timedelta(days=29)
            end = today

        board_id_value = str(request.GET.get("board") or "").strip()
        try:
            board_id = int(board_id_value) if board_id_value else None
        except ValueError:
            board_id = None
        board_choices = Board.objects.only("id", "bo_table", "bo_subject").order_by("bo_subject", "bo_table")
        if board_id is not None and not board_choices.filter(pk=board_id).exists():
            board_id = None

        content_type = str(request.GET.get("content_type") or "all").strip()
        if content_type not in {"all", "posts", "comments"}:
            content_type = "all"
        query = str(request.GET.get("q") or "").strip()[:120]
        date_range_error = bool(start and end and start > end)

        post_rows = Post.objects.all()
        comment_rows = Comment.objects.all()
        if date_range_error:
            post_rows = post_rows.none()
            comment_rows = comment_rows.none()
        else:
            if start:
                post_rows = post_rows.filter(wr_datetime__date__gte=start)
                comment_rows = comment_rows.filter(wr_datetime__date__gte=start)
            if end:
                post_rows = post_rows.filter(wr_datetime__date__lte=end)
                comment_rows = comment_rows.filter(wr_datetime__date__lte=end)
        if board_id:
            post_rows = post_rows.filter(board_id=board_id)
            comment_rows = comment_rows.filter(board_id=board_id)
        if query:
            post_rows = post_rows.filter(
                Q(wr_subject__icontains=query)
                | Q(wr_content__icontains=query)
                | Q(wr_name__icontains=query)
                | Q(user__username__icontains=query)
                | Q(board__bo_subject__icontains=query)
                | Q(board__bo_table__icontains=query)
            )
            comment_rows = comment_rows.filter(
                Q(wr_content__icontains=query)
                | Q(wr_name__icontains=query)
                | Q(user__username__icontains=query)
                | Q(post__wr_subject__icontains=query)
                | Q(board__bo_subject__icontains=query)
                | Q(board__bo_table__icontains=query)
            )
        if content_type == "posts":
            comment_rows = Comment.objects.none()
        elif content_type == "comments":
            post_rows = Post.objects.none()

        timezone_value = timezone.get_current_timezone()
        post_daily = (
            post_rows.annotate(day=TruncDate("wr_datetime", tzinfo=timezone_value))
            .values("day")
            .annotate(total=Count("pk"))
            .order_by("-day")[:91]
        )
        comment_daily = (
            comment_rows.annotate(day=TruncDate("wr_datetime", tzinfo=timezone_value))
            .values("day")
            .annotate(total=Count("pk"))
            .order_by("-day")[:91]
        )
        daily_activity = {}
        for row in post_daily:
            daily_activity[row["day"]] = {"day": row["day"], "posts": row["total"], "comments": 0}
        for row in comment_daily:
            daily_activity.setdefault(row["day"], {"day": row["day"], "posts": 0, "comments": 0})
            daily_activity[row["day"]]["comments"] = row["total"]
        all_daily_rows = [daily_activity[day] for day in sorted(daily_activity, reverse=True)]
        daily_rows_limited = len(all_daily_rows) > 90
        daily_rows = all_daily_rows[:90]

        board_activity = {}
        post_board_rows = (
            post_rows.values("board_id", "board__bo_table", "board__bo_subject")
            .annotate(total=Count("pk"))
            .order_by("-total", "board__bo_subject")
        )
        comment_board_rows = (
            comment_rows.values("board_id", "board__bo_table", "board__bo_subject")
            .annotate(total=Count("pk"))
            .order_by("-total", "board__bo_subject")
        )
        for row in post_board_rows:
            board_activity[row["board_id"]] = {
                "id": row["board_id"],
                "table": row["board__bo_table"],
                "subject": row["board__bo_subject"],
                "posts": row["total"],
                "comments": 0,
            }
        for row in comment_board_rows:
            activity = board_activity.setdefault(
                row["board_id"],
                {
                    "id": row["board_id"],
                    "table": row["board__bo_table"],
                    "subject": row["board__bo_subject"],
                    "posts": 0,
                    "comments": 0,
                },
            )
            activity["comments"] = row["total"]
        board_rows = sorted(
            board_activity.values(),
            key=lambda row: (-(row["posts"] + row["comments"]), row["subject"] or ""),
        )[:20]

        posts = list(post_rows.select_related("board", "user").order_by("-wr_datetime", "-pk")[:20])
        comments = list(comment_rows.select_related("board", "post", "user").order_by("-wr_datetime", "-pk")[:20])
        recent_posts = [
            {
                "id": post.pk,
                "subject": post.wr_subject or _("(no subject)"),
                "board": post.board.bo_subject if post.board_id else "-",
                "author": post.user.get_username() if post.user_id and post.user else post.wr_name or "-",
                "time": datetime_value(post.wr_datetime),
                "views": format_number(post.wr_hit),
                "comments": format_number(post.wr_comment),
            }
            for post in posts
        ]
        recent_comments = [
            {
                "id": comment.pk,
                "subject": compact_text(comment.post.wr_subject if comment.post_id else "", comment.wr_content, limit=100),
                "board": comment.board.bo_subject if comment.board_id else "-",
                "author": comment.user.get_username() if comment.user_id and comment.user else comment.wr_name or "-",
                "time": datetime_value(comment.wr_datetime),
            }
            for comment in comments
        ]

        active_board_ids = set(post_rows.values_list("board_id", flat=True).distinct())
        active_board_ids.update(comment_rows.values_list("board_id", flat=True).distinct())
        context = {
            **self.admin_site.each_context(request),
            "title": _("Content activity report"),
            "subtitle": _("Review post and comment volume by date and board."),
            "opts": self.model._meta,
            "report_path": request.path,
            "filters": {
                "date_from": start.isoformat() if start else "",
                "date_to": end.isoformat() if end else "",
                "board": board_id,
                "content_type": content_type,
                "q": query,
            },
            "board_choices": board_choices,
            "content_types": [
                ("all", _("Posts and comments")),
                ("posts", _("Posts only")),
                ("comments", _("Comments only")),
            ],
            "date_range_error": date_range_error,
            "metrics": [
                {"label": _("Posts"), "value": format_number(post_rows.count()), "hint": _("Matching posts in this period")},
                {"label": _("Comments"), "value": format_number(comment_rows.count()), "hint": _("Matching comments in this period")},
                {"label": _("Active boards"), "value": format_number(len(active_board_ids)), "hint": _("Boards with matching activity")},
            ],
            "daily_rows": daily_rows,
            "daily_rows_limited": daily_rows_limited,
            "board_rows": board_rows,
            "recent_posts": recent_posts,
            "recent_comments": recent_comments,
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/bbs/activity_report.html", context)

    @admin.display(description=_("Post"), ordering="wr_subject")
    def post_subject_display(self, obj):
        return obj.wr_subject or "-"

    @admin.display(description=_("Author"))
    def author_display(self, obj):
        if obj.user_id and obj.user:
            return obj.user.get_username()
        return obj.wr_name or "-"

    @admin.display(description=_("Status"))
    def post_status(self, obj):
        if obj.is_notice:
            return badge(_("Notice"), "info")
        if "secret" in str(obj.wr_option or ""):
            return badge(_("Secret"), "warning")
        return badge(_("Public"), "success")

    @admin.display(description=_("Engagement"))
    def post_engagement(self, obj):
        return format_html(
            "{} {} {}",
            badge(_("Views %(count)s") % {"count": format_number(obj.wr_hit)}, "info"),
            badge(_("Comments %(count)s") % {"count": format_number(obj.wr_comment)}, "neutral"),
            badge(_("Likes %(count)s") % {"count": format_number(obj.wr_good)}, "success"),
        )

    @admin.display(description=_("Post snapshot"))
    def post_snapshot(self, obj):
        if not obj:
            return "-"
        if obj.is_notice:
            state, tone = _("Notice"), "info"
        elif "secret" in str(obj.wr_option or ""):
            state, tone = _("Secret"), "warning"
        else:
            state, tone = _("Public"), "success"

        return snapshot_panel(
            _("Post snapshot"),
            state,
            tone,
            _("Review board, author, visibility, engagement, links, and attachments together."),
            (
                (_("Post title"), obj.wr_subject or "-", compact_text(obj.board.bo_table if obj.board_id else "", obj.ca_name)),
                (_("Author"), self.author_display(obj), compact_text(obj.wr_email, obj.wr_ip)),
                (_("Engagement"), _("Views %(views)s / comments %(comments)s") % {"views": format_number(obj.wr_hit), "comments": format_number(obj.wr_comment)}, _("Likes %(good)s / dislikes %(bad)s") % {"good": format_number(obj.wr_good), "bad": format_number(obj.wr_nogood)}),
                (_("Links and files"), _("%(links)s links / %(files)s files") % {"links": format_number(bool(obj.wr_link1) + bool(obj.wr_link2)), "files": format_number(obj.wr_file)}, compact_text(obj.wr_link1, obj.wr_link2)),
                (_("Written"), datetime_value(obj.wr_datetime), datetime_value(obj.wr_last)),
                (_("Slug"), obj.wr_slug or "-", _("Parent %(parent)s") % {"parent": obj.wr_parent}),
            ),
        )


@admin.register(Comment)
class CommentAdmin(ModelAdmin):
    list_display = ("id", "post", "board", "author_display", "comment_status", "comment_score", "wr_datetime")
    search_fields = ("wr_content", "wr_name", "wr_email", "post__wr_subject", "board__bo_subject")
    list_filter = ("board", "wr_option", "wr_datetime")
    list_select_related = ("board", "post", "user")
    readonly_fields = ("comment_snapshot",)
    list_fullwidth = True

    def get_fieldsets(self, request, obj=None):
        fieldsets = fieldsets_without(tuple(super().get_fieldsets(request, obj)), "comment_snapshot")
        return (
            (
                _("Comment snapshot"),
                {
                    "classes": ("tab",),
                    "fields": ("comment_snapshot",),
                },
            ),
        ) + fieldsets

    @admin.display(description=_("Author"))
    def author_display(self, obj):
        if obj.user_id and obj.user:
            return obj.user.get_username()
        return obj.wr_name or "-"

    @admin.display(description=_("Status"))
    def comment_status(self, obj):
        if "secret" in str(obj.wr_option or ""):
            return badge(_("Secret"), "warning")
        return badge(_("Public"), "success")

    @admin.display(description=_("Score"))
    def comment_score(self, obj):
        return format_html(
            "{} {}",
            badge(_("Likes %(count)s") % {"count": format_number(obj.wr_good)}, "success"),
            badge(_("Dislikes %(count)s") % {"count": format_number(obj.wr_nogood)}, "neutral"),
        )

    @admin.display(description=_("Comment snapshot"))
    def comment_snapshot(self, obj):
        if not obj:
            return "-"
        state, tone = (_("Secret"), "warning") if "secret" in str(obj.wr_option or "") else (_("Public"), "success")
        return snapshot_panel(
            _("Comment snapshot"),
            state,
            tone,
            _("Review comment author, parent post, visibility, score, and edit trail together."),
            (
                (_("Parent post"), str(obj.post or "-"), str(obj.board or "-")),
                (_("Author"), self.author_display(obj), compact_text(obj.wr_email, obj.wr_ip)),
                (_("Score"), _("Likes %(good)s / dislikes %(bad)s") % {"good": format_number(obj.wr_good), "bad": format_number(obj.wr_nogood)}, obj.wr_option or "-"),
                (_("Written"), datetime_value(obj.wr_datetime), datetime_value(obj.wr_last)),
            ),
        )


@admin.register(Post_file)
class PostFileAdmin(ModelAdmin):
    list_display = ("id", "board", "post", "file_name", "bf_download", "file_size_display", "bf_datetime")
    search_fields = ("bf_source", "bf_file", "post__wr_subject", "board__bo_subject", "board__bo_table")
    list_filter = ("board", "bf_type", "bf_datetime")
    list_select_related = ("board", "post")
    ordering = ("-bf_datetime", "-id")
    readonly_fields = (
        "board",
        "post",
        "bf_no",
        "bf_file",
        "bf_source",
        "bf_download",
        "bf_content",
        "bf_fileurl",
        "bf_thumburl",
        "bf_storage",
        "bf_filesize",
        "bf_width",
        "bf_height",
        "bf_type",
        "bf_datetime",
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    @admin.display(description=_("File"), ordering="bf_source")
    def file_name(self, obj):
        return obj.bf_source or str(obj.bf_file or "-")

    @admin.display(description=_("File size"), ordering="bf_filesize")
    def file_size_display(self, obj):
        return format_number(obj.bf_filesize)


@admin.register(Post_scrap)
class PostScrapAdmin(ModelAdmin):
    list_display = ("id", "user", "board", "post", "ms_datetime")
    search_fields = ("user__username", "post__wr_subject", "board__bo_subject", "board__bo_table")
    list_filter = ("board", "ms_datetime")
    list_select_related = ("user", "board", "post")
    ordering = ("-ms_datetime", "-id")


@admin.register(Gnu_auto_save)
class GnuAutoSaveAdmin(ModelAdmin):
    list_display = ("id", "user", "as_uid", "subject_display", "as_datetime")
    search_fields = ("user__username", "as_uid", "as_subject", "as_content")
    list_filter = ("as_datetime",)
    list_select_related = ("user",)
    ordering = ("-as_datetime", "-id")
    readonly_fields = ("user", "as_uid", "as_subject", "as_content", "as_datetime")
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    @admin.display(description=_("Subject"), ordering="as_subject")
    def subject_display(self, obj):
        return obj.as_subject or "-"
