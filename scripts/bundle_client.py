"""Make one wheel per platform with the FreeRDP SDL client inside.

    uv build
    python scripts/bundle_client.py dist/freerdp_tk-*-any.whl     # adds the wheels to dist/
    python scripts/bundle_client.py --pin 20261106.3              # bump client.lock

uvx then needs nothing else: an installer takes the wheel of its platform, and
any platform without one (musl, glibc older than 2.34, a BSD) still gets the
plain wheel, which finds the client on PATH as before.

The clients are the portable builds of rdp-release-kit: one self-contained
program each, so nothing has to be repaired the way auditwheel or delocate do
for a program that loads libraries next to it. client.lock pins the release and
the SHA-256 of every file, and a file that does not match stops the build. The
plain wheel is repacked rather than built again, so `uv build` stays pure and a
source checkout never holds a binary. Standard library only.
"""

import argparse
import base64
import hashlib
import io
import re
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

KIT = "https://github.com/congzhangzh/rdp-release-kit/releases/download"
LOCK = Path(__file__).resolve().parent.parent / "client.lock"
# wheel platform tag: the end of the kit's file name. The floors are the kit's
# own: glibc 2.34 (built on AlmaLinux 9) and macOS 12.
PLATFORMS = {
    "manylinux_2_34_x86_64": "linux-x86_64.tar.xz",
    "manylinux_2_34_aarch64": "linux-aarch64.tar.xz",
    "macosx_12_0_x86_64": "macos-x86_64.tar.xz",
    "macosx_12_0_arm64": "macos-arm64.tar.xz",
    "win_amd64": "windows-x86_64.zip",
    "win_arm64": "windows-aarch64.zip",
}
# The kit's licenses/ also covers the Python and the freerdp-tk it ships, which
# do not come along here: uv brings the Python, the wheel is freerdp-tk itself.
NOT_THE_CLIENT = re.compile(r"(python_|freerdp_tk)")
ZIP_TIME = (2020, 1, 1, 0, 0, 0)  # the same input gives the same wheel


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=300) as response:
        return response.read()


def read_lock(path: Path = LOCK) -> dict[str, str]:
    """{file name: SHA-256} of the kit's files."""
    pairs = (line.split() for line in path.read_text().splitlines()
             if line.strip() and not line.startswith("#"))
    return {name: sha for sha, name in pairs}


def lock_release(path: Path = LOCK) -> str:
    """The kit release the files come from: its `# release` line. The file names
    carry the FreeRDP version, which is not the kit's release (sdl3-freerdp-20261111.4
    is in release 20261112.1); a lock without the line is from when they were one."""
    for line in path.read_text().splitlines():
        if line.startswith("# release "):
            return line.split()[2]
    return next(iter(read_lock(path))).split("-")[2]


def pin(version: str) -> None:
    sums = fetch(f"{KIT}/{version}/SHA256SUMS").decode()
    ends = tuple(PLATFORMS.values())
    lines = [line for line in sums.splitlines()
             if line.split()[-1].startswith("sdl3-freerdp-") and line.endswith(ends)]
    if len(lines) != len(PLATFORMS):
        sys.exit(f"release {version} has {len(lines)} clients, not {len(PLATFORMS)}")
    head = LOCK.read_text().partition("\n\n")[0].rstrip()
    LOCK.write_text(head + "\n\n" + f"# release {version}\n"
                    + "\n".join(sorted(lines, key=lambda s: s.split()[1])) + "\n")
    print(f"{LOCK.name}: release {version}")


def archive_members(data: bytes, name: str):
    """(path, contents) of every file in a kit archive."""
    if name.endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if not info.is_dir():
                    yield info.filename, z.read(info)
    else:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as t:
            for member in t:
                if member.isfile():
                    yield member.name, t.extractfile(member).read()


def archive_files(data: bytes, name: str) -> dict[str, bytes]:
    """Every file of a kit archive that belongs to the client, with paths
    relative to the archive's one top folder."""
    wanted = re.compile(r"[^/]+/((?:bin/)?sdl-freerdp(?:\.exe)?|MANIFEST|licenses/.+)$")
    found = {}
    for path, contents in archive_members(data, name):
        match = wanted.match(path)
        if match and not NOT_THE_CLIENT.match(match[1].removeprefix("licenses/")):
            found[match[1]] = contents
    return found


def record_line(path: str, data: bytes) -> str:
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
    return f"{path},sha256={digest},{len(data)}"


def bundle(wheel: Path, tag: str, files: dict[str, bytes], out: Path) -> Path:
    """The wheel again, tagged for one platform, with the client in
    freerdp_tk/client/ (package data: a program in the wheel's scripts would make
    `uv tool install` refuse to overwrite an sdl-freerdp in ~/.local/bin)."""
    name, version = wheel.name.split("-")[:2]
    info = f"{name}-{version}.dist-info"
    target = out / f"{name}-{version}-py3-none-{tag}.whl"
    programs = [p for p in files if Path(p).stem == "sdl-freerdp"]
    if len(programs) != 1:
        sys.exit(f"{tag}: expected one client, found {programs}")
    with zipfile.ZipFile(wheel) as z:
        entries = {i.filename: z.read(i) for i in z.infolist()
                   if i.filename != f"{info}/RECORD"}
    text = entries[f"{info}/WHEEL"].decode()
    text = re.sub(r"^Tag: .*$", f"Tag: py3-none-{tag}", text, flags=re.MULTILINE)
    entries[f"{info}/WHEEL"] = text.replace("Root-Is-Purelib: true",
                                            "Root-Is-Purelib: false").encode()
    client = {"freerdp_tk/client/" + Path(path).name if path in programs
              else "freerdp_tk/client/" + path: data for path, data in files.items()}
    executable = f"freerdp_tk/client/{Path(programs[0]).name}"
    ordered = [*sorted(p for p in {**entries, **client} if not p.startswith(info)),
               *sorted(p for p in entries if p.startswith(info))]
    merged = {**entries, **client}
    record = [record_line(p, merged[p]) for p in ordered] + [f"{info}/RECORD,,"]
    merged[f"{info}/RECORD"] = ("\n".join(record) + "\n").encode()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in [*ordered, f"{info}/RECORD"]:
            entry = zipfile.ZipInfo(path, ZIP_TIME)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (0o100755 if path == executable else 0o100644) << 16
            z.writestr(entry, merged[path])
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.partition("\n")[0])
    parser.add_argument("wheel", nargs="?", type=Path, help="the plain wheel from uv build")
    parser.add_argument("--pin", metavar="RELEASE", help="write that kit release to client.lock")
    args = parser.parse_args()
    if args.pin:
        return pin(args.pin)
    if not args.wheel:
        parser.error("name the wheel, or --pin a release")
    lock = read_lock()
    release = lock_release()
    for tag, end in PLATFORMS.items():
        name = next(n for n in lock if n.endswith(end))
        data = fetch(f"{KIT}/{release}/{name}")
        if hashlib.sha256(data).hexdigest() != lock[name]:
            sys.exit(f"{name}: not the file client.lock pins")
        done = bundle(args.wheel, tag, archive_files(data, name), args.wheel.parent)
        print(f"{done.name}: {done.stat().st_size / 1048576:.1f} MiB")


if __name__ == "__main__":
    main()
