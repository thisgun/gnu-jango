"""requirements.txt must stay self-contained and in step with requirements-base.txt.

Vercel's Python builder and the Docker image install requirements.txt directly and cannot follow a
`-r` include (Vercel: PYTHON_REQUIREMENTS_PARSE_ERROR; Docker copies only that one file), so the
root file repeats the base list plus S3 support. PythonAnywhere installs
requirements-pythonanywhere.txt, which includes requirements-base.txt.
"""

from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[2]
# Names only: Dependabot bumps these pins in requirements.txt, so the test must not repeat the versions.
S3_ONLY = {"django-storages[s3]", "boto3"}


def _requirement_lines(name):
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    return [line.split("#", 1)[0].strip() for line in lines if line.split("#", 1)[0].strip()]


def _name(line):
    return line.split("==", 1)[0].strip()


class RequirementsFilesTests(SimpleTestCase):
    def test_the_root_file_has_no_includes(self):
        self.assertFalse([line for line in _requirement_lines("requirements.txt") if line.startswith("-")])

    def test_the_root_file_is_the_base_list_plus_s3(self):
        root = _requirement_lines("requirements.txt")
        s3 = [line for line in root if _name(line) in S3_ONLY]
        self.assertEqual({line for line in root if _name(line) not in S3_ONLY}, set(_requirement_lines("requirements-base.txt")))
        self.assertEqual({_name(line) for line in s3}, S3_ONLY)
        self.assertTrue(all("==" in line for line in s3), s3)

    def test_pythonanywhere_installs_the_base_list(self):
        self.assertEqual(_requirement_lines("requirements-pythonanywhere.txt"), ["-r requirements-base.txt"])
