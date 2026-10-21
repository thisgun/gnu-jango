"""상품정보제공고시: keep every notice row in a JSON column.

Earlier imports copied YoungCart's PHP-serialized ``it_info_value`` into the 255-character
``it_info_title`` column, so the rows were cut short and shown as one garbled line. This
moves whatever can still be read (the complete leading rows of a cut value) into
``it_info_value`` and clears the copied text. A plain text that is not a serialized notice
stays in ``it_info_title``.
"""
from django.db import migrations, models

from gnu_jango.shop.item_info import parse_item_info_value


def move_info_rows(apps, schema_editor):
    ShopProduct = apps.get_model("shop", "ShopProduct")
    products = ShopProduct.objects.exclude(it_info_title="").only("it_id", "it_info_gubun", "it_info_title")
    for product in products.iterator():
        text = product.it_info_title.strip()
        rows = parse_item_info_value(text, product.it_info_gubun)
        if rows is None and not text.startswith("a:"):
            continue
        ShopProduct.objects.filter(pk=product.pk).update(it_info_value=rows or [], it_info_title="")


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0030_shoporder_refund_history"),
    ]

    operations = [
        migrations.AddField(
            model_name="shopproduct",
            name="it_info_value",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(move_info_rows, migrations.RunPython.noop),
    ]
