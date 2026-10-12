from django.db import migrations, models


def invalidate_existing_tokens(apps, schema_editor):
    """Force one re-login after deployment so pre-version access JWTs cannot outlive logout."""
    Profile = apps.get_model("users", "Profile")
    User = Profile._meta.get_field("user").remote_field.model
    existing_user_ids = Profile.objects.values_list("user_id", flat=True)
    missing_user_ids = User.objects.exclude(pk__in=existing_user_ids).values_list("pk", flat=True)
    Profile.objects.bulk_create(
        [Profile(user_id=user_id, token_version=1) for user_id in missing_user_ids.iterator()],
        batch_size=500,
    )
    Profile.objects.update(token_version=1)


class Migration(migrations.Migration):

    dependencies = [
        ("users", "0013_profile_member_lifecycle"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="token_version",
            field=models.PositiveIntegerField(default=0, verbose_name="인증 토큰 버전"),
        ),
        migrations.RunPython(invalidate_existing_tokens, migrations.RunPython.noop),
    ]
