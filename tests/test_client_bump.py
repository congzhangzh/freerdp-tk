"""The plain-Python steps of the client bump workflow (no network, a throwaway git repo)."""

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "client_bump.py"
spec = importlib.util.spec_from_file_location("client_bump", SCRIPT)
client_bump = importlib.util.module_from_spec(spec)
sys.modules["client_bump"] = client_bump
spec.loader.exec_module(client_bump)

HEAD = "# freerdp-tk release notes\n\nIntro.\n\n"
OLD = "## 20261115.1\n\n- Something old.\n"


def bump(release="20261115.4", freerdp="20261114.3"):
    return client_bump.BUMP_LINE.format(release=release, freerdp=freerdp)


def test_a_bump_makes_the_unreleased_section_above_the_newest_release():
    text = client_bump.with_bump(HEAD + OLD, "20261115.4", "20261114.3")
    assert text == HEAD + "## Unreleased\n\n" + bump() + "\n\n" + OLD


def test_a_bump_joins_the_unreleased_section_and_replaces_an_older_bump():
    notes = HEAD + "## Unreleased\n\n- Show live stats.\n" + bump("20261115.2", "20261114.1") \
        + "\n\n" + OLD
    text = client_bump.with_bump(notes, "20261115.4", "20261114.3")
    assert text == HEAD + "## Unreleased\n\n- Show live stats.\n" + bump() + "\n\n" + OLD
    assert client_bump.with_bump(text, "20261115.4", "20261114.3") == text  # same pin, same notes


def test_a_bump_alone_in_the_section_is_replaced():
    notes = HEAD + "## Unreleased\n\n" + bump("20261115.2", "20261114.1") + "\n\n" + OLD
    assert client_bump.with_bump(notes, "20261115.4", "20261114.3") == \
        HEAD + "## Unreleased\n\n" + bump() + "\n\n" + OLD


def test_dating_the_notes():
    notes = client_bump.with_bump(HEAD + OLD, "20261115.4", "20261114.3")
    assert client_bump.dated(notes, "20261115.2").startswith(HEAD + "## 20261115.2\n\n- Under")
    with pytest.raises(SystemExit):
        client_bump.dated(HEAD + OLD, "20261115.2")


@pytest.mark.parametrize("tags, today, tag", [
    (["20261115.1", "0.5.0"], "20261115", "20261115.2"),
    (["20261115.1", "20261115.10", "20261115.9"], "20261115", "20261115.11"),
    (["20261112.2"], "20261115", "20261115.1"),
    (["20261116.1"], "20261115", "20261116.2"),  # tagged ahead of this clock: stay newer
])
def test_next_tag(tags, today, tag):
    assert client_bump.next_tag(tags, today) == tag


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A git repo with notes, client.lock and a dated tag; client_bump works in it."""
    if not shutil.which("git"):
        pytest.skip("needs git")
    root = tmp_path / "repo"
    (root / "src" / "freerdp_tk").mkdir(parents=True)
    notes = root / "src" / "freerdp_tk" / "RELEASE_NOTES.md"
    notes.write_text(HEAD + OLD)
    (root / "client.lock").write_text("# release 20261115.3\n")
    (root / "README.md").write_text("readme\n")

    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
                       cwd=root, check=True, capture_output=True)

    def commit(message):
        git("add", "-A")
        git("commit", "-q", "-m", message)

    git("init", "-q")
    commit("start")
    git("tag", "20261115.1")
    monkeypatch.setattr(client_bump, "ROOT", root)
    monkeypatch.setattr(client_bump, "NOTES", notes)

    def do_bump(release, freerdp):
        (root / "client.lock").write_text(f"# release {release}\n")
        notes.write_text(client_bump.with_bump(notes.read_text(), release, freerdp))
        commit(f"Bundle the client of rdp-release-kit {release}")

    return root, commit, do_bump


def test_only_bumps_since_the_tag_are_client_only(repo):
    root, commit, do_bump = repo
    assert client_bump.client_only()[0] is False  # nothing to release
    do_bump("20261115.4", "20261114.3")
    do_bump("20261115.5", "20261114.4")
    ok, why = client_bump.client_only()
    assert ok and why == "2 bump commit(s) since 20261115.1"


def test_a_ui_commit_since_the_tag_is_not_client_only(repo):
    root, commit, do_bump = repo
    (root / "README.md").write_text("new words\n")
    commit("Explain something")
    do_bump("20261115.4", "20261114.3")
    ok, why = client_bump.client_only()
    assert not ok and "Explain something is not a client bump" in why


def test_a_notes_line_by_hand_is_not_client_only(repo):
    root, commit, do_bump = repo
    notes = root / "src" / "freerdp_tk" / "RELEASE_NOTES.md"
    notes.write_text(client_bump.with_bump(notes.read_text(), "20261115.4", "20261114.3")
                     .replace("## Unreleased\n\n", "## Unreleased\n\n- Show live stats.\n"))
    commit("Release note by hand")
    assert client_bump.client_only()[0] is False


def test_a_kit_release_with_the_same_client_files_is_no_bump(tmp_path):
    """Names and SHA-256 decide, not the release line: a page-only kit round carries
    the client freerdp-tk has already."""
    files = "aa  sdl3-freerdp-20261114.3-linux-x86_64.tar.xz\nbb  sdl3-freerdp-20261114.3-win.zip\n"
    old, same, new = tmp_path / "old", tmp_path / "same", tmp_path / "new"
    old.write_text("# pins\n\n# release 20261115.3\n" + files)
    same.write_text("# pins\n\n# release 20261115.4\n" + files)
    new.write_text("# pins\n\n# release 20261115.5\n" + files.replace("aa", "cc"))
    assert client_bump.same_client(old, same)
    assert not client_bump.same_client(old, new)
