"""Remove location and camera metadata from uploaded photos before they are stored.

Boards, the editor and profiles serve the original upload, so EXIF (GPS position, camera serial,
time), XMP, IPTC and text chunks would be published with every phone photo. JPEG (including the MPO
variant many phones write for portrait or depth shots) is re-encoded once with the EXIF orientation
applied; PNG is rewritten losslessly and keeps its transparency.

Left untouched: files without metadata (no needless recompression), animated images such as GIF,
APNG or animated WebP (re-saving would keep only the first frame), WebP (Pillow cannot tell a
lossless one apart, so re-encoding could degrade it), other types and anything Pillow cannot read —
content validation stays the validators' job.
"""

import io
import logging
import os

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger(__name__)

# Source format -> (stored format, save options). MPO keeps only its primary image, saved as JPEG;
# the extra frames are depth maps or previews, not part of the picture people see.
_SAVE_AS = {
    "JPEG": ("JPEG", {"quality": 95}),
    "MPO": ("JPEG", {"quality": 95}),
    "PNG": ("PNG", {"optimize": True}),
}
# Same ceiling as core/thumbnails.MAX_SOURCE_PIXELS: larger files are left as uploaded.
_MAX_PIXELS = 40_000_000
_METADATA_INFO_KEYS = ("exif", "xmp", "XML:com.adobe.xmp", "comment", "photoshop", "iptc")


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


def _is_animation(image):
    return image.format != "MPO" and (getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) > 1)


def _cleaned_bytes(image, source_format):
    stored_format, base_options = _SAVE_AS[source_format]
    options = dict(base_options)
    # Keep what affects how the picture looks; drop everything else Pillow would copy from info.
    if image.info.get("icc_profile"):
        options["icc_profile"] = image.info["icc_profile"]
    if stored_format == "PNG" and "transparency" in image.info:
        options["transparency"] = image.info["transparency"]
    image = ImageOps.exif_transpose(image)
    image.info = {}
    if stored_format == "JPEG" and image.mode not in ("RGB", "L", "CMYK"):
        image = image.convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, stored_format, **options)
    return buffer.getvalue()


def strip_image_metadata(uploaded_file):
    """The upload without photo metadata, or the same object when nothing needs removing."""
    _rewind(uploaded_file)
    try:
        with Image.open(uploaded_file) as image:
            source_format = image.format
            if source_format not in _SAVE_AS or _is_animation(image):
                return uploaded_file
            if image.width * image.height > _MAX_PIXELS or not _has_metadata(image):
                return uploaded_file
            image.load()
            data = _cleaned_bytes(image, source_format)
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError):
        return uploaded_file
    finally:
        _rewind(uploaded_file)

    name = os.path.basename(str(getattr(uploaded_file, "name", "") or "image"))
    content_type = getattr(uploaded_file, "content_type", None) or Image.MIME.get(_SAVE_AS[source_format][0], "")
    logger.info("Removed photo metadata from an upload (%s).", source_format)
    return SimpleUploadedFile(name, data, content_type=content_type)
