"""The production static storage keeps references to files the legacy skins never shipped."""

import tempfile
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

STORAGE = "gnu_jango.core.static_storage.LegacyTolerantManifestStorage"


class LegacyTolerantManifestStorageTests(SimpleTestCase):
    def collect(self, files):
        source = Path(tempfile.mkdtemp())
        target = Path(tempfile.mkdtemp())
        for name, content in files.items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        storages = {
            "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
            "staticfiles": {"BACKEND": STORAGE},
        }
        with override_settings(STATICFILES_DIRS=[str(source)], STATIC_ROOT=str(target), STORAGES=storages):
            call_command("collectstatic", interactive=False, verbosity=0)
        return target

    def test_a_missing_source_map_does_not_stop_collectstatic(self):
        target = self.collect({"skin/app.js": "console.log(1);\n//# sourceMappingURL=app.js.map\n"})

        hashed = [path for path in (target / "skin").glob("app.*.js") if not path.name.endswith(".gz")]
        self.assertTrue(hashed)
        self.assertIn("sourceMappingURL=app.js.map", hashed[0].read_text(encoding="utf-8"))

    def test_missing_and_absolute_css_references_stay_as_written_while_present_ones_are_hashed(self):
        target = self.collect({
            "skin/style.css": "a{background:url(gone.png)} b{background:url(/img/captcha2.png)} i{background:url(here.png)}",
            "skin/here.png": "png",
        })

        css = next(path for path in (target / "skin").glob("style.*.css") if not path.name.endswith(".gz"))
        content = css.read_text(encoding="utf-8")
        self.assertIn("url(gone.png)", content)
        self.assertIn("url(/img/captcha2.png)", content)
        self.assertNotIn("url(here.png)", content)
        self.assertRegex(content, r"url\(\"?here\.[0-9a-f]+\.png\"?\)")
