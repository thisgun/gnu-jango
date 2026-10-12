FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=example.settings.production \
    ENVIRONMENT=Production

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/staticfiles /app/media /app/logs

# Static files are collected into the image (served by WhiteNoise), so containers start without it and
# every new image brings its own assets. The build needs no database or real secrets.
RUN SECRET_KEY=build-only-not-secret ALLOWED_HOSTS=localhost     EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend     python manage.py collectstatic --noinput

RUN chmod +x /app/docker/entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["sh", "-c", "gunicorn example.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3} --timeout ${GUNICORN_TIMEOUT:-60}"]
