import json

from django.db import migrations


DEMO_BANNERS = (
    ("SAMPLE2ab3cdb401", "책상 위 문구|기록이 시작되는 책상", "hero-notebook-202611.webp"),
    ("SAMPLE2ab3cdb402", "슬림 데스크 선반|책상 위에 여유를", "hero-desk-shelf-202611.webp"),
    ("SAMPLE2ab3cdb403", "우드 데스크 매트|나무 결을 담은 책상", "hero-wood-mat-202611.webp"),
)


def set_demo_shop_banners(apps, schema_editor):
    db = schema_editor.connection.alias
    settings = apps.get_model("config", "Config").objects.using(db)
    banners = apps.get_model("shop", "ShopBanner").objects.using(db)
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

    # Identify the deployed demo catalog before editing its original seed banner.
    product_ids = [product_id for product_id, _, _ in DEMO_BANNERS]
    tracked_products = manifest.get("products")
    tracked_banners = manifest.get("banners")
    if (
        not isinstance(tracked_products, list)
        or not isinstance(tracked_banners, list)
        or not all(product_id in tracked_products for product_id in product_ids)
        or products.filter(pk__in=product_ids, it_use="1").count() != len(product_ids)
    ):
        return

    main_banners = banners.select_for_update().filter(bn_position="메인", is_active=True)
    banner = main_banners.filter(
        pk__in=tracked_banners, bn_alt="차분한 일상을 위한 데모 스토어", bn_url="/shop",
        bn_device="both", bn_order=1, bn_border=False, bn_new_win=False,
        image_url="/sample-data/banner.webp", image_file="", begin_at__isnull=True, end_at__isnull=True,
    ).first()
    if banner is None or tracked_banners != [banner.pk] or main_banners.exclude(pk=banner.pk).exists():
        return

    slots = {"1": banner.pk}
    for order, (product_id, alt, image) in enumerate(DEMO_BANNERS, start=1):
        content = {
            "bn_alt": alt,
            "bn_url": f"/shop/item-{product_id}",
            "image_url": f"/sample-data/{image}",
        }
        if order == 1:
            banners.filter(pk=banner.pk).update(**content)
        else:
            new_banner = banners.create(bn_position="메인", bn_device="both", bn_order=order, **content)
            tracked_banners.append(new_banner.pk)
            slots[str(order)] = new_banner.pk

    manifest["shop_banner_slots"] = slots
    row.value = json.dumps(manifest, ensure_ascii=False)
    row.save(update_fields=["value"])


class Migration(migrations.Migration):
    dependencies = [("config", "0006_restore_demo_shop_categories")]

    operations = [migrations.RunPython(set_demo_shop_banners, migrations.RunPython.noop)]
