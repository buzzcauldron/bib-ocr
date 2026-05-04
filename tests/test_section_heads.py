"""``section_heads``: bibliography title patterns."""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("line", "expect"),
    [
        ("Bibliography", True),
        ("BIBLIOGRAPHY ", True),
        ("Bibliography.", True),
        ("Bibliography 216", True),
        ("Bibliography–216", True),
        ("Chapter IV References", True),
        ("Part 3 Works Cited", True),
        ("3.2 List of References", True),
        ("List of References", True),
        ("Literature Cited\n", True),
        ("References and Bibliography:", True),
        ("Appendix A References", True),
        ("IV.\u00a0References", True),
        ("Reference", False),
        ("Reference Domain", False),
        ("references therein", False),
        ("literature review", False),
        ("literature revised", False),
    ],
)
def test_section_header_line(line: str, expect: bool) -> None:
    from bib_ocr.section_heads import SECTION_HEADER_LINE_RE

    assert bool(SECTION_HEADER_LINE_RE.search(line)) is expect


def test_density_matches_substrings() -> None:
    from bib_ocr.section_heads import SECTION_HEADER_DENSITY_RE

    assert SECTION_HEADER_DENSITY_RE.search("See Works Cited.")
    assert SECTION_HEADER_DENSITY_RE.search("extended bibliography below")
    assert not SECTION_HEADER_DENSITY_RE.search("reference implementation")
