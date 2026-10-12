"""Re-register Django's built-in Site and Redirect admins on top of Unfold.

django.contrib.sites and django.contrib.redirects register plain ``ModelAdmin`` classes.
Unfold's changelist action bar only shows its Run button when the action select is bound
with Alpine, which the plain admin does not do, so bulk actions (delete selected) could not
be run for these two models. Same re-registration pattern as ``core.admin.tokens``.
"""

from django.contrib import admin
from django.contrib.admin.sites import NotRegistered
from django.contrib.redirects.admin import RedirectAdmin as BaseRedirectAdmin
from django.contrib.redirects.models import Redirect
from django.contrib.sites.admin import SiteAdmin as BaseSiteAdmin
from django.contrib.sites.models import Site
from unfold.admin import ModelAdmin

for model in (Site, Redirect):
    try:
        admin.site.unregister(model)
    except NotRegistered:
        pass


@admin.register(Site)
class SiteAdmin(BaseSiteAdmin, ModelAdmin):
    pass


@admin.register(Redirect)
class RedirectAdmin(BaseRedirectAdmin, ModelAdmin):
    pass
