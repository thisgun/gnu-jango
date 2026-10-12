from collections import defaultdict

from django.db import migrations, models
from django.db.models import F


def _legacy_reply_marker(rank, reply_order):
    """Translate old numeric sibling ranks into ordered reply paths."""
    if rank <= 26:
        offset = rank - 1
        letter = chr(ord("A") + offset) if reply_order else chr(ord("Z") - offset)
        return letter

    # The old Django implementation allowed unlimited flat numeric replies,
    # while Gnuboard allows 26 siblings per level. Preserve overflow records
    # as ordered legacy paths; new API replies still enforce Gnuboard's limit.
    overflow = rank - 27
    level, offset = divmod(overflow, 26)
    if reply_order:
        return "Z" + ("Z" * level) + chr(ord("A") + offset)
    return ("0" * (level + 1)) + chr(ord("Z") - offset)


def forwards(apps, schema_editor):
    Post = apps.get_model("bbs", "Post")
    Board = apps.get_model("bbs", "Board")
    database = schema_editor.connection.alias
    reply_order_by_board = dict(
        Board.objects.using(database).values_list("pk", "bo_reply_order")
    )
    threads = defaultdict(list)
    roots = []

    for post in Post.objects.using(database).all().only(
        "pk", "board_id", "wr_num", "wr_parent", "wr_reply"
    ).iterator(chunk_size=2000):
        value = str(post.wr_reply or "").strip()
        if value == "0":
            roots.append(post.pk)
        elif value.isdigit():
            numeric_rank = int(value)
            if numeric_rank > 0:
                key = (post.board_id, post.wr_num, post.wr_parent)
                threads[key].append((numeric_rank, post.pk))

    if roots:
        Post.objects.using(database).filter(pk__in=roots).update(wr_reply="")

    # Previous imports copied each row's source wr_id into wr_parent. For
    # top-level/legacy rows that value lets us recover the public ID safely.
    Post.objects.using(database).filter(
        wr_reply="",
        wr_parent__gt=0,
    ).update(legacy_wr_id=F("wr_parent"))

    for (board_id, _wr_num, _wr_parent), rows in threads.items():
        reply_order = bool(reply_order_by_board.get(board_id, False))
        rows.sort(key=lambda row: (row[0], row[1]))
        for rank, (_old_value, post_id) in enumerate(rows, start=1):
            Post.objects.using(database).filter(pk=post_id).update(
                wr_reply=_legacy_reply_marker(rank, reply_order)
            )


def backwards(apps, schema_editor):
    Post = apps.get_model("bbs", "Post")
    Board = apps.get_model("bbs", "Board")
    database = schema_editor.connection.alias
    reply_order_by_board = dict(
        Board.objects.using(database).values_list("pk", "bo_reply_order")
    )
    threads = defaultdict(list)
    roots = []

    for post in Post.objects.using(database).all().only(
        "pk", "board_id", "wr_num", "wr_parent", "wr_reply"
    ).iterator(chunk_size=2000):
        marker = str(post.wr_reply or "")
        if not marker:
            roots.append(post.pk)
        else:
            key = (post.board_id, post.wr_num, post.wr_parent)
            threads[key].append((marker, post.pk))

    if roots:
        Post.objects.using(database).filter(pk__in=roots).update(wr_reply="0")

    for (board_id, _wr_num, _wr_parent), rows in threads.items():
        reply_order = bool(reply_order_by_board.get(board_id, False))
        rows.sort(key=lambda row: (row[0], row[1]))
        count = len(rows)
        for index, (_marker, post_id) in enumerate(rows):
            old_rank = index + 1 if reply_order else count - index
            Post.objects.using(database).filter(pk=post_id).update(
                wr_reply=str(old_rank)
            )

    Post.objects.using(database).all().update(legacy_wr_id=None)


class Migration(migrations.Migration):

    dependencies = [
        ("bbs", "0043_comment_wr_comment"),
    ]

    operations = [
        migrations.AddField(
            model_name="post",
            name="legacy_wr_id",
            field=models.PositiveBigIntegerField(
                blank=True,
                editable=False,
                null=True,
                verbose_name="원본 글 번호",
            ),
        ),
        migrations.AlterUniqueTogether(
            name="post",
            unique_together={("board", "wr_slug"), ("board", "legacy_wr_id")},
        ),
        migrations.AlterField(
            model_name="post",
            name="wr_reply",
            field=models.CharField(
                blank=True,
                default="",
                max_length=10,
                verbose_name="답글순서",
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
