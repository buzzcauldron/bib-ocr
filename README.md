# bib-ocr

Bibliography-oriented PDF citation extractor. Runs a five-stage cascade, stopping
as soon as enough citations are found. Designed to be ported into
[Research Party](https://github.com/buzzcauldron/research-party) once stable.

## Pipeline

| Stage | Method | When it runs |
|-------|--------|-------------|
| 1. `link_crawl` | PDF hyperlink annotations → DOIs (pymupdf) | Always first |
| 2. `doi_scan` | Regex scan raw text for unlinked `10.XXXX/` patterns | Stage 1 < min_hits |
| 3. `ref_section` | Detect bibliography section header; OCR with Tesseract if pypdf yields sparse text | Stage 2 < min_hits |
| 4. `footnote_scan` | OCR bottom 28% band of each page | Stage 3 < min_hits |
| 5. `inline_crawl` | Parenthetical, narrative, numeric-bracket inline citations | Stage 4 < min_hits (last resort) |

Stage 5 is a last resort. Papers almost always have a reference list — if
stages 1–4 all fail the PDF is likely image-only and needs better scan quality.

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
bib-ocr paper.pdf --max-stage 2   # hyperlinks + DOI scan only
```

## Sources

See [SOURCES.md](SOURCES.md) for full upstream attribution.

Key sources:
- [witchofthewires/biblio](https://github.com/witchofthewires/biblio) — Tesseract preprocessing pipeline
- [shravanxd/bibliographies-nlp-avra](https://github.com/shravanxd/bibliographies-nlp-avra) — bibliography parsing architecture
- Research Party `bib_pdf_ocr.py` / `inline_citation_extractor.py` — OCR cache, footnote-band, inline extractors
- InterPARES Trust AI OCR bibliography — preprocessing guidance
