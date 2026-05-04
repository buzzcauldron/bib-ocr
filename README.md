# bib-ocr

Bibliography-oriented PDF citation extractor. Runs a five-stage citation cascade whenever
each stage's ``max_stage`` allows (defaults to all five — no ``min_hits`` early exit). **Integrated into**
[Research Party](https://github.com/buzzcauldron/research-party) as compile **Step 2.0 / 2.1**
(`pack_compiler` + `cli/bib_ocr_adapter.py`) when this package is installed and a `--pdf-dir`
(or auto-resolved PDF folder) contains PDFs.

## Research Party install

```bash
# Standalone (any venv):
pip install "bib-ocr @ git+https://github.com/buzzcauldron/bib-ocr.git"

# From a Research Party checkout (installs this package + PDF stack):
pip install -e ".[bib_ocr]"
```

Research Party also needs **system** Tesseract + Poppler (same as below). Optional PNG density
heatmaps in the compile log use matplotlib: `pip install -e ".[viz]"` here, or add `matplotlib`
on the RP side. Web/server: set **`RESEARCH_PARTY_PDF_DIR`** to a shared PDF library, or place
PDFs in a `pdfs/` folder next to the `.bib` — see RP `cli/pdf_dir_infer.py`.

## Pipeline

There is **no** ``min_hits`` early exit: after stages **1–2**, **ref_section**, **footnote_scan**, and
**inline_crawl** run whenever ``max_stage`` permits (default **5** — full cascade). Cap work with Python
(`extract(..., max_stage=n)`) or CLI (`bib-ocr --max-stage n`). Research Party forwards
**``RESEARCH_PARTY_BIB_OCR_MAX_STAGE``**.

**Stages 1 and 2** both run whenever ``max_stage`` ≥ ``2``. Overlap dedupes: ``link_crawl`` omits DOIs already seen from plaintext regex.

| Stage | Method | When it runs |
|-------|--------|-------------|
| 1. `doi_scan` | Regex scan raw pypdf text for `10.XXXX/` patterns | When ``max_stage`` ≥ ``1`` (unless capped) |
| 2. `link_crawl` | PDF hyperlink annotations → DOIs (pymupdf); skips dois already hit in stage 1 | When ``max_stage`` ≥ ``2`` (together with stage 1) |
| 3. `ref_section` | Detect bibliography header; OCR with Tesseract where pypdf is sparse | When ``max_stage`` ≥ ``3`` |
| 4. `footnote_scan` | OCR bottom band on density-targeted pages | When ``max_stage`` ≥ ``4`` |
| 5. `inline_crawl` | Parenthetical, narrative, numeric-bracket inline citations | When ``max_stage`` ≥ ``5`` |

Stages **3–4** anchor on citation-density heuristics **target_pages** / **ref_section_start** — useful for locating reference blocks and footnote lanes on heterogeneous PDFs. Recognized bibliography headings (including **Bibliography**, **References**, **Works cited**, multilingual variants, ``Chapter N …`` / TOC page numbers, and hierarchical outline numbers such as ``3.2 …``) live in **`bib_ocr/section_heads.py`** — shared between the density heat-map boost and **`ref_section`** header stripping.

## Tests

```bash
pip install -e ".[dev]"
pytest -q
```

Pipeline orchestration is covered with **mocked stages** (no real PDF/OCR). Full PDF tests are optional local runs.

## Install

```bash
pip install -e ".[dev]"
# Also requires system Tesseract:
# macOS:  brew install tesseract poppler
# Ubuntu: apt install tesseract-ocr poppler-utils
```

## Usage

```python
from bib_ocr import extract

result = extract("paper.pdf", verbose=True)
for c in result["citations"]:
    print(c["stage"], c.get("doi") or c.get("text", "")[:80])
```

```bash
bib-ocr paper.pdf --verbose
bib-ocr paper.pdf --max-stage 2   # plaintext DOIs + hyperlinks only
```

## Sources

See [SOURCES.md](SOURCES.md) for full upstream attribution.

Key sources:
- [witchofthewires/biblio](https://github.com/witchofthewires/biblio) — Tesseract preprocessing pipeline
- [shravanxd/bibliographies-nlp-avra](https://github.com/shravanxd/bibliographies-nlp-avra) — bibliography parsing architecture
- Research Party `bib_pdf_ocr.py` / `inline_citation_extractor.py` — OCR cache, footnote-band, inline extractors
- InterPARES Trust AI OCR bibliography — preprocessing guidance
