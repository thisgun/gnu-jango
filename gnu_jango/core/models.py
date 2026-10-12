from django.conf import settings
from django.core.cache import cache
from django.db import models
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

# from django.db.models import CharField, Model
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.urls import reverse

from gnu_jango import defaults

# Create your models here.

# 사이트 팝업
class New_win(models.Model):
    DIVISIONS = (("comm", "커뮤니티"),)
    DEVICES = (
        ("both", "PC와 모바일"),
        ("pc", "PC"),
        ("mobile", "모바일"),
    )

    nw_division = models.CharField(
        _("커뮤니티 구분"),
        null=True,
        blank=True,
        default="comm",
        max_length=10,
        choices=DIVISIONS,
    )
    nw_device = models.CharField(
        _("접속기기"),
        null=True,
        blank=True,
        default="both",
        max_length=10,
        choices=DEVICES,
        help_text=_("팝업레이어가 표시될 접속기기를 설정합니다."),
    )
    nw_disable_hours = models.IntegerField(
        _("시간"),
        default=0,
        null=True,
        blank=True,
        help_text=_("고객이 다시 보지 않음을 선택할 시 몇 시간동안 팝업레이어를 보여주지 않을지 설정합니다."),
    )
    nw_begin_time = models.DateTimeField(_("시작일시"), null=True, blank=True)
    nw_end_time = models.DateTimeField(_("종료일시"), null=True, blank=True)
    nw_left = models.IntegerField(_("좌측 위치"), default=0, null=True, blank=True)
    nw_top = models.IntegerField(_("상단 위치"), default=0, null=True, blank=True)
    nw_height = models.IntegerField(_("높이"), default=0, null=True, blank=True)
    nw_width = models.IntegerField(_("넓이"), default=0, null=True, blank=True)
    nw_subject = models.TextField(_("제목"), default="", null=True, blank=True)
    nw_content = models.TextField(_("내용"), default="", null=True, blank=True)
    nw_content_html = models.PositiveSmallIntegerField(
        _("html 사용"), default=0, null=True, blank=True
    )

    def get_admin_url(self):
        return reverse(
            "admin:%s_%s_change" % (self._meta.app_label, self._meta.model_name),
            args=(self.id,),
        )

    class Meta:
        verbose_name = _("사이트팝업")
        verbose_name_plural = _("사이트팝업")


# 사이트 메뉴
class Site_menu(models.Model):
    me_code = models.CharField(_("메뉴코드"), null=True, blank=True, default="", max_length=255)
    me_name = models.CharField(_("메뉴명"), null=True, blank=True, default="", max_length=255)
    me_link = models.CharField(_("링크"), null=True, blank=True, default="", max_length=255)
    me_type = models.CharField(_("대상구분"), null=True, blank=True, default="", max_length=255)
    me_type_pk = models.IntegerField(_("대상참조pk"), default=0, null=True, blank=True)
    me_target = models.CharField(_("새창"), null=True, blank=True, default="", max_length=255)
    me_order = models.IntegerField(_("출력순서"), default=0, null=True, blank=True)
    me_use = models.PositiveSmallIntegerField(_("메뉴사용"), default=0, null=True, blank=True)
    me_mobile_use = models.PositiveSmallIntegerField(
        _("모바일 메뉴사용"), default=0, null=True, blank=True
    )

    def get_admin_url(self):
        return reverse(
            "admin:%s_%s_change" % (self._meta.app_label, self._meta.model_name),
            args=(self.id,),
        )

    class Meta:
        verbose_name = _("사이트메뉴")
        verbose_name_plural = _("사이트메뉴")

class Editor_attachments(models.Model):
    name = models.CharField(
        max_length=255, null=True, blank=True, help_text="Defaults to filename, if left blank"
    )
    file = models.FileField(null=True, blank=True, verbose_name=_("파일"))
    filepath = models.TextField(null=True, blank=True, help_text="")
    # file = models.FileField(
    #     upload_to=get_attachment_upload_to(),
    # )
    uploaded = models.DateTimeField(auto_now_add=True)
    # wdatetime = models.DateTimeField(_("등록일"))

    def __str__(self):
        return self.name

    # def save(self, *args, **kwargs):
    #     if not self.name:
    #         self.name = self.file.name
    #     super().save(*args, **kwargs)

    class Meta:
        db_table = defaults.DB_PREFIX + "editor_attachments"
        verbose_name = _("Editor attachment")
        verbose_name_plural = _("Editor attachments")


class ContentPage(models.Model):
    co_id = models.CharField(max_length=64, primary_key=True)
    co_subject = models.CharField(max_length=255, default="", blank=True)
    co_content = models.TextField(default="", blank=True)
    co_mobile_content = models.TextField(default="", blank=True)
    co_html = models.PositiveSmallIntegerField(default=1)
    co_skin = models.CharField(max_length=64, default="basic", blank=True)
    co_mobile_skin = models.CharField(max_length=64, default="basic", blank=True)
    co_seo_title = models.CharField(max_length=255, default="", blank=True, db_index=True)
    co_include_head = models.CharField(max_length=255, default="", blank=True)
    co_include_tail = models.CharField(max_length=255, default="", blank=True)
    co_order = models.IntegerField(default=0)
    co_use = models.PositiveSmallIntegerField(default=1)
    co_created_at = models.DateTimeField(default=timezone.now)
    co_updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.co_subject or self.co_id

    class Meta:
        db_table = defaults.DB_PREFIX + "content"
        verbose_name = _("Content page")
        verbose_name_plural = _("Content pages")
        ordering = ["co_order", "co_id"]


class FAQMaster(models.Model):
    fm_id = models.BigAutoField(primary_key=True)
    fm_subject = models.CharField(max_length=255, default="", blank=True)
    fm_head_html = models.TextField(default="", blank=True)
    fm_tail_html = models.TextField(default="", blank=True)
    fm_mobile_head_html = models.TextField(default="", blank=True)
    fm_mobile_tail_html = models.TextField(default="", blank=True)
    fm_order = models.IntegerField(default=0)
    fm_use = models.PositiveSmallIntegerField(default=1)

    def __str__(self):
        return self.fm_subject or str(self.fm_id)

    class Meta:
        db_table = defaults.DB_PREFIX + "faq_master"
        verbose_name = _("FAQ master")
        verbose_name_plural = _("FAQ masters")
        ordering = ["fm_order", "fm_id"]


class FAQItem(models.Model):
    fa_id = models.BigAutoField(primary_key=True)
    master = models.ForeignKey(FAQMaster, on_delete=models.CASCADE, related_name="items")
    fa_subject = models.CharField(max_length=255, default="", blank=True)
    fa_content = models.TextField(default="", blank=True)
    fa_order = models.IntegerField(default=0)
    fa_use = models.PositiveSmallIntegerField(default=1)
    fa_created_at = models.DateTimeField(default=timezone.now)
    fa_updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.fa_subject or str(self.fa_id)

    class Meta:
        db_table = defaults.DB_PREFIX + "faq"
        verbose_name = _("FAQ item")
        verbose_name_plural = _("FAQ items")
        ordering = ["fa_order", "fa_id"]


class Poll(models.Model):
    po_id = models.BigAutoField(primary_key=True)
    po_subject = models.CharField(max_length=255, default="", blank=True)
    po_etc = models.CharField(max_length=255, default="", blank=True)
    po_level = models.PositiveSmallIntegerField(default=1)
    po_point = models.IntegerField(default=0)
    po_date = models.DateField(default=timezone.localdate)
    po_use = models.PositiveSmallIntegerField(default=1)
    po_begin_date = models.DateField(null=True, blank=True)
    po_end_date = models.DateField(null=True, blank=True)
    po_created_at = models.DateTimeField(default=timezone.now)
    po_updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.po_subject or str(self.po_id)

    class Meta:
        db_table = defaults.DB_PREFIX + "poll"
        verbose_name = _("Poll")
        verbose_name_plural = _("Polls")
        ordering = ["-po_date", "-po_id"]


class PollChoice(models.Model):
    id = models.BigAutoField(primary_key=True)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="choices")
    num = models.PositiveSmallIntegerField(default=1)
    content = models.CharField(max_length=255, default="", blank=True)
    count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.content or "%s #%s" % (self.poll_id, self.num)

    class Meta:
        db_table = defaults.DB_PREFIX + "poll_choice"
        verbose_name = _("Poll choice")
        verbose_name_plural = _("Poll choices")
        ordering = ["poll_id", "num"]
        unique_together = (("poll", "num"),)


class PollVote(models.Model):
    id = models.BigAutoField(primary_key=True)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="votes")
    choice = models.ForeignKey(PollChoice, on_delete=models.CASCADE, related_name="votes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    session_key = models.CharField(max_length=40, default="", blank=True, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = defaults.DB_PREFIX + "poll_vote"
        verbose_name = _("Poll vote")
        verbose_name_plural = _("Poll votes")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["poll", "user"]),
            models.Index(fields=["poll", "session_key"]),
            models.Index(fields=["poll", "ip"]),
        ]


class PollComment(models.Model):
    pc_id = models.BigAutoField(primary_key=True)
    poll = models.ForeignKey(Poll, on_delete=models.CASCADE, related_name="comments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    pc_name = models.CharField(max_length=255, default="", blank=True)
    pc_idea = models.CharField(max_length=255, default="", blank=True)
    pc_datetime = models.DateTimeField(default=timezone.now)
    pc_ip = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        return self.pc_idea[:40]

    class Meta:
        db_table = defaults.DB_PREFIX + "poll_etc"
        verbose_name = _("Poll comment")
        verbose_name_plural = _("Poll comments")
        ordering = ["-pc_datetime", "-pc_id"]


class Notification(models.Model):
    nt_id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    nt_type = models.CharField(max_length=50, default="system", blank=True)
    nt_title = models.CharField(max_length=255, default="", blank=True)
    nt_body = models.TextField(default="", blank=True)
    nt_data = models.JSONField(null=True, blank=True)
    dday_id = models.CharField(max_length=64, default="", blank=True)
    nt_sent_at = models.DateTimeField(default=timezone.now)
    nt_read_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.nt_title or str(self.nt_id)

    class Meta:
        db_table = defaults.DB_PREFIX + "notification"
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        ordering = ["-nt_sent_at", "-nt_id"]


class MailCampaign(models.Model):
    RECIPIENT_GROUP_CHOICES = (
        ("test", "테스트"),
        ("active", "활성 회원"),
        ("staff", "스태프"),
        ("superuser", "최고관리자"),
        ("all", "전체 이메일 회원"),
    )
    STATUS_CHOICES = (
        ("draft", "작성중"),
        ("sending", "발송중"),
        ("sent", "발송완료"),
        ("partial", "일부실패"),
        ("failed", "실패"),
    )

    id = models.BigAutoField(primary_key=True)
    title = models.CharField("관리 제목", max_length=255, default="", blank=True)
    recipient_group = models.CharField("대상 그룹", max_length=20, choices=RECIPIENT_GROUP_CHOICES, default="active")
    subject = models.CharField("메일 제목", max_length=255)
    body = models.TextField("본문", default="", blank=True)
    from_email = models.EmailField("발신 이메일", max_length=254, default="", blank=True)
    recipient_count = models.PositiveIntegerField("대상 수", default=0)
    sent_count = models.PositiveIntegerField("성공 수", default=0)
    failed_count = models.PositiveIntegerField("실패 수", default=0)
    status = models.CharField("상태", max_length=20, choices=STATUS_CHOICES, default="draft", db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mail_campaigns",
        verbose_name="작성자",
    )
    created_at = models.DateTimeField("생성일시", default=timezone.now, db_index=True)
    sent_at = models.DateTimeField("발송일시", null=True, blank=True, db_index=True)
    note = models.TextField("운영 메모", default="", blank=True)

    def __str__(self):
        return self.title or self.subject

    class Meta:
        db_table = defaults.DB_PREFIX + "mail_campaign"
        verbose_name = "메일 캠페인"
        verbose_name_plural = "메일 캠페인"
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["recipient_group", "status"]),
            models.Index(fields=["sent_at", "status"]),
        ]


class MailSendLog(models.Model):
    STATUS_CHOICES = (
        ("success", "성공"),
        ("failed", "실패"),
        ("skipped", "건너뜀"),
    )

    id = models.BigAutoField(primary_key=True)
    campaign = models.ForeignKey(MailCampaign, on_delete=models.CASCADE, related_name="logs", verbose_name="캠페인")
    recipient_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mail_send_logs",
        verbose_name="회원",
    )
    recipient_email = models.EmailField("수신 이메일", max_length=254, db_index=True)
    status = models.CharField("상태", max_length=20, choices=STATUS_CHOICES, default="success", db_index=True)
    error_message = models.TextField("오류 메시지", default="", blank=True)
    sent_at = models.DateTimeField("처리일시", default=timezone.now, db_index=True)

    def __str__(self):
        return "%s %s" % (self.recipient_email, self.status)

    class Meta:
        db_table = defaults.DB_PREFIX + "mail_send_log"
        verbose_name = "메일 발송 로그"
        verbose_name_plural = "메일 발송 로그"
        ordering = ["-sent_at", "-id"]
        indexes = [
            models.Index(fields=["campaign", "status"]),
            models.Index(fields=["recipient_email", "sent_at"]),
        ]


class VisitLog(models.Model):
    id = models.BigAutoField(primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visit_logs",
    )
    session_key = models.CharField(max_length=80, default="", blank=True, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True, db_index=True)
    method = models.CharField(max_length=10, default="GET")
    path = models.CharField(max_length=500, db_index=True)
    query_string = models.TextField(default="", blank=True)
    referer = models.TextField(default="", blank=True)
    user_agent = models.TextField(default="", blank=True)
    device = models.CharField(max_length=20, default="desktop", db_index=True)
    status_code = models.PositiveSmallIntegerField(default=0, db_index=True)
    is_staff_area = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return "%s %s" % (self.ip_address or "-", self.path)

    class Meta:
        db_table = defaults.DB_PREFIX + "visit_log"
        verbose_name = _("Visit log")
        verbose_name_plural = _("Visit logs")
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["created_at", "path"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["ip_address", "created_at"]),
        ]


class SearchKeyword(models.Model):
    SOURCE_CHOICES = (
        ("site", _("Site")),
        ("shop", _("Shop")),
        ("api", _("API")),
        ("admin", _("Admin")),
    )

    id = models.BigAutoField(primary_key=True)
    keyword = models.CharField(max_length=255, db_index=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="site", db_index=True)
    count = models.PositiveIntegerField(default=0, db_index=True)
    last_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="search_keywords",
    )
    last_ip_address = models.GenericIPAddressField(null=True, blank=True)
    first_searched_at = models.DateTimeField(default=timezone.now)
    last_searched_at = models.DateTimeField(default=timezone.now, db_index=True)

    def __str__(self):
        return self.keyword

    class Meta:
        db_table = defaults.DB_PREFIX + "search_keyword"
        verbose_name = _("Search keyword")
        verbose_name_plural = _("Search keywords")
        ordering = ["-count", "keyword"]
        unique_together = (("source", "keyword"),)


class SearchKeywordDaily(models.Model):
    id = models.BigAutoField(primary_key=True)
    keyword = models.CharField(max_length=255, db_index=True)
    source = models.CharField(max_length=20, choices=SearchKeyword.SOURCE_CHOICES, default="site", db_index=True)
    day = models.DateField(db_index=True)
    count = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.keyword} ({self.day})"

    class Meta:
        db_table = defaults.DB_PREFIX + "search_keyword_daily"
        verbose_name = _("Daily search keyword")
        verbose_name_plural = _("Daily search keywords")
        ordering = ["-day", "-count", "keyword"]
        unique_together = (("source", "keyword", "day"),)


# Gnuboard5 rebuilds the menu on every request; the cached copy is dropped whenever a menu changes.
MENU_CACHE_VERSION_KEY = "django-gnu-menu-items-version"


@receiver([post_save, post_delete], sender=Site_menu)
def invalidate_menu_cache(**kwargs):
    try:
        cache.incr(MENU_CACHE_VERSION_KEY)
    except ValueError:
        cache.set(MENU_CACHE_VERSION_KEY, 1, None)
