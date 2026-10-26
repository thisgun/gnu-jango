"""List-size copies of shop and board pictures, made by Django instead of sending the original.

List payloads carry `thumbnail_url(url, width)`: product cards and gallery cards 400px, cart and
order lines 240px, banners 1440px. Detail pages keep the original `images`. The copy is made once
with sorl-thumbnail, kept in the default storage (local media or the S3 bucket) and served with a
year-long cache, as WebP when the browser accepts it. An original PNG of ~330KB becomes ~20KB.

Every copy URL carries an HMAC of its own path, so the view only resizes pictures the API handed
out; it never opens an arbitrary media name (an attachment of a secret post stays unreachable).
"""

import re
import hashlib
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit

from django.conf import settings
from django.core.files.storage import FileSystemStorage, default_storage
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.http import require_safe

THUMBNAIL_WIDTHS = (240, 400, 800, 1440, 1920)
THUMBNAIL_QUALITY = 80
THUMBNAIL_URL_PREFIX = "/api/v1/thumbs/"
THUMBNAIL_CACHE_CONTROL = "public, max-age=31536000, s-maxage=31536000, immutable"
MAX_SOURCE_BYTES = 20 * 1024 * 1024
# A small file can still decode to a huge bitmap (a "decompression bomb"): refuse more pixels than
# a large photo has (40MP, e.g. 8000x5000) before anything is decoded.
MAX_SOURCE_PIXELS = 40_000_000
WEBP_REFUSED_RE = re.compile(r"image/webp\s*;\s*q\s*=\s*0(?:\.0*)?(?:\s*[,;]|\s*$)", re.IGNORECASE)
RESIZABLE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
# Gnuboard data folders the copies may read. Legacy banners are saved without an extension.
DATA_AREAS = {"item", "banner", "event", "file"}
EXTENSIONLESS_DATA_AREAS = {"banner"}
SIGNATURE_SALT = "gnu_jango.core.thumbnails"
SIGNATURE_LENGTH = 20


class LegacyDataStorage(FileSystemStorage):
    """One Gnuboard data folder. Its own class keeps sorl's cache keys apart from media files."""


def _clean_path(value):
    from gnu_jango.core.views import LEGACY_DATA_DENIED_NAME_RE, _safe_relative_path

    path = _safe_relative_path(value)
    if not path or LEGACY_DATA_DENIED_NAME_RE.search(path):
        return None
    return path


def _resizable(kind, path):
    suffix = PurePosixPath(path).suffix.lower()
    if suffix in RESIZABLE_EXTENSIONS:
        return True
    return kind == "data" and suffix == "" and path.split("/", 1)[0] in EXTENSIONLESS_DATA_AREAS


def _signature(width, kind, path):
    return salted_hmac(SIGNATURE_SALT, f"{width}/{kind}/{path}").hexdigest()[:SIGNATURE_LENGTH]


def _copy_url(width, kind, path, version=""):
    url = f"{THUMBNAIL_URL_PREFIX}{_signature(width, kind, path)}/{width}/{kind}/{quote(path)}"
    return f"{url}?v={version}" if version else url


def _legacy_file(path):
    """The local file for "area/rest" in a Gnuboard data folder, with the folder, or (None, None)."""
    from gnu_jango.core.legacy_assets import legacy_area_roots

    area, _, rest = path.partition("/")
    if area not in DATA_AREAS or not rest:
        return None, None
    for root in legacy_area_roots(area):
        try:
            resolved_root = root.resolve()
            candidate = (resolved_root / rest).resolve()
        except (OSError, ValueError):
            continue
        if candidate.is_relative_to(resolved_root) and candidate.is_file():
            return candidate, resolved_root
    return None, None


def _local_path(url):
    """Path part of a URL on this site or on the legacy Gnuboard site; None for any other host."""
    parts = urlsplit(url)
    if not parts.netloc:
        return unquote(parts.path)
    legacy = urlsplit(str(getattr(settings, "LEGACY_GNUBOARD5_BASE_URL", "") or ""))
    if legacy.netloc and parts.netloc.lower() == legacy.netloc.lower():
        return unquote(parts.path)
    return None


def thumbnail_url(url, width, *, storage_path=""):
    """URL of a `width`-wide copy of the picture at `url`, or `url` unchanged when there is none.

    `storage_path` names the file in the default storage when the URL itself cannot (an S3 URL
    is signed and expires). Pictures this server cannot read keep their original URL.
    """
    value = str(url or "").strip()
    if width not in THUMBNAIL_WIDTHS or not (value or storage_path):
        return value

    if storage_path:
        path = _clean_path(storage_path)
        return _copy_url(width, "media", path) if path and _resizable("media", path) else value

    local = _local_path(value)
    if local is None:
        return value
    media_url = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/")
    if local.startswith(media_url):
        path = _clean_path(local[len(media_url):])
        return _copy_url(width, "media", path) if path and _resizable("media", path) else value
    if local.startswith("/data/"):
        path = _clean_path(local[len("/data/"):])
        if not path or not _resizable("data", path):
            return value
        file_path, _ = _legacy_file(path)
        if file_path is None:
            return value
        try:
            version = str(int(file_path.stat().st_mtime))
        except OSError:
            version = ""
        return _copy_url(width, "data", path, version)
    return value


def _source(kind, path):
    """The picture to resize as (name, storage), or None when it is not there or too big."""
    if kind == "media":
        storage, name = default_storage, path
    else:
        file_path, root = _legacy_file(path)
        if file_path is None:
            return None
        storage, name = LegacyDataStorage(location=str(root)), file_path.relative_to(root).as_posix()
    try:
        if not storage.exists(name) or storage.size(name) > MAX_SOURCE_BYTES:
            return None
    except (OSError, ValueError, NotImplementedError):
        return None
    return name, storage


def _output_format(request, path):
    accept = request.headers.get("Accept") or ""
    if "image/webp" in accept.lower() and not WEBP_REFUSED_RE.search(accept):
        return "WEBP", "image/webp"
    if PurePosixPath(path).suffix.lower() in {".png", ".webp"}:
        return "PNG", "image/png"
    return "JPEG", "image/jpeg"


def _make_copy(name, storage, width, image_format):
    from PIL import Image
    from sorl.thumbnail import default as sorl_default
    from sorl.thumbnail import get_thumbnail
    from sorl.thumbnail.images import ImageFile

    with storage.open(name, "rb") as handle, Image.open(handle) as header:  # reads the header only
        width_px, height_px = header.size
    if width_px * height_px > MAX_SOURCE_PIXELS:
        raise ValueError(f"{name} has {width_px}x{height_px} pixels, more than a copy is made from")

    source = ImageFile(name, storage=storage)
    options = {"upscale": False, "format": image_format, "quality": THUMBNAIL_QUALITY}
    copy = get_thumbnail(source, str(width), **options)
    try:
        return copy.read()
    except (OSError, ValueError):
        # The key-value store remembered a copy whose file is gone: forget it and make it again.
        sorl_default.kvstore.delete(copy)
        return get_thumbnail(source, str(width), **options).read()


def _original_redirect(kind, path):
    """When no copy can be made, send the browser to the original so the picture still shows."""
    url = default_storage.url(path) if kind == "media" else f"/data/{quote(path)}"
    response = HttpResponseRedirect(url)
    response["Cache-Control"] = "no-store"
    return response


def thumbnail_artifact_name(kind, path, width, image_format):
    digest = hashlib.sha256(f"v1:{kind}:{path}:{width}:{image_format}".encode()).hexdigest()
    return f"background-thumbnails/{digest}.{image_format.lower()}"


@require_safe
def thumbnail_view(request, signature, width, kind, path):
    clean = _clean_path(path)
    if (
        width not in THUMBNAIL_WIDTHS
        or kind not in {"media", "data"}
        or not clean
        or not _resizable(kind, clean)
        or not constant_time_compare(signature, _signature(width, kind, clean))
    ):
        raise Http404("Thumbnail not found")
    source = _source(kind, clean)
    if source is None:
        raise Http404("Thumbnail not found")

    image_format, content_type = _output_format(request, clean)
    from .background import enabled, enqueue
    if enabled():
        payload = {"kind": kind, "path": clean, "width": width, "image_format": image_format}
        artifact = thumbnail_artifact_name(**payload)
        if default_storage.exists(artifact):
            response = FileResponse(default_storage.open(artifact, "rb"), content_type=content_type)
            response["Cache-Control"] = THUMBNAIL_CACHE_CONTROL
            response["Vary"] = "Accept"
            response["X-Content-Type-Options"] = "nosniff"
            return response
        # Only the request path is signed; workers cannot fetch user-supplied remote URLs.
        enqueue("thumbnail", payload, active_key=f"thumbnail:{artifact}")
        return _original_redirect(kind, clean)
    try:
        content = _make_copy(*source, width, image_format)
    except Exception:  # noqa: BLE001 - a broken, huge or hostile upload must not become a 500
        content = b""
    if not content:
        return _original_redirect(kind, clean)

    response = HttpResponse(content, content_type=content_type)
    response["Cache-Control"] = THUMBNAIL_CACHE_CONTROL
    response["Vary"] = "Accept"
    response["X-Content-Type-Options"] = "nosniff"
    return response
