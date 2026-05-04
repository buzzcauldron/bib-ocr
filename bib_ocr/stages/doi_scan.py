"""
Stage 1 — Plaintext DOI text scan.

Reads raw text via pypdf and scans every page for DOI patterns in the extracted
character stream (no hyperlink layer). Runs **before** :mod:`link_crawl`,
which picks up doi.org links and other URI annotations that plaintext may miss.

No OCR is used; if pypdf yields empty pages those are skipped (Stage 3
``ref_section`` handles them via Tesseract).

Sources: original implementation.
"""

from __future__ import annotations

import re
from pathlib import Path

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>,;)]+)", re.ASCII)


def _clean_doi(raw: str) -> str:
    return raw.rstrip(".,;)")


def extract(pdf_path: Path, known_dois: set[str] | None = None) -> list[dict]:
    """
    Return list of {"doi": str, "page": int, "context": str, "stage": "doi_scan"}
    for every ``10.`` + registry DOI substring found via pypdf text extraction.

    Args:
      known_dois: Optional set of DOI strings already counted elsewhere —
        plaintext hits matching these values are omitted (normally empty when
        this stage runs first; still used when tests call ``extract`` with a hint).
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader  # type: ignore[no-redef]
        except ImportError:
            return []

    skip = known_dois or set()
    results: list[dict] = []
    seen: set[str] = set()

    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return []

    for page_num, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if not text.strip():
            continue
        for m in _DOI_RE.finditer(text):
            doi = _clean_doi(m.group(1))
            if doi in skip or doi in seen:
                continue
            seen.add(doi)
            # Grab a small context window around the match
            start = max(0, m.start() - 60)
            end = min(len(text), m.end() + 60)
            context = text[start:end].replace("\n", " ").strip()
            results.append({"doi": doi, "page": page_num, "context": context, "stage": "doi_scan"})

    return results
