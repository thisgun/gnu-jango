"""The youngcart order and order-line statuses (g5_shop_order.od_status, g5_shop_cart.ct_status).

youngcart adm/shop_admin/orderformcartupdate.php splits them into $status_normal (주문, 입금,
준비, 배송, 완료) and $status_cancel (취소, 반품, 품절); lib/shop.lib.php get_order_info prices
only the normal ones."""

STATUS_ORDERED = "주문"
STATUS_PAID = "입금"
STATUS_READY = "준비"
STATUS_SHIPPING = "배송"
STATUS_COMPLETED = "완료"
STATUS_CANCELLED = "취소"
STATUS_RETURNED = "반품"
STATUS_SOLD_OUT = "품절"

ACTIVE_LINE_STATUSES = (STATUS_ORDERED, STATUS_PAID, STATUS_READY, STATUS_SHIPPING, STATUS_COMPLETED)
# A line in one of these counts for nothing (no price, no sale, no further status move) and an
# order in one of them is closed. Older rows spell 취소 in English.
INACTIVE_LINE_STATUSES = frozenset({STATUS_CANCELLED, STATUS_RETURNED, STATUS_SOLD_OUT, "cancel", "cancelled"})
