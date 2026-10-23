"""Shared audit-history helpers.

The project uses django-simple-history for the field-level revision tables and Unfold for the
admin skin. ``UnfoldHistoryAdmin`` is the one base class the audited ModelAdmins inherit so the
history screen, diff view and revert action keep Unfold's layout.
"""

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, reverse
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin

AUDIT_PAGE_SIZE = 50
AUDIT_PER_MODEL_LIMIT = 500


class UnfoldHistoryAdmin(SimpleHistoryAdmin, ModelAdmin):
    """SimpleHistoryAdmin with Unfold's form and changelist widgets.

    MRO is deliberate: SimpleHistoryAdmin adds the history URLs and views, while Unfold's
    ModelAdmin supplies the template/widget layer both classes inherit from Django's
    ModelAdmin. The two do not override the same admin hooks.
    """

    def history_form_view(self, request, object_id, version_id, extra_context=None):
        # SimpleHistoryAdmin renders a disabled revert button but still accepts the POST.
        # Enforce the same rule server-side so a crafted POST cannot restore an immutable
        # ledger row or overwrite a redacted credential.
        if request.method == "POST":
            record = self._history_record_for_restore(object_id, version_id)
            if record is not None and self.revert_disabled(request, record.instance):
                self.message_user(
                    request,
                    _("This history row cannot be restored. Use the model's normal workflow instead."),
                    messages.ERROR,
                )
                return HttpResponseRedirect(request.path)
        return super().history_form_view(request, object_id, version_id, extra_context)

    def _history_record_for_restore(self, object_id, version_id):
        pk_name = self.model._meta.pk.attname
        return (
            self.model.history.model.objects.filter(**{pk_name: object_id, "history_id": version_id})
            .first()
        )


def history_record_for(obj):
    """Return the historical row a revert form is based on, if ``obj`` came from history.

    ``simple_history`` attaches the source record as ``_history`` on the instance returned by
    ``HistoricalRecord.instance``. That is the only reliable marker, because the restored
    instance is a normal model instance by the time ``save_model`` sees it.
    """

    return getattr(obj, "_history", None)


def audit_model_specs():
    """The models shown on the unified audit screen.

    Labels and search fields are kept here instead of in the template so a new audited model
    only needs one entry (plus its HistoricalRecords field and admin registration).
    """

    from gnu_jango.config.models import Config
    from gnu_jango.shop.models import ShopCouponLog, ShopOrder
    from gnu_jango.users.models import User_Point

    return (
        {
            "model": ShopOrder,
            "label": _("Shop order"),
            "search_fields": ("od_id", "od_name", "od_b_name", "od_hp", "od_tno"),
            "object_repr": lambda record: " · ".join(
                part for part in (record.od_id, record.od_name) if part
            ),
        },
        {
            "model": User_Point,
            "label": _("Member point"),
            "search_fields": ("po_content", "po_rel_action", "po_rel_table"),
            "object_repr": lambda record: " · ".join(
                part for part in (str(record.user_id or ""), record.po_content or "") if part
            ),
        },
        {
            "model": ShopCouponLog,
            "label": _("Coupon usage"),
            "search_fields": ("cp_id", "od_id", "mb_id"),
            "object_repr": lambda record: " · ".join(
                part for part in (record.cp_id, record.od_id) if part
            ),
        },
        {
            "model": Config,
            "label": _("Site setting"),
            "search_fields": ("name",),
            "object_repr": lambda record: record.name,
        },
    )


def _can_view_audit_model(user, model):
    opts = model._meta
    return user.is_superuser or user.has_perm(f"{opts.app_label}.view_{opts.model_name}")


def _history_url(model, record):
    opts = model._meta
    object_id = getattr(record, opts.pk.attname)
    try:
        return reverse(
            f"admin:{opts.app_label}_{opts.model_name}_simple_history",
            args=[object_id, record.history_id],
        )
    except NoReverseMatch:
        try:
            return reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[object_id])
        except NoReverseMatch:
            return ""


def _display_change_value(value):
    if value is None or value == "":
        return "-"
    text = str(value)
    if len(text) > 80:
        text = text[:77] + "..."
    return text


def _change_summary(record):
    """A short 'field: old → new' line for the changelist.

    ``prev_record`` is one query per row; the audit page only asks for it after pagination, so
    the cost is bounded by AUDIT_PAGE_SIZE.
    """

    if record.history_type == "+":
        return str(_("Created"))
    if record.history_type == "-":
        return str(_("Deleted"))
    previous = record.prev_record
    if previous is None:
        return ""
    try:
        delta = record.diff_against(previous)
    except Exception:
        return ""
    parts = []
    for change in delta.changes:
        parts.append(
            f"{change.field}: {_display_change_value(change.old)} → {_display_change_value(change.new)}"
        )
    return "; ".join(parts)


def audit_log_view(request):
    """One screen for every audited model, newest change first.

    Rows link to the model's simple-history page, where the field diff is shown and the
    model-specific revert rules apply (settings: yes, orders: safe fields only, ledgers: no).
    """

    if not request.user.is_active or not request.user.is_staff:
        raise PermissionDenied

    specs = [spec for spec in audit_model_specs() if _can_view_audit_model(request.user, spec["model"])]
    for spec in specs:
        spec["value"] = spec["model"]._meta.label_lower
    selected_model = (request.GET.get("model") or "").strip()
    selected_action = (request.GET.get("action") or "").strip()
    selected_user = (request.GET.get("user") or "").strip()
    selected_query = (request.GET.get("q") or "").strip()
    date_from = parse_date(request.GET.get("date_from") or "")
    date_to = parse_date(request.GET.get("date_to") or "")

    entries = []
    for spec in specs:
        model = spec["model"]
        if selected_model and selected_model != model._meta.label_lower:
            continue
        queryset = model.history.all()
        if selected_action in {"+", "~", "-"}:
            queryset = queryset.filter(history_type=selected_action)
        if selected_user:
            queryset = queryset.filter(history_user__username__icontains=selected_user)
        if date_from:
            queryset = queryset.filter(history_date__date__gte=date_from)
        if date_to:
            queryset = queryset.filter(history_date__date__lte=date_to)
        if selected_query:
            query = Q(history_user__username__icontains=selected_query)
            for field in spec["search_fields"]:
                query |= Q(**{f"{field}__icontains": selected_query})
            queryset = queryset.filter(query)
        queryset = queryset.select_related("history_user").order_by("-history_date")[:AUDIT_PER_MODEL_LIMIT]
        for record in queryset:
            entries.append(
                {
                    "record": record,
                    "model": model,
                    "model_label": spec["label"],
                    "object_label": spec["object_repr"](record) or "-",
                    "action": record.history_type,
                    "action_label": record.get_history_type_display(),
                    "user": getattr(record.history_user, "username", "") or _("System"),
                    "history_date": record.history_date,
                    "url": _history_url(model, record),
                }
            )

    entries.sort(key=lambda entry: entry["history_date"], reverse=True)
    paginator = Paginator(entries, AUDIT_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    for entry in page_obj.object_list:
        entry["changes"] = _change_summary(entry["record"])

    query_params = request.GET.copy()
    query_params.pop("page", None)
    context = {
        **admin.site.each_context(request),
        "title": _("Audit log"),
        "opts": None,
        "specs": specs,
        "entries": page_obj.object_list,
        "page_obj": page_obj,
        "page_query": query_params.urlencode(),
        "filters": {
            "model": selected_model,
            "action": selected_action,
            "user": selected_user,
            "q": selected_query,
            "date_from": date_from.isoformat() if date_from else "",
            "date_to": date_to.isoformat() if date_to else "",
        },
        "audit_per_model_limit": AUDIT_PER_MODEL_LIMIT,
    }
    return TemplateResponse(request, "admin/core/audit_log.html", context)
