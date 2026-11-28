"""The script that puts the client into the wheels (no network, a fake client)."""

import hashlib
import importlib.util
import io
import subprocess
import sys
import tarfile
import zipfile
from base64 import urlsafe_b64encode
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "bundle_client.py"
spec = importlib.util.spec_from_file_location("bundle_client", SCRIPT)
bundle_client = importlib.util.module_from_spec(spec)
sys.modules["bundle_client"] = bundle_client
spec.loader.exec_module(bundle_client)

INFO = "freerdp_tk-1.2.3.dist-info"


def plain_wheel(folder: Path) -> Path:
    wheel = folder / "freerdp_tk-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as z:
        z.writestr("freerdp_tk/app.py", "pass\n")
        z.writestr(f"{INFO}/METADATA", "Name: freerdp-tk\n")
        z.writestr(f"{INFO}/WHEEL", "Root-Is-Purelib: true\nTag: py3-none-any\n")
        z.writestr(f"{INFO}/RECORD", "stale\n")
    return wheel


def tar_xz(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:xz") as t:
        for path, data in files.items():
            info = tarfile.TarInfo(path)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return out.getvalue()


def zipped(files: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        for path, data in files.items():
            z.writestr(path, data)
    return out.getvalue()


KIT_FILES = {"top/MANIFEST": b"built from", "top/licenses/freerdp/LICENSE": b"apache",
             "top/licenses/python_linux_x86_64/LICENSE.txt": b"not shipped",
             "top/licenses/freerdp_tk/needs/x/LICENSE": b"not shipped",
             "top/python/bin/python3": b"not shipped", "top/freerdp-tk": b"not shipped"}


def test_a_tar_gives_the_client_and_its_licences_only():
    data = tar_xz({**KIT_FILES, "top/bin/sdl-freerdp": b"program"})
    assert bundle_client.archive_files(data, "x.tar.xz") == {
        "bin/sdl-freerdp": b"program", "MANIFEST": b"built from",
        "licenses/freerdp/LICENSE": b"apache"}


def test_a_zip_gives_the_client_and_its_licences_only():
    data = zipped({**KIT_FILES, "top/sdl-freerdp.exe": b"program"})
    assert bundle_client.archive_files(data, "x.zip") == {
        "sdl-freerdp.exe": b"program", "MANIFEST": b"built from",
        "licenses/freerdp/LICENSE": b"apache"}


# kit 20261128.1 on: the Mac client is an app, and bin/sdl-freerdp runs it (the kit's own script)
MAC_SCRIPT = b"""#!/bin/sh
p=$0
while [ -L "$p" ]; do
    l=$(readlink "$p")
    case $l in /*) p=$l ;; *) p=$(dirname "$p")/$l ;; esac
done
exec "$(dirname "$p")/../FreeRDP.app/Contents/MacOS/sdl-freerdp" "$@"
"""
MAC_APP = {"FreeRDP.app/Contents/Info.plist": b"<plist/>",
           "FreeRDP.app/Contents/MacOS/sdl-freerdp": b'#!/bin/sh\necho "the app: $*"\n',
           "FreeRDP.app/Contents/_CodeSignature/CodeResources": b"hashes of the files above",
           "FreeRDP.app/Contents/Resources/fr.lproj/InfoPlist.strings": b"cam\xc3\xa9ra"}


def test_a_mac_tar_gives_the_app_its_script_runs():
    data = tar_xz({**KIT_FILES, "top/bin/sdl-freerdp": MAC_SCRIPT,
                   **{"top/" + path: body for path, body in MAC_APP.items()}})
    assert bundle_client.archive_files(data, "x.tar.xz") == {
        "bin/sdl-freerdp": MAC_SCRIPT, "MANIFEST": b"built from",
        "licenses/freerdp/LICENSE": b"apache", **MAC_APP}


def test_the_mac_wheel_keeps_the_app_byte_for_byte_where_the_script_finds_it(tmp_path):
    files = {"bin/sdl-freerdp": MAC_SCRIPT, "MANIFEST": b"m", **MAC_APP}
    done = bundle_client.bundle(plain_wheel(tmp_path), "macosx_12_0_arm64", files, tmp_path)
    with zipfile.ZipFile(done) as z:
        mode = {i.filename: i.external_attr >> 16 for i in z.infolist()}
        assert z.read("freerdp_tk/client/sdl-freerdp") == MAC_SCRIPT
        for path, body in MAC_APP.items():  # the app's signature covers these bytes
            assert z.read("freerdp_tk/" + path) == body
        record = dict(line.split(",", 1) for line in z.read(f"{INFO}/RECORD").decode().split())
        assert set(record) == set(mode)
    program = "freerdp_tk/FreeRDP.app/Contents/MacOS/sdl-freerdp"
    assert mode["freerdp_tk/client/sdl-freerdp"] == mode[program] == 0o100755
    assert mode["freerdp_tk/FreeRDP.app/Contents/Info.plist"] == 0o100644
    if sys.platform == "win32":
        return  # no sh to run the script with; the path above is the same
    with zipfile.ZipFile(done) as z:  # as an installer does: the files, with their modes
        z.extractall(tmp_path / "site")
    for path, bits in mode.items():
        (tmp_path / "site" / path).chmod(bits & 0o777)
    ran = subprocess.run([str(tmp_path / "site/freerdp_tk/client/sdl-freerdp"), "/v:x"],
                         capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert (ran.returncode, ran.stdout) == (0, "the app: /v:x\n"), ran.stderr


def test_the_wheel_is_tagged_and_recorded(tmp_path):
    files = {"bin/sdl-freerdp": b"program", "MANIFEST": b"m", "licenses/a/LICENSE": b"l"}
    done = bundle_client.bundle(plain_wheel(tmp_path), "macosx_12_0_arm64", files, tmp_path)
    assert done.name == "freerdp_tk-1.2.3-py3-none-macosx_12_0_arm64.whl"
    with zipfile.ZipFile(done) as z:
        names = z.namelist()
        assert names[-1] == f"{INFO}/RECORD"  # installers expect dist-info at the end
        assert z.read("freerdp_tk/client/sdl-freerdp") == b"program"
        assert "freerdp_tk/client/licenses/a/LICENSE" in names
        mode = z.getinfo("freerdp_tk/client/sdl-freerdp").external_attr >> 16
        assert mode & 0o111  # installers keep the executable bit from here
        assert not z.getinfo("freerdp_tk/client/MANIFEST").external_attr >> 16 & 0o111
        wheel_text = z.read(f"{INFO}/WHEEL").decode()
        assert "Tag: py3-none-macosx_12_0_arm64" in wheel_text
        assert "Root-Is-Purelib: false" in wheel_text
        record = dict(line.split(",", 1) for line in z.read(f"{INFO}/RECORD").decode().split())
        assert "stale" not in record
        assert set(record) == set(names)
        digest = urlsafe_b64encode(hashlib.sha256(b"program").digest()).rstrip(b"=").decode()
        assert record["freerdp_tk/client/sdl-freerdp"] == f"sha256={digest},7"


def test_the_same_input_gives_the_same_wheel(tmp_path):
    wheel = plain_wheel(tmp_path)
    files = {"sdl-freerdp.exe": b"program"}
    first = bundle_client.bundle(wheel, "win_amd64", files, tmp_path).read_bytes()
    assert bundle_client.bundle(wheel, "win_amd64", files, tmp_path).read_bytes() == first


def test_an_archive_without_a_client_stops_the_build(tmp_path):
    with pytest.raises(SystemExit):
        bundle_client.bundle(plain_wheel(tmp_path), "win_amd64", {"MANIFEST": b"m"}, tmp_path)


def test_the_lock_names_one_client_for_every_platform():
    lock = bundle_client.read_lock()
    for end in bundle_client.PLATFORMS.values():
        assert sum(name.endswith(end) for name in lock) == 1
    assert len(lock) == len(bundle_client.PLATFORMS)
    assert all(len(sha) == 64 for sha in lock.values())


def test_the_release_comes_from_the_lock_not_the_file_names(tmp_path):
    lock = tmp_path / "client.lock"
    lock.write_text("# head\n\n# release 20261112.1\n"
                    "ab  sdl3-freerdp-20261111.4-linux-x86_64.tar.xz\n", encoding="utf-8")
    assert bundle_client.lock_release(lock) == "20261112.1"
    assert bundle_client.read_lock(lock) == {"sdl3-freerdp-20261111.4-linux-x86_64.tar.xz": "ab"}


def test_an_old_lock_takes_the_release_from_the_file_names(tmp_path):
    lock = tmp_path / "client.lock"
    lock.write_text("# head\n\nab  sdl3-freerdp-20261106.3-linux-x86_64.tar.xz\n", encoding="utf-8")
    assert bundle_client.lock_release(lock) == "20261106.3"


@pytest.mark.parametrize("intel", [True, False])
def test_pin_takes_one_client_per_wheel_and_no_intel_mac(tmp_path, monkeypatch, intel):
    """The kit built macos-x86_64 until 20261122.6; a pin leaves it out, with or without it."""
    ends = [*bundle_client.PLATFORMS.values(), *(["macos-x86_64.tar.xz"] if intel else [])]
    sums = "".join(f"{i:064x}  sdl3-freerdp-20261122.4-{end}\n" for i, end in enumerate(ends))
    sums += f"{9:064x}  freerdp-host-20261122.4-linux-x86_64.tar.xz\n"
    monkeypatch.setattr(bundle_client, "fetch", lambda url: sums.encode())
    lock = tmp_path / "client.lock"
    lock.write_text("# head\n\n# release 20261122.5\nab  old\n", encoding="utf-8")
    monkeypatch.setattr(bundle_client, "LOCK", lock)
    bundle_client.pin("20261122.6")
    pinned = bundle_client.read_lock(lock)
    assert bundle_client.lock_release(lock) == "20261122.6"
    assert len(pinned) == len(bundle_client.PLATFORMS)
    assert not any("macos-x86_64" in name for name in pinned)
    assert lock.read_text(encoding="utf-8").startswith("# head\n\n")
