"""The 결제대행사 / 토스페이먼츠 키 / 결제 테스트 / 에스크로 part of the shop settings page
(youngcart adm/shop_admin/configform.php 결제설정 and configformupdate.php).

Secret keys are write-only: the inputs never render a stored value, the page only says
등록됨/미등록, and a key is replaced by typing a new one or removed with its 삭제 box. Client
keys show masked (prefix and last four characters). When the server environment sets the keys
(SHOP_TOSS_CLIENT_KEY / SHOP_TOSS_SECRET_KEY) or the provider (SHOP_PAYMENT_PROVIDER), the
matching inputs are disabled: the environment wins."""

from django import forms
from django.urls import reverse
from django.views.decorators.debug import sensitive_variables

from gnu_jango.config.models import Config

from .pg_settings import (
    CARD_TEST_FIELD,
    ESCROW_FIELD,
    KEY_KINDS,
    KEY_MODES,
    MODE_LABELS,
    PG_SERVICE_CHOICES,
    PG_SERVICE_FIELD,
    TOSS_KEY_ROWS,
    UNSUPPORTED_PG_SERVICES,
    admin_keys,
    admin_keys_enabled,
    admin_pg_service,
    unreadable_key_rows,
    card_test_enabled,
    env_keys_set,
    env_payment_provider,
    escrow_enabled,
    key_family,
    key_label,
    key_prefix_error,
    mask_key,
    seal_key,
)

ENV_LOCKED_HELP = "서버 환경 변수로 설정됨 (여기서 변경 불가)"
ADMIN_KEYS_OFF_HELP = "이 서버는 관리자 화면의 키를 사용하지 않습니다 (SHOP_TOSS_ADMIN_KEYS_ENABLED=False)."
CARD_TEST_CHOICES = (("0", "실결제"), ("1", "테스트결제"))
ESCROW_CHOICES = (("0", "일반결제 사용"), ("1", "에스크로결제 사용"))
WEBHOOK_PATH_NAME = "api_v1:shop-payment-toss-vbank-webhook"

KEY_HELP = {
    "client": "토스페이먼츠 상점관리자 → 개발자센터 → API 키 → 클라이언트 키입니다. 바꿀 때만 입력하세요.",
    "secret": "토스페이먼츠 상점관리자 → 개발자센터 → API 키 → 시크릿 키입니다. 저장한 값은 다시 표시하지 않으며, 바꿀 때만 입력하세요.",
}

# youngcart 결제설정 rows this shop does not offer: shown as text so the page mirrors youngcart
UNSUPPORTED_ROWS = (
    (
        f"{' · '.join(UNSUPPORTED_PG_SERVICES)} 키",
        "지원하지 않음 — 주문 결제는 토스페이먼츠로만 시작합니다. 다른 PG의 사이트 코드·키는 입력하지 않습니다.",
    ),
    (
        "신용카드 무이자할부 (KCP만 해당)",
        "지원하지 않음 — 토스페이먼츠의 무이자 할부는 토스페이먼츠 상점관리자에서 설정한 대로 적용됩니다.",
    ),
    (
        "네이버페이 결제형",
        "지원하지 않음 — 네이버페이 가맹점 ID·인증키와 결제테스트 설정은 제공하지 않습니다.",
    ),
)


def pg_field_order():
    """The 결제대행사 section's fields in youngcart order (keys, 결제 테스트, 에스크로)."""
    names = [PG_SERVICE_FIELD]
    for mode in KEY_MODES:
        for kind in KEY_KINDS:
            name = TOSS_KEY_ROWS[(mode, kind)]
            names += [name, f"{name}_delete"]
    return [*names, CARD_TEST_FIELD, ESCROW_FIELD]


@sensitive_variables("stored", "current", "rows")
def add_pg_fields(form, rows):
    """Add the PG fields to ``form`` with their saved values (``rows``: the stored Config rows)."""
    provider_locked = bool(env_payment_provider())
    form.fields[PG_SERVICE_FIELD] = forms.ChoiceField(
        label="결제대행사",
        required=False,
        choices=PG_SERVICE_CHOICES,
        widget=forms.RadioSelect,
        disabled=provider_locked,
        help_text=(
            f"{ENV_LOCKED_HELP} · SHOP_PAYMENT_PROVIDER"
            if provider_locked
            else "쇼핑몰에서 사용할 결제대행사를 선택합니다. 사용안함이면 무통장입금만 받습니다. "
            f"영카트의 {' · '.join(UNSUPPORTED_PG_SERVICES)}는 지원하지 않습니다."
        ),
    )
    form.initial[PG_SERVICE_FIELD] = admin_pg_service(rows)
    form.fields[CARD_TEST_FIELD] = forms.ChoiceField(
        label="결제 테스트",
        required=False,
        choices=CARD_TEST_CHOICES,
        widget=forms.RadioSelect,
        help_text="테스트결제는 테스트 키 쌍으로, 실결제는 실결제 키 쌍으로 결제합니다. 결제단위 최소 1,000원. "
        "주문은 결제할 때의 모드를 기억해 승인 확인·취소·환불을 그 모드의 키로 요청하므로, 모드를 바꾼 뒤에도 "
        "이전 모드의 키 쌍을 지우지 마세요. "
        "테스트 결제건은 토스페이먼츠 상점관리자 상단의 '테스트 모드'에서 볼 수 있습니다."
        + (" 서버 환경 변수 키가 있으면 그 키를 사용합니다." if env_keys_set() else ""),
    )
    form.initial[CARD_TEST_FIELD] = "1" if card_test_enabled(rows) else "0"
    form.fields[ESCROW_FIELD] = forms.ChoiceField(
        label="에스크로 사용",
        required=False,
        choices=ESCROW_CHOICES,
        widget=forms.RadioSelect,
        help_text="에스크로 결제를 사용하려면 토스페이먼츠 상점관리자에서 에스크로 서비스를 먼저 신청하세요. "
        "계좌이체·가상계좌 결제에 적용되며, 배송 정보는 토스페이먼츠 상점관리자에서 직접 등록해야 합니다 "
        "(배송 처리 시 주문 변경 이력에 안내를 남깁니다).",
    )
    form.initial[ESCROW_FIELD] = "1" if escrow_enabled(rows) else "0"

    stored = admin_keys(rows)
    unreadable = set(unreadable_key_rows(rows))
    env_locked = env_keys_set()
    keys_off = not admin_keys_enabled()
    for mode in KEY_MODES:
        for kind in KEY_KINDS:
            name = TOSS_KEY_ROWS[(mode, kind)]
            current = stored[(mode, kind)]
            if env_locked:
                state, help_text = ENV_LOCKED_HELP, ENV_LOCKED_HELP
            elif keys_off:
                state, help_text = "사용 안 함", ADMIN_KEYS_OFF_HELP
            else:
                registered = (f"등록됨 ({mask_key(current)})" if kind == "client" else "등록됨") if current else "미등록"
                state, help_text = registered, f"현재: {registered}. {KEY_HELP[kind]}"
            if (mode, kind) in unreadable and not (env_locked or keys_off):
                state = "저장된 키를 읽을 수 없음 - 다시 입력하세요"
                help_text = f"{state}. {KEY_HELP[kind]}"
            # never echoed back, not even after a validation error (a secret may be pasted here)
            widget = forms.PasswordInput(
                render_value=False,
                attrs={"autocomplete": "new-password", "spellcheck": "false", "placeholder": state},
            )
            form.fields[name] = forms.CharField(
                label=f"토스페이먼츠 {key_label(mode, kind)}",
                required=False,
                max_length=200,
                widget=widget,
                disabled=env_locked or keys_off,
                help_text=help_text,
            )
            form.initial[name] = ""
            form.fields[f"{name}_delete"] = forms.BooleanField(
                label=f"{key_label(mode, kind)} 삭제",
                required=False,
                disabled=env_locked or keys_off or not current,
            )
    form.stored_toss_keys = stored


@sensitive_variables("cleaned", "value", "result", "client", "secret", "stored")
def clean_pg_fields(form, cleaned):
    """Check each new key's prefix and that a pair stays of one kind (ck/sk or gck/gsk)."""
    stored = getattr(form, "stored_toss_keys", {})
    for mode in KEY_MODES:
        result = {}
        changed = invalid = False
        for kind in KEY_KINDS:
            name = TOSS_KEY_ROWS[(mode, kind)]
            value = str(cleaned.get(name) or "").strip()
            cleaned[name] = value
            if value:
                error = key_prefix_error(mode, kind, value)
                if error:
                    form.add_error(name, error)
                    invalid = True
                result[kind] = value
                changed = True
            elif cleaned.get(f"{name}_delete"):
                result[kind] = ""
                changed = True
            else:
                result[kind] = stored.get((mode, kind), "")
        client, secret = result["client"], result["secret"]
        if changed and not invalid and client and secret and key_family(client) != key_family(secret):
            form.add_error(
                TOSS_KEY_ROWS[(mode, "client")],
                f"{MODE_LABELS[mode]} 키는 클라이언트 키와 시크릿 키를 같은 종류"
                "(API 개별 연동 키 ck/sk 또는 결제위젯 연동 키 gck/gsk)로 등록하세요.",
            )


@sensitive_variables("cleaned", "value")
def pg_changes(form):
    """(Config rows to write, Config rows to delete, the change descriptions without values)."""
    cleaned = form.cleaned_data
    values, deleted, changes = {}, [], []
    for name, choices, label in (
        (PG_SERVICE_FIELD, PG_SERVICE_CHOICES, "결제대행사"),
        (CARD_TEST_FIELD, CARD_TEST_CHOICES, "결제 테스트"),
        (ESCROW_FIELD, ESCROW_CHOICES, "에스크로 사용"),
    ):
        value = str(cleaned.get(name) or "")
        # a blank (missing) choice keeps what is saved; a disabled field keeps the initial value
        if form.fields[name].disabled or value not in dict(choices) or value == form.initial.get(name):
            continue
        values[name] = value
        changes.append(f"{label}: {dict(choices)[value]}")
    for mode in KEY_MODES:
        for kind in KEY_KINDS:
            name = TOSS_KEY_ROWS[(mode, kind)]
            if form.fields[name].disabled:
                continue
            value = cleaned.get(name) or ""
            if value:
                values[name] = seal_key(mode, kind, value)
                changes.append(f"{key_label(mode, kind)} 등록")
            elif cleaned.get(f"{name}_delete") and form.stored_toss_keys.get((mode, kind)):
                deleted.append(name)
                changes.append(f"{key_label(mode, kind)} 삭제")
    return values, deleted, changes


def save_pg_changes(form):
    values, deleted, changes = pg_changes(form)
    for name, value in values.items():
        Config.objects.update_or_create(name=name, defaults={"value": value})
    if deleted:
        Config.objects.filter(name__in=deleted).delete()
    return changes


def webhook_url(request):
    return request.build_absolute_uri(reverse(WEBHOOK_PATH_NAME))


def pg_status(toss, provider, rows):
    """What the 결제 연결 상태 card shows about the keys and modes (never a key value), and the
    warnings for settings that contradict each other."""
    card_test = card_test_enabled(rows)
    source_labels = {"env": "서버 환경 변수", "admin": "관리자 설정", "none": "미등록"}
    effective_mode = {"test": "테스트결제", "live": "실결제"}.get(toss["key_status"], "결제 불가")
    warnings = []
    if admin_keys_enabled() and unreadable_key_rows(rows):
        warnings.append("저장된 결제 키를 읽을 수 없습니다 — SECRET_KEY 변경 여부를 확인하고 키를 다시 입력하세요.")
    if toss["source"] == "env" and toss["enabled"] and toss["is_test_mode"] != card_test:
        warnings.append(
            f"결제 테스트가 '{'테스트결제' if card_test else '실결제'}'로 설정되어 있지만 서버 환경 변수의 키는 "
            f"{'테스트' if toss['is_test_mode'] else '실결제'} 키입니다. 환경 변수 키로 결제합니다."
        )
    other_mode = "live" if toss["selected_mode"] == "test" else "test"
    other_pair_saved = toss["source"] == "none" and admin_keys_enabled() and any(
        admin_keys(rows)[(other_mode, kind)] for kind in KEY_KINDS
    )
    if (toss["source"] == "admin" and not toss["enabled"]) or other_pair_saved:
        warnings.append(
            f"결제 테스트가 '{'테스트결제' if card_test else '실결제'}'이므로 "
            f"{MODE_LABELS[toss['selected_mode']]} 키 쌍(클라이언트 키·시크릿 키)을 모두 등록해야 결제할 수 있습니다."
        )
    if toss["enabled"] and key_family(toss["client_key"]) == "widget":
        warnings.append(
            "결제위젯 연동 키(gck)가 등록되어 있습니다. 이 쇼핑몰은 결제창(API 개별 연동)을 사용하므로 "
            "API 개별 연동 키(ck/sk)를 등록하세요."
        )
    if toss["enabled"] and provider == "bank" and not env_payment_provider() and admin_pg_service(rows) != "toss":
        warnings.append("결제대행사가 '사용안함'이라 토스페이먼츠 키가 있어도 온라인 결제를 받지 않습니다.")
    return {
        "source": toss["source"],
        "source_label": source_labels.get(toss["source"], "미등록"),
        "card_test_label": "테스트결제" if card_test else "실결제",
        "effective_mode_label": effective_mode,
        "is_test_mode": toss["is_test_mode"],
        "escrow_enabled": escrow_enabled(rows),
        "provider_locked": bool(env_payment_provider()),
        "warnings": warnings,
    }
