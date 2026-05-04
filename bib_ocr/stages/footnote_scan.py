"""
Stage 4 — Footnote zone scan.

For each page, extract the bottom FOOTNOTE_FRACTION of the page text and
look for citation evidence. For image-only pages (sparse pypdf output),
OCR only the bottom band of the page image.

Sources:
  - bib_pdf_ocr.py (research-party): _footnote_zone(), _extract_footnote_band_image_ocr(),
    footnote band fraction (0.28), sparse-text threshold.
"""

from __future__ import annotations

import re
from pathlib import Path

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>,;)]+)", re.ASCII)
_AUTHOR_YEAR_RE = re.compile(r"([A-Z][a-z]{1,20}(?:\s+(?:and|&)\s+[A-Z][a-z]{1,20})?)[,\s]+(\d{4})[,\.]")

_MIN_CHARS = 80
_FOOTNOTE_FRACTION = 0.28
_PSM_BAND = "6"


def _footnote_zone(text: str, fraction: float = _FOOTNOTE_FRACTION) -> str:
    """Return the bottom fraction of a page's text lines."""
    lines = text.splitlines()
    if not lines:
        return ""
    cut = max(1, int(len(lines) * (1.0 - fraction)))
    return "\n".join(lines[cut:])


def _ocr_bottom_band(pdf_path: Path, page_idx: int, fraction: float = _FOOTNOTE_FRACTION) -> str:
    """Crop and OCR the bottom band of a page image."""
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
        img = images[0]
        w, h = img.size
        band_top = int(h * (1.0 - fraction))
        band = img.crop((0, band_top, w, h))
        band = prepare_for_tesseract(band)
        return pytesseract.image_to_string(band, config=f"--psm {_PSM_BAND}")
    except Exception:
        return ""


def extract(pdf_path: Path, target_page_indices: list[int] | None = None) -> list[dict]:
    """
    Return list of {"text": str, "doi": str|None, "author": str|None,
    "year": str|None, "page": int, "stage": "footnote_scan"}.

    target_page_indices: if given, only scan these 0-based page indices.
                         Defaults to all pages (original behavior).
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

    results: list[dict] = []
    page_iter = (
        ((idx, reader.pages[idx]) for idx in target_page_indices if idx < len(reader.pages))
        if target_page_indices is not None
        else enumerate(reader.pages)
    )
    for page_idx, page in page_iter:
        try:
            full_text = page.extract_text() or ""
        except Exception:
            full_text = ""

        zone = _footnote_zone(full_text)
        if len(zone.strip()) < _MIN_CHARS:
            zone = _ocr_bottom_band(pdf_path, page_idx)

        if not zone.strip():
            continue

        # Extract any DOIs and author-year pairs from the footnote band
        dois = [m.group(1).rstrip(".,;)") for m in _DOI_RE.finditer(zone)]
        ay_pairs = _AUTHOR_YEAR_RE.findall(zone)

        if not dois and not ay_pairs:
            continue

        for doi in dois:
            results.append({"text": zone[:200], "doi": doi, "author": None, "year": None,
                            "page": page_idx, "stage": "footnote_scan"})
        for author, year in ay_pairs:
            results.append({"text": zone[:200], "doi": None, "author": author.strip(), "year": year,
                            "page": page_idx, "stage": "footnote_scan"})

    return results
