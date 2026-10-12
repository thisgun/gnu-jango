from .base import *
from .deploy import database_from_env

DATABASE_URL = de_config("DATABASE_URL", default="")
DB_ENGINE = de_config("DB_ENGINE", default="")

# DATABASE_URL wins over DB_ENGINE/DB_*; both settings modules resolve it the same way
# (example/settings/deploy.py), only the defaults differ: no persistent connections and no
# forced SSL here. DB_CONN_MAX_AGE / DB_SSL_REQUIRE / DB_DISABLE_SERVER_SIDE_CURSORS override them.
if DATABASE_URL:
    DATABASES = {
        "default": database_from_env(DEPLOY_ENV, default_conn_max_age=0, default_ssl_require=False),
    }
elif DB_ENGINE:
    DATABASES = {
        "default": {
            "ENGINE": DB_ENGINE,
            "NAME": de_config("DB_NAME", default=""),
            "USER": de_config("DB_USERNAME", default=""),
            "PASSWORD": de_config("DB_PASSWORD", default=""),
            "HOST": de_config("DB_HOSTNAME", default=""),
            "PORT": de_config("DB_PORT", default=5432, cast=int),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

DEBUG = True
ALLOWED_HOSTS = de_config(
    "ALLOWED_HOSTS",
    default="localhost, 127.0.0.1",
    cast=csv_config,
)

# MEDIA_URL / MEDIA_ROOT come from base.py (MEDIA_ROOT env, MEDIA_STORAGE switch).

DEFAULT_DEVELOPMENT_CORS_ALLOWED_ORIGINS = (
    "http://localhost:3000,"
    "http://127.0.0.1:3000,"
    "http://127.0.0.1:8000,"
    "http://localhost:5173,"
    "http://127.0.0.1:5173"
)
CORS_ALLOW_ALL_ORIGINS = bool_config(
    "CORS_ALLOW_ALL_ORIGINS",
    default=bool_config("CORS_ORIGIN_ALLOW_ALL", default=False),
)
CORS_ORIGIN_ALLOW_ALL = CORS_ALLOW_ALL_ORIGINS
CORS_ALLOWED_ORIGINS = de_config(
    "CORS_ALLOWED_ORIGINS",
    default=de_config(
        "CORS_ORIGIN_WHITELIST",
        default=DEFAULT_DEVELOPMENT_CORS_ALLOWED_ORIGINS,
    ),
    cast=csv_config,
)
if CORS_ALLOWED_ORIGINS:
    CORS_ALLOW_ALL_ORIGINS = False
CORS_ORIGIN_ALLOW_ALL = CORS_ALLOW_ALL_ORIGINS
CORS_ORIGIN_WHITELIST = CORS_ALLOWED_ORIGINS
CORS_ALLOW_CREDENTIALS = bool_config(
    "CORS_ALLOW_CREDENTIALS",
    default=not CORS_ALLOW_ALL_ORIGINS,
)
if CORS_ALLOW_ALL_ORIGINS and CORS_ALLOW_CREDENTIALS:
    CORS_ALLOW_CREDENTIALS = False

INSTALLED_APPS += ["debug_toolbar"]
MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]

ENABLE_DEBUG_TOOLBAR = bool_config("ENABLE_DEBUG_TOOLBAR", default=False)

NEXTJS25_DEBUG_TOOLBAR_BLOCKED_PATHS = {
    "/",
    "/icon-192.png",
    "/icon-512.png",
    "/manifest.json",
    "/manifest.webmanifest",
    "/og-default.png",
    "/robots.txt",
    "/sitemap-posts.xml",
    "/sitemap.xml",
    "/sw.js",
}

NEXTJS25_DEBUG_TOOLBAR_BLOCKED_PREFIXES = (
    "/_next/",
    "/api/",
    "/data/",
    "/nextjs25/",
    "/login",
    "/register",
    "/forgot-password",
    "/email-certify",
    "/boards",
    "/notice",
    "/free",
    "/qa",
    "/cm_free",
    "/n_gallery",
    "/content/",
    "/members/",
    "/mypage",
    "/shop",
    "/faq",
    "/polls",
    "/recent",
    "/search",
    "/baby",
    "/offline",
)


def show_debug_toolbar(request):
    path = getattr(request, "path", "") or ""
    if not ENABLE_DEBUG_TOOLBAR:
        return False
    if path.startswith("/admin/") or path.startswith("/__debug__/"):
        return False
    if path in NEXTJS25_DEBUG_TOOLBAR_BLOCKED_PATHS:
        return False
    if any(path.startswith(prefix) for prefix in NEXTJS25_DEBUG_TOOLBAR_BLOCKED_PREFIXES):
        return False
    return DEBUG and request.META.get("REMOTE_ADDR") in INTERNAL_IPS


DEBUG_TOOLBAR_CONFIG = {
    "SHOW_TOOLBAR_CALLBACK": "example.settings.development.show_debug_toolbar",
    # Allow `manage.py test` to run under development settings; the toolbar
    # otherwise raises debug_toolbar.E001 when DEBUG is forced off for tests.
    "IS_RUNNING_TESTS": False,
}

SILENCED_SYSTEM_CHECKS = ["captcha.recaptcha_test_key_error"]

LOGGING["loggers"]["django.db.backends"] = {
    "handlers": ["console"],
    "level": "INFO",
    "propagate": False,
}
