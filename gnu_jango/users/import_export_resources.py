"""Member CSV import/export for the admin.

Member import is a registration/update tool, not an account-security tool. It deliberately never
writes passwords, staff/superuser flags, points, or token versions. New members receive an unusable
password and must use the normal password-reset flow before they can sign in.
"""

from import_export import fields, resources

from django.contrib.auth import get_user_model

from gnu_jango.api.auth_sessions import revoke_member_tokens

from .models import Profile

User = get_user_model()


class UserResource(resources.ModelResource):
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

    def before_import_row(self, row, **kwargs):
        username = str(row.get("username") or "").strip()
        if not username:
            raise ValueError("username is required.")
        row["username"] = username
        existing = User.objects.filter(username=username).only("email", "is_staff", "is_superuser").first()
        if existing and (existing.is_staff or existing.is_superuser):
            raise ValueError("Admin accounts cannot be changed by member CSV import.")
        row["_old_email"] = existing.email if existing else ""

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
