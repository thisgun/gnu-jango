"""The 배송조회 (Delivery Tracker) part of the shop settings page.

Both keys are write-only, like the PG secret keys (admin_pg_settings.py): the inputs never
render a stored value, the page says 등록됨 (the Client ID with its last four characters) or
미등록, a key is replaced by typing a new one and removed with its 삭제 box. The two switches
are ordinary shop options (shop_options.TRACKING_OPTIONS) saved with the rest of the form."""

from django import forms
from django.views.decorators.debug import sensitive_variables

from gnu_jango.config.models import Config

from .delivery_tracking_settings import (
    COMPLETE_FIELD,
    ENABLED_FIELD,
    KEY_KINDS,
    KEY_LABELS,
    KEY_ROWS,
    admin_keys,
    callback_base_url,
    key_error,
    mask_key,
    polling_job_enabled,
    seal_key,
    unreadable_keys,
)

KEY_HELP = {
    "client_id": "Delivery Tracker 콘솔(console.tracker.delivery) → 프로젝트 → API 키의 Client ID입니다. 바꿀 때만 입력하세요.",
    "client_secret": "같은 화면의 Client Secret입니다. 저장한 값은 다시 표시하지 않으며, 바꿀 때만 입력하세요.",
}


def tracking_field_order():
    names = [ENABLED_FIELD]
    for kind in KEY_KINDS:
        names += [KEY_ROWS[kind], f"{KEY_ROWS[kind]}_delete"]
    return [*names, COMPLETE_FIELD]


def tracking_status_text(stored):
    """One line on how tracking would run with the saved keys: never a key value."""
    parts = []
    if not (stored["client_id"] and stored["client_secret"]):
        parts.append("Client ID와 Client Secret을 모두 등록해야 조회합니다")
    if polling_job_enabled():
        parts.append("자동 조회: 예약 작업(track_shipments)이 5분마다 조회 시점이 된 주문을 확인합니다")
    else:
        parts.append(
            "자동 조회 꺼짐: 서버의 SHOP_DELIVERY_TRACKING_JOB이 꺼져 있어 주문 화면의 '지금 조회'로만 조회합니다"
        )
    if callback_base_url():
        parts.append("웹훅: 배송 상태가 바뀌면 Delivery Tracker가 알려 줍니다")
    else:
        parts.append("웹훅 미사용: https 공개 주소(SHOP_DELIVERY_TRACKER_CALLBACK_BASE_URL)가 없습니다")
    return "현재 상태 - " + " · ".join(parts) + "."


@sensitive_variables("stored", "current", "rows")
def add_tracking_fields(form, rows):
    """Add the key fields to ``form`` (``rows``: the stored key Config rows) and the current
    state to the 배송조회 사용 help text."""
    stored = admin_keys(rows)
    unreadable = set(unreadable_keys(rows))
    for kind in KEY_KINDS:
        name = KEY_ROWS[kind]
        current = stored[kind]
        if kind in unreadable:
            state = "저장된 키를 읽을 수 없음 - 다시 입력하세요"
        elif current:
            state = f"등록됨 ({mask_key(current)})" if kind == "client_id" else "등록됨"
        else:
            state = "미등록"
        # never echoed back, not even after a validation error (a secret may be pasted here)
        form.fields[name] = forms.CharField(
            label=f"Delivery Tracker {KEY_LABELS[kind]}",
            required=False,
            max_length=200,
            widget=forms.PasswordInput(
                render_value=False,
                attrs={"autocomplete": "new-password", "spellcheck": "false", "placeholder": state},
            ),
            help_text=f"현재: {state}. {KEY_HELP[kind]}",
        )
        form.initial[name] = ""
        form.fields[f"{name}_delete"] = forms.BooleanField(
            label=f"{KEY_LABELS[kind]} 삭제", required=False, disabled=not current
        )
    if ENABLED_FIELD in form.fields:
        field = form.fields[ENABLED_FIELD]
        field.help_text = f"{field.help_text} {tracking_status_text(stored)}"
    form.stored_tracking_keys = stored


@sensitive_variables("cleaned", "value")
def clean_tracking_fields(form, cleaned):
    for kind in KEY_KINDS:
        name = KEY_ROWS[kind]
        value = str(cleaned.get(name) or "").strip()
        cleaned[name] = value
        error = key_error(kind, value) if value else ""
        if error:
            form.add_error(name, error)


@sensitive_variables("cleaned", "value")
def tracking_changes(form):
    """(Config rows to write, Config rows to delete, the change descriptions without values)."""
    cleaned = form.cleaned_data
    stored = getattr(form, "stored_tracking_keys", {})
    values, deleted, changes = {}, [], []
    for kind in KEY_KINDS:
        name = KEY_ROWS[kind]
        value = cleaned.get(name) or ""
        if value:
            values[name] = seal_key(kind, value)
            changes.append(f"배송조회 {KEY_LABELS[kind]} 등록")
        elif cleaned.get(f"{name}_delete") and stored.get(kind):
            deleted.append(name)
            changes.append(f"배송조회 {KEY_LABELS[kind]} 삭제")
    return values, deleted, changes


def save_tracking_changes(form):
    values, deleted, changes = tracking_changes(form)
    for name, value in values.items():
        Config.objects.update_or_create(name=name, defaults={"value": value})
    if deleted:
        Config.objects.filter(name__in=deleted).delete()
    return changes
