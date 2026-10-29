from gnu_jango.core.admin._common import *  # noqa: F401,F403
from gnu_jango.core.tasks import send_mail_campaign_task
from gnu_jango.core.maintenance import maintenance_snapshot, run_maintenance_action
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.utils.translation import gettext_lazy as _
from gnu_jango.core.models import NotificationAnnouncement, NotificationWork
from gnu_jango.utils.date_ranges import local_days


@admin.register(NotificationAnnouncement)
class NotificationAnnouncementAdmin(ModelAdmin):
    list_display = ("request_id", "created_by", "recipient_count", "status", "created_at")
    readonly_fields = ("request_id", "created_by", "content_digest", "recipient_count", "status", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NotificationWork)
class NotificationWorkAdmin(ModelAdmin):
    list_display = ("id", "kind", "user", "attempts", "error_type", "available_at", "completed_at")
    list_filter = ("kind", "completed_at")
    exclude = ("payload",)
    readonly_fields = ("event_key", "kind", "user", "attempts", "error_type", "created_at", "available_at", "completed_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Notification)
class NotificationAdmin(ModelAdmin):
    list_display = ("nt_id", "user", "nt_type", "nt_title", "nt_sent_at", "nt_read_at")
    list_filter = ("nt_type", "nt_sent_at", "nt_read_at")
    search_fields = ("user__username", "nt_title", "nt_body")
    ordering = ("-nt_sent_at", "-nt_id")

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "announce/",
                self.admin_site.admin_view(self.announcement_view),
                name="core_notification_announce",
            ),
            path(
                "mail-tools/",
                self.admin_site.admin_view(self.mail_tools_view),
                name="core_notification_mail_tools",
            ),
        ]
        return custom_urls + urls

    def announcement_view(self, request):
        from gnu_jango.notifications.announcements import announcement_view

        return announcement_view(self, request)

    def mail_tools_view(self, request):
        test_form = {
            "recipient": request.POST.get("recipient", ""),
            "subject": request.POST.get("subject", _("GNU Jango mail test")),
            "body": request.POST.get("body", _("This is a test message from the GNU Jango admin.")),
        }
        member_form = {
            "recipient_group": request.POST.get("recipient_group", "active"),
            "subject": request.POST.get("member_subject", _("Member notice")),
            "body": request.POST.get("member_body", ""),
            "limit": str(self.mail_limit(request)),
        }

        if request.method == "POST":
            mode = request.POST.get("mode")
            if mode == "test":
                self.handle_test_mail(request, test_form)
            elif mode == "members":
                self.handle_member_mail(request, member_form)

        preview_queryset = self.member_mail_queryset(member_form["recipient_group"])
        preview_limit = int(member_form["limit"])
        context = {
            **self.admin_site.each_context(request),
            "title": _("Mail tools"),
            "subtitle": _("Send a test email or prepare member mail from the admin console."),
            "opts": self.model._meta,
            "report_path": request.path,
            "from_email": getattr(settings, "DEFAULT_FROM_EMAIL", ""),
            "email_backend": getattr(settings, "MAILERS", {}).get("default", {}).get("BACKEND", ""),
            "test_form": test_form,
            "member_form": member_form,
            "recipient_groups": [
                ("active", _("Active members")),
                ("staff", _("Staff members")),
                ("superuser", _("Superusers")),
                ("all", _("All members with email")),
            ],
            "preview_count": admin_number(preview_queryset.count()),
            "preview_limit": admin_number(preview_limit),
            "preview_emails": list(preview_queryset.values_list("email", flat=True)[:8]),
            "recent_campaigns": MailCampaign.objects.select_related("created_by").order_by("-created_at", "-id")[:8],
            "failed_send_count": admin_number(MailSendLog.objects.filter(status="failed").count()),
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/core/mail_tools.html", context)

    def handle_test_mail(self, request, form_data):
        recipient = str(form_data["recipient"] or "").strip()
        subject = str(form_data["subject"] or "").strip()
        body = str(form_data["body"] or "").strip()
        try:
            recipient = forms.EmailField().clean(recipient)
        except ValidationError:
            self.message_user(request, _("Enter a valid test recipient email."), level=messages.ERROR)
            return
        if not subject or not body:
            self.message_user(request, _("Subject and body are required."), level=messages.ERROR)
            return
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "webmaster@localhost")
        campaign = MailCampaign.objects.create(
            title=_("Test email to %(email)s") % {"email": recipient},
            recipient_group="test",
            subject=subject,
            body=body,
            from_email=from_email,
            recipient_count=1,
            status="sending",
            created_by=request.user if getattr(request.user, "is_authenticated", False) else None,
        )
        self.queue_mail_campaign(
            request,
            campaign,
            [{"email": recipient}],
            _("Test email queued for %(email)s.") % {"email": recipient},
        )

    def handle_member_mail(self, request, form_data):
        subject = str(form_data["subject"] or "").strip()
        body = str(form_data["body"] or "").strip()
        if not subject or not body:
            self.message_user(request, _("Subject and body are required."), level=messages.ERROR)
            return
        if request.POST.get("send_confirm") != "1":
            self.message_user(request, _("Recipient preview updated. Tick confirmation to send member mail."), level=messages.WARNING)
            return

        queryset = self.member_mail_queryset(form_data["recipient_group"])
        limit = int(form_data["limit"])
        recipient_rows = list(queryset.values("pk", "email")[:limit])
        recipients = [row["email"] for row in recipient_rows]
        if not recipients:
            self.message_user(request, _("No member email recipients matched the selected group."), level=messages.ERROR)
            return
        from_email = getattr(settings, "DEFAULT_FROM_EMAIL", "webmaster@localhost")
        campaign = MailCampaign.objects.create(
            title=subject,
            recipient_group=form_data["recipient_group"],
            subject=subject,
            body=body,
            from_email=from_email,
            recipient_count=len(recipients),
            status="sending",
            created_by=request.user if getattr(request.user, "is_authenticated", False) else None,
        )
        self.queue_mail_campaign(
            request,
            campaign,
            [{"user_id": row["pk"], "email": row["email"]} for row in recipient_rows],
            _("Member email queued for %(count)s recipients.") % {"count": admin_number(len(recipients))},
        )

    def queue_mail_campaign(self, request, campaign, recipient_rows, success_message):
        try:
            from gnu_jango.core.background import enabled
            if enabled():
                from gnu_jango.core.queued_mail import queue_campaign
                queue_campaign(campaign.pk, recipient_rows)
            else:
                send_mail_campaign_task.delay(campaign.pk, recipient_rows)
        except Exception as exc:
            campaign.status = "failed"
            campaign.failed_count = campaign.recipient_count
            campaign.sent_at = timezone.now()
            campaign.note = force_str(exc)
            campaign.save(update_fields=["status", "failed_count", "sent_at", "note"])
            MailSendLog.objects.bulk_create(
                [
                    MailSendLog(
                        campaign=campaign,
                        recipient_user_id=row.get("user_id") or row.get("pk") or row.get("id"),
                        recipient_email=row["email"],
                        status="failed",
                        error_message=force_str(exc),
                    )
                    for row in recipient_rows
                    if row.get("email")
                ],
                batch_size=500,
            )
            self.message_user(request, _("Mail campaign could not be queued: %(error)s") % {"error": exc}, level=messages.ERROR)
            return
        self.message_user(request, success_message, level=messages.SUCCESS)

    def member_mail_queryset(self, recipient_group):
        user_model = get_user_model()
        queryset = user_model.objects.exclude(email="").exclude(email__isnull=True)
        if recipient_group == "active":
            queryset = queryset.filter(is_active=True)
        elif recipient_group == "staff":
            queryset = queryset.filter(is_staff=True)
        elif recipient_group == "superuser":
            queryset = queryset.filter(is_superuser=True)
        return queryset.order_by("email")

    def mail_limit(self, request):
        try:
            limit = int(request.POST.get("limit") or request.GET.get("limit") or 200)
        except (TypeError, ValueError):
            limit = 200
        return min(max(limit, 1), 1000)


class MailSendLogInline(TabularInline):
    model = MailSendLog
    extra = 0
    can_delete = False
    fields = ("recipient_email", "recipient_user", "status", "error_message", "sent_at")
    readonly_fields = fields
    show_change_link = True
    tab = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(MailCampaign)
class MailCampaignAdmin(ModelAdmin):
    list_display = (
        "title_display",
        "recipient_group",
        "status_display",
        "recipient_count",
        "sent_count",
        "failed_count",
        "created_by_display",
        "sent_at_display",
    )
    list_filter = ("status", "recipient_group", "created_at", "sent_at")
    search_fields = ("title", "subject", "body", "from_email", "logs__recipient_email")
    ordering = ("-created_at", "-id")
    list_per_page = 50
    inlines = (MailSendLogInline,)
    readonly_fields = (
        "recipient_group",
        "subject",
        "body",
        "from_email",
        "recipient_count",
        "sent_count",
        "failed_count",
        "status",
        "created_by",
        "created_at",
        "sent_at",
    )
    fieldsets = (
        (
            "캠페인 요약",
            {
                "classes": ("tab",),
                "fields": (
                    ("title", "status"),
                    ("recipient_group", "recipient_count"),
                    ("sent_count", "failed_count"),
                    ("created_by", "created_at", "sent_at"),
                ),
            },
        ),
        (
            "메일 내용",
            {
                "classes": ("tab",),
                "fields": ("from_email", "subject", "body", "note"),
            },
        ),
    )

    @admin.display(description="캠페인", ordering="title")
    def title_display(self, obj):
        return obj.title or obj.subject

    @admin.display(description="상태", ordering="status")
    def status_display(self, obj):
        tones = {
            "draft": "neutral",
            "sending": "warning",
            "sent": "success",
            "partial": "warning",
            "failed": "danger",
        }
        return admin_badge(obj.get_status_display(), tones.get(obj.status, "neutral"))

    @admin.display(description="작성자", ordering="created_by")
    def created_by_display(self, obj):
        return getattr(obj.created_by, "username", "") or "-"

    @admin.display(description="발송일시", ordering="sent_at")
    def sent_at_display(self, obj):
        return admin_datetime(obj.sent_at)


@admin.register(MailSendLog)
class MailSendLogAdmin(ModelAdmin):
    list_display = ("sent_at_display", "campaign_display", "recipient_email", "recipient_user_display", "status_display")
    list_filter = ("status", "sent_at", "campaign__recipient_group")
    search_fields = ("recipient_email", "recipient_user__username", "campaign__title", "campaign__subject", "error_message")
    ordering = ("-sent_at", "-id")
    list_per_page = 50
    readonly_fields = ("campaign", "recipient_user", "recipient_email", "status", "error_message", "sent_at")
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="처리일시", ordering="sent_at")
    def sent_at_display(self, obj):
        return admin_datetime(obj.sent_at)

    @admin.display(description="캠페인", ordering="campaign")
    def campaign_display(self, obj):
        return obj.campaign.title or obj.campaign.subject

    @admin.display(description="회원", ordering="recipient_user")
    def recipient_user_display(self, obj):
        return getattr(obj.recipient_user, "username", "") or "-"

    @admin.display(description="상태", ordering="status")
    def status_display(self, obj):
        tones = {"success": "success", "failed": "danger", "skipped": "neutral"}
        return admin_badge(obj.get_status_display(), tones.get(obj.status, "neutral"))


@admin.register(VisitLog)
class VisitLogAdmin(ModelAdmin):
    list_display = ("created_at_display", "ip_address", "user_display", "method", "status_code", "device", "path_display")
    list_filter = ("device", "status_code", "is_staff_area", "created_at")
    search_fields = ("path", "query_string", "ip_address", "user__username", "user_agent", "referer")
    ordering = ("-created_at", "-id")
    list_per_page = 50

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "reports/",
                self.admin_site.admin_view(self.reports_view),
                name="core_visitlog_reports",
            ),
            path(
                "maintenance/",
                self.admin_site.admin_view(self.maintenance_view),
                name="core_visitlog_maintenance",
            ),
        ]
        return custom_urls + urls

    def maintenance_view(self, request):
        if not request.user.is_superuser:
            raise PermissionDenied
        if request.method == "POST":
            action = str(request.POST.get("action") or "")
            if request.POST.get("confirm") != "1":
                self.message_user(
                    request,
                    _("Confirm the selected maintenance action before running it."),
                    level=messages.ERROR,
                )
            else:
                try:
                    result = run_maintenance_action(action)
                except Exception as exc:
                    self.message_user(
                        request,
                        _("Maintenance action failed: %(error)s") % {"error": force_str(exc)},
                        level=messages.ERROR,
                    )
                else:
                    self.message_user(request, _(result), level=messages.SUCCESS)
            return HttpResponseRedirect(request.path)
        if request.method != "GET":
            return HttpResponseNotAllowed(["GET", "POST"])

        context = {
            **self.admin_site.each_context(request),
            "title": _("System maintenance"),
            "subtitle": _("Review maintenance targets before clearing caches or stale generated data."),
            "opts": self.model._meta,
            "report_path": request.path,
            "snapshot": maintenance_snapshot(),
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/core/maintenance.html", context)

    def reports_view(self, request):
        start, end = admin_report_date_range(request)
        visits = VisitLog.objects.filter(local_days("created_at", start or None, end or None))

        unique_ips = visits.values("ip_address").exclude(ip_address__isnull=True).distinct().count()
        metrics = [
            {"label": _("Visits"), "value": admin_number(visits.count()), "hint": _("Recorded page requests")},
            {"label": _("Unique IPs"), "value": admin_number(unique_ips), "hint": _("Approximate visitor count")},
            {"label": _("Mobile visits"), "value": admin_number(visits.filter(device="mobile").count()), "hint": _("Mobile user agents")},
            {"label": _("Admin visits"), "value": admin_number(visits.filter(is_staff_area=True).count()), "hint": _("Admin console requests")},
        ]
        action_logs = LogEntry.objects.filter(local_days("action_time", start or None, end or None))

        context = {
            **self.admin_site.each_context(request),
            "title": _("Visit statistics"),
            "subtitle": _("Review visitor traffic, device mix, status codes, and popular paths."),
            "opts": self.model._meta,
            "report_path": request.path,
            "filters": {
                "date_from": start.isoformat() if start else "",
                "date_to": end.isoformat() if end else "",
            },
            "privacy_policy": {
                "retention_days": admin_number(getattr(settings, "ADMIN_VISIT_LOG_RETENTION_DAYS", 180)),
                "mask_ip": getattr(settings, "ADMIN_VISIT_LOG_MASK_IP", True),
                "exclude_bots": getattr(settings, "ADMIN_VISIT_LOG_EXCLUDE_BOTS", True),
                "cleanup_command": "python manage.py cleanup_admin_privacy --anonymize-existing",
            },
            "metrics": metrics,
            "daily_rows": self.visit_count_rows(visits, "created_at"),
            "device_rows": self.value_count_rows(visits, "device", _("Device")),
            "status_rows": self.value_count_rows(visits, "status_code", _("Status")),
            "path_rows": self.value_count_rows(visits, "path", _("Path"), limit=12),
            "recent_rows": [
                {
                    "time": admin_datetime(row.created_at),
                    "ip": row.ip_address or "-",
                    "user": getattr(row.user, "username", "") or "-",
                    "device": row.device,
                    "status": row.status_code,
                    "path": row.path,
                }
                for row in visits.select_related("user").order_by("-created_at", "-id")[:15]
            ],
            "admin_actions": admin_number(action_logs.count()),
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/core/visit_reports.html", context)

    def visit_count_rows(self, queryset, field):
        rows = (
            queryset.annotate(day=TruncDate(field))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("-day")[:30]
        )
        return [{"key": row["day"], "count": admin_number(row["count"])} for row in rows]

    def value_count_rows(self, queryset, field, label, limit=10):
        rows = queryset.values(field).annotate(count=Count("id")).order_by("-count", field)[:limit]
        return [
            {
                "key": row[field] if row[field] not in (None, "") else _("Unspecified"),
                "count": admin_number(row["count"]),
                "label": label,
            }
            for row in rows
        ]

    @admin.display(description=_("Created at"), ordering="created_at")
    def created_at_display(self, obj):
        return admin_datetime(obj.created_at)

    @admin.display(description=_("User"))
    def user_display(self, obj):
        return getattr(obj.user, "username", "") or "-"

    @admin.display(description=_("Path"), ordering="path")
    def path_display(self, obj):
        return compact_identifier(obj.path, 48, 16)


@admin.register(SearchKeyword)
class SearchKeywordAdmin(ModelAdmin):
    list_display = ("keyword", "source", "count", "last_user_display", "last_ip_address", "last_searched_at_display")
    list_filter = ("source", "last_searched_at")
    search_fields = ("keyword", "last_ip_address", "last_user__username")
    ordering = ("-count", "keyword")
    list_per_page = 50

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "reports/",
                self.admin_site.admin_view(self.reports_view),
                name="core_searchkeyword_reports",
            ),
        ]
        return custom_urls + urls

    def reports_view(self, request):
        start, end = admin_report_date_range(request)
        keywords = SearchKeyword.objects.filter(local_days("last_searched_at", start or None, end or None))

        metrics = [
            {"label": _("Keywords"), "value": admin_number(keywords.count()), "hint": _("Unique search terms")},
            {"label": _("Searches"), "value": admin_number(keywords.aggregate(total=Sum("count"))["total"] or 0), "hint": _("Accumulated search count")},
            {"label": _("Shop searches"), "value": admin_number(keywords.filter(source="shop").aggregate(total=Sum("count"))["total"] or 0), "hint": _("Shop search source")},
            {"label": _("API searches"), "value": admin_number(keywords.filter(source="api").aggregate(total=Sum("count"))["total"] or 0), "hint": _("API search source")},
        ]
        context = {
            **self.admin_site.each_context(request),
            "title": _("Search keyword statistics"),
            "subtitle": _("Review popular search terms by source and recency."),
            "opts": self.model._meta,
            "report_path": request.path,
            "filters": {
                "date_from": start.isoformat() if start else "",
                "date_to": end.isoformat() if end else "",
            },
            "metrics": metrics,
            "source_rows": self.value_count_rows(keywords, "source", _("Source")),
            "keyword_rows": [
                {
                    "keyword": row.keyword,
                    "source": row.source,
                    "count": admin_number(row.count),
                    "last_user": getattr(row.last_user, "username", "") or "-",
                    "last_ip": row.last_ip_address or "-",
                    "last_time": admin_datetime(row.last_searched_at),
                }
                for row in keywords.select_related("last_user").order_by("-count", "keyword")[:50]
            ],
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/core/search_keyword_reports.html", context)

    def value_count_rows(self, queryset, field, label, limit=10):
        rows = queryset.values(field).annotate(total=Count("id")).order_by("-total", field)[:limit]
        return [
            {
                "key": row[field] if row[field] not in (None, "") else _("Unspecified"),
                "count": admin_number(row["total"]),
                "label": label,
            }
            for row in rows
        ]

    @admin.display(description=_("Last user"))
    def last_user_display(self, obj):
        return getattr(obj.last_user, "username", "") or "-"

    @admin.display(description=_("Last searched at"), ordering="last_searched_at")
    def last_searched_at_display(self, obj):
        return admin_datetime(obj.last_searched_at)
