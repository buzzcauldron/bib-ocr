"""
Reference-density analysis for PDF OCR targeting.

Builds a (pages × vertical_bands) heat map of citation-marker frequency using
only fast pymupdf text extraction (no OCR). The map lets the pipeline target
Tesseract on the specific pages/regions where references actually are, rather
than blindly scanning a fixed tail window.

Section titles that trigger a modest per-page heat boost (“References”,
“Bibliography”, “Works cited”, chapter-prefixed lines, multilingual variants,
TOC rows with trailing page numbers, …) are defined alongside the
reference-section line detector in ``bib_ocr.section_heads``.

Usage
-----
    from bib_ocr.density import page_density, target_pages, render_heatmap

    dm = page_density("paper.pdf")        # ndarray (n_pages, bands=10)
    hot = target_pages(dm)                # [page indices to OCR]
    render_heatmap(dm, "density.png")     # optional PNG (requires matplotlib)
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

# Citation markers detected for density scoring
_CITATION_RE = re.compile(
    r"(?:"
    r"\b10\.[0-9]{4,}/[^\s\"'<>,;)\]\s]{3,}"  # bare DOI
    r"|(?<!\w)\[\s*\d{1,3}\s*\]"               # numeric bracket ref [1]
    r"|\b[A-Z][a-z]{1,20}"
    r"(?:\s+(?:et\s+al\.?|and|&)\s+[A-Z][a-z]{1,20})?"
    r"\s*[\(\[]\s*\d{4}\s*[\)\]]"              # Author (YYYY)
    r"|[†‡§¶]"                                  # footnote symbols
    r")",
    re.UNICODE,
)

from bib_ocr.section_heads import SECTION_HEADER_DENSITY_RE


def page_density(
    pdf_path: str | Path,
    bands: int = 10,
) -> np.ndarray:
    """
    Return a float32 array of shape (n_pages, bands) counting citation markers
    per vertical band on each page.

    bands=10 gives 10% vertical slices; increase for finer resolution.
    """
    try:
        import fitz
    except ImportError:
        raise ImportError("pymupdf required: pip install pymupdf")

    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    n = len(doc)
    arr = np.zeros((n, bands), dtype=np.float32)

    for i, page in enumerate(doc):
        page_h = page.rect.height or 1.0
        # get_text("blocks") → (x0, y0, x1, y1, text, block_no, block_type)
        for block in page.get_text("blocks"):
            if block[6] != 0:  # skip non-text (images)
                continue
            text = block[4]
            y_center = (block[1] + block[3]) / 2.0
            band_idx = min(int(y_center / page_h * bands), bands - 1)
            arr[i, band_idx] += len(_CITATION_RE.findall(text))

        # bonus score for pages that contain a section header
        page_text = page.get_text()
        if SECTION_HEADER_DENSITY_RE.search(page_text):
            arr[i, :] += 3.0

    doc.close()
    return arr


def target_pages(
    density: np.ndarray,
    *,
    threshold_fraction: float = 0.10,
    min_signal: float = 1.0,
    margin: int = 1,
) -> list[int]:
    """
    Return sorted 0-based page indices whose citation density is worth OCR-ing.

    threshold_fraction: pages scoring above this fraction of the max score qualify.
    min_signal:         absolute floor — pages below this are never hot.
    margin:             include this many pages before/after each hot page.
    """
    page_scores: np.ndarray = density.sum(axis=1)
    threshold = max(min_signal, float(page_scores.max()) * threshold_fraction)
    hot: set[int] = set()
    for i, s in enumerate(page_scores):
        if s >= threshold:
            for offset in range(-margin, margin + 1):
                j = i + offset
                if 0 <= j < len(page_scores):
                    hot.add(j)
    return sorted(hot)


def ref_section_start(density: np.ndarray) -> int:
    """
    Heuristic: return the first page index of the likely reference section —
    the last contiguous high-density run at the tail of the document.
    """
    page_scores: np.ndarray = density.sum(axis=1)
    if page_scores.max() == 0:
        return max(0, len(page_scores) - 4)

    threshold = float(page_scores.max()) * 0.15
    hot_pages = [i for i, s in enumerate(page_scores) if s >= threshold]
    if not hot_pages:
        return max(0, len(page_scores) - 4)

    # Walk backward from the last hot page to find the start of the tail run
    last = hot_pages[-1]
    start = last
    for p in reversed(hot_pages):
        if last - p <= 3:  # allow small gaps (table-of-contents, etc.)
            start = p
            last = p
        else:
            break
    return start


def ref_section_end_exclusive(density: np.ndarray, ref_header_page: int) -> int:
    """
    First page index *after* the contiguous bibliography pocket, inferred from heatmap totals.

    After the References header page, bibliography pages retain elevated citation-marker
    density while appendix / proofs usually drop toward zero — but we ``max`` peak over a
    short window anchored at the header (not globally) so a mid-document spike does not raise
    the floor to the heavens.

    If density is unreliable (no signal), returns ``len(scores)`` so callers fall back to
    scanning remaining pages — pair with text heuristics (appendix headings) downstream.
    """
    scores: np.ndarray = density.sum(axis=1)
    n = len(scores)
    if ref_header_page < 0 or ref_header_page >= n:
        return n

    lookahead = min(32, max(8, n - ref_header_page))
    window = scores[ref_header_page : ref_header_page + lookahead]
    peak = float(window.max())
    if peak <= 1e-6:
        return n

    floor = max(1.25, peak * 0.06)

    end_exclusive = ref_header_page + 1
    for i in range(ref_header_page, n):
        s = float(scores[i])
        if s >= floor:
            end_exclusive = i + 1
            continue
        # First weak page ends the bibliography run (appendices are usually sparse here).
        if i > ref_header_page:
            break

    return min(end_exclusive, n)


def render_heatmap(
    density: np.ndarray,
    output_path: str | Path | None = None,
    *,
    title: str = "Reference citation density",
) -> None:
    """
    Render the density map as a heat map image.

    output_path: save PNG here if given; otherwise show interactively.
    Requires matplotlib: pip install matplotlib
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
    except ImportError:
        raise ImportError("matplotlib required for heatmap rendering: pip install matplotlib")

    n_pages, bands = density.shape
    fig, (ax_map, ax_bar) = plt.subplots(
        1, 2,
        figsize=(max(6, n_pages * 0.25), 4),
        gridspec_kw={"width_ratios": [n_pages, 1], "wspace": 0.05},
    )

    vmax = float(density.max()) or 1.0
    norm = mcolors.PowerNorm(gamma=0.5, vmin=0, vmax=vmax)
    im = ax_map.imshow(
        density.T,
        aspect="auto",
        cmap="YlOrRd",
        norm=norm,
        origin="upper",
        interpolation="nearest",
    )
    ax_map.set_xlabel("Page (0-indexed)")
    ax_map.set_ylabel("Vertical band (top → bottom)")
    ax_map.set_title(title)

    # Right-side bar: per-page total
    page_totals = density.sum(axis=1)
    ax_bar.barh(range(bands), [0] * bands, color="none")  # invisible placeholder
    ax_bar.set_visible(False)

    # Add a simple line overlay showing page totals
    ax2 = ax_map.twinx()
    ax2.plot(range(n_pages), page_totals, color="steelblue", linewidth=1.2, alpha=0.7, label="page total")
    ax2.set_ylabel("Page total", color="steelblue", fontsize=8)
    ax2.tick_params(axis="y", labelcolor="steelblue", labelsize=7)

    plt.colorbar(im, ax=ax_map, fraction=0.02, pad=0.01, label="markers/band")
    plt.tight_layout()

    if output_path:
        fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()
