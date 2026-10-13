from .base import *
from .deploy import database_from_env, vercel_allowed_hosts
from django.core.exceptions import ImproperlyConfigured

ALLOWED_HOSTS = de_config("ALLOWED_HOSTS", default="", cast=csv_config)
# On Vercel (VERCEL=1) also accept the deployment, branch and production *.vercel.app hosts.
ALLOWED_HOSTS += [host for host in vercel_allowed_hosts(os.environ) if host not in ALLOWED_HOSTS]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS environment variable is required in production.")

# INSTALLED_APPS += [
#     'cloudinary_storage',
#     'cloudinary',
# ]

# Media: MEDIA_URL / STORAGES["default"] come from base.py (MEDIA_STORAGE=local|s3).
# Production never set MEDIA_ROOT, so FileSystemStorage wrote to the working directory; keep that default
# so existing installs still find their files, and set MEDIA_ROOT explicitly (docker-compose uses
# /app/media). `manage.py check_deploy_profile` fails while it is empty.
MEDIA_ROOT = de_config("MEDIA_ROOT", default="")
# DEFAULT_FILE_STORAGE = 'cloudinary_storage.storage.MediaCloudinaryStorage'

RECAPTCHA_PUBLIC_KEY = de_config("RECAPTCHA_PUBLIC_KEY", default="")
RECAPTCHA_PRIVATE_KEY = de_config("RECAPTCHA_PRIVATE_KEY", default="")

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
# Production runs behind one reverse proxy; raise it if there are more (e.g. a CDN plus nginx).
TRUSTED_PROXY_COUNT = de_config("TRUSTED_PROXY_COUNT", default=1, cast=int)
SECURE_SSL_REDIRECT = bool_config("SECURE_SSL_REDIRECT", default=True)
SESSION_COOKIE_SECURE = bool_config("SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE = bool_config("CSRF_COOKIE_SECURE", default=True)
SECURE_HSTS_SECONDS = de_config("SECURE_HSTS_SECONDS", default=31536000, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = bool_config("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True)
SECURE_HSTS_PRELOAD = bool_config("SECURE_HSTS_PRELOAD", default=False)

# Database
# https://docs.djangoproject.com/en/3.2/ref/settings/#databases

DATABASES = {
    "default": {
        "ENGINE": de_config("DB_ENGINE", default="django.db.backends.postgresql"),
        "NAME": de_config("DB_NAME", default=""),
        "USER": de_config("DB_USERNAME", default=""),
        "PASSWORD": de_config("DB_PASSWORD", default=""),
        "HOST": de_config("DB_HOSTNAME", default=""),
        "PORT": de_config("DB_PORT", default=5432, cast=int),
    }
}

# https://github.com/heroku/python-getting-started/blob/main/gettingstarted/settings.py

# Cloudinary configs
# CLOUDINARY_STORAGE = {
#     'CLOUD_NAME': config('CLOUDINARY_CLOUD_NAME'),
#     'API_KEY': config('CLOUDINARY_API_SECRET'),
#     'API_SECRET': config('CLOUDINARY_API_KEY')
# }

IS_HEROKU = "DYNO" in os.environ


def configure_heroku(settings_mapping):
	"""Apply the optional legacy Heroku settings integration with actionable setup guidance."""
	try:
		import django_heroku
	except ModuleNotFoundError as exc:
		if exc.name != "django_heroku":
			raise
		raise ImproperlyConfigured(
			"Heroku deployment detected (DYNO is set), but django-heroku is not installed. "
			"Install the optional Heroku dependency with `pip install django-heroku==0.3.1`."
		) from exc

	django_heroku.settings(settings_mapping)

MAX_CONN_AGE = 600

# DATABASE_URL wins over DB_*; resolved exactly like development.py (example/settings/deploy.py) but
# with persistent connections and SSL required for Postgres by default. Serverless + Supabase
# transaction pooler: DB_CONN_MAX_AGE=0 and DB_DISABLE_SERVER_SIDE_CURSORS=true. A local compose
# Postgres without TLS: DB_SSL_REQUIRE=false.
_database_from_url = database_from_env(DEPLOY_ENV, default_conn_max_age=MAX_CONN_AGE, default_ssl_require=True)
if _database_from_url:
    DATABASES["default"] = _database_from_url
        
if IS_HEROKU:
	configure_heroku(locals())

# Enable WhiteNoise's compression and caching of static assets on persistent hosts.
# Vercel serves collected assets from its static output, outside the Python function
# bundle. A manifest storage lookup there cannot inspect STATIC_ROOT at request time,
# so use plain /static/... URLs for the function to avoid failing admin page renders.
# STATICFILES_STORAGE was removed in Django 5.1; the optional Heroku integration may
# set it, so use STORAGES and apply this after that integration.
_staticfiles_backend = "gnu_jango.core.static_storage.LegacyTolerantManifestStorage"
if os.environ.get("VERCEL") == "1":
    _staticfiles_backend = "django.contrib.staticfiles.storage.StaticFilesStorage"

STORAGES = {
	**STORAGES,
	"staticfiles": {
		# Hashed + compressed on persistent hosts; plain paths on Vercel's static output.
		"BACKEND": _staticfiles_backend,
	},
}

DEBUG = bool_config("DEBUG", default=False)
