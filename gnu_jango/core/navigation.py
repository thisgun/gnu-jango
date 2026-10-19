"""The site's navigation, for the menus API and for the runtime config of Next.js theme pages.

The theme export is shared by every installation, so it cannot carry any site's menus or boards;
Django hands them over at request time instead (see core.views runtime config).
"""

from gnu_jango.bbs.models import Board
from gnu_jango.config import config
from gnu_jango.templatetags.gnu_menus import get_items

# Enough for a "community" dropdown; a site with more boards should configure its menus.
NAV_BOARD_LIMIT = 8
_MENU_KEYS = (
    "id",
    "me_code",
    "me_name",
    "me_link",
    "me_type",
    "me_type_pk",
    "me_target",
    "me_order",
    "me_use",
    "me_mobile_use",
)


def _menu_item(menu):
    item = {key: getattr(menu, key) for key in _MENU_KEYS if hasattr(menu, key)}
    item["me_id"] = item.get("id")  # the frontend MenuItem type names the key me_id
    return item


def site_menu_items(current_path, user):
    """The main menu as the menus API returns it: top-level items with their children."""
    menus = []
    for menu in get_items("main_menu", current_path, user).values():
        item = _menu_item(menu)
        item["children"] = [_menu_item(child) for child in getattr(menu, "sub", [])]
        menus.append(item)
    return menus


def navigation_boards():
    """Boards a visitor without an account may list, for the header when no menu is configured.

    The manual (handbook) group is left out: its boards are books, not community boards.
    """
    boards = Board.objects.filter(bo_list_level__lte=1)
    docs_group = str(config.get_all().get("cf_docs_group") or "").strip()
    if docs_group:
        boards = boards.exclude(group__gr_id=docs_group)
    rows = boards.order_by("group__gr_order", "bo_order", "pk").values_list("bo_table", "bo_subject")[:NAV_BOARD_LIMIT]
    return [{"bo_table": table, "bo_subject": subject or table} for table, subject in rows]
