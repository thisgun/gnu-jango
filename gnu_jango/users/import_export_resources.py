"""Member CSV import/export for the admin.

Member import is a registration/update tool, not an account-security tool. It deliberately never
writes passwords, staff/superuser flags, points, or token versions. New members receive an unusable
password and must use the normal password-reset flow before they can sign in.
"""

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from import_export import fields

from gnu_jango.api.auth_sessions import revoke_member_tokens
from gnu_jango.core.import_export import SafeExportResource

from .models import Profile

User = get_user_model()


class UserResource(SafeExportResource):
    id = fields.Field(attribute="id", readonly=True)
    is_active = fields.Field(attribute="is_active", readonly=True)
    is_staff = fields.Field(attribute="is_staff", readonly=True)
    is_superuser = fields.Field(attribute="is_superuser", readonly=True)
    date_joined = fields.Field(attribute="date_joined", readonly=True)
    last_login = fields.Field(attribute="last_login", readonly=True)
    nickname = fields.Field(attribute="profile__nickname", readonly=True)
    real_name = fields.Field(attribute="profile__realname", readonly=True)
    phone = fields.Field(attribute="profile__user_hp", readonly=True)
    member_level = fields.Field(attribute="profile__user_level", readonly=True)
    point_balance = fields.Field(attribute="profile__user_point", readonly=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_active",
            "is_staff",
            "is_superuser",
            "date_joined",
            "last_login",
            "nickname",
            "real_name",
            "phone",
            "member_level",
            "point_balance",
        )
        export_order = fields
        import_id_fields = ("username",)
        skip_unchanged = True
        report_skipped = True
        clean_model_instances = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen_emails = set()

    def before_import_row(self, row, **kwargs):
        username = str(row.get("username") or "").strip()
        if not username:
            raise ValueError("username is required.")
        row["username"] = username
        existing = (
            User.objects.select_for_update()
            .filter(username=username)
            .only("pk", "email", "is_staff", "is_superuser")
            .first()
        )
        if existing and (existing.is_staff or existing.is_superuser):
            raise ValueError("Admin accounts cannot be changed by member CSV import.")
        email = str(row.get("email") or "").strip()
        if existing and not email:
            row["email"] = existing.email
        elif email:
            try:
                validate_email(email)
            except ValidationError as exc:
                raise ValueError(f"Invalid email address: {email}") from exc
            normalized = email.casefold()
            if normalized in self._seen_emails:
                raise ValueError(f"Duplicate email address in file: {email}")
            self._seen_emails.add(normalized)
            duplicates = User.objects.filter(email__iexact=email)
            if existing:
                duplicates = duplicates.exclude(pk=existing.pk)
            if duplicates.exists():
                raise ValueError(f"Email address is already used: {email}")
        row["_old_email"] = existing.email if existing else ""

    def validate_instance(self, instance, import_validation_errors=None, validate_unique=True):
        # full_clean() requires a non-empty password; new imported members get an unusable one.
        if instance.pk is None:
            instance.set_unusable_password()
        super().validate_instance(instance, import_validation_errors, validate_unique)

    def before_save_instance(self, instance, row, **kwargs):
        if instance.pk is None:
            instance.set_unusable_password()
            instance.is_staff = False
            instance.is_superuser = False

    def after_save_instance(self, instance, row, **kwargs):
        # An address change normally revokes existing JWTs through the admin form. Do the same
        # when the address came from a CSV import instead of leaving old sessions usable.
        old_email = row.get("_old_email") or ""
        if old_email and instance.email != old_email:
            revoke_member_tokens(instance)
        profile, _created = Profile.objects.get_or_create(user=instance)
        changed = []
        for column, field_name in (
            ("nickname", "nickname"),
            ("real_name", "realname"),
            ("phone", "user_hp"),
        ):
            value = str(row.get(column) or "").strip()
            if value and getattr(profile, field_name) != value:
                setattr(profile, field_name, value)
                changed.append(field_name)
        if changed:
            profile.save(update_fields=changed)
