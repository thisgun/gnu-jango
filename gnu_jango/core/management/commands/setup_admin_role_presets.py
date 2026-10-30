from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand


ROLE_PRESETS = {
    "쇼핑몰 운영자": {
        "apps": ("shop",),
        "extra_models": (("users", "profile"), ("auth", "user"), ("core", "notification")),
        # "export" only matches shop.export_shoporder (order CSV/XLSX export in the admin).
        "actions": ("view", "add", "change", "export"),
    },
    "정산 담당자": {
        "models": (
            ("shop", "shoporder"),
            ("shop", "shoporderitem"),
            ("shop", "shoporderdata"),
            ("shop", "shoppersonalpay"),
            ("core", "visitlog"),
            ("core", "mailsendlog"),
            ("core", "mailcampaign"),
        ),
        "actions": ("view", "change", "export"),
    },
    "커뮤니티 운영자": {
        "apps": ("bbs",),
        "extra_models": (
            ("core", "contentpage"),
            ("core", "faqmaster"),
            ("core", "faqitem"),
            ("core", "poll"),
            ("core", "pollchoice"),
            ("core", "pollcomment"),
            ("core", "notification"),
            ("users", "user_memo"),
        ),
        "actions": ("view", "add", "change", "delete"),
    },
    "고객지원": {
        "models": (
            ("auth", "user"),
            ("users", "profile"),
            ("users", "user_point"),
            ("users", "user_memo"),
            ("shop", "shoporder"),
            ("shop", "shoporderitem"),
            ("shop", "shoppersonalpay"),
            ("shop", "generalinquiry"),
            # customer return / exchange requests: approving, rejecting and completing them (completing
            # also needs shop.change_shoporder, which this role has for the order screen already)
            ("shop", "shopreturnrequest"),
            ("shop", "shopreturnrequestline"),
            ("core", "notification"),
            ("core", "mailcampaign"),
            ("core", "mailsendlog"),
            ("core", "visitlog"),
            ("core", "searchkeyword"),
        ),
        # No "export": support staff look up single orders but do not bulk-download customer data.
        "actions": ("view", "change"),
    },
}


class Command(BaseCommand):
    help = "Create Gnuboard-style admin role groups with practical permission presets."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Show role permissions without applying them.")

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        for role_name, preset in ROLE_PRESETS.items():
            permissions = self.permissions_for_preset(preset)
            if dry_run:
                self.stdout.write(f"{role_name}: {len(permissions)} permissions")
                continue
            group, created = Group.objects.get_or_create(name=role_name)
            group.permissions.set(permissions)
            self.stdout.write(
                self.style.SUCCESS(
                    f"{'Created' if created else 'Updated'} {role_name}: {len(permissions)} permissions"
                )
            )

    def permissions_for_preset(self, preset):
        actions = tuple(preset.get("actions") or ("view",))
        content_types = []

        app_labels = preset.get("apps") or ()
        if app_labels:
            content_types.extend(ContentType.objects.filter(app_label__in=app_labels))

        model_pairs = list(preset.get("models") or ()) + list(preset.get("extra_models") or ())
        for app_label, model in model_pairs:
            try:
                content_types.append(ContentType.objects.get(app_label=app_label, model=model))
            except ContentType.DoesNotExist:
                continue

        content_type_ids = {content_type.pk for content_type in content_types}
        permissions = []
        for permission in Permission.objects.filter(content_type_id__in=content_type_ids).select_related("content_type"):
            if permission.codename.split("_", 1)[0] in actions:
                permissions.append(permission)
        return permissions
