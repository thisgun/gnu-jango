import json
import re

from django.db import migrations

from gnu_jango.config.demo_shop_catalog_v2 import DEMO_CATEGORY_GROUPS


def group_demo_products(apps, schema_editor):
    db = schema_editor.connection.alias
    settings = apps.get_model("config", "Config").objects.using(db)
    categories = apps.get_model("shop", "ShopCategory").objects.using(db)
    products = apps.get_model("shop", "ShopProduct").objects.using(db)
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
    if not isinstance(tracked_categories, list) or len(tracked_categories) != 1 or not isinstance(tracked_products, list):
        return
    root_id = tracked_categories[0]
    if not isinstance(root_id, str) or not re.fullmatch(r"[a-z0-9]{2}", root_id):
        return
    if not categories.filter(pk=root_id, ca_name="데모 스토어", ca_parent="", ca_use=True).exists():
        return

    eligible = {}
    legacy_products = products.select_for_update().filter(
        pk__in=tracked_products, category_id=root_id, category2__isnull=True, category3__isnull=True,
    )
    for product in legacy_products:
        slot = re.fullmatch(r"/sample-data/product-0([1-6])\.webp", product.image_url or "")
        if slot and re.fullmatch(r"SAMPLE[0-9a-f]{8}0" + slot[1], product.pk):
            eligible[int(slot[1])] = product.pk

    slots = {"1": root_id}
    for index, (suffix, title, numbers) in enumerate(DEMO_CATEGORY_GROUPS, start=2):
        product_ids = [eligible[number] for number in numbers if number in eligible]
        category_id = root_id + suffix
        if not product_ids or categories.filter(pk=category_id).exists():
            continue
        categories.create(ca_id=category_id, ca_parent=root_id, ca_name=title, ca_order=index, ca_use=True)
        products.filter(
            pk__in=product_ids, category_id=root_id, category2__isnull=True, category3__isnull=True,
        ).update(category2_id=category_id)
        tracked_categories.append(category_id)
        slots[str(index)] = category_id

    if len(slots) > 1:
        manifest["shop_category_slots"] = slots
        row.value = json.dumps(manifest, ensure_ascii=False)
        row.save(update_fields=["value"])


class Migration(migrations.Migration):
    dependencies = [
        ("config", "0004_historicalconfig"),
        ("shop", "0042_shop_subscriptions"),
    ]

    operations = [migrations.RunPython(group_demo_products, migrations.RunPython.noop)]
