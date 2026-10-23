"""Autodiscovered via core.tasks. Broker args and task results never contain private payloads."""
from celery import shared_task
from django.db import OperationalError, InterfaceError


@shared_task(name="core.dispatch_background_jobs", ignore_result=True,
             autoretry_for=(OperationalError, InterfaceError), retry_backoff=True, max_retries=5)
def dispatch_background_jobs():
    from .background import dispatch_due
    return dispatch_due()


@shared_task(bind=True, name="core.execute_background_job", ignore_result=True,
             acks_late=True, reject_on_worker_lost=True, max_retries=5)
def execute_background_job(self, job_id):
    from .background import execute_job
    result = execute_job(job_id)
    if result["status"] == "pending":
        raise self.retry(countdown=result["retry_in"], exc=RuntimeError("Background operation retry scheduled"))
    if result["status"] == "dead":
        raise RuntimeError("Background operation moved to the dead-letter queue")
    return result


@shared_task(name="core.enqueue_scheduled_job", ignore_result=True,
             autoretry_for=(OperationalError, InterfaceError), retry_backoff=True, max_retries=5)
def enqueue_scheduled_job(name):
    from .background import enqueue_scheduled
    return {"id": str(enqueue_scheduled(name).pk)}


@shared_task(name="core.purge_background_jobs", ignore_result=True)
def purge_background_jobs():
    from .background import enqueue
    return {"id": str(enqueue("scheduled", {"name": "purge_background_jobs"},
                              active_key="scheduled:purge_background_jobs").pk)}
