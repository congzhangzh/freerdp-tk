"""The script that puts the client into the wheels (no network, a fake client)."""

import hashlib
import importlib.util
import io
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
