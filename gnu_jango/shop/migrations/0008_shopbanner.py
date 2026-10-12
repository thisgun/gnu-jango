# Generated for the shop banner management and rendering flow.

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0007_alter_shopqa_product_alter_shopreview_product"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShopBanner",
            fields=[
                (
                    "bn_id",
                    models.BigAutoField(primary_key=True, serialize=False),
                ),
                ("bn_alt", models.CharField(blank=True, default="", max_length=255)),
                ("bn_url", models.CharField(blank=True, default="/shop", max_length=1000)),
                ("bn_position", models.CharField(default="메인", max_length=100)),
                (
                    "bn_device",
                    models.CharField(
                        choices=[("both", "All devices"), ("pc", "Desktop"), ("mobile", "Mobile")],
                        default="both",
                        max_length=10,
                    ),
                ),
                ("bn_border", models.BooleanField(default=False)),
                ("bn_new_win", models.BooleanField(default=False)),
                ("bn_order", models.IntegerField(default=0)),
                ("image_url", models.CharField(max_length=1000)),
                ("is_active", models.BooleanField(default=True)),
                ("begin_at", models.DateTimeField(blank=True, null=True)),
                ("end_at", models.DateTimeField(blank=True, null=True)),
                ("hit_count", models.PositiveBigIntegerField(default=0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "shop banner",
                "verbose_name_plural": "shop banners",
                "ordering": ["bn_order", "bn_id"],
            },
        ),
    ]
