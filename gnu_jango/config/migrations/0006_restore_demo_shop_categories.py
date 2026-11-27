import json
import re

from django.db import migrations
from django.db.models import Q

from gnu_jango.config.demo_shop_catalog_v2 import DEMO_CATEGORY_GROUPS


def restore_demo_categories(apps, schema_editor):
    db = schema_editor.connection.alias
    settings = apps.get_model("config", "Config").objects.using(db)
    categories = apps.get_model("shop", "ShopCategory").objects.using(db)
    products = apps.get_model("shop", "ShopProduct").objects.using(db)
    coupons = apps.get_model("shop", "ShopCoupon").objects.using(db)
    coupon_zones = apps.get_model("shop", "ShopCouponZone").objects.using(db)

    row = settings.select_for_update().filter(name="g5_sample_data_manifest_v1").first()
    if row is None:
        return
    try:
        manifest = json.loads(row.value)
    except (TypeError, ValueError):
        return
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        return
    tracked_categories = manifest.get("categories")
    tracked_products = manifest.get("products")
    slots = manifest.get("shop_category_slots")
    if not isinstance(tracked_categories, list) or not isinstance(tracked_products, list) or not isinstance(slots, dict):
        return
    root_id = slots.get("1")
    if not isinstance(root_id, str) or root_id not in tracked_categories or not re.fullmatch(r"[a-z0-9]{2}", root_id):
        return
    if not categories.filter(pk=root_id, ca_name="데모 스토어", ca_parent="", ca_use=True).exists():
        return

    removed = set()
    for index, (suffix, title, numbers) in enumerate(DEMO_CATEGORY_GROUPS, start=2):
        category_id = root_id + suffix
        if slots.get(str(index)) != category_id or category_id not in tracked_categories:
            continue
        category = categories.select_for_update().filter(
            pk=category_id, ca_parent=root_id, ca_name=title, ca_order=index, ca_use=True,
            ca_skin="", ca_list_mod=0, ca_list_row=0, ca_mobile_list_mod=0, ca_mobile_list_row=0,
            ca_nocoupon=False,
        ).first()
        if category is None:
            continue

        # Preserve categories used by merchandise or marketing added after the migration.
        category_products = products.select_for_update().filter(
            Q(category_id=category_id) | Q(category2_id=category_id) | Q(category3_id=category_id),
        )
        demo_assignments = []
        for product in category_products:
            slot = re.fullmatch(r"/sample-data/product-0([1-6])\.webp", product.image_url or "")
            if (
                slot and int(slot[1]) in numbers and product.pk in tracked_products
                and re.fullmatch(r"SAMPLE[0-9a-f]{8}0" + slot[1], product.pk)
                and product.category_id == root_id and product.category2_id == category_id
                and product.category3_id is None
            ):
                demo_assignments.append(product.pk)

        if (
            category_products.exclude(pk__in=demo_assignments).exists()
            or categories.filter(ca_parent=category_id).exists()
            or coupons.filter(cp_method=1, cp_target=category_id).exists()
            or coupon_zones.filter(cp_method=1, cp_target=category_id).exists()
        ):
            continue

        category_products.filter(pk__in=demo_assignments).update(category2_id=None)
        category.delete()
        removed.add(category_id)

    if removed:
        manifest["categories"] = [category_id for category_id in tracked_categories if category_id not in removed]
        manifest["shop_category_slots"] = {slot: category_id for slot, category_id in slots.items() if category_id not in removed}
        row.value = json.dumps(manifest, ensure_ascii=False)
        row.save(update_fields=["value"])


class Migration(migrations.Migration):
    dependencies = [("config", "0005_group_legacy_demo_shop_products")]

    operations = [migrations.RunPython(restore_demo_categories, migrations.RunPython.noop)]
