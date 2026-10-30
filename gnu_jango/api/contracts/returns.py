"""Response contract of the customer return / exchange requests (shop/returns.py).

* ``GET /api/v1/shop/orders/{od_id}/returns`` - ``returns.customer_payload(order)``: which lines may
  be asked for, until when, and the order's requests (newest first).
* ``POST /api/v1/shop/orders/{od_id}/returns`` (201) and
  ``POST /api/v1/shop/orders/{od_id}/returns/{request_id}/withdraw`` answer with the same shape
  after the change.

The POST body of a new request is described too (``ShopReturnCreateSerializer``).
"""

from rest_framework import serializers

# Named enum components (SPECTACULAR_SETTINGS["ENUM_NAME_OVERRIDES"]).
RETURN_REQUEST_KINDS = ["return", "exchange"]
RETURN_REQUEST_STATUSES = ["requested", "approved", "completed", "rejected", "withdrawn"]
RETURN_REQUEST_REASONS = ["change_of_mind", "defective", "wrong_item", "other"]


class ShopReturnKindOptionSerializer(serializers.Serializer):
    value = serializers.ChoiceField(choices=RETURN_REQUEST_KINDS)
    label = serializers.CharField()


class ShopReturnReasonOptionSerializer(serializers.Serializer):
    value = serializers.ChoiceField(choices=RETURN_REQUEST_REASONS)
    label = serializers.CharField()


class ShopReturnOrderLineSerializer(serializers.Serializer):
    """One order line and whether it may be asked for now."""

    # the ShopOrderItem pk: what a request names
    line_id = serializers.IntegerField()
    ct_id = serializers.CharField(allow_blank=True)
    it_id = serializers.CharField(allow_blank=True)
    it_name = serializers.CharField(allow_blank=True)
    ct_option = serializers.CharField(allow_blank=True)
    ct_qty = serializers.IntegerField()
    ct_status = serializers.CharField(allow_blank=True)
    line_total = serializers.IntegerField()
    eligible = serializers.BooleanField()
    # Korean, "" when eligible
    block_reason = serializers.CharField(allow_blank=True)
    # ISO time the window closes; "" while it has not started (a 배송 line)
    deadline = serializers.CharField(allow_blank=True)
    # the open request holding the line, null when none
    open_request_id = serializers.IntegerField(allow_null=True)


class ShopReturnRequestLineSerializer(serializers.Serializer):
    line_id = serializers.IntegerField()
    ct_id = serializers.CharField(allow_blank=True)
    it_name = serializers.CharField(allow_blank=True)
    ct_option = serializers.CharField(allow_blank=True)
    qty = serializers.IntegerField()
    # the requested units' share of the line total when it was asked for
    amount = serializers.IntegerField()


class ShopReturnRequestSerializer(serializers.Serializer):
    """``returns.request_payload``: one request; times are ISO strings or ""."""

    id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=RETURN_REQUEST_KINDS)
    kind_label = serializers.CharField()
    status = serializers.ChoiceField(choices=RETURN_REQUEST_STATUSES)
    status_label = serializers.CharField()
    reason = serializers.ChoiceField(choices=RETURN_REQUEST_REASONS)
    reason_label = serializers.CharField()
    detail = serializers.CharField(allow_blank=True)
    # the shop's reason, shown once the request is rejected
    reject_reason = serializers.CharField(allow_blank=True)
    # a completed return: the return shipping fee kept back and the cash refunded
    return_fee = serializers.IntegerField()
    refund_amount = serializers.IntegerField()
    # a completed exchange: the re-shipment and its tracking link ("" for an unknown courier)
    exchange_delivery_company = serializers.CharField(allow_blank=True)
    exchange_invoice = serializers.CharField(allow_blank=True)
    exchange_inquiry_url = serializers.CharField(allow_blank=True)
    can_withdraw = serializers.BooleanField()
    created_at = serializers.CharField(allow_blank=True)
    approved_at = serializers.CharField(allow_blank=True)
    closed_at = serializers.CharField(allow_blank=True)
    lines = ShopReturnRequestLineSerializer(many=True)


class ShopOrderReturnsSerializer(serializers.Serializer):
    """``returns.customer_payload(order)``."""

    # de_return_request_use
    enabled = serializers.BooleanField()
    # de_return_request_days: counted from when a line was completed (배송완료)
    request_days = serializers.IntegerField()
    # de_return_shipping_fee: kept back from a 단순변심 return's refund
    return_shipping_fee = serializers.IntegerField()
    # some line may be asked for now
    can_request = serializers.BooleanField()
    # Korean, why the whole order cannot be asked for ("" otherwise)
    block_reason = serializers.CharField(allow_blank=True)
    kinds = ShopReturnKindOptionSerializer(many=True)
    reasons = ShopReturnReasonOptionSerializer(many=True)
    lines = ShopReturnOrderLineSerializer(many=True)
    requests = ShopReturnRequestSerializer(many=True)


class ShopReturnLineInputSerializer(serializers.Serializer):
    line_id = serializers.IntegerField()
    qty = serializers.IntegerField(min_value=1)


class ShopReturnCreateSerializer(serializers.Serializer):
    """The body of ``POST /api/v1/shop/orders/{od_id}/returns`` (a guest also sends ``uid``)."""

    kind = serializers.ChoiceField(choices=RETURN_REQUEST_KINDS)
    reason = serializers.ChoiceField(choices=RETURN_REQUEST_REASONS)
    # required for "other"; up to 1,000 characters
    detail = serializers.CharField(required=False, allow_blank=True)
    lines = ShopReturnLineInputSerializer(many=True)
    uid = serializers.CharField(required=False, allow_blank=True)
