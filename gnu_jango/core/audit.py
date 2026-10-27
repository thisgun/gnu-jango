"""Shared audit-history helpers.

The project uses django-simple-history for the field-level revision tables and Unfold for the
admin skin. ``UnfoldHistoryAdmin`` is the one base class the audited ModelAdmins inherit so the
history screen, diff view and revert action keep Unfold's layout.
"""

import csv

from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import CharField, F, Q, Value
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import NoReverseMatch, reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.translation import gettext_lazy as _
from simple_history.admin import SimpleHistoryAdmin
from unfold.admin import ModelAdmin

from gnu_jango.utils.lib import get_client_ip

AUDIT_PAGE_SIZE = 50
AUDIT_EXPORT_LIMIT = 1000
# get_history_type_display() reuses Django's "created" translation, which the Korean locale
# renders as "생성일시" (a timestamp). The audit screen needs action verbs.
AUDIT_ACTION_LABELS = {
    "+": "생성",
    "~": "변경",
    "-": "삭제",
}
AUDIT_ACTION_CHOICES = tuple(AUDIT_ACTION_LABELS.items())


def log_admin_export(request, model, count, *, label=""):
    """Record who exported how many rows through an import-export admin endpoint."""
    label = label or str(model._meta.verbose_name_plural)
    LogEntry.objects.create(
        user_id=request.user.pk,
        content_type_id=ContentType.objects.get_for_model(model).pk,
        object_id="",
        object_repr=(f"Export {label}: {count} rows")[:200],
        action_flag=CHANGE,
        change_message=f"Admin export via django-import-export; rows={count}; ip={get_client_ip(request) or '-'}",
    )


class AdminExportAuditMixin:
    """Log successful export downloads, including the row count and client IP."""

    export_audit_label = ""

    def _do_file_export(self, file_format, request, queryset, export_form=None):
        response = super()._do_file_export(file_format, request, queryset, export_form=export_form)
        try:
            count = queryset.count()
        except Exception:
            count = 0
        log_admin_export(request, self.model, count, label=self.export_audit_label)
        return response


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
    from gnu_jango.shop.models import (
        ShopCoupon,
        ShopCouponLog,
        ShopOrder,
        ShopOrderItem,
        ShopProduct,
        ShopShippingPolicy,
    )
    from gnu_jango.users.models import User_Point

    return (
        {
            "model": ShopOrder,
            "label": "주문",
            "search_fields": ("od_id", "od_name", "od_b_name", "od_hp", "od_tno"),
            "object_repr": lambda record: " · ".join(
                part for part in (record.od_id, record.od_name) if part
            ),
            "restore": True,
        },
        {
            "model": ShopOrderItem,
            "label": "주문 상품",
            "search_fields": ("it_name", "it_id", "ct_id", "order__od_id"),
            "object_repr": lambda record: " · ".join(
                part for part in (record.order_id, record.it_name, record.ct_status) if part
            ),
            "restore": False,
        },
        {
            "model": ShopProduct,
            "label": "상품",
            "search_fields": ("it_id", "it_name", "it_brand", "it_maker"),
            "object_repr": lambda record: " · ".join(
                part for part in (record.it_id, record.it_name) if part
            ),
            "restore": False,
        },
        {
            "model": ShopCoupon,
            "label": "쿠폰",
            "search_fields": ("cp_id", "cp_subject", "cp_target"),
            "object_repr": lambda record: " · ".join(
                part for part in (record.cp_id, record.cp_subject) if part
            ),
            "restore": False,
        },
        {
            "model": ShopCouponLog,
            "label": "쿠폰 사용",
            "search_fields": ("cp_id", "od_id", "mb_id"),
            "object_repr": lambda record: " · ".join(
                part for part in (record.cp_id, record.od_id) if part
            ),
            "restore": False,
        },
        {
            "model": ShopShippingPolicy,
            "label": "배송 정책",
            "search_fields": ("de_admin_company_name", "de_delivery_company"),
            "object_repr": lambda record: (
                record.de_admin_company_name
                or record.de_delivery_company
                or f"Shipping policy #{record.id}"
            ),
            "restore": False,
        },
        {
            "model": User_Point,
            "label": "회원 포인트",
            "search_fields": ("po_content", "po_rel_action", "po_rel_table"),
            "object_repr": lambda record: " · ".join(
                part for part in (str(record.user_id or ""), record.po_content or "") if part
            ),
            "restore": False,
        },
        {
            "model": Config,
            "label": "사이트 설정",
            "search_fields": ("name",),
            "object_repr": lambda record: record.name,
            "restore": True,
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
        return AUDIT_ACTION_LABELS["+"]
    if record.history_type == "-":
        return AUDIT_ACTION_LABELS["-"]
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


def _csv_safe(value):
    """Prevent spreadsheet formula injection in exported audit values."""

    text = str(value)
    if text.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def _audit_history_rows(
    specs,
    *,
    selected_model,
    selected_action,
    selected_user,
    selected_query,
    date_from,
    date_to,
):
    """Return the common columns of the filtered history tables as one ordered queryset.

    Each model has its own history table and its own search fields, so filters are applied per
    model first. ``union(all=True)`` then gives the whole audit log one global ordering instead
    of truncating each model to a fixed number of rows.
    """

    querysets = []
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
        querysets.append(
            queryset.order_by().values(
                model_label=Value(model._meta.label_lower, output_field=CharField()),
                audit_history_id=F("history_id"),
                audit_history_date=F("history_date"),
                audit_history_type=F("history_type"),
            )
        )

    if not querysets:
        return None
    if len(querysets) == 1:
        return querysets[0].order_by("-audit_history_date", "-audit_history_id")
    return querysets[0].union(*querysets[1:], all=True).order_by(
        "-audit_history_date", "-audit_history_id"
    )


def _audit_entries_from_rows(rows, specs_by_label):
    """Load the real historical rows for the page/export window and build display entries."""

    ids_by_label = {}
    for row in rows:
        ids_by_label.setdefault(row["model_label"], []).append(row["audit_history_id"])

    records_by_label = {}
    for label, history_ids in ids_by_label.items():
        spec = specs_by_label.get(label)
        if spec is None:
            continue
        records = {}
        # SQLite's parameter limit is below 1,000; keep the IN lists chunked for it too.
        for offset in range(0, len(history_ids), 500):
            chunk = history_ids[offset : offset + 500]
            for record in spec["model"].history.filter(history_id__in=chunk).select_related("history_user"):
                records[record.history_id] = record
        records_by_label[label] = records

    entries = []
    for row in rows:
        spec = specs_by_label.get(row["model_label"])
        record = records_by_label.get(row["model_label"], {}).get(row["audit_history_id"])
        if spec is None or record is None:
            continue
        entries.append(
            {
                "record": record,
                "model": spec["model"],
                "model_label": spec["label"],
                "object_label": spec["object_repr"](record) or "-",
                "action": record.history_type,
                "action_label": AUDIT_ACTION_LABELS.get(record.history_type, record.history_type),
                "can_restore": bool(spec.get("restore")),
                "user": getattr(record.history_user, "username", "") or _("System"),
                "history_date": record.history_date,
                "url": _history_url(spec["model"], record),
            }
        )
    return entries


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
    specs_by_label = {spec["model"]._meta.label_lower: spec for spec in specs}
    selected_model = (request.GET.get("model") or "").strip()
    selected_action = (request.GET.get("action") or "").strip()
    selected_user = (request.GET.get("user") or "").strip()
    selected_query = (request.GET.get("q") or "").strip()
    date_from = parse_date(request.GET.get("date_from") or "")
    date_to = parse_date(request.GET.get("date_to") or "")

    rows = _audit_history_rows(
        specs,
        selected_model=selected_model,
        selected_action=selected_action,
        selected_user=selected_user,
        selected_query=selected_query,
        date_from=date_from,
        date_to=date_to,
    )

    if (request.GET.get("export") or "").lower() == "csv":
        total = rows.count() if rows is not None else 0
        if total > AUDIT_EXPORT_LIMIT:
            return HttpResponseBadRequest(
                _("Too many audit rows to export; narrow the filters (limit: %(limit)s).")
                % {"limit": AUDIT_EXPORT_LIMIT}
            )
        export_rows = list(rows[:AUDIT_EXPORT_LIMIT]) if rows is not None else []
        entries = _audit_entries_from_rows(export_rows, specs_by_label)
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="audit-log.csv"'
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(["시각", "사용자", "모델", "대상", "작업", "변경 내용", "이력 URL"])
        for entry in entries:
            writer.writerow(
                [
                    timezone.localtime(entry["history_date"]).strftime("%Y-%m-%d %H:%M:%S"),
                    _csv_safe(entry["user"]),
                    _csv_safe(entry["model_label"]),
                    _csv_safe(entry["object_label"]),
                    _csv_safe(entry["action_label"]),
                    _csv_safe(_change_summary(entry["record"])),
                    _csv_safe(request.build_absolute_uri(entry["url"]) if entry["url"] else ""),
                ]
            )
        return response

    paginator = Paginator(rows if rows is not None else [], AUDIT_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    entries = _audit_entries_from_rows(list(page_obj.object_list), specs_by_label)
    for entry in entries:
        entry["changes"] = _change_summary(entry["record"])

    query_params = request.GET.copy()
    query_params.pop("page", None)
    query_params.pop("export", None)
    context = {
        **admin.site.each_context(request),
        "title": _("Audit log"),
        "opts": None,
        "specs": specs,
        "entries": entries,
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
        "action_choices": AUDIT_ACTION_CHOICES,
        "audit_export_limit": AUDIT_EXPORT_LIMIT,
    }
    return TemplateResponse(request, "admin/core/audit_log.html", context)
