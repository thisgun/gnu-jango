from gnu_jango.shop.admin._common import *  # noqa: F401,F403
from django.utils.translation import gettext_lazy as _

from gnu_jango.shop.admin.coupon_forms import (
    COUPON_METHOD_CHOICES,
    COUPON_METHOD_LABELS,
    CategoryTargetAutocompleteView,
    ProductTargetAutocompleteView,
    ShopCouponAdminForm,
)


class CouponMethodFilter(admin.SimpleListFilter):
    title = "쿠폰종류"
    parameter_name = "cp_method"

    def lookups(self, request, model_admin):
        return [(str(value), label) for value, label in COUPON_METHOD_CHOICES]

    def queryset(self, request, queryset):
        value = self.value()
        if value is not None and value.isdigit():
            return queryset.filter(cp_method=int(value))
        return queryset


@admin.register(ShopCouponZone)
class ShopCouponZoneAdmin(ModelAdmin):
    list_display = ("id", "cz_subject", "coupon_zone_status", "coupon_zone_benefit", "coupon_zone_rule", "cz_start", "cz_end")
    search_fields = ("cz_subject", "cp_target")
    list_filter = ("cz_type", "cp_method", "cp_type")
    readonly_fields = ("coupon_zone_snapshot",)
    fieldsets = (
        (
            _("Coupon zone snapshot"),
            {
                "classes": ("tab",),
                "fields": ("coupon_zone_snapshot",),
            },
        ),
        (
            _("Coupon zone identity"),
            {
                "classes": ("tab",),
                "fields": (
                    ("cz_subject", "cz_type"),
                    ("cz_start", "cz_end", "cz_period"),
                    ("cz_file", "image_url"),
                    "created_at",
                ),
            },
        ),
        (
            _("Coupon benefit"),
            {
                "classes": ("tab",),
                "fields": (
                    ("cp_method", "cp_target"),
                    ("cp_type", "cp_price", "cz_point"),
                    ("cp_minimum", "cp_maximum", "cp_trunc"),
                    "cz_download",
                ),
            },
        ),
    )

    @admin.display(description=_("Status"))
    def coupon_zone_status(self, obj):
        today = timezone.localdate()
        if obj.cz_end and obj.cz_end < today:
            return badge(_("Expired"), "neutral")
        if obj.cz_start and obj.cz_start > today:
            return badge(_("Scheduled"), "info")
        return badge(_("Active"), "success")

    @admin.display(description=_("Benefit"))
    def coupon_zone_benefit(self, obj):
        if obj.cp_type == 1:
            return badge(_("%(rate)s%% discount") % {"rate": format_number(obj.cp_price)}, "info")
        return money_html(obj.cp_price)

    @admin.display(description=_("Rule"))
    def coupon_zone_rule(self, obj):
        return compact_text(_("Minimum %(amount)s") % {"amount": format_number(obj.cp_minimum)}, obj.cp_target)

    @admin.display(description=_("Coupon zone snapshot"))
    def coupon_zone_snapshot(self, obj):
        if not obj:
            return "-"
        today = timezone.localdate()
        if obj.cz_end and obj.cz_end < today:
            state, tone = _("Expired"), "neutral"
        elif obj.cz_start and obj.cz_start > today:
            state, tone = _("Scheduled"), "info"
        else:
            state, tone = _("Active"), "success"

        return snapshot_panel(
            _("Coupon zone snapshot"),
            state,
            tone,
            _("Review public coupon exposure, period, benefit, and download limits together."),
            (
                (_("Coupon title"), obj.cz_subject, obj.cz_file or "-"),
                (_("Period"), f"{date_value(obj.cz_start)} - {date_value(obj.cz_end)}", _("%(days)s days") % {"days": format_number(obj.cz_period)}),
                (_("Benefit"), format_number(obj.cp_price), compact_text(_("Point %(point)s") % {"point": format_number(obj.cz_point)}, obj.cp_target)),
                (_("Rule"), _("Minimum %(amount)s") % {"amount": format_number(obj.cp_minimum)}, _("Maximum %(amount)s") % {"amount": format_number(obj.cp_maximum)}),
                (_("Downloads"), format_number(obj.cz_download), _("Created %(date)s") % {"date": datetime_value(obj.created_at)}),
                (_("Image"), obj.image_url or "-", obj.cz_file or "-"),
            ),
        )


@admin.register(ShopCoupon)
class ShopCouponAdmin(ModelAdmin):
    form = ShopCouponAdminForm
    list_display = (
        "cp_id", "coupon_recipient", "cp_subject", "coupon_scope", "coupon_status", "coupon_benefit",
        "coupon_period", "created_at",
    )
    list_select_related = ("user",)
    search_fields = ("cp_id", "cp_subject", "user__username", "cp_target")
    list_filter = (CouponMethodFilter, "cp_type", "cp_all_members", "cp_used")
    readonly_fields = ("coupon_snapshot",)
    autocomplete_fields = ("user", "coupon_zone")
    # youngcart couponform.php: the target row only for product / category coupons, and the
    # rate-only fields only for a percentage coupon
    conditional_fields = {
        "target_product": "cp_method == '0'",
        "target_category": "cp_method == '1'",
        "user": "!cp_all_members",
        "cp_maximum": "cp_type == '1'",
        "cp_trunc": "cp_type == '1'",
    }
    fieldsets = (
        (
            _("Coupon snapshot"),
            {
                "classes": ("tab",),
                "fields": ("coupon_snapshot",),
            },
        ),
        (
            _("Coupon identity"),
            {
                "classes": ("tab",),
                "fields": (
                    ("cp_id", "coupon_zone"),
                    ("cp_subject", "cp_used"),
                    ("cp_all_members", "user"),
                    "created_at",
                ),
            },
        ),
        (
            _("Coupon benefit"),
            {
                "classes": ("tab",),
                "fields": (
                    "cp_method",
                    ("target_product", "target_category"),
                    ("cp_type", "cp_price"),
                    ("cp_minimum", "cp_maximum", "cp_trunc"),
                    ("cp_start", "cp_end"),
                ),
            },
        ),
    )

    def get_readonly_fields(self, request, obj=None):
        readonly = super().get_readonly_fields(request, obj)
        # the coupon code is the primary key: editing it would copy the coupon to a new row
        return (*readonly, "cp_id") if obj else readonly

    def get_urls(self):
        info = (self.opts.app_label, self.opts.model_name)
        return [
            path(
                "target-products/",
                self.admin_site.admin_view(ProductTargetAutocompleteView.as_view(model_admin=self)),
                name="%s_%s_target_products" % info,
            ),
            path(
                "target-categories/",
                self.admin_site.admin_view(CategoryTargetAutocompleteView.as_view(model_admin=self)),
                name="%s_%s_target_categories" % info,
            ),
            *super().get_urls(),
        ]

    @admin.display(description="발행 대상")
    def coupon_recipient(self, obj):
        if obj.cp_all_members:
            return badge("전체회원", "info")
        return getattr(obj.user, "username", "") or "-"

    @admin.display(description="쿠폰종류")
    def coupon_scope(self, obj):
        label = COUPON_METHOD_LABELS.get(obj.cp_method, str(obj.cp_method))
        return compact_text(label, obj.cp_target) if obj.cp_target else label

    @admin.display(description=_("Status"))
    def coupon_status(self, obj):
        today = timezone.localdate()
        if flag_enabled(obj.cp_used):
            return badge(_("Used"), "neutral")
        if obj.cp_end and obj.cp_end < today:
            return badge(_("Expired"), "neutral")
        if obj.cp_start and obj.cp_start > today:
            return badge(_("Scheduled"), "info")
        return badge(_("Usable"), "success")

    @admin.display(description=_("Benefit"))
    def coupon_benefit(self, obj):
        if obj.cp_type == 1:
            return badge(_("%(rate)s%% discount") % {"rate": format_number(obj.cp_price)}, "info")
        return money_html(obj.cp_price)

    @admin.display(description=_("Period"))
    def coupon_period(self, obj):
        return f"{date_value(obj.cp_start)} - {date_value(obj.cp_end)}"

    @admin.display(description=_("Coupon snapshot"))
    def coupon_snapshot(self, obj):
        if not obj:
            return "-"
        today = timezone.localdate()
        if flag_enabled(obj.cp_used):
            state, tone = _("Used"), "neutral"
        elif obj.cp_end and obj.cp_end < today:
            state, tone = _("Expired"), "neutral"
        elif obj.cp_start and obj.cp_start > today:
            state, tone = _("Scheduled"), "info"
        else:
            state, tone = _("Usable"), "success"

        return snapshot_panel(
            _("Coupon snapshot"),
            state,
            tone,
            _("Review recipient, benefit, target, period, and usage state together."),
            (
                (_("Coupon title"), obj.cp_subject, obj.cp_id),
                (
                    _("Recipient"),
                    "전체회원" if obj.cp_all_members else getattr(obj.user, "username", "") or "-",
                    "-" if obj.cp_all_members else getattr(obj.user, "email", "") or "-",
                ),
                (_("Benefit"), format_number(obj.cp_price), compact_text(obj.cp_target, _("Minimum %(amount)s") % {"amount": format_number(obj.cp_minimum)})),
                (_("Period"), f"{date_value(obj.cp_start)} - {date_value(obj.cp_end)}", _("Created %(date)s") % {"date": datetime_value(obj.created_at)}),
                (_("Limit"), _("Maximum %(amount)s") % {"amount": format_number(obj.cp_maximum)}, _("Truncation %(value)s") % {"value": format_number(obj.cp_trunc)}),
                (_("Source"), str(obj.coupon_zone or "-"), _("Used") if flag_enabled(obj.cp_used) else _("Not used")),
            ),
        )


@admin.register(ShopCouponLog)
class ShopCouponLogAdmin(ModelAdmin):
    list_display = ("cl_id", "cp_id", "user", "od_id", "cp_price", "cl_datetime")
    search_fields = ("cp_id", "mb_id", "od_id", "user__username")
    list_filter = ("cl_datetime",)
    readonly_fields = ("cl_id",)

    # A coupon log is the order's record of the discount: editing or deleting one changed what
    # the order owes (od_misu) and stopped the coupon from coming back when the order is
    # cancelled. Logs are written and removed only by the order and cancel paths.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

