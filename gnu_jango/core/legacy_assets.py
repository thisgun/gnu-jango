from pathlib import Path

from django.conf import settings


DEFAULT_LEGACY_GNUBOARD5_SOURCE_ROOT = Path(r"C:\xampp824\www\gnuboard5_3")


def _iter_configured_roots(value):
    if value is None:
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_configured_roots(item)
        return
    for item in str(value).replace("|", ",").split(","):
        root = item.strip().strip('"').strip("'")
        if root:
            yield root


def legacy_source_roots(extra_roots=None):
    configured = list(_iter_configured_roots(getattr(settings, "LEGACY_GNUBOARD5_SOURCE_ROOTS", "")))
    if extra_roots:
        configured.extend(_iter_configured_roots(extra_roots))
    if not configured:
        configured = [str(DEFAULT_LEGACY_GNUBOARD5_SOURCE_ROOT)]

    roots = []
    seen = set()
    for root in configured:
        path = Path(root).expanduser()
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        roots.append(resolved)
    return roots


def legacy_data_root(source_root):
    root = Path(source_root)
    return root if root.name.lower() == "data" else root / "data"


def legacy_area_roots(area, extra_roots=None, include_media=True):
    roots = []
    if include_media:
        roots.append(Path(settings.MEDIA_ROOT) / "data" / area)
    for source_root in legacy_source_roots(extra_roots):
        roots.append(legacy_data_root(source_root) / area)
    return roots


def existing_legacy_source_roots(extra_roots=None):
    return [root for root in legacy_source_roots(extra_roots) if root.exists()]


def first_existing_legacy_path(relative_path, extra_roots=None):
    clean_path = str(relative_path or "").replace("\\", "/").strip("/")
    if not clean_path or ".." in clean_path.split("/"):
        return None
    if clean_path == "data":
        return None
    if clean_path.startswith("data/"):
        clean_path = clean_path[5:]

    for source_root in legacy_source_roots(extra_roots):
        candidate = legacy_data_root(source_root) / clean_path
        if candidate.is_file():
            return candidate
    return None
