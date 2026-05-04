"""
Bibliography / reference section title patterns (shared).

Used by ``page_density`` (substring heat boost) and ``ref_section`` (header line
detection). Phrases match common thesis, dissertation, and journal styles:
``Bibliography``, ``References``, ``Works cited``, chapter-prefixed headings, and
lightweight TOC rows (title + trailing page number).
"""

from __future__ import annotations

import re

# Multi-word titles (longer spans listed first — alternation favors them).
_SECTION_MULTIS: tuple[str, ...] = (
    r"works\s+cited",
    r"works\s+consulted",
    r"works\s+referenced",
    r"sources\s+consulted",
    r"list\s+of\s+references",
    r"list\s+of\s+cited\s+references",
    r"literature\s+cited",
    r"literaturverzeichnis",
    r"literatuurlijst",
    r"cited\s+references",
    r"references?\s+cited",  # "references cited", "reference cited"
    r"references\s+and\s+bibliography",
    r"bibliography\s+and\s+references",
    r"selected\s+bibliography",
    r"extended\s+bibliography",
    r"reference\s+list",
    r"cited\s+works",
    r"bibliografie",
    r"bibliographie",
    r"footnotes",
    r"foot\s+notes",
    r"endnotes",
    r"end\s+notes",
    r"published\s+works",
    r"primary\s+sources",
    r"secondary\s+sources",
)

_SECTION_SINGLES: tuple[str, ...] = (
    "references",
    "bibliography",
    "referenzen",
    "literatur",
    "literatuur",
    "notes",
)


def _title_body_alternation() -> str:
    multis = "|".join(_SECTION_MULTIS)
    singles = "|".join(re.escape(w) for w in _SECTION_SINGLES)
    return f"{multis}|{singles}"


# Page-level substring heuristic (heatmap).
SECTION_HEADER_DENSITY_RE = re.compile(
    "|".join(
        list(_SECTION_MULTIS) + [rf"\b{re.escape(t)}\b" for t in _SECTION_SINGLES]
    ),
    re.IGNORECASE,
)


_TITLE_BODY_GROUP = rf"({_title_body_alternation()})"


# Logical line anchored at start: optional chapter / appendix / outline numbering + title +
# optional trailing TOC page digits.
SECTION_HEADER_LINE_RE = re.compile(
    rf"(?im)^[\s\u00a0]*"
    rf"(?:"
    rf"(?:chapter|part)\s+(?:\d+|[IVXLCDM]+)\s*[:\.\-\u2013\u2014]?\s+"
    rf"|appendix\s+[A-Z0-9]+\s*[:\.\-\u2013\u2014]?\s+"
    rf"|[IVXLCDM]+\.\s+"
    rf"|(?:\d+(?:\.\d+)*[.):]\s+|\d+(?:\.\d+)+\s+)"
    rf"|\((?:\d|[ivxlcdm])+\)\s+"
    rf")?"
    rf"{_TITLE_BODY_GROUP}"
    rf"\s*[.:]?(?:[\s\-–—\u2013\u2014]+[0-9]+)?\s*$",
)
