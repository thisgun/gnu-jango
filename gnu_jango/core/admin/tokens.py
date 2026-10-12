from gnu_jango.core.admin._common import *  # noqa: F401,F403
from django.utils.translation import gettext_lazy as _


class TokenReadOnlyAdminMixin:
    actions = None
    list_fullwidth = True

    def get_readonly_fields(self, request, obj=None):
        model_fields = tuple(field.name for field in self.model._meta.fields)
        configured_fields = tuple(getattr(self, "readonly_fields", ()))
        return tuple(dict.fromkeys(configured_fields + model_fields))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        if request.method not in ("GET", "HEAD"):
            return False
        return super().has_change_permission(request, obj)


class OutstandingTokenAdmin(TokenReadOnlyAdminMixin, ModelAdmin):
    list_display = (
        "token_id_display",
        "user_display",
        "created_at_display",
        "expires_at_display",
        "token_state",
    )
    search_fields = ("user__id", "user__username", "user__email", "jti")
    list_filter = (TokenCreatedDateFilter, TokenExpiresDateFilter)
    readonly_fields = (
        "token_snapshot",
        "record_id_display",
        "user_display",
        "token_id_full",
        "raw_token_preview",
        "created_at_display",
        "expires_at_display",
    )
    fieldsets = (
        (
            _("Token snapshot"),
            {
                "classes": ("tab",),
                "fields": ("token_snapshot",),
            },
        ),
        (
            _("Token identity"),
            {
                "classes": ("tab",),
                "fields": (
                    ("record_id_display", "user_display"),
                    "token_id_full",
                    "raw_token_preview",
                    ("created_at_display", "expires_at_display"),
                ),
            },
        ),
    )
    ordering = ("-created_at", "-id")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user")

    @admin.display(description=_("Token ID"), ordering="jti")
    def token_id_display(self, obj):
        return format_html("<code>{}</code>", compact_identifier(obj.jti))

    @admin.display(description=_("Record ID"))
    def record_id_display(self, obj):
        return obj.id

    @admin.display(description=_("Full token ID"))
    def token_id_full(self, obj):
        return format_html("<code>{}</code>", obj.jti or "-")

    @admin.display(description=_("Raw token"))
    def raw_token_preview(self, obj):
        return format_html("<code>{}</code>", compact_identifier(obj.token, 32, 24))

    @admin.display(description=_("Member"), ordering="user")
    def user_display(self, obj):
        return token_user_label(obj.user)

    @admin.display(description=_("Created at"), ordering="created_at")
    def created_at_display(self, obj):
        return admin_datetime(obj.created_at)

    @admin.display(description=_("Expires at"), ordering="expires_at")
    def expires_at_display(self, obj):
        return admin_datetime(obj.expires_at)

    @admin.display(description=_("Token state"))
    def token_state(self, obj):
        if obj.expires_at and obj.expires_at <= timezone.now():
            return admin_badge(_("Expired"), "danger")
        if not obj.user_id:
            return admin_badge(_("No user"), "warning")
        return admin_badge(_("Valid"), "success")

    @admin.display(description=_("Token snapshot"))
    def token_snapshot(self, obj):
        if not obj:
            return "-"
        expired = obj.expires_at and obj.expires_at <= timezone.now()
        state = _("Expired token") if expired else _("Valid token")
        tone = "danger" if expired else "success"
        user_email = getattr(obj.user, "email", "") or "-"
        return admin_snapshot_panel(
            _("Token snapshot"),
            state,
            tone,
            _("Review issued member, token key, issue time, and expiration together."),
            (
                (_("Token ID"), compact_identifier(obj.jti, 16, 10), obj.id),
                (_("Member"), str(obj.user or "-"), user_email),
                (_("Created at"), admin_datetime(obj.created_at), _("Issue time")),
                (_("Expires at"), admin_datetime(obj.expires_at), _("Expiration time")),
            ),
        )


class BlacklistedTokenAdmin(TokenReadOnlyAdminMixin, ModelAdmin):
    list_display = (
        "token_id_display",
        "user_display",
        "created_at_display",
        "expires_at_display",
        "blacklisted_at_display",
    )
    search_fields = ("token__user__id", "token__user__username", "token__user__email", "token__jti")
    list_filter = (BlacklistedDateFilter, BlacklistCreatedDateFilter, BlacklistExpiresDateFilter)
    readonly_fields = (
        "blacklist_snapshot",
        "record_id_display",
        "linked_token_display",
        "token_id_full",
        "user_display",
        "created_at_display",
        "expires_at_display",
        "blacklisted_at_display",
    )
    fieldsets = (
        (
            _("Blacklist snapshot"),
            {
                "classes": ("tab",),
                "fields": ("blacklist_snapshot",),
            },
        ),
        (
            _("Token identity"),
            {
                "classes": ("tab",),
                "fields": (
                    ("record_id_display", "linked_token_display"),
                    ("token_id_full", "user_display"),
                    ("created_at_display", "expires_at_display"),
                    "blacklisted_at_display",
                ),
            },
        ),
    )
    ordering = ("-blacklisted_at", "-id")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("token__user")

    @admin.display(description=_("Token ID"), ordering="token__jti")
    def token_id_display(self, obj):
        return format_html("<code>{}</code>", compact_identifier(obj.token.jti))

    @admin.display(description=_("Record ID"))
    def record_id_display(self, obj):
        return obj.id

    @admin.display(description=_("Token record"))
    def linked_token_display(self, obj):
        return obj.token_id

    @admin.display(description=_("Full token ID"))
    def token_id_full(self, obj):
        return format_html("<code>{}</code>", obj.token.jti or "-")

    @admin.display(description=_("Member"), ordering="token__user")
    def user_display(self, obj):
        return token_user_label(obj.token.user)

    @admin.display(description=_("Created at"), ordering="token__created_at")
    def created_at_display(self, obj):
        return admin_datetime(obj.token.created_at)

    @admin.display(description=_("Expires at"), ordering="token__expires_at")
    def expires_at_display(self, obj):
        return admin_datetime(obj.token.expires_at)

    @admin.display(description=_("Blacklisted at"), ordering="blacklisted_at")
    def blacklisted_at_display(self, obj):
        return admin_badge(admin_datetime(obj.blacklisted_at), "danger")

    @admin.display(description=_("Blacklist snapshot"))
    def blacklist_snapshot(self, obj):
        if not obj:
            return "-"
        user_email = getattr(obj.token.user, "email", "") or "-"
        return admin_snapshot_panel(
            _("Blacklist snapshot"),
            _("Blocked token"),
            "danger",
            _("Review blocked token, issued member, issue time, and expiration together."),
            (
                (_("Token ID"), compact_identifier(obj.token.jti, 16, 10), obj.token_id),
                (_("Member"), str(obj.token.user or "-"), user_email),
                (_("Created at"), admin_datetime(obj.token.created_at), _("Issue time")),
                (_("Blacklisted at"), admin_datetime(obj.blacklisted_at), _("Blocked time")),
            ),
        )


# Make sure the third-party admin has registered its default token admins
# before we override them. Import order under autodiscover is otherwise not
# guaranteed; the module is import-cached, so when autodiscover reaches it later
# it won't re-register and raise AlreadyRegistered.
import rest_framework_simplejwt.token_blacklist.admin  # noqa: E402,F401

for token_model in (OutstandingToken, BlacklistedToken):
    try:
        admin.site.unregister(token_model)
    except NotRegistered:
        pass

admin.site.register(OutstandingToken, OutstandingTokenAdmin)
admin.site.register(BlacklistedToken, BlacklistedTokenAdmin)


@admin.register(LogEntry)
class LogEntryAdmin(ModelAdmin):
    list_display = ("action_time_display", "user_display", "action_badge", "content_type", "object_repr_display")
    list_filter = ("action_flag", "content_type", "action_time")
    search_fields = ("user__username", "object_repr", "change_message")
    ordering = ("-action_time", "-pk")
    list_per_page = 50
    readonly_fields = (
        "action_time",
        "user",
        "content_type",
        "object_id",
        "object_repr",
        "action_flag",
        "change_message",
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description=_("Action time"), ordering="action_time")
    def action_time_display(self, obj):
        return admin_datetime(obj.action_time)

    @admin.display(description=_("User"), ordering="user__username")
    def user_display(self, obj):
        return getattr(obj.user, "username", "") or "-"

    @admin.display(description=_("Action"), ordering="action_flag")
    def action_badge(self, obj):
        labels = {
            ADDITION: (_("Added"), "success"),
            CHANGE: (_("Changed"), "info"),
            DELETION: (_("Deleted"), "danger"),
        }
        label, tone = labels.get(obj.action_flag, (_("Unknown"), "neutral"))
        return admin_badge(label, tone)

    @admin.display(description=_("Object"), ordering="object_repr")
    def object_repr_display(self, obj):
        return compact_identifier(obj.object_repr, 48, 16)

# Register your models here.
# admin.site.register(Config, ConstanceAdmin)
# admin.site.register(Config, TestConfigAdmin)

# Add extra fields for pages to the Displayable fields.
# We only add the menu field if PAGE_MENU_TEMPLATES has values.


# page_fieldsets = deepcopy(DisplayableAdmin.fieldsets)

# class Site_menu_admin(ContentTypedAdmin, DisplayableAdmin):

#     fieldsets = page_fieldsets
#     change_list_template = "admin/pages/page/change_list.html"

# # 사이트메뉴 등록
# admin.site.register(Site_menu, Site_menu_admin)

# admin.site.register(Site_menu)
