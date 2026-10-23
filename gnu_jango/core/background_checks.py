from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.compatibility)
def background_configuration(app_configs, **kwargs):
    if not getattr(settings, "BACKGROUND_JOBS_ENABLED", False):
        return []
    errors = []
    if settings.CELERY_TASK_ALWAYS_EAGER:
        errors.append(Error("Background jobs require CELERY_TASK_ALWAYS_EAGER=False.", id="core.E030"))
    hard = settings.CELERY_TASK_TIME_LIMIT
    soft = settings.CELERY_TASK_SOFT_TIME_LIMIT
    if not 0 < soft < hard < settings.BACKGROUND_JOB_LEASE:
        errors.append(Error("Require soft timeout < hard timeout < BACKGROUND_JOB_LEASE.", id="core.E031"))
    delivery = settings.MAILERS.get("delivery", {}).get("BACKEND", "")
    if not delivery or delivery == "gnu_jango.core.queued_mail.EmailBackend":
        errors.append(Error("Configure a real MAILERS['delivery'] backend; recursive queue delivery is forbidden.", id="core.E032"))
    if not str(settings.CELERY_BROKER_URL).startswith(("redis://", "rediss://", "amqp://", "amqps://")):
        errors.append(Error("Configure a shared Redis or AMQP broker for background jobs.", id="core.E033"))
    return errors
