from django.db import migrations


def enable_search_on_every_board(apps, schema_editor):
    # Site search and recent posts now honour bo_use_search (Gnuboard5 search.php / new.php).
    # Boards created here before 0046 got the old default (off); the owner chose to switch every
    # board on so none drops out of search after the change.
    Board = apps.get_model("bbs", "Board")
    Board.objects.filter(bo_use_search=False).update(bo_use_search=True)


class Migration(migrations.Migration):

    dependencies = [
        ("bbs", "0046_board_use_search_default_on"),
    ]

    operations = [
        migrations.RunPython(enable_search_on_every_board, migrations.RunPython.noop),
    ]
