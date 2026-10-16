from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("shop", "0027_general_inquiry_proxy"),
    ]

    operations = [
        migrations.AddField(
            model_name="shoporder",
            name="od_cash_type",
            field=models.CharField(
                blank=True,
                choices=[("income", "Income deduction"), ("expense", "Business expense proof")],
                default="",
                max_length=10,
                verbose_name="Cash receipt type",
            ),
        ),
        migrations.AddField(
            model_name="shoporder",
            name="od_tax_business_no",
            field=models.CharField(
                blank=True,
                default="",
                max_length=10,
                verbose_name="Tax invoice business number",
            ),
        ),
        migrations.AddField(
            model_name="shoporder",
            name="od_tax_company",
            field=models.CharField(
                blank=True,
                default="",
                max_length=100,
                verbose_name="Tax invoice company",
            ),
        ),
        migrations.AddField(
            model_name="shoporder",
            name="od_tax_email",
            field=models.EmailField(
                blank=True,
                default="",
                max_length=254,
                verbose_name="Tax invoice email",
            ),
        ),
    ]
