"""Every installed Next.js theme must ship the CSS/JS its pages ask for, and git must carry them.

A theme export is two folders: templates/theme/<name> (HTML) and templates/theme_static/<name>
(hashed _next/static assets). The "static/" rule in .gitignore silently dropped a newly added theme's
assets, so the theme worked on the machine that built it and rendered unstyled everywhere else.
"""

import re
import shutil
import subprocess
from pathlib import Path

from django.test import SimpleTestCase

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
REPO_ROOT = TEMPLATES.parents[1]
THEME_DIR = TEMPLATES / "theme"
STATIC_DIR = TEMPLATES / "theme_static"
ASSET_URL = re.compile(r"/_next/static/[A-Za-z0-9_./~%-]+\.(?:js|css|woff2?)")


def _installed_exports():
    """Theme names whose export has an entry page (the classic Django themes do not)."""
    if not THEME_DIR.is_dir():
        return []
    return sorted(p.name for p in THEME_DIR.iterdir() if (p / "index.html").is_file() and (p / "404.html").is_file())


def _entry_asset_urls(name):
    html = (THEME_DIR / name / "index.html").read_text(encoding="utf-8", errors="replace")
    return sorted(set(ASSET_URL.findall(html)))


def _resolve(asset_url):
    relative = asset_url.lstrip("/")
    for static_root in sorted(STATIC_DIR.iterdir()):
        candidate = static_root / relative
        if candidate.is_file():
            return candidate
    return None


class ThemeStaticCompleteTests(SimpleTestCase):
    def test_an_export_is_installed(self):
        self.assertIn("nextjs_default", _installed_exports())

    def test_every_asset_the_entry_page_asks_for_exists(self):
        for name in _installed_exports():
            urls = _entry_asset_urls(name)
            self.assertTrue(urls, f"{name}: index.html references no _next/static assets")
            missing = [url for url in urls if _resolve(url) is None]
            self.assertEqual(missing, [], f"{name}: assets missing from theme_static")

    def test_git_does_not_ignore_the_assets(self):
        git = shutil.which("git")
        if not git or not (REPO_ROOT / ".git").exists():
            self.skipTest("not a git checkout")
        for name in _installed_exports():
            paths = [
                _resolve(url).relative_to(REPO_ROOT).as_posix()
                for url in _entry_asset_urls(name)
                if _resolve(url)
            ]
            result = subprocess.run(
                [git, "check-ignore", "--stdin"],
                input="\n".join(paths),
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.stdout.strip(), "", f"{name}: git ignores theme assets (see .gitignore)")
