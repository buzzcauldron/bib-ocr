"""
Stage 5 — Inline citation crawl (last resort).

Scans every page for inline citation patterns: parenthetical author-year,
narrative author-year, numeric brackets. Runs after **footnote_scan** when
``max_stage`` permits.

Useful overlap with earlier stages catches inline-only patterns; Stage 5
also remains the place for citation styles weak on bibliography blocks.

Sources:
  - inline_citation_extractor.py (research-party): pattern definitions,
    ibid/op-cit state machine concept, OpenAlex resolution contract.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# ── Patterns ──────────────────────────────────────────────────────────────────

# (Smith 2010) / (Smith, 2010) / (Smith & Jones, 2010) / (Smith et al. 2010)
_PARENS_AY = re.compile(
    r"\(([A-Z][a-z]{1,25}(?:\s+(?:and|&|et\s+al\.?)\s+[A-Z][a-z]{0,25})?)"
    r"[,\s]+(\d{4})(?:[,;][^)]{0,40})?\)",
)
# Smith (2010) argues
_NARRATIVE_AY = re.compile(
    r"\b([A-Z][a-z]{1,25}(?:\s+(?:and|&)\s+[A-Z][a-z]{1,25})?)\s+\((\d{4})\)",
)
# [12] / [12, 15] / [12-15]
_NUMERIC_BRACKET = re.compile(r"\[(\d+(?:[,–\-]\d+)*)\]")


@dataclass
class InlineCitation:
    author: str
    year: str | None
    raw: str
    page: int
    style: str  # "parens_ay" | "narrative_ay" | "numeric"


def _extract_page_text(reader, page_idx: int) -> str:
    try:
        return reader.pages[page_idx].extract_text() or ""
    except Exception:
        return ""


def _ocr_full_page(pdf_path: Path, page_idx: int) -> str:
    try:
        from pdf2image import convert_from_path
        import pytesseract
        from bib_ocr.preprocessing import prepare_for_tesseract
    except ImportError:
        return ""
    try:
        images = convert_from_path(str(pdf_path), first_page=page_idx + 1, last_page=page_idx + 1, dpi=200)
        if not images:
            return ""
        return pytesseract.image_to_string(prepare_for_tesseract(images[0]), config="--psm 3")
    except Exception:
        return ""


def extract(pdf_path: Path, min_page_chars: int = 80) -> list[dict]:
    """
    Return list of {"author": str, "year": str|None, "raw": str,
    "page": int, "style": str, "stage": "inline_crawl"}.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore[no-redef]
        except ImportError:
            return []

    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return []

    citations: list[InlineCitation] = []

    for page_idx in range(len(reader.pages)):
        text = _extract_page_text(reader, page_idx)
        if len(text.strip()) < min_page_chars:
            text = _ocr_full_page(pdf_path, page_idx)

        for m in _PARENS_AY.finditer(text):
            citations.append(InlineCitation(m.group(1), m.group(2), m.group(0), page_idx, "parens_ay"))
        for m in _NARRATIVE_AY.finditer(text):
            citations.append(InlineCitation(m.group(1), m.group(2), m.group(0), page_idx, "narrative_ay"))
        for m in _NUMERIC_BRACKET.finditer(text):
            citations.append(InlineCitation(f"[{m.group(1)}]", None, m.group(0), page_idx, "numeric"))

    # Deduplicate by (author, year)
    seen: set[tuple[str, str | None]] = set()
    results: list[dict] = []
    for c in citations:
        key = (c.author.lower(), c.year)
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "author": c.author, "year": c.year, "raw": c.raw,
            "page": c.page, "style": c.style, "stage": "inline_crawl",
        })

    return results
