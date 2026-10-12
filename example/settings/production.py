from .base import *
import dj_database_url

ALLOWED_HOSTS = de_config("ALLOWED_HOSTS", default="", cast=csv_config)
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS environment variable is required in production.")

# INSTALLED_APPS += [
#     'cloudinary_storage',
#     'cloudinary',
# ]

# Media
MEDIA_URL = '/media/'
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

MAX_CONN_AGE = 600

if "DATABASE_URL" in os.environ:
    # Configure Django for DATABASE_URL environment variable.
    DATABASES["default"] = dj_database_url.config(
        conn_max_age=MAX_CONN_AGE, ssl_require=True)

    # Enable test database if found in CI environment.
    if "CI" in os.environ:
        DATABASES["default"]["TEST"] = DATABASES["default"]
        
if IS_HEROKU:
	import django_heroku

	#Heroku 환경 추가
	# 맨 마지막줄 추가
	django_heroku.settings(locals())

# Enable WhiteNoise's compression and caching of static assets. STATICFILES_STORAGE
# was removed in Django 5.1, so this has to be set through STORAGES. django_heroku
# still writes the obsolete setting, which Django ignores, so apply this after it.
STORAGES = {
	**STORAGES,
	"staticfiles": {
		"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
	},
}

DEBUG = bool_config("DEBUG", default=False)
