"""Non-secret checkout switches shared by the admin and the order API."""

from gnu_jango.config.models import Config


PAYMENT_OPTION_FIELDS = {
    "card": "de_card_use",
    "vbank": "de_vbank_use",
    "iche": "de_iche_use",
    "hp": "de_hp_use",
    "easy_pay": "de_easy_pay_use",
}

CASH_RECEIPT_ENABLED_FIELD = "de_taxsave_use"
CASH_RECEIPT_TYPES_FIELD = "de_taxsave_types"
CASH_RECEIPT_METHOD_TYPES = {
    "bank": "account",
    "vbank": "vbank",
    "iche": "transfer",
}


def config_flag(value):
    return str(value or "").strip().lower() not in {"", "0", "false", "no", "off"}


def online_payment_preferences():
    values = dict(
        Config.objects.filter(name__in=PAYMENT_OPTION_FIELDS.values()).values_list("name", "value")
    )
    # Existing installations keep their gateway-supported methods until an
    # administrator explicitly turns them off. Keys are still required.
    return {method: config_flag(values.get(name, "1")) for method, name in PAYMENT_OPTION_FIELDS.items()}


def cash_receipt_preferences():
    values = dict(
        Config.objects.filter(name__in=(CASH_RECEIPT_ENABLED_FIELD, CASH_RECEIPT_TYPES_FIELD))
        .values_list("name", "value")
    )
    # Preserve the current checkout behavior on existing installations that
    # have never stored these newly surfaced settings.
    enabled = config_flag(values.get(CASH_RECEIPT_ENABLED_FIELD, "1"))
    allowed_types = {
        value.strip()
        for value in str(values.get(CASH_RECEIPT_TYPES_FIELD, "account,vbank,transfer") or "").split(",")
        if value.strip()
    }
    return {
        "enabled": enabled,
        "methods": {
            method: enabled and receipt_type in allowed_types
            for method, receipt_type in CASH_RECEIPT_METHOD_TYPES.items()
        },
    }


def cash_receipt_method_enabled(settle_case):
    normalized = str(settle_case or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    aliases = {
        "bank": "bank",
        "무통장": "bank",
        "무통장입금": "bank",
        "vbank": "vbank",
        "virtualaccount": "vbank",
        "가상계좌": "vbank",
        "iche": "iche",
        "transfer": "iche",
        "계좌이체": "iche",
        "실시간계좌이체": "iche",
    }
    method = aliases.get(normalized)
    return bool(method and cash_receipt_preferences()["methods"][method])


def online_payment_method_enabled(settle_case):
    normalized = str(settle_case or "").strip().lower().replace(" ", "").replace("_", "").replace("-", "")
    if normalized in {"", "bank", "무통장", "무통장입금"}:
        return True  # Account/use checks are enforced separately for bank transfer.
    aliases = {
        "card": ("card", "creditcard", "카드", "신용카드"),
        "vbank": ("vbank", "virtualaccount", "가상계좌"),
        "iche": ("iche", "transfer", "계좌이체", "실시간계좌이체"),
        "hp": ("hp", "mobilephone", "휴대폰", "휴대폰결제"),
        "easy_pay": ("easypay", "tosspay", "간편결제", "kakaopay", "naverpay", "samsungpay", "카카오페이", "네이버페이", "삼성페이"),
    }
    method = next((name for name, names in aliases.items() if normalized in names), None)
    # Unknown labels must not bypass an administrator's disabled method.
    return method is not None and online_payment_preferences()[method]
