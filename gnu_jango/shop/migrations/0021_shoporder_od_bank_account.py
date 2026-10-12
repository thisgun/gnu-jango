from django.db import migrations, models
from django.utils.translation import gettext_lazy as _


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0020_shopshippingpolicy_de_admin_company_name_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="shoporder",
            name="od_bank_account",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name=_("Bank account")),
        ),
    ]
