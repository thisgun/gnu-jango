import csv
import uuid
from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.sites import NotRegistered
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import GroupAdmin as BaseGroupAdmin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse
from django.urls import path
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from import_export.admin import ImportExportMixin
from unfold.admin import ModelAdmin, StackedInline
from unfold.contrib.filters.admin import DropdownFilter
from unfold.forms import AdminPasswordChangeForm, UserChangeForm, UserCreationForm

from gnu_jango.api.auth_sessions import revoke_member_tokens
from gnu_jango.config.models import Config
from gnu_jango.core.audit import AdminExportAuditMixin, UnfoldHistoryAdmin
from gnu_jango.users import point_ledger

from .import_export_resources import UserResource
from .impersonation import start_impersonation
from .models import Profile, User_Memo, User_Point, User_Scrap
from gnu_jango.utils.admin_display import (
    badge,
    compact_text,
    fieldsets_without,
    format_number,
    money_html,
    snapshot_panel,
)

User = get_user_model()


def datetime_value(value):
    if not value:
        return "-"
    try:
        return timezone.localtime(value).strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return value.strftime("%Y-%m-%d %H:%M:%S")


def get_profile(obj):
    try:
        return obj.profile
    except (AttributeError, Profile.DoesNotExist):
        return None


def related_count(obj, related_name):
    manager = getattr(obj, related_name, None)
    if manager is None:
        return 0
    try:
        return manager.count()
    except Exception:
        return 0


class ProfileInline(StackedInline):
    model = Profile
    can_delete = False
    extra = 0
    verbose_name_plural = _("Profile")
    # Moved only by auth_sessions.bump_token_version; editing it by hand would revive revoked tokens.
    exclude = ("token_version",)


class RevokingAdminPasswordChangeForm(AdminPasswordChangeForm):
    """A password the admin sets signs the member out on every device, like a member's own change."""

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            revoke_member_tokens(user)
        return user


# Changes in the Django admin that end every login of the member (adm/member_form_update.php sets
# mb_intercept_date for a block; the e-mail address receives the password reset mail).
TOKEN_REVOKING_CHANGES = ("email", "password")


class ProfileAdmin(ModelAdmin):
    exclude = ("token_version",)
    list_display = ("user", "nickname", "realname", "member_level", "point_balance", "user_hp")
    list_display_links = ("user", "nickname")
    search_fields = ("user__username", "user__email", "nickname", "realname", "user_hp")
    list_filter = ("user_level",)
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    list_fullwidth = True

    @admin.display(ordering="user_level", description=_("Member level"))
    def member_level(self, obj):
        return badge(_("Level %(level)s") % {"level": format_number(obj.user_level)}, "info")

    @admin.display(ordering="user_point", description=_("Point balance"))
    def point_balance(self, obj):
        return money_html(obj.user_point, danger=obj.user_point < 0)


class PointStateFilter(DropdownFilter):
    title = _("Point state")
    parameter_name = "point_state"

    def lookups(self, request, model_admin):
        return (
            ("expiration_attention", _("Expiration attention")),
            ("expired", _("Expired")),
            ("expiring", _("Expiring soon")),
            ("available", _("Available")),
            ("negative", _("Negative point")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        now = timezone.now()
        expiration_attention = Q(po_expired__gt=0) | Q(
            po_expired=0,
            po_expire_date__isnull=False,
            po_expire_date__lte=now + timedelta(days=7),
        )
        if value == "expiration_attention":
            return queryset.filter(expiration_attention)
        if value == "expired":
            return queryset.filter(po_expired__gt=0)
        if value == "expiring":
            return queryset.filter(
                po_expired=0,
                po_expire_date__isnull=False,
                po_expire_date__lte=now + timedelta(days=7),
            )
        if value == "available":
            return queryset.filter(po_expired=0)
        if value == "negative":
            return queryset.filter(po_point__lt=0)
        return queryset


class MemoStateFilter(DropdownFilter):
    title = _("Memo state")
    parameter_name = "memo_state"

    def lookups(self, request, model_admin):
        return (
            ("unread", _("Unread")),
            ("read", _("Read")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        if value == "unread":
            return queryset.filter(me_type="recv", me_read_datetime__isnull=True)
        if value == "read":
            return queryset.filter(me_read_datetime__isnull=False)
        return queryset


class UserAdmin(AdminExportAuditMixin, ImportExportMixin, BaseUserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = RevokingAdminPasswordChangeForm
    resource_classes = [UserResource]
    export_audit_label = "members"
    change_form_template = "admin/users/user/change_form.html"
    inlines = (ProfileInline,)

    def has_import_permission(self, request):
        return request.user.is_superuser

    def has_export_permission(self, request):
        return request.user.is_superuser

    def get_urls(self):
        urls = super().get_urls()
        return [
            path(
                "<path:object_id>/impersonate/",
                self.admin_site.admin_view(start_impersonation),
                name="auth_user_impersonate",
            ),
            *urls,
        ]
    readonly_fields = tuple(getattr(BaseUserAdmin, "readonly_fields", ())) + ("user_snapshot",)
    list_display = (
        "profile_add",
        "username",
        "email",
        "member_level",
        "point_balance",
        "member_status",
        "is_staff",
        "last_login",
    )
    list_display_links = ("profile_add", "username")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups", "profile__user_level")
    search_fields = tuple(getattr(BaseUserAdmin, "search_fields", ())) + (
        "profile__nickname",
        "profile__realname",
        "profile__user_hp",
    )
    list_select_related = ("profile",)
    list_fullwidth = True
    actions = tuple(getattr(BaseUserAdmin, "actions", ()) or ()) + (
        "block_selected_members",
        "leave_selected_members",
        "export_selected_members_csv",
    )

    def _apply_to_members(self, request, queryset, apply, log_message):
        """Run ``apply`` on each selected member. Super admins, the acting admin and (for a staff
        member who is not a superuser) other staff accounts are left alone; adm/member_list_update.php
        refuses to change the super admin."""
        site_admin = (Config.objects.filter(name="cf_admin").values_list("value", flat=True).first() or "").strip()
        changed = skipped = 0
        for user in queryset:
            protected = (
                user.is_superuser
                or user.pk == request.user.pk
                or (site_admin and user.get_username() == site_admin)
                or (user.is_staff and not request.user.is_superuser)
            )
            if protected:
                skipped += 1
                continue
            apply(user)
            self.log_change(request, user, log_message)
            changed += 1
        if changed:
            self.message_user(request, f"{changed}명을 처리했습니다.", messages.SUCCESS)
        if skipped:
            self.message_user(request, f"최고 관리자·본인·관리자 계정 {skipped}개는 건너뛰었습니다.", messages.WARNING)

    @admin.action(description="선택 회원 차단", permissions=["change"])
    def block_selected_members(self, request, queryset):
        from gnu_jango.api.member_lifecycle import block_member

        self._apply_to_members(request, queryset, block_member, "회원 차단")

    @admin.action(description="선택 회원 탈퇴 처리", permissions=["change"])
    def leave_selected_members(self, request, queryset):
        from gnu_jango.api.member_lifecycle import block_member, leave_member

        # g5_leave_member stamps the leave date; a member who already left is only kept blocked.
        self._apply_to_members(request, queryset, lambda user: leave_member(user) or block_member(user), "회원 탈퇴 처리")

    def save_related(self, request, form, formsets, change):
        # After the inlines: the profile inline saves the Profile row too, so the token version is
        # bumped once that save is done.
        super().save_related(request, form, formsets, change)
        if not change:
            return
        changed = set(getattr(form, "changed_data", ()) or ())
        blocked = "is_active" in changed and not form.instance.is_active
        if blocked or changed.intersection(TOKEN_REVOKING_CHANGES):
            revoke_member_tokens(form.instance)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("export_selected_members_csv", None)
        return actions

    @admin.action(description=_("Export selected members CSV"), permissions=["view"])
    def export_selected_members_csv(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied("Only superusers may export member data.")

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="members-{timezone.localdate():%Y%m%d}.csv"'
        )
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(
            (
                "username",
                "email",
                "real_name",
                "nickname",
                "phone",
                "member_level",
                "point_balance",
                "is_active",
                "is_staff",
                "date_joined",
                "last_login",
            )
        )

        def safe_cell(value):
            if value is None:
                return ""
            text = str(value)
            first_visible = text.lstrip(" \t\r\n")[:1]
            if first_visible in {"=", "+", "-", "@"} or text[:1] in {"\t", "\r", "\n"}:
                return "'" + text
            return text

        for user in queryset.select_related("profile").order_by("pk"):
            profile = get_profile(user)
            writer.writerow(
                safe_cell(value)
                for value in (
                    user.get_username(),
                    user.email,
                    getattr(profile, "realname", ""),
                    getattr(profile, "nickname", ""),
                    getattr(profile, "user_hp", ""),
                    getattr(profile, "user_level", ""),
                    getattr(profile, "user_point", ""),
                    user.is_active,
                    user.is_staff,
                    datetime_value(user.date_joined),
                    datetime_value(user.last_login),
                )
            )
        return response

    def get_fieldsets(self, request, obj=None):
        fieldsets = fieldsets_without(tuple(super().get_fieldsets(request, obj)), "user_snapshot")
        if obj is None:
            return fieldsets
        return (
            (
                _("User snapshot"),
                {
                    "classes": ("tab",),
                    "fields": ("user_snapshot",),
                },
            ),
        ) + fieldsets

    @admin.display(ordering="profile", description=_("Nickname"))
    def profile_add(self, obj):
        profile = get_profile(obj)
        return getattr(profile, "nickname", "") or "-"

    @admin.display(ordering="profile__user_level", description=_("Member level"))
    def member_level(self, obj):
        profile = get_profile(obj)
        if not profile:
            return badge(_("No profile"), "warning")
        return badge(_("Level %(level)s") % {"level": format_number(profile.user_level)}, "info")

    @admin.display(ordering="profile__user_point", description=_("Point balance"))
    def point_balance(self, obj):
        profile = get_profile(obj)
        point = getattr(profile, "user_point", 0)
        return money_html(point, danger=point < 0)

    @admin.display(ordering="is_active", description=_("Member status"))
    def member_status(self, obj):
        if not obj.is_active:
            return badge(_("Inactive"), "danger")
        if obj.is_superuser:
            return badge(_("Superuser"), "info")
        if obj.is_staff:
            return badge(_("Staff"), "info")
        return badge(_("Active member"), "success")

    @admin.display(description=_("User snapshot"))
    def user_snapshot(self, obj):
        profile = get_profile(obj)
        if not obj.is_active:
            tone = "danger"
            state = _("Inactive")
        elif obj.is_superuser:
            tone = "info"
            state = _("Superuser")
        elif obj.is_staff:
            tone = "info"
            state = _("Staff")
        else:
            tone = "success"
            state = _("Active member")

        point = getattr(profile, "user_point", 0)
        scrap_count = related_count(obj, "user_scrap") + related_count(obj, "post_scrap")
        address = compact_text(
            getattr(profile, "user_zip", ""),
            getattr(profile, "user_addr1", ""),
            getattr(profile, "user_addr2", ""),
            getattr(profile, "user_addr_jibeon", ""),
        )
        return snapshot_panel(
            _("User snapshot"),
            state,
            tone,
            _("Review account access, profile, points, activity, and related records together."),
            (
                (_("Account"), obj.get_username(), compact_text(obj.email, obj.get_full_name())),
                (
                    _("Profile signal"),
                    getattr(profile, "nickname", "") or "-",
                    compact_text(getattr(profile, "realname", ""), getattr(profile, "user_hp", "")),
                ),
                (
                    _("Level and points"),
                    _("Level %(level)s") % {"level": format_number(getattr(profile, "user_level", 0))},
                    _("Point %(point)s") % {"point": format_number(point)},
                ),
                (
                    _("Activity"),
                    _("Joined %(date)s") % {"date": datetime_value(obj.date_joined)},
                    _("Last login %(date)s") % {"date": datetime_value(obj.last_login)},
                ),
                (
                    _("Commerce records"),
                    _("Orders %(count)s") % {"count": format_number(related_count(obj, "shop_orders"))},
                    _("Coupons %(count)s") % {"count": format_number(related_count(obj, "shop_coupons"))},
                ),
                (
                    _("Community records"),
                    _("Posts %(count)s") % {"count": format_number(related_count(obj, "user_post"))},
                    _("Comments %(count)s") % {"count": format_number(related_count(obj, "comments"))},
                ),
                (
                    _("Member records"),
                    _("Points %(count)s") % {"count": format_number(related_count(obj, "user_point"))},
                    _("Memos %(count)s / scraps %(scraps)s")
                    % {"count": format_number(related_count(obj, "user_memo")), "scraps": format_number(scrap_count)},
                ),
                (_("Contact address"), address, compact_text(getattr(profile, "user_homepage", ""), obj.email)),
            ),
        )


class UserPointGrantForm(forms.ModelForm):
    """adm/point_update.php: grant (or, negative, take) points; the ledger keeps the balance in step."""

    class Meta:
        model = User_Point
        fields = ("user", "po_point", "po_content")
        labels = {"po_point": "포인트(차감은 음수)", "po_content": "내용"}

    def clean(self):
        cleaned = super().clean()
        user, point = cleaned.get("user"), cleaned.get("po_point")
        if not point:
            raise forms.ValidationError({"po_point": "0이 아닌 포인트를 입력하세요."})
        if not point_ledger.points_enabled():
            raise forms.ValidationError("포인트 사용이 꺼져 있습니다. 환경설정에서 포인트 사용을 켠 뒤 지급하세요.")
        if user and point < 0 and point_ledger.point_balance(user) < -point:
            raise forms.ValidationError(
                {"po_point": f"현재 포인트({point_ledger.point_balance(user)}점)보다 많이 차감할 수 없습니다."}
            )
        return cleaned


class UserPointAdmin(UnfoldHistoryAdmin):
    list_display = (
        "id",
        "user_display",
        "point_delta",
        "point_use",
        "point_balance",
        "point_state",
        "po_datetime",
        "po_expire_date",
    )
    list_display_links = ("id", "user_display")
    search_fields = ("user__username", "user__email", "po_content", "po_rel_table", "po_rel_action")
    list_filter = (PointStateFilter, "po_expired", "po_datetime", "po_expire_date")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("point_snapshot",)
    list_fullwidth = True

    def revert_disabled(self, request, obj=None):
        # A point row and Profile.user_point are written as one ledger operation
        # (point_ledger.insert_point). Restoring just the row would leave the balance and the
        # ledger disagreeing, so the history screen is read-only; use the grant form instead.
        return True

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["form"] = UserPointGrantForm
            kwargs["fields"] = UserPointGrantForm.Meta.fields
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        if change:
            return super().save_model(request, obj, form, change)
        # The ledger writes the row and the balance together (a plain save would leave the balance stale).
        rel_action = f"{request.user.get_username()}-{uuid.uuid4().hex[:13]}"
        result = point_ledger.insert_point(
            obj.user,
            obj.po_point,
            obj.po_content or "관리자 포인트",
            "@passive",
            0,
            rel_action,
            require_balance=True,
        )
        if result != point_ledger.APPLIED:
            raise PermissionDenied(f"포인트를 처리하지 못했습니다 ({result}).")
        row = User_Point.objects.get(user=obj.user, po_rel_table="@passive", po_rel_action=rel_action)
        obj.__dict__.update({key: value for key, value in row.__dict__.items() if not key.startswith("_")})
        obj._state.adding = False

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return ((None, {"fields": UserPointGrantForm.Meta.fields}),)
        fieldsets = fieldsets_without(tuple(super().get_fieldsets(request, obj)), "point_snapshot")
        return (
            (
                _("Point snapshot"),
                {
                    "classes": ("tab",),
                    "fields": ("point_snapshot",),
                },
            ),
        ) + fieldsets

    @admin.display(ordering="user__username", description=_("Member"))
    def user_display(self, obj):
        return obj.user.get_username() if obj.user_id and obj.user else "-"

    @admin.display(ordering="po_point", description=_("Point amount"))
    def point_delta(self, obj):
        return money_html(obj.po_point, danger=obj.po_point < 0)

    @admin.display(ordering="po_use_point", description=_("Used point"))
    def point_use(self, obj):
        return money_html(obj.po_use_point, danger=obj.po_use_point > 0)

    @admin.display(ordering="po_mb_point", description=_("Point balance"))
    def point_balance(self, obj):
        return money_html(obj.po_mb_point, danger=obj.po_mb_point < 0)

    @admin.display(ordering="po_expired", description=_("Point status"))
    def point_state(self, obj):
        if obj.po_expired:
            return badge(_("Expired"), "danger")
        if obj.po_expire_date and obj.po_expire_date < timezone.now():
            return badge(_("Expiration reached"), "warning")
        return badge(_("Available"), "success")

    @admin.display(description=_("Point snapshot"))
    def point_snapshot(self, obj):
        tone = "danger" if obj.po_expired else "success"
        state = _("Expired") if obj.po_expired else _("Available")
        return snapshot_panel(
            _("Point snapshot"),
            state,
            tone,
            _("Review point movement, balance, expiration, and source relation together."),
            (
                (_("Member"), self.user_display(obj), compact_text(getattr(obj.user, "email", ""), obj.po_content)),
                (_("Point amount"), format_number(obj.po_point), _("Used point %(point)s") % {"point": format_number(obj.po_use_point)}),
                (_("Balance after change"), format_number(obj.po_mb_point), _("Expired flag %(value)s") % {"value": obj.po_expired}),
                (_("Expiration"), datetime_value(obj.po_expire_date), datetime_value(obj.po_datetime)),
                (_("Related source"), compact_text(obj.po_rel_table, obj.po_rel_id), obj.po_rel_action or "-"),
            ),
        )


class UserMemoAdmin(ModelAdmin):
    list_display = ("id", "memo_user", "memo_type", "memo_length", "memo_status", "me_send_datetime", "me_read_datetime")
    list_display_links = ("id", "memo_user")
    search_fields = ("user__username", "user__email", "me_memo", "me_send_ip")
    list_filter = (MemoStateFilter, "me_type", "me_send_datetime", "me_read_datetime")
    autocomplete_fields = ("user",)
    list_select_related = ("user",)
    readonly_fields = ("memo_snapshot",)
    list_fullwidth = True

    def get_fieldsets(self, request, obj=None):
        fieldsets = fieldsets_without(tuple(super().get_fieldsets(request, obj)), "memo_snapshot")
        if obj is None:
            return fieldsets
        return (
            (
                _("Memo snapshot"),
                {
                    "classes": ("tab",),
                    "fields": ("memo_snapshot",),
                },
            ),
        ) + fieldsets

    @admin.display(ordering="user__username", description=_("Member"))
    def memo_user(self, obj):
        return obj.user.get_username() if obj.user_id and obj.user else "-"

    @admin.display(ordering="me_type", description=_("Memo type"))
    def memo_type(self, obj):
        tone = "info" if obj.me_type == "send" else "neutral"
        return badge(obj.me_type or "-", tone)

    @admin.display(description=_("Memo length"))
    def memo_length(self, obj):
        return badge(_("%(count)s chars") % {"count": format_number(len(obj.me_memo or ""))}, "success")

    @admin.display(ordering="me_read_datetime", description=_("Memo status"))
    def memo_status(self, obj):
        if obj.me_read_datetime:
            return badge(_("Read"), "success")
        if obj.me_type == "send":
            return badge(_("Sent"), "info")
        return badge(_("Unread"), "warning")

    @admin.display(description=_("Memo snapshot"))
    def memo_snapshot(self, obj):
        state = _("Read") if obj.me_read_datetime else _("Unread")
        tone = "success" if obj.me_read_datetime else "warning"
        return snapshot_panel(
            _("Memo snapshot"),
            state,
            tone,
            _("Review sender, recipient, read state, IP, and message size together."),
            (
                (_("Member"), self.memo_user(obj), compact_text(getattr(obj.user, "email", ""), obj.me_type)),
                (_("Recipient"), format_number(obj.me_recv_user_id), _("Sender %(id)s") % {"id": format_number(obj.me_send_id)}),
                (_("Memo length"), format_number(len(obj.me_memo or "")), _("Characters")),
                (_("Sent"), datetime_value(obj.me_send_datetime), compact_text(obj.me_send_ip)),
                (_("Read"), datetime_value(obj.me_read_datetime), _("Full memo is editable in the Memo tab.")),
            ),
        )


class UserScrapAdmin(ModelAdmin):
    list_display = ("id", "scrap_user", "board", "post", "ms_datetime")
    list_display_links = ("id", "scrap_user")
    search_fields = ("user__username", "user__email", "board__bo_table", "board__bo_subject", "post__wr_subject")
    list_filter = ("board", "ms_datetime")
    autocomplete_fields = ("user", "board", "post")
    list_select_related = ("user", "board", "post")
    list_fullwidth = True

    @admin.display(ordering="user__username", description=_("Member"))
    def scrap_user(self, obj):
        return obj.user.get_username() if obj.user_id and obj.user else "-"


class GroupAdmin(BaseGroupAdmin, ModelAdmin):
    list_display = ("name", "member_count", "permission_count")
    search_fields = ("name", "permissions__name", "permissions__codename")
    filter_horizontal = ("permissions",)

    @admin.display(description=_("Members"))
    def member_count(self, obj):
        return format_number(obj.user_set.count())

    @admin.display(description=_("Permissions"))
    def permission_count(self, obj):
        return format_number(obj.permissions.count())


for model in (User, Group):
    try:
        admin.site.unregister(model)
    except NotRegistered:
        pass


admin.site.register(User, UserAdmin)
admin.site.register(Group, GroupAdmin)
admin.site.register(Profile, ProfileAdmin)
admin.site.register(User_Point, UserPointAdmin)
admin.site.register(User_Memo, UserMemoAdmin)
admin.site.register(User_Scrap, UserScrapAdmin)
