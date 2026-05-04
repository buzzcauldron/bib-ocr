"""
No-DOI eval harness for bib-ocr.

Reads one or more .bib files, finds entries that have:
  - no DOI field
  - a file= field pointing to a Zotero storage PDF that exists on disk

Then runs bib-ocr on each PDF and reports extraction quality:
  - total citations found
  - citations with a direct DOI
  - citations with an inferred preprint DOI (SSRN/arXiv/NBER)
  - text-only citations (no DOI, but has author-year text)

Usage
-----
    python3 eval/nodoi_eval.py "bibliographies/Medieval AI.bib"
    python3 eval/nodoi_eval.py --bib-dir /path/to/bibliographies --out results.jsonl
    python3 eval/nodoi_eval.py "Medieval AI.bib" Sylometry.bib --verbose
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Iterator


# ---------------------------------------------------------------------------
# BibTeX parser (no external deps)
# ---------------------------------------------------------------------------

def _parse_bib(path: Path) -> list[dict]:
    """Return list of entry dicts from a .bib file (handles missing cite-keys)."""
    txt = path.read_text(errors="ignore")
    blocks = re.split(r"\n(?=@)", txt.strip())
    entries = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        tm = re.match(r"@(\w+)\{([^,\n]*)", block)
        if not tm:
            continue
        etype = tm.group(1).lower()
        key = tm.group(2).strip()
        has_doi = bool(re.search(r"^\s*doi\s*=", block, re.M | re.I))
        has_isbn = bool(re.search(r"^\s*isbn\s*=", block, re.M | re.I))
        title_m = re.search(r"^\s*title\s*=\s*\{(.*?)\}", block, re.M | re.I | re.S)
        title = title_m.group(1)[:120].replace("\n", " ").strip() if title_m else ""
        year_m = re.search(r"^\s*year\s*=\s*\{?(\d{4})", block, re.M | re.I)
        year = year_m.group(1) if year_m else ""
        author_m = re.search(r"^\s*author\s*=\s*\{(.*?)\}", block, re.M | re.I | re.S)
        author = author_m.group(1)[:100].replace("\n", " ").strip() if author_m else ""

        # Extract PDF paths from file= field
        file_m = re.search(r"^\s*file\s*=\s*\{(.*?)\}", block, re.M | re.I | re.S)
        pdfs: list[Path] = []
        if file_m:
            for segment in file_m.group(1).split(";"):
                cols = segment.split(":")
                fp_str = (cols[1] if len(cols) >= 3 else cols[-1]).strip()
                if fp_str.lower().endswith(".pdf"):
                    fp = Path(fp_str)
                    if fp.exists():
                        pdfs.append(fp)

        entries.append({
            "type":     etype,
            "key":      key,
            "title":    title,
            "year":     year,
            "author":   author,
            "has_doi":  has_doi,
            "has_isbn": has_isbn,
            "pdfs":     pdfs,
        })
    return entries


# ---------------------------------------------------------------------------
# bib-ocr runner
# ---------------------------------------------------------------------------

def _run_bib_ocr(pdf: Path, verbose: bool = False) -> dict:
    """Run bib-ocr pipeline on a single PDF.  Returns raw pipeline result."""
    try:
        from bib_ocr.pipeline import extract
    except ImportError:
        return {"error": "bib-ocr not installed", "citations": [], "stages_run": []}
    try:
        return extract(str(pdf), min_hits=3, verbose=verbose)
    except Exception as exc:
        return {"error": str(exc), "citations": [], "stages_run": []}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

_DOI_RE = re.compile(r"\b10\.\d{4,9}/", re.ASCII)

def _classify_citations(citations: list[dict]) -> dict:
    n_doi_direct   = 0
    n_doi_inferred = 0
    n_text_only    = 0
    stages: dict[str, int] = {}

    for c in citations:
        doi = c.get("doi") or ""
        stage = c.get("stage") or "unknown"
        stages[stage] = stages.get(stage, 0) + 1
        if _DOI_RE.search(doi):
            if stage in ("link_crawl", "doi_scan"):
                n_doi_direct += 1
            else:
                n_doi_inferred += 1
        elif c.get("text"):
            n_text_only += 1

    return {
        "n_total":        len(citations),
        "n_doi_direct":   n_doi_direct,
        "n_doi_inferred": n_doi_inferred,
        "n_text_only":    n_text_only,
        "stages":         stages,
    }


# ---------------------------------------------------------------------------
# Main eval loop
# ---------------------------------------------------------------------------

def eval_bib(bib_path: Path, verbose: bool, quiet: bool) -> Iterator[dict]:
    entries = _parse_bib(bib_path)
    bib_name = bib_path.name

    no_doi_with_pdf = [e for e in entries if not e["has_doi"] and e["pdfs"]]
    total = len(entries)
    n_no_doi = sum(1 for e in entries if not e["has_doi"])

    if not quiet:
        print(f"\n{bib_name}: {total} entries, {n_no_doi} no-DOI, "
              f"{len(no_doi_with_pdf)} no-DOI with PDF", flush=True)

    for e in no_doi_with_pdf:
        pdf = e["pdfs"][0]
        label = e["key"] or e["title"][:40] or "(unknown)"

        if not quiet:
            print(f"  {label} ({e['year']}) … ", end="", flush=True)

        t0 = time.perf_counter()
        result = _run_bib_ocr(pdf, verbose=verbose)
        elapsed = time.perf_counter() - t0

        if "error" in result:
            if not quiet:
                print(f"ERROR: {result['error']}")
            yield {"bib": bib_name, "key": e["key"], "title": e["title"],
                   "year": e["year"], "pdf": str(pdf), "error": result["error"]}
            continue

        metrics = _classify_citations(result.get("citations", []))
        stages_run = result.get("stages_run", [])

        if not quiet:
            parts = [
                f"{metrics['n_total']} cites",
                f"{metrics['n_doi_direct']} direct-DOI",
            ]
            if metrics["n_doi_inferred"]:
                parts.append(f"{metrics['n_doi_inferred']} inferred-DOI")
            if metrics["n_text_only"]:
                parts.append(f"{metrics['n_text_only']} text-only")
            parts.append(f"[{'+'.join(stages_run) or 'none'}]")
            parts.append(f"{elapsed:.1f}s")
            print("  ".join(parts))

        yield {
            "bib":          bib_name,
            "key":          e["key"],
            "type":         e["type"],
            "title":        e["title"],
            "author":       e["author"],
            "year":         e["year"],
            "pdf":          str(pdf),
            "stages_run":   stages_run,
            "elapsed_s":    round(elapsed, 2),
            **metrics,
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Run bib-ocr on no-DOI entries from Zotero .bib files and report extraction quality."
    )
    ap.add_argument("bibs", nargs="*", help=".bib file(s) to evaluate")
    ap.add_argument("--bib-dir", type=Path, help="Directory of .bib files (scans recursively)")
    ap.add_argument("--out", type=Path, help="JSONL output path (stdout if omitted)")
    ap.add_argument("--verbose", action="store_true", help="Pass verbose=True to bib-ocr pipeline")
    ap.add_argument("--quiet",   action="store_true", help="Suppress progress output (only JSONL)")
    args = ap.parse_args(argv)

    bib_paths: list[Path] = [Path(b) for b in args.bibs]
    if args.bib_dir:
        bib_paths += sorted(args.bib_dir.glob("**/*.bib"))

    if not bib_paths:
        ap.error("provide at least one .bib file or --bib-dir")

    out_fh = open(args.out, "w") if args.out else None
    total_records = 0

    for bib_path in bib_paths:
        if not bib_path.exists():
            print(f"[skip] {bib_path}: not found", file=sys.stderr)
            continue
        for record in eval_bib(bib_path, verbose=args.verbose, quiet=args.quiet):
            total_records += 1
            line = json.dumps(record, ensure_ascii=False)
            if out_fh:
                out_fh.write(line + "\n")
            elif args.quiet:
                print(line)

    if out_fh:
        out_fh.close()
        print(f"\n{total_records} record(s) → {args.out}")
    elif not args.quiet:
        print(f"\n{total_records} record(s) evaluated")


if __name__ == "__main__":
    main()
