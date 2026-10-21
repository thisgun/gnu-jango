from gnu_jango.shop.admin._common import *  # noqa: F401,F403
from urllib.parse import quote, unquote, urlencode, urlsplit

from django import forms
from django.conf import settings
from django.contrib import messages
from unfold.forms import ActionForm
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.http import Http404, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join
from django.utils.translation import gettext_lazy as _

from gnu_jango.shop.images import (
    delete_product_image_after_commit,
    managed_product_image_storage_path,
    upload_product_images,
)
from gnu_jango.shop.admin.catalog_tools import (
    CategoryAdminForm,
    ProductCopyForm,
    ProductOptionFormMixin,
    ShopProductRelationInline,
    add_child_category_button,
    copy_products,
    new_category_initial,
    product_copy_button,
    protected_category_reasons,
    refuse_blocked_categories,
)
from gnu_jango.shop.admin.item_info_form import ItemInfoTextField, clean_item_info, item_info_kind_field
from gnu_jango.shop.product_copy import copy_product, next_product_id
from gnu_jango.shop.product_relations import mirror_product_relations
from gnu_jango.shop.models import ShopProduct, ShopStockAdjustment


PRODUCT_TYPE_FIELDS = (
    ("it_type1", _("Best")),
    ("it_type2", _("Recommended")),
    ("it_type3", _("New")),
    ("it_type4", _("Popular")),
    ("it_type5", _("Sale")),
)


def admin_product_image_url(value):
    if isinstance(value, dict):
        value = value.get("url") or value.get("src") or value.get("image_url") or ""
    url = str(value or "").strip()
    if not url:
        return ""
    legacy_base = str(getattr(settings, "LEGACY_GNUBOARD5_BASE_URL", "") or "").strip().rstrip("/")
    if url.startswith(("/data/item/", "/data/banner/")) and legacy_base:
        url = f"{legacy_base}{url}"
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    if parsed.scheme:
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            return ""
    elif parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return ""
    return url


def admin_product_image_urls(product):
    values = [product.image_url]
    images = product.images if isinstance(product.images, list) else []
    values.extend(images)
    urls = []
    for value in values:
        url = admin_product_image_url(value)
        if url and url not in urls:
            urls.append(url)
    return urls


def admin_product_image_rows(product):
    images = product.images if isinstance(product.images, list) else []
    storage_paths = {}
    for image in images:
        url = admin_product_image_url(image)
        path = managed_product_image_storage_path(image, product.it_id)
        if url and path:
            storage_paths.setdefault(url, path)
    primary_url = admin_product_image_url(product.image_url)
    return [
        {
            "url": url,
            "is_primary": url == primary_url,
            "managed_upload": url in storage_paths,
        }
        for url in admin_product_image_urls(product)
    ]


class ShopProductActionForm(ActionForm):
    target_event = forms.ModelChoiceField(
        queryset=ShopEvent.objects.filter(ev_use=True).order_by("-ev_id"),
        required=False,
        label=_("Target event"),
    )
    product_type = forms.ChoiceField(
        choices=(
            ("", _("Select a product type")),
            *((str(index), label) for index, (_, label) in enumerate(PRODUCT_TYPE_FIELDS, 1)),
        ),
        required=False,
        label=_("Product type"),
    )
    product_type_operation = forms.ChoiceField(
        choices=(
            ("", _("Select an action")),
            ("show", _("Add selected products to this type")),
            ("hide", _("Remove selected products from this type")),
        ),
        required=False,
        label=_("Type action"),
    )


class ShopProductAdminForm(ProductOptionFormMixin, forms.ModelForm):
    it_info_value = ItemInfoTextField()

    class Meta:
        model = ShopProduct
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "it_info_gubun" in self.fields:
            # itemform.php: the notice kind comes from lib/iteminfo.lib.php
            self.fields["it_info_gubun"] = item_info_kind_field(self.instance.it_info_gubun)
        self.setup_option_builder()

    def clean(self):
        return self.clean_option_fields(clean_item_info(self, super().clean()))

    def clean_it_stock_qty(self):
        stock = self.cleaned_data.get("it_stock_qty")
        if stock is not None and (stock < 0 or stock > 2_147_483_647):
            raise forms.ValidationError(_("Stock must be between 0 and 2,147,483,647."))
        return stock


def option_stock_map(options):
    result = {}
    for option in options if isinstance(options, list) else []:
        if not isinstance(option, dict):
            continue
        option_id = str(option.get("io_id") or "").strip()
        if not option_id:
            continue
        try:
            option_type = int(option.get("io_type") or 0)
            stock = int(option.get("io_stock_qty") or 0)
        except (TypeError, ValueError):
            continue
        if option_type in (0, 1):
            result.setdefault((option_type, option_id), stock)
    return result


@admin.register(ShopCategory)
class ShopCategoryAdmin(ModelAdmin):
    """YoungCart categorylist.php: the tree (two ca_id characters per level), item counts, and the
    order and use flags edited in the list."""

    form = CategoryAdminForm
    list_display = ("ca_id", "tree_name", "product_count", "ca_order", "ca_use", "add_child_link")
    list_display_links = ("ca_id", "tree_name")
    list_editable = ("ca_order", "ca_use")
    search_fields = ("ca_id", "ca_name")
    list_filter = ("ca_use",)
    ordering = ("ca_id",)
    readonly_fields = ("add_child_link",)
    fieldsets = (
        (None, {"fields": (("ca_id", "add_child_link"), "ca_name", "ca_parent", ("ca_order", "ca_use"), "ca_skin")}),
        ("출력설정", {
            "description": "상품 목록의 1줄당 이미지 수와 줄 수입니다. 한 쪽에 1줄당 수 × 줄 수(최대 100개)를 "
                           "보여 줍니다. 0 이면 기본 진열을 씁니다.",
            "fields": (("ca_list_mod", "ca_list_row"), ("ca_mobile_list_mod", "ca_mobile_list_row")),
        }),
        ("쿠폰", {"fields": ("ca_nocoupon",)}),
    )

    def get_changeform_initial_data(self, request):
        # categoryform.php: a new category starts at 3 x 5 and ?parent= proposes the next child code
        return {**new_category_initial(request), **super().get_changeform_initial_data(request)}

    @admin.display(description="하위분류")
    def add_child_link(self, obj):
        return add_child_category_button(obj)

    def get_deleted_objects(self, objs, request):
        # categoryformupdate.php refuses a category that still has child categories or products;
        # listing the reasons as "protected" makes Django's delete pages refuse it as well.
        deleted, model_count, perms_needed, protected = super().get_deleted_objects(objs, request)
        return deleted, model_count, perms_needed, [*protected, *protected_category_reasons(objs)]

    def delete_model(self, request, obj):
        if refuse_blocked_categories(self, request, [obj]):
            super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        allowed = refuse_blocked_categories(self, request, list(queryset))
        super().delete_queryset(request, queryset.filter(pk__in=[category.pk for category in allowed]))

    def get_queryset(self, request):
        # A product counts once for each category it belongs to through ca_id, ca_id2 or ca_id3.
        category = OuterRef("pk")
        members = (
            ShopProduct.objects.filter(Q(category=category) | Q(category2=category) | Q(category3=category))
            .order_by()
            .annotate(group=Value(1))
            .values("group")
            .annotate(total=Count("it_id"))
            .values("total")
        )
        return super().get_queryset(request).annotate(
            item_total=Coalesce(Subquery(members, output_field=IntegerField()), 0)
        )

    @admin.display(description=_("Category"), ordering="ca_id")
    def tree_name(self, obj):
        depth = max(len(obj.ca_id or "") // 2 - 1, 0)
        if not depth:
            return obj.ca_name
        return format_html('<span style="padding-left:{}rem">└ {}</span>', depth * 1.25, obj.ca_name)

    @admin.display(description="상품 수", ordering="item_total")
    def product_count(self, obj):
        total = getattr(obj, "item_total", 0)
        return format_html('<span data-product-count="{}">{}</span>', total, total)


@admin.register(ShopProduct)
class ShopProductAdmin(ModelAdmin):
    form = ShopProductAdminForm
    action_form = ShopProductActionForm
    actions = ("add_selected_to_event", "update_selected_product_type", "copy_selected_products")
    inlines = (ShopProductRelationInline,)
    list_before_template = "admin/shop/product_list_before.html"
    list_display = (
        "product_id_display",
        "product_name_display",
        "category",
        "sale_status",
        "stock_status",
        "product_type_summary",
        "product_price_display",
        "shipping_policy",
        "updated_at",
    )
    list_display_links = ("product_id_display", "product_name_display")
    search_fields = ("it_id", "it_name", "it_seo_title", "it_brand", "it_maker")
    list_filter = (
        "category",
        "it_use",
        "it_soldout",
        "it_notax",
        "it_type1",
        "it_type2",
        "it_type3",
        "it_type4",
        "it_type5",
    )
    readonly_fields = (
        "product_snapshot",
        "product_image_preview",
        "product_image_manager_link",
        "stock_adjustment_link",
        "product_copy_link",
        "updated_at",
    )
    fieldsets = (
        (
            _("Product snapshot"),
            {
                "classes": ("tab",),
                "fields": ("product_snapshot",),
            },
        ),
        (
            _("Product identity"),
            {
                "classes": ("tab",),
                "fields": (
                    ("it_id", "category"),
                    ("category2", "category3"),
                    ("it_name", "it_seo_title"),
                    ("it_brand", "it_maker"),
                    ("it_origin", "it_model"),
                    ("created_at", "updated_at"),
                    "product_copy_link",
                ),
            },
        ),
        (
            _("Pricing and points"),
            {
                "classes": ("tab",),
                "fields": (
                    ("it_price", "it_basic_price", "it_cust_price"),
                    ("it_point", "it_point_type"),
                    ("it_notax", "it_nocoupon"),
                ),
            },
        ),
        (
            _("Stock and purchase"),
            {
                "classes": ("tab",),
                "fields": (
                    ("it_stock_qty", "stock_adjustment_link", "it_stock_sms"),
                    ("it_buy_min_qty", "it_buy_max_qty"),
                    ("it_tel_inq", "it_soldout", "it_use"),
                ),
            },
        ),
        (
            _("Shipping policy"),
            {
                "classes": ("tab",),
                "fields": (
                    ("it_sc_type", "it_sc_method"),
                    ("it_sc_price", "it_sc_minimum", "it_sc_qty"),
                ),
            },
        ),
        (
            _("Display badges"),
            {
                "classes": ("tab",),
                "fields": (
                    ("it_type1", "it_type2", "it_type3", "it_type4", "it_type5"),
                ),
            },
        ),
        (
            _("Content"),
            {
                "classes": ("tab",),
                "fields": (
                    "it_basic",
                    "it_content",
                    "it_explan",
                    "it_head_html",
                    "it_tail_html",
                    "it_info_gubun",
                    "it_info_value",
                ),
            },
        ),
        (
            _("Images and options"),
            {
                "classes": ("tab",),
                "fields": (
                    "it_option_subject",
                    "it_supply_subject",
                    "product_image_preview",
                    "product_image_manager_link",
                    "image_url",
                    "images",
                    "options",
                ),
            },
        ),
    )
    list_fullwidth = True

    def get_readonly_fields(self, request, obj=None):
        fields = tuple(super().get_readonly_fields(request, obj))
        return fields + (("it_stock_qty",) if obj else ())

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.has_perm("shop.add_shopeventitem") or not request.user.has_perm("shop.change_shopeventitem"):
            actions.pop("add_selected_to_event", None)
        return actions

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<str:it_id>/images/",
                self.admin_site.admin_view(self.product_images_view),
                name="shop_shopproduct_images",
            ),
            path(
                "stock-adjustments/",
                self.admin_site.admin_view(self.stock_adjustments_view),
                name="shop_shopproduct_stock_adjustments",
            ),
            path(
                "<str:it_id>/copy/",
                self.admin_site.admin_view(self.product_copy_view),
                name="shop_shopproduct_copy",
            ),
        ]
        return custom_urls + urls

    @admin.display(description=_("Stock and adjustment history"))
    def stock_adjustment_link(self, obj):
        if not obj or not obj.pk:
            return "-"
        url = f"{reverse('admin:shop_shopproduct_stock_adjustments')}?{urlencode({'it_id': obj.it_id})}"
        return format_html('<a class="button" href="{}">{}</a>', url, _("Adjust stock / history"))

    @admin.display(description="상품 복사")
    def product_copy_link(self, obj):
        return product_copy_button(obj)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        # itemformupdate.php lists the product back on each related product
        mirror_product_relations(form.instance)

    def product_copy_view(self, request, it_id):
        """itemcopy.php: copy one product under a new code (default: the current unix time)."""
        source = ShopProduct.objects.filter(pk=it_id).first()
        if not source:
            raise Http404
        if not (self.has_add_permission(request) and self.has_view_permission(request, source)):
            raise PermissionDenied
        if request.method == "POST":
            form = ProductCopyForm(request.POST)
            if form.is_valid():
                try:
                    copy = copy_product(source, form.cleaned_data["new_it_id"])
                except ValidationError as error:
                    form.add_error("new_it_id", error)
                except IntegrityError:
                    form.add_error("new_it_id", "이미 존재하는 상품코드 입니다.")
                else:
                    self.message_user(
                        request,
                        f"{source.it_id} 상품을 {copy.it_id} 코드로 복사했습니다. 내용을 확인한 뒤 판매해 주세요.",
                        level=messages.SUCCESS,
                    )
                    return HttpResponseRedirect(reverse("admin:shop_shopproduct_change", args=[copy.it_id]))
        else:
            form = ProductCopyForm(initial={"new_it_id": next_product_id()})
        context = {
            **self.admin_site.each_context(request),
            "title": "상품 복사",
            "opts": self.model._meta,
            "product": source,
            "form": form,
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/shop/product_copy.html", context)

    @admin.action(description="선택 상품 복사", permissions=["add"])
    def copy_selected_products(self, request, queryset):
        copies, failures = copy_products(queryset)
        if copies:
            self.message_user(
                request,
                "상품 {}개를 복사했습니다: {}".format(
                    len(copies), ", ".join(f"{source.it_id} → {copy.it_id}" for source, copy in copies)
                ),
                level=messages.SUCCESS,
            )
        for source, error in failures:
            self.message_user(request, f"{source.it_id} 상품을 복사하지 못했습니다: {error}", level=messages.ERROR)

    @admin.display(description=_("Image management"))
    def product_image_manager_link(self, obj):
        if not obj or not obj.pk:
            return "-"
        url = reverse("admin:shop_shopproduct_images", args=[obj.it_id])
        return format_html('<a class="button" href="{}">{}</a>', url, _("Upload / manage product images"))

    def save_model(self, request, obj, form, change):
        if not change:
            return super().save_model(request, obj, form, change)

        with transaction.atomic():
            previous = ShopProduct.objects.select_for_update().filter(pk=obj.pk).first()
            previous_stock = previous.it_stock_qty if previous else obj.it_stock_qty
            previous_options = option_stock_map(previous.options if previous else [])
            if previous:
                obj.it_stock_qty = previous.it_stock_qty
                if "options" not in form.changed_data:
                    obj.options = previous.options
                elif isinstance(obj.options, list):
                    initial_options = option_stock_map(form.initial.get("options"))
                    current_options = option_stock_map(previous.options)
                    for option in obj.options:
                        if not isinstance(option, dict):
                            continue
                        try:
                            option_type = int(option.get("io_type") or 0)
                        except (TypeError, ValueError):
                            continue
                        option_id = str(option.get("io_id") or "").strip()
                        key = (option_type, option_id)
                        if (
                            key in current_options
                            and option_id
                            and option_stock_map([option]).get(key, 0) == initial_options.get(key, 0)
                        ):
                            option["io_stock_qty"] = current_options[key]
            super().save_model(request, obj, form, change)
            if previous is None:
                return

            if previous_stock != obj.it_stock_qty:
                ShopStockAdjustment.objects.create(
                    product=obj,
                    it_id=obj.it_id,
                    it_name=obj.it_name,
                    scope="product",
                    before_qty=previous_stock,
                    delta=obj.it_stock_qty - previous_stock,
                    after_qty=obj.it_stock_qty,
                    reason=_("Changed in product admin form."),
                    actor=request.user,
                )

            current_options = option_stock_map(obj.options)
            for option_type, option_id in sorted(set(previous_options) | set(current_options)):
                before_qty = previous_options.get((option_type, option_id), 0)
                after_qty = current_options.get((option_type, option_id), 0)
                if before_qty == after_qty:
                    continue
                ShopStockAdjustment.objects.create(
                    product=obj,
                    it_id=obj.it_id,
                    it_name=obj.it_name,
                    scope="option",
                    io_id=option_id,
                    io_type=option_type,
                    before_qty=before_qty,
                    delta=after_qty - before_qty,
                    after_qty=after_qty,
                    reason=_("Changed in product options form."),
                    actor=request.user,
                )

    def stock_adjustments_view(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        source = request.POST if request.method == "POST" else request.GET
        product_id = str(source.get("it_id") or "").strip()
        query = str(request.GET.get("q") or "").strip()[:120]
        error = ""
        form_values = {
            "scope": "product",
            "delta": "",
            "reason": "",
            "option_key": "",
        }
        product = ShopProduct.objects.filter(pk=product_id).first() if product_id else None

        if request.method == "POST":
            form_values.update(
                {
                    "scope": str(request.POST.get("scope") or "product"),
                    "delta": str(request.POST.get("delta") or "").strip(),
                    "reason": str(request.POST.get("reason") or "").strip(),
                    "option_key": str(request.POST.get("option_key") or "").strip(),
                }
            )
            if not product:
                error = _("Select a valid product before adjusting stock.")
            else:
                try:
                    delta = int(form_values["delta"])
                except (TypeError, ValueError):
                    delta = 0
                    error = _("Enter a whole-number stock adjustment.")
                reason = form_values["reason"]
                scope = form_values["scope"]
                if not error and delta == 0:
                    error = _("The stock adjustment must be non-zero.")
                elif not error and abs(delta) > 2_147_483_647:
                    error = _("The adjustment must be within the supported integer range.")
                elif not error and not reason:
                    error = _("Enter a reason for this stock adjustment.")
                elif not error and len(reason) > 255:
                    error = _("The reason must be 255 characters or fewer.")
                elif not error and scope not in {"product", "option"}:
                    error = _("Choose product stock or option stock.")

                option_type = None
                option_id = ""
                if not error and scope == "option":
                    encoded_type, separator, encoded_id = form_values["option_key"].partition(":")
                    try:
                        option_type = int(encoded_type)
                        option_id = unquote(encoded_id)
                    except (TypeError, ValueError):
                        option_type = -1
                    if not separator or option_type not in (0, 1) or not option_id:
                        error = _("Choose an option from this product.")

                if not error:
                    with transaction.atomic():
                        locked_product = ShopProduct.objects.select_for_update().filter(pk=product_id).first()
                        if not locked_product:
                            error = _("The product no longer exists.")
                        elif scope == "product":
                            before_qty = int(locked_product.it_stock_qty)
                            after_qty = before_qty + delta
                            if after_qty < 0:
                                error = _("Stock cannot be reduced below zero.")
                            elif after_qty > 2_147_483_647:
                                error = _("Stock exceeds the supported integer range.")
                            else:
                                locked_product.it_stock_qty = after_qty
                                fields = ["it_stock_qty", "updated_at"]
                                if after_qty <= 0:
                                    locked_product.it_soldout = "1"
                                    fields.append("it_soldout")
                                elif before_qty <= 0 and locked_product.it_soldout == "1":
                                    locked_product.it_soldout = ""
                                    fields.append("it_soldout")
                                locked_product.save(update_fields=fields)
                        else:
                            options = [dict(row) for row in (locked_product.options or []) if isinstance(row, dict)]
                            matched = None
                            for row in options:
                                try:
                                    row_type = int(row.get("io_type") or 0)
                                except (TypeError, ValueError):
                                    continue
                                if str(row.get("io_id") or "").strip() == option_id and row_type == option_type:
                                    matched = row
                                    break
                            if matched is None:
                                error = _("The selected option no longer exists.")
                            else:
                                try:
                                    before_qty = int(matched.get("io_stock_qty") or 0)
                                except (TypeError, ValueError):
                                    before_qty = -1
                                after_qty = before_qty + delta
                                if before_qty < 0:
                                    error = _("The selected option has invalid stock data; fix the option first.")
                                elif after_qty < 0:
                                    error = _("Option stock cannot be reduced below zero.")
                                elif after_qty > 2_147_483_647:
                                    error = _("Option stock exceeds the supported integer range.")
                                else:
                                    matched["io_stock_qty"] = after_qty
                                    locked_product.options = options
                                    locked_product.save(update_fields=["options", "updated_at"])

                        if not error:
                            ShopStockAdjustment.objects.create(
                                product=locked_product,
                                it_id=locked_product.it_id,
                                it_name=locked_product.it_name,
                                scope=scope,
                                io_id=option_id if scope == "option" else "",
                                io_type=option_type,
                                before_qty=before_qty,
                                delta=delta,
                                after_qty=after_qty,
                                reason=reason,
                                actor=request.user,
                            )
                    if not error:
                        self.message_user(request, _("Stock adjustment saved."), level=messages.SUCCESS)
                        redirect_url = reverse("admin:shop_shopproduct_stock_adjustments")
                        return HttpResponseRedirect(f"{redirect_url}?{urlencode({'it_id': product_id})}")

        if not product and product_id:
            error = error or _("Product not found.")
        option_rows = []
        if product:
            for option in product.options if isinstance(product.options, list) else []:
                if not isinstance(option, dict):
                    continue
                option_id = str(option.get("io_id") or "").strip()
                if not option_id:
                    continue
                try:
                    option_type = int(option.get("io_type") or 0)
                    stock = int(option.get("io_stock_qty") or 0)
                except (TypeError, ValueError):
                    continue
                if option_type not in (0, 1):
                    continue
                option_rows.append(
                    {
                        "key": f"{option_type}:{quote(option_id, safe='')}",
                        "id": option_id.replace("\x1e", " / "),
                        "type": option_type,
                        "type_label": _("Supply") if option_type else _("Choice"),
                        "stock": stock,
                        "use": option.get("io_use", 1),
                    }
                )

        products = ShopProduct.objects.only("it_id", "it_name", "it_stock_qty").order_by("it_name", "it_id")
        if query:
            products = products.filter(Q(it_id__icontains=query) | Q(it_name__icontains=query))
        recent_adjustments = (
            ShopStockAdjustment.objects.filter(it_id=product_id).select_related("actor").order_by("-created_at", "-pk")[:30]
            if product_id
            else ShopStockAdjustment.objects.select_related("actor").order_by("-created_at", "-pk")[:30]
        )
        context = {
            **self.admin_site.each_context(request),
            "title": _("Stock adjustment and history"),
            "subtitle": _("Adjust product or option stock with a reason and immutable change history."),
            "opts": self.model._meta,
            "report_path": request.path,
            "product": product,
            "products": products[:50],
            "query": query,
            "error": error,
            "form_values": form_values,
            "option_rows": option_rows,
            "adjustments": recent_adjustments,
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/shop/stock_adjustments.html", context)

    def product_images_view(self, request, it_id):
        product = ShopProduct.objects.filter(pk=it_id).first()
        if not product:
            raise Http404
        if not self.has_change_permission(request, product):
            raise PermissionDenied

        error = ""
        if request.method == "POST":
            action = str(request.POST.get("action") or "").strip()
            if action == "upload":
                files = [uploaded_file for _, uploaded_files in request.FILES.lists() for uploaded_file in uploaded_files]
                if not files:
                    error = _("Choose at least one image file to upload.")
                else:
                    try:
                        upload_product_images(it_id, files)
                    except ShopProduct.DoesNotExist:
                        raise Http404
                    except ValidationError as exc:
                        error = "; ".join(str(item) for item in exc.messages)
                    else:
                        self.message_user(request, _("Product images uploaded."), level=messages.SUCCESS)
                        return HttpResponseRedirect(reverse("admin:shop_shopproduct_images", args=[it_id]))
            elif action in {"set_primary", "remove"}:
                target_url = str(request.POST.get("image_url") or "").strip()
                with transaction.atomic():
                    product = ShopProduct.objects.select_for_update().filter(pk=it_id).first()
                    if not product:
                        raise Http404
                    available_urls = admin_product_image_urls(product)
                    if target_url not in available_urls:
                        error = _("That image is no longer attached to this product. Refresh the page and try again.")
                    elif action == "set_primary" and not isinstance(product.images, list):
                        error = _("Product image data must be a list before a primary image can be changed.")
                    elif action == "set_primary":
                        primary_url = admin_product_image_url(product.image_url)
                        if primary_url == target_url:
                            error = _("That image is already the primary image.")
                        else:
                            images = product.images if isinstance(product.images, list) else []
                            if primary_url and not any(
                                admin_product_image_url(image) == primary_url for image in images
                            ):
                                images = [*images, product.image_url]
                            primary_images = [
                                image for image in images if admin_product_image_url(image) == target_url
                            ]
                            additional_images = [
                                image for image in images if admin_product_image_url(image) != target_url
                            ]
                            product.images = [
                                primary_images[0] if primary_images else target_url,
                                *additional_images,
                            ]
                            product.image_url = target_url
                            product.save(update_fields=["images", "image_url", "updated_at"])
                    elif not isinstance(product.images, list):
                        error = _("Product image data must be a list before an image can be removed.")
                    else:
                        remaining_images = []
                        storage_paths = []
                        for image in product.images:
                            if admin_product_image_url(image) == target_url:
                                storage_path = managed_product_image_storage_path(image, product.it_id)
                                if storage_path:
                                    storage_paths.append(storage_path)
                            else:
                                remaining_images.append(image)
                        old_primary_url = admin_product_image_url(product.image_url)
                        product.images = remaining_images
                        if old_primary_url == target_url:
                            product.image_url = next(
                                (url for image in remaining_images if (url := admin_product_image_url(image))),
                                "",
                            )
                        product.save(update_fields=["images", "image_url", "updated_at"])
                        if storage_paths:
                            transaction.on_commit(
                                lambda paths=tuple(storage_paths): delete_product_image_after_commit(paths)
                            )

                if not error:
                    message = _("Primary image updated.") if action == "set_primary" else _("Image removed from the product.")
                    self.message_user(request, message, level=messages.SUCCESS)
                    return HttpResponseRedirect(reverse("admin:shop_shopproduct_images", args=[it_id]))
            else:
                error = _("Choose an image action.")

        product.refresh_from_db()
        context = {
            **self.admin_site.each_context(request),
            "title": _("Product image management"),
            "subtitle": _("Upload validated product images, choose the storefront primary image, or remove an image."),
            "opts": self.model._meta,
            "product": product,
            "image_rows": admin_product_image_rows(product),
            "error": error,
            "image_max_size_mb": int(
                getattr(settings, "SHOP_PRODUCT_IMAGE_MAX_UPLOAD_SIZE", 5 * 1024 * 1024)
            )
            // (1024 * 1024),
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/shop/product_images.html", context)

    @admin.action(description=_("Add selected products to event"), permissions=["change"])
    def add_selected_to_event(self, request, queryset):
        event = ShopEvent.objects.filter(pk=request.POST.get("target_event"), ev_use=True).first()
        if not event:
            self.message_user(
                request,
                _("Choose an active target event before running this action."),
                level=messages.ERROR,
            )
            return
        if not request.user.has_perm("shop.add_shopeventitem") or not request.user.has_perm("shop.change_shopeventitem"):
            self.message_user(
                request,
                _("You need add and change permissions for event products to run this action."),
                level=messages.ERROR,
            )
            return

        products = list(queryset.only("it_id"))
        product_by_id = {product.it_id: product for product in products}
        product_ids = list(product_by_id)
        if not product_ids:
            return

        with transaction.atomic():
            existing_links = {
                link.it_id: link
                for link in ShopEventItem.objects.filter(event=event, it_id__in=product_ids)
            }
            new_links = []
            updated_links = []
            for product in products:
                existing = existing_links.get(product.it_id)
                if existing is None:
                    new_links.append(ShopEventItem(event=event, product=product, it_id=product.it_id))
                elif existing.product_id != product.it_id:
                    existing.product = product
                    updated_links.append(existing)

            ShopEventItem.objects.bulk_create(new_links, batch_size=500, ignore_conflicts=True)
            ShopEventItem.objects.bulk_update(updated_links, ("product",), batch_size=500)

        self.message_user(
            request,
            _("Added %(added)s product(s), repaired %(repaired)s link(s), and skipped %(skipped)s existing link(s) for “%(event)s”.")
            % {
                "added": format_number(len(new_links)),
                "repaired": format_number(len(updated_links)),
                "skipped": format_number(len(existing_links) - len(updated_links)),
                "event": event.ev_subject,
            },
            level=messages.SUCCESS,
        )

    @admin.action(description=_("Update selected products' display type"), permissions=["change"])
    def update_selected_product_type(self, request, queryset):
        type_number = str(request.POST.get("product_type") or "").strip()
        operation = str(request.POST.get("product_type_operation") or "").strip()
        type_fields = {str(index): field for index, (field, _) in enumerate(PRODUCT_TYPE_FIELDS, 1)}
        type_field = type_fields.get(type_number)
        if type_field is None or operation not in {"show", "hide"}:
            self.message_user(
                request,
                _("Choose a product type and whether to add or remove it before running this action."),
                level=messages.ERROR,
            )
            return

        desired_value = "1" if operation == "show" else ""
        selected_count = queryset.count()
        with transaction.atomic():
            changed_count = queryset.exclude(**{type_field: desired_value}).update(
                **{type_field: desired_value, "updated_at": timezone.now()}
            )
        unchanged_count = selected_count - changed_count
        self.message_user(
            request,
            _("Updated %(changed)s product(s); %(unchanged)s already had the requested type state.")
            % {"changed": format_number(changed_count), "unchanged": format_number(unchanged_count)},
            level=messages.SUCCESS if changed_count else messages.WARNING,
        )

    @admin.display(description=_("Product ID"), ordering="it_id")
    def product_id_display(self, obj):
        return obj.it_id

    @admin.display(description=_("Product"), ordering="it_name")
    def product_name_display(self, obj):
        return obj.it_name

    @admin.display(description=_("Display types"))
    def product_type_summary(self, obj):
        active_types = [label for field, label in PRODUCT_TYPE_FIELDS if flag_enabled(getattr(obj, field))]
        if not active_types:
            return badge(_("No display type"), "neutral")
        return format_html_join(
            " ",
            '<span class="g5-admin-badge g5-admin-badge-info">{}</span>',
            ((label,) for label in active_types),
        )

    @admin.display(description=_("Sale status"), ordering="it_use")
    def sale_status(self, obj):
        if not flag_enabled(obj.it_use):
            return badge(_("Hidden"), "neutral")
        if flag_enabled(obj.it_soldout):
            return badge(_("Sold out"), "danger")
        if flag_enabled(obj.it_tel_inq):
            return badge(_("Phone inquiry"), "info")
        return badge(_("Selling"), "success")

    @admin.display(description=_("Stock"), ordering="it_stock_qty")
    def stock_status(self, obj):
        if flag_enabled(obj.it_soldout):
            return badge(_("Sold out"), "danger")
        if obj.it_stock_qty <= 0:
            return badge(_("No stock"), "danger")
        if obj.it_stock_qty <= 5:
            return badge(_("%(count)s left") % {"count": format_number(obj.it_stock_qty)}, "warning")
        return badge(format_number(obj.it_stock_qty), "success")

    @admin.display(description=_("Price"), ordering="it_price")
    def product_price_display(self, obj):
        return money_html(obj.it_price)

    @admin.display(description=_("Shipping"))
    def shipping_policy(self, obj):
        if obj.it_sc_price <= 0:
            return badge(_("Free shipping"), "success")
        return badge(format_number(obj.it_sc_price), "info")

    @admin.display(description=_("Product snapshot"))
    def product_snapshot(self, obj):
        if not obj:
            return "-"
        if not flag_enabled(obj.it_use):
            state, tone = _("Hidden"), "neutral"
        elif flag_enabled(obj.it_soldout) or obj.it_stock_qty <= 0:
            state, tone = _("Sold out"), "danger"
        elif obj.it_stock_qty <= 5:
            state, tone = _("Low stock"), "warning"
        elif flag_enabled(obj.it_tel_inq):
            state, tone = _("Phone inquiry"), "info"
        else:
            state, tone = _("Selling"), "success"

        option_count = len(obj.options or [])
        image_count = len(obj.images or [])
        return snapshot_panel(
            _("Product snapshot"),
            state,
            tone,
            _("Review sale exposure, price, stock, shipping, and storefront assets together."),
            (
                (_("Sale exposure"), obj.it_name, compact_text(obj.it_id, getattr(obj.category, "ca_name", ""))),
                (_("Price and point"), format_number(obj.it_price), _("Point %(point)s") % {"point": format_number(obj.it_point)}),
                (_("Stock and purchase"), format_number(obj.it_stock_qty), _("Min %(min)s / max %(max)s") % {"min": format_number(obj.it_buy_min_qty), "max": format_number(obj.it_buy_max_qty)}),
                (_("Shipping fee"), format_number(obj.it_sc_price), _("Free over %(amount)s") % {"amount": format_number(obj.it_sc_minimum)}),
                (_("Assets"), _("%(images)s images / %(options)s options") % {"images": format_number(image_count), "options": format_number(option_count)}, obj.image_url or "-"),
                (_("Updated"), datetime_value(obj.updated_at), datetime_value(obj.created_at)),
            ),
        )

    @admin.display(description=_("Image preview"))
    def product_image_preview(self, obj):
        if not obj:
            return "-"
        urls = admin_product_image_urls(obj)
        if not urls:
            return format_html('<span class="g5-admin-product-image-empty">{}</span>', _("No product image is configured."))
        preview_count = min(len(urls), 6)
        return format_html(
            '<div class="g5-admin-product-image-gallery">{}</div><p class="g5-admin-product-image-count">{}</p>',
            format_html_join(
                "",
                '<a class="g5-admin-product-image-thumb" href="{}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer" aria-label="{}"><img src="{}" alt="" loading="lazy" decoding="async"></a>',
                ((url, _("Open product image"), url) for url in urls[:preview_count]),
            ),
            _("Showing %(shown)s of %(total)s configured images.")
            % {"shown": format_number(preview_count), "total": format_number(len(urls))},
        )


@admin.register(ShopStockAdjustment)
class ShopStockAdjustmentAdmin(ModelAdmin):
    actions = None
    list_display = (
        "created_at",
        "product_id_display",
        "scope_display",
        "option_display",
        "before_qty",
        "delta_display",
        "after_qty",
        "actor_display",
        "reason_display",
    )
    list_filter = ("scope", "io_type", "created_at")
    search_fields = ("it_id", "it_name", "io_id", "reason", "actor__username")
    list_select_related = ("product", "actor")
    list_fullwidth = True
    readonly_fields = (
        "product",
        "it_id",
        "it_name",
        "scope",
        "io_id",
        "io_type",
        "before_qty",
        "delta",
        "after_qty",
        "reason",
        "actor",
        "created_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description=_("Product"), ordering="it_id")
    def product_id_display(self, obj):
        return compact_text(obj.it_name, obj.it_id)

    @admin.display(description=_("Stock scope"), ordering="scope")
    def scope_display(self, obj):
        return badge(obj.get_scope_display(), "info" if obj.scope == "option" else "neutral")

    @admin.display(description=_("Option"), ordering="io_id")
    def option_display(self, obj):
        if obj.scope != "option":
            return "-"
        option_type = obj.get_io_type_display() if hasattr(obj, "get_io_type_display") else obj.io_type
        return compact_text(obj.io_id, option_type)

    @admin.display(description=_("Adjustment"), ordering="delta")
    def delta_display(self, obj):
        tone = "success" if obj.delta > 0 else "danger" if obj.delta < 0 else "neutral"
        return badge(f"{obj.delta:+,}", tone)

    @admin.display(description=_("Actor"), ordering="actor__username")
    def actor_display(self, obj):
        return obj.actor.get_username() if obj.actor_id and obj.actor else _("Deleted user")

    @admin.display(description=_("Reason"))
    def reason_display(self, obj):
        return compact_text(obj.reason, limit=100)


@admin.register(ShopEvent)
class ShopEventAdmin(ModelAdmin):
    list_display = ("ev_id", "ev_subject", "ev_use", "event_product_count")
    list_display_links = ("ev_id", "ev_subject")
    list_filter = ("ev_use", "ev_subject_strong")
    search_fields = ("ev_subject",)
    readonly_fields = ("ev_id", "event_product_count")
    fieldsets = (
        (_("Event"), {"fields": (("ev_id", "ev_use"), ("ev_subject", "ev_subject_strong"))}),
        (_("Desktop layout"), {"classes": ("tab",), "fields": ("ev_skin", ("ev_img_width", "ev_img_height"), ("ev_list_mod", "ev_list_row"))}),
        (_("Mobile layout"), {"classes": ("tab",), "fields": ("ev_mobile_skin", ("ev_mobile_img_width", "ev_mobile_img_height"), ("ev_mobile_list_mod", "ev_mobile_list_row"))}),
        (_("Event content"), {"classes": ("tab",), "fields": (("ev_head_image", "ev_tail_image"), "ev_head_html", "ev_tail_html")}),
        (_("Products"), {"fields": ("event_product_count",)}),
    )

    @admin.display(description=_("Products"))
    def event_product_count(self, obj):
        return obj.items.filter(product__it_use="1").count() if obj and obj.pk else 0


class ShopEventItemAdminForm(forms.ModelForm):
    class Meta:
        model = ShopEventItem
        fields = ("event", "product")

    def clean_product(self):
        product = self.cleaned_data.get("product")
        if not product:
            raise forms.ValidationError(_("Select a product for this event."))
        return product

    def clean(self):
        cleaned_data = super().clean()
        event = cleaned_data.get("event")
        product = cleaned_data.get("product")
        if event and product:
            duplicates = ShopEventItem.objects.filter(event=event, it_id=product.it_id)
            if self.instance.pk:
                duplicates = duplicates.exclude(pk=self.instance.pk)
            if duplicates.exists():
                self.add_error("product", forms.ValidationError(_("This product is already linked to the event.")))
        return cleaned_data


@admin.register(ShopEventItem)
class ShopEventItemAdmin(ModelAdmin):
    list_display = ("event", "it_id", "product")
    list_display_links = ("event", "it_id")
    list_filter = ("event__ev_use",)
    search_fields = ("event__ev_subject", "it_id", "product__it_name")
    autocomplete_fields = ("event", "product")
    form = ShopEventItemAdminForm

    def save_model(self, request, obj, form, change):
        obj.it_id = obj.product.it_id
        super().save_model(request, obj, form, change)



@admin.register(ShopOrderItem)
class ShopOrderItemAdmin(ModelAdmin):
    list_display = (
        "ct_id",
        "order_link",
        "product_display",
        "ct_status",
        "ct_qty",
        "price_display",
        "line_total_display",
        "stock_adjusted",
    )
    list_filter = ("ct_status", "stock_adjusted", "order__od_datetime")
    search_fields = ("ct_id", "it_id", "it_name", "order__od_id", "order__od_name")
    ordering = ("-order__od_datetime", "-ct_id")
    list_select_related = ("order", "product")
    list_per_page = 50
    readonly_fields = (
        "ct_id",
        "order",
        "product",
        "it_id",
        "it_name",
        "ct_price",
        "ct_qty",
        "ct_point",
        "ct_option",
        "ct_status",
        "io_type",
        "io_price",
        "ct_send_cost",
        "stock_adjusted",
        "image_url",
    )
    fields = readonly_fields

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        # a line deleted on its own leaves the order total and the reserved stock wrong; lines go
        # only with their order (ShopOrderAdmin deletes unpaid or cancelled orders)
        return False

    @admin.display(description=_("Order"), ordering="order__od_id")
    def order_link(self, obj):
        if not obj.order_id:
            return "-"
        return format_html('<a href="/admin/shop/shoporder/{}/change/">{}</a>', obj.order_id, obj.order_id)

    @admin.display(description=_("Product"), ordering="it_name")
    def product_display(self, obj):
        if obj.product_id:
            return format_html('<a href="/admin/shop/shopproduct/{}/change/">{}</a><br><small>{}</small>', obj.product_id, obj.it_name or obj.product_id, obj.it_id)
        return format_html("<strong>{}</strong><br><small>{}</small>", obj.it_name or "-", obj.it_id or "-")

    @admin.display(description=_("Price"), ordering="ct_price")
    def price_display(self, obj):
        return money_html(order_line_unit_price(obj))

    @admin.display(description=_("Line total"))
    def line_total_display(self, obj):
        return money_html(order_line_unit_price(obj) * obj.ct_qty)

