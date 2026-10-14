import json

from gnu_jango.shop.admin._common import *  # noqa: F401,F403
from django import forms
from unfold.forms import ActionForm
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.utils.html import format_html_join, strip_tags
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from django.db.models import CharField, OuterRef, Subquery, Value
from django.db.models.functions import Cast, Concat

from gnu_jango.api.community_common import GENERAL_QA_PRODUCT_ID, QA_META_CONFIG_PREFIX
from gnu_jango.config.models import Config
from gnu_jango.shop.models import GeneralInquiry
from gnu_jango.config import config as config_cache
from gnu_jango.shop.settings_sync import sync_shop_phone_from_policy


class ShopStockNotificationActionForm(ActionForm):
    confirm_send = forms.BooleanField(
        required=False,
        label=_("I reviewed the recipients and want to send these SMS messages now."),
    )


class ShopQAAnswerFilter(admin.SimpleListFilter):
    title = _("Answer status")
    parameter_name = "answer_status"

    def lookups(self, request, model_admin):
        return (
            ("pending", _("Needs answer")),
            ("answered", _("Answered")),
        )

    def queryset(self, request, queryset):
        if self.value() == "pending":
            return queryset.filter(iq_answer="")
        if self.value() == "answered":
            return queryset.exclude(iq_answer="")
        return queryset


class ShopReviewVisibilityFilter(admin.SimpleListFilter):
    title = _("Storefront visibility")
    parameter_name = "visibility"

    def lookups(self, request, model_admin):
        return (
            ("published", _("Published")),
            ("hidden", _("Hidden")),
        )

    def queryset(self, request, queryset):
        if self.value() == "published":
            return queryset.filter(is_confirm="1")
        if self.value() == "hidden":
            return queryset.exclude(is_confirm="1")
        return queryset


class ShopQAAdminForm(forms.ModelForm):
    iq_answer = forms.CharField(
        label=_("Staff answer"),
        required=False,
        widget=forms.Textarea(attrs={"rows": 8}),
    )

    class Meta:
        model = ShopQA
        fields = "__all__"


class ShopReviewAdminForm(forms.ModelForm):
    is_confirm = forms.ChoiceField(
        label=_("Storefront visibility"),
        choices=(("1", _("Published")), ("0", _("Hidden")), ("", _("Hidden (legacy)"))),
        required=False,
    )

    class Meta:
        model = ShopReview
        fields = "__all__"


@admin.register(ShopWishlist)
class ShopWishlistAdmin(ModelAdmin):
    list_display = ("id", "user", "session_key", "it_id", "wi_time")
    search_fields = ("it_id", "session_key", "user__username")


@admin.register(ShopStockNotification)
class ShopStockNotificationAdmin(ModelAdmin):
    action_form = ShopStockNotificationActionForm
    actions = ("send_restock_sms",)
    list_display = (
        "id",
        "product",
        "it_id",
        "masked_phone",
        "ss_send",
        "ss_datetime",
        "ss_send_time",
    )
    list_display_links = ("id",)
    list_filter = ("ss_send", "source", "ss_datetime")
    search_fields = ("it_id", "product__it_name", "ss_hp")
    list_select_related = ("product",)
    ordering = ("ss_send", "-ss_datetime", "-pk")
    list_per_page = 50
    readonly_fields = (
        "id",
        "product",
        "it_id",
        "masked_phone",
        "ss_send",
        "ss_send_time",
        "ss_datetime",
        "ss_ip",
        "legacy_ss_id",
        "source",
    )
    fields = readonly_fields

    @admin.display(description=_("Phone"))
    def masked_phone(self, obj):
        digits = "".join(character for character in str(obj.ss_hp or "") if character.isdigit())
        return f"••••{digits[-4:]}" if len(digits) >= 4 else "••••"

    def has_add_permission(self, request):
        return False

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("send_restock_sms", None)
        return actions

    @admin.action(description=_("Send restock SMS to selected subscribers"), permissions=["change"])
    def send_restock_sms(self, request, queryset):
        if not request.user.is_superuser:
            self.message_user(request, _("Only superusers can send SMS messages."), level=messages.ERROR)
            return
        if request.POST.get("confirm_send") != "on":
            self.message_user(
                request,
                _("Review the selected subscribers and confirm SMS sending in the action form."),
                level=messages.ERROR,
            )
            return

        selected_ids = list(queryset.values_list("pk", flat=True).distinct())
        if not selected_ids:
            self.message_user(request, _("Select at least one subscriber."), level=messages.WARNING)
            return
        if len(selected_ids) > 25:
            self.message_user(request, _("Send at most 25 messages per operation."), level=messages.ERROR)
            return

        from gnu_jango.shop.sms.icode import ICodeConfigurationError, send_sms

        counts = {"accepted": 0, "rejected": 0, "unknown": 0, "skipped": 0}
        shop_policy = ShopShippingPolicy.objects.filter(pk=1).first()
        sender_name = str(shop_policy.de_admin_company_name if shop_policy else "").strip()
        callback = str(shop_policy.de_admin_company_tel if shop_policy else "")
        if not sender_name or not callback:
            self.message_user(
                request,
                _("Set the shop name and callback number in YoungCart shop settings before sending."),
                level=messages.ERROR,
            )
            return

        for notification_id in selected_ids:
            with transaction.atomic():
                notification = (
                    ShopStockNotification.objects.select_for_update()
                    .select_related("product")
                    .filter(pk=notification_id)
                    .first()
                )
                if not notification or notification.ss_send:
                    counts["skipped"] += 1
                    continue
                previous = notification.send_logs.order_by("-created_at", "-pk").first()
                if previous and previous.status in {"sending", "unknown"}:
                    counts["skipped"] += 1
                    continue
                product = notification.product
                if (
                    not product
                    or str(product.it_soldout or "0") == "1"
                    or int(product.it_stock_qty or 0) <= 0
                ):
                    counts["skipped"] += 1
                    continue
                message_text = f"[{sender_name}] {product.it_name} 상품이 재입고되었습니다."
                digits = "".join(character for character in str(notification.ss_hp or "") if character.isdigit())
                send_log = ShopStockNotificationSendLog.objects.create(
                    notification=notification,
                    product_it_id=notification.it_id,
                    recipient_last4=digits[-4:],
                    message=message_text,
                    requested_by=request.user,
                )

            try:
                result = send_sms(notification.ss_hp, callback, message_text)
            except ICodeConfigurationError as exc:
                result = None
                final_status = "rejected"
                error_text = str(exc)
                provider_code = "configuration"
            except Exception as exc:
                result = None
                final_status = "unknown"
                error_text = type(exc).__name__
                provider_code = "unexpected"
            else:
                final_status = result.status
                error_text = result.error_text
                provider_code = result.provider_code

            with transaction.atomic():
                send_log.status = final_status
                send_log.error_text = error_text[:2000]
                send_log.provider_code = provider_code[:40]
                send_log.completed_at = timezone.now()
                send_log.save(update_fields=("status", "error_text", "provider_code", "completed_at"))
                if final_status == "accepted":
                    ShopStockNotification.objects.filter(pk=notification_id, ss_send=False).update(
                        ss_send=True,
                        ss_send_time=timezone.now(),
                    )
            counts[final_status] = counts.get(final_status, 0) + 1

        self.message_user(
            request,
            _("SMS results: %(accepted)s accepted, %(rejected)s rejected, %(unknown)s unknown, %(skipped)s skipped.")
            % counts,
            level=messages.SUCCESS if counts["accepted"] and not (counts["rejected"] or counts["unknown"]) else messages.WARNING,
        )


@admin.register(ShopStockNotificationSendLog)
class ShopStockNotificationSendLogAdmin(ModelAdmin):
    list_display = (
        "id",
        "product_it_id",
        "recipient_last4",
        "status",
        "provider_code",
        "requested_by",
        "created_at",
        "completed_at",
    )
    list_filter = ("status", "provider", "created_at")
    search_fields = ("product_it_id", "recipient_last4", "provider_code", "error_text")
    ordering = ("-created_at", "-pk")
    list_per_page = 50
    readonly_fields = tuple(field.name for field in ShopStockNotificationSendLog._meta.fields)
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ShopAddress)
class ShopAddressAdmin(ModelAdmin):
    list_display = ("id", "user", "ad_subject", "ad_name", "ad_default", "created_at")
    search_fields = ("user__username", "ad_subject", "ad_name", "ad_hp")



@admin.register(ShopReview)
class ShopReviewAdmin(ModelAdmin):
    form = ShopReviewAdminForm
    list_display = (
        "id",
        "product",
        "mb_id",
        "is_score",
        "is_subject",
        "visibility_status",
        "review_preview",
        "is_time",
    )
    list_display_links = ("id", "is_subject")
    search_fields = ("product__it_name", "mb_id", "is_subject", "is_content")
    list_filter = (ShopReviewVisibilityFilter, "is_score", "is_time")
    list_select_related = ("product", "user")
    date_hierarchy = "is_time"
    list_per_page = 50
    readonly_fields = ("product", "user", "mb_id", "mb_nick", "is_name", "is_score", "is_subject", "is_content", "is_time")
    fields = (*readonly_fields, "is_confirm")

    def has_add_permission(self, request):
        return False

    @admin.display(description=_("Visibility"), ordering="is_confirm")
    def visibility_status(self, obj):
        if str(obj.is_confirm or "").strip() == "1":
            return badge(_("Published"), "success")
        return badge(_("Hidden"), "neutral")

    @admin.display(description=_("Review content"))
    def review_preview(self, obj):
        return compact_text(strip_tags(obj.is_content or ""), limit=180)


@admin.register(ShopQA)
class ShopQAAdmin(ModelAdmin):
    form = ShopQAAdminForm
    list_display = (
        "id",
        "product",
        "mb_id",
        "iq_subject",
        "answer_status",
        "question_preview",
        "privacy_status",
        "iq_time",
    )
    list_display_links = ("id", "iq_subject")
    search_fields = ("product__it_name", "mb_id", "iq_subject", "iq_question", "iq_answer")
    list_filter = (ShopQAAnswerFilter, "iq_secret", "iq_time")
    list_select_related = ("product", "user")
    date_hierarchy = "iq_time"
    list_per_page = 50
    readonly_fields = (
        "product",
        "user",
        "mb_id",
        "mb_nick",
        "iq_name",
        "iq_subject",
        "iq_question",
        "iq_time",
        "iq_email",
        "iq_hp",
    )
    fieldsets = (
        (
            _("Customer question"),
            {
                "fields": (
                    ("product", "user"),
                    ("mb_id", "mb_nick", "iq_name"),
                    "iq_subject",
                    "iq_question",
                    ("iq_secret", "iq_time"),
                )
            },
        ),
        (_("Staff response"), {"fields": ("iq_answer",)}),
        (_("Private contact details"), {"classes": ("collapse",), "fields": (("iq_email", "iq_hp"),)}),
    )

    def has_add_permission(self, request):
        return False

    def get_queryset(self, request):
        # 1:1 inquiries have their own admin (GeneralInquiryAdmin below).
        return super().get_queryset(request).exclude(product_id=GENERAL_QA_PRODUCT_ID)

    @admin.display(description=_("Answer"))
    def answer_status(self, obj):
        if str(obj.iq_answer or "").strip():
            return badge(_("Answered"), "success")
        return badge(_("Needs answer"), "warning")

    @admin.display(description=_("Question"))
    def question_preview(self, obj):
        return compact_text(strip_tags(obj.iq_question or ""), limit=160)

    @admin.display(description=_("Privacy"), ordering="iq_secret")
    def privacy_status(self, obj):
        if bool(obj.iq_secret):
            return badge(_("Private"), "warning")
        return badge(_("Public"), "neutral")


class GeneralInquiryAdminForm(forms.ModelForm):
    answer_subject = forms.CharField(
        label="답변 제목",
        required=False,
        max_length=255,
        help_text="비워 두면 \"RE: 문의 제목\"으로 저장됩니다.",
    )
    iq_answer = forms.CharField(label="답변 내용", required=False, widget=forms.Textarea(attrs={"rows": 10}))

    class Meta:
        model = GeneralInquiry
        fields = ("iq_answer",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            from gnu_jango.api.community_qas import _qa_load_meta

            self.fields["answer_subject"].initial = _qa_load_meta(self.instance.pk).get("answer_subject", "")


@admin.register(GeneralInquiry)
class GeneralInquiryAdmin(ModelAdmin):
    """1:1 inquiries (bbs/qalist.php, adm/qa*): read the question and its attachments, then answer."""

    form = GeneralInquiryAdminForm
    list_display = ("id", "iq_subject", "inquirer", "answer_status", "attachment_count", "iq_time")
    list_display_links = ("id", "iq_subject")
    search_fields = ("iq_subject", "iq_question", "iq_answer", "mb_id", "mb_nick", "iq_name")
    list_filter = (ShopQAAnswerFilter, "iq_time")
    list_select_related = ("user",)
    date_hierarchy = "iq_time"
    list_per_page = 50
    readonly_fields = ("inquirer", "iq_subject", "iq_question", "attachments", "iq_email", "iq_hp", "iq_time")
    fieldsets = (
        ("문의", {"fields": ("inquirer", "iq_subject", "iq_question", "attachments", "iq_time")}),
        ("답변", {"fields": ("answer_subject", "iq_answer")}),
        ("연락처", {"classes": ("collapse",), "fields": (("iq_email", "iq_hp"),)}),
    )

    def get_queryset(self, request):
        # The attachment metadata (Config row qa_meta_<id>) comes along in one query, not one per row.
        meta_name = Concat(Value(QA_META_CONFIG_PREFIX), Cast(OuterRef("pk"), CharField()))
        meta = Config.objects.filter(name=meta_name).values("value")[:1]
        return (
            super()
            .get_queryset(request)
            .filter(product_id=GENERAL_QA_PRODUCT_ID)
            .annotate(meta_raw=Subquery(meta, output_field=CharField()))
        )

    def has_add_permission(self, request):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not str(obj.iq_answer or "").strip():
            return
        from gnu_jango.api.community_qas import _qa_load_meta, _qa_save_meta

        # qa_answer_view: the answer subject defaults to "RE: <question subject>".
        meta = _qa_load_meta(obj.pk)
        meta["answer_subject"] = form.cleaned_data.get("answer_subject", "").strip() or f"RE: {obj.iq_subject or ''}"
        _qa_save_meta(obj.pk, meta)

    def _files(self, obj):
        from gnu_jango.api.community_qas import _qa_file_slot, _qa_load_meta, _qa_normalize_meta

        cached = getattr(obj, "_attachment_files", None)
        if cached is not None:
            return cached
        raw = getattr(obj, "meta_raw", None)
        if raw is None:
            meta = _qa_load_meta(obj.pk)
        else:
            try:
                meta = _qa_normalize_meta(json.loads(raw))
            except (TypeError, ValueError):
                meta = _qa_normalize_meta({})
        obj._attachment_files = [slot for slot in (_qa_file_slot(meta, 1), _qa_file_slot(meta, 2)) if slot["url"]]
        return obj._attachment_files

    @admin.display(description="문의자")
    def inquirer(self, obj):
        return compact_text(obj.iq_name or obj.mb_nick, f"({obj.mb_id})" if obj.mb_id else "")

    @admin.display(description=_("Answer"))
    def answer_status(self, obj):
        if str(obj.iq_answer or "").strip():
            return badge(_("Answered"), "success")
        return badge(_("Needs answer"), "warning")

    @admin.display(description="첨부")
    def attachment_count(self, obj):
        return len(self._files(obj))

    @admin.display(description="첨부파일")
    def attachments(self, obj):
        files = self._files(obj)
        if not files:
            return "-"
        return format_html_join(
            mark_safe("<br>"),
            '<a href="{}" target="_blank" rel="noopener">{}</a>',
            ((item["url"], item["name"] or item["path"]) for item in files),
        )


@admin.register(ShopShippingPolicy)
class ShopShippingPolicyAdmin(ModelAdmin):
    list_display = ("id", "de_delivery_company", "de_send_cost_case", "de_send_cost_limit", "de_send_cost_list")
    fields = (
        ("de_admin_company_name", "de_admin_company_tel"),
        "de_delivery_company",
        "de_send_cost_case",
        "de_send_cost_limit",
        "de_send_cost_list",
        "de_baesong_content",
        "de_change_content",
        ("de_item_use_write", "de_item_use_use"),
        "de_tax_flag_use",
        ("de_settle_min_point", "de_settle_max_point", "de_settle_point_unit"),
    )

    def has_add_permission(self, request):
        return not ShopShippingPolicy.objects.exists() and super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.pk = 1
        super().save_model(request, obj, form, change)
        sync_shop_phone_from_policy(obj.de_admin_company_tel)
        config_cache.clear()


@admin.register(ShopShippingCost)
class ShopShippingCostAdmin(ModelAdmin):
    list_display = ("sc_id", "sc_name", "sc_zip1", "sc_zip2", "sc_price")
    search_fields = ("sc_name", "sc_zip1", "sc_zip2")
    list_display_links = ("sc_id", "sc_name")
