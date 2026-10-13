#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'example.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    # Vercel discovers Django settings by invoking manage.py with no command and
    # serializing the uppercase settings before importing the WSGI application.
    # Initialize the app registry first so settings that contain gettext_lazy
    # values (for example, Unfold's admin menu) can be serialized safely.
    if os.environ.get("VERCEL") == "1" and len(sys.argv) == 1:
        import django

        django.setup()

    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
