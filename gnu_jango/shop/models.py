import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from gnu_jango.site_search.source import SearchIndexedSource
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.core.validators import FileExtensionValidator
from simple_history.models import HistoricalRecords


# youngcart 완료: the status whose lines earn their purchase point (ct_complete_time is its clock).
ORDER_ITEM_STATUS_COMPLETED = "완료"


def generate_order_uid():
    return uuid.uuid4().hex + uuid.uuid4().hex


def generate_coupon_id():
    return uuid.uuid4().hex[:16]


def generate_log_id():
    return uuid.uuid4().hex


def shop_banner_image_upload(instance, filename):
    extension = Path(filename).suffix.lower()
    return f"shop/banners/{uuid.uuid4().hex}{extension}"


def validate_shop_banner_image_size(uploaded_file):
    max_size = 5 * 1024 * 1024
    if uploaded_file.size and uploaded_file.size > max_size:
        raise ValidationError(_("Banner images must be 5 MB or smaller."))


def shop_event_head_image_upload(instance, filename):
    extension = Path(filename).suffix.lower()
    return f"shop/events/{instance.pk or 'new'}/head{extension}"


def shop_event_tail_image_upload(instance, filename):
    extension = Path(filename).suffix.lower()
    return f"shop/events/{instance.pk or 'new'}/tail{extension}"


class ShopCategory(models.Model):
    ca_id = models.CharField(max_length=20, primary_key=True)
    ca_name = models.CharField(max_length=255)
    ca_parent = models.CharField(max_length=20, blank=True, default="")
    ca_order = models.IntegerField(default=0)
    ca_skin = models.CharField(max_length=100, blank=True, default="")
    ca_use = models.BooleanField(default=True)
    # youngcart categoryform.php 출력설정: images per row / rows (PC and mobile). 0 (the install
    # default) means "not set" and the storefront keeps its standard grid; the admin add form
    # starts a new category at youngcart's 3 x 5.
    ca_list_mod = models.PositiveSmallIntegerField("1줄당 이미지 수", default=0)
    ca_list_row = models.PositiveSmallIntegerField("이미지 줄 수", default=0)
    ca_mobile_list_mod = models.PositiveSmallIntegerField("모바일 1줄당 이미지 수", default=0)
    ca_mobile_list_row = models.PositiveSmallIntegerField("모바일 이미지 줄 수", default=0)
    # youngcart ca_nocoupon: category coupons may not target this category.
    ca_nocoupon = models.BooleanField(
        "쿠폰적용안함",
        default=False,
        help_text="체크하면 이 분류를 대상으로 하는 분류 쿠폰을 쓸 수 없습니다.",
    )

    class Meta:
        ordering = ["ca_order", "ca_id"]
        verbose_name = _("Shop category")
        verbose_name_plural = _("Shop categories")

    def __str__(self):
        return f"{self.ca_id}: {self.ca_name}"


class ShopBanner(models.Model):
    DEVICE_CHOICES = [
        ("both", _("All devices")),
        ("pc", _("Desktop")),
        ("mobile", _("Mobile")),
    ]

    bn_id = models.BigAutoField(primary_key=True)
    bn_alt = models.CharField(max_length=255, blank=True, default="")
    bn_url = models.CharField(max_length=1000, blank=True, default="/shop")
    bn_position = models.CharField(max_length=100, default="메인")
    bn_device = models.CharField(max_length=10, choices=DEVICE_CHOICES, default="both")
    bn_border = models.BooleanField(default=False)
    bn_new_win = models.BooleanField(default=False)
    bn_order = models.IntegerField(default=0)
    image_url = models.CharField(max_length=1000, blank=True, default="")
    image_file = models.ImageField(
        upload_to=shop_banner_image_upload,
        blank=True,
        validators=[
            FileExtensionValidator(["jpg", "jpeg", "png", "gif", "webp"]),
            validate_shop_banner_image_size,
        ],
    )
    is_active = models.BooleanField(default=True)
    begin_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    hit_count = models.PositiveBigIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["bn_order", "bn_id"]
        verbose_name = _("Shop banner")
        verbose_name_plural = _("Shop banners")

    def clean(self):
        super().clean()
        if self.is_active and not self.image_file and not str(self.image_url or "").strip():
            raise ValidationError({"image_file": _("Upload a banner image or provide a legacy image URL.")})

    def __str__(self):
        return self.bn_alt or f"Banner {self.bn_id}"


class ShopEvent(models.Model):
    ev_id = models.AutoField(primary_key=True)
    ev_skin = models.CharField(max_length=255, blank=True, default="")
    ev_mobile_skin = models.CharField(max_length=255, blank=True, default="")
    ev_img_width = models.PositiveIntegerField(default=0)
    ev_img_height = models.PositiveIntegerField(default=0)
    ev_list_mod = models.PositiveSmallIntegerField(default=0)
    ev_list_row = models.PositiveSmallIntegerField(default=0)
    ev_mobile_img_width = models.PositiveIntegerField(default=0)
    ev_mobile_img_height = models.PositiveIntegerField(default=0)
    ev_mobile_list_mod = models.PositiveSmallIntegerField(default=0)
    ev_mobile_list_row = models.PositiveSmallIntegerField(default=0)
    ev_subject = models.CharField(max_length=255)
    ev_subject_strong = models.BooleanField(default=False)
    ev_head_html = models.TextField(blank=True, default="")
    ev_tail_html = models.TextField(blank=True, default="")
    ev_head_image = models.ImageField(
        upload_to=shop_event_head_image_upload,
        blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "gif", "webp"])],
    )
    ev_tail_image = models.ImageField(
        upload_to=shop_event_tail_image_upload,
        blank=True,
        validators=[FileExtensionValidator(["jpg", "jpeg", "png", "gif", "webp"])],
    )
    ev_use = models.BooleanField(default=False)
    products = models.ManyToManyField(
        "ShopProduct",
        through="ShopEventItem",
        related_name="shop_events",
        blank=True,
    )

    class Meta:
        ordering = ["-ev_id"]
        verbose_name = _("Shop event")
        verbose_name_plural = _("Shop events")

    def __str__(self):
        return f"{self.ev_id}: {self.ev_subject}"


class ShopEventItem(models.Model):
    event = models.ForeignKey(ShopEvent, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        "ShopProduct",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="event_items",
    )
    it_id = models.CharField(max_length=40)

    class Meta:
        ordering = ["event_id", "it_id"]
        constraints = [
            models.UniqueConstraint(fields=["event", "it_id"], name="shop_event_item_unique_product"),
        ]
        indexes = [models.Index(fields=["it_id"])]
        verbose_name = _("Shop event product")
        verbose_name_plural = _("Shop event products")

    def __str__(self):
        return f"{self.event_id}: {self.it_id}"


class ShopShippingPolicy(models.Model):
    SEND_COST_CASE_CHOICES = [
        ("차등", _("Tiered by order amount")),
        ("무료", _("Free shipping")),
    ]

    de_admin_company_name = models.CharField(max_length=255, blank=True, default="")
    de_admin_company_tel = models.CharField(max_length=30, blank=True, default="")
    de_delivery_company = models.CharField(max_length=255, blank=True, default="")
    de_send_cost_case = models.CharField(max_length=255, blank=True, default="", choices=SEND_COST_CASE_CHOICES)
    de_send_cost_limit = models.CharField(max_length=255, blank=True, default="")
    de_send_cost_list = models.CharField(max_length=255, blank=True, default="")
    de_baesong_content = models.TextField(blank=True, default="")
    de_change_content = models.TextField(blank=True, default="")
    de_item_use_write = models.PositiveSmallIntegerField(default=0)
    de_item_use_use = models.PositiveSmallIntegerField(default=0)
    de_tax_flag_use = models.BooleanField(default=False)
    de_settle_min_point = models.IntegerField(default=0)
    de_settle_max_point = models.IntegerField(default=0)
    de_settle_point_unit = models.IntegerField(default=1)

    class Meta:
        verbose_name = _("Shop shipping policy")
        verbose_name_plural = _("Shop shipping policies")

    def __str__(self):
        return self.de_admin_company_name or self.de_delivery_company or f"Shipping policy #{self.pk}"


class ShopShippingCost(models.Model):
    sc_id = models.BigIntegerField(primary_key=True)
    sc_name = models.CharField(max_length=255, blank=True, default="")
    sc_zip1 = models.CharField(max_length=10, blank=True, default="")
    sc_zip2 = models.CharField(max_length=10, blank=True, default="")
    sc_price = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sc_id"]
        verbose_name = _("Regional shipping cost")
        verbose_name_plural = _("Regional shipping costs")
        indexes = [
            models.Index(fields=["sc_zip1"]),
            models.Index(fields=["sc_zip2"]),
        ]

    def __str__(self):
        return f"{self.sc_name or self.sc_id}: {self.sc_zip1}–{self.sc_zip2}"


class ShopProduct(SearchIndexedSource):
    it_id = models.CharField(max_length=40, primary_key=True)
    category = models.ForeignKey(
        ShopCategory,
        to_field="ca_id",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    # PHP ca_id2 / ca_id3: Gnuboard5 treats all three as equal category memberships.
    category2 = models.ForeignKey(
        ShopCategory,
        to_field="ca_id",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="secondary_products",
        verbose_name=_("Secondary category"),
    )
    category3 = models.ForeignKey(
        ShopCategory,
        to_field="ca_id",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tertiary_products",
        verbose_name=_("Tertiary category"),
    )
    it_name = models.CharField(max_length=255)
    it_seo_title = models.SlugField(max_length=255, blank=True, default="", allow_unicode=True)
    it_brand = models.CharField(max_length=255, blank=True, default="")
    it_maker = models.CharField(max_length=255, blank=True, default="")
    it_origin = models.CharField(max_length=255, blank=True, default="")
    it_model = models.CharField(max_length=255, blank=True, default="")
    it_price = models.IntegerField(default=0)
    it_basic_price = models.IntegerField(default=0)
    it_cust_price = models.IntegerField(default=0)
    it_hit = models.PositiveIntegerField(default=0)
    it_update_time = models.DateTimeField(null=True, blank=True)
    it_order = models.IntegerField(default=0)
    it_sum_qty = models.PositiveIntegerField(default=0)
    it_use_cnt = models.PositiveIntegerField(default=0)
    it_use_avg = models.DecimalField(max_digits=2, decimal_places=1, default=0)
    it_point = models.IntegerField(default=0)
    it_point_type = models.PositiveSmallIntegerField(default=0)
    it_stock_qty = models.IntegerField(default=9999)
    it_buy_min_qty = models.PositiveIntegerField(default=1)
    it_buy_max_qty = models.PositiveIntegerField(default=0)
    it_tel_inq = models.CharField(max_length=1, blank=True, default="")
    it_soldout = models.CharField(max_length=1, blank=True, default="")
    it_use = models.CharField(max_length=1, blank=True, default="1")
    it_stock_sms = models.CharField(max_length=1, blank=True, default="")
    it_sc_type = models.PositiveSmallIntegerField(default=0)
    it_sc_method = models.PositiveSmallIntegerField(default=0)
    it_sc_price = models.IntegerField(default=3000)
    it_sc_minimum = models.IntegerField(default=50000)
    it_sc_qty = models.PositiveIntegerField(default=0)
    it_notax = models.PositiveSmallIntegerField(default=0)
    it_type1 = models.CharField(max_length=1, blank=True, default="")
    it_type2 = models.CharField(max_length=1, blank=True, default="")
    it_type3 = models.CharField(max_length=1, blank=True, default="")
    it_type4 = models.CharField(max_length=1, blank=True, default="")
    it_type5 = models.CharField(max_length=1, blank=True, default="")
    it_basic = models.TextField(blank=True, default="")
    it_content = models.TextField(blank=True, default="")
    it_explan = models.TextField(blank=True, default="")
    it_head_html = models.TextField(blank=True, default="")
    it_tail_html = models.TextField(blank=True, default="")
    it_info_gubun = models.CharField(max_length=100, blank=True, default="")
    # Legacy column: older imports put YoungCart it_info_value here (cut at 255 characters).
    # Rows now live in it_info_value; a leftover plain text is still shown as the notice text.
    it_info_title = models.CharField(max_length=255, blank=True, default="")
    # 상품정보제공고시 rows: [{"key", "title", "value"}] (see gnu_jango.shop.item_info).
    it_info_value = models.JSONField(default=list, blank=True)
    it_option_subject = models.CharField(max_length=255, blank=True, default="")
    it_supply_subject = models.CharField(max_length=255, blank=True, default="")
    # youngcart it_nocoupon: product and category coupons do not apply to this product.
    it_nocoupon = models.BooleanField(
        "쿠폰적용안함",
        default=False,
        help_text="체크하면 개별상품 · 분류 쿠폰을 이 상품에 쓸 수 없습니다. 주문 · 배송비 쿠폰은 그대로 적용됩니다.",
    )
    image_url = models.CharField(max_length=1000, blank=True, default="")
    images = models.JSONField(default=list, blank=True)
    options = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "it_id"]
        verbose_name = _("Shop product")
        verbose_name_plural = _("Shop products")

    def __str__(self):
        return f"{self.it_id}: {self.it_name}"

    @property
    def category_ids(self):
        """Distinct assigned category ids in ca_id, ca_id2, ca_id3 order."""
        ids = (self.category_id, self.category2_id, self.category3_id)
        return tuple(dict.fromkeys(ca_id for ca_id in ids if ca_id))


class ShopProductRelation(models.Model):
    """youngcart g5_shop_item_relation: one row per (product, related product), listed by ir_no.

    The admin keeps both directions like itemformupdate.php (adding B to A also lists A on B)."""

    product = models.ForeignKey(ShopProduct, on_delete=models.CASCADE, related_name="relations")
    related = models.ForeignKey(
        ShopProduct, on_delete=models.CASCADE, related_name="related_from", verbose_name="관련상품"
    )
    ir_no = models.IntegerField("순서", default=0)

    class Meta:
        ordering = ["ir_no", "pk"]
        verbose_name = "관련상품"
        verbose_name_plural = "관련상품"
        constraints = [
            models.UniqueConstraint(fields=["product", "related"], name="shop_product_relation_unique_pair"),
            models.CheckConstraint(
                condition=~models.Q(product=models.F("related")), name="shop_product_relation_not_self"
            ),
        ]

    def __str__(self):
        return f"{self.product_id} → {self.related_id}"


class ShopStockAdjustment(models.Model):
    SCOPE_CHOICES = [
        ("product", _("Product stock")),
        ("option", _("Option stock")),
    ]

    product = models.ForeignKey(
        ShopProduct,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_adjustments",
    )
    it_id = models.CharField(max_length=40, db_index=True)
    it_name = models.CharField(max_length=255, blank=True, default="")
    scope = models.CharField(max_length=10, choices=SCOPE_CHOICES)
    io_id = models.CharField(max_length=255, blank=True, default="")
    io_type = models.PositiveSmallIntegerField(null=True, blank=True)
    before_qty = models.IntegerField()
    delta = models.IntegerField()
    after_qty = models.IntegerField()
    reason = models.CharField(max_length=255)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shop_stock_adjustments",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = _("Shop stock adjustment")
        verbose_name_plural = _("Shop stock adjustments")
        indexes = [
            models.Index(fields=["it_id", "created_at"]),
            models.Index(fields=["scope", "created_at"]),
        ]

    def __str__(self):
        return f"{self.it_id} {self.before_qty} → {self.after_qty} ({self.delta:+d})"


class ShopStockNotification(models.Model):
    SOURCE_CHOICES = [
        ("api", _("API registration")),
        ("legacy-smoke", _("Migrated temporary registration")),
        ("legacy-db", _("Imported Gnuboard registration")),
    ]

    product = models.ForeignKey(
        ShopProduct,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_notifications",
    )
    it_id = models.CharField(max_length=40, db_index=True)
    ss_hp = models.CharField(max_length=255)
    ss_send = models.BooleanField(default=False)
    ss_send_time = models.DateTimeField(null=True, blank=True)
    ss_datetime = models.DateTimeField(default=timezone.now, null=True, blank=True)
    ss_ip = models.CharField(max_length=45, blank=True, default="")
    legacy_ss_id = models.PositiveIntegerField(null=True, blank=True, unique=True)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default="api")

    class Meta:
        ordering = ["-ss_datetime", "-pk"]
        verbose_name = _("Restock notification")
        verbose_name_plural = _("Restock notifications")
        indexes = [
            models.Index(fields=["it_id", "ss_send"]),
            models.Index(fields=["ss_send", "ss_datetime"]),
        ]

    def __str__(self):
        return f"{self.it_id}: {self.ss_hp}"


class ShopStockNotificationSendLog(models.Model):
    STATUS_CHOICES = [
        ("sending", _("Sending")),
        ("accepted", _("Accepted by gateway")),
        ("rejected", _("Rejected by gateway")),
        ("unknown", _("Outcome unknown")),
        ("skipped", _("Skipped")),
    ]

    notification = models.ForeignKey(
        ShopStockNotification,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="send_logs",
    )
    product_it_id = models.CharField(max_length=40, blank=True, default="")
    recipient_last4 = models.CharField(max_length=4, blank=True, default="")
    message = models.TextField(blank=True, default="")
    provider = models.CharField(max_length=20, default="icode")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="sending", db_index=True)
    provider_code = models.CharField(max_length=40, blank=True, default="")
    error_text = models.TextField(blank=True, default="")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shop_stock_sms_logs",
    )
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = _("Restock SMS send log")
        verbose_name_plural = _("Restock SMS send logs")
        indexes = [models.Index(fields=["product_it_id", "created_at"])]

    def __str__(self):
        return f"{self.product_it_id}: {self.get_status_display()} #{self.pk}"


class ShopWishlist(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="shop_wishlist",
    )
    session_key = models.CharField(max_length=80, blank=True, default="")
    product = models.ForeignKey(
        ShopProduct,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="wishlist_entries",
    )
    it_id = models.CharField(max_length=40)
    wi_time = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-wi_time", "-pk"]
        verbose_name = _("Shop wishlist")
        verbose_name_plural = _("Shop wishlists")
        indexes = [
            models.Index(fields=["session_key", "it_id"]),
            models.Index(fields=["user", "it_id"]),
        ]


def validate_coupon_target(cp_method, cp_target):
    """youngcart couponformupdate.php / couponzoneformupdate.php: a product or category coupon may
    not target a product or category marked 쿠폰적용안함 (it_nocoupon / ca_nocoupon)."""
    target = str(cp_target or "").strip()
    if not target:
        return
    if cp_method == 0 and ShopProduct.objects.filter(pk=target, it_nocoupon=True).exists():
        raise ValidationError({"cp_target": "쿠폰적용안함으로 설정된 상품입니다. 이 상품에는 쿠폰을 만들 수 없습니다."})
    if cp_method == 1 and ShopCategory.objects.filter(pk=target, ca_nocoupon=True).exists():
        raise ValidationError({"cp_target": "쿠폰적용안함으로 설정된 분류입니다. 이 분류에는 쿠폰을 만들 수 없습니다."})


class ShopCouponZone(models.Model):
    cz_type = models.PositiveSmallIntegerField(default=0)
    cz_point = models.IntegerField(default=0)
    cz_subject = models.CharField(max_length=255)
    cz_start = models.DateField(default=timezone.localdate)
    cz_end = models.DateField(null=True, blank=True)
    cz_file = models.CharField(max_length=1000, blank=True, default="")
    cz_period = models.PositiveIntegerField(default=30)
    cz_download = models.PositiveIntegerField(default=0)
    cp_method = models.PositiveSmallIntegerField(default=2)
    cp_target = models.CharField(max_length=100, blank=True, default="")
    cp_type = models.PositiveSmallIntegerField(default=0)
    cp_price = models.IntegerField(default=0)
    cp_minimum = models.IntegerField(default=0)
    cp_maximum = models.IntegerField(default=0)
    cp_trunc = models.IntegerField(default=1)
    image_url = models.CharField(max_length=1000, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = _("Shop coupon zone")
        verbose_name_plural = _("Shop coupon zones")

    def __str__(self):
        return self.cz_subject

    def clean(self):
        super().clean()
        validate_coupon_target(self.cp_method, self.cp_target)


class ShopCoupon(models.Model):
    cp_id = models.CharField(max_length=40, primary_key=True, default=generate_coupon_id)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="shop_coupons",
    )
    coupon_zone = models.ForeignKey(
        ShopCouponZone,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_coupons",
    )
    cp_subject = models.CharField(max_length=255)
    cp_method = models.PositiveSmallIntegerField(default=2)
    cp_target = models.CharField(max_length=100, blank=True, default="")
    cp_type = models.PositiveSmallIntegerField(default=0)
    cp_price = models.IntegerField(default=0)
    cp_minimum = models.IntegerField(default=0)
    cp_maximum = models.IntegerField(default=0)
    cp_trunc = models.IntegerField(default=1)
    cp_start = models.DateField(default=timezone.localdate)
    cp_end = models.DateField(null=True, blank=True)
    cp_used = models.CharField(max_length=1, blank=True, default="")
    # YoungCart mb_id '전체회원': every member may use it once; use is tracked per member in the
    # coupon log (is_used_coupon), so cp_used stays empty
    cp_all_members = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-cp_id"]
        verbose_name = _("Shop coupon")
        verbose_name_plural = _("Shop coupons")
        indexes = [
            models.Index(fields=["user", "cp_used"]),
            models.Index(fields=["cp_method", "cp_target"]),
        ]

    def __str__(self):
        return f"{self.cp_id}: {self.cp_subject}"

    def clean(self):
        super().clean()
        validate_coupon_target(self.cp_method, self.cp_target)


class ShopCouponLog(models.Model):
    cl_id = models.BigIntegerField(primary_key=True)
    coupon = models.ForeignKey(
        ShopCoupon,
        to_field="cp_id",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="usage_logs",
    )
    cp_id = models.CharField(max_length=40, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shop_coupon_logs",
    )
    mb_id = models.CharField(max_length=150, blank=True, default="")
    order = models.ForeignKey(
        "ShopOrder",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="coupon_logs",
    )
    od_id = models.CharField(max_length=40, blank=True, default="")
    cp_price = models.IntegerField(default=0)
    cl_datetime = models.DateTimeField(default=timezone.now)

    history = HistoricalRecords()

    class Meta:
        ordering = ["-cl_datetime", "-cl_id"]
        verbose_name = _("Shop coupon log")
        verbose_name_plural = _("Shop coupon logs")
        indexes = [
            models.Index(fields=["cp_id"]),
            models.Index(fields=["od_id"]),
            models.Index(fields=["user", "cl_datetime"]),
        ]


class ShopAddress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shop_addresses")
    ad_subject = models.CharField(max_length=100, blank=True, default="")
    ad_default = models.BooleanField(default=False)
    ad_name = models.CharField(max_length=100, blank=True, default="")
    ad_tel = models.CharField(max_length=50, blank=True, default="")
    ad_hp = models.CharField(max_length=50, blank=True, default="")
    ad_zip = models.CharField(max_length=20, blank=True, default="")
    ad_addr1 = models.CharField(max_length=255, blank=True, default="")
    ad_addr2 = models.CharField(max_length=255, blank=True, default="")
    ad_addr3 = models.CharField(max_length=255, blank=True, default="")
    ad_jibeon = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-ad_default", "-created_at", "-pk"]
        verbose_name = _("Shop address")
        verbose_name_plural = _("Shop addresses")


class ShopOrder(models.Model):
    od_id = models.CharField(max_length=40, primary_key=True)
    uid = models.CharField(max_length=64, default=generate_order_uid, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shop_orders",
    )
    od_name = models.CharField(max_length=100, blank=True, default="")
    od_tel = models.CharField(max_length=50, blank=True, default="")
    od_hp = models.CharField(max_length=50, blank=True, default="")
    od_email = models.EmailField(blank=True, default="")
    od_zip = models.CharField(max_length=20, blank=True, default="")
    od_addr1 = models.CharField(max_length=255, blank=True, default="")
    od_addr2 = models.CharField(max_length=255, blank=True, default="")
    od_addr3 = models.CharField(max_length=255, blank=True, default="")
    od_b_name = models.CharField(max_length=100, blank=True, default="")
    od_b_tel = models.CharField(max_length=50, blank=True, default="")
    od_b_hp = models.CharField(max_length=50, blank=True, default="")
    od_b_zip = models.CharField(max_length=20, blank=True, default="")
    od_b_addr1 = models.CharField(max_length=255, blank=True, default="")
    od_b_addr2 = models.CharField(max_length=255, blank=True, default="")
    od_b_addr3 = models.CharField(max_length=255, blank=True, default="")
    od_memo = models.TextField(blank=True, default="")
    # youngcart od_shop_memo / od_mod_history: an admin-only memo, and the log of admin changes
    # (status moves, cancellations, refunds); neither is shown to the customer.
    od_shop_memo = models.TextField("관리자 메모", blank=True, default="")
    od_mod_history = models.TextField("주문 변경 이력", blank=True, default="")
    # youngcart 희망배송일 (de_hope_date_use); empty when the shop does not ask for one.
    od_hope_date = models.DateField(null=True, blank=True)
    od_cart_price = models.IntegerField(default=0)
    od_send_cost = models.IntegerField(default=0)
    od_send_cost2 = models.IntegerField(default=0)
    od_receipt_price = models.IntegerField(default=0)
    od_cancel_price = models.IntegerField(default=0)
    # youngcart od_refund_price: what was paid back (PG cancel or a manual bank refund);
    # od_receipt_price keeps what the customer paid.
    od_refund_price = models.IntegerField("환불금액", default=0)
    od_receipt_point = models.IntegerField(default=0)
    od_bank_account = models.CharField(_("Bank account"), max_length=255, blank=True, default="")
    od_vbank_bank_code = models.CharField(max_length=10, blank=True, default="")
    od_vbank_account = models.CharField(max_length=20, blank=True, default="")
    od_vbank_customer_name = models.CharField(max_length=100, blank=True, default="")
    od_vbank_due_date = models.CharField(max_length=40, blank=True, default="")
    od_vbank_secret_hash = models.CharField(max_length=64, blank=True, default="")
    od_vbank_status = models.CharField(max_length=32, blank=True, default="")
    od_deposit_name = models.CharField(max_length=100, blank=True, default="")
    od_status = models.CharField(max_length=50, default="order")
    od_settle_case = models.CharField(max_length=50, blank=True, default="bank")
    od_test = models.CharField(max_length=1, blank=True, default="")
    od_misu = models.IntegerField(default=0)
    od_pg = models.CharField(max_length=50, blank=True, default="")
    od_tno = models.CharField(max_length=255, blank=True, default="")
    od_app_no = models.CharField(max_length=255, blank=True, default="")
    od_tax_flag = models.PositiveSmallIntegerField(default=0)
    od_tax_invoice_request = models.BooleanField(_("Tax invoice requested"), default=False)
    od_tax_company = models.CharField(_("Tax invoice company"), max_length=100, blank=True, default="")
    od_tax_business_no = models.CharField(_("Tax invoice business number"), max_length=10, blank=True, default="")
    od_tax_email = models.EmailField(_("Tax invoice email"), blank=True, default="")
    od_tax_mny = models.IntegerField(default=0)
    od_vat_mny = models.IntegerField(default=0)
    od_free_mny = models.IntegerField(default=0)
    od_coupon = models.IntegerField(default=0)
    od_send_coupon = models.IntegerField(default=0)
    od_point = models.IntegerField(default=0)
    od_cash_request = models.BooleanField(_("Cash receipt requested"), default=False)
    od_cash_type = models.CharField(
        _("Cash receipt type"),
        max_length=10,
        blank=True,
        default="",
        choices=(("income", _("Income deduction")), ("expense", _("Business expense proof"))),
    )
    od_cash_no = models.CharField(max_length=255, blank=True, default="")
    od_cash_res = models.CharField(max_length=255, blank=True, default="")
    od_delivery_company = models.CharField(max_length=100, blank=True, default="")
    od_invoice = models.CharField(max_length=100, blank=True, default="")
    od_invoice_time = models.CharField(max_length=100, blank=True, default="")
    od_datetime = models.DateTimeField(default=timezone.now)
    od_receipt_time = models.CharField(max_length=100, blank=True, default="")
    od_ip = models.GenericIPAddressField(null=True, blank=True)

    # Field-level audit trail. The IP and the virtual-account secret hash are deliberately
    # excluded: they are sensitive and never need to be restored from history.
    history = HistoricalRecords(excluded_fields=["od_ip", "od_vbank_secret_hash"])

    class Meta:
        ordering = ["-od_datetime", "-od_id"]
        verbose_name = _("Shop order")
        verbose_name_plural = _("Shop orders")
        indexes = [
            models.Index(fields=["od_datetime", "od_status"]),
            models.Index(fields=["od_misu", "od_datetime"]),
            models.Index(fields=["od_receipt_price", "od_datetime"]),
            models.Index(fields=["od_cancel_price", "od_datetime"]),
            models.Index(fields=["od_invoice", "od_datetime"]),
            models.Index(fields=["od_pg", "od_datetime"]),
            models.Index(fields=["od_settle_case", "od_datetime"]),
        ]

    def __str__(self):
        return self.od_id


class ShopOrderItem(models.Model):
    order = models.ForeignKey(ShopOrder, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(ShopProduct, on_delete=models.SET_NULL, null=True, blank=True)
    ct_id = models.CharField(max_length=40)
    it_id = models.CharField(max_length=40)
    it_name = models.CharField(max_length=255)
    ct_price = models.IntegerField(default=0)
    ct_qty = models.PositiveIntegerField(default=1)
    ct_point = models.IntegerField(default=0)
    # youngcart ct_point_use / ct_complete_time: the purchase point of this line was handled,
    # and when the line first reached the completed status (the de_point_days clock).
    ct_point_use = models.BooleanField(default=False)
    ct_complete_time = models.DateTimeField(null=True, blank=True)
    ct_option = models.CharField(max_length=255, blank=True, default="")
    ct_status = models.CharField(max_length=50, default="order")
    io_type = models.PositiveSmallIntegerField(default=0)
    io_price = models.IntegerField(default=0)
    ct_notax = models.PositiveSmallIntegerField(default=0)
    ct_send_cost = models.IntegerField(default=0)
    stock_adjusted = models.BooleanField(default=False)
    image_url = models.CharField(max_length=1000, blank=True, default="")

    class Meta:
        ordering = ["pk"]
        verbose_name = _("Shop order item")
        verbose_name_plural = _("Shop order items")
        indexes = [
            models.Index(fields=["it_id", "it_name"]),
            models.Index(fields=["ct_status"]),
            models.Index(fields=["product", "ct_status"]),
        ]

    def sync_complete_time(self):
        """Stamp ct_complete_time when the line is 완료 without one, clear it otherwise
        (youngcart get_cart_complete_time_sql). Returns True when it changed."""
        if self.ct_status == ORDER_ITEM_STATUS_COMPLETED:
            if self.ct_complete_time is None:
                self.ct_complete_time = timezone.now()
                return True
            return False
        if self.ct_complete_time is not None:
            self.ct_complete_time = None
            return True
        return False

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if self.sync_complete_time() and update_fields is not None and "ct_status" in update_fields:
            kwargs["update_fields"] = {*update_fields, "ct_complete_time"}
        super().save(*args, **kwargs)


class ShopOrderData(models.Model):
    log_id = models.CharField(max_length=40, primary_key=True, default=generate_log_id)
    order = models.ForeignKey(ShopOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="raw_logs")
    od_id = models.CharField(max_length=40, blank=True, default="")
    cart_id = models.CharField(max_length=40, blank=True, default="")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shop_order_data_logs",
    )
    mb_id = models.CharField(max_length=150, blank=True, default="")
    dt_pg = models.CharField(max_length=50, blank=True, default="")
    dt_data = models.TextField(blank=True, default="")
    dt_time = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-dt_time", "-log_id"]
        verbose_name = _("Shop order data")
        verbose_name_plural = _("Shop order data")
        indexes = [
            models.Index(fields=["od_id"]),
            models.Index(fields=["cart_id"]),
            models.Index(fields=["dt_pg", "dt_time"]),
        ]

    def __str__(self):
        return self.log_id


class ShopPersonalPay(models.Model):
    pp_id = models.CharField(max_length=40, primary_key=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shop_personal_pays",
    )
    order = models.ForeignKey(ShopOrder, on_delete=models.SET_NULL, null=True, blank=True, related_name="personal_pays")
    pp_name = models.CharField(max_length=100)
    pp_email = models.EmailField(blank=True, default="")
    pp_hp = models.CharField(max_length=50, blank=True, default="")
    pp_content = models.TextField(blank=True, default="")
    pp_price = models.IntegerField(default=0)
    pp_settle_case = models.CharField(max_length=50, blank=True, default="bank")
    pp_bank_account = models.CharField(max_length=255, blank=True, default="")
    pp_deposit_name = models.CharField(max_length=100, blank=True, default="")
    pp_receipt_price = models.IntegerField(default=0)
    pp_pg = models.CharField(max_length=50, blank=True, default="")
    pp_tno = models.CharField(max_length=255, blank=True, default="")
    pp_app_no = models.CharField(max_length=255, blank=True, default="")
    pp_cash = models.PositiveSmallIntegerField(default=0)
    pp_cash_no = models.CharField(max_length=255, blank=True, default="")
    pp_receipt_time = models.CharField(max_length=100, blank=True, default="")
    pp_time = models.DateTimeField(default=timezone.now)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-pp_time", "-pp_id"]
        verbose_name = _("Shop personal pay")
        verbose_name_plural = _("Shop personal pays")
        indexes = [
            models.Index(fields=["active", "pp_time"]),
            models.Index(fields=["active", "pp_receipt_price"]),
            models.Index(fields=["pp_settle_case", "pp_time"]),
        ]

    def __str__(self):
        return self.pp_id


class ShopReview(models.Model):
    product = models.ForeignKey(ShopProduct, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviews")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    mb_id = models.CharField(max_length=150, blank=True, default="")
    mb_nick = models.CharField(max_length=150, blank=True, default="")
    is_name = models.CharField(max_length=150, blank=True, default="")
    is_score = models.PositiveSmallIntegerField(default=5)
    is_subject = models.CharField(max_length=255)
    is_content = models.TextField(blank=True, default="")
    is_confirm = models.CharField(max_length=1, blank=True, default="1")
    is_time = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-is_time", "-pk"]
        verbose_name = _("Shop review")
        verbose_name_plural = _("Shop reviews")


class ShopQA(models.Model):
    product = models.ForeignKey(ShopProduct, on_delete=models.SET_NULL, null=True, blank=True, related_name="qas")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    mb_id = models.CharField(max_length=150, blank=True, default="")
    mb_nick = models.CharField(max_length=150, blank=True, default="")
    iq_name = models.CharField(max_length=150, blank=True, default="")
    iq_subject = models.CharField(max_length=255)
    iq_question = models.TextField(blank=True, default="")
    iq_answer = models.TextField(blank=True, default="")
    iq_secret = models.PositiveSmallIntegerField(default=0)
    iq_email = models.EmailField(blank=True, default="")
    iq_hp = models.CharField(max_length=50, blank=True, default="")
    iq_time = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-iq_time", "-pk"]
        verbose_name = _("Shop QA")
        verbose_name_plural = _("Shop QAs")


class GeneralInquiry(ShopQA):
    """1:1 inquiries (Gnuboard5 bbs/qa*): ShopQA rows on the "__general_qa__" pseudo product, kept apart
    from product questions in the admin."""

    class Meta:
        proxy = True
        verbose_name = "1:1 문의"
        verbose_name_plural = "1:1 문의"


# Some shop records keep companion rows in the Config side table, keyed by the
# record's id. Until now only the API delete paths cleared them, so deleting
# through the admin or a queryset left the companion row behind -- a cleanup
# found 24 stale qa_meta rows and 57 stale guest_order_pwd rows. post_delete
# fires for admin deletes and queryset deletes alike, so the row now goes
# wherever the record does.
#
# The helpers live in gnu_jango.api, which imports this module, so they are
# imported inside the handlers to avoid a circular import at load time.


@receiver(models.signals.post_delete, sender=ShopQA)
@receiver(models.signals.post_delete, sender=GeneralInquiry)  # deletes from the 1:1 admin send the proxy
def delete_qa_meta_on_delete(sender, instance, **kwargs):
    """Drop the qa_meta config row (and its attachments) with the Q&A."""
    from gnu_jango.api.v1_community import _qa_delete_meta

    _qa_delete_meta(instance.pk)


@receiver(models.signals.post_delete, sender=ShopOrder)
def delete_guest_order_password_on_delete(sender, instance, **kwargs):
    """Drop the guest order password hash with the order it unlocks."""
    from gnu_jango.api.v1_shop import guest_order_password_config_name
    from gnu_jango.config.models import Config

    Config.objects.filter(name=guest_order_password_config_name(instance.od_id)).delete()
