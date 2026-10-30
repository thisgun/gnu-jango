"""Unified shop settings, ordered like youngcart adm/shop_admin/configform.php: 사업자정보,
진열, 결제설정, 배송설정, 기타 설정, SMS 설정. Toss and NICEPAY credentials entered here are
sealed in Config (shop/admin_pg_settings.py); server environment keys still win over them."""

import re

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from gnu_jango.api.page_bootstrap import batch_bootstrap_changes
from gnu_jango.api.shop_payments import (
    check_toss_connection,
    checkout_payment_methods,
    configured_payment_provider,
    payment_adapter_config,
    toss_payment_config,
)
from gnu_jango.config import signals
from gnu_jango.config.models import Config
from gnu_jango.shop.pg_settings import nicepay_payment_config

from .admin_pg_settings import (
    UNSUPPORTED_ROWS,
    add_pg_fields,
    clean_pg_fields,
    nicepay_notify_url,
    nicepay_return_url_help,
    pg_field_order,
    pg_status,
    save_pg_changes,
    webhook_url,
)
from .delivery import delivery_company_form_field
from .models import ShopShippingPolicy
from .payment_options import (
    CASH_RECEIPT_ENABLED_FIELD,
    CASH_RECEIPT_TYPES_FIELD,
    PAYMENT_OPTION_FIELDS,
    cash_receipt_preferences,
    config_flag,
)
from .pg_settings import PG_SETTING_NAMES, TOSS_KEY_ROWS
from .pg_settings import stored_rows as pg_stored_rows
from .settings_sync import sync_shop_phone_from_policy
from .shipping import current_shipping_policy
from .logo_uploads import delete_logo_file, logo_form_fields, store_logo
from .sms import icode as sms_gateway
from .sms.service import reserve_test_send, send_test_message, sms_settings
from .shop_options import (
    COMPANY_OPTIONS,
    HOME_LIST_TYPES,
    LIST_OPTIONS,
    SHOP_CONFIG_OPTIONS,
    SHOP_LOGO_FIELDS,
    SMS_OPTIONS,
    SUBSCRIPTION_OPTIONS,
    shop_logo_urls,
    to_python,
    to_stored,
)


PAYMENT_LABELS = {
    "card": "카드 결제",
    "vbank": "가상계좌",
    "iche": "실시간계좌이체",
    "hp": "휴대폰 결제",
    "easy_pay": "간편결제 (토스페이)",
}

# youngcart configform.php 결제설정 labels and help texts for the checkout switches
PAYMENT_OPTION_LABELS = {
    "card": ("신용카드 결제사용", "주문시 신용카드 결제를 가능하게 할것인지를 설정합니다."),
    "vbank": (
        "가상계좌 결제사용",
        "주문별로 유일하게 생성되는 일회용 계좌번호입니다. 주문자가 가상계좌에 입금시 상점에 실시간으로 "
        "통보가 되므로 업무처리가 빨라집니다.",
    ),
    "iche": ("계좌이체 결제사용", "주문시 실시간 계좌이체를 가능하게 할것인지를 설정합니다."),
    "hp": ("휴대폰결제 사용", "주문시 휴대폰 결제를 가능하게 할것인지를 설정합니다."),
    "easy_pay": (
        "PG사 간편결제 버튼 노출",
        "주문서에 토스페이 간편결제 버튼을 따로 표시합니다. 토스페이먼츠와 계약한 수단만 사용하세요.",
    ),
}


def option_form_field(option):
    common = {"label": option.label, "required": False, "help_text": option.help_text}
    if option.kind == "bool":
        return forms.BooleanField(**common)
    if option.kind == "int":
        return forms.IntegerField(min_value=option.min_value, max_value=option.max_value, **common)
    if option.kind == "email":
        return forms.EmailField(max_length=option.max_length, **common)
    if option.kind == "html":
        return forms.CharField(max_length=option.max_length, widget=forms.Textarea(attrs={"rows": 5}), **common)
    if option.kind == "textarea":
        return forms.CharField(
            max_length=option.max_length, strip=False, widget=forms.Textarea(attrs={"rows": 5}), **common
        )
    if option.kind == "choice":
        return forms.ChoiceField(choices=option.choices, **common)
    return forms.CharField(max_length=option.max_length, **common)


def sms_byte_limits():
    """The byte limits the SMS text counters show: (SMS, LMS). LMS needs the token API."""
    if sms_gateway.credential_status()["mode"] == "legacy":
        return sms_gateway.LEGACY_SMS_MAX_BYTES, sms_gateway.LEGACY_SMS_MAX_BYTES
    return sms_gateway.SMS_MAX_BYTES, sms_gateway.LMS_MAX_BYTES


STATUS_SECTIONS = {"payment-status", "sms-status"}

# (group id, group title, [(section id, title, description, field names)]) in youngcart
# configform.php order: 사업자정보, 초기화면 진열, 결제설정, 배송설정, 기타 설정, SMS 설정.
SETTINGS_GROUPS = (
    ("company-group", "사업자정보", (
        ("company", "사업자정보",
         "대표자·사업자번호·주소 등은 기본환경설정의 사이트 정보와 같은 값이며 쇼핑몰 하단에 표시됩니다.",
         ["de_admin_company_name", "de_admin_company_tel", *(option.name for option in COMPANY_OPTIONS)]),
    )),
    ("display-group", "쇼핑몰 진열", (
        ("home", "쇼핑몰 초기화면 진열", "", []),
        ("lists", "상품 목록·관련상품 진열",
         "검색결과와 유형별 상품 목록, 상품 상세의 관련상품 진열입니다.",
         [option.name for option in LIST_OPTIONS]),
    )),
    ("payment-group", "결제설정", (
        ("payment-status", "결제 연결 상태", "현재 저장된 설정을 기준으로 주문 화면에서 사용할 수 있는 결제수단입니다.", []),
        ("pg", "결제대행사와 결제 방식",
         "토스페이먼츠 키는 암호화해 저장하며 저장한 시크릿 키는 다시 표시하지 않습니다. 서버 환경 변수의 키가 있으면 그 키가 우선합니다.",
         [*pg_field_order(), "de_tax_flag_use"]),
        ("bank", "무통장입금", "입금계좌를 등록하고 사용을 켜면 주문 화면에서 선택할 수 있습니다.",
         ["de_bank_use", "de_bank_account"]),
        ("online", "온라인 결제수단", "사용으로 설정한 수단도 결제대행사 연결이 준비되어야 표시됩니다. 변경은 새 주문부터 적용됩니다.",
         list(PAYMENT_OPTION_FIELDS.values())),
        ("receipts", "현금영수증 발급",
         "무통장입금 신청은 주문에 기록됩니다. 토스 가상계좌·계좌이체는 고객이 요청한 경우에만 발급 옵션을 PG에 전달합니다.",
         ["de_taxsave_use", "de_taxsave_type_account", "de_taxsave_type_vbank", "de_taxsave_type_transfer"]),
        ("points", "포인트 사용·구매 포인트",
         "포인트를 사용하려면 기본환경설정의 포인트 사용도 켜져 있어야 합니다. 구매 포인트는 상품의 포인트 설정에 따라 "
         "주문 상품이 완료된 뒤 회원에게 지급합니다.",
         ["de_settle_min_point", "de_settle_max_point", "de_settle_point_unit", "de_card_point", "de_point_days"]),
        ("subscription", "정기구독 (카드 자동결제)",
         "회원이 카드를 한 번 등록하면 고른 주기마다 토스페이먼츠 자동결제로 결제하고 일반 주문을 만듭니다. 결제 금액은 "
         "결제하는 날의 상품 가격입니다. 상품마다 '정기구독 가능'과 배송 주기를 따로 설정합니다.",
         [option.name for option in SUBSCRIPTION_OPTIONS]),
    )),
    ("delivery-group", "배송설정", (
        ("shipping", "배송비와 배송 안내", "상품별 배송비와 지역별 추가 배송비는 해당 상품·지역 설정이 함께 적용됩니다.",
         ["de_delivery_company", "de_send_cost_case", "de_send_cost_limit", "de_send_cost_list",
          "de_baesong_content", "de_change_content"]),
        ("hope-date", "희망배송일", "주문서에서 고객이 희망배송일을 고르게 합니다.",
         ["de_hope_date_use", "de_hope_date_after"]),
    )),
    ("etc-group", "기타 설정", (
        ("reviews", "상품 후기", "상품 후기 작성 자격과 공개 방식입니다.", ["de_item_use_write", "de_item_use_use"]),
        ("cart", "장바구니", "장바구니에 담은 상품의 보관 방식입니다.", ["de_guest_cart_use", "de_cart_keep_term"]),
        ("coupon", "신규회원 쿠폰", "회원가입을 마친 회원에게 발행하는 쿠폰입니다.",
         ["de_member_reg_coupon_use", "de_member_reg_coupon_price", "de_member_reg_coupon_minimum",
          "de_member_reg_coupon_term"]),
        ("guest-privacy", "비회원 개인정보 수집 안내", "비회원 주문서에 표시하는 개인정보 수집 안내입니다.", ["de_guest_privacy"]),
        ("logos", "쇼핑몰 로고", "올린 로고가 테마 기본 로고 대신 표시됩니다.",
         [field for name in SHOP_LOGO_FIELDS for field in (name, f"{name}_delete")]),
    )),
    ("sms-group", "SMS 설정", (
        ("sms-status", "SMS 연결 상태", "", []),
        ("sms", "SMS 설정",
         "주문·입금·배송 등 쇼핑몰 이벤트에 맞춰 아이코드로 문자를 보냅니다. 회신번호는 사업자정보의 "
         "쇼핑몰 고객센터 전화번호이며 아이코드에 발신번호로 등록되어 있어야 합니다.",
         [option.name for option in SMS_OPTIONS]),
    )),
)


class ShopSettingsForm(forms.ModelForm):
    de_bank_use = forms.BooleanField(label="무통장입금 사용", required=False)
    de_bank_account = forms.CharField(
        label="무통장입금 계좌 안내",
        required=False,
        max_length=4000,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="은행, 계좌번호, 예금주를 한 줄에 하나씩 입력하세요. 주문 화면에 공개됩니다.",
    )
    de_taxsave_use = forms.BooleanField(
        label="현금영수증 신청 사용",
        required=False,
        help_text="회원 주문에 신청 항목을 표시합니다. 무통장입금은 관리자 수동 발급 대상이며, 토스 가상계좌·계좌이체는 신청 시 발급 요청을 PG로 전달합니다.",
    )
    de_taxsave_type_account = forms.BooleanField(
        label="무통장입금 (기본 적용)", required=False, disabled=True,
    )
    de_taxsave_type_vbank = forms.BooleanField(label="가상계좌", required=False)
    de_taxsave_type_transfer = forms.BooleanField(label="실시간계좌이체", required=False)
    de_send_cost_case = forms.ChoiceField(
        label="배송비 방식",
        required=False,
        choices=[("", "배송비 없음 (공통 배송비 미부과)"), *ShopShippingPolicy.SEND_COST_CASE_CHOICES],
        help_text="영카트와 같이 금액별 차등일 때만 공통 배송비를 받습니다. 상품별 배송비는 그대로 적용됩니다.",
    )
    de_item_use_write = forms.BooleanField(label="구매 완료한 회원만 후기 작성", required=False)
    de_item_use_use = forms.BooleanField(label="관리자 승인 후 후기 공개", required=False)
    de_settle_min_point = forms.IntegerField(label="포인트 사용 최소 보유액", min_value=0)
    de_settle_max_point = forms.IntegerField(label="주문당 최대 사용 포인트", min_value=0, help_text="0이면 포인트로 결제할 수 없습니다.")
    de_settle_point_unit = forms.IntegerField(label="포인트 사용 단위", min_value=1)

    class Meta:
        model = ShopShippingPolicy
        fields = [
            "de_admin_company_name", "de_admin_company_tel", "de_delivery_company",
            "de_send_cost_case", "de_send_cost_limit", "de_send_cost_list",
            "de_baesong_content", "de_change_content", "de_item_use_write", "de_item_use_use",
            "de_tax_flag_use", "de_settle_min_point", "de_settle_max_point", "de_settle_point_unit",
        ]
        labels = {
            "de_admin_company_name": "쇼핑몰 회사명",
            "de_admin_company_tel": "쇼핑몰 고객센터 전화번호",
            "de_delivery_company": "기본 택배사",
            "de_send_cost_limit": "구간별 주문금액 상한 (원)",
            "de_send_cost_list": "구간별 배송비 (원)",
            "de_baesong_content": "배송 안내",
            "de_change_content": "교환·반품 안내",
            "de_tax_flag_use": "복합과세 결제",
        }
        help_texts = {
            "de_send_cost_limit": "예: 30000;50000 — 3만원 미만, 5만원 미만 구간. 마지막 상한 이상은 무료입니다.",
            "de_send_cost_list": "예: 3000;1500 — 주문금액 상한과 같은 개수로 입력하세요.",
            "de_baesong_content": "상품 상세에 표시합니다. 기존 HTML 안내도 유지할 수 있습니다.",
            "de_change_content": "상품 상세에 표시할 교환·반품 정책입니다.",
            "de_tax_flag_use": "복합과세(과세, 비과세) 결제를 사용하려면 체크하십시오. 복합과세 결제를 사용하기 전 "
            "토스페이먼츠에 별도로 결제 신청을 해주셔야 합니다. 켜면 면세 상품 금액을 결제·취소 요청에 면세 금액"
            "(taxFreeAmount)으로 함께 보냅니다.",
        }
        widgets = {
            "de_baesong_content": forms.Textarea(attrs={"rows": 5}),
            "de_change_content": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        names = [
            "de_bank_use", "de_bank_account", "de_admin_company_tel",
            CASH_RECEIPT_ENABLED_FIELD, CASH_RECEIPT_TYPES_FIELD,
            *PAYMENT_OPTION_FIELDS.values(), *SHOP_CONFIG_OPTIONS, *SHOP_LOGO_FIELDS, *PG_SETTING_NAMES,
        ]
        self.config_values = dict(Config.objects.filter(name__in=names).values_list("name", "value"))
        add_pg_fields(self, {name: self.config_values[name] for name in PG_SETTING_NAMES if name in self.config_values})
        for name, option in SHOP_CONFIG_OPTIONS.items():
            self.fields[name] = option_form_field(option)
            self.initial[name] = to_python(option, self.config_values.get(name))
        self.fields.update(logo_form_fields())
        self.logo_urls = shop_logo_urls()
        self.initial["de_bank_use"] = config_flag(self.config_values.get("de_bank_use", "0"))
        self.initial["de_bank_account"] = self.config_values.get("de_bank_account", "")
        saved_receipt_types = self.config_values.get(CASH_RECEIPT_TYPES_FIELD)
        initial_receipt_types = (
            "account,vbank,transfer" if saved_receipt_types is None else saved_receipt_types
        )
        receipt_types = {
            value.strip()
            for value in str(initial_receipt_types or "").split(",")
            if value.strip()
        }
        self.initial["de_taxsave_use"] = config_flag(self.config_values.get(CASH_RECEIPT_ENABLED_FIELD, "1"))
        self.initial["de_taxsave_type_account"] = True
        self.initial["de_taxsave_type_vbank"] = "vbank" in receipt_types
        self.initial["de_taxsave_type_transfer"] = "transfer" in receipt_types
        if not self.instance.de_admin_company_tel:
            self.initial["de_admin_company_tel"] = self.config_values.get("de_admin_company_tel", "")
        for method, name in PAYMENT_OPTION_FIELDS.items():
            label, help_text = PAYMENT_OPTION_LABELS[method]
            self.fields[name] = forms.BooleanField(label=label, required=False, help_text=help_text)
            self.initial[name] = config_flag(self.config_values.get(name, "1"))
        # configform.php get_delivery_company: the default courier is picked from the courier list
        self.fields["de_delivery_company"] = delivery_company_form_field(
            self.instance.de_delivery_company, label="기본 택배사", widget=forms.Select
        )
        for name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "checkbox"
            elif isinstance(field.widget, forms.RadioSelect):
                field.widget.attrs["class"] = "radio"
            elif isinstance(field.widget, forms.Textarea):
                field.widget.attrs["class"] = "textarea w-full"
            elif isinstance(field.widget, forms.Select):
                field.widget.attrs["class"] = "select w-full"
            else:
                field.widget.attrs["class"] = "input w-full"
            field.widget.attrs["aria-describedby"] = f"id_{name}_help id_{name}_errors"
        sms_limit, lms_limit = sms_byte_limits()
        for option in SMS_OPTIONS:
            if option.kind == "textarea":
                self.fields[option.name].widget.attrs.update(
                    {"data-sms-bytes": "", "data-sms-limit": sms_limit, "data-lms-limit": lms_limit}
                )

    def clean_de_sms_hp(self):
        value = self.cleaned_data.get("de_sms_hp", "").strip()
        if value and not sms_gateway.normalize_mobile(value):
            raise forms.ValidationError("관리자 휴대폰번호는 010-1234-5678 형식의 휴대폰번호로 입력하세요.")
        return value

    def clean_de_bank_account(self):
        lines = [line.strip() for line in self.cleaned_data["de_bank_account"].splitlines() if line.strip()]
        if len(lines) > 20 or any(len(line) > 200 for line in lines):
            raise forms.ValidationError("계좌는 최대 20개, 한 줄에 200자 이내로 입력하세요.")
        return "\n".join(lines)

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("de_bank_use") and not cleaned.get("de_bank_account"):
            self.add_error("de_bank_account", "무통장입금을 사용하려면 입금계좌를 입력하세요.")
        if cleaned.get("de_send_cost_case") == "차등":
            parsed = {}
            for name in ("de_send_cost_limit", "de_send_cost_list"):
                value = cleaned.get(name, "")
                parts = [part.strip() for part in value.split(";")]
                if not value or any(not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)", part) for part in parts):
                    self.add_error(name, "0 이상의 정수를 세미콜론(;)으로 구분해 입력하세요.")
                    continue
                numbers = [int(part.replace(",", "")) for part in parts]
                if any(number > 2147483647 for number in numbers):
                    self.add_error(name, "입력 금액이 너무 큽니다.")
                    continue
                parsed[name] = numbers
            limits = parsed.get("de_send_cost_limit")
            costs = parsed.get("de_send_cost_list")
            if limits is not None and (not all(limits) or limits != sorted(set(limits))):
                self.add_error("de_send_cost_limit", "주문금액 상한은 0보다 큰 금액을 중복 없이 오름차순으로 입력하세요.")
            if limits is not None and costs is not None and len(limits) != len(costs):
                self.add_error("de_send_cost_list", "배송비 개수를 주문금액 상한 개수와 맞춰 주세요.")
        if cleaned.get("de_member_reg_coupon_use"):
            for name, message in (
                ("de_member_reg_coupon_price", "신규회원 쿠폰을 발행하려면 할인금액을 1원 이상 입력하세요."),
                ("de_member_reg_coupon_term", "신규회원 쿠폰을 발행하려면 유효기간을 1일 이상 입력하세요."),
            ):
                if not cleaned.get(name):
                    self.add_error(name, message)
        clean_pg_fields(self, cleaned)
        return cleaned

    def section_groups(self):
        """The page's groups and sections in youngcart configform.php order."""
        groups = []
        for group_id, group_title, sections in SETTINGS_GROUPS:
            built = []
            for key, title, description, names in sections:
                if key == "home":
                    built.append(self._home_list_section())
                    continue
                section = {"id": key, "title": title, "description": description,
                           "fields": [self._section_field(name) for name in names]}
                if key in STATUS_SECTIONS:
                    section["status"] = key
                built.append(section)
            groups.append({"id": group_id, "title": group_title, "sections": built})
        return groups

    def sections(self):
        return [section for group in self.section_groups() for section in group["sections"]]

    def _section_field(self, name):
        widget = self.fields[name].widget
        item = {
            "bound": self[name],
            "checkbox": isinstance(widget, forms.CheckboxInput),
            "radio": isinstance(widget, forms.RadioSelect),
        }
        if name in SHOP_LOGO_FIELDS:
            item["current_url"] = self.logo_urls.get(name, "")
        return item

    def _home_list_section(self):
        rows = [
            {"label": title, "fields": [self[f"de_type{number}_list_use"]] + [
                self[name] for name in (
                    f"de_type{number}_list_mod", f"de_type{number}_list_row",
                    f"de_mobile_type{number}_list_mod", f"de_mobile_type{number}_list_row",
                )
            ]}
            for number, title in HOME_LIST_TYPES
        ]
        return {
            "id": "home", "title": "쇼핑몰 초기화면 진열",
            "description": "초기화면 상품 묶음별 출력 여부와 진열 수입니다. 표시되는 상품 수는 1줄당 상품 수 × 줄 수입니다.",
            "fields": [],
            "table": {"columns": ["출력", "PC 1줄당", "PC 줄 수", "모바일 1줄당", "모바일 줄 수"], "rows": rows},
        }

    def save_settings(self, user):
        # Save only this screen's known fields, never arbitrary Config names from POST; the Toss
        # keys are sealed before they are stored. Keep policy and switches atomic.
        with batch_bootstrap_changes(), transaction.atomic():
            policy = self.save(commit=False)
            policy.pk = 1
            policy.save()
            values = {"de_bank_account": self.cleaned_data["de_bank_account"]}
            for name in ("de_bank_use", *PAYMENT_OPTION_FIELDS.values()):
                values[name] = "1" if self.cleaned_data[name] else ""
            receipt_types = ["account"]
            if self.cleaned_data["de_taxsave_type_vbank"]:
                receipt_types.append("vbank")
            if self.cleaned_data["de_taxsave_type_transfer"]:
                receipt_types.append("transfer")
            values[CASH_RECEIPT_ENABLED_FIELD] = "1" if self.cleaned_data["de_taxsave_use"] else "0"
            values[CASH_RECEIPT_TYPES_FIELD] = ",".join(receipt_types)
            for name, option in SHOP_CONFIG_OPTIONS.items():
                value = self.cleaned_data.get(name)
                if option.kind == "int" and value is None:
                    value = to_python(option, None)
                values[name] = to_stored(option, value)
            # Existing site/company API consumers use this Config row.
            values["de_admin_company_tel"] = self.cleaned_data["de_admin_company_tel"]
            replaced_logos = []
            for name in SHOP_LOGO_FIELDS:
                uploaded = self.cleaned_data.get(name)
                if uploaded or self.cleaned_data.get(f"{name}_delete"):
                    replaced_logos.append(self.config_values.get(name, ""))
                    values[name] = store_logo(name, uploaded) if uploaded else ""
            for name, value in values.items():
                Config.objects.update_or_create(name=name, defaults={"value": value})
            for path in replaced_logos:
                transaction.on_commit(lambda path=path: delete_logo_file(path))
            pg_changes = save_pg_changes(self)
            sync_shop_phone_from_policy(self.cleaned_data["de_admin_company_tel"])
            content_type = ContentType.objects.get_for_model(ShopShippingPolicy)
            LogEntry.objects.create(
                user_id=user.pk,
                content_type=content_type,
                object_id=str(policy.pk),
                object_repr="쇼핑몰 설정",
                action_flag=CHANGE,
                change_message="쇼핑몰 결제수단·입금계좌·배송 및 운영 설정 변경",
            )
            if pg_changes:
                # what changed (a key was registered or removed), never a key value
                LogEntry.objects.create(
                    user_id=user.pk,
                    content_type=content_type,
                    object_id=str(policy.pk),
                    object_repr="쇼핑몰 결제설정",
                    action_flag=CHANGE,
                    change_message=f"결제설정 변경: {', '.join(pg_changes)}"[:2000],
                )
            transaction.on_commit(lambda: signals.config_done.send(sender=Config))


@sensitive_post_parameters(*TOSS_KEY_ROWS.values())
@require_http_methods(["GET", "POST"])
def shop_settings(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    if request.method == "POST" and request.POST.get("action") == "check_pg":
        result = check_toss_connection()
        if result["status"] == "connected":
            messages.success(request, "토스페이먼츠 서버 인증에 성공했습니다. 실제 결제는 실행하지 않았습니다.")
        elif result["status"] == "invalid_credentials":
            messages.error(request, "토스페이먼츠 키를 인증하지 못했습니다. 결제 테스트 설정과 등록한 키(또는 서버 환경 변수) 값을 확인하세요.")
        elif result["status"] in {"missing", "incomplete", "invalid_prefix", "mode_mismatch"}:
            messages.error(request, "테스트 키끼리 또는 실결제 키끼리 한 쌍을 등록해야 연결을 확인할 수 있습니다.")
        else:
            messages.error(request, "토스페이먼츠에 연결하지 못했습니다. 네트워크와 API 응답을 확인하세요.")
        return HttpResponseRedirect(reverse("admin-shop-settings"))
    if request.method == "POST" and request.POST.get("action") == "test_sms":
        test_sms(request)
        return HttpResponseRedirect(reverse("admin-shop-settings") + "#sms-status")
    is_post = request.method == "POST"
    form = ShopSettingsForm(
        request.POST if is_post else None, request.FILES if is_post else None, instance=current_shipping_policy()
    )
    if request.method == "POST" and form.is_valid():
        form.save_settings(request.user)
        messages.success(request, "쇼핑몰 설정을 저장했습니다. 새 주문부터 적용됩니다.")
        return HttpResponseRedirect(reverse("admin-shop-settings"))

    context = {
        **admin.site.each_context(request),
        "title": "쇼핑몰 설정",
        "form": form,
        "groups": form.section_groups(),
        **payment_status_context(request),
        "sms": sms_status_context(),
    }
    request.current_app = admin.site.name
    return TemplateResponse(request, "admin/shop/settings.html", context)


GATEWAY_LABELS = {
    "missing": "키 미등록", "incomplete": "키 한 개 누락", "invalid_prefix": "키 형식 확인 필요",
    "invalid_mid": "MID 형식 확인 필요", "invalid_key": "MerchantKey 형식 확인 필요",
    "mode_mismatch": "테스트·실결제 키 혼합", "test": "테스트 키 쌍", "live": "실결제 키 쌍",
}
PROVIDER_LABELS = {
    "toss": "토스페이먼츠", "nicepay": "NICEPAY 인증결제",
    "bank": "온라인 PG 미선택 (무통장입금만)",
}


def payment_method_status(toss, nicepay, provider, methods):
    preferences = {"bank": config_flag(Config.objects.filter(name="de_bank_use").values_list("value", flat=True).first())}
    # Missing legacy rows preserve the historical enabled default for online methods.
    saved_options = dict(Config.objects.filter(name__in=PAYMENT_OPTION_FIELDS.values()).values_list("name", "value"))
    preferences.update({method: config_flag(saved_options.get(field_name, "1")) for method, field_name in PAYMENT_OPTION_FIELDS.items()})
    active = nicepay if provider == "nicepay" else toss
    active_label = "NICEPAY" if provider == "nicepay" else "토스페이먼츠"
    rows = []
    for method, label in {"bank": "무통장입금", **PAYMENT_LABELS}.items():
        enabled = bool(methods[method])
        if method == "bank":
            account_value = Config.objects.filter(name="de_bank_account").values_list("value", flat=True).first()
            bank_accounts = any(line.strip() for line in str(account_value or "").splitlines())
            detail = "사용 가능" if enabled else "관리자 중지"
            if preferences["bank"] and not bank_accounts:
                detail = "입금계좌 없음"
        elif not preferences[method]:
            detail = "관리자 중지"
        elif not active["enabled"]:
            detail = GATEWAY_LABELS[active["key_status"]]
        elif provider not in {"toss", "nicepay"}:
            detail = f"{active_label}가 주문 결제사로 선택되지 않음"
        elif method == "vbank" and not active["vbank_enabled"]:
            detail = "서버 플래그 비활성 · 입금통보 URL 등록 확인 필요"
        else:
            detail = "사용 가능"
        rows.append({"name": label, "enabled": enabled, "detail": detail})
    return rows


def payment_status_context(request):
    """The 결제 연결 상태 card: what checkout can offer and where the keys come from. Only
    presence and modes reach the template, never a key or adapter secret."""
    rows = pg_stored_rows()
    toss = toss_payment_config(rows=rows)
    nicepay = nicepay_payment_config(rows=rows)
    adapter = payment_adapter_config()
    provider = configured_payment_provider(rows=rows, toss_config=toss, nicepay_config=nicepay)
    methods = checkout_payment_methods(
        toss_config=toss, nicepay_config=nicepay, pg_service=provider
    )
    receipt_preferences = cash_receipt_preferences()
    return {
        "payment_status": payment_method_status(toss, nicepay, provider, methods),
        "has_payment_method": any(methods.values()),
        "cash_receipt": {
            "enabled": receipt_preferences["enabled"],
            "methods": [
                label for key, label in (
                    ("bank", "무통장입금"), ("vbank", "가상계좌"), ("iche", "실시간계좌이체")
                ) if receipt_preferences["methods"][key]
            ],
        },
        "payment_provider_label": PROVIDER_LABELS.get(provider, f"{provider} 확인 어댑터 (주문 결제 시작 미지원)"),
        "gateway": {
            "adapter_enabled": adapter["enabled"],
            **pg_status(toss, provider, rows, nicepay),
        },
        "webhook_url": webhook_url(request),
        "nicepay_notify_url": nicepay_notify_url(request),
        "nicepay_return_url": nicepay_return_url_help(request),
        "unsupported_rows": UNSUPPORTED_ROWS,
    }


SMS_MODE_LABELS = {"token": "토큰키 (JSON 방식)", "legacy": "아이디·비밀번호 (구버전)", "missing": "미등록"}


def sms_status_context():
    """Only whether the iCode credentials are present, never their values."""
    status = sms_gateway.credential_status()
    current = sms_settings()
    return {
        "enabled": current.enabled,
        "type_label": "LMS" if current.allow_lms else "SMS",
        "credentials_registered": status["mode"] != "missing",
        "mode_label": SMS_MODE_LABELS[status["mode"]],
        "provider_enabled": status["provider_enabled"],
        "ready": status["ready"],
        "has_admin_hp": bool(sms_gateway.normalize_mobile(current.admin_hp)),
        "has_callback": bool(current.callback),
        "lms_unsupported": current.allow_lms and status["mode"] == "legacy",
        "can_test": status["ready"] and bool(sms_gateway.normalize_mobile(current.admin_hp)) and bool(current.callback),
    }


def test_sms(request):
    """테스트 발송: one text to de_sms_hp, at most once a minute (the view is superuser-only)."""
    status = sms_status_context()
    if not status["ready"]:
        messages.error(request, "아이코드 인증 정보가 서버 환경 변수에 등록되지 않았거나 서버에서 SMS가 꺼져 있습니다.")
        return
    if not status["has_admin_hp"] or not status["has_callback"]:
        messages.error(request, "관리자 휴대폰번호와 쇼핑몰 고객센터 전화번호(회신번호)를 먼저 저장하세요.")
        return
    if not reserve_test_send():
        messages.error(request, "테스트 발송은 1분에 한 번만 할 수 있습니다. 잠시 후 다시 시도하세요.")
        return
    result = send_test_message()
    LogEntry.objects.create(
        user_id=request.user.pk,
        content_type=ContentType.objects.get_for_model(ShopShippingPolicy),
        object_id="1",
        object_repr="쇼핑몰 설정",
        action_flag=CHANGE,
        change_message=f"SMS 테스트 발송 ({result.status}, {result.provider_code})"[:200],
    )
    if result.status == "queued":
        messages.success(request, "테스트 문자를 발송 대기열에 등록했습니다. 백그라운드 작업에서 최종 결과를 확인하세요.")
    elif result.status == "accepted":
        messages.success(request, f"테스트 문자를 관리자 휴대폰번호로 보냈습니다. (아이코드 접수번호 {result.provider_code})")
    elif result.status == "unknown":
        messages.warning(request, "아이코드 응답을 확인하지 못했습니다. 문자가 도착했는지 휴대폰에서 확인하세요.")
    else:
        messages.error(request, f"아이코드가 테스트 문자를 거부했습니다. (코드 {result.provider_code or '-'})")
