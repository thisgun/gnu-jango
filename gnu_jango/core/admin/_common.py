from collections import OrderedDict
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from operator import itemgetter
import hashlib

from django import forms, VERSION, conf
from django.apps import apps
from django.contrib import admin, messages
from django.contrib.admin.models import ADDITION, CHANGE, DELETION, LogEntry
from django.contrib.admin.sites import NotRegistered
from django.contrib.admin import widgets
from django.contrib.admin.options import csrf_protect_m
from django.core.exceptions import PermissionDenied, ImproperlyConfigured
from unfold.admin import ModelAdmin, TabularInline
from unfold.contrib.filters.admin import DropdownFilter

from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin

# from django.contrib.auth.models import User as AuthUser
from django.contrib.messages import error
from django.conf import settings

from django.core.files.storage import default_storage

from django.contrib.redirects.admin import RedirectAdmin

from django.forms import fields, ModelForm, ValidationError
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.encoding import smart_bytes, force_str
from django.utils.formats import localize
from django.utils.html import format_html, format_html_join
from django.utils.module_loading import import_string
from django.utils.dateparse import parse_date
from django.utils.text import normalize_newlines
from django.utils.translation import gettext_lazy as _
from django.urls import path
from django.db.models import Count, F
from django.db.models.functions import Lower, TruncDate
from django.db import models
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from gnu_jango.utils import lib
from gnu_jango.core.models import (
    ContentPage,
    Editor_attachments,
    FAQItem,
    FAQMaster,
    MailCampaign,
    MailSendLog,
    New_win,
    Notification,
    Poll,
    PollChoice,
    PollComment,
    PollVote,
    SearchKeyword,
    Site_menu,
    VisitLog,
)


from copy import deepcopy
from django.utils.translation import activate, get_language
from django.urls import reverse, reverse_lazy

from functools import partial, update_wrapper
from gnu_jango.utils.admin import admin_url
from gnu_jango.bbs.models import Group, Board
from gnu_jango.bbs.utils import get_pretty_url
from gnu_jango.core.forms import SiteMenuForms

from django.db.models.functions import Substr, Length
from django.db.models import Q, Max, Min, Sum
from gnu_jango.utils.lib import chng_frm_base


def admin_badge(label, tone="neutral"):
    return format_html('<span class="g5-admin-badge g5-admin-badge-{}">{}</span>', tone, label)


def admin_datetime(value):
    if not value:
        return "-"
    try:
        value = timezone.localtime(value)
    except ValueError:
        pass
    return value.strftime("%Y-%m-%d %H:%M:%S")


def admin_number(value):
    return f"{int(value or 0):,}"


def admin_report_date_range(request, default_days=29):
    start = parse_date(str(request.GET.get("date_from") or request.GET.get("start") or ""))
    end = parse_date(str(request.GET.get("date_to") or request.GET.get("end") or ""))
    if not start and not end:
        end = timezone.localdate()
        start = end - timedelta(days=default_days)
    return start, end


def compact_identifier(value, head=12, tail=8):
    text = str(value or "").strip()
    if not text:
        return "-"
    if len(text) <= head + tail + 3:
        return text
    return f"{text[:head]}...{text[-tail:]}"


def token_user_label(user):
    if not user:
        return "-"
    username = getattr(user, "username", "") or str(user)
    email = getattr(user, "email", "") or ""
    if email:
        return format_html("<strong>{}</strong><br><small>{}</small>", username, email)
    return username


def admin_snapshot_panel(title, state, tone, description, cards):
    return format_html(
        '<section class="g5-admin-order-snapshot g5-admin-order-snapshot-{}">'
        '<div class="g5-admin-order-snapshot-head">'
        '<div><span>{}</span><strong>{}</strong></div>'
        '<p>{}</p>'
        '</div>'
        '<div class="g5-admin-order-snapshot-grid">{}</div>'
        '</section>',
        tone,
        title,
        state,
        description,
        format_html_join(
            "",
            '<article class="g5-admin-order-snapshot-card"><span>{}</span><strong>{}</strong><small>{}</small></article>',
            cards,
        ),
    )


class AdminDatePeriodFilter(DropdownFilter):
    title = _("Date")
    parameter_name = "date_period"
    field_name = ""

    def lookups(self, request, model_admin):
        return (
            ("today", _("Today")),
            ("7d", _("Last 7 days")),
            ("month", _("This month")),
            ("year", _("This year")),
        )

    def queryset(self, request, queryset):
        value = self.value()
        today = timezone.localdate()
        if value == "today":
            return queryset.filter(**{f"{self.field_name}__date": today})
        if value == "7d":
            return queryset.filter(**{f"{self.field_name}__date__gte": today - timedelta(days=6)})
        if value == "month":
            return queryset.filter(**{f"{self.field_name}__date__year": today.year, f"{self.field_name}__date__month": today.month})
        if value == "year":
            return queryset.filter(**{f"{self.field_name}__date__year": today.year})
        return queryset


class TokenCreatedDateFilter(AdminDatePeriodFilter):
    title = _("Created at")
    parameter_name = "created_at_period"
    field_name = "created_at"


class TokenExpiresDateFilter(AdminDatePeriodFilter):
    title = _("Expires at")
    parameter_name = "expires_at_period"
    field_name = "expires_at"


class BlacklistCreatedDateFilter(AdminDatePeriodFilter):
    title = _("Created at")
    parameter_name = "token_created_at_period"
    field_name = "token__created_at"


class BlacklistExpiresDateFilter(AdminDatePeriodFilter):
    title = _("Expires at")
    parameter_name = "token_expires_at_period"
    field_name = "token__expires_at"


class BlacklistedDateFilter(AdminDatePeriodFilter):
    title = _("Blacklisted at")
    parameter_name = "blacklisted_at_period"
    field_name = "blacklisted_at"


# `django.contrib.admin` (the default AdminConfig) already calls
# admin.autodiscover() from its ready() hook, so calling it again here is
# redundant and can trigger duplicate-registration churn.
admin.site.enable_nav_sidebar = True
