# Source Material

This package is derived from and informed by the following sources.
All upstream code is MIT/unspecified-open licensed unless noted.

---

## Direct Code Sources

### witchofthewires/biblio
- URL: https://github.com/witchofthewires/biblio
- What it provides: PIL image preprocessing pipeline (invert, contrast ×2, psm 6)
  and parenthetical-citation regex for Tesseract OCR of scanned bibliography images.
- Ported into: `bib_ocr/preprocessing.py`, `bib_ocr/stages/ref_section.py`
- License: not stated (used as reference implementation)

### shravanxd/bibliographies-nlp-avra
- URL: https://github.com/shravanxd/bibliographies-nlp-avra
- What it provides: Architecture for LLM-assisted bibliography parsing — chunked
  text (~15 k chars), schema-validated JSON output, unicode sanitization.
- Ported into: `bib_ocr/bibliography_nlp.py` (schema + chunking strategy; local
  NLP replaces the OpenAI API dependency)
- License: not stated (used as reference implementation)

### Research Party — bib_pdf_ocr.py
- URL: https://github.com/buzzcauldron/research-party (private)
- Path: `cli/bib_pdf_ocr.py`
- What it provides: per-page OCR cache, pypdf→tesseract fallback, footnote-band
  image OCR, author-year pattern matching, bracket-key map, OpenAlex resolution.
- Ported into: `bib_ocr/stages/footnote_scan.py`, `bib_ocr/cache.py`,
  `bib_ocr/resolve.py`
- License: project-private

### Research Party — inline_citation_extractor.py
- URL: https://github.com/buzzcauldron/research-party (private)
- Path: `cli/inline_citation_extractor.py`
- What it provides: parenthetical, narrative, numeric-bracket, MLA, classics,
  Chicago footnote, ibid/op-cit state machine extractors.
- Ported into: `bib_ocr/stages/inline_crawl.py`
- License: project-private

---

## Reference / Background Material

### InterPARES Trust AI — Bibliography of OCR (2021–2026)
- URL: https://interparestrustai.org/assets/public/dissemination/BibliographyofOCR.pdf
- What it covers: Survey of OCR error correction techniques, AI-enhanced
  transcription for archival records, challenges in scanned document text quality.
- Informed: preprocessing decisions and confidence thresholds in
  `bib_ocr/preprocessing.py`.

---

## Key Dependencies

| Package | Role |
|---------|------|
| `pymupdf` (fitz) | PDF parsing, hyperlink annotation extraction (Stage 2) |
| `pypdf` | Fallback text extraction (Stages 1, 3–4) |
| `pytesseract` | OCR engine wrapper (Stages 3–4) |
| `pdf2image` | PDF page → PIL image for Tesseract (Stage 3–4) |
| `Pillow` | Image preprocessing (invert, contrast, rotate) |
| `regex` | DOI and citation pattern matching |
| `bibtexparser` | BibTeX output serialization |
