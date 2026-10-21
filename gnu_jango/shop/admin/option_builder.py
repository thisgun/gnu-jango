"""Admin option builder for ShopProduct.options (youngcart itemform.php 선택옵션 / 추가옵션).

The widget keeps the option rows as JSON in a textarea and draws youngcart's builder over it
(admin_next/js/product_option_builder.js): option names with comma separated values generate the
combination rows, supplement names and values generate the supplement rows, and every row has its
extra price, stock, notice quantity and use flag. Power users can switch to the raw JSON. The
server checks whatever arrives with gnu_jango.shop.product_options.
"""

from django import forms

from gnu_jango.shop.product_options import (
    DEFAULT_OPTION_NOTI,
    DEFAULT_OPTION_STOCK,
    MAX_OPTION_LEVELS,
)


class OptionBuilderWidget(forms.Textarea):
    template_name = "admin/shop/widgets/option_builder.html"

    class Media:
        css = {"all": ("admin_next/css/product_option_builder.css",)}
        js = ("admin_next/js/product_option_builder.js",)

    def __init__(self, attrs=None):
        super().__init__({"rows": 8, "spellcheck": "false", **(attrs or {})})

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["builder"] = {
            "max_levels": MAX_OPTION_LEVELS,
            "default_stock": DEFAULT_OPTION_STOCK,
            "default_noti": DEFAULT_OPTION_NOTI,
            "subject_field": "it_option_subject",
            "supply_field": "it_supply_subject",
        }
        return context
