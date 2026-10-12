"""Paths built from imported Gnuboard data never leave the legacy data or media directories."""

import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from gnu_jango.core.management.commands import audit_gnuboard_assets
from gnu_jango.core.management.commands.migrate_gnuboard5 import Command as ImportCommand


class ImporterBoardFilePathTests(SimpleTestCase):
    def setUp(self):
        self.source = Path(tempfile.mkdtemp())
        (self.source / "data" / "file" / "free").mkdir(parents=True)
        (self.source / "secret.txt").write_text("x", encoding="utf-8")
        self.command = ImportCommand()
        self.command.source_root = self.source

    def test_a_board_file_resolves_inside_data_file(self):
        path = self.command.legacy_board_file_path("free", "a.jpg")
        self.assertEqual(path, (self.source / "data" / "file" / "free" / "a.jpg").resolve())

    def test_a_crafted_board_table_cannot_escape_data_file(self):
        self.assertIsNone(self.command.legacy_board_file_path("../..", "secret.txt"))
        self.assertIsNone(self.command.legacy_board_file_path("free", ".."))


class AuditAssetPathTests(SimpleTestCase):
    def setUp(self):
        self.source = Path(tempfile.mkdtemp())
        data = audit_gnuboard_assets.legacy_data_root(self.source)
        (data / "file" / "free").mkdir(parents=True)
        (data / "file" / "free" / "a.jpg").write_text("x", encoding="utf-8")
        (self.source / "secret.txt").write_text("x", encoding="utf-8")

    def test_a_legacy_file_is_found_inside_the_data_root(self):
        found = audit_gnuboard_assets.source_path([self.source], "data/file/free/a.jpg")
        self.assertEqual(found.name, "a.jpg")

    def test_a_traversing_or_absolute_path_is_not_followed(self):
        for path in ("data/../secret.txt", "../secret.txt", str(self.source / "secret.txt")):
            with self.subTest(path=path):
                self.assertIsNone(audit_gnuboard_assets.source_path([self.source], path))

    def test_media_paths_stay_under_media_root(self):
        media = Path(tempfile.mkdtemp())
        with override_settings(MEDIA_ROOT=str(media)):
            self.assertEqual(audit_gnuboard_assets.media_path("data/file/free/a.jpg"), (media / "data/file/free/a.jpg").resolve())
            self.assertIsNone(audit_gnuboard_assets.media_path("data/../../secret.txt"))
