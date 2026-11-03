"""Checking a member against the level rules and giving the new level.

A member is checked when they are an active, e-mail-certified, non-staff member who has not left, at
or above the sign-up level (cf_register_level). Three kinds of member are left alone: one an admin set
below the sign-up level (a penalty), one
whose level is now below a level this plugin gave them (an admin lowered it on purpose), and one on
the admin's hold list (LevelUpHold). The member
gets the highest active rule above their level whose conditions they all meet; levels are never
lowered. Points are the current balance; posts and comments count what the member wrote.
"""

from dataclasses import dataclass, fields

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Exists, F, OuterRef
from django.utils import timezone

from gnu_jango.bbs.models import Comment, Post
from gnu_jango.notifications.outbox import event_on_commit
from gnu_jango.plugins import hooks
from gnu_jango.users.models import Profile
from gnu_jango.users.point_ledger import config_points

from . import conf
from .models import ATTENDANCE_APP, MAX_LEVEL, MIN_LEVEL, LevelChange, LevelRule, LevelUpHold

SWEEP_CHUNK = 500
# cf_register_level outside 1-9 means the Gnuboard5 default (gnu_jango.api.v1_auth.register_level).
DEFAULT_SIGN_UP_LEVEL = 2
# One sweep raises at most this many members (each sends a notification and a hook); the next run
# goes on where this one stopped.
MAX_PROMOTIONS_PER_RUN = 2000

LABELS = {"points": "포인트", "posts": "글", "comments": "댓글", "days": "가입", "attendance": "출석"}
UNITS = {"days": "일", "attendance": "일"}


@dataclass(frozen=True)
class Activity:
    """What a member has. None: not counted, because no rule being checked needs it."""

    points: int | None = None
    posts: int | None = None
    comments: int | None = None
    days: int | None = None
    attendance: int | None = None

    def get(self, name):
        return getattr(self, name) or 0

    def describe(self):
        parts = []
        for field in fields(self):
            value = getattr(self, field.name)
            if value is not None:
                parts.append(f"{LABELS[field.name]} {value:,}{UNITS.get(field.name, '')}")
        return " · ".join(parts)


def active_rules():
    """The active rules a member can be given, highest level first."""
    rules = LevelRule.objects.filter(is_active=True, level__gte=MIN_LEVEL, level__lte=MAX_LEVEL)
    return list(rules.order_by("-level"))


def needed(rules):
    """The conditions any of ``rules`` uses: the counts worth making."""
    return {name for name in LABELS if any(getattr(rule, f"min_{name}") for rule in rules)}


def _counts(model, user_ids):
    rows = model.objects.filter(user_id__in=user_ids).values("user_id").annotate(n=Count("pk"))
    return {row["user_id"]: row["n"] for row in rows}


def activities(members, *, today, need):
    """{user id: Activity} for (user id, point balance, date joined) rows, in a few queries."""
    ids = [user_id for user_id, _points, _joined in members]
    posts = _counts(Post, ids) if "posts" in need else None
    comments = _counts(Comment, ids) if "comments" in need else None
    attendance = None
    if "attendance" in need and apps.is_installed(ATTENDANCE_APP):
        attendance = _counts(apps.get_model("attendance", "Attendance"), ids)

    def count(found, user_id):
        return None if found is None else found.get(user_id, 0)

    return {
        user_id: Activity(
            points=(points or 0) if "points" in need else None,
            posts=count(posts, user_id),
            comments=count(comments, user_id),
            days=max(0, (today - timezone.localdate(joined)).days) if "days" in need and joined else None,
            attendance=count(attendance, user_id) if "attendance" in need else None,
        )
        for user_id, points, joined in members
    }


def sign_up_level():
    """The level new members start at; members below it were lowered by an admin."""
    level = config_points("cf_register_level")
    return level if 1 <= level <= MAX_LEVEL else DEFAULT_SIGN_UP_LEVEL


def _candidates():
    """Profiles of the members the rules apply to."""
    lowered_by_admin = LevelChange.objects.filter(user_id=OuterRef("user_id"), new_level__gt=OuterRef("user_level"))
    held = LevelUpHold.objects.filter(user_id=OuterRef("user_id"))
    return Profile.objects.filter(
        user__is_active=True,
        user__is_staff=False,
        user__is_superuser=False,
        leave_date__isnull=True,
        email_certify__isnull=False,
        user_level__gte=sign_up_level(),
    ).exclude(Exists(lowered_by_admin)).exclude(Exists(held))


def target_rule(level, activity, rules):
    """The highest rule above ``level`` that ``activity`` meets, or None."""
    for rule in rules:
        if MIN_LEVEL <= rule.level <= MAX_LEVEL and rule.level > level and _meets(rule, activity):
            return rule
    return None


def _meets(rule, activity):
    return all(activity.get(name) >= getattr(rule, f"min_{name}") for name in LABELS)


def promote(user, old_level, rule, activity):
    """Give ``rule.level`` to a member still at ``old_level`` and still eligible; the LevelChange, or
    None when that changed meanwhile (another request, the admin blocking or re-levelling them)."""
    if not MIN_LEVEL <= rule.level <= MAX_LEVEL:
        return None
    with transaction.atomic():
        updated = _candidates().filter(user=user, user_level=old_level).update(user_level=rule.level)
        if not updated:
            return None
        change = LevelChange.objects.create(
            user=user, old_level=old_level, new_level=rule.level, reason=activity.describe()[:255]
        )
        if conf.value("LEVEL_UP_NOTIFY"):
            event_on_commit(
                user.pk,
                f"level_up:{change.pk}",
                {
                    "nt_type": "system",
                    "nt_title": f"축하합니다! 회원 레벨이 {rule.level}(으)로 올랐습니다.",
                    "nt_data": {"href": "/mypage", "level": rule.level},
                },
            )
        transaction.on_commit(
            lambda: hooks.emit("level_up.promoted", user=user, old_level=old_level, new_level=rule.level)
        )
    return change


def check(user, *, today=None):
    """Promote ``user`` if a rule now fits; the LevelChange or None. Cheap when no rule is above them."""
    if not user or not user.pk or not user.is_active or user.is_staff or user.is_superuser:
        return None
    row = _candidates().filter(user=user).values_list("user_level", "user_point").first()
    if row is None:
        return None
    level, points = row
    rules = [rule for rule in active_rules() if rule.level > level]
    if not rules:
        return None
    today = today or timezone.localdate()
    activity = activities([(user.pk, points, user.date_joined)], today=today, need=needed(rules))[user.pk]
    rule = target_rule(level, activity, rules)
    return promote(user, level, rule, activity) if rule else None


def sweep(*, apply, today=None, limit=MAX_PROMOTIONS_PER_RUN):
    """Check every member below the highest rule; {"checked", "promoted", "levels", "more", "dry_run"}.
    ``more`` is True when the run stopped at ``limit`` promotions."""
    today = today or timezone.localdate()
    rules = active_rules()
    report = {"checked": 0, "promoted": 0, "levels": {}, "more": False, "dry_run": not apply}
    if not rules:
        return report
    need = needed(rules)
    rows = (
        _candidates()
        .filter(user_level__lt=rules[0].level)
        .order_by("user_id")
        .values_list("user_id", "user_level", "user_point", F("user__date_joined"))
    )
    users = get_user_model().objects
    last_id = 0
    while True:
        chunk = list(rows.filter(user_id__gt=last_id)[:SWEEP_CHUNK])
        if not chunk:
            return report
        last_id = chunk[-1][0]
        found = activities([(uid, points, joined) for uid, _level, points, joined in chunk], today=today, need=need)
        for user_id, level, _points, _joined in chunk:
            if report["promoted"] >= limit:
                return {**report, "more": True}
            report["checked"] += 1
            rule = target_rule(level, found[user_id], rules)
            if rule is None:
                continue
            if apply:
                user = users.filter(pk=user_id).first()  # None: deleted since the chunk was read
                if user is None or not promote(user, level, rule, found[user_id]):
                    continue
            report["promoted"] += 1
            report["levels"][str(rule.level)] = report["levels"].get(str(rule.level), 0) + 1
