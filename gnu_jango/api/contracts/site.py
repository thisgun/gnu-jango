"""Response contract of ``GET /api/v1/settings`` (``v1_community.settings_response``)."""

from rest_framework import serializers

from . import FreeformObjectField


class VisitStatsSerializer(serializers.Serializer):
    today = serializers.IntegerField()
    yesterday = serializers.IntegerField()
    max = serializers.IntegerField()
    total = serializers.IntegerField()


class ProductGridSerializer(serializers.Serializer):
    pc_cols = serializers.IntegerField()
    rows = serializers.IntegerField()
    per_page = serializers.IntegerField()
    mobile_cols = serializers.IntegerField()


class RelatedProductsDisplaySerializer(serializers.Serializer):
    use = serializers.BooleanField()
    pc_cols = serializers.IntegerField()
    mobile_cols = serializers.IntegerField()


class ShopDisplaySerializer(serializers.Serializer):
    search = ProductGridSerializer()
    listtype = ProductGridSerializer()
    related = RelatedProductsDisplaySerializer()


class SiteSettingsSerializer(serializers.Serializer):
    cf_title = serializers.CharField(allow_blank=True)
    cf_company_name = serializers.CharField(allow_blank=True)
    cf_company_owner = serializers.CharField(allow_blank=True)
    cf_company_addr = serializers.CharField(allow_blank=True)
    cf_company_biz_no = serializers.CharField(allow_blank=True)
    cf_company_tel = serializers.CharField(allow_blank=True)
    cf_company_tongsin_no = serializers.CharField(allow_blank=True)
    cf_company_buga_no = serializers.CharField(allow_blank=True)
    cf_company_fax = serializers.CharField(allow_blank=True)
    cf_company_info_name = serializers.CharField(allow_blank=True)
    cf_company_email = serializers.CharField(allow_blank=True)
    de_admin_company_tel = serializers.CharField(allow_blank=True)
    de_bank_use = serializers.CharField(allow_blank=True)
    de_bank_account = serializers.CharField(allow_blank=True)
    cf_home_boards = serializers.CharField(allow_blank=True)
    cf_home_gallery = serializers.CharField(allow_blank=True)
    cf_docs_group = serializers.CharField(allow_blank=True)
    # The active theme's own settings object (config/theme_settings.py), or null.
    theme_settings = FreeformObjectField(allow_null=True)
    cf_bbs_rewrite = serializers.IntegerField()
    infinite_scroll = serializers.BooleanField()
    # 정기구독 (shop/subscriptions.py) is available to members
    shop_subscriptions = serializers.BooleanField()
    comment_editor = serializers.BooleanField()
    pwa_enabled = serializers.BooleanField()
    price_alert_enabled = serializers.BooleanField()
    visit = VisitStatsSerializer()
    shop_logo = serializers.CharField(allow_blank=True)
    shop_logo_footer = serializers.CharField(allow_blank=True)
    shop_logo_mobile = serializers.CharField(allow_blank=True)
    shop_logo_mobile_footer = serializers.CharField(allow_blank=True)
    shop_display = ShopDisplaySerializer()
