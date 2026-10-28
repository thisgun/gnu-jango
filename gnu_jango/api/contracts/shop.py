"""Response contracts of the shop catalogue reads in ``v1_shop``.

* ``GET /api/v1/shop/categories`` - ``categories_response``: top-level categories, each with its
  direct ``children`` (one level only; a child carries no ``children`` key).
* ``GET /api/v1/shop/categories/{ca_id}`` - ``category_detail_view``.
* ``GET /api/v1/shop/products`` - ``products_response``.
* ``GET /api/v1/shop/products/{it_id}`` - ``product_payload(..., detail=True)``.
"""

from rest_framework import serializers

from . import PageMetaSerializer


class CategoryListDisplaySerializer(serializers.Serializer):
    """``shop_display.category_list_display``: the category page grid (categoryform.php 출력설정)."""

    configured = serializers.BooleanField()
    pc_cols = serializers.IntegerField()
    rows = serializers.IntegerField()
    per_page = serializers.IntegerField()
    mobile_cols = serializers.IntegerField()
    mobile_rows = serializers.IntegerField()


class ShopCategorySerializer(serializers.Serializer):
    """``v1_shop.category_payload`` (without children)."""

    ca_id = serializers.CharField()
    ca_name = serializers.CharField(allow_blank=True)
    ca_order = serializers.IntegerField()
    ca_skin = serializers.CharField(allow_blank=True)
    # "" for a top-level category
    ca_parent = serializers.CharField(allow_blank=True)
    ca_list_mod = serializers.IntegerField()
    ca_list_row = serializers.IntegerField()
    ca_mobile_list_mod = serializers.IntegerField()
    ca_mobile_list_row = serializers.IntegerField()
    ca_nocoupon = serializers.BooleanField()
    list_display = CategoryListDisplaySerializer()
    # On-sale products of the whole tree where the query annotates it (category lists); the
    # product payload's ``category`` counts every product placed directly in the category.
    item_count = serializers.IntegerField()


class ShopCategoryTreeSerializer(ShopCategorySerializer):
    """A top-level category of ``GET /shop/categories`` with its direct sub-categories."""

    children = ShopCategorySerializer(many=True)


class ShopProductOptionSerializer(serializers.Serializer):
    """A ``ShopProduct.options`` row (``shop.product_options``): 선택옵션 (io_type 0) or 추가옵션 (1).

    The stored row is passed through as saved; only ``io_type`` is coerced to an int, and rows of
    any other type are dropped."""

    io_no = serializers.IntegerField()
    # 선택옵션 values (or 추가옵션 "항목명\\x1e값") joined with chr(30)
    io_id = serializers.CharField(allow_blank=True)
    io_type = serializers.IntegerField()
    io_price = serializers.IntegerField()
    io_stock_qty = serializers.IntegerField()
    io_noti_qty = serializers.IntegerField()
    io_use = serializers.IntegerField()


class ShopProductInfoItemSerializer(serializers.Serializer):
    """A 상품정보제공고시 row (``shop.item_info.item_info_rows``)."""

    key = serializers.CharField()
    title = serializers.CharField(allow_blank=True)
    value = serializers.CharField(allow_blank=True)
    example = serializers.CharField(allow_blank=True)


class ShopProductSerializer(serializers.Serializer):
    """``v1_shop.product_payload`` as product lists, cards and the detail's neighbours show it."""

    it_id = serializers.CharField()
    # "" when the slot is empty
    ca_id = serializers.CharField(allow_blank=True)
    ca_id2 = serializers.CharField(allow_blank=True)
    ca_id3 = serializers.CharField(allow_blank=True)
    ca_name = serializers.CharField(allow_blank=True)
    it_name = serializers.CharField(allow_blank=True)
    it_seo_title = serializers.CharField(allow_blank=True)
    it_brand = serializers.CharField(allow_blank=True)
    it_maker = serializers.CharField(allow_blank=True)
    it_origin = serializers.CharField(allow_blank=True)
    it_model = serializers.CharField(allow_blank=True)
    it_price = serializers.IntegerField()
    # it_basic_price, or it_price when that is 0
    it_basic_price = serializers.IntegerField()
    it_cust_price = serializers.IntegerField()
    it_hit = serializers.IntegerField()
    it_point = serializers.IntegerField()
    it_point_type = serializers.IntegerField()
    it_stock_qty = serializers.IntegerField()
    # 0 taxable, 1 tax-free (an int flag, not a boolean)
    it_notax = serializers.IntegerField()
    it_nocoupon = serializers.BooleanField()
    it_buy_min_qty = serializers.IntegerField()
    it_buy_max_qty = serializers.IntegerField()
    # "1" / "" string flags (YoungCart char(1) columns)
    it_tel_inq = serializers.CharField(allow_blank=True)
    it_soldout = serializers.CharField(allow_blank=True)
    it_stock_sms = serializers.CharField(allow_blank=True)
    # stored subject, or one made up from the option rows ("선택 옵션 1,..." / "추가 옵션")
    it_option_subject = serializers.CharField(allow_blank=True)
    it_supply_subject = serializers.CharField(allow_blank=True)
    # always "" here
    stock_sms_privacy = serializers.CharField(allow_blank=True)
    it_sc_type = serializers.IntegerField()
    it_sc_method = serializers.IntegerField()
    it_sc_price = serializers.IntegerField()
    it_sc_minimum = serializers.IntegerField()
    it_sc_qty = serializers.IntegerField()
    it_type1 = serializers.CharField(allow_blank=True)
    it_type2 = serializers.CharField(allow_blank=True)
    it_type3 = serializers.CharField(allow_blank=True)
    it_type4 = serializers.CharField(allow_blank=True)
    it_type5 = serializers.CharField(allow_blank=True)
    has_coupon = serializers.BooleanField()
    it_content = serializers.CharField(allow_blank=True)
    it_explan = serializers.CharField(allow_blank=True)
    it_basic = serializers.CharField(allow_blank=True)
    it_head_html = serializers.CharField(allow_blank=True)
    it_tail_html = serializers.CharField(allow_blank=True)
    it_info_gubun = serializers.CharField(allow_blank=True)
    it_info_gubun_title = serializers.CharField(allow_blank=True)
    it_info_title = serializers.CharField(allow_blank=True)
    it_info_items = ShopProductInfoItemSerializer(many=True)
    # 400px list copy of the main picture (the original when it cannot be resized), or ""
    image_url = serializers.CharField(allow_blank=True)
    # original gallery URLs; the main picture alone when the product has no gallery, [] without both
    images = serializers.ListField(child=serializers.CharField())
    options = ShopProductOptionSerializer(many=True)
    category = ShopCategorySerializer(allow_null=True)
    review_count = serializers.IntegerField()
    review_avg = serializers.FloatField()
    qa_count = serializers.IntegerField()


class ShopProductDetailSerializer(ShopProductSerializer):
    """``product_payload(..., detail=True)``: the list shape plus the neighbours and related items."""

    prev_item = ShopProductSerializer(allow_null=True)
    next_item = ShopProductSerializer(allow_null=True)
    # [] when de_rel_list_use is off
    related_items = ShopProductSerializer(many=True)


class ShopCategoryDetailSerializer(serializers.Serializer):
    """``GET /shop/categories/{ca_id}``: the category, its direct sub-categories and a page of
    its tree's products; ``meta`` repeats the envelope's page meta."""

    category = ShopCategorySerializer()
    subcategories = ShopCategorySerializer(many=True)
    items = ShopProductSerializer(many=True)
    meta = PageMetaSerializer()
