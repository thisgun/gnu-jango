"""Shared display helpers for the admin modules.

These were previously copy-pasted across the shop/users/bbs admin modules and
the admin_ops template tags. Only helpers that were byte-for-byte identical (or
a safe superset, e.g. the defensive ``format_number``) are consolidated here.
Helpers whose behaviour legitimately differs between modules — notably
``datetime_value`` (shop returns ``""`` for CSV cells, users/bbs return ``"-"``
for display) — are intentionally left local to each module.
"""

from django.db.models import Sum
from django.utils.html import format_html, format_html_join


def format_number(value):
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "0"


def money_sum(queryset, field):
    return queryset.aggregate(value=Sum(field))["value"] or 0


def compact_text(*values, limit=None):
    """Join the non-empty values with spaces; ``limit`` shortens the result with an ellipsis."""
    text = " ".join(str(value).strip() for value in values if str(value or "").strip())
    if limit is not None and len(text) > limit:
        text = (text[: max(limit - 1, 0)].rstrip() + "…")[: max(limit, 0)]
    return text or "-"


def badge(label, tone="neutral"):
    return format_html('<span class="g5-admin-badge g5-admin-badge-{}">{}</span>', tone, label)


def money_html(value, danger=False):
    css = "g5-admin-money g5-admin-money-danger" if danger else "g5-admin-money"
    return format_html('<span class="{}">{}</span>', css, format_number(value))


def snapshot_panel(title, state, tone, description, cards):
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


def fieldsets_without(fieldsets, *field_names):
    excluded = set(field_names)
    cleaned = []
    for title, options in fieldsets:
        options = dict(options)
        fields = []
        for field in options.get("fields", ()):
            if isinstance(field, (list, tuple)):
                grouped = tuple(item for item in field if item not in excluded)
                if len(grouped) == 1:
                    fields.append(grouped[0])
                elif grouped:
                    fields.append(grouped)
            elif field not in excluded:
                fields.append(field)
        options["fields"] = tuple(fields)
        cleaned.append((title, options))
    return tuple(cleaned)
