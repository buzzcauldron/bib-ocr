"""
Main pipeline orchestrator.

Runs citation stages **1→5** in order whenever ``max_stage`` allows — there is **no**
``min_hits`` short-circuit. Scanned PDFs are assumed to need the full cascade (plaintext
layer, links, density-guided bibliography tail, footnote bands, inline patterns) unless
the operator caps stages with ``max_stage``.

Stages **1 (`doi_scan`)** and **2 (`link_crawl`)** both run whenever ``max_stage`` ≥ **2**.
OCR-bearing stages (**3–5**) always follow if still permitted by ``max_stage``.

Each stage is independent and returns a flat list of dicts with a "stage" key.
"""

from __future__ import annotations

from pathlib import Path

from .stages import doi_scan, link_crawl, ref_section, footnote_scan, inline_crawl


def extract(
    pdf_path: str | Path,
    *,
    max_stage: int = 5,
    verbose: bool = False,
) -> dict:
    """
    Run the five-stage citation extraction cascade on a PDF.

    Stage order **(1→5)**:

    1. ``doi_scan`` — plaintext ``10.*/*`` DOI-shaped substrings via pypdf on every page.

    2. ``link_crawl`` — hyperlink annotations → DOIs/URLs via pymupdf (skips DOIs
       already harvested in stage 1). **Runs when ``max_stage`` ≥ 2.**

    3. ``ref_section`` — detect + OCR bibliography tail (density-guided).

    4. ``footnote_scan`` — OCR lower page bands for footnote styles.

    5. ``inline_crawl`` — last-resort inline / parenthetical patterns.

    Parameters
    ----------
    pdf_path:  Path to the input PDF.
    max_stage: Stop after this stage number (1–5). Useful for testing.
    verbose:   Print stage results to stdout.

    Returns
    -------
    {
      "citations": [list of dicts, each with a "stage" key],
      "stages_run": [list of stage names that were executed],
      "pdf": str(pdf_path),
    }
    """
    pdf_path = Path(pdf_path)
    all_citations: list[dict] = []
    stages_run: list[str] = []

    # Pre-compute reference density map once; used by Stages 3 & 4 to target OCR.
    _density_map = None
    _hot_pages: list[int] | None = None
    _ref_start: int | None = None

    def _ensure_density() -> None:
        nonlocal _density_map, _hot_pages, _ref_start
        if _density_map is not None:
            return
        try:
            from bib_ocr.density import page_density, target_pages, ref_section_start
            _density_map = page_density(pdf_path)
            _hot_pages = target_pages(_density_map)
            _ref_start = ref_section_start(_density_map)
            if verbose:
                print(f"  [density] hot pages: {_hot_pages}  ref_start: {_ref_start}")
        except Exception as exc:
            if verbose:
                print(f"  [density] skipped ({exc})")

    def _run(stage_num: int, name: str, fn, **kwargs) -> list[dict]:
        if stage_num > max_stage:
            return []
        hits = fn(pdf_path, **kwargs)
        stages_run.append(name)
        if verbose:
            print(f"  [{name}] {len(hits)} hit(s)")
        return hits

    # Stage 1 — plaintext DOIs in the extracted text layer (pypdf)
    s1 = _run(1, "doi_scan", doi_scan.extract)
    all_citations.extend(s1)
    doi_hits = {c["doi"] for c in s1 if c.get("doi")}

    # Stage 2 — hyperlink annotations → DOIs/URLs (pymupdf; skips dois already in plain text).
    s2 = _run(2, "link_crawl", link_crawl.extract, known_dois=doi_hits)
    all_citations.extend(s2)

    # Stage 3 — reference section OCR (density-targeted tail_start)
    _ensure_density()
    s3 = _run(3, "ref_section", ref_section.extract, tail_start=_ref_start, density=_density_map)
    all_citations.extend(s3)

    # Stage 4 — footnote zone scan (density-targeted pages)
    s4 = _run(4, "footnote_scan", footnote_scan.extract, target_page_indices=_hot_pages or None)
    all_citations.extend(s4)

    # Stage 5 — inline citation crawl (last resort)
    s5 = _run(5, "inline_crawl", inline_crawl.extract)
    all_citations.extend(s5)

    return _result(all_citations, stages_run, pdf_path)


def _result(citations: list[dict], stages_run: list[str], pdf_path: Path) -> dict:
    return {
        "citations": citations,
        "stages_run": stages_run,
        "pdf": str(pdf_path),
    }
