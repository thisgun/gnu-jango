"""Member points: Gnuboard5's insert_point/delete_point rules for the v1 API.

Every change moves ``Profile.user_point`` and writes a ``User_Point`` history row in one
transaction. A row with a relation (table, id, action) is written at most once, which is how
Gnuboard5 charges a post's read or download points only the first time and grants the daily
login points once a day.
"""

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from gnu_jango import defaults
from gnu_jango.config.models import Config

from .models import Profile, User_Point

APPLIED = "applied"
DUPLICATE = "duplicate"
INSUFFICIENT = "insufficient"
SKIPPED = "skipped"

_FALSE_VALUES = {"", "0", "false", "no", "off"}


def points_enabled():
    """Gnuboard5's cf_use_point; on unless the imported config turns it off."""
    value = Config.objects.filter(name="cf_use_point").values_list("value", flat=True).first()
    return str("1" if value is None else value).strip().lower() not in _FALSE_VALUES


def config_points(name):
    """An integer site setting; when the row is missing, the Gnuboard5 default (defaults.CONFIGS)."""
    value = Config.objects.filter(name=name).values_list("value", flat=True).first()
    if value is None:
        value = defaults.CONFIGS.get(name, (0,))[0]
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return 0


def post_point_id(post):
    """The id points use for a post: its Gnuboard5 wr_id (kept on imported posts), else its pk.

    Imported point history refers to the original wr_id, and the public URLs use the same id.
    """
    return post.legacy_wr_id or post.pk


def _lock_member(user):
    """Serialise point changes per member (Gnuboard5 takes a named lock for the same reason)."""
    Profile.objects.get_or_create(user=user)
    return Profile.objects.select_for_update().get(user=user)


def point_balance(user):
    if not user or not getattr(user, "pk", None):
        return 0
    return int(Profile.objects.filter(user=user).values_list("user_point", flat=True).first() or 0)


def has_point_row(user, rel_table, rel_id, rel_action):
    if not user or not getattr(user, "pk", None):
        return False
    return User_Point.objects.filter(
        user=user, po_rel_table=rel_table, po_rel_id=rel_id, po_rel_action=rel_action
    ).exists()


def insert_point(user, point, content, rel_table="", rel_id=0, rel_action="", *, require_balance=False, force=False):
    """Add (or, with a negative ``point``, take) points and record it.

    ``require_balance`` refuses a charge the balance does not cover (the spend is a conditional
    update, so two requests cannot both spend the same points). ``force`` applies the change even
    when points are switched off, for refunds of points already taken.
    """
    point = int(point or 0)
    if not user or not getattr(user, "pk", None) or point == 0:
        return SKIPPED
    if not force and not points_enabled():
        return SKIPPED

    has_relation = bool(rel_table or rel_id or rel_action)
    with transaction.atomic():
        _lock_member(user)
        if has_relation and has_point_row(user, rel_table, rel_id, rel_action):
            return DUPLICATE
        updated = Profile.objects.filter(user=user)
        if require_balance and point < 0:
            updated = updated.filter(user_point__gte=-point)
        if not updated.update(user_point=F("user_point") + point):
            return INSUFFICIENT
        User_Point.objects.create(
            user=user,
            po_datetime=timezone.now(),
            po_content=content[:255],
            po_point=point,
            po_use_point=0,
            po_mb_point=point_balance(user),
            po_expired=1 if point < 0 else 0,
            po_rel_table=rel_table[:20],
            po_rel_id=rel_id or 0,
            po_rel_action=rel_action[:255],
        )
    return APPLIED


def delete_point(user, rel_table, rel_id, rel_action):
    """Undo the rows of a relation (Gnuboard5 delete_point): the balance gives their points back."""
    if not user or not getattr(user, "pk", None):
        return False
    with transaction.atomic():
        _lock_member(user)
        rows = list(
            User_Point.objects.filter(
                user=user, po_rel_table=rel_table, po_rel_id=rel_id, po_rel_action=rel_action
            ).values_list("pk", "po_point")
        )
        if not rows:
            return False
        User_Point.objects.filter(pk__in=[pk for pk, _ in rows]).delete()
        Profile.objects.filter(user=user).update(user_point=F("user_point") - sum(point for _, point in rows))
    return True
