"""
arXiv bibliography extraction evaluation.

Downloads PDFs from arXiv, fetches known references via Semantic Scholar,
runs the bib-ocr pipeline, and scores each stage.

Usage
-----
  python arxiv_eval.py --n 100 --workers 16 --out results.jsonl
  python arxiv_eval.py --n 100 --workers 16 --out results.jsonl --categories cs.IR cs.DL

Requirements (pip install --user)
----------------------------------
  arxiv pymupdf pypdf pdf2image pillow pytesseract bibtexparser requests tqdm
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import requests

# Allow running from repo root
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from bib_ocr.pipeline import extract as bib_extract

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

S2_API = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}"
S2_REFS = "https://api.semanticscholar.org/graph/v1/paper/arXiv:{arxiv_id}/references"
S2_FIELDS = "references.externalIds,references.title"
ARXIV_PDF = "https://arxiv.org/pdf/{arxiv_id}"

_SESSION = requests.Session()
_SESSION.headers["User-Agent"] = "bib-ocr-eval/0.1 (research; mailto:tvv125@gmail.com)"

# ---------------------------------------------------------------------------
# arXiv paper sampling
# ---------------------------------------------------------------------------

def _arxiv_ids(n: int, categories: list[str]) -> list[str]:
    """
    Return n arXiv IDs by querying the arXiv search API.
    Spreads across provided categories.
    """
    import urllib.parse, urllib.request, xml.etree.ElementTree as ET

    ids: list[str] = []
    per_cat = max(1, (n + len(categories) - 1) // len(categories))
    for cat in categories:
        url = (
            "https://export.arxiv.org/api/query?"
            + urllib.parse.urlencode({
                "search_query": f"cat:{cat}",
                "start": 0,
                "max_results": per_cat,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            })
        )
        try:
            with urllib.request.urlopen(url, timeout=20) as r:
                tree = ET.fromstring(r.read())
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for entry in tree.findall("a:entry", ns):
                id_url = (entry.find("a:id", ns) or object()).text or ""
                arxiv_id = id_url.strip("/").split("/")[-1]
                if arxiv_id and arxiv_id not in ids:
                    ids.append(arxiv_id)
                    if len(ids) >= n:
                        return ids
        except Exception as e:
            print(f"  [arxiv] {cat}: {e}", file=sys.stderr)
    return ids[:n]


# ---------------------------------------------------------------------------
# Ground truth: Semantic Scholar references
# ---------------------------------------------------------------------------

def _s2_dois(arxiv_id: str) -> set[str]:
    """Return set of DOIs for a paper's references via Semantic Scholar."""
    url = S2_REFS.format(arxiv_id=arxiv_id)
    try:
        r = _SESSION.get(url, params={"fields": "externalIds"}, timeout=15)
        if r.status_code == 429:
            time.sleep(5)
            r = _SESSION.get(url, params={"fields": "externalIds"}, timeout=15)
        if not r.ok:
            return set()
        data = r.json()
    except Exception:
        return set()
    dois: set[str] = set()
    for ref in data.get("data") or []:
        ext = (ref.get("citedPaper") or {}).get("externalIds") or {}
        doi = (ext.get("DOI") or "").strip().lower()
        if doi:
            dois.add(doi)
    return dois


# ---------------------------------------------------------------------------
# PDF download
# ---------------------------------------------------------------------------

def _download_pdf(arxiv_id: str, dest: Path) -> Path | None:
    pdf_path = dest / f"{arxiv_id.replace('/', '_')}.pdf"
    if pdf_path.exists():
        return pdf_path
    url = ARXIV_PDF.format(arxiv_id=arxiv_id)
    try:
        r = _SESSION.get(url, timeout=60, stream=True)
        if not r.ok:
            return None
        with open(pdf_path, "wb") as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)
        return pdf_path
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Per-paper evaluation (runs in subprocess)
# ---------------------------------------------------------------------------

def _eval_one(args: tuple[str, str]) -> dict:
    """
    Download, extract, and score one arXiv paper.
    Returns a result dict suitable for JSONL output.
    Runs in a worker process — reimports pipeline fresh.
    """
    arxiv_id, pdf_dir = args

    from bib_ocr.pipeline import extract as _extract

    pdf_path = _download_pdf(arxiv_id, Path(pdf_dir))
    if pdf_path is None:
        return {"arxiv_id": arxiv_id, "error": "download_failed"}

    try:
        result = _extract(str(pdf_path), min_hits=3, verbose=False)
    except Exception as exc:
        return {"arxiv_id": arxiv_id, "error": str(exc)}

    ground_truth = _s2_dois(arxiv_id)
    extracted_dois = {
        (c.get("doi") or "").strip().lower().lstrip("https://doi.org/")
        for c in result["citations"]
        if c.get("doi")
    }

    tp = len(extracted_dois & ground_truth)
    fp = len(extracted_dois - ground_truth)
    fn = len(ground_truth - extracted_dois)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall    = tp / (tp + fn) if (tp + fn) else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    stage_counts = {}
    for c in result["citations"]:
        s = c.get("stage", "unknown")
        stage_counts[s] = stage_counts.get(s, 0) + 1

    return {
        "arxiv_id":      arxiv_id,
        "pdf":           str(pdf_path),
        "stages_run":    result["stages_run"],
        "stage_counts":  stage_counts,
        "n_extracted":   len(extracted_dois),
        "n_ground_truth": len(ground_truth),
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 4),
        "recall":    round(recall,    4),
        "f1":        round(f1,        4),
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _aggregate(results: list[dict]) -> dict:
    good = [r for r in results if "error" not in r]
    if not good:
        return {}
    total = len(good)
    avg = lambda key: sum(r[key] for r in good) / total
    stage_use: dict[str, int] = {}
    for r in good:
        for s, c in (r.get("stage_counts") or {}).items():
            stage_use[s] = stage_use.get(s, 0) + c
    return {
        "n_papers":       total,
        "n_errors":       len(results) - total,
        "avg_precision":  round(avg("precision"), 4),
        "avg_recall":     round(avg("recall"),    4),
        "avg_f1":         round(avg("f1"),        4),
        "stage_hit_counts": stage_use,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Evaluate bib-ocr against arXiv ground truth")
    ap.add_argument("--n",          type=int,   default=50,  help="Number of papers to evaluate")
    ap.add_argument("--workers",    type=int,   default=8,   help="Parallel workers")
    ap.add_argument("--out",        default="results.jsonl", help="Output JSONL path")
    ap.add_argument("--pdf-dir",    default="pdfs",         help="Directory for cached PDFs")
    ap.add_argument("--categories", nargs="+",
                    default=["cs.IR", "cs.CL", "cs.DL", "econ.GN", "stat.ML"],
                    help="arXiv subject categories to sample from")
    args = ap.parse_args()

    pdf_dir = Path(args.pdf_dir)
    pdf_dir.mkdir(exist_ok=True)

    print(f"Sampling {args.n} papers from: {', '.join(args.categories)}")
    ids = _arxiv_ids(args.n, args.categories)
    print(f"Got {len(ids)} paper IDs")

    tasks = [(arxiv_id, str(pdf_dir)) for arxiv_id in ids]
    results: list[dict] = []

    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_eval_one, t): t[0] for t in tasks}
        done = 0
        for fut in as_completed(futures):
            done += 1
            arxiv_id = futures[fut]
            try:
                r = fut.result()
            except Exception as exc:
                r = {"arxiv_id": arxiv_id, "error": str(exc)}
            results.append(r)
            status = f"f1={r.get('f1','?')}" if "error" not in r else f"ERR:{r['error'][:40]}"
            print(f"  [{done}/{len(tasks)}] {arxiv_id} — {status}")

    # Write JSONL
    out_path = Path(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nResults → {out_path}")

    agg = _aggregate(results)
    print("\n── Aggregate ──────────────────────────────")
    for k, v in agg.items():
        print(f"  {k}: {v}")

    # Also write aggregate summary
    summary_path = out_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(agg, indent=2))
    print(f"Summary → {summary_path}")


if __name__ == "__main__":
    main()
