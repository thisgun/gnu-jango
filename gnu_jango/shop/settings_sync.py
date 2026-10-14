"""Keep legacy shop-support settings synchronized across admin screens."""

from gnu_jango.config.models import Config

from .models import ShopShippingPolicy


def sync_shop_phone_from_config(value):
    ShopShippingPolicy.objects.filter(pk=1).update(de_admin_company_tel=str(value or "")[:30])


def sync_shop_phone_from_policy(value):
    Config.objects.update_or_create(
        name="de_admin_company_tel",
        defaults={"value": str(value or "")[:30]},
    )
