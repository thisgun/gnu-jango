"""The coupon change form, after youngcart adm/shop_admin/couponform.php / couponformupdate.php.

쿠폰종류 (cp_method) and 쿠폰타입 (cp_type) are labelled choices, the 적용상품 / 적용분류 target is
picked with a search box for the chosen kind, and 전체회원 (cp_all_members) issues one coupon every
member may use once (the use is tracked per member in the coupon log, see
api/shop_coupons.valid_coupons_queryset) instead of picking a single member.
"""

from django import forms
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.utils import timezone
from unfold.fields import UnfoldAdminAutocompleteModelChoiceField
from unfold.views import BaseAutocompleteView
from unfold.widgets import (
    UnfoldAdminAutocompleteModelChoiceFieldWidget,
    UnfoldAdminSelectWidget,
    UnfoldBooleanSwitchWidget,
)

from gnu_jango.shop.models import ShopCategory, ShopCoupon, ShopProduct

METHOD_PRODUCT = 0
METHOD_CATEGORY = 1
METHOD_ORDER = 2
METHOD_SHIPPING = 3
TYPE_AMOUNT = 0
TYPE_RATE = 1
COUPON_METHOD_CHOICES = (
    (METHOD_PRODUCT, "개별상품할인"),
    (METHOD_CATEGORY, "카테고리할인"),
    (METHOD_ORDER, "주문금액할인"),
    (METHOD_SHIPPING, "배송비할인"),
)
COUPON_TYPE_CHOICES = ((TYPE_AMOUNT, "정액할인(원)"), (TYPE_RATE, "정률할인(%)"))
COUPON_TRUNC_CHOICES = ((1, "1원단위"), (10, "10원단위"), (100, "100원단위"), (1000, "1,000원단위"))
COUPON_METHOD_LABELS = dict(COUPON_METHOD_CHOICES)
PRODUCT_AUTOCOMPLETE_URL = "admin:shop_shopcoupon_target_products"
CATEGORY_AUTOCOMPLETE_URL = "admin:shop_shopcoupon_target_categories"


class SelectedOnlyAutocompleteWidget(UnfoldAdminAutocompleteModelChoiceFieldWidget):
    """Render only the chosen option (like Django's AutocompleteSelect), not the whole catalog."""

    def optgroups(self, name, value, attrs=None):
        selected = [str(item) for item in value if item not in (None, "")]
        options = []
        if not self.is_required:
            options.append(self.create_option(name, "", "", False, 0))
        if selected:
            field = self.choices.field
            for index, obj in enumerate(self.choices.queryset.filter(pk__in=selected), start=len(options)):
                options.append(
                    self.create_option(
                        name, field.prepare_value(obj), field.label_from_instance(obj), True, index, attrs=attrs
                    )
                )
        return [(None, options, 0)]


class _TargetAutocompleteView(BaseAutocompleteView):
    """Search box results for the coupon target picker (staff with coupon edit rights only)."""

    model_admin = None
    search_fields = ()

    def get(self, request, *args, **kwargs):
        if not (self.model_admin.has_add_permission(request) or self.model_admin.has_change_permission(request)):
            raise PermissionDenied
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        term = str(self.request.GET.get("term") or "").strip()[:100]
        queryset = self.model.objects.order_by("pk")
        if term:
            condition = Q()
            for name in self.search_fields:
                condition |= Q(**{f"{name}__icontains": term})
            queryset = queryset.filter(condition)
        return queryset


class ProductTargetAutocompleteView(_TargetAutocompleteView):
    model = ShopProduct
    search_fields = ("it_id", "it_name")

    def get_queryset(self):
        return super().get_queryset().only("it_id", "it_name")


class CategoryTargetAutocompleteView(_TargetAutocompleteView):
    model = ShopCategory
    search_fields = ("ca_id", "ca_name")

    def get_queryset(self):
        return super().get_queryset().only("ca_id", "ca_name")


class ShopCouponAdminForm(forms.ModelForm):
    cp_method = forms.TypedChoiceField(
        label="쿠폰종류",
        choices=COUPON_METHOD_CHOICES,
        coerce=int,
        initial=METHOD_ORDER,
        widget=UnfoldAdminSelectWidget,
        help_text="개별상품·카테고리 할인은 적용할 상품이나 분류를 고릅니다.",
    )
    target_product = UnfoldAdminAutocompleteModelChoiceField(
        url_path=PRODUCT_AUTOCOMPLETE_URL,
        queryset=ShopProduct.objects.all(),
        required=False,
        label="적용상품",
        widget=SelectedOnlyAutocompleteWidget,
        help_text="상품코드나 상품명으로 검색합니다.",
    )
    target_category = UnfoldAdminAutocompleteModelChoiceField(
        url_path=CATEGORY_AUTOCOMPLETE_URL,
        queryset=ShopCategory.objects.all(),
        required=False,
        label="적용분류",
        widget=SelectedOnlyAutocompleteWidget,
        help_text="분류코드나 분류명으로 검색합니다. 하위 분류의 상품에도 적용됩니다.",
    )
    cp_all_members = forms.BooleanField(
        label="전체회원",
        required=False,
        widget=UnfoldBooleanSwitchWidget,
        help_text="켜면 회원을 고르지 않고 모든 회원이 한 번씩 쓸 수 있는 쿠폰 한 장을 발행합니다.",
    )
    cp_type = forms.TypedChoiceField(
        label="쿠폰타입", choices=COUPON_TYPE_CHOICES, coerce=int, initial=TYPE_AMOUNT, widget=UnfoldAdminSelectWidget
    )
    cp_trunc = forms.TypedChoiceField(
        label="절사금액",
        choices=COUPON_TRUNC_CHOICES,
        coerce=int,
        initial=1,
        widget=UnfoldAdminSelectWidget,
        help_text="정률할인 금액을 이 단위로 잘라냅니다.",
    )

    class Meta:
        model = ShopCoupon
        fields = "__all__"
        labels = {
            "cp_subject": "쿠폰이름",
            "user": "회원",
            "cp_price": "할인금액 또는 할인비율",
            "cp_minimum": "최소주문금액 (원)",
            "cp_maximum": "최대할인금액 (원)",
            "cp_start": "사용시작일",
            "cp_end": "사용종료일",
        }
        help_texts = {
            "user": "회원 아이디·이름으로 검색합니다. 전체회원 쿠폰이면 비워 둡니다.",
            "cp_price": "정액할인은 원, 정률할인은 1~99 사이의 %입니다.",
            "cp_maximum": "정률할인의 최대 할인금액입니다. 0이면 제한하지 않습니다.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = self.instance
        if not instance._state.adding and instance.cp_target:
            if instance.cp_method == METHOD_PRODUCT:
                self.initial.setdefault("target_product", instance.cp_target)
            elif instance.cp_method == METHOD_CATEGORY:
                self.initial.setdefault("target_category", instance.cp_target)

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("cp_method")
        target = ""
        if method == METHOD_PRODUCT:
            product = cleaned.get("target_product")
            if product is None:
                self.add_error("target_product", "적용상품을 선택해 주십시오.")
            else:
                target = product.pk
        elif method == METHOD_CATEGORY:
            category = cleaned.get("target_category")
            if category is None:
                self.add_error("target_category", "적용분류를 선택해 주십시오.")
            else:
                target = category.pk
        self.instance.cp_target = target

        if cleaned.get("cp_all_members"):
            cleaned["user"] = None
        elif not cleaned.get("user"):
            self.add_error("user", "회원을 선택하거나 전체회원을 켜 주십시오.")
        elif not cleaned["user"].is_active:
            self.add_error("user", "탈퇴 또는 차단된 회원에게는 쿠폰을 발행할 수 없습니다.")

        start, end = cleaned.get("cp_start"), cleaned.get("cp_end")
        if start and end and start > end:
            self.add_error("cp_end", "사용 시작일은 종료일 이전으로 입력해 주십시오.")
        if self.instance._state.adding:
            if not end:
                self.add_error("cp_end", "사용종료일을 입력해 주십시오.")
            elif end < timezone.localdate():
                self.add_error("cp_end", f"종료일은 오늘({timezone.localdate():%Y-%m-%d}) 이후로 입력해 주십시오.")

        price = cleaned.get("cp_price")
        if price is not None:
            if price <= 0:
                self.add_error(
                    "cp_price", "할인비율을 입력해 주십시오." if cleaned.get("cp_type") == TYPE_RATE else "할인금액을 입력해 주십시오."
                )
            elif cleaned.get("cp_type") == TYPE_RATE and not 1 <= price <= 99:
                self.add_error("cp_price", "할인비율을 1과 99사이 값으로 입력해 주십시오.")
        for name in ("cp_minimum", "cp_maximum"):
            if (cleaned.get(name) or 0) < 0:
                self.add_error(name, "0 이상의 금액을 입력해 주십시오.")
        return cleaned
