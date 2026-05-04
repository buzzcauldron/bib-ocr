"""
bib-ocr: Bibliography-oriented PDF citation extractor.

Five-stage cascade (each stage only runs if the previous yielded < min_hits):

  1. link_crawl    — PDF hyperlink annotations → DOIs/URLs (zero OCR, instant)
  2. doi_scan      — regex scan raw text for unlinked DOI patterns
  3. ref_section   — detect and OCR the bibliography / references section
  4. footnote_scan — OCR footnote bands across all pages
  5. inline_crawl  — last resort: inline parenthetical / numeric citations

See SOURCES.md for upstream attribution.
"""

from .pipeline import extract  # noqa: F401

__version__ = "0.1.0"
