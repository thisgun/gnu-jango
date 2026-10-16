"""Remove location and camera metadata from uploaded photos before they are stored.

Boards, the editor and profiles serve the original upload, so EXIF (GPS position, camera serial,
time), XMP and text chunks would be published with every phone photo. JPEG and WebP that carry such
metadata are re-encoded once with the EXIF orientation applied; PNG is rewritten losslessly. Files
without metadata, GIF (re-saving can break animation), other types and anything Pillow cannot read
are returned untouched — content validation stays the validators' job.
"""

import io
import logging
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

_LOSSY_FORMATS = {"JPEG": {"quality": 95}, "WEBP": {"quality": 95}}
_LOSSLESS_FORMATS = {"PNG": {"optimize": True}}
# Same ceiling as core/thumbnails.MAX_SOURCE_PIXELS: larger files are left as uploaded.
_MAX_PIXELS = 40_000_000
_METADATA_INFO_KEYS = ("exif", "xmp", "XML:com.adobe.xmp", "comment")


def _rewind(uploaded_file):
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError, ValueError):
        pass


def _has_metadata(image):
    if image.getexif():
        return True
    if any(image.info.get(key) for key in _METADATA_INFO_KEYS):
        return True
    return bool(getattr(image, "text", None))  # PNG tEXt/iTXt/zTXt chunks


def _cleaned_bytes(image, image_format):
    icc_profile = image.info.get("icc_profile")
    image = ImageOps.exif_transpose(image)
    image.info = {}  # Pillow copies comment/XMP from info when saving; drop everything.
    if image_format == "JPEG" and image.mode not in ("RGB", "L", "CMYK"):
        image = image.convert("RGB")
    options = dict(_LOSSY_FORMATS.get(image_format) or _LOSSLESS_FORMATS[image_format])
    if icc_profile:
        options["icc_profile"] = icc_profile
    buffer = io.BytesIO()
    image.save(buffer, image_format, **options)
    return buffer.getvalue()


def strip_image_metadata(uploaded_file):
    """The upload without photo metadata, or the same object when nothing needs removing."""
    _rewind(uploaded_file)
    try:
        with Image.open(uploaded_file) as image:
            image_format = image.format
            if image_format not in _LOSSY_FORMATS and image_format not in _LOSSLESS_FORMATS:
                return uploaded_file
            if image.width * image.height > _MAX_PIXELS or not _has_metadata(image):
                return uploaded_file
            image.load()
            data = _cleaned_bytes(image, image_format)
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return uploaded_file
    finally:
        _rewind(uploaded_file)

    name = os.path.basename(str(getattr(uploaded_file, "name", "") or "image"))
    content_type = getattr(uploaded_file, "content_type", None) or Image.MIME.get(image_format, "")
    logger.info("Removed photo metadata from an upload (%s).", image_format)
    return SimpleUploadedFile(name, data, content_type=content_type)
