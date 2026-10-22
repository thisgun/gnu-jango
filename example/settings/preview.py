"""Disposable Vercel previews: separate DB role/schema and no external integrations."""
# ruff: noqa: F403, F405
import re

from django.core.exceptions import ImproperlyConfigured

from .base import *
from .deploy import database_from_env, secret_key_for, vercel_allowed_hosts

DEBUG = False
# Preview must not subscribe to production channels or reuse its ticket cache.
NOTIFICATION_WS_ENABLED = False
CHANNEL_LAYERS = {}
RECAPTCHA_PUBLIC_KEY = RECAPTCHA_PRIVATE_KEY = ""
SECRET_KEY = secret_key_for(DEPLOY_ENV, is_production=True)
ALLOWED_HOSTS = vercel_allowed_hosts(os.environ)
ALLOWED_HOSTS += de_config("ALLOWED_HOSTS", default="", cast=csv_config)
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("Preview requires explicit deployment hosts.")
PREVIEW_DB_SCHEMA = de_config("PREVIEW_DB_SCHEMA", default="")
PREVIEW_DB_ROLE = de_config("PREVIEW_DB_ROLE", default="")
if not all(re.fullmatch(r"g5_preview[a-z0-9_]*", name) for name in (PREVIEW_DB_SCHEMA, PREVIEW_DB_ROLE)):
    raise ImproperlyConfigured("Preview requires dedicated g5_preview* schema and role.")
_db = database_from_env(DEPLOY_ENV, default_conn_max_age=0, default_ssl_require=True)
if not _db or _db["ENGINE"] != "django.db.backends.postgresql":
    raise ImproperlyConfigured("Preview requires its isolated PostgreSQL database URL.")
if _db["USER"].split(".")[0] != PREVIEW_DB_ROLE:
    raise ImproperlyConfigured("Preview database URL must use the dedicated role.")
_db["ENGINE"] = "example.preview_db"
_db["DISABLE_SERVER_SIDE_CURSORS"] = True
DATABASES = {"default": _db}
CACHES = {"default": {"BACKEND": "django.core.cache.backends.db.DatabaseCache", "LOCATION": "gnu_jango_cache"}}
MEDIA_ROOT = "/tmp/gnu-jango-preview-media"
MEDIA_URL = "/media/"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
MAILERS = {"default": {"BACKEND": "django.core.mail.backends.locmem.EmailBackend"}}
CRON_SECRET = ""
SHOP_TOSS_CLIENT_KEY = SHOP_TOSS_SECRET_KEY = ""
SHOP_PAYMENT_CALLBACK_SECRET = SHOP_PAYMENT_CALLBACK_SIGNATURE_SECRET = ""
SHOP_PAYMENT_ADAPTER_BASE_URL = SHOP_PAYMENT_ADAPTER_SECRET = ""
SHOP_PAYMENT_PROVIDER = ""
SHOP_TOSS_VBANK_ENABLED = False
G5_SMS_PROVIDER = "disabled"
SOCIAL_NAVER_CLIENT_ID = SOCIAL_NAVER_CLIENT_SECRET = ""
SOCIAL_KAKAO_REST_KEY = SOCIAL_KAKAO_CLIENT_SECRET = ""
SOCIAL_GOOGLE_CLIENT_ID = SOCIAL_GOOGLE_CLIENT_SECRET = ""
G5_DOCS_LLM_BASE_URL = ""
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = True
SECURE_SSL_REDIRECT = True
MIDDLEWARE = ["gnu_jango.core.preview.PreviewSafetyMiddleware", *MIDDLEWARE]
