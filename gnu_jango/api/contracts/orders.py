"""Response contracts of the shop cart and order reads.

* ``GET /api/v1/shop/cart`` - ``shop_cart.cart_payload``: the member's cart (a Config row) or a
  guest's (the session), the same shape for both.
* ``GET /api/v1/shop/orders`` - ``v1_shop.order_payload(order)`` per order, numbered-page meta.
* ``GET /api/v1/shop/orders/{od_id}`` - ``order_payload(order, detail=True)``: the list shape plus
  the order lines, the cash receipt offer and the shipment tracking.

Neither the cart lines nor the order lines nest a product payload: they copy the few product
columns they need, so nothing of ``contracts.shop`` is reused here.
"""

from rest_framework import serializers


class ShopCartLineSerializer(serializers.Serializer):
    """``shop_cart.cart_item_payload``. A line whose product was deleted still renders, with the
    stored name (or the it_id) and fallback shipping / stock values."""

    ct_id = serializers.CharField(allow_blank=True)
    it_id = serializers.CharField(allow_blank=True)
    it_name = serializers.CharField(allow_blank=True)
    it_seo_title = serializers.CharField(allow_blank=True)
    ct_price = serializers.IntegerField()
    ct_qty = serializers.IntegerField()
    # the option's io_id ("" for a product without options)
    ct_option = serializers.CharField(allow_blank=True)
    # 0 선택옵션 (or no option), 1 추가옵션: an 추가옵션 line costs io_price alone
    io_type = serializers.IntegerField()
    io_price = serializers.IntegerField()
    # 0 / 1 int flag: a 바로구매 line (left out of the regular cart view)
    ct_direct = serializers.IntegerField()
    # 0 prepaid, 1 on delivery, 2 free (shipping.cart_send_cost_flag)
    ct_send_cost = serializers.IntegerField()
    it_sc_type = serializers.IntegerField()
    it_sc_method = serializers.IntegerField()
    it_sc_price = serializers.IntegerField()
    it_sc_minimum = serializers.IntegerField()
    it_sc_qty = serializers.IntegerField()
    line_total = serializers.IntegerField()
    # the stored column as is (0 when unset), unlike ShopProduct.it_basic_price
    it_basic_price = serializers.IntegerField()
    it_stock_qty = serializers.IntegerField()
    it_notax = serializers.IntegerField()
    ct_notax = serializers.IntegerField()
    # "1" / "" string flags (YoungCart char(1) columns)
    it_soldout = serializers.CharField(allow_blank=True)
    it_use = serializers.CharField(allow_blank=True)
    it_tel_inq = serializers.CharField(allow_blank=True)
    # a 240px copy of the main picture; "/icon-192.png" when the product is gone
    image_url = serializers.CharField(allow_blank=True)
    # a product coupon applied to the line (0 / "" without one)
    cp_price = serializers.IntegerField()
    cp_id = serializers.CharField(allow_blank=True)


class ShopCartSerializer(serializers.Serializer):
    """``shop_cart.cart_payload``: the lines (``?ct_ids=`` selects some, 바로구매 lines included)
    and their totals; every amount is 0 for an empty cart."""

    items = ShopCartLineSerializer(many=True)
    total_price = serializers.IntegerField()
    total_qty = serializers.IntegerField()
    cart_coupon = serializers.IntegerField()
    # base + remote-area fee; shipping_cost repeats send_cost
    send_cost = serializers.IntegerField()
    # the remote-area part (``?od_b_zip=`` / ``zip`` / ``zip1``+``zip2``)
    send_cost2 = serializers.IntegerField()
    shipping_cost = serializers.IntegerField()


class ShopOrderLineSerializer(serializers.Serializer):
    """``v1_shop.order_item_payload``: one ShopOrderItem."""

    ct_id = serializers.CharField(allow_blank=True)
    it_id = serializers.CharField(allow_blank=True)
    it_name = serializers.CharField(allow_blank=True)
    # "" when the product was deleted
    it_seo_title = serializers.CharField(allow_blank=True)
    ct_price = serializers.IntegerField()
    ct_qty = serializers.IntegerField()
    ct_point = serializers.IntegerField()
    line_total = serializers.IntegerField()
    line_point = serializers.IntegerField()
    ct_option = serializers.CharField(allow_blank=True)
    # stored as is (주문, 입금, 준비, 배송, 완료, 취소, 반품, 품절 ...), not normalised like od_status
    ct_status = serializers.CharField(allow_blank=True)
    # 0 / 1 int copy of stock_adjusted (YoungCart ct_stock_use)
    ct_stock_use = serializers.IntegerField()
    stock_adjusted = serializers.BooleanField()
    io_type = serializers.IntegerField()
    io_price = serializers.IntegerField()
    ct_notax = serializers.IntegerField()
    ct_send_cost = serializers.IntegerField()
    image_url = serializers.CharField(allow_blank=True)


# Named enum components (SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"]).
CASH_RECEIPT_STATES = ["available", "requested", "issued", "cancel_needed", "unavailable"]
CASH_RECEIPT_TYPES = ["income", "expense"]


class CashReceiptTypeSerializer(serializers.Serializer):
    # cash_receipt_toss.TOSS_RECEIPT_TYPES keys
    value = serializers.ChoiceField(choices=CASH_RECEIPT_TYPES)
    label = serializers.CharField()


class ShopOrderCashReceiptSerializer(serializers.Serializer):
    """``shop.cash_receipts.customer_payload``: whether the customer may request a cash receipt."""

    # issued / cancel_needed / requested / available / unavailable
    # shop/cash_receipts.receipt_state
    state = serializers.ChoiceField(choices=CASH_RECEIPT_STATES)
    can_request = serializers.BooleanField()
    # 0 unless the state is "available"
    amount = serializers.IntegerField()
    types = CashReceiptTypeSerializer(many=True)
    message = serializers.CharField(allow_blank=True)
    # "" unless the state is "available"
    request_url = serializers.CharField(allow_blank=True)


class ShopOrderTrackingEventSerializer(serializers.Serializer):
    """One Delivery Tracker event of ``shop.delivery_tracking.tracking_payload``."""

    # RFC 3339 with the carrier's offset, "" when the carrier gave no time
    time = serializers.CharField(allow_blank=True)
    # Delivery Tracker TrackEventStatusCode (IN_TRANSIT, DELIVERED, ...)
    status = serializers.CharField()
    # the carrier's own wording, else the Korean label of the status
    status_label = serializers.CharField()
    location = serializers.CharField(allow_blank=True)
    description = serializers.CharField(allow_blank=True)


class ShopOrderShipmentTrackingSerializer(serializers.Serializer):
    """``shop.delivery_tracking.tracking_payload``: the latest tracking of the order's invoice."""

    carrier_id = serializers.CharField()
    # TrackEventStatusCode of the most likely current event, "" before the first event
    status = serializers.CharField(allow_blank=True)
    status_label = serializers.CharField(allow_blank=True)
    delivered = serializers.BooleanField()
    # ISO date-times in the site's time zone, "" when unknown
    delivered_at = serializers.CharField(allow_blank=True)
    last_event_at = serializers.CharField(allow_blank=True)
    last_checked_at = serializers.CharField(allow_blank=True)
    # newest first, at most 30
    events = ShopOrderTrackingEventSerializer(many=True)


class ShopOrderSerializer(serializers.Serializer):
    """``v1_shop.order_payload(order)`` as the order list shows it.

    Dates and times are ISO strings or "" (``od_datetime``, ``od_time``, ``od_hope_date``);
    ``od_receipt_time``, ``od_invoice_time`` and ``od_vbank_due_date`` are stored text."""

    od_id = serializers.CharField()
    uid = serializers.CharField()
    # "" for a guest order
    mb_id = serializers.CharField(allow_blank=True)
    item_count = serializers.IntegerField()
    od_cart_count = serializers.IntegerField()
    od_name = serializers.CharField(allow_blank=True)
    od_tel = serializers.CharField(allow_blank=True)
    od_hp = serializers.CharField(allow_blank=True)
    od_email = serializers.CharField(allow_blank=True)
    od_zip = serializers.CharField(allow_blank=True)
    od_addr1 = serializers.CharField(allow_blank=True)
    od_addr2 = serializers.CharField(allow_blank=True)
    od_addr3 = serializers.CharField(allow_blank=True)
    od_b_name = serializers.CharField(allow_blank=True)
    od_b_tel = serializers.CharField(allow_blank=True)
    od_b_hp = serializers.CharField(allow_blank=True)
    od_b_zip = serializers.CharField(allow_blank=True)
    od_b_addr1 = serializers.CharField(allow_blank=True)
    od_b_addr2 = serializers.CharField(allow_blank=True)
    od_b_addr3 = serializers.CharField(allow_blank=True)
    od_memo = serializers.CharField(allow_blank=True)
    od_hope_date = serializers.CharField(allow_blank=True)
    od_cart_price = serializers.IntegerField()
    od_send_cost = serializers.IntegerField()
    od_send_cost2 = serializers.IntegerField()
    od_receipt_price = serializers.IntegerField()
    od_cancel_price = serializers.IntegerField()
    od_refund_price = serializers.IntegerField()
    od_receipt_point = serializers.IntegerField()
    od_deposit_name = serializers.CharField(allow_blank=True)
    # normalised to 주문 / 입금 / 배송 / 취소 where it is one of their aliases; other stored
    # statuses (준비, 완료, 반품 ...) pass through
    od_status = serializers.CharField()
    od_settle_case = serializers.CharField(allow_blank=True)
    # "" unless the order is paid by bank deposit
    od_bank_account = serializers.CharField(allow_blank=True)
    # the virtual account: "" in the order list, filled on the detail only
    od_vbank_bank_code = serializers.CharField(allow_blank=True)
    od_vbank_account = serializers.CharField(allow_blank=True)
    od_vbank_customer_name = serializers.CharField(allow_blank=True)
    od_vbank_due_date = serializers.CharField(allow_blank=True)
    od_vbank_status = serializers.CharField(allow_blank=True)
    # "1" / "" string flag
    od_test = serializers.CharField(allow_blank=True)
    od_misu = serializers.IntegerField()
    od_pg = serializers.CharField(allow_blank=True)
    od_tno = serializers.CharField(allow_blank=True)
    od_app_no = serializers.CharField(allow_blank=True)
    od_tax_flag = serializers.IntegerField()
    od_tax_invoice_request = serializers.BooleanField()
    od_tax_mny = serializers.IntegerField()
    od_vat_mny = serializers.IntegerField()
    od_free_mny = serializers.IntegerField()
    # the stored order coupon; od_cart_coupon is the product coupons still counting (0 once the
    # order is cancelled)
    od_coupon = serializers.IntegerField()
    od_cart_coupon = serializers.IntegerField()
    od_send_coupon = serializers.IntegerField()
    od_point = serializers.IntegerField()
    od_cash_request = serializers.BooleanField()
    od_cash_type = serializers.CharField(allow_blank=True)
    # 0 / 1 int flag: a cash receipt number is stored
    od_cash = serializers.IntegerField()
    od_cash_no = serializers.CharField(allow_blank=True)
    od_cash_res = serializers.CharField(allow_blank=True)
    od_cash_info = serializers.CharField(allow_blank=True)
    od_datetime = serializers.CharField(allow_blank=True)
    od_time = serializers.CharField(allow_blank=True)
    od_receipt_time = serializers.CharField(allow_blank=True)
    od_ip = serializers.CharField(allow_blank=True)
    od_total_price = serializers.IntegerField()
    od_order_price = serializers.IntegerField()
    od_list_price = serializers.IntegerField()
    od_receipt_total = serializers.IntegerField()
    od_misu_price = serializers.IntegerField()
    od_is_fully_paid = serializers.BooleanField()
    od_delivery_company = serializers.CharField(allow_blank=True)
    od_invoice = serializers.CharField(allow_blank=True)
    od_invoice_time = serializers.CharField(allow_blank=True)
    # the courier's tracking link and phone; "" for an unknown courier or without an invoice
    delivery_inquiry_url = serializers.CharField(allow_blank=True)
    od_delivery_inquiry_url = serializers.CharField(allow_blank=True)
    delivery_inquiry_tel = serializers.CharField(allow_blank=True)
    # the Toss receipt link, "" for other PGs
    receipt_url = serializers.CharField(allow_blank=True)
    od_payment_receipt_url = serializers.CharField(allow_blank=True)
    # "승인번호" / "거래번호" / ""
    od_payment_app_label = serializers.CharField(allow_blank=True)
    od_payment_app_value = serializers.CharField(allow_blank=True)
    # od_cash_res when it is a web address, else ""
    cash_receipt_url = serializers.CharField(allow_blank=True)
    od_cash_receipt_url = serializers.CharField(allow_blank=True)
    # where a paid cash order requests its receipt: "" in the order list
    cash_receipt_issue_url = serializers.CharField(allow_blank=True)
    od_cash_receipt_issue_url = serializers.CharField(allow_blank=True)
    # null in the order list; the detail always carries it
    cash_receipt = ShopOrderCashReceiptSerializer(allow_null=True)
    can_cancel = serializers.BooleanField()
    cancel_block_reason = serializers.CharField(allow_blank=True)


class ShopOrderDetailSerializer(ShopOrderSerializer):
    """``order_payload(order, detail=True)``: the list shape plus the lines, the cash receipt and
    the shipment tracking."""

    cash_receipt = ShopOrderCashReceiptSerializer()
    items = ShopOrderLineSerializer(many=True)
    # null unless 배송조회 is on with its keys and the invoice of a tracked courier has events
    shipment_tracking = ShopOrderShipmentTrackingSerializer(allow_null=True)
