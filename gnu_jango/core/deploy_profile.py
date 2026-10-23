"""Readiness checks for the three deployment profiles (DEPLOY_PROFILE=vps|vercel|split).

``evaluate_deploy_profile`` only reads a settings-like object and an env mapping, so it is cheap to
test and is shared by ``manage.py check_deploy_profile`` and ``manage.py check_release_readiness``.
See docs/04-deploy/deployment-profiles.md for what each profile expects.
"""

from __future__ import annotations

import os

PROFILES = ("vps", "vercel", "split")
SPLIT_AUTH_MODES = ("proxy", "direct")

S3_STORAGE_BACKEND = "storages.backends.s3.S3Storage"
DATABASE_CACHE_BACKEND = "django.core.cache.backends.db.DatabaseCache"
REDIS_CACHE_BACKEND = "django.core.cache.backends.redis.RedisCache"
LOCMEM_CACHE_BACKEND = "django.core.cache.backends.locmem.LocMemCache"
SHARED_CACHE_BACKENDS = {DATABASE_CACHE_BACKEND, REDIS_CACHE_BACKEND}
INSECURE_SECRET_PREFIXES = ("unsafe-", "django-insecure")
MIN_SECRET_KEY_LENGTH = 50
MIN_CRON_SECRET_LENGTH = 16
DEFAULT_GUNICORN_WORKERS = 3  # Dockerfile default (GUNICORN_WORKERS)
SUPABASE_POOLER_HOST = "pooler.supabase.com"
SUPABASE_TRANSACTION_POOLER_PORT = 6543


def _result(name, label, status, details="", action=""):
    return {"name": name, "label": label, "status": status, "details": details, "action": action}


def _setting(settings_obj, name, default=None):
    return getattr(settings_obj, name, default)


def _env(env, name, default=""):
    value = env.get(name, None)
    return default if value is None else str(value).strip()


def _default_db(settings_obj):
    return (_setting(settings_obj, "DATABASES", {}) or {}).get("default", {}) or {}


def _default_cache(settings_obj):
    return (_setting(settings_obj, "CACHES", {}) or {}).get("default", {}) or {}


def _media_backend(settings_obj):
    storages = _setting(settings_obj, "STORAGES", {}) or {}
    # The queue wrapper delegates to exactly the same configured local/S3 storage.
    selected = storages.get("background_media_source") or storages.get("default", {})
    return selected.get("BACKEND", "")


def database_cache_table_exists(table):
    from django.db import connection

    try:
        return table in connection.introspection.table_names()
    except Exception:
        return False


# --------------------------------------------------------------------------------------------- #
#  Checks shared by every profile
# --------------------------------------------------------------------------------------------- #


def check_debug(settings_obj):
    if _setting(settings_obj, "DEBUG", False):
        return _result("debug", "DEBUG off", "fail", "DEBUG is on.", "Set DEBUG=False.")
    return _result("debug", "DEBUG off", "pass", "DEBUG is off.")


def check_secret_key(settings_obj):
    key = str(_setting(settings_obj, "SECRET_KEY", "") or "")
    weak = (
        not key
        or key.startswith(INSECURE_SECRET_PREFIXES)
        or len(key) < MIN_SECRET_KEY_LENGTH
        or len(set(key)) < 5
    )
    if weak:
        return _result(
            "secret_key",
            "SECRET_KEY",
            "fail",
            "SECRET_KEY is missing, a development default, or shorter than 50 characters.",
            "Generate one with `python -c \"from django.core.management.utils import get_random_secret_key as g;"
            " print(g())\"` and set SECRET_KEY.",
        )
    return _result("secret_key", "SECRET_KEY", "pass", "SECRET_KEY looks production-grade.")


def check_allowed_hosts(settings_obj):
    hosts = list(_setting(settings_obj, "ALLOWED_HOSTS", []) or [])
    if not hosts:
        return _result("allowed_hosts", "ALLOWED_HOSTS", "fail", "ALLOWED_HOSTS is empty.", "Set ALLOWED_HOSTS.")
    if "*" in hosts:
        return _result(
            "allowed_hosts", "ALLOWED_HOSTS", "warn", "ALLOWED_HOSTS contains '*'.", "List the real host names."
        )
    return _result("allowed_hosts", "ALLOWED_HOSTS", "pass", ", ".join(hosts))


def check_cache(settings_obj, *, cache_table_exists, allow_locmem_workers=None):
    cache = _default_cache(settings_obj)
    backend = cache.get("BACKEND", "")
    label = "Shared cache (CACHE_URL)"
    if backend == DATABASE_CACHE_BACKEND:
        table = cache.get("LOCATION", "")
        if not cache_table_exists(table):
            return _result(
                "cache",
                label,
                "fail",
                f"DatabaseCache table {table!r} does not exist.",
                "Run `python manage.py createcachetable` against this database.",
            )
        return _result("cache", label, "pass", f"DatabaseCache ({table}).")
    if backend == REDIS_CACHE_BACKEND:
        return _result("cache", label, "pass", "RedisCache.")
    if allow_locmem_workers is not None and backend == LOCMEM_CACHE_BACKEND:
        if allow_locmem_workers <= 1:
            return _result("cache", label, "pass", "LocMemCache with a single worker process.")
        return _result(
            "cache",
            label,
            "warn",
            f"LocMemCache with {allow_locmem_workers} worker processes: throttles, cooldowns and cache "
            "invalidation are counted per process.",
            "Set CACHE_URL=redis://... (compose ships a redis service) or CACHE_URL=db:// + createcachetable.",
        )
    return _result(
        "cache",
        label,
        "fail",
        f"{backend or 'No cache'} is not shared between serverless instances.",
        "Set CACHE_URL=db:// (then `python manage.py createcachetable`) or CACHE_URL=redis://...",
    )


# --------------------------------------------------------------------------------------------- #
#  Vercel + Supabase
# --------------------------------------------------------------------------------------------- #


def check_vercel_database(settings_obj, env):
    db = _default_db(settings_obj)
    label = "Postgres DATABASE_URL"
    engine = db.get("ENGINE", "")
    if "postgresql" not in engine or not _env(env, "DATABASE_URL"):
        return _result(
            "database",
            label,
            "fail",
            f"ENGINE={engine or '-'}; DATABASE_URL {'set' if _env(env, 'DATABASE_URL') else 'missing'}. "
            "A Vercel function has no persistent disk, so SQLite data would be lost.",
            "Set DATABASE_URL to the Supabase pooler connection string (port 6543, sslmode=require).",
        )
    host = str(db.get("HOST", "") or "")
    port = str(db.get("PORT", "") or "")
    if SUPABASE_POOLER_HOST in host and port == str(SUPABASE_TRANSACTION_POOLER_PORT):
        if not db.get("DISABLE_SERVER_SIDE_CURSORS"):
            return _result(
                "database",
                label,
                "fail",
                "Supabase transaction pooler without DISABLE_SERVER_SIDE_CURSORS: .iterator() queries break.",
                "Set DB_DISABLE_SERVER_SIDE_CURSORS=true.",
            )
        if db.get("CONN_MAX_AGE"):
            return _result(
                "database",
                label,
                "warn",
                "Persistent connections behind the transaction pooler keep pooler slots busy.",
                "Set DB_CONN_MAX_AGE=0.",
            )
    elif host.startswith("db.") and host.endswith(".supabase.co"):
        return _result(
            "database",
            label,
            "warn",
            "Direct Supabase connection: needs IPv6 (or the IPv4 add-on) and one connection per instance.",
            "Use the Supavisor pooler URL (aws-0-<region>.pooler.supabase.com:6543) for serverless.",
        )
    sslmode = str((db.get("OPTIONS") or {}).get("sslmode", ""))
    if sslmode not in {"require", "verify-ca", "verify-full"}:
        return _result(
            "database", label, "warn", f"sslmode={sslmode or 'unset'}.", "Add ?sslmode=require or DB_SSL_REQUIRE=true."
        )
    return _result("database", label, "pass", f"Postgres at {host or '-'}:{port or '-'} (sslmode={sslmode}).")


def check_vercel_media(settings_obj):
    backend = _media_backend(settings_obj)
    if backend != S3_STORAGE_BACKEND:
        return _result(
            "media_storage",
            "Uploads in object storage",
            "fail",
            f"STORAGES['default'] is {backend or '-'}; the function filesystem is read-only and not shared.",
            "Set MEDIA_STORAGE=s3 with the Supabase Storage S3 credentials (S3_*).",
        )
    return _result("media_storage", "Uploads in object storage", "pass", "S3Storage.")


def check_cron_secret(settings_obj, env):
    secret = str(_setting(settings_obj, "CRON_SECRET", "") or _env(env, "CRON_SECRET"))
    if len(secret) < MIN_CRON_SECRET_LENGTH:
        return _result(
            "cron_secret",
            "CRON_SECRET",
            "fail",
            "CRON_SECRET is missing or shorter than 16 characters; /api/internal/cron stays disabled.",
            "Set CRON_SECRET to a random string (e.g. `openssl rand -hex 32`) in the Vercel project.",
        )
    return _result("cron_secret", "CRON_SECRET", "pass", "Set.")


def check_writable_paths(settings_obj):
    problems = []
    if _setting(settings_obj, "LOG_TO_FILE", False):
        problems.append("LOG_TO_FILE=True")
    if _setting(settings_obj, "SESSION_ENGINE", "") == "django.contrib.sessions.backends.file":
        problems.append("file-based sessions")
    if "filebased" in _default_cache(settings_obj).get("BACKEND", ""):
        problems.append("FileBasedCache")
    if problems:
        return _result(
            "writable_paths",
            "No runtime disk writes",
            "fail",
            "Writes to the read-only function filesystem: " + ", ".join(problems) + ".",
            "Log to the console (LOG_TO_FILE=False) and keep sessions/cache in the database or redis.",
        )
    return _result("writable_paths", "No runtime disk writes", "pass", "Logs, sessions and cache avoid the disk.")


def check_background_tasks(settings_obj):
    if _setting(settings_obj, "BACKGROUND_JOBS_ENABLED", False):
        return _result(
            "background_tasks", "Background tasks", "warn",
            "Requests use a durable DB outbox; Vercel web functions do not run the configured Beat and workers.",
            "Provision external worker, media-worker and one Beat with the same DB/storage/settings. See docs/04-deploy/background-jobs.md.",
        )
    if not _setting(settings_obj, "CELERY_TASK_ALWAYS_EAGER", False):
        return _result(
            "background_tasks",
            "Background tasks",
            "warn",
            "Celery tasks are queued, but there is no worker on Vercel.",
            "Set CELERY_TASK_ALWAYS_EAGER=True (tasks run inside the request) or run a worker elsewhere.",
        )
    return _result("background_tasks", "Background tasks", "pass", "Celery tasks run eagerly.")


# --------------------------------------------------------------------------------------------- #
#  VPS (also the API side of the split profile)
# --------------------------------------------------------------------------------------------- #


def check_vps_database(settings_obj):
    engine = _default_db(settings_obj).get("ENGINE", "")
    if "sqlite3" in engine:
        return _result(
            "database",
            "Database",
            "pass",
            "SQLite: fine for one small server; back up the database file and keep it on a persistent volume.",
        )
    return _result("database", "Database", "pass", engine or "-")


def check_vps_media(settings_obj):
    backend = _media_backend(settings_obj)
    if backend == S3_STORAGE_BACKEND:
        return _result("media_storage", "Media storage", "pass", "S3Storage.")
    media_root = str(_setting(settings_obj, "MEDIA_ROOT", "") or "")
    # POSIX-style roots count as absolute too (the settings may be checked on a Windows workstation).
    if not media_root or not (media_root.startswith(("/", "\\")) or os.path.isabs(media_root)):
        return _result(
            "media_storage",
            "Media storage",
            "fail",
            f"MEDIA_ROOT={media_root or '(empty)'} is not an absolute path.",
            "Set MEDIA_ROOT to a persistent directory (compose mounts /app/media) and serve it from nginx.",
        )
    return _result("media_storage", "Media storage", "pass", f"Local files in {media_root}.")


def check_static_root(settings_obj):
    if not _setting(settings_obj, "STATIC_ROOT", ""):
        return _result("static_files", "STATIC_ROOT", "fail", "STATIC_ROOT is not set.", "Set STATIC_ROOT.")
    return _result("static_files", "STATIC_ROOT", "pass", str(_setting(settings_obj, "STATIC_ROOT")))


def _gunicorn_workers(env):
    value = _env(env, "GUNICORN_WORKERS") or _env(env, "WEB_CONCURRENCY")
    try:
        return int(value) if value else DEFAULT_GUNICORN_WORKERS
    except ValueError:
        return DEFAULT_GUNICORN_WORKERS


# --------------------------------------------------------------------------------------------- #
#  Split: Next.js front on Vercel, Django API elsewhere (nextjs/README.md "Cross-Domain Authentication")
# --------------------------------------------------------------------------------------------- #


def check_cross_domain(settings_obj, env):
    label = "Cross-domain auth"
    allow_all = bool(_setting(settings_obj, "CORS_ALLOW_ALL_ORIGINS", False))
    credentials = bool(_setting(settings_obj, "CORS_ALLOW_CREDENTIALS", False))
    if allow_all and credentials:
        return _result(
            "cross_domain",
            label,
            "fail",
            "CORS_ALLOW_ALL_ORIGINS with CORS_ALLOW_CREDENTIALS lets any site use a visitor's cookies.",
            "List the front-end origin in CORS_ALLOWED_ORIGINS instead.",
        )
    mode = (_env(env, "SPLIT_AUTH_MODE") or "proxy").lower()
    if mode not in SPLIT_AUTH_MODES:
        return _result(
            "cross_domain", label, "fail", f"SPLIT_AUTH_MODE={mode!r}.", "Use SPLIT_AUTH_MODE=proxy or direct."
        )
    if mode == "proxy":
        return _result(
            "cross_domain",
            label,
            "pass",
            "Proxy (BFF) mode: the browser only talks to the front-end, which forwards /api/v1 server-side; "
            "no CORS needed. Front-end: G5_NEXT_RUNTIME=server, G5_API_INTERNAL_URL set, NEXT_PUBLIC_API_URL unset.",
        )

    origins = list(_setting(settings_obj, "CORS_ALLOWED_ORIGINS", []) or [])
    trusted = set(_setting(settings_obj, "CSRF_TRUSTED_ORIGINS", []) or [])
    problems = []
    if not origins:
        problems.append("CORS_ALLOWED_ORIGINS is empty")
    if any(not origin.startswith("https://") for origin in origins):
        problems.append("CORS_ALLOWED_ORIGINS has non-HTTPS origins")
    if not credentials:
        problems.append("CORS_ALLOW_CREDENTIALS is off")
    missing_trusted = [origin for origin in origins if origin not in trusted]
    if missing_trusted:
        problems.append("CSRF_TRUSTED_ORIGINS lacks " + ", ".join(missing_trusted))
    if problems:
        return _result(
            "cross_domain",
            label,
            "fail",
            "Direct mode: " + "; ".join(problems) + ".",
            "Set CORS_ALLOWED_ORIGINS=https://<front>, CORS_ALLOW_CREDENTIALS=True, CSRF_TRUSTED_ORIGINS=https://<front>.",
        )
    return _result(
        "cross_domain",
        label,
        "warn",
        "Direct mode configured, but the g5_refresh cookie is SameSite=Lax (gnu_jango/api/v1_auth.py), so sessions "
        "do not survive a reload across sites.",
        "Prefer proxy mode (SPLIT_AUTH_MODE=proxy) as nextjs/README.md recommends.",
    )


def check_secure_cookies(settings_obj):
    insecure = [
        name for name in ("SESSION_COOKIE_SECURE", "CSRF_COOKIE_SECURE") if not _setting(settings_obj, name, False)
    ]
    if insecure:
        return _result(
            "secure_cookies",
            "Secure cookies",
            "fail",
            ", ".join(insecure) + " off.",
            "Serve the API over HTTPS and set both to True.",
        )
    return _result("secure_cookies", "Secure cookies", "pass", "Session and CSRF cookies are Secure.")


# --------------------------------------------------------------------------------------------- #


def evaluate_deploy_profile(profile, *, settings_obj, env, cache_table_exists=None):
    profile = str(profile or "").strip().lower()
    if profile not in PROFILES:
        raise ValueError(f"Unknown deploy profile {profile!r}; expected one of {', '.join(PROFILES)}.")
    cache_table_exists = cache_table_exists or database_cache_table_exists

    checks = [check_debug(settings_obj), check_secret_key(settings_obj), check_allowed_hosts(settings_obj)]
    if profile == "vercel":
        checks += [
            check_vercel_database(settings_obj, env),
            check_vercel_media(settings_obj),
            check_cache(settings_obj, cache_table_exists=cache_table_exists),
            check_cron_secret(settings_obj, env),
            check_writable_paths(settings_obj),
            check_background_tasks(settings_obj),
        ]
    else:
        checks += [
            check_vps_database(settings_obj),
            check_vps_media(settings_obj),
            check_cache(
                settings_obj, cache_table_exists=cache_table_exists, allow_locmem_workers=_gunicorn_workers(env)
            ),
            check_static_root(settings_obj),
        ]
        if profile == "split":
            checks += [check_cross_domain(settings_obj, env), check_secure_cookies(settings_obj)]

    summary = {
        "passed": sum(1 for check in checks if check["status"] == "pass"),
        "warnings": sum(1 for check in checks if check["status"] == "warn"),
        "failed": sum(1 for check in checks if check["status"] == "fail"),
    }
    summary["ready"] = summary["failed"] == 0
    return {"profile": profile, "summary": summary, "checks": checks}
