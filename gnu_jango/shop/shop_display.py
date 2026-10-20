"""Public shop display values built from the youngcart display settings (shop_options).

The admin saves these as Config rows; this module only shapes them for the APIs:

* ``home_display()`` - one block per home section (types 1..5) for the shop home snapshot.
* ``list_display()`` - search / type-list page sizes and grid columns, and the related-products switch,
  delivered to the browser in the public settings (``shop_display``).
* ``public_logo_urls()`` - the uploaded shop logos under public API names.
"""

from .shop_options import HOME_LIST_TYPES, shop_logo_urls, shop_options

MAX_PRODUCT_PAGE_SIZE = 100  # paginate_queryset's max_per_page in api/shop_common.py

# Public API name -> Config row of the uploaded logo.
PUBLIC_LOGO_FIELDS = {
    "shop_logo": "de_logo_img",
    "shop_logo_footer": "de_logo_img2",
    "shop_logo_mobile": "de_mobile_logo_img",
    "shop_logo_mobile_footer": "de_mobile_logo_img2",
}


def _home_option_names(number):
    return (
        f"de_type{number}_list_use", f"de_type{number}_list_mod", f"de_type{number}_list_row",
        f"de_mobile_type{number}_list_mod", f"de_mobile_type{number}_list_row",
    )


def home_display():
    """{"type1": {"use", "pc_cols", "pc_count", "mobile_cols", "mobile_count", "count"}, ...}.

    ``count`` is how many products the snapshot fetches: enough for the larger of the two screens.
    """
    names = [name for number, _title in HOME_LIST_TYPES for name in _home_option_names(number)]
    values = shop_options(*names)
    display = {}
    for number, _title in HOME_LIST_TYPES:
        use, pc_cols, pc_rows, mobile_cols, mobile_rows = (values[name] for name in _home_option_names(number))
        pc_count, mobile_count = pc_cols * pc_rows, mobile_cols * mobile_rows
        display[f"type{number}"] = {
            "use": bool(use),
            "pc_cols": pc_cols,
            "pc_count": pc_count,
            "mobile_cols": mobile_cols,
            "mobile_count": mobile_count,
            "count": max(pc_count, mobile_count) if use else 0,
        }
    return display


def _grid(values, prefix):
    pc_cols = values[f"de_{prefix}_list_mod"]
    rows = values[f"de_{prefix}_list_row"]
    return {
        "pc_cols": pc_cols,
        "rows": rows,
        # the products API serves at most MAX_PRODUCT_PAGE_SIZE per page
        "per_page": min(MAX_PRODUCT_PAGE_SIZE, pc_cols * rows),
        "mobile_cols": values[f"de_mobile_{prefix}_list_mod"],
    }


def list_display():
    values = shop_options(
        "de_search_list_mod", "de_search_list_row", "de_mobile_search_list_mod",
        "de_listtype_list_mod", "de_listtype_list_row", "de_mobile_listtype_list_mod",
        "de_rel_list_use", "de_rel_list_mod", "de_mobile_rel_list_mod",
    )
    return {
        "search": _grid(values, "search"),
        "listtype": _grid(values, "listtype"),
        "related": {
            "use": bool(values["de_rel_list_use"]),
            "pc_cols": values["de_rel_list_mod"],
            "mobile_cols": values["de_mobile_rel_list_mod"],
        },
    }


def related_list_enabled():
    return bool(shop_options("de_rel_list_use")["de_rel_list_use"])


def public_logo_urls():
    urls = shop_logo_urls()
    return {public: urls.get(row, "") for public, row in PUBLIC_LOGO_FIELDS.items()}
