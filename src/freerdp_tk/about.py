"""What About shows, read without Tk: freerdp-tk's own commit, and the MANIFEST that
the bundled client carries (what it was built from, and the kit release it came
from). Nothing here guesses: what cannot be read is None, and About leaves it out.

MANIFEST (rdp-release-kit, beside the client, freerdp_tk/client/MANIFEST in a wheel):

    sdl3-freerdp 20261114.3 for Linux x86_64, built 2026-11-15
    build environment: AlmaLinux 9.8 (Olive Jaguar), ldd (GNU libc) 2.34
    kit: rdp-release-kit <kit commit>                      (kits since e462e7c)
    freerdp-upstream: master <sha> +<N> [yyyy-mm-dd]       (FreeRDP's own base, newer kits)

    sources (sources.lock):
      freerdp   20261114.3 b91abbc81cba56af55cf54b2544b07cbeba9e61d [url]
      sdl3      3.4.18   <sha-256 of its tarball> [url]
      ...
    WITH_AAD=ON ...

A 40-hex hash is a commit; a 64-hex one the digest of a source tarball. The url column
and the kit line are newer: an older MANIFEST has neither, and still reads. The kit line
has no release (the kit picks it after the build): bundle_client.py writes it beside
MANIFEST as KIT_RELEASE, from client.lock.
"""

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

PROJECT = "https://github.com/congzhangzh/freerdp-tk"
KIT = "https://github.com/congzhangzh/rdp-release-kit"
FREERDP = "https://github.com/congzhangzh/FreeRDP"  # the kit's FreeRDP, before MANIFEST had urls
COMMIT_FILE = Path(__file__).with_name("COMMIT")  # written by release.yml before it builds
MAX_MANIFEST = 1 << 20  # a MANIFEST is a few kB; anything far bigger is not one
SHA1 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
# "sdl3-freerdp 20261114.3 for Linux x86_64, built ..." on Linux and macOS,
# "sdl-freerdp.exe 20261115.4 for Windows x86_64, built ..." on Windows: any program name
TITLE = re.compile(r"^\S+ (\d{8}\.\d+) for (.+?), built (\S+)\s*$")
KIT_LINE = re.compile(r"^kit:\s+rdp-release-kit((?:\s+\S+)*)\s*$")
RELEASE = re.compile(r"^\d{8}\.\d+$")
UPSTREAM_LINE = re.compile(r"^freerdp-upstream:\s+(\S+)\s+([0-9a-f]{40})\s+\+(\d+)"
                           r"(?:\s+(\d{4}-\d{2}-\d{2}))?\s*$")
UPSTREAM = "https://github.com/FreeRDP/FreeRDP"
NOT_THE_CLIENT = {"freerdp_tk", "python"}  # the kit's pack, not this client


@dataclass
class Source:
    name: str
    version: str
    hash: str = ""
    url: str = ""

    @property
    def commit(self) -> str | None:
        return self.hash if SHA1.match(self.hash) else None

    @property
    def digest(self) -> str | None:
        return self.hash if SHA256.match(self.hash) else None

    def commit_link(self) -> str | None:
        """The page of this exact commit: on its repo when that is on GitHub."""
        base = self.url or (FREERDP if self.name == "freerdp" else "")
        if self.commit and base.startswith("https://github.com/"):
            return f"{base.rstrip('/').removesuffix('.git')}/commit/{self.commit}"
        return None


@dataclass
class Manifest:
    release: str | None = None  # the FreeRDP release of the client
    platform: str | None = None
    built: str | None = None
    environment: str | None = None
    kit_release: str | None = None
    kit_commit: str | None = None
    upstream: tuple[str, str, int, str | None] | None = None  # branch, commit, ahead, date
    sources: list[Source] = field(default_factory=list)

    def source(self, name: str) -> Source | None:
        return next((s for s in self.sources if s.name == name), None)

    @property
    def client_sources(self) -> list[Source]:
        return [s for s in self.sources if s.name not in NOT_THE_CLIENT]


def parse_manifest(text: str) -> Manifest:
    """What the text says; never raises: a line it cannot read is passed over."""
    m = Manifest()
    in_sources = False
    for line in text.splitlines():
        if in_sources:
            if not line.strip() or not line[0].isspace():
                break  # the sources end at the first blank or unindented line
            words = line.split()
            if len(words) < 2 or words[1] == "needs":  # "freerdp_tk needs (its uv.lock): ..."
                continue
            url = next((w for w in words[3:] if w.startswith(("https://", "http://"))), "")
            m.sources.append(Source(words[0], words[1], words[2] if len(words) > 2 else "", url))
        elif match := TITLE.match(line):
            m.release, m.platform, m.built = match.groups()
        elif line.startswith(("build environment:", "toolchain:")):  # Windows: toolchain
            m.environment = line.partition(":")[2].strip()
        elif match := KIT_LINE.match(line):  # "<commit>"; a release too, should it come
            for word in match[1].split():
                if SHA1.match(word):
                    m.kit_commit = word
                elif RELEASE.match(word):
                    m.kit_release = word
        elif match := UPSTREAM_LINE.match(line):
            branch, sha, ahead, date = match.groups()
            m.upstream = (branch, sha, int(ahead), date)
        elif line.startswith("sources"):
            in_sources = True
    return m


def read_manifest(client: str) -> Manifest | None:
    """The MANIFEST beside a client (the wheel's: client/MANIFEST next to sdl-freerdp)
    or one folder up (a kit archive unpacked by hand: MANIFEST next to bin/). None when
    there is none or it cannot be read, or it says nothing a MANIFEST says."""
    folder = Path(client).parent
    for path in (folder / "MANIFEST", folder.parent / "MANIFEST"):
        try:
            if path.is_file() and path.stat().st_size <= MAX_MANIFEST:
                m = parse_manifest(path.read_text(encoding="utf-8", errors="replace"))
                if not (m.release or m.sources):
                    return None
                release = path.with_name("KIT_RELEASE")
                if not m.kit_release and release.is_file():
                    word = release.read_text(encoding="utf-8", errors="replace").strip()
                    m.kit_release = word if RELEASE.match(word) else None
                return m
        except OSError:
            return None
    return None


def kit_links(m: Manifest) -> tuple[str | None, str | None]:
    """The kit release's page, and its commit's."""
    return (f"{KIT}/releases/tag/{m.kit_release}" if m.kit_release else None,
            f"{KIT}/commit/{m.kit_commit}" if m.kit_commit else None)


FORGES = {"github.com", "gitlab.com", "code.videolan.org", "gitlab.freedesktop.org"}


def url_name(url: str) -> str:
    """A url as a short name: a forge's host and project (github.com/libsdl-org/SDL),
    else the bare host (zlib.net). The link still goes to the whole url."""
    from urllib.parse import urlparse
    parts = urlparse(url)
    host = parts.netloc.removeprefix("www.")
    if host in FORGES:
        project = [p for p in parts.path.split("/") if p][:2]
        if len(project) == 2:
            return f"{host}/{project[0]}/{project[1].removesuffix('.git')}"
    return host or url


def upstream_link(m: Manifest) -> str | None:
    return f"{UPSTREAM}/commit/{m.upstream[1]}" if m.upstream else None


def build_commit(timeout: float = 5) -> str | None:
    """The commit this freerdp-tk was built from: COMMIT in the package (a release
    writes it), else the git checkout it runs from. None when neither tells, never a
    guess. git is asked, so not on the Tk thread."""
    try:
        sha = COMMIT_FILE.read_text(encoding="ascii").strip()
        if SHA1.match(sha):
            return sha
    except (OSError, UnicodeDecodeError):
        pass
    root = Path(__file__).resolve().parents[2]  # src/freerdp_tk/about.py -> the checkout
    if not (root / ".git").exists():
        return None
    try:
        sha = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    return sha if SHA1.match(sha) else None


def commit_link(sha: str) -> str:
    return f"{PROJECT}/commit/{sha}"


def home_as_tilde(text: str, home: str | None = None) -> str:
    """The home folder as ~, for a report that leaves this computer."""
    home = home or str(Path.home())
    return text.replace(home, "~") if home and home not in ("/", "~") else text
