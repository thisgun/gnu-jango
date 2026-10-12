"""Install the theme archive and rehearse admin switching in an isolated local clone."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_NAME = "nextjs-default-theme"
THEME_DIRS = ("theme/nextjs_default", "theme_static/nextjs_default")
RUNTIME_TABLES = {"django_session", "sqlite_sequence", "gnu_jango_visit_log"}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def inside(root, path):
    root, path = root.resolve(), path.resolve()
    if path == root or not path.is_relative_to(root):
        raise RuntimeError("Refusing a filesystem mutation outside the rehearsal root.")
    return path


def database_snapshot(path):
    """Compare business rows, allowing session, visit-log and read-counter changes."""
    result = {}
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        names = connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        for (name,) in names:
            if name in RUNTIME_TABLES:
                continue
            quoted = '"' + name.replace('"', '""') + '"'
            fields = connection.execute("PRAGMA table_info(" + quoted + ")").fetchall()
            columns = [row[1] for row in fields if row[1] not in {"wr_hit", "it_hit", "last_login"}]
            selected = ", ".join('"' + field.replace('"', '""') + '"' for field in columns)
            query = "SELECT " + selected + " FROM " + quoted
            if name == "gnu_jango_config":
                query += " WHERE name != 'cf_theme'"
            query += " ORDER BY " + selected
            rows = connection.execute(query).fetchall()
            serialized = json.dumps(rows, ensure_ascii=False, default=str).encode()
            result[name] = {"rows": len(rows), "sha256": hashlib.sha256(serialized).hexdigest()}
    return result


def clone_ignore(path, names):
    ignored = {name for name in names if name in {"__pycache__", ".pytest_cache"}}
    if Path(path).name in {"theme", "theme_static"}:
        ignored.update({"nextjs_default", "nextjs25"})
    return ignored


def extract_verified_archive(archive, destination):
    checksum_path = Path(str(archive) + ".sha256")
    expected = checksum_path.read_text(encoding="utf-8").split()[0]
    if digest(archive) != expected:
        raise RuntimeError("Archive SHA-256 does not match its sidecar.")
    destination.mkdir()
    extracted = {}
    # Read the compressed archive once and hash the bytes while writing them.
    with tarfile.open(archive, "r|gz") as bundle:
        for member in bundle:
            target = destination / member.name
            inside(destination, target)
            if not (member.isfile() or member.isdir()):
                raise RuntimeError("The archive must contain only directories and regular files.")
            if Path(member.name).parts[0] != PACKAGE_NAME:
                raise RuntimeError("Unexpected package root.")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            value = hashlib.sha256()
            size = 0
            with bundle.extractfile(member) as source, target.open("wb") as output:
                for block in iter(lambda: source.read(1024 * 1024), b""):
                    value.update(block)
                    output.write(block)
                    size += len(block)
            if size != member.size:
                raise RuntimeError("Truncated archive member.")
            relative = target.relative_to(destination / PACKAGE_NAME).as_posix()
            if relative in extracted:
                raise RuntimeError("Duplicate archive member.")
            extracted[relative] = {"sha256": value.hexdigest(), "size": size}
    package = destination / PACKAGE_NAME
    manifest = json.loads((package / "MANIFEST.json").read_text(encoding="utf-8"))
    files = {
        path.removeprefix("upload/"): item["sha256"]
        for path, item in extracted.items() if path.startswith("upload/")
    }
    if manifest["theme"] != "nextjs_default" or len(files) != manifest["fileCount"]:
        raise RuntimeError("Manifest theme or file count does not match the package.")
    listed = {}
    for item in manifest["files"]:
        if not item["path"].startswith(("upload/theme/nextjs_default/", "upload/theme_static/nextjs_default/")):
            raise RuntimeError("Unexpected theme payload path.")
        listed[item["path"].removeprefix("upload/")] = item["sha256"]
        if extracted.get(item["path"]) != {"size": item["size"], "sha256": item["sha256"]}:
            raise RuntimeError("A packaged file does not match its manifest.")
    if files != listed:
        raise RuntimeError("Packaged payload file list does not match the manifest.")
    for line in (package / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines():
        expected_file_hash, relative = line.split("  ", 1)
        if extracted.get(relative, {}).get("sha256") != expected_file_hash:
            raise RuntimeError("A packaged file does not match CHECKSUMS.sha256.")
    return package, manifest, expected


def write_payload(archive, templates, expected, *, group=None, snapshot=None):
    """Hash streamed input and write exactly those bytes to the isolated target."""
    written = {}
    backup = tarfile.open(snapshot, "w") if snapshot else None
    try:
        with tarfile.open(archive, "r|gz") as bundle:
            for member in bundle:
                prefix = PACKAGE_NAME + "/upload/"
                if not member.isfile() or not member.name.startswith(prefix):
                    continue
                relative = member.name.removeprefix(prefix)
                if group and not relative.startswith(group + "/"):
                    continue
                if relative not in expected:
                    raise RuntimeError("Unexpected deployment payload.")
                content = bundle.extractfile(member).read()
                if hashlib.sha256(content).hexdigest() != expected[relative]:
                    raise RuntimeError("Payload changed after archive validation.")
                if snapshot and relative == "theme/nextjs_default/sw.js":
                    content += b"\n/* Isolated prior-release snapshot. */\n"
                target = inside(templates, templates / relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.write_bytes(content) != len(content):
                    raise RuntimeError("Incomplete deployment write.")
                written[relative] = hashlib.sha256(content).hexdigest()
                if backup:
                    info = tarfile.TarInfo(relative)
                    info.size = len(content)
                    backup.addfile(info, io.BytesIO(content))
        if backup:
            markers = {
                "theme/nextjs_default/rehearsal-prior-release.txt": b"Previous isolated release\n",
                "theme_static/nextjs_default/_next/static/css/rehearsal-prior.css":
                    b"/* Retained previous release asset. */\n",
            }
            for relative, content in markers.items():
                target = inside(templates, templates / relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
                info = tarfile.TarInfo(relative)
                info.size = len(content)
                backup.addfile(info, io.BytesIO(content))
                written[relative] = hashlib.sha256(content).hexdigest()
    finally:
        if backup:
            backup.close()
    return written


def restore_snapshot(snapshot, templates):
    written = {}
    with tarfile.open(snapshot, "r|") as bundle:
        for member in bundle:
            if not member.isfile():
                raise RuntimeError("Unexpected rollback member.")
            target = inside(templates, templates / member.name)
            content = bundle.extractfile(member).read()
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.write_bytes(content) != len(content):
                raise RuntimeError("Incomplete rollback write.")
            written[member.name] = hashlib.sha256(content).hexdigest()
    return written


def run_browser(stage, origin, phase, credentials, routes, file_hashes):
    payload = {
        "origin": origin,
        "phase": phase,
        "username": credentials["username"],
        "password": credentials["password"],
        "profileRoot": str(stage / "browser-profile"),
        "reportPath": str(stage / (phase + ".json")),
        "screenshotRoot": str(stage),
        "routes": routes,
        "fileHashes": file_hashes,
    }
    subprocess.run(
        ["node", str(REPO_ROOT / "nextjs/scripts/check-theme-rehearsal.mjs")],
        input=json.dumps(payload),
        text=True,
        check=True,
        cwd=REPO_ROOT / "nextjs",
    )
    return json.loads((stage / (phase + ".json")).read_text(encoding="utf-8"))


def run(args):
    archive = args.archive.resolve()
    source_database = args.database.resolve()
    if not source_database.is_file():
        raise RuntimeError("Source SQLite database does not exist.")
    stage_parent = REPO_ROOT / ".tmp-nextjs-runtime"
    stage_parent.mkdir(exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix="staging-", dir=stage_parent))
    print("[theme-rehearsal] Isolated workspace: " + str(stage), flush=True)
    source_hash = digest(source_database)
    _, manifest, archive_hash = extract_verified_archive(archive, stage / "archive")
    expected_payload = {
        item["path"].removeprefix("upload/"): item["sha256"] for item in manifest["files"]
    }
    print("[theme-rehearsal] Archive, manifest, and file checksums verified.", flush=True)
    project = stage / "project"
    project.mkdir()
    for name in ("example", "gnu_jango"):
        shutil.copytree(REPO_ROOT / name, project / name, ignore=clone_ignore)
    shutil.copy2(REPO_ROOT / "manage.py", project / "manage.py")
    # Stop python-decouple searching parent directories for the working site's .env.
    (project / ".env").write_text("ENVIRONMENT=Development\n", encoding="utf-8")
    database = project / "db.sqlite3"
    with sqlite3.connect(source_database.as_uri() + "?mode=ro", uri=True) as source:
        with sqlite3.connect(database) as target:
            source.backup(target)
    templates = project / "gnu_jango/templates"
    backup = stage / "previous-release.tar"
    backup_hashes = write_payload(archive, templates, expected_payload, snapshot=backup)
    backup_archive_hash = digest(backup)
    old_asset = templates / "theme_static/nextjs_default/_next/static/css/rehearsal-prior.css"
    print("[theme-rehearsal] Project, SQLite clone, and paired rollback snapshot prepared.", flush=True)
    settings_file = project / "example/settings/theme_rehearsal.py"
    settings_file.write_text(
        "from .development import *\n"
        "DEBUG = False\n"
        "ALLOWED_HOSTS = ['127.0.0.1', 'localhost']\n"
        "DATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', "
        "'NAME': BASE_DIR / 'db.sqlite3', 'OPTIONS': {'timeout': 30}}}\n"
        "MEDIA_ROOT = BASE_DIR / 'media'\n"
        "LEGACY_GNUBOARD5_SOURCE_ROOTS = [str(MEDIA_ROOT)]\n"
        "CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}\n"
        "MAILERS = {'default': {'BACKEND': 'django.core.mail.backends.locmem.EmailBackend'}}\n"
        "SENTRY_DSN = ''\n"
        "SHOP_PAYMENT_PROVIDER = ''\n"
        "SECURE_SSL_REDIRECT = False\n"
        "SESSION_COOKIE_NAME = 'theme_rehearsal_session'\n"
        "CSRF_COOKIE_NAME = 'theme_rehearsal_csrf'\n",
        encoding="utf-8",
    )
    (project / "example/theme_rehearsal_urls.py").write_text(
        "from example.urls import urlpatterns as application_patterns\n"
        "from django.conf import settings\n"
        "from django.urls import re_path\n"
        "from django.views.static import serve\n"
        "urlpatterns = [re_path(r'^media/(?P<path>.*)$', serve, "
        "{'document_root': settings.MEDIA_ROOT})] + application_patterns\n",
        encoding="utf-8",
    )
    with settings_file.open("a", encoding="utf-8") as stream:
        stream.write("ROOT_URLCONF = 'example.theme_rehearsal_urls'\n")
    if (REPO_ROOT / "media").is_dir():
        shutil.copytree(REPO_ROOT / "media", project / "media")
    else:
        (project / "media").mkdir()
    (project / "staticfiles").mkdir()
    credentials = {"username": "theme_stage_" + secrets.token_hex(5), "password": secrets.token_urlsafe(24)}
    environment = os.environ.copy()
    environment.update({
        "DJANGO_SETTINGS_MODULE": "example.settings.theme_rehearsal",
        "ENVIRONMENT": "Development",
        "DATABASE_URL": "",
        "DB_ENGINE": "",
        "SECRET_KEY": secrets.token_urlsafe(48),
        "SENTRY_DSN": "",
        "EMAIL_BACKEND": "django.core.mail.backends.locmem.EmailBackend",
        "THEME_STAGE_USERNAME": credentials["username"],
        "THEME_STAGE_PASSWORD": credentials["password"],
        "PYTHONUNBUFFERED": "1",
    })
    seed = r"""
import django, json, os
django.setup()
from django.contrib.auth import get_user_model
from gnu_jango.config.models import Config
from gnu_jango.bbs.models import Board, Post
from gnu_jango.shop.models import ShopProduct
get_user_model().objects.create_superuser(
    username=os.environ["THEME_STAGE_USERNAME"],
    email=os.environ["THEME_STAGE_USERNAME"] + "@example.invalid",
    password=os.environ["THEME_STAGE_PASSWORD"],
)
Config.objects.update_or_create(name="cf_theme", defaults={"value": "basic"})
board = Board.objects.filter(bo_table="free").first() or Board.objects.first()
post = Post.objects.filter(board=board, wr_reply="").exclude(wr_option__icontains="secret").first()
product = ShopProduct.objects.filter(it_use="1").first()
if not post or not product:
    raise RuntimeError("Rehearsal requires an existing public post and active product.")
print(json.dumps({"board": "/" + board.bo_table,
                  "post": "/" + board.bo_table + "/" + str(post.wr_parent or post.pk),
                  "postTitle": post.wr_subject,
                  "product": "/shop/" + product.it_id,
                  "productTitle": product.it_name}))
"""
    seed_output = subprocess.check_output(
        [sys.executable, "-c", seed], cwd=project, env=environment, text=True
    )
    routes = json.loads(seed_output.strip().splitlines()[-1])
    baseline_database = database_snapshot(database)
    (stage / "database-before.json").write_text(
        json.dumps(baseline_database, indent=2) + "\n", encoding="utf-8"
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", args.port))
        port = listener.getsockname()[1]
    origin = "http://127.0.0.1:" + str(port)
    server = None
    log_path = stage / "server.log"
    try:
        with log_path.open("w", encoding="utf-8") as log:
            server = subprocess.Popen(
                [sys.executable, "manage.py", "runserver", "127.0.0.1:" + str(port),
                 "--noreload", "--insecure"],
                cwd=project, env=environment, stdout=log, stderr=subprocess.STDOUT,
            )
        for attempt in range(60):
            if server.poll() is not None:
                raise RuntimeError("Isolated server stopped. Inspect " + str(log_path))
            try:
                readiness = Request(origin + "/", headers={"User-Agent": "GNUThemeRehearsal monitoring"})
                with urlopen(readiness, timeout=2) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError):
                time.sleep(0.5)
        else:
            raise RuntimeError("Isolated server did not become ready.")
        print("[theme-rehearsal] Server ready: " + origin, flush=True)
        baseline = run_browser(stage, origin, "baseline", credentials, routes, backup_hashes)
        # Publish assets first, retaining previous hashed files for cached HTML.
        installed = write_payload(archive, templates, expected_payload, group="theme_static")
        html_target = inside(stage, templates / "theme/nextjs_default")
        html_target.rename(inside(stage, stage / "displaced-html"))
        installed.update(write_payload(archive, templates, expected_payload, group="theme"))
        if installed != expected_payload:
            raise RuntimeError("Installed payload differs from package.")
        if not old_asset.is_file():
            raise RuntimeError("Deployment removed a previous hashed asset.")
        deployed = run_browser(stage, origin, "deployed", credentials, routes, installed)
        # Restore both directories from the same snapshot before selecting basic.
        for index, relative in enumerate(THEME_DIRS):
            target = inside(stage, templates / relative)
            target.rename(inside(stage, stage / ("displaced-deployed-" + str(index))))
        if digest(backup) != backup_archive_hash:
            raise RuntimeError("The paired rollback snapshot changed.")
        restored_files = restore_snapshot(backup, templates)
        if restored_files != backup_hashes:
            raise RuntimeError("Restored theme bytes differ from the snapshot.")
        actual_files = {
            path.relative_to(templates).as_posix()
            for relative in THEME_DIRS for path in (templates / relative).rglob("*")
            if path.is_file()
        }
        if actual_files != set(backup_hashes):
            raise RuntimeError("Restored theme file list differs from the snapshot.")
        restored = run_browser(stage, origin, "restored", credentials, routes, restored_files)
        if baseline["serviceWorkerSha256"] == deployed["serviceWorkerSha256"]:
            raise RuntimeError("Deployment did not replace the prior service worker.")
        if baseline["serviceWorkerSha256"] != restored["serviceWorkerSha256"]:
            raise RuntimeError("Rollback did not restore the prior service worker.")
        final_database = database_snapshot(database)
        (stage / "database-after.json").write_text(
            json.dumps(final_database, indent=2) + "\n", encoding="utf-8"
        )
        changed_tables = sorted(name for name in set(baseline_database) | set(final_database)
                                if baseline_database.get(name) != final_database.get(name))
        if changed_tables:
            raise RuntimeError("Business data changed during theme deployment or rollback: " +
                               ", ".join(changed_tables))
        if digest(source_database) != source_hash:
            raise RuntimeError("Source database changed during rehearsal; inspect concurrent activity.")
        report = {
            "status": "passed", "origin": origin, "isolatedProject": str(project),
            "sourceCommit": manifest["sourceCommit"], "archiveSha256": archive_hash,
            "themeFiles": manifest["fileCount"], "rollbackFiles": len(backup_hashes),
            "businessDataPreserved": True, "sourceDatabaseUnchanged": True,
            "excludedRuntimeTables": sorted(RUNTIME_TABLES),
            "excludedRuntimeColumns": ["wr_hit", "it_hit", "last_login"],
            "excludedConfigRow": "cf_theme",
            "applicationFilesSha256": {
                relative: digest(project / relative)
                for relative in ("gnu_jango/core/middleware.py", "gnu_jango/core/views.py")
            },
            "baseline": baseline, "deployed": deployed, "restored": restored,
        }
        (stage / "REPORT.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("[theme-rehearsal] PASS: install, admin switch, paired rollback, browser routes, and data preservation.")
        print("[theme-rehearsal] Report: " + str(stage / "REPORT.json"))
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        if server is not None:
            print("[theme-rehearsal] Isolated server stopped (exit " + str(server.returncode) + ").")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=REPO_ROOT / "nextjs/.deploy/nextjs-default-theme.tar.gz")
    parser.add_argument("--database", type=Path, default=REPO_ROOT / "db.sqlite3")
    parser.add_argument("--port", type=int, default=0, help="Loopback port; zero selects an unused port.")
    options = parser.parse_args()
    try:
        run(options)
    except Exception as error:
        print("[theme-rehearsal] FAIL: " + str(error), file=sys.stderr)
        sys.exit(1)
