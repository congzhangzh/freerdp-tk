"""The plain-Python steps of .github/workflows/client-bump.yml: a green kit release
reaches freerdp-tk without a person.

    python scripts/client_bump.py same-client OLD_LOCK    # exit 0: client.lock pins the same client
    python scripts/client_bump.py notes RELEASE FREERDP   # the Unreleased "Under the hood" line
    python scripts/client_bump.py client-only             # exit 0: only bumps since the last tag
    python scripts/client_bump.py next-tag                # prints yyyymmdd.N
    python scripts/client_bump.py date-notes TAG          # "## Unreleased" becomes "## TAG"
    python scripts/client_bump.py unpack DIR              # the locked linux-x86_64 client into DIR

A bump commit touches client.lock and, in RELEASE_NOTES.md, only the Unreleased
heading and its bump line. "Client-only" means every commit since the last dated
tag is one: then the bump publishes itself (聪哥, 2026-11-15); anything else since
the tag waits for his go. Standard library only.
"""

import argparse
import datetime
import hashlib
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bundle_client  # noqa: E402  (beside this file)

ROOT = Path(__file__).resolve().parent.parent
NOTES = ROOT / "src" / "freerdp_tk" / "RELEASE_NOTES.md"
UNRELEASED = "## Unreleased"
BUMP_LINE = "- Under the hood: the bundled client is FreeRDP {freerdp} (rdp-release-kit {release})."
BUMP_RE = re.compile(r"- Under the hood: the bundled client is FreeRDP \S+ \(rdp-release-kit \S+\)\.$")
TAG_RE = re.compile(r"^(\d{8})\.(\d+)$")
VERSION_RE = re.compile(r"^\d{8}\.\d+$")  # a kit release and a FreeRDP version look alike
BUMP_FILES = {"client.lock", "src/freerdp_tk/RELEASE_NOTES.md"}


def same_client(old: Path, new: Path) -> bool:
    """The two locks pin the same client: the same file names, which carry the FreeRDP
    version (sdl3-freerdp-<version>-<platform>). Not the SHA-256s: the kit builds its
    archives again every round, not byte for byte the same, so a round that changed
    only its pages or demos has new hashes for the very client freerdp-tk has, and
    must not make a freerdp-tk release (20261115.3 was one, rel-rdp-g1, 2026-11-15).
    A rebuild of one FreeRDP version with other libraries waits for the next version."""
    return set(bundle_client.read_lock(old)) == set(bundle_client.read_lock(new))


def with_bump(text: str, release: str, freerdp: str) -> str:
    """The notes with this bump's line under "## Unreleased": the section is made
    above the newest release when there is none, and an older bump line in it is
    replaced, so one Unreleased section names one client."""
    line = BUMP_LINE.format(freerdp=freerdp, release=release)
    lines = text.splitlines()
    if UNRELEASED not in lines:
        first = next((i for i, s in enumerate(lines) if s.startswith("## ")), len(lines))
        lines[first:first] = [UNRELEASED, "", line, ""]
        return "\n".join(lines) + "\n"
    start = lines.index(UNRELEASED) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = [s for s in lines[start:end] if not BUMP_RE.match(s)]
    while section and not section[-1].strip():
        section.pop()
    section = [*section, line] if any(s.strip() for s in section) else ["", line]
    lines[start:end] = [*section, ""]
    return "\n".join(lines) + "\n"


def dated(text: str, tag: str) -> str:
    lines = text.splitlines()
    if UNRELEASED not in lines:
        sys.exit(f"no '{UNRELEASED}' section to date")
    lines[lines.index(UNRELEASED)] = f"## {tag}"
    return "\n".join(lines) + "\n"


def next_tag(tags: list[str], today: str) -> str:
    """The next dated tag: today's next index, never below the newest tag (a tag dated
    ahead of this clock, by a person in another time zone, must stay older)."""
    dates = sorted({m[1] for t in tags if (m := TAG_RE.match(t))} | {today})
    day = dates[-1]
    index = max((int(m[2]) for t in tags if (m := TAG_RE.match(t)) and m[1] == day), default=0)
    return f"{day}.{index + 1}"


def is_bump_change(files: set[str], notes_diff: list[str]) -> bool:
    """A commit that only bumps the client: its files, and its changed notes lines."""
    if not files or not files <= BUMP_FILES:
        return False
    for line in notes_diff:
        if line.startswith(("+++", "---")) or not line.startswith(("+", "-")):
            continue
        body = line[1:]
        if body.strip() and body != UNRELEASED and not BUMP_RE.match(body):
            return False
    return True


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True,
                          text=True).stdout


def last_tag() -> str | None:
    tags = [t for t in git("tag", "--merged", "HEAD").split() if TAG_RE.match(t)]
    return max(tags, key=lambda t: tuple(map(int, t.split(".")))) if tags else None


def client_only() -> tuple[bool, str]:
    tag = last_tag()
    if not tag:
        return False, "no dated tag to compare with"
    commits = git("rev-list", f"{tag}..HEAD").split()
    if not commits:
        return False, f"nothing since {tag}"
    for sha in commits:
        files = set(git("diff-tree", "--no-commit-id", "--name-only", "-r", sha).split())
        diff = git("show", "--format=", "-U0", sha, "--", "src/freerdp_tk/RELEASE_NOTES.md")
        if not is_bump_change(files, diff.splitlines()):
            subject = git("log", "-1", "--format=%h %s", sha).strip()
            return False, f"{subject} is not a client bump (since {tag})"
    return True, f"{len(commits)} bump commit(s) since {tag}"


def unpack(dest: Path) -> Path:
    """The client client.lock pins for linux x86_64, as a wheel would carry it."""
    lock = bundle_client.read_lock()
    end = bundle_client.PLATFORMS["manylinux_2_34_x86_64"]
    name = next(n for n in lock if n.endswith(end))
    data = bundle_client.fetch(f"{bundle_client.KIT}/{bundle_client.lock_release()}/{name}")
    if hashlib.sha256(data).hexdigest() != lock[name]:
        sys.exit(f"{name}: not the file client.lock pins")
    client = bundle_client.archive_files(data, name)["bin/sdl-freerdp"]
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "sdl-freerdp"
    path.write_bytes(client)
    path.chmod(0o755)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.partition("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    same = sub.add_parser("same-client")
    same.add_argument("old", type=Path)
    notes = sub.add_parser("notes")
    notes.add_argument("release")
    notes.add_argument("freerdp")
    sub.add_parser("client-only")
    sub.add_parser("next-tag")
    date = sub.add_parser("date-notes")
    date.add_argument("tag")
    up = sub.add_parser("unpack")
    up.add_argument("dest", type=Path)
    args = parser.parse_args()
    if args.command == "same-client":
        sys.exit(0 if same_client(args.old, bundle_client.LOCK) else 1)
    if args.command == "notes":
        for value in (args.release, args.freerdp):
            if not VERSION_RE.match(value):
                sys.exit(f"not a yyyymmdd.N version: {value!r}")
        NOTES.write_text(with_bump(NOTES.read_text(encoding="utf-8"), args.release,
                                   args.freerdp), encoding="utf-8")
    elif args.command == "client-only":
        ok, why = client_only()
        print(why)
        sys.exit(0 if ok else 1)
    elif args.command == "next-tag":
        today = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        print(next_tag(git("tag").split(), today))
    elif args.command == "date-notes":
        if not TAG_RE.match(args.tag):
            sys.exit(f"not a dated tag: {args.tag!r}")
        NOTES.write_text(dated(NOTES.read_text(encoding="utf-8"), args.tag), encoding="utf-8")
    else:
        print(unpack(args.dest))


if __name__ == "__main__":
    main()
