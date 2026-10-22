"""Bounded administrator announcements, persisted before realtime hints are sent."""

import hashlib
import json
import secrets

from django import forms
from django.contrib import messages
from django.contrib.admin.models import ADDITION, LogEntry
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseNotAllowed, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import reverse

from gnu_jango.core.models import Notification, NotificationAnnouncement

from .delivery import queue_hints

MAX_RECIPIENTS = 500


class AnnouncementForm(forms.Form):
    send_token = forms.CharField(widget=forms.HiddenInput)
    title = forms.CharField(label="공지 제목", max_length=255)
    body = forms.CharField(label="공지 내용", max_length=2000, widget=forms.Textarea)
    href = forms.CharField(label="이동할 사이트 내부 경로", required=False, max_length=500, help_text="예: /bbs/notice/1")
    audience = forms.ChoiceField(label="수신 대상", choices=(("selected", "아이디 지정"), ("staff", "활성 스태프"), ("active", "활성 회원 전체")))
    usernames = forms.CharField(label="수신 아이디", required=False, max_length=5000, widget=forms.Textarea, help_text="아이디 지정 시 쉼표 또는 줄바꿈으로 구분하세요.")
    confirm = forms.BooleanField(label="선택한 대상의 알림함에 공지를 보냅니다.")

    def clean_href(self):
        value = self.cleaned_data["href"]
        if value and (not value.startswith("/") or value.startswith("//") or "\\" in value or any(ord(c) < 33 for c in value)):
            raise forms.ValidationError("현재 사이트의 /로 시작하는 경로를 입력하세요.")
        return value

    def clean(self):
        values = super().clean()
        users = get_user_model().objects.filter(is_active=True)
        audience = values.get("audience")
        if audience == "selected":
            names = set(values.get("usernames", "").replace("\n", ",").replace("\r", "").split(","))
            names = {name.strip() for name in names if name.strip()}
            if not names:
                raise forms.ValidationError("수신 아이디를 입력하세요.")
            users = users.filter(username__in=names)
            if users.count() != len(names):
                raise forms.ValidationError("존재하지 않거나 비활성 상태인 수신 아이디가 있습니다.")
        elif audience == "staff":
            users = users.filter(is_staff=True)
        elif audience != "active":
            return values
        ids = list(users.order_by("pk").values_list("pk", flat=True)[:MAX_RECIPIENTS + 1])
        if not ids:
            raise forms.ValidationError("수신 대상이 없습니다.")
        if len(ids) > MAX_RECIPIENTS:
            raise forms.ValidationError(f"한 번에 {MAX_RECIPIENTS}명까지 발송할 수 있습니다. 아이디를 지정해 나누어 보내세요.")
        values["recipient_ids"] = ids
        return values


def publish_announcement(actor, values, *, request_id):
    ids = values["recipient_ids"]
    digest = hashlib.sha256(json.dumps({
        "title": values["title"], "body": values["body"], "href": values["href"], "recipients": sorted(ids),
    }, sort_keys=True).encode()).hexdigest()
    with transaction.atomic():
        batch, created = NotificationAnnouncement.objects.get_or_create(
            request_id=request_id,
            defaults={"created_by": actor, "content_digest": digest, "recipient_count": len(ids)},
        )
        if not created:
            if batch.created_by_id != actor.pk or batch.content_digest != digest:
                raise forms.ValidationError("이미 처리한 발송 요청의 내용을 바꿀 수 없습니다. 새 발송 화면을 열어 주세요.")
            return batch.recipient_count
        Notification.objects.bulk_create([
            Notification(
                user_id=user_id, event_key=f"announcement:{request_id}:{user_id}",
                nt_type="announcement", nt_title=values["title"], nt_body=values["body"], nt_data={"href": values["href"]},
            )
            for user_id in ids
        ], batch_size=100)
        queue_hints(ids)
        batch.status = "sent"
        batch.save(update_fields=["status"])
        LogEntry.objects.log_actions(
            user_id=actor.pk, queryset=[batch], action_flag=ADDITION,
            change_message=f"Notification announcement sent to {len(ids)} active members.",
        )
    return len(ids)


def announcement_view(model_admin, request):
    if not model_admin.has_add_permission(request):
        raise PermissionDenied
    if request.method not in ("GET", "POST"):
        return HttpResponseNotAllowed(["GET", "POST"])
    form = AnnouncementForm(
        request.POST if request.method == "POST" else None,
        initial={"send_token": signing.dumps({"user_id": request.user.pk, "nonce": secrets.token_urlsafe(24)}, salt="notification-announce")},
    )
    if request.method == "POST" and form.is_valid():
        try:
            token = signing.loads(form.cleaned_data["send_token"], salt="notification-announce", max_age=3600)
            if token.get("user_id") != request.user.pk:
                raise signing.BadSignature
        except (signing.BadSignature, AttributeError):
            form.add_error(None, "발송 화면의 유효 시간이 지났습니다. 페이지를 다시 열어 주세요.")
        else:
            try:
                count = publish_announcement(request.user, form.cleaned_data, request_id=token["nonce"])
            except forms.ValidationError as exc:
                form.add_error(None, exc)
            else:
                model_admin.message_user(request, f"{count}명의 알림함에 공지를 보냈습니다.", level=messages.SUCCESS)
                return HttpResponseRedirect(reverse("admin:core_notification_changelist"))
    return TemplateResponse(request, "admin/core/notification_announcement.html", {
        **model_admin.admin_site.each_context(request), "opts": model_admin.model._meta,
        "title": "관리자 공지 알림 발송", "form": form, "max_recipients": MAX_RECIPIENTS,
    })
