"""
Main pipeline orchestrator.

Runs stages in order, short-circuiting once enough citations are found.
Each stage is independent and returns a flat list of dicts with a "stage" key.
"""

from __future__ import annotations

from pathlib import Path

from .stages import link_crawl, doi_scan, ref_section, footnote_scan, inline_crawl

# A stage is considered "sufficient" if it returns at least this many hits.
# Downstream callers can override per-call.
DEFAULT_MIN_HITS = 3


def extract(
    pdf_path: str | Path,
    *,
    min_hits: int = DEFAULT_MIN_HITS,
    max_stage: int = 5,
    verbose: bool = False,
) -> dict:
    """
    Run the five-stage citation extraction cascade on a PDF.

    Parameters
    ----------
    pdf_path:  Path to the input PDF.
    min_hits:  Minimum citation hits required before skipping remaining stages.
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

    def _run(stage_num: int, name: str, fn, **kwargs) -> list[dict]:
        if stage_num > max_stage:
            return []
        hits = fn(pdf_path, **kwargs)
        stages_run.append(name)
        if verbose:
            print(f"  [{name}] {len(hits)} hit(s)")
        return hits

    # Stage 1 — hyperlink annotations
    s1 = _run(1, "link_crawl", link_crawl.extract)
    all_citations.extend(s1)
    doi_hits = {c["doi"] for c in s1 if c.get("doi")}
    if len(doi_hits) >= min_hits:
        return _result(all_citations, stages_run, pdf_path)

    # Stage 2 — unlinked DOI text scan
    s2 = _run(2, "doi_scan", doi_scan.extract, known_dois=doi_hits)
    all_citations.extend(s2)
    doi_hits |= {c["doi"] for c in s2 if c.get("doi")}
    if len(doi_hits) >= min_hits:
        return _result(all_citations, stages_run, pdf_path)

    # Stage 3 — reference section OCR
    s3 = _run(3, "ref_section", ref_section.extract)
    all_citations.extend(s3)
    ref_hits = len([c for c in s3 if c.get("doi") or c.get("text")])
    if ref_hits >= min_hits:
        return _result(all_citations, stages_run, pdf_path)

    # Stage 4 — footnote zone scan
    s4 = _run(4, "footnote_scan", footnote_scan.extract)
    all_citations.extend(s4)
    fn_hits = len([c for c in s4 if c.get("doi") or c.get("author")])
    if fn_hits >= min_hits:
        return _result(all_citations, stages_run, pdf_path)

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
