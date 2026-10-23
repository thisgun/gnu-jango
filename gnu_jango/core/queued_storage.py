"""Publish a harmless placeholder; keep the original upload only in the private outbox.

Image decoding/re-encoding happens in the worker. Originals containing EXIF/location data
must never be briefly published while a conversion is pending.
"""
import base64
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import FileSystemStorage


class QueueImagesMixin:
    def _save(self, name, content):
        from .background import enabled, enqueue, executing
        if not enabled() or executing():
            return super()._save(name, content)
        from PIL import Image, UnidentifiedImageError
        content.seek(0)
        try:
            with Image.open(content) as image:
                image_format = image.format
                animated = getattr(image, "is_animated", False)
                if image.width * image.height > 40_000_000:
                    raise ValidationError("Image exceeds the processing pixel limit.")
        except Image.DecompressionBombError:
            raise ValidationError("Image exceeds the processing pixel limit.") from None
        except (UnidentifiedImageError, OSError, ValueError):
            image_format, animated = None, False
        finally:
            content.seek(0)
        # The existing privacy sanitizer rewrites only static JPEG/MPO/PNG files.
        if image_format is None and Path(name).suffix.lower() in {".jpg", ".jpeg", ".mpo", ".png"}:
            raise ValidationError("Invalid image upload.")
        if image_format not in {"JPEG", "MPO", "PNG"} or (animated and image_format != "MPO"):
            return super()._save(name, content)
        if content.size > 20 * 1024 * 1024:
            raise ValidationError("Queued image exceeds 20 MiB.")
        raw = content.read()
        content.seek(0)
        extension = "png" if image_format == "PNG" else "jpg"
        placeholder = (Path(__file__).parent / "assets" / f"processing.{extension}").read_bytes()
        stored = super()._save(name, ContentFile(placeholder))
        try:
            enqueue("image", {"name": stored, "data": base64.b64encode(raw).decode("ascii"),
                              "content_type": getattr(content, "content_type", "") or "application/octet-stream"})
        except Exception:
            self.delete(stored)
            raise
        return stored

    def delete(self, name):
        from .background import enabled, resource_digest
        if not enabled():
            return super().delete(name)
        from django.db import transaction
        from django.utils import timezone
        from .background_models import BackgroundJob
        with transaction.atomic():
            # Serialize removal with final publication; a delayed worker cannot resurrect it.
            jobs = list(BackgroundJob.objects.select_for_update().filter(
                kind="image", status__in=["pending", "running"], resource_key=resource_digest(name))
                .values_list("pk", flat=True))
            if jobs:
                BackgroundJob.objects.filter(pk__in=jobs).update(
                    status="dead", error_code="source_deleted", payload={}, active_key=None,
                    claim_token=None, lease_until=None, finished_at=timezone.now())
            return super().delete(name)


class QueuedFileSystemStorage(QueueImagesMixin, FileSystemStorage):
    pass
