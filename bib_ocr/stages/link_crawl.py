"""
Stage 2 — Hyperlink crawl.

Extracts DOIs and canonical URLs from PDF link annotations using pymupdf.
This is faster than OCR stages and higher-confidence — just metadata the
PDF already carries. Runs **after** :mod:`doi_scan`, which harvests plaintext
DOIs from the extracted text layer; hyperlinks whose DOIs are already known
can be omitted from the citation list via ``known_dois``.

Sources: original implementation (no upstream analogue).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# DOI bare pattern (without https://doi.org/ prefix)
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'>]+)", re.ASCII)
_DOI_URL_RE = re.compile(r"https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/[^\s\"'>]+)", re.ASCII)


def _normalise_doi(raw: str) -> str:
    raw = raw.rstrip(".,;)")
    m = _DOI_URL_RE.match(raw)
    return m.group(1) if m else raw


def extract(pdf_path: Path, known_dois: set[str] | None = None) -> list[dict]:
    """
    Return list of {"doi": str, "url": str, "page": int, "stage": "link_crawl"}
    for every hyperlink annotation whose DOI is not already in ``known_dois``
    (typically DOIs harvested by :mod:`doi_scan` in Stage 1).

    Requires pymupdf. Returns [] gracefully if not installed or PDF has no links.
    """
    try:
        import fitz  # pymupdf
    except ImportError:
        return []

    results: list[dict] = []
    skip = known_dois or set()
    seen_dois: set[str] = set()

    try:
        doc = fitz.open(str(pdf_path))
    except Exception:
        return []

    for page_num, page in enumerate(doc):
        for link in page.get_links():
            uri = link.get("uri") or ""
            if not uri:
                continue
            doi = None
            # Prefer explicit doi.org URLs
            m = _DOI_URL_RE.match(uri)
            if m:
                doi = _normalise_doi(m.group(1))
            else:
                # Bare DOI in URI?
                mb = _DOI_RE.search(uri)
                if mb:
                    doi = _normalise_doi(mb.group(1))
            if doi and doi not in skip and doi not in seen_dois:
                seen_dois.add(doi)
                results.append({"doi": doi, "url": uri, "page": page_num, "stage": "link_crawl"})

    doc.close()
    return results
