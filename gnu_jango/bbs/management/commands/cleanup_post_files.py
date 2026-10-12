import posixpath

from django.core.exceptions import SuspiciousFileOperation
from django.core.management.base import BaseCommand, CommandError

from gnu_jango import defaults
from gnu_jango.bbs.models import Post_file


def normalize_storage_name(name):
    return str(name or "").replace("\\", "/").strip("/")


def join_storage_name(root, name):
    return normalize_storage_name(
        posixpath.join(normalize_storage_name(root), normalize_storage_name(name))
    )


def iter_storage_files(storage, root):
    root = normalize_storage_name(root)
    stack = [root]
    visited = set()

    while stack:
        current = stack.pop()
        if current in visited:
            continue

        visited.add(current)

        try:
            directories, files = storage.listdir(current)
        except (FileNotFoundError, NotADirectoryError):
            continue
        except SuspiciousFileOperation as exc:
            raise CommandError(f"Cannot scan unsafe storage path '{current}': {exc}") from exc
        except NotImplementedError as exc:
            raise CommandError(
                f"Storage backend does not support listing '{current}'."
            ) from exc
        except OSError as exc:
            raise CommandError(f"Cannot scan storage path '{current}': {exc}") from exc

        for file_name in files:
            yield join_storage_name(current, file_name)

        for directory in directories:
            stack.append(join_storage_name(current, directory))


def get_referenced_file_names():
    return {
        normalize_storage_name(file_name)
        for file_name in Post_file.objects.exclude(bf_file="").values_list(
            "bf_file", flat=True
        )
        if file_name
    }


class Command(BaseCommand):
    help = "Find or remove stored BBS post files that are no longer referenced in the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete",
            action="store_true",
            help="Delete orphaned files. Without this option the command only reports them.",
        )
        parser.add_argument(
            "--include-missing",
            action="store_true",
            help="Also report database file references whose stored files are missing.",
        )

    def handle(self, *args, **options):
        storage = Post_file._meta.get_field("bf_file").storage
        root = normalize_storage_name(defaults.BBS_FILE_DIR)
        verbosity = int(options.get("verbosity", 1))

        referenced_files = get_referenced_file_names()
        stored_files = set(iter_storage_files(storage, root))
        orphaned_files = sorted(stored_files - referenced_files)

        if options["delete"]:
            deleted_count = self.delete_orphaned_files(storage, orphaned_files)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Deleted {deleted_count} orphaned post file(s) from '{root}'."
                )
            )
        else:
            self.stdout.write(
                f"Found {len(orphaned_files)} orphaned post file(s) under '{root}'."
            )
            if orphaned_files:
                self.stdout.write("Dry run only. Re-run with --delete to remove them.")

        if verbosity >= 2:
            for file_name in orphaned_files:
                self.stdout.write(f"  orphaned: {file_name}")

        if options["include_missing"]:
            missing_files = self.get_missing_files(storage, referenced_files)
            self.stdout.write(
                f"Found {len(missing_files)} missing referenced post file(s)."
            )
            if verbosity >= 2:
                for file_name in missing_files:
                    self.stdout.write(f"  missing: {file_name}")

    def delete_orphaned_files(self, storage, orphaned_files):
        deleted_count = 0

        for file_name in orphaned_files:
            try:
                storage.delete(file_name)
            except SuspiciousFileOperation as exc:
                raise CommandError(f"Cannot delete unsafe file '{file_name}': {exc}") from exc
            except OSError as exc:
                raise CommandError(f"Cannot delete file '{file_name}': {exc}") from exc

            deleted_count += 1

        return deleted_count

    def get_missing_files(self, storage, referenced_files):
        missing_files = []

        for file_name in sorted(referenced_files):
            try:
                if not storage.exists(file_name):
                    missing_files.append(file_name)
            except SuspiciousFileOperation as exc:
                raise CommandError(f"Cannot check unsafe file '{file_name}': {exc}") from exc
            except OSError as exc:
                raise CommandError(f"Cannot check file '{file_name}': {exc}") from exc

        return missing_files
