#!/usr/bin/env python
"""Update the public, history-free snapshot of GNU Jango from a commit of the private branch.

The public repository (github.com/thisgun/gnu-jango) must never receive the private history: old commits
carry a personal e-mail address and the internal work log. This script copies the tree of one private
commit into a separate worktree on the orphan branch ``public-release``, drops the internal paths, scans
what would be published, and commits it as one new public commit. Nothing is pushed unless ``--push``
is given.

    python scripts/public_snapshot.py --dry-run          # show what would change, leave everything as is
    python scripts/public_snapshot.py                    # commit the snapshot locally
    python scripts/public_snapshot.py --push https://github.com/thisgun/gnu-jango.git
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

EXCLUDED_PATHS = ("docs/03-analysis", "docs/.pdca-status.json")
# personal addresses are not written here (this file is published too): every non-noreply author e-mail
# of the private history is looked up at run time
NOREPLY_SUFFIX = "users.noreply.github.com"
SELF_PATH = "scripts/public_snapshot.py"
SECRET_PATTERN = (
    r"(sk_live_|live_sk_|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|ghp_[A-Za-z0-9]{30,}"
    r"|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY"
    r"|SECRET_KEY\s*=\s*['\"][^'\"$]{20,}|client_secret\s*[=:]\s*['\"][A-Za-z0-9_-]{16,})"
)
SCAN_SKIP = (":!*.min.js", ":!gnu_jango/templates/theme_static/**")
# values that announce themselves as fakes (test fixtures, templates) are not secrets
PLACEHOLDER_MARKERS = re.compile(r"change-?me|unsafe|example|placeholder|dummy|not-a-real", re.IGNORECASE)


def git(*args, cwd, check=True):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")
    if check and result.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed:\n{result.stderr.strip()}")
    return result


def ensure_worktree(repo, worktree, branch, source):
    if (worktree / ".git").exists():
        current = git("rev-parse", "--abbrev-ref", "HEAD", cwd=worktree).stdout.strip()
        if current != branch:
            sys.exit(f"{worktree} is on '{current}', expected '{branch}'")
        if git("status", "--porcelain", cwd=worktree).stdout.strip():
            sys.exit(f"{worktree} has uncommitted changes; clean it first")
        return False
    git("worktree", "add", "--detach", str(worktree), source, cwd=repo)
    git("checkout", "-q", "--orphan", branch, cwd=worktree)
    return True


def personal_emails(repo):
    authors = git("log", "--all", "--format=%ae%n%ce", cwd=repo).stdout.split()
    return sorted({email for email in authors if "@" in email and not email.endswith(NOREPLY_SUFFIX)})


def scan_staged(worktree, personal_strings):
    problems = []
    for path in EXCLUDED_PATHS:
        if git("ls-files", "--cached", "--", path, cwd=worktree).stdout.strip():
            problems.append(f"internal path would be published: {path}")
    secrets = git(
        "grep", "--cached", "-n", "-I", "-E", SECRET_PATTERN, "--", ".", *SCAN_SKIP, f":!{SELF_PATH}",
        cwd=worktree, check=False,
    )
    problems += [
        f"possible secret: {line[:120]}"
        for line in secrets.stdout.splitlines()
        if not PLACEHOLDER_MARKERS.search(line)
    ]
    for text in personal_strings:
        hits = git("grep", "--cached", "-l", "-I", "-F", text, cwd=worktree, check=False)
        # report the file only, so the address itself is not echoed into logs
        problems += [f"personal e-mail address in: {path}" for path in hits.stdout.splitlines()]
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--source", default="HEAD", help="private commit to publish (default: HEAD)")
    parser.add_argument("--worktree", default=None, help="public worktree (default: ../gnu_jango_public)")
    parser.add_argument("--branch", default="public-release")
    parser.add_argument("--message", default=None, help="commit message for the public commit")
    parser.add_argument("--dry-run", action="store_true", help="report the changes and undo them")
    parser.add_argument("--push", metavar="URL", default=None, help="push the branch to URL as main")
    args = parser.parse_args()

    repo = Path(git("rev-parse", "--show-toplevel", cwd=Path.cwd()).stdout.strip())
    worktree = Path(args.worktree) if args.worktree else repo.parent / "gnu_jango_public"
    source = git("rev-parse", args.source, cwd=repo).stdout.strip()
    subject = git("log", "-1", "--format=%s", source, cwd=repo).stdout.strip()

    created = ensure_worktree(repo, worktree, args.branch, source)
    git("read-tree", "--reset", "-u", source, cwd=worktree)
    for path in EXCLUDED_PATHS:
        git("rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", path, cwd=worktree)
        subprocess.run(["git", "clean", "-fdqx", "--", path], cwd=worktree, check=False)

    problems = scan_staged(worktree, personal_emails(repo))
    has_head = git("rev-parse", "--verify", "-q", "HEAD", cwd=worktree, check=False).returncode == 0
    changed = not has_head or git("diff", "--cached", "--quiet", cwd=worktree, check=False).returncode != 0
    stat = git("diff", "--cached", "--stat", cwd=worktree, check=False).stdout.strip().splitlines() if has_head else []
    print(f"source {source[:9]} ({subject})")
    print(stat[-1] if stat else ("initial snapshot" if not has_head else "no changes"))

    if problems or args.dry_run or not changed:
        if has_head:
            git("read-tree", "--reset", "-u", "HEAD", cwd=worktree)
            subprocess.run(["git", "clean", "-fdq"], cwd=worktree, check=False)
        if problems:
            print("\n".join(problems))
            sys.exit("refusing to publish: fix the problems above")
        if created and not has_head:
            print(f"worktree {worktree} created on {args.branch}; run again without --dry-run to commit")
        return

    message = args.message or f"Update from upstream ({subject})"
    git("commit", "-q", "-m", message, cwd=worktree)
    print(f"committed {git('rev-parse', '--short', 'HEAD', cwd=worktree).stdout.strip()} on {args.branch}")
    if args.push:
        result = git("push", args.push, f"{args.branch}:main", cwd=worktree)
        print(result.stderr.strip() or result.stdout.strip())


if __name__ == "__main__":
    main()
