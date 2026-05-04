"""
Stage 3 — Reference section OCR.

Detects the bibliography / references / works-cited section at the end of the
paper and extracts raw reference strings from it.

Strategy (in order):
  1. Scan the last N pages with pypdf text extraction.
  2. Look for a bibliography section header (``Bibliography``, ``References``,
     ``Works cited``, chapter prefixes, multilingual variants — see ``section_heads``).
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

from bib_ocr.section_heads import SECTION_HEADER_LINE_RE as _SECTION_HEADERS

# Stop bibliography extraction when proofs / appendix content begins (SSRNecon pattern).
_TAIL_STOP_LINES = re.compile(
    r"(?im)^\s*(?:"
    r"appendix\s*[a-z]?\s*[\.\:]?|online\s+appendix\b|supplementary\s+materials?\b|"
    r"(?:technical\s+|online\s+|supplementary\s+)?appendix\b|"
    r"a\s+proofs\b|"  # “A Proofs We present…”
    r"proofs\s+we\s+present\b|"
    r"internet\s+appendix\b"
    r")"
)

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>,;)]+)", re.ASCII)

# Preprint patterns → inferred DOI
# Ordered longest-match first so SSRN beats a bare number match.
_PREPRINT_PATTERNS: list[tuple[re.Pattern, str]] = [
    # SSRN: "SSRN preprint 1234567" or "SSRN Working Paper 1234567"
    (re.compile(r"(?i)\bssrn\b[^0-9]{0,25}(\d{6,8})\b"), "10.2139/ssrn.{0}"),
    # arXiv: "arXiv:2101.01234" or "arXiv preprint 2101.01234v2"
    (re.compile(r"(?i)\barxiv[:\s]+([0-9]{4}\.[0-9]{4,5})(?:v\d+)?"), "10.48550/arXiv.{0}"),
    # NBER: "NBER Working Paper 12345"
    (re.compile(r"(?i)\bnber\b[^0-9]{0,20}(\d{4,6})\b"), "10.3386/w{0}"),
]


def _infer_preprint_doi(text: str) -> str | None:
    """Return an inferred DOI for a known preprint repository, or None."""
    for pattern, template in _PREPRINT_PATTERNS:
        m = pattern.search(text)
        if m:
            return template.format(m.group(1))
    return None

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


# Concatenated author–year refs: ``…. 5962739. Author, Given (yyyy)``.
_YEAR_GLUE = re.compile(
    # Only glue breaks like ``…(1999). Author, …``, ``…preprint 123. Author``, ``…858. Author``.
    # Never split after initials ``J. Sherbino`` — require digit or ")" before ".".
    r"(?<=[\d\)])\.\s+(?=[A-Z][^\n]{4,}?,\s*[A-Za-z .\u2019'\-¨\u0326]+\([12]\d{3}\))",
    flags=re.UNICODE,
)
_COMMA_GLUE = re.compile(
    # ``…preprint 5962739. Author, …`` / ``…114, 1321–1358. Author, …`` — never ``J. Sherbino``.
    r"(?<=\d)\.\s+(?=[A-Z][A-Za-z\u2019'\-\u02bc]+,\s+(?:and\s+)?[A-Z])",
    flags=re.UNICODE,
)


def _pre_split_glued_refs(block: str) -> str:
    """
    SSRN/AEA refs often concatenate entries (...preprint 5962739. Ben-Porath…) with no
    blank line, or glue across a newline (``358.\\nHolmström, …``). Prefer the stricter
    ``Surname … (yyyy)`` boundary so diacritics in surnames do not break comma-only rules.
    """
    block = _YEAR_GLUE.sub(".\n", block)
    return _COMMA_GLUE.sub(".\n", block)


def _tail_line_stops_refs(line: str) -> bool:
    s = line.strip()
    return bool(_TAIL_STOP_LINES.match(s))


_PDF_LINE_NOT_NEW_ENTRY = (
    r"(?!In\s|On\s|At\s|The\s|An\s|For\s|By\s|We\s|If\s|Proceedings\s|Chapter\s|Volume\s"
    r"|IEEE\s|ACM\s|Journal\s|Mathematical\s|Operations\s|Transactions\s)"
)


def _split_pdf_prose_bundle(block: str, *, min_entries: int = 35) -> list[str] | None:
    """
    Thesis / dissertation lists often put **Given-name-first** authors and mix single-
    multi-, and dot-initial lines. :func:`_split_ref_entries` was written for SSRN surname-
    comma starts; merging whole PDF pages makes that mismatch painful. Prefer boundary
    marks at ``"... and Alice"``, ``Kimon Antonakopoulos. Title``, ``R. Tyrrell Rockafellar
    and Roger ...``, and ``E. N. Khobotov. Modification ...``.
    """
    txt = block.strip()
    if len(txt) < 4000:
        return None

    neg = _PDF_LINE_NOT_NEW_ENTRY
    team = re.compile(
        rf"\n\s*(?={neg}[A-Z][a-z]{{2,30}}\s+[^\n]{{1,400}}?\band\s+[A-Z])",
        re.UNICODE,
    )
    solo = re.compile(
        rf"\n\s*(?={neg}[A-Z][a-z]{{2,30}}\s+[A-Z][a-z]{{2,40}}\.\s+[A-Z])",
        re.UNICODE,
    )
    init_team = re.compile(
        rf"\n\s*(?={neg}(?:[A-Z]\.\s+){{1,3}}[A-Z][a-z]{{2,30}}\s+[^\n]{{0,120}}?\band\s+[A-Z])",
        re.UNICODE,
    )
    dot_init_solo = re.compile(
        rf"\n\s*(?={neg}(?:[A-Z]\.\s+){{1,3}}[A-Z][a-z]{{2,40}}\.\s+[A-Z])",
        re.UNICODE,
    )

    bounds: set[int] = {0}
    for rx in (team, solo, init_team, dot_init_solo):
        for m in rx.finditer(txt):
            bounds.add(m.start())
    spans = sorted(bounds)

    slices: list[str] = []
    for a, b in zip(spans, spans[1:]):
        frag = txt[a:b].strip()
        if len(frag) > 25:
            slices.append(frag)

    if len(slices) < min_entries:
        return None
    return slices


def _split_ref_entries(block: str) -> list[str]:
    """Split a raw reference block into individual reference strings."""
    block = _pre_split_glued_refs(block.strip())
    # [1] / [12] bracket-numbered refs
    bracket_split = re.split(r"\n(?=\[\d{1,3}\])", block)
    if len(bracket_split) > 2:
        return [e.strip() for e in bracket_split if e.strip()]

    # "1. " / "12. " numbered list
    numbered_split = re.split(r"\n(?=\d{1,3}\.\s+[A-Z])", block)
    if len(numbered_split) > 2:
        return [e.strip() for e in numbered_split if e.strip()]

    # Blank-line separated (most reliable when present)
    blank_split = [e.strip() for e in re.split(r"\n{2,}", block) if len(e.strip()) > 20]
    if len(blank_split) > 4:
        return blank_split

    # Author-year single-newline style (e.g. SSRN/AEA format):
    # New entry starts with "Surname, Firstname" or "Surname and Co"
    # Split at \n followed by an uppercase word + comma/space + uppercase letter,
    # but NOT at mid-reference continuations (which start with lowercase or a
    # continuation word mid-sentence).
    #
    # Pattern: line starts with [A-Z][a-z…] followed by:
    #   ",\s[A-Z]"  → "Smith, John"
    #   " and [A-Z]" → "Smith and Jones"
    #   " [A-Z][a-z]+ [A-Z]" → "Van Den Berg..."  (multiple surname words)
    # Split on newline before a new bibliography line. The main branch requires a plain
    # Latin surname opener; the alternate allows anything up to the first comma (Unicode
    # names, “Holmstr\n+¨om”) so “…358.\\nHolmstr¨om, Bengt (1979)…” is not glued to the
    # prior entry.
    _AUTH_START = re.compile(
        r"\n(?="
        r"(?:"
        r"[A-Z][a-z]{1,20}"
        r"(?:"
        r",\s+[A-Z]"
        r"|,\s+\d{4}"
        r"|\s+(?:and|&)\s+[A-Z][a-z]"
        r"|\s+[A-Z][a-z]{1,20},"
        r")"
        r"|"
        r"[A-Z][^\n,]{2,70},\s*[A-Za-z .\u2019'\-¨\u0326]+\([12]\d{3}\)"
        r")"
        r")",
    )
    auth_split = _AUTH_START.split(block)
    if len(auth_split) > 4:
        return [e.strip() for e in auth_split if len(e.strip()) > 20]

    # Last resort: any capital-starting line
    entries = re.split(r"\n(?=[A-Z])", block)
    return [e.strip() for e in entries if len(e.strip()) > 20]


def extract(
    pdf_path: Path,
    tail_start: int | None = None,
    *,
    density: object | None = None,
) -> list[dict]:
    """
    Return list of {"text": str, "doi": str|None, "page": int, "stage": "ref_section"}
    for each detected reference string.

    tail_start: first page index to scan (0-based). If None, determined via
                density analysis falling back to the last _TAIL_PAGES pages.
    density:    Optional page_density matrix — when set together with detected
                ``References`` page, trims the scan before appendix/proofs pages.
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

    ref_end_exclusive = n_pages
    if density is not None:
        try:
            from bib_ocr.density import ref_section_end_exclusive as _rs_end_excl

            ref_end_exclusive = int(_rs_end_excl(density, ref_start_page))
        except Exception:
            ref_end_exclusive = n_pages

    # Join bibliography pages before splitting — PDF line-wrap and page breaks sit in the middle
    # of logical entries; per-page splitting produces fragments ("York, 2021") and drops cites.
    _YEAR_RE = re.compile(r"\b(?:1[5-9]\d{2}|20\d{2})\b")
    results: list[dict] = []
    seen_text: set[str] = set()

    mega_parts: list[str] = []
    first_ref_page = True
    for i in range(ref_start_page, ref_end_exclusive):
        page_t = page_texts.get(i, "")
        if not page_t.strip():
            continue
        if first_ref_page:
            hm = _SECTION_HEADERS.search(page_t)
            if hm:
                page_t = page_t[hm.end():]
            first_ref_page = False

        head_nonempty = [ln.strip() for ln in page_t.splitlines() if ln.strip()]
        # Typical SSRN appendix right after References: leading “A Proofs …”.
        if head_nonempty and _tail_line_stops_refs(head_nonempty[0]):
            break

        page_t = page_t.strip()
        mega_parts.append(page_t)

    if not mega_parts:
        return results

    mega = "\n".join(mega_parts)
    mega_prep = _pre_split_glued_refs(mega)
    prose_slices = _split_pdf_prose_bundle(mega_prep)
    if prose_slices is None:
        split_candidates = _split_ref_entries(mega)
    else:
        split_candidates = prose_slices

    for entry in split_candidates:
        if not _YEAR_RE.search(entry):
            continue  # journal-fragment line, not a reference
        key = entry[:60]
        if key in seen_text:
            continue
        seen_text.add(key)
        # Page-level provenance: merged bibliography spans many pages; density-based
        # character offsets are fragile after line re-glue. Anchor to the section start.
        page_i = ref_start_page

        doi_match = _DOI_RE.search(entry)
        if doi_match:
            doi = doi_match.group(1).rstrip(".,;)")
        else:
            doi = _infer_preprint_doi(entry)
        results.append({
            "text": entry,
            "doi": doi,
            "page": page_i,
            "stage": "ref_section",
        })

    return results
