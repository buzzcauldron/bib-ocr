"""
arXiv + local PDF bibliography extraction evaluation.

Sources of papers:
  1. arXiv  — digital PDFs, ground truth via Semantic Scholar references API
  2. Local   — PDFs from JSTOR, Zotero, or any directory; ground truth from
               a paired .json sidecar or auto-fetched from S2 by DOI

Usage
-----
  # arXiv only (default)
  python arxiv_eval.py --n 100 --workers 16 --out results.jsonl

  # Mix arXiv + local directory (JSTOR exports, Zotero attachments, etc.)
  python arxiv_eval.py --n 50 --local-dir ~/Zotero/storage --workers 16

  # Local only
  python arxiv_eval.py --n 0 --local-dir ~/Downloads/jstor_pdfs --workers 16

Ground truth for local PDFs
----------------------------
  Place a JSON sidecar next to each PDF with the same stem:
    paper.pdf  →  paper.json  {"doi": "10.xxxx/...", "references": ["10.a/b", ...]}
  If no sidecar exists, the evaluator tries to resolve the PDF's own DOIs via S2.

Requirements (pip install --user --break-system-packages)
----------------------------------------------------------
  pymupdf pypdf pdf2image pillow pytesseract requests tqdm arxiv
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import requests as _requests

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

S2_REFS_URL  = "https://api.semanticscholar.org/graph/v1/paper/{paper_id}/references"
OA_WORKS_URL = "https://api.openalex.org/works"
ARXIV_PDF    = "https://arxiv.org/pdf/{arxiv_id}"

# mailto param improves OA rate limits (polite pool: 10 req/s vs 100 req/min)
_OA_MAILTO: str = "tvv125@gmail.com"
_OA_BATCH  = 50   # max openalex_id filters per /works request

_SESSION = _requests.Session()
_SESSION.headers["User-Agent"] = "bib-ocr-eval/0.1 (research; mailto:tvv125@gmail.com)"

# ---------------------------------------------------------------------------
# arXiv paper sampling
# ---------------------------------------------------------------------------

def _arxiv_ids(n: int, categories: list[str], year: int | None = None) -> list[str]:
    if n <= 0:
        return []
    ids: list[str] = []
    per_cat = max(1, (n + len(categories) - 1) // len(categories))
    for cat in categories:
        # Restrict to a specific year so S2 has had time to index references.
        # arXiv date filter: submittedDate:[YYYYMMDD TO YYYYMMDD]
        if year:
            query = f"cat:{cat} AND submittedDate:[{year}0101 TO {year}1231]"
        else:
            query = f"cat:{cat}"
        url = (
            "https://export.arxiv.org/api/query?"
            + urllib.parse.urlencode({
                "search_query": query,
                "start": 0,
                "max_results": per_cat,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            })
        )
        try:
            import xml.etree.ElementTree as ET
            with urllib.request.urlopen(url, timeout=20) as r:
                tree = ET.fromstring(r.read())
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for entry in tree.findall("a:entry", ns):
                id_elem = entry.find("a:id", ns)
                id_url = (id_elem.text or "") if id_elem is not None else ""
                arxiv_id = id_url.strip("/").split("/")[-1]
                if arxiv_id and arxiv_id not in ids:
                    ids.append(arxiv_id)
                    if len(ids) >= n:
                        return ids
        except Exception as e:
            print(f"  [arxiv] {cat}: {e}", file=sys.stderr)
    return ids[:n]


# ---------------------------------------------------------------------------
# Ground truth via Semantic Scholar
# ---------------------------------------------------------------------------

def _s2_dois_for_arxiv(arxiv_id: str) -> set[str]:
    # Strip version suffix (v1, v2, …) — S2 uses the bare ID
    bare = re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)
    return _s2_dois(f"arXiv:{bare}")


def _s2_dois_for_doi(doi: str) -> set[str]:
    return _s2_dois(f"DOI:{doi}")


def _s2_dois(paper_id: str) -> set[str]:
    url = S2_REFS_URL.format(paper_id=urllib.parse.quote(paper_id, safe=":/"))
    for attempt in range(2):
        try:
            r = _SESSION.get(url, params={"fields": "externalIds"}, timeout=15)
            if r.status_code == 429:
                time.sleep(5)
                continue
            if not r.ok:
                return set()
            data = r.json()
            break
        except Exception:
            return set()
    else:
        return set()
    dois: set[str] = set()
    for ref in data.get("data") or []:
        ext = (ref.get("citedPaper") or {}).get("externalIds") or {}
        doi = (ext.get("DOI") or "").strip().lower()
        if doi:
            dois.add(doi)
    return dois


# ---------------------------------------------------------------------------
# Ground truth via OpenAlex (good coverage of recent papers)
# ---------------------------------------------------------------------------

def _oa_params() -> dict:
    return {"mailto": _OA_MAILTO} if _OA_MAILTO else {}


def _oa_dois_for_arxiv(arxiv_id: str) -> set[str]:
    """Return reference DOIs for an arXiv paper via OpenAlex referenced_works."""
    bare = re.sub(r"v\d+$", "", arxiv_id, flags=re.IGNORECASE)
    doi  = f"10.48550/arXiv.{bare}"
    return _oa_dois_for_doi(doi)


def _oa_dois_for_doi(doi: str) -> set[str]:
    """Return reference DOIs for any paper by DOI via OpenAlex referenced_works."""
    doi = doi.strip().lower().lstrip("https://doi.org/")
    if not doi:
        return set()
    try:
        r = _SESSION.get(
            OA_WORKS_URL,
            params={**_oa_params(), "filter": f"doi:{doi}",
                    "select": "referenced_works"},
            timeout=15,
        )
        if not r.ok:
            return set()
        results = r.json().get("results") or []
        if not results:
            return set()
        w_ids: list[str] = results[0].get("referenced_works") or []
    except Exception:
        return set()

    if not w_ids:
        return set()

    # Batch-resolve W-IDs → DOIs
    dois: set[str] = set()
    for i in range(0, len(w_ids), _OA_BATCH):
        batch = w_ids[i : i + _OA_BATCH]
        id_param = "|".join(w.split("/")[-1] for w in batch)
        try:
            rb = _SESSION.get(
                OA_WORKS_URL,
                params={**_oa_params(), "filter": f"openalex_id:{id_param}",
                        "select": "doi", "per_page": _OA_BATCH},
                timeout=15,
            )
            if not rb.ok:
                continue
            for item in rb.json().get("results") or []:
                d = (item.get("doi") or "").strip().lower()
                d = re.sub(r"^https?://doi\.org/", "", d)
                if d:
                    dois.add(d)
        except Exception:
            continue
    return dois


# ---------------------------------------------------------------------------
# PDF download (arXiv)
# ---------------------------------------------------------------------------

def _download_arxiv_pdf(arxiv_id: str, dest: Path) -> Path | None:
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
# Local PDF ground truth
# ---------------------------------------------------------------------------

def _local_ground_truth(pdf_path: Path) -> set[str]:
    """
    Try sidecar JSON first, then fall back to scanning the PDF itself for a DOI
    and fetching their references from S2 + OpenAlex (union).

    OA is the primary source for published papers (journals/conferences) since
    it has near-complete reference lists for those.  S2 fills gaps for preprints.
    """
    sidecar = pdf_path.with_suffix(".json")
    if sidecar.exists():
        try:
            data = json.loads(sidecar.read_text())
            # Sidecar may carry the paper's own DOI so we can also hit OA
            own_doi = (data.get("doi") or "").strip().lower()
            refs = set(data.get("references") or [])
            if own_doi:
                refs |= _oa_dois_for_doi(own_doi)
                refs |= _s2_dois_for_doi(own_doi)
            return {r.strip().lower() for r in refs if r.strip()}
        except Exception:
            pass

    # No sidecar — extract the paper's own DOI from the PDF and query both APIs
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        doi_re = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>,;)]+)")
        for page in doc:
            for link in page.get_links():
                uri = link.get("uri") or ""
                m = doi_re.search(uri)
                if m:
                    doi = m.group(1).rstrip(".,;)")
                    return _oa_dois_for_doi(doi) | _s2_dois_for_doi(doi)
        doc.close()
    except Exception:
        pass
    return set()


# ---------------------------------------------------------------------------
# Per-paper eval (runs in subprocess)
# ---------------------------------------------------------------------------

def _eval_one(args: tuple[str, str, str, list[str]]) -> dict:
    """
    args: (kind, identifier, pdf_path_str, ground_truth_doi_list)
      kind:             "arxiv" | "local"
      identifier:       arxiv_id OR original pdf path string (for labelling)
      pdf_path_str:     absolute path to the already-downloaded PDF
      ground_truth_dois: list of normalised DOI strings (fetched in main process)

    Network calls (S2, PDF download) are done in the main process so that SSL
    cert configuration is consistent.  Workers only run bib-ocr extraction.
    """
    kind, identifier, pdf_path_str, ground_truth_doi_list = args
    ground_truth = set(ground_truth_doi_list)

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from bib_ocr.pipeline import extract as _extract

    pdf_path = Path(pdf_path_str)
    if not pdf_path.exists():
        return {"kind": kind, "id": identifier, "error": "pdf_not_found"}

    try:
        result = _extract(str(pdf_path), min_hits=3, verbose=False)
    except Exception as exc:
        return {"kind": kind, "id": identifier, "error": str(exc)}

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

    stage_counts: dict[str, int] = {}
    for c in result["citations"]:
        s = c.get("stage", "unknown")
        stage_counts[s] = stage_counts.get(s, 0) + 1

    return {
        "kind": kind,
        "id": identifier,
        "pdf": str(pdf_path),
        "stages_run": result["stages_run"],
        "stage_counts": stage_counts,
        "n_extracted": len(extracted_dois),
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
    def avg(key: str, subset=good) -> float:
        return sum(r[key] for r in subset) / len(subset) if subset else 0.0

    def group(kind: str) -> list[dict]:
        return [r for r in good if r.get("kind") == kind]

    stage_use: dict[str, int] = {}
    for r in good:
        for s, c in (r.get("stage_counts") or {}).items():
            stage_use[s] = stage_use.get(s, 0) + c

    out: dict = {
        "n_papers": len(good),
        "n_errors": len(results) - len(good),
        "avg_precision": round(avg("precision"), 4),
        "avg_recall":    round(avg("recall"),    4),
        "avg_f1":        round(avg("f1"),        4),
        "stage_hit_counts": stage_use,
    }
    for kind in ("arxiv", "local"):
        sub = group(kind)
        if sub:
            out[f"{kind}_avg_f1"] = round(avg("f1", sub), 4)
            out[f"{kind}_n"]      = len(sub)
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    global _OA_MAILTO
    ap = argparse.ArgumentParser(description="Evaluate bib-ocr against arXiv + local PDFs")
    ap.add_argument("--n",          type=int,   default=50,
                    help="Number of arXiv papers (0 = local only)")
    ap.add_argument("--workers",    type=int,   default=8)
    ap.add_argument("--out",        default="results.jsonl")
    ap.add_argument("--pdf-dir",    default="pdfs",
                    help="Cache dir for arXiv PDF downloads")
    ap.add_argument("--local-dir",  default=None,
                    help="Directory of local PDFs (JSTOR, Zotero, etc.)")
    ap.add_argument("--categories", nargs="+",
                    default=["cs.IR", "cs.CL", "cs.DL", "econ.GN", "stat.ML"],
                    help="arXiv subject categories")
    ap.add_argument("--year",       type=int,   default=2023,
                    help="Sample papers from this year so S2 has indexed their refs (default: 2023)")
    ap.add_argument("--gt-source",  default="both",
                    choices=["s2", "oa", "both"],
                    help="Ground-truth source: s2 (Semantic Scholar), oa (OpenAlex), "
                         "or both (union — best coverage, default)")
    ap.add_argument("--oa-mailto",  default=_OA_MAILTO,
                    help="Email for OpenAlex polite pool (faster rate limits)")
    args = ap.parse_args()

    _OA_MAILTO = args.oa_mailto

    pdf_dir = Path(args.pdf_dir)
    pdf_dir.mkdir(exist_ok=True)

    # ---- Phase 1: collect paper list and prefetch ground truth + PDFs ----
    # All network calls happen here in the main process so SSL certs are
    # consistent.  Workers receive a ready (pdf_path, ground_truth_doi_list)
    # pair and only run bib-ocr — no network needed in subprocesses.

    # (kind, identifier, pdf_path_str, ground_truth_doi_list)
    tasks: list[tuple[str, str, str, list[str]]] = []

    # arXiv papers
    if args.n > 0:
        print(f"Sampling {args.n} arXiv papers from: {', '.join(args.categories)} (year={args.year})")
        ids = _arxiv_ids(args.n, args.categories, year=args.year)
        print(f"  Got {len(ids)} IDs")
        gt_note = {"s2": "S2", "oa": "OA (note: OA refs sparse for bare arXiv preprints)", "both": "S2+OA"}[args.gt_source]
        print(f"  Downloading PDFs + fetching ground truth ({gt_note}) …")
        for i, aid in enumerate(ids, 1):
            pdf_path = _download_arxiv_pdf(aid, pdf_dir)
            if pdf_path is None:
                print(f"    [{i}/{len(ids)}] {aid} — download failed, skipping")
                continue
            gt: set[str] = set()
            counts: list[str] = []
            if args.gt_source in ("s2", "both"):
                s2 = _s2_dois_for_arxiv(aid)
                gt |= s2
                counts.append(f"s2={len(s2)}")
            if args.gt_source in ("oa", "both"):
                oa = _oa_dois_for_arxiv(aid)
                gt |= oa
                counts.append(f"oa={len(oa)}")
            print(f"    [{i}/{len(ids)}] {aid} — {' '.join(counts)}  union={len(gt)}")
            tasks.append(("arxiv", aid, str(pdf_path), list(gt)))

    # Local PDFs (JSTOR, Zotero, etc.)
    if args.local_dir:
        local_pdfs = sorted(Path(args.local_dir).glob("**/*.pdf"))
        print(f"Found {len(local_pdfs)} local PDFs in {args.local_dir}")
        for p in local_pdfs:
            # _local_ground_truth already uses sidecar → S2; augment with OA when doi known
            gt: set[str] = set(_local_ground_truth(p))
            tasks.append(("local", str(p), str(p), list(gt)))

    if not tasks:
        print("No papers to evaluate. Use --n or --local-dir.")
        return

    # ---- Phase 2: parallel bib-ocr extraction ----
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_eval_one, t): t for t in tasks}
        done = 0
        for fut in as_completed(futures):
            done += 1
            t = futures[fut]
            kind, identifier = t[0], t[1]
            label = Path(identifier).name if kind == "local" else identifier
            try:
                r = fut.result()
            except Exception as exc:
                r = {"kind": kind, "id": identifier, "error": str(exc)}
            results.append(r)
            status = f"f1={r.get('f1','?')} [{r.get('kind','')}]" if "error" not in r else f"ERR:{r['error'][:50]}"
            print(f"  [{done}/{len(tasks)}] {label} — {status}")

    out_path = Path(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"\nResults → {out_path}")

    agg = _aggregate(results)
    print("\n── Aggregate ──────────────────────────────")
    for k, v in agg.items():
        print(f"  {k}: {v}")

    summary_path = out_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(agg, indent=2))
    print(f"Summary → {summary_path}")


if __name__ == "__main__":
    main()
