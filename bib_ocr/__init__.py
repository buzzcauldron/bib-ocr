"""
bib-ocr: Bibliography-oriented PDF citation extractor.

Five-stage cascade. Stages ``doi_scan`` and ``link_crawl`` **both** run whenever
``max_stage`` ≥ 2; denser stages **ref_section**, **footnote_scan**, and **inline_crawl**
also run whenever ``max_stage`` allows (no ``min_hits`` early exit).

  1. doi_scan       — regex scan raw pypdf text for ``10.…`` DOIs (plaintext layer first)
  2. link_crawl    — PDF hyperlink annotations → DOIs/URLs (pymupdf; skips dois from step 1)
  3. ref_section   — detect and OCR the bibliography / references section
  4. footnote_scan — OCR footnote bands across all pages
  5. inline_crawl  — last resort: inline parenthetical / numeric citations

See SOURCES.md for upstream attribution.
"""

from .pipeline import extract  # noqa: F401
from .density import page_density, target_pages, ref_section_start, render_heatmap  # noqa: F401

__version__ = "0.1.6"
