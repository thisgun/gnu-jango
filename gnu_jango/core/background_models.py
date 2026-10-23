"""Durable outbox and dead letters. Broker messages contain only this row's UUID."""
import uuid

from django.db import models
from django.utils import timezone


class BackgroundJob(models.Model):
    STATUS = (("pending", "대기"), ("running", "실행 중"), ("succeeded", "완료"), ("dead", "최종 실패"))
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=32, db_index=True)
    operation = models.CharField(max_length=80, blank=True, default="")
    resource_key = models.CharField(max_length=64, blank=True, default="", db_index=True)
    queue = models.CharField(max_length=32)
    status = models.CharField(max_length=12, choices=STATUS, default="pending")
    payload = models.JSONField(default=dict)  # Private; never sent to Celery/Flower or exposed by admin.
    dedupe_key = models.CharField(max_length=160, unique=True, null=True, blank=True)
    active_key = models.CharField(max_length=160, unique=True, null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=5)
    available_at = models.DateTimeField(default=timezone.now)
    dispatched_at = models.DateTimeField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    claim_token = models.UUIDField(null=True, blank=True)
    error_code = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "gnu_jango_background_job"
        ordering = ["created_at"]
        verbose_name = "백그라운드 작업"
        verbose_name_plural = "백그라운드 작업 / 실패 큐"
        indexes = [
            models.Index(fields=["status", "available_at"], name="bg_status_available"),
            models.Index(fields=["status", "lease_until"], name="bg_status_lease"),
        ]

    def __str__(self):
        return f"{self.kind} {self.id} ({self.status})"
