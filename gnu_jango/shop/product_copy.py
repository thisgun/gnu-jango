"""상품 복사 (youngcart itemcopyupdate.php).

The copy takes every product column except the id and the sales/review counters, its options
(stock included, as youngcart copies g5_shop_item_option) and its categories. Reviews, Q&A,
relations, events and wish lists stay with the original.

Images: an upload this site manages lives under ``shop/products/<it_id>/`` and is deleted when it
is removed from that product, so the copy gets its own copy of each such file (like youngcart
copying data/item/<it_id>/). Other images (imported /data/item/... paths or external URLs) are
not owned by any product here and are never deleted by it, so the copy keeps the same reference.
"""

import posixpath
import re
import time
import uuid

from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from django.utils.text import get_valid_filename

from gnu_jango.shop.images import _image_url, managed_product_image_storage_path
from gnu_jango.shop.models import ShopProduct

PRODUCT_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,20}$")  # itemcopyupdate.php, it_id varchar(20)
RESET_FIELDS = {
    "it_sum_qty": 0,
    "it_use_cnt": 0,
    "it_use_avg": 0,
    "it_hit": 0,
}


def next_product_id(*, reserved=()):
    """youngcart's default product code: the current unix time, moved on while it is taken."""
    candidate = int(time.time())
    taken = set(reserved)
    while str(candidate) in taken or ShopProduct.objects.filter(pk=str(candidate)).exists():
        candidate += 1
    return str(candidate)


def validate_new_product_id(it_id):
    it_id = str(it_id or "").strip()
    if not it_id:
        raise ValidationError("상품코드를 입력해 주세요.")
    if not PRODUCT_ID_PATTERN.match(it_id):
        raise ValidationError("상품코드는 영문자, 숫자, -, _ 만 20자까지 사용할 수 있습니다.")
    if ShopProduct.objects.filter(pk=it_id).exists():
        raise ValidationError("이미 존재하는 상품코드 입니다.")
    return it_id


def _copy_managed_image(image, source_id, new_id, stored_paths):
    storage_path = managed_product_image_storage_path(image, source_id)
    if not storage_path:
        return image
    name = posixpath.basename(storage_path)
    original_name = name.split("_", 1)[1] if "_" in name else name
    target = posixpath.join("shop", "products", get_valid_filename(new_id), f"{uuid.uuid4().hex}_{original_name}")
    try:
        with default_storage.open(storage_path, "rb") as source:
            saved = default_storage.save(target, source)
    except OSError:
        return None  # the file is gone: the copy goes without it
    stored_paths.append(saved)
    return {**image, "url": default_storage.url(saved), "storage_path": saved}


def _copied_images(product, new_id, stored_paths):
    images = product.images if isinstance(product.images, list) else []
    url_map = {}
    copied = []
    for image in images:
        new_image = _copy_managed_image(image, product.it_id, new_id, stored_paths)
        if new_image is image:
            copied.append(image)
            continue
        url_map[_image_url(image)] = new_image["url"] if new_image else ""
        if new_image:
            copied.append(new_image)
    primary = str(product.image_url or "").strip()
    image_url = url_map.get(primary, product.image_url)
    source_dir = f"/shop/products/{get_valid_filename(product.it_id)}/"
    if (primary in url_map and not image_url) or (primary not in url_map and source_dir in primary):
        # never leave the copy pointing at a file the source owns (and may delete)
        image_url = next((url for image in copied if (url := _image_url(image)) and source_dir not in url), "")
    return copied, image_url


def copy_product(source, new_it_id):
    """A new product ``new_it_id`` copied from ``source``; raises ValidationError on a bad id.

    A managed image whose file is missing is left out of the copy. When saving fails, the files
    copied so far are removed again."""
    new_it_id = validate_new_product_id(new_it_id)
    stored_paths = []
    try:
        with transaction.atomic():
            images, image_url = _copied_images(source, new_it_id, stored_paths)
            copy = ShopProduct.objects.get(pk=source.pk)
            copy.pk = new_it_id
            copy.it_id = new_it_id
            copy._state.adding = True
            for field, value in RESET_FIELDS.items():
                setattr(copy, field, value)
            # the SEO slug finds one product; youngcart makes a new one (shop_seo_title_update)
            copy.it_seo_title = ""
            copy.images = images
            copy.image_url = image_url
            copy.options = [dict(row) for row in (source.options or []) if isinstance(row, dict)]
            copy.created_at = timezone.now()
            copy.it_update_time = timezone.now()
            copy.save(force_insert=True)
    except Exception:
        for path in stored_paths:
            default_storage.delete(path)
        raise
    return copy
