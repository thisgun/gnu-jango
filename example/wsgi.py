"""
WSGI config for gnu_jango project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.1/howto/deployment/wsgi/
"""

import os, sys

from django.core.wsgi import get_wsgi_application

path = os.path.abspath(__file__+'/../..')
if path not in sys.path:
    sys.path.append(path)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'example.settings')

application = get_wsgi_application()

# Vercel (VERCEL=1) passes PATH_INFO still percent-encoded, which broke every Korean board URL.
# Other servers (gunicorn, runserver) already decode it, so the wrapper is applied only there.
if os.environ.get('VERCEL') == '1':
    from gnu_jango.core.wsgi_path import decode_percent_encoded_path_info

    application = decode_percent_encoded_path_info(application)