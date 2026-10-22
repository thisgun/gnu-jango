# Build stage: compilers are needed only if a dependency has no wheel; they stay out of the final image.
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

ARG INSTALL_REALTIME=0
COPY requirements.txt requirements-realtime.txt /tmp/
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r /tmp/requirements.txt \
    && if [ "$INSTALL_REALTIME" = "1" ]; then /opt/venv/bin/pip install -r /tmp/requirements-realtime.txt; fi


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=example.settings.production \
    ENVIRONMENT=Production \
    MEDIA_ROOT=/app/media

# Keep the PostgreSQL client library available to the runtime image.
# The app runs as an unprivileged user; it writes only to media/ and logs/.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin app

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY . .

# Static files are collected into the image (served by WhiteNoise), so containers start without it and
# every new image brings its own assets. The build needs no database or real secrets.
RUN SECRET_KEY=build-only-not-secret ALLOWED_HOSTS=localhost \
    EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend \
    python manage.py collectstatic --noinput

RUN mkdir -p /app/media /app/logs \
    && chown app:app /app/media /app/logs \
    && chmod +x /app/docker/entrypoint.sh

USER app

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["sh", "-c", "gunicorn example.wsgi:application --bind 0.0.0.0:8000 --workers ${GUNICORN_WORKERS:-3} --timeout ${GUNICORN_TIMEOUT:-60}"]
