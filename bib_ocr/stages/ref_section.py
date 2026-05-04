"""
Stage 3 — Reference section OCR.

Detects the bibliography / references / works-cited section at the end of the
paper and extracts raw reference strings from it.

Strategy (in order):
  1. Scan the last N pages with pypdf text extraction.
  2. Look for a section header (References / Bibliography / Works Cited / Notes…).
  3. For pages that yield < MIN_CHARS of text, fall back to Tesseract OCR using
     the preprocessing pipeline from bib_ocr.preprocessing (biblio.py-derived).
  4. Split the raw block into individual reference strings.
  5. Extract DOIs and author-year tokens from each string.

Sources:
  - bib_pdf_ocr.py (research-party): section detection, pypdf→tesseract fallback,
    _split_ref_entries, _scan_ref_entries patterns.
  - biblio.py (witchofthewires/biblio): PIL preprocessing pipeline.
"""

from __future__ import annotations

import re
from pathlib import Path

# Section header keywords (case-insensitive)
_SECTION_HEADERS = re.compile(
    r"^\s*(references|bibliography|works\s+cited|works\s+consulted|"
    r"bibliographie|literatur|literatuur|notes|endnotes|footnotes|"
    r"reference\s+list|cited\s+works)\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>,;)]+)", re.ASCII)

# Minimum characters for pypdf output to be considered usable
_MIN_CHARS = 80
# How many trailing pages to scan for the reference section
_TAIL_PAGES = 12
# Tesseract page-segmentation mode for reference lists (single block)
_PSM = "6"


def _pypdf_page_text(reader, page_idx: int) -> str:
    try:
        return reader.pages[page_idx].extract_text() or ""
    except Exception:
        return ""


def _tesseract_page_text(pdf_path: Path, page_idx: int) -> str:
    try:
        from pdf2image import convert_from_path
        import pytesseract
        from bib_ocr.preprocessing import prepare_for_tesseract
    except ImportError:
        return ""
    try:
        images = convert_from_path(str(pdf_path), first_page=page_idx + 1, last_page=page_idx + 1, dpi=300)
        if not images:
            return ""
        img = prepare_for_tesseract(images[0])
        return pytesseract.image_to_string(img, config=f"--psm {_PSM}")
    except Exception:
        return ""


def _page_text(pdf_path: Path, reader, page_idx: int) -> str:
    text = _pypdf_page_text(reader, page_idx)
    if len(text.strip()) < _MIN_CHARS:
        text = _tesseract_page_text(pdf_path, page_idx)
    return text


def _split_ref_entries(block: str) -> list[str]:
    """Split a raw reference block into individual reference strings."""
    # Try splitting on lines that begin with [number] or author-like patterns
    bracket_split = re.split(r"\n(?=\[\d+\])", block)
    if len(bracket_split) > 2:
        return [e.strip() for e in bracket_split if e.strip()]
    # Fall back to double-newline or single-newline after a trailing year/period
    entries = re.split(r"\n{2,}|\n(?=[A-Z][a-z])", block)
    return [e.strip() for e in entries if len(e.strip()) > 20]


def extract(pdf_path: Path, tail_start: int | None = None) -> list[dict]:
    """
    Return list of {"text": str, "doi": str|None, "page": int, "stage": "ref_section"}
    for each detected reference string.

    tail_start: first page index to scan (0-based). If None, determined via
                density analysis falling back to the last _TAIL_PAGES pages.
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

    n_pages = len(reader.pages)

    if tail_start is None:
        try:
            from bib_ocr.density import page_density, ref_section_start
            dm = page_density(pdf_path)
            tail_start = ref_section_start(dm)
        except Exception:
            tail_start = max(0, n_pages - _TAIL_PAGES)

    # Scan tail pages, find the first page with a section header
    ref_start_page: int | None = None
    page_texts: dict[int, str] = {}

    for i in range(tail_start, n_pages):
        text = _page_text(pdf_path, reader, i)
        page_texts[i] = text
        if _SECTION_HEADERS.search(text) and ref_start_page is None:
            ref_start_page = i

    if ref_start_page is None:
        # No header found — treat the last 4 pages as reference section
        ref_start_page = max(tail_start, n_pages - 4)

    # Concatenate all pages from ref_start onward
    ref_block = "\n\n".join(page_texts.get(i, "") for i in range(ref_start_page, n_pages))

    # Strip everything before the header line itself
    hm = _SECTION_HEADERS.search(ref_block)
    if hm:
        ref_block = ref_block[hm.end():]

    entries = _split_ref_entries(ref_block)
    results: list[dict] = []
    for entry in entries:
        doi_match = _DOI_RE.search(entry)
        results.append({
            "text": entry,
            "doi": doi_match.group(1).rstrip(".,;)") if doi_match else None,
            "page": ref_start_page,
            "stage": "ref_section",
        })
    return results
