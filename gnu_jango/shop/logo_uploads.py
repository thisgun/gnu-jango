"""Shop logo uploads for the admin shop settings (youngcart's data/common/logo_img*)."""

import logging
import uuid
from pathlib import Path

from django import forms
from django.core.files.storage import default_storage
from django.core.validators import FileExtensionValidator

from gnu_jango.core.image_privacy import strip_image_metadata

from .shop_options import SHOP_LOGO_FIELDS

logger = logging.getLogger(__name__)

LOGO_MAX_BYTES = 2 * 1024 * 1024
LOGO_EXTENSIONS = ["jpg", "jpeg", "png", "gif", "webp"]
LOGO_UPLOAD_DIR = "shop/logo"


def validate_logo_size(uploaded_file):
    if uploaded_file.size and uploaded_file.size > LOGO_MAX_BYTES:
        raise forms.ValidationError("로고 이미지는 2MB 이하로 올려 주세요.")


def logo_form_fields():
    """An image field and a delete checkbox per logo, keyed by form field name."""
    fields = {}
    for name, label in SHOP_LOGO_FIELDS.items():
        fields[name] = forms.ImageField(
            label=label,
            required=False,
            validators=[FileExtensionValidator(LOGO_EXTENSIONS), validate_logo_size],
            help_text="JPG·PNG·GIF·WEBP, 2MB 이하. 올리지 않으면 테마 기본 로고를 씁니다.",
        )
        fields[f"{name}_delete"] = forms.BooleanField(label=f"{label} 삭제", required=False)
    return fields


def store_logo(name, uploaded_file):
    """Save an uploaded logo under a fresh name and return its storage name."""
    extension = Path(uploaded_file.name).suffix.lower()
    cleaned = strip_image_metadata(uploaded_file)
    return default_storage.save(f"{LOGO_UPLOAD_DIR}/{name}-{uuid.uuid4().hex}{extension}", cleaned)


def delete_logo_file(path):
    """Remove a replaced logo file; a missing file or storage error never blocks saving."""
    if not path or not str(path).startswith(f"{LOGO_UPLOAD_DIR}/"):
        return
    try:
        default_storage.delete(path)
    except Exception:  # noqa: BLE001 - the settings are already saved
        logger.warning("Could not delete the replaced shop logo %s.", path, exc_info=True)
