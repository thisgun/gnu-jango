"""Catalog admin pieces ported from youngcart (itemform.php, itemcopy.php, categoryform.php).

* ProductOptionFormMixin - the option builder widget and the server-side option checks.
* ShopProductRelationInline - 관련상품 on the product form (autocomplete, drag order).
* ProductCopyForm / copy helpers - 상품 복사.
* CategoryAdminForm / category tools - 하위분류 추가 and the delete refusal.
"""

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse
from django.utils.html import format_html
from unfold.admin import TabularInline

from gnu_jango.shop.admin.option_builder import OptionBuilderWidget
from gnu_jango.shop.category_tree import (
    CATEGORY_ID_STEP,
    MAX_CATEGORY_ID_LENGTH,
    category_delete_blockers,
    next_child_category_id,
)
from gnu_jango.shop.models import ShopCategory, ShopProductRelation
from gnu_jango.shop.product_copy import copy_product, next_product_id, validate_new_product_id
from gnu_jango.shop.product_options import (
    clean_option_subject,
    normalize_option_rows,
    option_rows_equivalent,
    supply_subject,
)

# youngcart categoryform.php starts a new category at 3 images x 5 rows on both screens
NEW_CATEGORY_LIST_DEFAULTS = {
    "ca_list_mod": 3,
    "ca_list_row": 5,
    "ca_mobile_list_mod": 3,
    "ca_mobile_list_row": 5,
}
MAX_LIST_MOD = 8  # lib/shop-display.ts MAX_COLS
MAX_LIST_ROW = 20


class ProductOptionFormMixin:
    """For ShopProductAdminForm: the builder widget on ``options`` and youngcart's option checks."""

    def setup_option_builder(self):
        if "options" in self.fields:
            self.fields["options"].widget = OptionBuilderWidget()
            self.fields["options"].label = "선택옵션 · 추가옵션"
            self.fields["options"].help_text = ""
        for name in ("it_option_subject", "it_supply_subject"):
            if name in self.fields:
                # written by the builder; the server re-derives / checks them in clean_option_fields
                self.fields[name].widget = forms.HiddenInput()

    def clean_options(self):
        options = self.cleaned_data.get("options")
        if "options" not in self.changed_data:
            return options
        initial = self.instance.options if self.instance.pk else None
        if option_rows_equivalent(options, initial):
            # stored rows sent back untouched (e.g. imported rows the builder only re-serialized):
            # keep them as they are instead of failing an unrelated edit on stricter checks
            return initial
        return normalize_option_rows(options)

    def clean_option_fields(self, cleaned_data):
        touched = {"options", "it_option_subject", "it_supply_subject"} & set(self.changed_data)
        if not touched or "options" in self.errors:
            return cleaned_data
        rows = cleaned_data.get("options")
        if not isinstance(rows, list):
            return cleaned_data
        if "options" not in self.changed_data or rows is self.instance.options:
            try:
                rows = normalize_option_rows(rows)
            except ValidationError:
                return cleaned_data  # stored rows from before the builder; leave them be
        try:
            cleaned_data["it_option_subject"] = clean_option_subject(cleaned_data.get("it_option_subject"), rows)
        except ValidationError as error:
            self.add_error("options", error)
        cleaned_data["it_supply_subject"] = supply_subject(rows)
        return cleaned_data


class ShopProductRelationForm(forms.ModelForm):
    class Meta:
        model = ShopProductRelation
        fields = ("related", "ir_no")

    def clean(self):
        cleaned_data = super().clean()
        related = cleaned_data.get("related")
        if related is not None and related.pk == self.instance.product_id:
            self.add_error("related", "자기 자신은 관련상품으로 지정할 수 없습니다.")
        return cleaned_data


class ShopProductRelationInline(TabularInline):
    """itemformrelation.php: search and add related products, drag to order (ir_no)."""

    model = ShopProductRelation
    form = ShopProductRelationForm
    fk_name = "product"
    fields = ("related", "ir_no")
    autocomplete_fields = ("related",)
    ordering_field = "ir_no"
    hide_ordering_field = True
    extra = 0
    tab = True
    verbose_name = "관련상품"
    verbose_name_plural = "관련상품"

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("related")


class ProductCopyForm(forms.Form):
    new_it_id = forms.CharField(
        label="새 상품코드",
        max_length=20,
        help_text="영문자, 숫자, -, _ 만 쓸 수 있습니다. 기본값은 영카트처럼 현재 시각입니다.",
    )

    def clean_new_it_id(self):
        return validate_new_product_id(self.cleaned_data["new_it_id"])


def copy_products(queryset):
    """Copy each product under a fresh time-based code, each on its own.

    Returns ``([(source, copy)], [(source, error)])``."""
    reserved = []
    copies = []
    failures = []
    for product in queryset.order_by("it_id"):
        new_id = next_product_id(reserved=reserved)
        reserved.append(new_id)
        try:
            copies.append((product, copy_product(product, new_id)))
        except (ValidationError, OSError, IntegrityError) as error:
            failures.append((product, "; ".join(getattr(error, "messages", [str(error)]))))
    return copies, failures


def product_copy_button(obj):
    if not obj or not obj.pk:
        return "-"
    url = reverse("admin:shop_shopproduct_copy", args=[obj.it_id])
    return format_html('<a class="button" href="{}">{}</a>', url, "상품 복사")


# --- categories ---------------------------------------------------------------


class CategoryAdminForm(forms.ModelForm):
    class Meta:
        model = ShopCategory
        fields = "__all__"
        labels = {
            "ca_id": "분류코드",
            "ca_name": "분류명",
            "ca_parent": "상위분류코드",
            "ca_order": "출력순서",
            "ca_use": "판매가능",
            "ca_skin": "스킨",
        }
        help_texts = {
            "ca_id": "단계마다 영문 · 숫자 2자씩, 5단계(10자)까지. 하위분류 추가를 누르면 다음 코드가 채워집니다.",
            "ca_parent": "비워 두면 분류코드에서 끝 2자를 뗀 코드로 채웁니다.",
        }

    def clean_ca_id(self):
        ca_id = str(self.cleaned_data.get("ca_id") or "").strip()
        if self.instance and not self.instance._state.adding:
            return ca_id
        if not ca_id.isascii() or not ca_id.isalnum():
            raise ValidationError("분류코드는 영문자와 숫자만 쓸 수 있습니다.")
        if len(ca_id) % CATEGORY_ID_STEP or len(ca_id) > MAX_CATEGORY_ID_LENGTH:
            raise ValidationError("분류코드는 단계마다 2자씩, 5단계(10자)까지만 만들 수 있습니다.")
        parent = ca_id[:-CATEGORY_ID_STEP]
        if parent and not ShopCategory.objects.filter(pk=parent).exists():
            raise ValidationError(f"상위 분류 {parent} 가 없습니다. 상위 분류를 먼저 만들어 주세요.")
        return ca_id

    def clean(self):
        cleaned_data = super().clean()
        for name, limit in (
            ("ca_list_mod", MAX_LIST_MOD), ("ca_mobile_list_mod", MAX_LIST_MOD),
            ("ca_list_row", MAX_LIST_ROW), ("ca_mobile_list_row", MAX_LIST_ROW),
        ):
            value = cleaned_data.get(name)
            if value is not None and value > limit:
                self.add_error(name, f"{limit} 이하로 입력해 주세요. (0 은 기본 진열)")
        ca_id = str(cleaned_data.get("ca_id") or self.instance.ca_id or "")
        if not cleaned_data.get("ca_parent") and len(ca_id) > CATEGORY_ID_STEP:
            cleaned_data["ca_parent"] = ca_id[:-CATEGORY_ID_STEP]
        return cleaned_data


def new_category_initial(request):
    """Add-form initial values: youngcart's 3 x 5 grid and, for ?parent=<ca_id>, the next child code."""
    initial = dict(NEW_CATEGORY_LIST_DEFAULTS)
    parent_id = str(request.GET.get("parent") or "").strip()
    parent = ShopCategory.objects.filter(pk=parent_id).first() if parent_id else None
    initial["ca_id"] = next_child_category_id(parent.ca_id if parent else "")
    if parent:
        initial["ca_parent"] = parent.ca_id
        initial["ca_use"] = parent.ca_use
        for name in NEW_CATEGORY_LIST_DEFAULTS:
            initial[name] = getattr(parent, name) or initial[name]
    return initial


def add_child_category_button(obj):
    if not obj or not obj.pk or len(obj.ca_id) >= MAX_CATEGORY_ID_LENGTH:
        return "-"
    url = f"{reverse('admin:shop_shopcategory_add')}?parent={obj.ca_id}"
    return format_html('<a class="button" href="{}">{}</a>', url, "하위분류 추가")


def protected_category_reasons(objs):
    reasons = []
    for category in objs:
        if isinstance(category, ShopCategory):
            reasons.extend(category_delete_blockers(category))
    return reasons


def refuse_blocked_categories(modeladmin, request, categories):
    """The categories that may be deleted; a message names each refused one."""
    allowed = []
    for category in categories:
        reasons = category_delete_blockers(category)
        if reasons:
            for reason in reasons:
                modeladmin.message_user(request, reason, level=messages.ERROR)
        else:
            allowed.append(category)
    return allowed
