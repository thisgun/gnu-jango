"""G5_DEFAULT_THEME / G5_DEFAULT_DOCS_GROUP: a deployment picks its starting theme without a database row.

The handbook demo runs from the same repository as the main demo. It is a separate Vercel project
with its own empty database, so the theme it starts with has to come from its environment: nothing
may be written to that database before the first page can render. The defaults are read once when
gnu_jango.defaults is imported, so each case runs in a fresh interpreter.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROBE = (
    "import json, django; django.setup(); from gnu_jango import defaults; "
    "c = defaults.CONFIGS; print(json.dumps([c['cf_theme'][0], c['cf_docs_group'][0]]))"
)


def _configured_defaults(**env):
    clean = {k: v for k, v in os.environ.items() if not k.startswith("G5_DEFAULT_")}
    clean.update(DJANGO_SETTINGS_MODULE="example.settings", **env)
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=PROJECT_ROOT,
        env=clean,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return json.loads(result.stdout.strip().splitlines()[-1])


class DefaultThemeEnvTests(SimpleTestCase):
    def test_nothing_set_keeps_the_existing_defaults(self):
        self.assertEqual(_configured_defaults(), ["nextjs_default", ""])

    def test_theme_and_docs_group_come_from_the_environment(self):
        values = _configured_defaults(G5_DEFAULT_THEME="handbook", G5_DEFAULT_DOCS_GROUP="manual")
        self.assertEqual(values, ["handbook", "manual"])

    def test_blank_values_fall_back_to_the_defaults(self):
        values = _configured_defaults(G5_DEFAULT_THEME="  ", G5_DEFAULT_DOCS_GROUP="  ")
        self.assertEqual(values, ["nextjs_default", ""])
