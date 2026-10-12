"""Turn deployment environment variables into Django settings values.

Every function here is pure: it takes a mapping-like ``env`` (anything with ``.get(name, default)``)
and returns plain dicts/strings, so the settings modules stay declarative and the resolution can be
unit-tested without importing optional backends (django-storages, boto3, redis).

Profiles (see docs/04-deploy/deployment-profiles.md):
  * vps    -- local media, locmem/redis cache, Postgres or SQLite, system cron.
  * vercel -- Supabase Postgres via DATABASE_URL, MEDIA_STORAGE=s3, CACHE_URL=db:// or redis://.
  * split  -- the vps API behind a Next.js front-end on another domain.
"""

import re
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

FILESYSTEM_STORAGE_BACKEND = "django.core.files.storage.FileSystemStorage"
S3_STORAGE_BACKEND = "storages.backends.s3.S3Storage"

LOCMEM_CACHE_BACKEND = "django.core.cache.backends.locmem.LocMemCache"
DATABASE_CACHE_BACKEND = "django.core.cache.backends.db.DatabaseCache"
REDIS_CACHE_BACKEND = "django.core.cache.backends.redis.RedisCache"
DUMMY_CACHE_BACKEND = "django.core.cache.backends.dummy.DummyCache"
DEFAULT_CACHE_TABLE = "gnu_jango_cache"

S3_REQUIRED_VARIABLES = ("S3_BUCKET", "S3_REGION", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY")
POSTGRES_URL_SCHEMES = {"postgres", "postgresql", "pgsql", "postgis"}

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}
_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class ConfigEnv:
    """Expose python-decouple's ``config`` (environment first, then ``.env``) as a mapping-like env."""

    def __init__(self, getter):
        self._getter = getter

    def get(self, name, default=None):
        return self._getter(name, default=default)


def env_str(env, name, default=""):
    value = env.get(name, None)
    if value is None:
        return default
    return str(value).strip()


def env_bool(env, name, default=False):
    value = env_str(env, name).lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default


def env_int(env, name, default):
    value = env_str(env, name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer, got {value!r}.") from exc


# --------------------------------------------------------------------------------------------- #
#  Media storage
# --------------------------------------------------------------------------------------------- #


def media_storage_kind(env):
    kind = env_str(env, "MEDIA_STORAGE", "local").lower() or "local"
    if kind not in {"local", "s3"}:
        raise ImproperlyConfigured(f"MEDIA_STORAGE must be 'local' or 's3', got {kind!r}.")
    return kind


def _public_base(env):
    """Return (protocol, host-and-path) for public media URLs, or None for a private bucket."""
    public_base_url = env_str(env, "S3_PUBLIC_BASE_URL")
    if public_base_url:
        parts = urlsplit(public_base_url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ImproperlyConfigured("S3_PUBLIC_BASE_URL must be an absolute http(s) URL.")
        return f"{parts.scheme}:", (parts.netloc + parts.path).rstrip("/")
    custom_domain = env_str(env, "S3_CUSTOM_DOMAIN").strip("/")
    if custom_domain:
        return "https:", custom_domain
    return None


def media_storage_config(env):
    """Return the ``STORAGES["default"]`` entry selected by MEDIA_STORAGE (local by default)."""
    if media_storage_kind(env) == "local":
        return {"BACKEND": FILESYSTEM_STORAGE_BACKEND}

    missing = [name for name in S3_REQUIRED_VARIABLES if not env_str(env, name)]
    if missing:
        raise ImproperlyConfigured(
            "MEDIA_STORAGE=s3 needs these environment variables: " + ", ".join(missing) + "."
        )

    options = {
        "bucket_name": env_str(env, "S3_BUCKET"),
        "region_name": env_str(env, "S3_REGION"),
        "access_key": env_str(env, "S3_ACCESS_KEY_ID"),
        "secret_key": env_str(env, "S3_SECRET_ACCESS_KEY"),
        # Supabase Storage (and most S3-compatible services) expect path-style addressing and SigV4.
        "addressing_style": env_str(env, "S3_ADDRESSING_STYLE", "path") or "path",
        "signature_version": "s3v4",
        # No object ACLs: access is governed by the bucket policy (Supabase ignores ACLs anyway).
        "default_acl": None,
        # Keep FileSystemStorage semantics: never silently replace an existing upload.
        "file_overwrite": False,
        "querystring_auth": True,
        "querystring_expire": env_int(env, "S3_QUERYSTRING_EXPIRE", 3600),
    }
    endpoint_url = env_str(env, "S3_ENDPOINT_URL")
    if endpoint_url:
        options["endpoint_url"] = endpoint_url
    location = env_str(env, "S3_LOCATION").strip("/")
    if location:
        options["location"] = location
    public_base = _public_base(env)
    if public_base:
        protocol, domain = public_base
        options["url_protocol"] = protocol
        options["custom_domain"] = domain
        # Public bucket: plain URLs are cacheable and never expire.
        options["querystring_auth"] = False
    return {"BACKEND": S3_STORAGE_BACKEND, "OPTIONS": options}


def media_url_for(env, default="/media/"):
    """MEDIA_URL: the public bucket URL when one is configured, otherwise the local default."""
    if media_storage_kind(env) != "s3":
        return default
    public_base = _public_base(env)
    if not public_base:
        # Private bucket: django-storages signs every URL itself; MEDIA_URL is only a label.
        return default
    protocol, domain = public_base
    location = env_str(env, "S3_LOCATION").strip("/")
    return f"{protocol}//{domain}/" + (f"{location}/" if location else "")


# --------------------------------------------------------------------------------------------- #
#  Cache
# --------------------------------------------------------------------------------------------- #


def cache_config(env):
    """Return CACHES for CACHE_URL. Empty or ``locmem://`` keeps Django's per-process default."""
    url = env_str(env, "CACHE_URL")
    scheme, _, rest = url.partition("://")
    scheme = scheme.lower()

    if not url or scheme == "locmem":
        default = {"BACKEND": LOCMEM_CACHE_BACKEND}
        if rest.strip("/"):
            default["LOCATION"] = rest.strip("/")
    elif scheme == "db":
        table = rest.strip("/") or DEFAULT_CACHE_TABLE
        if not _TABLE_NAME.match(table):
            raise ImproperlyConfigured(f"CACHE_URL db:// table name {table!r} is not a valid identifier.")
        default = {"BACKEND": DATABASE_CACHE_BACKEND, "LOCATION": table}
    elif scheme in {"redis", "rediss", "unix"}:
        default = {"BACKEND": REDIS_CACHE_BACKEND, "LOCATION": url}
    elif scheme == "dummy":
        default = {"BACKEND": DUMMY_CACHE_BACKEND}
    else:
        raise ImproperlyConfigured(
            "CACHE_URL must be empty, locmem://, db://[table], redis://..., rediss://... or dummy://; "
            f"got scheme {scheme!r}."
        )

    key_prefix = env_str(env, "CACHE_KEY_PREFIX")
    if key_prefix:
        default["KEY_PREFIX"] = key_prefix
    return {"default": default}


# --------------------------------------------------------------------------------------------- #
#  Database
# --------------------------------------------------------------------------------------------- #


def database_from_url(url, *, conn_max_age=0, ssl_require=False, disable_server_side_cursors=False):
    import dj_database_url

    is_postgres = urlsplit(url).scheme.lower() in POSTGRES_URL_SCHEMES
    return dj_database_url.parse(
        url,
        conn_max_age=conn_max_age,
        conn_health_checks=conn_max_age > 0,
        # sslmode is a libpq option; adding it to SQLite/MySQL would break their connections.
        ssl_require=ssl_require and is_postgres,
        disable_server_side_cursors=disable_server_side_cursors and is_postgres,
    )


def database_from_env(env, *, default_conn_max_age, default_ssl_require):
    """DATABASES["default"] from DATABASE_URL, or None when it is not set.

    DB_CONN_MAX_AGE, DB_SSL_REQUIRE and DB_DISABLE_SERVER_SIDE_CURSORS override the per-settings
    defaults. Behind Supabase's transaction pooler (port 6543, PgBouncer transaction mode) use
    DB_CONN_MAX_AGE=0 and DB_DISABLE_SERVER_SIDE_CURSORS=true.
    """
    url = env_str(env, "DATABASE_URL")
    if not url:
        return None
    return database_from_url(
        url,
        conn_max_age=env_int(env, "DB_CONN_MAX_AGE", default_conn_max_age),
        ssl_require=env_bool(env, "DB_SSL_REQUIRE", default_ssl_require),
        disable_server_side_cursors=env_bool(env, "DB_DISABLE_SERVER_SIDE_CURSORS", False),
    )


# --------------------------------------------------------------------------------------------- #
#  Secret key
# --------------------------------------------------------------------------------------------- #

DEVELOPMENT_SECRET_KEY = "unsafe-development-secret-key-change-me"
# Keys published in this repository start with one of these: the development fallback ("unsafe-") and
# the deploy/env/*.env.example placeholder ("<generate: ...>"). Anyone could forge sessions and JWTs
# signed with them.
PLACEHOLDER_SECRET_KEY_PREFIXES = ("unsafe-", "<")


def secret_key_for(env, *, is_production):
    """SECRET_KEY from the environment; production refuses a missing key or a published placeholder."""
    # The value is returned as given (not stripped) so an existing deployment keeps its signing key.
    value = env.get("SECRET_KEY", None) or ""
    if not is_production:
        return value or DEVELOPMENT_SECRET_KEY
    if not value.strip():
        raise ImproperlyConfigured("SECRET_KEY environment variable is required in production.")
    if value.strip().startswith(PLACEHOLDER_SECRET_KEY_PREFIXES):
        raise ImproperlyConfigured(
            "SECRET_KEY is a placeholder published in this repository; generate a real one with "
            "`python -c \"from django.core.management.utils import get_random_secret_key as g; print(g())\"`."
        )
    return value


# --------------------------------------------------------------------------------------------- #
#  Hosts
# --------------------------------------------------------------------------------------------- #


def vercel_allowed_hosts(env):
    """Hosts Vercel assigns to a deployment (only when running on Vercel, which sets VERCEL=1)."""
    if env_str(env, "VERCEL") != "1":
        return []
    hosts = []
    for name in ("VERCEL_URL", "VERCEL_BRANCH_URL", "VERCEL_PROJECT_PRODUCTION_URL"):
        host = env_str(env, name)
        if host and host not in hosts:
            hosts.append(host)
    return hosts
