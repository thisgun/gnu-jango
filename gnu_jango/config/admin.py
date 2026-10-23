from django.contrib import admin
from django.contrib.admin.options import csrf_protect_m
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.utils.encoding import force_str
from django.utils.translation import gettext_lazy as _

from gnu_jango.utils.admin import admin_url
from gnu_jango.config import config
from gnu_jango.core.audit import UnfoldHistoryAdmin, history_record_for
from gnu_jango.shop.settings_sync import sync_shop_phone_from_config

from .Configforms import ConfigsForm
from .models import Config, is_secret_config_name


class TestConfigAdmin(UnfoldHistoryAdmin):

    # The settings screen is the custom changelist below. This fieldset is what the
    # simple-history revert form renders for a single Config row.
    fieldsets = [
        (None, {"fields": ["name", "value"]}),
    ]
    # Reverting changes the value, never the setting key.
    readonly_fields = ("name",)

    change_list_template = "admin/config/change_list.html"

    # The change page renders entirely with Unfold's native widget/utility
    # classes (see templates/admin/config/change_list.html), so no custom
    # stylesheet is loaded here. The legacy `admin/admin_config.css` carried a
    # float-based layout that fought the Unfold flex layout, so it was dropped.

    def changelist_redirect(self):
        changelist_url = admin_url(Config, "changelist")
        return HttpResponseRedirect(changelist_url)

    def add_view(self, *args, **kwargs):
        return self.changelist_redirect()

    def change_view(self, *args, **kwargs):
        return self.changelist_redirect()

    def revert_disabled(self, request, obj=None):
        if super().revert_disabled(request, obj):
            return True
        record = history_record_for(obj)
        # Secret values are stored as a mask in history; restoring one would overwrite the
        # real credential with "********".
        return bool(record and is_secret_config_name(record.name))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # The settings form keeps the legacy shop phone column in step; a history revert has
        # to do the same or the two admin screens would show different numbers.
        if obj.name == "de_admin_company_tel":
            sync_shop_phone_from_config(obj.value)

    @csrf_protect_m
    def changelist_view(self, request, extra_context=None):

        # Only users allowed to change Config may submit the settings form.
        # Without this guard a view-only staff user could POST and overwrite
        # the whole configuration, since the form is saved before the parent
        # changelist_view (which enforces permissions) is reached.
        if request.method == "POST" and not self.has_change_permission(request):
            raise PermissionDenied

        if extra_context is None:
            extra_context = {}
        settings_form = ConfigsForm(request.POST or None)
        if settings_form.is_valid():
            settings_form.save()
            if "de_admin_company_tel" in settings_form.cleaned_data:
                sync_shop_phone_from_config(settings_form.cleaned_data["de_admin_company_tel"])
            config.clear()
            # info(request, _("Settings were successfully updated."))
            return self.changelist_redirect()
        extra_context["configs_form"] = settings_form
        extra_context["title"] = "{} {}".format(
            _("Change"),
            force_str(Config._meta.verbose_name_plural),
        )
        return super().changelist_view(request, extra_context)


# Register your models here.
admin.site.register(Config, TestConfigAdmin)
