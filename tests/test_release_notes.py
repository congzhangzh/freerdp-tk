"""The release notes: one section per release tag (yyyymmdd.index), newest first,
"Unreleased" on top. release.yml publishes a tag only with a section of its own."""

import re

from freerdp_tk import app


def headings():
    return re.findall(r"^## (.+)$", app.release_notes(), re.MULTILINE)


def test_the_package_carries_the_notes():
    assert app.release_notes().startswith("# freerdp-tk release notes")


def test_sections_are_release_tags_newest_first():
    found = headings()
    releases = [h for h in found if h != "Unreleased"]
    assert found[:1] == ["Unreleased"] or found[0] == releases[0]
    dated = [h for h in releases if re.fullmatch(r"\d{8}\.\d+", h)]
    key = [(int(day), int(n)) for day, n in (h.split(".") for h in dated)]
    assert key == sorted(key, reverse=True) and len(set(key)) == len(key)
    assert dated[-1] == "20261107.1"  # the first dated release
    # before it, the 0.x tags as published, with their dates, newest first
    old = releases[len(dated):]
    assert releases[:len(dated)] == dated, releases
    assert all(re.fullmatch(r"v?\d+\.\d+\.\d+ · \d{4}-\d{2}-\d{2}", h) for h in old), old
    assert [h.split(" · ")[0] for h in old] == OLD_TAGS


OLD_TAGS = ["0.5.0", "0.4.1", "0.4.0", "0.3.2", "0.3.1", "0.3.0", "0.2.0", "v0.1.1", "v0.1.0"]


def test_every_old_tag_has_its_date():
    """The date beside an old tag is the day it was tagged (git), as published."""
    old = [h for h in headings() if " · " in h]
    assert {h.split(" · ")[0]: h.split(" · ")[1] for h in old}.keys() == set(OLD_TAGS)
