from django.contrib import admin
from django.contrib.admin.options import csrf_protect_m
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseRedirect
from django.utils.encoding import force_str
from django.utils.translation import gettext_lazy as _
from unfold.admin import ModelAdmin

from gnu_jango.utils.admin import admin_url
from gnu_jango.config import config

from .Configforms import ConfigsForm
from .models import Config


class TestConfigAdmin(ModelAdmin):

    fieldsets = [
        # (None,               {'fields': ['question_text']}),
        (_("기본환경"), {"fields": ["cf_title", "cf_theme", "cf_admin"], "classes": ["collapse"]}),
    ]

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
