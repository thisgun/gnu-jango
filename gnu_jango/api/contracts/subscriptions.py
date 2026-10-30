"""Response contracts of the 정기구독 API (gnu_jango/api/shop_subscriptions.py)."""

from rest_framework import serializers


class ShopSubscriptionCycleSerializer(serializers.Serializer):
    # 1w | 2w | 4w | 1m
    value = serializers.CharField()
    label = serializers.CharField()


class ShopSubscriptionOfferSerializer(serializers.Serializer):
    """``subscription`` of the product detail: what the product page offers (null when it cannot
    be subscribed to or the feature is off)."""

    cycles = ShopSubscriptionCycleSerializer(many=True)
    discount_rate = serializers.IntegerField()
    # the product's base price less the subscription discount, today
    price = serializers.IntegerField()


class ShopSubscriptionCardSerializer(serializers.Serializer):
    """The registered card as Toss described it (the number comes masked from Toss)."""

    company = serializers.CharField(allow_blank=True)
    number = serializers.CharField(allow_blank=True)
    type = serializers.CharField(allow_blank=True)


class ShopSubscriptionDeliverySerializer(serializers.Serializer):
    name = serializers.CharField(allow_blank=True)
    tel = serializers.CharField(allow_blank=True)
    hp = serializers.CharField(allow_blank=True)
    zip = serializers.CharField(allow_blank=True)
    addr1 = serializers.CharField(allow_blank=True)
    addr2 = serializers.CharField(allow_blank=True)
    addr3 = serializers.CharField(allow_blank=True)


class ShopSubscriptionChargeSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    cycle_no = serializers.IntegerField()
    attempt = serializers.IntegerField()
    scheduled_date = serializers.DateField()
    # pending | done | failed | skipped | review
    status = serializers.CharField()
    status_label = serializers.CharField()
    amount = serializers.IntegerField()
    order_id = serializers.CharField(allow_blank=True)
    failure_message = serializers.CharField(allow_blank=True)
    created_at = serializers.DateTimeField()


class ShopSubscriptionSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    # active | paused | cancelled
    status = serializers.CharField()
    status_label = serializers.CharField()
    # "" | member | payment_failed | admin
    pause_reason = serializers.CharField(allow_blank=True)
    pause_reason_label = serializers.CharField(allow_blank=True)
    it_id = serializers.CharField()
    it_name = serializers.CharField(allow_blank=True)
    io_id = serializers.CharField(allow_blank=True)
    option_label = serializers.CharField(allow_blank=True)
    qty = serializers.IntegerField()
    cycle = serializers.CharField()
    cycle_label = serializers.CharField()
    # the cycles the product offers now (a cycle change picks one of them)
    cycle_choices = ShopSubscriptionCycleSerializer(many=True)
    discount_rate = serializers.IntegerField()
    # when the next charge is tried (a failed charge's retry date, else the cycle's date)
    next_charge_date = serializers.DateField(allow_null=True)
    retry_date = serializers.DateField(allow_null=True)
    cycle_no = serializers.IntegerField()
    failure_count = serializers.IntegerField()
    # goods and shipping at today's prices; null while the product cannot be charged
    estimated_amount = serializers.IntegerField(allow_null=True)
    card = ShopSubscriptionCardSerializer(allow_null=True)
    delivery = ShopSubscriptionDeliverySerializer()
    image_url = serializers.CharField(allow_blank=True)
    last_error = serializers.CharField(allow_blank=True)
    charge_in_progress = serializers.BooleanField()
    started_at = serializers.DateTimeField(allow_null=True)
    cancelled_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class ShopSubscriptionDetailSerializer(ShopSubscriptionSerializer):
    # newest first, at most 24
    charges = ShopSubscriptionChargeSerializer(many=True)


class ShopSubscriptionRegistrationSerializer(serializers.Serializer):
    """What the browser needs to open the Toss billing window (payment({customerKey})
    .requestBillingAuth). The registration token goes back with the authKey on the success page."""

    subscription_id = serializers.IntegerField()
    registration_token = serializers.CharField()
    customer_key = serializers.CharField()
    client_key = serializers.CharField()
    customer_name = serializers.CharField(allow_blank=True)
    customer_email = serializers.CharField(allow_blank=True)
    expires_at = serializers.DateTimeField(allow_null=True)


class ShopSubscriptionBillingResultSerializer(serializers.Serializer):
    subscription = ShopSubscriptionDetailSerializer()
    # the first charge's order ("" for a card change)
    order_id = serializers.CharField(allow_blank=True)
    # "" for a card change; charged, or pending while Toss's answer is being confirmed
    charge_status = serializers.CharField(allow_blank=True)
