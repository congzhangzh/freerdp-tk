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
    assert all(re.fullmatch(r"\d{8}\.\d+", h) for h in releases), releases
    key = [(int(day), int(n)) for day, n in (h.split(".") for h in releases)]
    assert key == sorted(key, reverse=True) and len(set(key)) == len(key)
    assert "20261107.1" in releases  # the first dated release; nothing older
