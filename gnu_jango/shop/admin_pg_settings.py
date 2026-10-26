"""The 결제대행사 / PG 키 / 결제 테스트 / 에스크로 part of the shop settings page
(youngcart adm/shop_admin/configform.php 결제설정 and configformupdate.php).

Secret keys are write-only: the inputs never render a stored value, the page only says
등록됨/미등록, and a key is replaced by typing a new one or removed with its 삭제 box. Client
keys show masked (prefix and last four characters); a NICEPAY MID is shown because it is the
public merchant identifier, while its MerchantKey is never echoed. When the server environment
sets the keys or the provider (SHOP_PAYMENT_PROVIDER), the matching inputs are disabled: the
environment wins."""

from django import forms
from django.conf import settings
from django.urls import reverse
from django.views.decorators.debug import sensitive_variables

from gnu_jango.config.models import Config

from .pg_settings import (
    CARD_TEST_FIELD,
    ESCROW_FIELD,
    KEY_KINDS,
    KEY_MODES,
    MODE_LABELS,
    NICEPAY_KEY_ROWS,
    PG_SERVICE_CHOICES,
    PG_SERVICE_FIELD,
    PG_SERVICE_NICEPAY,
    TOSS_KEY_ROWS,
    UNSUPPORTED_PG_SERVICES,
    admin_keys,
    admin_keys_enabled,
    admin_nicepay_values,
    admin_pg_service,
    unreadable_key_rows,
    card_test_enabled,
    env_keys_set,
    env_nicepay_keys,
    env_nicepay_keys_set,
    env_payment_provider,
    escrow_enabled,
    key_family,
    key_label,
    key_prefix_error,
    mask_key,
    nicepay_admin_keys_enabled,
    nicepay_seal_context,
    nicepay_unreadable_key_rows,
    nicepay_value_error,
    seal_key,
    seal_nicepay_value,
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
        for kind in ("mid", "merchant_key"):
            name = NICEPAY_KEY_ROWS[(mode, kind)]
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
            f"NICEPAY는 MID·MerchantKey 기반 인증결제 상품만 지원하며, 영카트의 "
            f"{' · '.join(UNSUPPORTED_PG_SERVICES)}는 지원하지 않습니다."
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

    nicepay_stored = admin_nicepay_values(rows)
    nicepay_unreadable = set(nicepay_unreadable_key_rows(rows))
    nicepay_keys_off = not nicepay_admin_keys_enabled()
    for mode in KEY_MODES:
        env_mid, env_merchant_key = env_nicepay_keys(mode)
        nicepay_env_locked = bool(env_mid or env_merchant_key)
        for kind in ("mid", "merchant_key"):
            name = NICEPAY_KEY_ROWS[(mode, kind)]
            current = nicepay_stored[mode][kind]
            label = "MID" if kind == "mid" else "MerchantKey"
            if nicepay_env_locked:
                state = ENV_LOCKED_HELP
                help_text = f"{ENV_LOCKED_HELP} · SHOP_NICEPAY_{'TEST_' if mode == 'test' else ''}{label.upper()}"
                displayed = ""
            elif nicepay_keys_off:
                state, help_text, displayed = "사용 안 함", "이 서버는 관리자 화면의 NICEPAY 키를 사용하지 않습니다.", ""
            else:
                registered = current if kind == "mid" and current else ("등록됨" if current else "미등록")
                state = registered
                help_text = (
                    f"현재: {registered}. NICEPAY 상점관리자에서 발급한 {label}입니다. "
                    "MerchantKey는 저장 후 다시 표시하지 않습니다."
                )
                displayed = current if kind == "mid" else ""
            if mode in nicepay_unreadable and kind == "merchant_key" and not (nicepay_env_locked or nicepay_keys_off):
                state = "저장된 MerchantKey를 읽을 수 없음 - 다시 입력하세요"
                help_text = state
                displayed = ""
            widget = (
                forms.TextInput(attrs={"autocomplete": "off", "spellcheck": "false", "placeholder": state})
                if kind == "mid"
                else forms.PasswordInput(
                    render_value=False,
                    attrs={"autocomplete": "new-password", "spellcheck": "false", "placeholder": state},
                )
            )
            form.fields[name] = forms.CharField(
                label=f"NICEPAY {MODE_LABELS[mode]} {label}",
                required=False,
                max_length=200 if kind == "merchant_key" else 10,
                widget=widget,
                disabled=nicepay_env_locked or nicepay_keys_off,
                help_text=help_text,
            )
            form.initial[name] = displayed
            form.fields[f"{name}_delete"] = forms.BooleanField(
                label=f"NICEPAY {MODE_LABELS[mode]} {label} 삭제",
                required=False,
                disabled=nicepay_env_locked or nicepay_keys_off or not current,
            )
    form.stored_nicepay_keys = nicepay_stored


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

    stored_nicepay = getattr(form, "stored_nicepay_keys", {})
    for mode in KEY_MODES:
        result = dict(stored_nicepay.get(mode) or {"mid": "", "merchant_key": ""})
        changed = invalid = False
        for kind in ("mid", "merchant_key"):
            name = NICEPAY_KEY_ROWS[(mode, kind)]
            value = str(cleaned.get(name) or "").strip()
            cleaned[name] = value
            if value and value != result.get(kind, ""):
                error = nicepay_value_error(mode, kind, value)
                if error:
                    form.add_error(name, error)
                    invalid = True
                result[kind] = value
                changed = True
            elif cleaned.get(f"{name}_delete"):
                result[kind] = ""
                changed = True
        # One value may be removed on its own; the status card flags the incomplete pair instead
        # of making the delete box unusable. A newly entered value is still format-checked above.


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
    for mode in KEY_MODES:
        for kind in ("mid", "merchant_key"):
            name = NICEPAY_KEY_ROWS[(mode, kind)]
            if form.fields[name].disabled:
                continue
            value = str(cleaned.get(name) or "").strip()
            stored = (form.stored_nicepay_keys.get(mode) or {}).get(kind, "")
            label = f"NICEPAY {MODE_LABELS[mode]} {'MID' if kind == 'mid' else 'MerchantKey'}"
            if value and value != stored:
                values[name] = seal_nicepay_value(mode, kind, value) if kind == "merchant_key" else value
                changes.append(f"{label} 등록")
            elif cleaned.get(f"{name}_delete") and stored:
                deleted.append(name)
                changes.append(f"{label} 삭제")
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


def nicepay_notify_url(request):
    return request.build_absolute_uri(reverse("api_v1:shop-payment-nicepay-vbank-notification"))


def nicepay_return_url_help(request):
    configured = str(getattr(settings, "SHOP_NICEPAY_RETURN_URL", "") or "").strip()
    return configured or request.build_absolute_uri(reverse("api_v1:shop-payment-nicepay-return"))


def pg_status(toss, provider, rows, nicepay=None):
    """The 결제 연결 상태 card: presence/mode only, never a key value, plus contradictions."""
    nicepay = nicepay or {}
    card_test = card_test_enabled(rows)
    source_labels = {"env": "서버 환경 변수", "admin": "관리자 설정", "none": "미등록"}
    active = nicepay if provider == "nicepay" else toss
    active_name = "NICEPAY" if provider == "nicepay" else "토스페이먼츠"
    key_status = active.get("key_status", "missing")
    enabled = bool(active.get("enabled"))
    effective_mode = {"test": "테스트결제", "live": "실결제"}.get(key_status, "결제 불가")
    warnings = []
    if admin_keys_enabled() and unreadable_key_rows(rows):
        warnings.append("저장된 결제 키를 읽을 수 없습니다 — SECRET_KEY 변경 여부를 확인하고 키를 다시 입력하세요.")
    if nicepay_admin_keys_enabled() and nicepay_unreadable_key_rows(rows):
        warnings.append("저장된 NICEPAY MerchantKey를 읽을 수 없습니다 — SECRET_KEY 변경 여부를 확인하고 다시 입력하세요.")
    source = active.get("source", "none")
    if source == "env" and enabled and active.get("is_test_mode") != card_test:
        warnings.append(
            f"결제 테스트가 '{'테스트결제' if card_test else '실결제'}'로 설정되어 있지만 "
            f"서버 환경 변수의 키는 {'테스트' if active.get('is_test_mode') else '실결제'} 키입니다. "
            "환경 변수 키로 결제합니다."
        )
    if not enabled and source != "env":
        if provider == "nicepay":
            warnings.append(
                f"결제 테스트가 '{'테스트결제' if card_test else '실결제'}'이므로 NICEPAY "
                f"{MODE_LABELS.get(active.get('selected_mode'), '')} MID와 MerchantKey를 모두 등록해야 결제할 수 있습니다."
            )
        else:
            warnings.append(
                f"결제 테스트가 '{'테스트결제' if card_test else '실결제'}'이므로 "
                f"{MODE_LABELS.get(active.get('selected_mode'), '')} 키 쌍(클라이언트 키·시크릿 키)을 모두 등록해야 결제할 수 있습니다."
            )
    if provider == "nicepay" and enabled:
        if not getattr(settings, "SHOP_NICEPAY_RETURN_URL", ""):
            warnings.append(
                "NICEPAY 모바일 복귀 URL(SHOP_NICEPAY_RETURN_URL)이 비어 있습니다. "
                "운영에서는 가맹점 서버의 HTTPS 복귀 URL을 등록해야 합니다."
            )
        if not nicepay_success_url_for_admin():
            warnings.append(
                "NICEPAY 결제 완료 후 이동할 프런트 URL(SHOP_NICEPAY_SUCCESS_URL 또는 "
                "SHOP_NICEPAY_FRONTEND_URL)이 비어 있습니다."
            )
    if toss.get("enabled") and key_family(toss.get("client_key", "")) == "widget":
        warnings.append(
            "토스페이먼츠 결제위젯 연동 키(gck)가 등록되어 있습니다. 이 쇼핑몰은 결제창(API 개별 연동)을 "
            "사용하므로 API 개별 연동 키(ck/sk)를 등록하세요."
        )
    if provider == "bank" and not env_payment_provider() and admin_pg_service(rows) != "none":
        warnings.append("결제대행사 '사용안함'이라 저장된 PG 키가 있어도 온라인 결제를 받지 않습니다.")
    return {
        "provider": provider,
        "provider_label": "NICEPAY 인증결제" if provider == "nicepay" else "토스페이먼츠",
        "source": source,
        "source_label": source_labels.get(source, "미등록"),
        "card_test_label": "테스트결제" if card_test else "실결제",
        "effective_mode_label": effective_mode,
        "is_test_mode": bool(active.get("is_test_mode")) if provider == "nicepay" else bool(toss.get("is_test_mode")),
        "mode": {
            "missing": "키 미등록", "incomplete": "키 한 개 누락", "invalid_mid": "MID 형식 확인 필요",
            "invalid_key": "MerchantKey 형식 확인 필요", "invalid_prefix": "키 형식 확인 필요",
            "mode_mismatch": "테스트·실결제 키 혼합", "test": "테스트 키 쌍", "live": "실결제 키 쌍",
        }.get(key_status, key_status),
        "key_status": key_status,
        "enabled": enabled,
        "has_client_key": bool(nicepay.get("mid")) if provider == "nicepay" else bool(toss.get("client_key")),
        "has_secret_key": bool(nicepay.get("has_merchant_key")) if provider == "nicepay" else bool(toss.get("has_secret_key")),
        "vbank_enabled": bool(active.get("vbank_enabled")),
        "native_checkout": (provider == "nicepay" and enabled) or (provider == "toss" and enabled),
        "escrow_enabled": escrow_enabled(rows) and provider == "toss",
        "provider_locked": bool(env_payment_provider()),
        "warnings": warnings,
    }


def nicepay_success_url_for_admin():
    configured = str(getattr(settings, "SHOP_NICEPAY_SUCCESS_URL", "") or "").strip()
    if configured:
        return configured
    frontend = str(getattr(settings, "SHOP_NICEPAY_FRONTEND_URL", "") or "").strip().rstrip("/")
    return f"{frontend}/shop/payment/success" if frontend else ""
