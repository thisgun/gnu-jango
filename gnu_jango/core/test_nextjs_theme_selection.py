"""Two Next.js exports side by side: the active theme (cf_theme) decides which one Django serves.

nextjs_default stays the fallback — for nextjs25, for the classic themes and for a theme folder that
is not a complete export (no index.html or no theme_static/<name>/_next/static).
"""

import json
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings

from gnu_jango.config import config as site_config
from gnu_jango.config.models import Config
from gnu_jango.core import views

ASSET = b"console.log('x')"


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8") if isinstance(content, str) else path.write_bytes(content)


class ThemeFixture(TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        for name in ("nextjs_default", "handbook"):
            write(
                self.root / "theme" / name / "index.html",
                f"<html>{name.upper()} HOME<script>window.__G5_NEXTJS25_CONFIG__ = Object.assign("
                '{"apiBaseUrl":"/api/v1"},window.__G5_NEXTJS25_CONFIG__ || {});</script></html>',
            )
            write(self.root / "theme" / name / "shop.html", f"<html>{name.upper()} SHOP</html>")
            write(self.root / "theme" / name / "sw.js", f"// {name} worker")
            write(self.root / "theme" / name / "manifest.json", json.dumps({"name": name, "icons": []}))
            write(self.root / "theme_static" / name / "_next" / "static" / "chunks" / f"{name}-only.js", ASSET)
            write(self.root / "theme_static" / name / "_next" / "static" / "chunks" / "shared-hash.js", f"// {name}")
        templates = [{**settings.TEMPLATES[0], "DIRS": [self.root]}]
        overrides = override_settings(TEMPLATES_DIR=self.root, TEMPLATES=templates)
        overrides.enable()
        self.addCleanup(overrides.disable)

    def activate(self, theme):
        Config.objects.update_or_create(name="cf_theme", defaults={"value": theme})
        site_config.clear()
        self.addCleanup(site_config.clear)


class ThemeSelectionTests(ThemeFixture):
    def test_the_home_page_comes_from_the_active_export(self):
        for theme, marker in (("nextjs_default", "NEXTJS_DEFAULT HOME"), ("handbook", "HANDBOOK HOME")):
            with self.subTest(theme=theme):
                self.activate(theme)
                self.assertContains(self.client.get("/"), marker)

    def test_other_pages_come_from_the_active_export_too(self):
        self.activate("handbook")

        self.assertContains(self.client.get("/shop"), "HANDBOOK SHOP")

    def test_nextjs25_and_unknown_themes_fall_back_to_nextjs_default(self):
        for theme in ("nextjs25", "no_such_theme"):
            with self.subTest(theme=theme):
                self.activate(theme)
                self.assertEqual(views._nextjs_theme_name(), "nextjs_default")

    def test_a_theme_folder_without_its_assets_is_not_an_export(self):
        self.activate("handbook")
        shutil.rmtree(self.root / "theme_static" / "handbook")

        self.assertEqual(views._nextjs_theme_name(), "nextjs_default")
        self.assertEqual(views._theme_template_dir(), "theme/nextjs_default")

    def test_theme_names_that_are_not_plain_folder_names_are_refused(self):
        for theme in ("../handbook", "hand/book", ""):
            with self.subTest(theme=theme):
                self.activate(theme)
                self.assertEqual(views._nextjs_theme_name(), "nextjs_default")

    def test_public_files_and_the_manifest_come_from_the_active_export(self):
        self.activate("handbook")

        self.assertContains(self.client.get("/sw.js"), "handbook worker")
        self.assertEqual(json.loads(self.client.get("/manifest.json").content)["name"], "handbook")


class ThemeStaticFilesTests(ThemeFixture):
    def get(self, name):
        return self.client.get(f"/_next/static/chunks/{name}")

    def test_files_of_every_installed_export_are_served(self):
        self.activate("nextjs_default")

        self.assertEqual(self.get("nextjs_default-only.js").status_code, 200)
        self.assertEqual(self.get("handbook-only.js").status_code, 200)

    def test_when_both_have_a_file_of_that_name_the_active_one_wins(self):
        for theme in ("nextjs_default", "handbook"):
            self.activate(theme)
            self.assertEqual(b"".join(self.get("shared-hash.js").streaming_content).decode(), f"// {theme}")

    def test_the_cache_rules_stay_the_same_for_a_file_of_another_export(self):
        self.activate("nextjs_default")

        self.assertEqual(
            self.get("handbook-only.js")["Cache-Control"], "public, max-age=31536000, s-maxage=31536000, immutable"
        )

    def test_a_missing_file_and_paths_leaving_the_folder_are_a_404(self):
        self.activate("handbook")

        for path in ("chunks/none.js", "chunks/../../../theme/handbook/index.html", "..%2f..%2findex.html"):
            with self.subTest(path=path):
                response = self.client.get(f"/_next/static/{path}")
                self.assertIn(response.status_code, (400, 404))
                self.assertNotIn(b"HANDBOOK HOME", response.content if not response.streaming else b"")

    def test_the_build_id_folder_is_found_in_the_export_that_has_it(self):
        write(self.root / "theme_static" / "handbook" / "_next" / "static" / "g5-handbook-static" / "_buildManifest.js", "x")
        self.activate("nextjs_default")

        response = self.client.get("/_next/static/g5-handbook-static/_buildManifest.js")

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("immutable", response.get("Cache-Control", ""))


class ThemeChooserTests(ThemeFixture):
    def setUp(self):
        super().setUp()
        from django.contrib.auth import get_user_model

        self.admin = get_user_model().objects.create_superuser("themeadmin", "a@example.test", "pw-admin-123")
        self.client.force_login(self.admin)

    def test_the_handbook_export_is_offered_with_its_own_title(self):
        from gnu_jango.config import theme_admin

        themes = {theme["name"]: theme for theme in theme_admin._installed_themes()}

        self.assertEqual(themes["handbook"]["title"], "Handbook (매뉴얼)")
        self.assertIn("nextjs_default", themes)

    def test_the_admin_can_switch_the_site_to_it(self):
        from django.urls import reverse

        self.client.post(reverse("admin-theme-settings"), {"theme": "handbook"})
        site_config.clear()

        self.assertEqual(Config.objects.get(name="cf_theme").value, "handbook")
        self.assertContains(self.client.get("/"), "HANDBOOK HOME")


class ThemeSettingsTests(ThemeFixture):
    """The handbook theme reads its manual group at run time: from the page's runtime config on a
    static export and from /api/v1/settings on a server runtime. The default theme gets neither."""

    def set_group(self, group):
        Config.objects.update_or_create(name="cf_docs_group", defaults={"value": group})
        site_config.clear()

    def runtime_settings(self, html):
        """The theme settings from the first runtime-config script (window.__G5_NEXTJS25_CONFIG__ = {...};)."""
        import re

        match = re.search(r"window\.__G5_NEXTJS25_CONFIG__ = (\{.*?\});</script>", html)
        return json.loads(match.group(1)).get("themeSettings") if match else None

    def test_the_page_carries_the_manual_group_for_the_handbook_theme(self):
        self.activate("handbook")
        self.set_group("manual")

        html = self.client.get("/").content.decode()

        self.assertIn('"themeSettings"', html)
        settings_value = self.runtime_settings(html)
        self.assertEqual(settings_value["theme"], "handbook")
        self.assertEqual(settings_value["docs"]["group"], "manual")
        self.assertGreater(settings_value["revision"], 0)

    def test_the_default_theme_page_is_left_as_it_was(self):
        self.activate("nextjs_default")
        self.set_group("manual")

        self.assertNotIn("themeSettings", self.client.get("/").content.decode())

    def test_the_settings_api_returns_them_only_for_the_active_handbook_theme(self):
        from rest_framework.test import APIClient

        self.set_group("manual")
        self.activate("handbook")
        value = APIClient().get("/api/v1/settings").json()["data"]["theme_settings"]
        self.assertEqual((value["theme"], value["docs"]["group"]), ("handbook", "manual"))

        self.activate("nextjs_default")
        self.assertIsNone(APIClient().get("/api/v1/settings").json()["data"]["theme_settings"])
