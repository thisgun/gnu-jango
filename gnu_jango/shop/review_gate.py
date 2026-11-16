"""Which order lines count as a received product for the review gate (YoungCart check_itemuse_write)."""

from .models import ShopOrderItem
from .order_statuses import STATUS_COMPLETED


def received_lines():
    return ShopOrderItem.objects.filter(ct_status=STATUS_COMPLETED)
