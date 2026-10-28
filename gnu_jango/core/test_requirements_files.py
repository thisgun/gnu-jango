"""requirements.txt must stay self-contained and in step with requirements-base.txt.

Vercel's Python builder and the Docker image install requirements.txt directly and cannot follow a
`-r` include (Vercel: PYTHON_REQUIREMENTS_PARSE_ERROR; Docker copies only that one file), so the
root file repeats the base list plus S3 support. PythonAnywhere installs
requirements-pythonanywhere.txt, which includes requirements-base.txt.
"""

from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
S3_ONLY = {"django-storages[s3]==1.14.6", "boto3==1.43.118"}


def _requirement_lines(name):
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    return [line.split("#", 1)[0].strip() for line in lines if line.split("#", 1)[0].strip()]


class RequirementsFilesTests(SimpleTestCase):
    def test_the_root_file_has_no_includes(self):
        self.assertFalse([line for line in _requirement_lines("requirements.txt") if line.startswith("-")])

    def test_the_root_file_is_the_base_list_plus_s3(self):
        self.assertEqual(set(_requirement_lines("requirements.txt")), set(_requirement_lines("requirements-base.txt")) | S3_ONLY)

    def test_pythonanywhere_installs_the_base_list(self):
        self.assertEqual(_requirement_lines("requirements-pythonanywhere.txt"), ["-r requirements-base.txt"])
