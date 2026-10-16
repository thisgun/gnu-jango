import logging
import posixpath
import uuid
from pathlib import PurePosixPath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils.text import get_valid_filename

from gnu_jango.bbs.models import validate_upload_file_content
from gnu_jango.core.image_privacy import strip_image_metadata
from gnu_jango.shop.models import ShopProduct


logger = logging.getLogger(__name__)

PRODUCT_IMAGE_ALLOWED_EXTENSIONS = {".gif", ".jpg", ".jpeg", ".png"}
DEFAULT_PRODUCT_IMAGE_MAX_UPLOAD_SIZE = 5 * 1024 * 1024


def validate_product_image_upload(uploaded_file):
    import os

    _, extension = os.path.splitext(str(uploaded_file.name or ""))
    if extension.lower() not in PRODUCT_IMAGE_ALLOWED_EXTENSIONS:
        raise ValidationError("Unsupported image file extension.")

    max_size = int(getattr(settings, "SHOP_PRODUCT_IMAGE_MAX_UPLOAD_SIZE", DEFAULT_PRODUCT_IMAGE_MAX_UPLOAD_SIZE))
    if uploaded_file.size and uploaded_file.size > max_size:
        raise ValidationError(f"Image file is too large. Maximum size is {max_size // (1024 * 1024)}MB.")

    validate_upload_file_content(uploaded_file)


def upload_product_images(it_id, uploaded_files):
    files = list(uploaded_files or [])
    if not files:
        raise ValidationError("Image file is required.")

    for uploaded_file in files:
        validate_product_image_upload(uploaded_file)

    stored_paths = []
    try:
        with transaction.atomic():
            product = ShopProduct.objects.select_for_update().filter(pk=it_id).first()
            if not product:
                raise ShopProduct.DoesNotExist
            if not isinstance(product.images, list):
                raise ValidationError("Product image data must be a list before uploads can be added.")

            safe_product_id = get_valid_filename(str(it_id))
            new_images = []
            for uploaded_file in files:
                raw_name = str(uploaded_file.name or "").replace("\\", "/").rsplit("/", 1)[-1]
                safe_name = get_valid_filename(raw_name)
                if not safe_name:
                    safe_name = "product-image"
                requested_path = posixpath.join(
                    "shop",
                    "products",
                    safe_product_id,
                    f"{uuid.uuid4().hex}_{safe_name}",
                )
                storage_path = default_storage.save(requested_path, strip_image_metadata(uploaded_file))
                stored_paths.append(storage_path)
                new_images.append({"url": default_storage.url(storage_path), "storage_path": storage_path})

            existing_images = list(product.images)
            primary_url = str(product.image_url or "").strip()
            if primary_url and not any(_image_url(item) == primary_url for item in existing_images):
                existing_images.insert(0, primary_url)
            product.images = [*existing_images, *new_images]
            if not product.image_url:
                product.image_url = new_images[0]["url"]
            product.save(update_fields=["images", "image_url", "updated_at"])
    except Exception:
        for storage_path in stored_paths:
            try:
                default_storage.delete(storage_path)
            except Exception:
                logger.exception("Could not remove an uncommitted product image upload: %s", storage_path)
        raise

    return product, [item["url"] for item in new_images]


def managed_product_image_storage_path(image, it_id):
    if not isinstance(image, dict):
        return ""
    storage_path = str(image.get("storage_path") or "").strip()
    if not storage_path or "\\" in storage_path or storage_path.startswith("/"):
        return ""

    parts = PurePosixPath(storage_path).parts
    if any(part in {"", ".", ".."} for part in parts):
        return ""
    normalized = PurePosixPath(storage_path).as_posix()
    safe_product_id = get_valid_filename(str(it_id))
    expected_prefix = f"shop/products/{safe_product_id}/"
    if normalized != storage_path or not normalized.startswith(expected_prefix):
        return ""
    return normalized


def _image_url(image):
    if isinstance(image, str):
        return image.strip()
    if isinstance(image, dict):
        return str(image.get("url") or image.get("src") or image.get("image_url") or "").strip()
    return ""


def delete_product_image_after_commit(storage_paths):
    for storage_path in set(storage_paths or []):
        try:
            default_storage.delete(storage_path)
        except Exception:
            logger.exception("Could not remove a detached product image: %s", storage_path)
