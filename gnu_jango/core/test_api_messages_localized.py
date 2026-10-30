"""Every fixed English API error message has a Korean entry in the front end.

The API answers in English and the Next.js client shows messages as received, so a message
missing from nextjs/src/lib/api-messages.ts reaches Korean visitors untranslated.
"""

import ast
import re
from pathlib import Path

from django.test import SimpleTestCase

API_DIR = Path(__file__).resolve().parents[1] / "api"
SHOP_DIR = Path(__file__).resolve().parents[1] / "shop"
MESSAGES_TS = Path(__file__).resolve().parents[2] / "nextjs" / "src" / "lib" / "api-messages.ts"
SKIPPED_MODULES = set()
ERROR_CALLS = {"api_error", "StockAdjustmentError", "SubscriptionError"}


def _has_hangul(text):
    return any("가" <= char <= "힣" for char in text)


def api_messages():
    messages = set()
    for path in [*API_DIR.glob("*.py"), SHOP_DIR / "inventory.py", SHOP_DIR / "subscriptions.py"]:
        if path.name in SKIPPED_MODULES:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            first = node.args[0]
            if name in ERROR_CALLS and isinstance(first, ast.Constant) and isinstance(first.value, str) and not _has_hangul(first.value):
                messages.add(first.value)
    return messages


def translated_messages():
    source = MESSAGES_TS.read_text(encoding="utf-8")
    return set(re.findall(r'^\s*"([^"]+)":', source, flags=re.MULTILINE))


class ApiMessagesLocalizedTests(SimpleTestCase):
    def test_every_english_api_message_has_a_korean_entry(self):
        missing = sorted(api_messages() - translated_messages())
        self.assertEqual(missing, [], "Add these to nextjs/src/lib/api-messages.ts")

    def test_translated_entries_are_korean(self):
        source = MESSAGES_TS.read_text(encoding="utf-8")
        pairs = re.findall(r'^\s*"([^"]+)":\s*"([^"]+)",', source, flags=re.MULTILINE)
        self.assertGreater(len(pairs), 100)
        english_only = [english for english, korean in pairs if not _has_hangul(korean)]
        self.assertEqual(english_only, [])
