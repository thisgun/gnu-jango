"""자동 등업: rules, the activity hooks, the daily sweep, notifications and the admin."""

import json
from datetime import date, timedelta
from io import StringIO

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from gnu_jango.core.models import Notification
from gnu_jango.plugins import hooks, state
from gnu_jango.testing.factories import AdminFactory, CommentFactory, MemberFactory, PostFactory
from gnu_jango.users.models import Profile

from . import services
from .models import LevelChange, LevelRule

pytestmark = pytest.mark.django_db

TODAY = date(2026, 11, 3)


def level_of(user):
    return Profile.objects.get(user=user).user_level


def give(user, *, points=0, posts=0, comments=0, joined_days_ago=0):
    Profile.objects.filter(user=user).update(user_point=points)
    for _ in range(posts):
        PostFactory(user=user)
    post = PostFactory() if comments else None
    for _ in range(comments):
        CommentFactory(post=post, user=user)
    type(user).objects.filter(pk=user.pk).update(date_joined=timezone.now() - timedelta(days=joined_days_ago))
    user.refresh_from_db()


def emit(django_capture_on_commit_callbacks, name, **payload):
    with django_capture_on_commit_callbacks(execute=True):
        hooks.emit(name, **payload)


@pytest.fixture
def rules():
    return [
        LevelRule.objects.create(level=3, min_posts=1),
        LevelRule.objects.create(level=4, min_points=1000, min_posts=5, min_comments=3, min_days=7),
    ]


def test_a_post_that_meets_a_rule_raises_the_level_and_tells_the_member(
    rules, monkeypatch, django_capture_on_commit_callbacks
):
    member = MemberFactory()
    post = PostFactory(user=member)
    monkeypatch.setattr(hooks, "_listeners", dict(hooks._listeners))  # the listener below stays in this test
    promoted = []
    hooks.on("level_up.promoted")(lambda user, old_level, new_level, **kw: promoted.append((user.pk, old_level, new_level)))

    emit(django_capture_on_commit_callbacks, "bbs.post.created", post=post, user=member, request=None)

    assert level_of(member) == 3
    change = LevelChange.objects.get()
    assert (change.user_id, change.old_level, change.new_level) == (member.pk, 2, 3)
    assert "글 1" in change.reason
    note = Notification.objects.get(user=member)
    assert "레벨이 3" in note.nt_title and note.nt_data["level"] == 3
    assert promoted == [(member.pk, 2, 3)]


def test_the_member_gets_the_highest_rule_they_meet(rules):
    member = MemberFactory()
    give(member, points=1500, posts=6, comments=3, joined_days_ago=10)

    services.check(member)

    assert level_of(member) == 4
    assert list(LevelChange.objects.values_list("old_level", "new_level")) == [(2, 4)]


@pytest.mark.parametrize(
    "missing", [{"points": 999}, {"posts": 4}, {"comments": 2}, {"joined_days_ago": 6}]
)
def test_every_condition_of_a_rule_must_be_met(rules, missing):
    member = MemberFactory()
    give(member, **{"points": 1500, "posts": 6, "comments": 3, "joined_days_ago": 10, **missing})

    services.check(member)

    assert level_of(member) == 3  # only the level 3 rule (one post)


def test_a_level_is_never_lowered(rules):
    member = MemberFactory(level=5)
    give(member, posts=1)

    assert services.check(member) is None
    assert level_of(member) == 5


@pytest.mark.parametrize(
    "member_kwargs",
    [{"is_staff": True}, {"is_superuser": True}, {"is_active": False}, {"level": 1}],
    ids=["staff", "superuser", "inactive", "below-the-sign-up-level"],
)
def test_staff_inactive_and_demoted_members_are_left_alone(rules, member_kwargs):
    member = MemberFactory(**member_kwargs)
    give(member, posts=1)

    services.check(member)
    services.sweep(apply=True)

    assert not LevelChange.objects.exists()


def test_a_member_who_left_is_left_alone(rules):
    member = MemberFactory()
    give(member, posts=1)
    Profile.objects.filter(user=member).update(leave_date=TODAY)

    services.sweep(apply=True)

    assert level_of(member) == 2


def test_an_inactive_rule_is_ignored(rules):
    LevelRule.objects.filter(level=3).update(is_active=False)
    member = MemberFactory()
    give(member, posts=1)

    services.check(member)

    assert level_of(member) == 2


def test_a_comment_and_a_new_member_are_checked_too(django_capture_on_commit_callbacks):
    LevelRule.objects.create(level=3, min_comments=1)
    LevelRule.objects.create(level=2 + 1 + 1)  # no conditions: everyone signing up gets level 4
    commenter = MemberFactory()
    comment = CommentFactory(user=commenter)

    emit(django_capture_on_commit_callbacks, "bbs.comment.created", comment=comment, user=commenter, request=None)
    newbie = MemberFactory()
    emit(django_capture_on_commit_callbacks, "member.joined", user=newbie, request=None)

    assert (level_of(commenter), level_of(newbie)) == (4, 4)


def test_attendance_days_count_through_the_attendance_plugin(django_capture_on_commit_callbacks):
    from gnu_plugins.attendance.services import check_in

    LevelRule.objects.create(level=3, min_attendance=2)
    member = MemberFactory()

    with django_capture_on_commit_callbacks(execute=True):
        check_in(member, today=TODAY - timedelta(days=1))
    assert level_of(member) == 2
    with django_capture_on_commit_callbacks(execute=True):
        check_in(member, today=TODAY)

    assert level_of(member) == 3
    assert "출석 2일" in LevelChange.objects.get().reason


def test_the_first_visit_of_the_day_checks_once(rules):
    member = MemberFactory()
    give(member, posts=1)
    Profile.objects.filter(user=member).update(user_level=2)
    LevelRule.objects.filter(level=3).update(min_days=1)

    hooks.emit("member.visited", user=member, request=None)  # joined today: not yet
    type(member).objects.filter(pk=member.pk).update(date_joined=timezone.now() - timedelta(days=2))
    member.refresh_from_db()
    hooks.emit("member.visited", user=member, request=None)  # same day: skipped by the cache
    assert level_of(member) == 2

    cache.clear()
    hooks.emit("member.visited", user=member, request=None)
    assert level_of(member) == 3


@override_settings(LEVEL_UP_ON_ACTIVITY=False)
def test_with_activity_checks_off_only_the_sweep_raises_levels(rules, django_capture_on_commit_callbacks):
    member = MemberFactory()
    post = PostFactory(user=member)

    emit(django_capture_on_commit_callbacks, "bbs.post.created", post=post, user=member, request=None)
    assert level_of(member) == 2

    services.sweep(apply=True)
    assert level_of(member) == 3


@override_settings(LEVEL_UP_NOTIFY=False)
def test_with_notifications_off_no_notification_is_made(rules, django_capture_on_commit_callbacks):
    member = MemberFactory()
    give(member, posts=1)

    with django_capture_on_commit_callbacks(execute=True):
        services.check(member)

    assert level_of(member) == 3
    assert not Notification.objects.filter(user=member).exists()


def test_switching_the_plugin_off_stops_the_activity_checks(rules, django_capture_on_commit_callbacks):
    member = MemberFactory()
    post = PostFactory(user=member)
    state.set_enabled("level_up", False)

    emit(django_capture_on_commit_callbacks, "bbs.post.created", post=post, user=member, request=None)

    assert level_of(member) == 2


def test_a_level_changed_meanwhile_is_not_overwritten(rules):
    member = MemberFactory()
    rule = LevelRule.objects.get(level=3)
    Profile.objects.filter(user=member).update(user_level=6)  # e.g. the admin, a moment earlier

    assert services.promote(member, 2, rule, services.Activity(posts=1)) is None
    assert level_of(member) == 6
    assert not LevelChange.objects.exists()


def test_the_sweep_counts_without_apply_and_walks_every_chunk(rules, monkeypatch):
    monkeypatch.setattr(services, "SWEEP_CHUNK", 2)
    members = [MemberFactory() for _ in range(5)]
    for member in members[:3]:
        give(member, posts=1)

    out = StringIO()
    call_command("level_up_sweep", "--json", stdout=out)
    dry = json.loads(out.getvalue())
    assert (dry["checked"], dry["promoted"], dry["dry_run"]) == (5, 3, True)
    assert [level_of(member) for member in members] == [2] * 5

    out = StringIO()
    call_command("level_up_sweep", "--apply", "--json", stdout=out)
    report = json.loads(out.getvalue())
    assert (report["promoted"], report["levels"]) == (3, {"3": 3})
    assert [level_of(member) for member in members] == [3, 3, 3, 2, 2]


def test_without_rules_the_sweep_does_nothing():
    MemberFactory()

    assert services.sweep(apply=True) == {"checked": 0, "promoted": 0, "levels": {}, "more": False, "dry_run": False}


def test_a_member_an_admin_lowered_after_a_promotion_is_not_raised_again(rules):
    member = MemberFactory()
    give(member, posts=1)
    services.check(member)
    Profile.objects.filter(user=member).update(user_level=2)  # the admin takes the level back

    services.check(member)
    services.sweep(apply=True)

    assert level_of(member) == 2
    assert LevelChange.objects.count() == 1


def test_a_member_who_has_not_certified_the_e_mail_is_left_alone(rules):
    member = MemberFactory()
    give(member, posts=1)
    Profile.objects.filter(user=member).update(email_certify=None)

    services.check(member)

    assert level_of(member) == 2


def test_a_member_blocked_meanwhile_is_not_promoted(rules):
    member = MemberFactory()
    type(member).objects.filter(pk=member.pk).update(is_active=False)  # after the candidate was read

    assert services.promote(member, 2, LevelRule.objects.get(level=3), services.Activity(posts=1)) is None
    assert level_of(member) == 2


def test_a_member_deleted_during_the_sweep_does_not_stop_it(rules, monkeypatch):
    gone, kept = MemberFactory(), MemberFactory()
    give(gone, posts=1)
    give(kept, posts=1)
    real = services.activities

    def delete_then_count(*args, **kwargs):
        found = real(*args, **kwargs)
        type(gone).objects.filter(pk=gone.pk).delete()
        return found

    monkeypatch.setattr(services, "activities", delete_then_count)
    report = services.sweep(apply=True)

    assert report["promoted"] == 1
    assert level_of(kept) == 3


def test_the_sweep_stops_at_its_limit_and_says_there_is_more(rules):
    members = [MemberFactory() for _ in range(3)]
    for member in members:
        give(member, posts=1)

    report = services.sweep(apply=True, limit=2)

    assert (report["promoted"], report["more"]) == (2, True)
    assert services.sweep(apply=True)["promoted"] == 1


def test_a_rule_row_outside_2_to_9_cannot_be_stored():
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError), transaction.atomic():
        LevelRule.objects.create(level=10)


def test_only_the_counts_a_rule_uses_are_made(rules):
    LevelRule.objects.filter(level=4).delete()  # left: level 3 needs one post
    member = MemberFactory()
    give(member, posts=1, comments=2)

    services.check(member)

    assert LevelChange.objects.get().reason == "글 1"


def test_a_failing_visit_check_is_not_retried_on_every_page(rules, monkeypatch):
    member = MemberFactory()
    calls = []

    def broken(user, **kwargs):
        calls.append(user.pk)
        raise RuntimeError("boom")

    monkeypatch.setattr(services, "check", broken)
    hooks.emit("member.visited", user=member, request=None)
    hooks.emit("member.visited", user=member, request=None)

    assert calls == [member.pk]


def test_only_superusers_change_rules_and_delete_records(client):
    from django.contrib.auth.models import Permission

    rule = LevelRule.objects.create(level=3, min_posts=1)
    change = LevelChange.objects.create(user=MemberFactory(), old_level=2, new_level=3)
    staff = MemberFactory(is_staff=True)
    staff.user_permissions.add(
        *Permission.objects.filter(content_type__app_label="level_up", codename__in=[
            "view_levelrule", "add_levelrule", "change_levelrule", "view_levelchange", "delete_levelchange",
        ])
    )
    client.force_login(staff)

    assert client.get("/admin/level_up/levelrule/").status_code == 200
    assert client.get("/admin/level_up/levelrule/add/").status_code == 403
    client.post(f"/admin/level_up/levelrule/{rule.pk}/change/", {"level": "9", "is_active": "on"})
    assert LevelRule.objects.get(pk=rule.pk).level == 3
    assert client.post(f"/admin/level_up/levelchange/{change.pk}/delete/", {"post": "yes"}).status_code == 403
    assert LevelChange.objects.filter(pk=change.pk).exists()


@pytest.mark.parametrize("level", [1, 10])
def test_a_rule_can_only_give_levels_2_to_9(level):
    with pytest.raises(ValidationError):
        LevelRule(level=level).full_clean()


def test_the_admin_edits_rules_and_lists_changes(client):
    member = MemberFactory()
    LevelChange.objects.create(user=member, old_level=2, new_level=3, reason="글 1")
    client.force_login(AdminFactory())

    response = client.post(
        "/admin/level_up/levelrule/add/",
        {
            "level": "5", "min_points": "100", "min_posts": "0", "min_comments": "0",
            "min_days": "0", "min_attendance": "3", "is_active": "on",
        },
    )

    assert response.status_code == 302, response.content[:500]
    assert LevelRule.objects.get(level=5).min_attendance == 3
    assert client.get("/admin/level_up/levelrule/").status_code == 200
    assert client.get("/admin/level_up/levelchange/").status_code == 200
    change = LevelChange.objects.get()
    assert client.get(f"/admin/level_up/levelchange/{change.pk}/change/").status_code == 200
    assert client.post(f"/admin/level_up/levelchange/{change.pk}/change/", {}).status_code == 403
