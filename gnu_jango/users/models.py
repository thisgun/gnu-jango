import uuid
import os
import warnings

from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify as _slugify


from django.contrib.auth import get_user_model

from gnu_jango.bbs.models import Board, Post
from gnu_jango.utils import lib

user_model_name = get_user_model()

# https://stackoverflow.com/questions/5773970/django-auth-user-with-unique-email
# 이메일 필드를 unique 속성으로 수정합니다.

# user_model_name = get_user_model_name()

# Create your models here.

# https://github.com/dev-yakuza/django_custom_user_model
# https://docs.djangoproject.com/en/dev/topics/auth/customizing/#a-full-example
# https://dev-yakuza.posstree.com/ko/django/custom-user-model/


# https://programmers-sosin.tistory.com/41
# class User(AbstractUser):
#     nickname = models.CharField(max_length=100, unique=True, null=True, blank=True)

#     def __str__(self):
#         return self.email

# https://ssungkang.tistory.com/entry/Django-OneToOne-%EB%B0%A9%EB%B2%95%EC%9C%BC%EB%A1%9C-User-Model-%ED%99%95%EC%9E%A5
# https://yonghyunlee.gitlab.io/python/user-extend/


def get_nickname_default():
    # nickname 필드의 default 값
    return uuid.uuid4().hex


def avatar_upload_to(instance, filename):

    filename, ext = os.path.splitext(filename)
    return os.path.join(
        "user_image",
        "a_{uuid}_{filename}{ext}".format(
            uuid=uuid.uuid4().hex, filename=_slugify(filename), ext=ext
        ),
    )


def icon_upload_to(instance, filename):

    filename, ext = os.path.splitext(filename)
    return os.path.join(
        "user_icon",
        "a_{uuid}_{filename}{ext}".format(
            uuid=uuid.uuid4().hex, filename=_slugify(filename), ext=ext
        ),
    )


class Profile(models.Model):
    user = models.OneToOneField(
        user_model_name,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="profile",
        verbose_name=_("user"),
    )
    nickname = models.CharField(
        _("닉네임"), max_length=100, unique=True, default=get_nickname_default, blank=True
    )
    nickname_date = models.DateTimeField(_("닉네임변경일"), null=True, blank=True)
    realname = models.CharField(
        help_text="user.first_name+' '+user.last_name",
        verbose_name="Full name",
        max_length=256,
        null=True,
        blank=True,
    )

    avatar = models.ImageField(
        _("회원이미지"), blank=True, upload_to=avatar_upload_to, help_text=_("회원이미지")
    )
    icon = models.ImageField(
        _("회원아이콘"), blank=True, upload_to=icon_upload_to, help_text=_("회원아이콘")
    )

    user_homepage = models.CharField(_("홈페이지주소"), max_length=255, null=True, blank=True)
    user_hp = models.CharField(_("연락처"), max_length=100, null=True, blank=True)
    user_level = models.PositiveSmallIntegerField(
        _("원글 수정 불가"), default=0, choices=lib.get_levels_choices()
    )
    user_zip = models.CharField(_("우편주소"), max_length=10, null=True, blank=True)
    user_addr1 = models.CharField(_("집주소1"), max_length=255, null=True, blank=True)
    user_addr2 = models.CharField(_("집주소2"), max_length=255, null=True, blank=True)
    user_addr_jibeon = models.CharField(
        _("집주소2"), max_length=255, null=True, blank=True
    )
    user_point = models.IntegerField(_("유저포인트"), default=0)

    # g5_member.mb_leave_date: the day the member left (bbs/member_leave.php).
    leave_date = models.DateField(_("탈퇴일"), null=True, blank=True)
    # Incremented (auth_sessions.bump_token_version) when the password or e-mail changes, the member
    # leaves or is blocked, so already-issued access and refresh JWTs stop working immediately.
    token_version = models.PositiveIntegerField(_("인증 토큰 버전"), default=0)
    # g5_member.mb_email_certify: when the e-mail address was certified; empty means not certified.
    # A profile made anywhere (admin, shell, a lazily created profile) counts as certified, as the
    # admin's member form does; self-registration clears it when cf_use_email_certify is on.
    email_certify = models.DateTimeField(_("메일인증일시"), null=True, blank=True, default=timezone.now)
    # g5_member.mb_email_certify2: the one-time token of the certify link ("random.issue_timestamp").
    email_certify_token = models.CharField(_("메일인증 토큰"), max_length=255, blank=True, default="")
    # g5_member.mb_open / mb_open_date: whether other members may see the profile, and when it changed.
    open_profile = models.BooleanField(_("정보공개"), default=True)
    open_profile_date = models.DateTimeField(_("정보공개 변경일"), null=True, blank=True)

    __original_avatar = None
    __original_icon = None

    def __str__(self):
        return "{0}".format(self.user.email)

    # https://stackoverflow.com/questions/36719566/identify-the-changed-fields-in-django-post-save-signal
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__original_avatar = self.avatar
        self.__original_icon = self.icon

    def save(self, force_insert=False, force_update=False, *args, **kwargs):
        if self.__original_avatar and (self.avatar != self.__original_avatar):
            try:
                self.__original_avatar.storage.delete(self.__original_avatar.name)
            except IOError:
                # failure to delete the old avatar shouldn't prevent us from continuing
                warnings.warn(
                    "Failed to delete old avatar file: %s" % self.__original_avatar.name
                )

        if self.__original_icon and (self.icon != self.__original_icon):
            try:
                self.__original_icon.storage.delete(self.__original_icon.name)
            except IOError:
                warnings.warn(
                    "Failed to delete old icon file: %s" % self.__original_icon.name
                )

        if not self._state.adding and not force_insert and kwargs.get("update_fields") is None:
            # token_version only moves through bump_token_version (a database-side increment). A full
            # save of a Profile loaded before a bump must not write the old version back and so bring
            # revoked tokens to life again; the column is written on insert or when named explicitly.
            kwargs["update_fields"] = [
                field.name
                for field in self._meta.concrete_fields
                if not field.primary_key and field.name != "token_version"
            ]
        super().save(force_insert=force_insert, force_update=force_update, *args, **kwargs)
        self.__original_avatar = self.avatar
        self.__original_icon = self.icon

    class Meta:
        verbose_name = _("프로필")
        verbose_name_plural = _("프로필")

    #     db_table = 'user_profile'


@receiver(post_save, sender=user_model_name)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(
            user=instance,
        )


@receiver(post_save, sender=user_model_name)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()


# https://github.com/Beomi/TIL/blob/master/2016/09/20160928_Gnuboard_to_Django_Series_01.md

# @receiver(post_save, sender=user_model_name)
# def save_user_profile(sender, instance, **kwargs):
#     instance.profile.save()

# class Cert_history(models.Model):
#     user = models.ForeignKey(user_model_name, on_delete=models.CASCADE, related_name='cert_history')
#     cr_company = models.CharField(_(""), max_length=100, unique=True, blank=True)

# 회원 포인트
class User_Point(models.Model):
    user = models.ForeignKey(
        user_model_name,
        on_delete=models.SET_NULL,
        related_name="user_point",
        blank=True,
        null=True,
    )
    po_datetime = models.DateTimeField(_("지급일시"))
    po_content = models.CharField(_("포인트내역"), max_length=255, null=True, blank=True)
    po_point = models.IntegerField(_("지급포인트"), default=0)
    po_use_point = models.IntegerField(_("사용포인트"), default=0)
    po_expired = models.PositiveSmallIntegerField(_("포인트만료"), default=0)
    po_expire_date = models.DateTimeField(_("포인트 만료일"), null=True, blank=True)
    po_mb_point = models.IntegerField(_("지급당시 회원포인트"), default=0)
    po_rel_table = models.CharField(_("관련 테이블"), max_length=20, null=True, blank=True)
    po_rel_id = models.BigIntegerField(_("관련 아이디"), default=0, null=True, blank=True)
    po_rel_action = models.CharField(
        _("관련 작업"), max_length=255, null=True, blank=True, default=""
    )

    class Meta:
        verbose_name = _("회원포인트")
        verbose_name_plural = _("회원포인트")
        indexes = [
            models.Index(
                fields=["id", "po_rel_table", "po_rel_id", "po_rel_action"],
                name="index1",
            ),
            models.Index(fields=["po_expire_date"], name="index2"),
        ]


# 회원 쪽지
class User_Memo(models.Model):
    me_recv_user_id = models.IntegerField(
        _("수신 회원번호"), default=0, null=True, blank=True
    )
    user = models.ForeignKey(
        user_model_name, on_delete=models.CASCADE, related_name="user_memo"
    )
    me_send_datetime = models.DateTimeField(_("쪽지 발신일시"), null=True, blank=True)
    me_read_datetime = models.DateTimeField(_("쪽지 수신일시"), null=True, blank=True)
    me_memo = models.TextField(_("쪽지내용"), null=True, blank=True, default="")
    me_send_id = models.IntegerField(_("보낸쪽지 번호"), default=0, null=True, blank=True)
    me_type = models.CharField(
        _("수신발신 구분"),
        choices=[("send", "send"), ("recv", "recv")],
        default="recv",
        max_length=4,
    )
    me_send_ip = models.CharField(
        _("글쓰기옵션"), null=True, blank=True, default="", max_length=100
    )

    class Meta:
        verbose_name = _("회원쪽지")
        verbose_name_plural = _("회원쪽지")
        indexes = [
            models.Index(fields=["me_recv_user_id"], name="me_recv_user_id"),
        ]


# 회원 스크랩
class User_Scrap(models.Model):
    user = models.ForeignKey(
        user_model_name, on_delete=models.CASCADE, related_name="user_scrap"
    )
    board = models.ForeignKey(Board, on_delete=models.CASCADE, verbose_name=_("게시판"))
    post = models.ForeignKey(Post, on_delete=models.CASCADE, verbose_name=_("게시글"))
    ms_datetime = models.DateTimeField(_("포인트 만료일"), null=True, blank=True)

    class Meta:
        verbose_name = _("회원스크랩")
        verbose_name_plural = _("회원스크랩")
        # indexes = [
        #     models.Index(fields=['user_id'], name='user_id'),
        # ]
